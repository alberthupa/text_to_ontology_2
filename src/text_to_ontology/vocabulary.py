"""The starter vocabulary: the classes and relationships ingestion may use.

The starter ontology declares every class, relation, and fact. In data-only
mode ingestion may add individuals and their statements, but it may never add
or change a class or a relationship. This module reads that declared
vocabulary out of a graph so the validation gate can lock it, and so merge
policy knows not to declare anything again.

Nothing here writes to a graph.
"""

from dataclasses import dataclass, field

from rdflib import BNode, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .graph_management import FACT, RELATION
from .graph_merge import class_uri, slug


def _declared(graph, rdf_type):
    """Every named subject of one rdf:type, as {IRI text: readable name}."""
    names = {}
    for subject in graph.subjects(RDF.type, rdf_type):
        if isinstance(subject, BNode):
            continue
        label = graph.value(subject, RDFS.label)
        names[str(subject)] = str(label) if label is not None else str(subject)
    return names


@dataclass(frozen=True)
class Vocabulary:
    """The frozen starter vocabulary, keyed by resource IRI.

    The starter is the naming authority for ingestion: a candidate says
    `kind: "Bike"` or `predicate: "made by"`, and the vocabulary decides which
    class or property IRI that is. A starter written by the model lives under
    the project's `class:` / `relation:` / `fact:` namespaces; an imported RDF
    file keeps its own IRIs, and ingestion still uses them, which is what makes
    an import usable instead of a dead end. Matching is by the same slug rule
    the generated IRIs use, so spelling and case do not matter.
    """

    classes: dict
    relations: dict
    facts: dict
    # property IRI text -> class IRI text, as the starter declares them
    domains: dict = field(default_factory=dict)
    ranges: dict = field(default_factory=dict)
    # class IRI text -> the IRIs of its declared parent classes
    parents: dict = field(default_factory=dict)

    # ---------- matching by name ----------

    def class_iri(self, kind):
        """The declared class IRI for this kind, or the generated one."""
        return self._match(self.classes, class_uri(kind), kind)

    def relation_iri(self, predicate):
        """The declared property IRI for this relation."""
        return self._match(self.relations, RELATION[slug(predicate)], predicate)

    def fact_iri(self, predicate):
        """The declared property IRI for this fact."""
        return self._match(self.facts, FACT[slug(predicate)], predicate)

    def declares_class(self, kind):
        """True when this kind's class IRI was declared by the starter."""
        return str(self.class_iri(kind)) in self.classes

    def declares_relation(self, predicate):
        """True when this relation's property IRI was declared."""
        return str(self.relation_iri(predicate)) in self.relations

    def declares_fact(self, predicate):
        """True when this fact's property IRI was declared."""
        return str(self.fact_iri(predicate)) in self.facts

    @staticmethod
    def _match(declared, generated, name):
        """The declared IRI whose name folds to this one, or the generated IRI.

        The generated IRI wins when it was declared; otherwise a declared label
        (or a declared IRI's own local name) that folds to the same slug wins,
        which is how an imported vocabulary keeps its own IRIs.
        """
        if str(generated) in declared:
            return generated
        wanted = slug(name)
        for iri, label in declared.items():
            if slug(label) == wanted or slug(local_name(iri)) == wanted:
                return URIRef(iri)
        return generated

    # ---------- domains and ranges ----------

    def is_a(self, class_iri, wanted_iri):
        """True when a class is the wanted class or one of its subclasses."""
        pending, seen = [str(class_iri)], set()
        while pending:
            current = pending.pop()
            if current == str(wanted_iri):
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self.parents.get(current, ()))
        return False

    def domain_of(self, property_iri):
        """The declared domain class IRI of a property, or None."""
        return self.domains.get(str(property_iri))

    def range_of(self, property_iri):
        """The declared range class IRI of a relation, or None."""
        return self.ranges.get(str(property_iri))

    def label_of(self, iri):
        """The readable name of a declared class or property."""
        for declared in (self.classes, self.relations, self.facts):
            if str(iri) in declared:
                return declared[str(iri)]
        return local_name(iri)

    @property
    def class_names(self):
        return sorted(self.classes.values())

    @property
    def relation_names(self):
        return sorted(self.relations.values())

    @property
    def fact_names(self):
        return sorted(self.facts.values())

    @property
    def is_empty(self):
        return not (self.classes or self.relations or self.facts)


def local_name(iri):
    """The last path or fragment piece of an IRI."""
    text = str(iri)
    for separator in ("#", "/"):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    return text or str(iri)


def read_vocabulary(graph):
    """The declared classes, relations, and facts of one graph."""
    classes = _declared(graph, OWL.Class)
    classes.update(_declared(graph, RDFS.Class))
    relations = _declared(graph, OWL.ObjectProperty)
    facts = _declared(graph, OWL.DatatypeProperty)
    domains, ranges = {}, {}
    for prop in list(relations) + list(facts):
        domain = graph.value(URIRef(prop), RDFS.domain)
        if isinstance(domain, URIRef):
            domains[prop] = str(domain)
        target = graph.value(URIRef(prop), RDFS.range)
        if prop in relations and isinstance(target, URIRef):
            ranges[prop] = str(target)
    parents = {}
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef):
            parents.setdefault(str(child), set()).add(str(parent))
    return Vocabulary(
        classes=classes,
        relations=relations,
        facts=facts,
        domains=domains,
        ranges=ranges,
        parents={child: tuple(sorted(found))
                 for child, found in parents.items()},
    )
