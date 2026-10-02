"""The starter vocabulary: the classes and relationships ingestion may use.

The starter ontology declares every class, relation, and fact. In data-only
mode ingestion may add individuals and their statements, but it may never add
or change a class or a relationship. This module reads that declared
vocabulary out of a graph so the validation gate can lock it, and so merge
policy knows not to declare anything again.

Nothing here writes to a graph.
"""

from dataclasses import dataclass

from rdflib import BNode
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
    """The frozen starter vocabulary, keyed by resource IRI."""

    classes: dict
    relations: dict
    facts: dict

    def declares_class(self, kind):
        """True when this kind's class IRI was declared by the starter."""
        return str(class_uri(kind)) in self.classes

    def declares_relation(self, predicate):
        """True when this relation's property IRI was declared."""
        return str(RELATION[slug(predicate)]) in self.relations

    def declares_fact(self, predicate):
        """True when this fact's property IRI was declared."""
        return str(FACT[slug(predicate)]) in self.facts

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


def read_vocabulary(graph):
    """The declared classes, relations, and facts of one graph."""
    classes = _declared(graph, OWL.Class)
    classes.update(_declared(graph, RDFS.Class))
    return Vocabulary(
        classes=classes,
        relations=_declared(graph, OWL.ObjectProperty),
        facts=_declared(graph, OWL.DatatypeProperty),
    )
