"""Copy the explicit structural core of a schema graph into a smaller graph.

Only statements the source actually makes are copied. Nothing is inferred: a
property never gains a domain, a class never gains a superclass, and a resource
mentioned only as a range never gains a declaration. Blank-node restrictions are
copied whole or not at all, because half a restriction misleads more than an
absent one.
"""

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS


# Declarations the skeleton keeps.
SKELETON_TYPES = {
    OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
}

# Axioms between two named schema resources.
NAMED_AXIOMS = {RDFS.subClassOf, RDFS.domain, RDFS.range}

# Naming statements kept for every retained resource.
ANNOTATIONS = {
    RDFS.label, RDFS.comment, SKOS.prefLabel, SKOS.altLabel, SKOS.definition,
}

# Decision gate 2: the restriction forms this proposal claims to support.
SUPPORTED_CONSTRAINTS = {
    OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.cardinality,
    OWL.minCardinality, OWL.maxCardinality,
}


def supported_restriction(schema_graph, node):
    """The triples of `node` if it is a complete supported restriction."""
    parts = {}
    for _, predicate, target in schema_graph.triples((node, None, None)):
        parts.setdefault(predicate, []).append(target)
    # Exactly a type, a property, and one constraint. Anything else is a form
    # this proposal has not decided to support.
    if sorted(len(values) for values in parts.values()) != [1, 1, 1]:
        return None
    if parts.get(RDF.type) != [OWL.Restriction]:
        return None
    if OWL.onProperty not in parts:
        return None
    constraint = (set(parts) - {RDF.type, OWL.onProperty}).pop()
    if constraint not in SUPPORTED_CONSTRAINTS:
        return None
    prop, value = parts[OWL.onProperty][0], parts[constraint][0]
    if isinstance(prop, BNode) or isinstance(value, BNode):
        return None
    if constraint in (OWL.cardinality, OWL.minCardinality, OWL.maxCardinality):
        if not isinstance(value, Literal):
            return None
    elif constraint != OWL.hasValue and not isinstance(value, URIRef):
        return None
    return [
        (node, RDF.type, OWL.Restriction),
        (node, OWL.onProperty, prop),
        (node, constraint, value),
    ], {prop, value}


def structural_triples(schema_graph):
    """The retained declarations and axioms, and the resources they name."""
    triples, named = set(), set()
    for subject, _, type_ in schema_graph.triples((None, RDF.type, None)):
        if type_ in SKELETON_TYPES and isinstance(subject, URIRef):
            triples.add((subject, RDF.type, type_))
            named.add(subject)
    for axiom in NAMED_AXIOMS:
        for subject, _, target in schema_graph.triples((None, axiom, None)):
            if isinstance(subject, URIRef) and isinstance(target, URIRef):
                triples.add((subject, axiom, target))
                named |= {subject, target}
    for subject, _, node in schema_graph.triples((None, RDFS.subClassOf, None)):
        if not isinstance(subject, URIRef) or not isinstance(node, BNode):
            continue
        supported = supported_restriction(schema_graph, node)
        if supported is not None:
            parts, referenced = supported
            triples.add((subject, RDFS.subClassOf, node))
            triples.update(parts)
            named.add(subject)
            named |= {term for term in referenced if isinstance(term, URIRef)}
    return triples, named


def create_graph_skeleton(schema_graph):
    """Return the compact explicit class and property structure as a graph."""
    triples, named = structural_triples(schema_graph)
    for resource in named:
        for annotation in ANNOTATIONS:
            for _, _, value in schema_graph.triples((resource, annotation, None)):
                triples.add((resource, annotation, value))

    skeleton = Graph()
    for prefix, namespace in schema_graph.namespaces():
        skeleton.bind(prefix, namespace)
    for triple in triples:
        skeleton.add(triple)
    return skeleton
