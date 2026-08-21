"""Open, seed, name, and save the one canonical Turtle graph."""

import os

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS


# Change this when you want permanent URIs of your own.
BASE = "http://example.org/text-ontology/"
ONTO = Namespace(BASE)
ENTITY = Namespace(BASE + "entity/")
CLASS = Namespace(BASE + "class/")
RELATION = Namespace(BASE + "relation/")
FACT = Namespace(BASE + "fact/")


def bind(graph):
    for prefix, namespace in {
        "onto": ONTO, "entity": ENTITY, "class": CLASS, "relation": RELATION,
        "fact": FACT, "owl": OWL, "rdf": RDF, "rdfs": RDFS, "sh": SH,
        "skos": SKOS,
    }.items():
        graph.bind(prefix, namespace)


def open_graph(path):
    graph = Graph()
    bind(graph)
    if path.exists():
        graph.parse(path, format="turtle")
        return graph

    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))

    # A tiny SHACL shape: every entity must have a preferred label.
    rule = BNode()
    graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
    graph.add((ONTO.EntityShape, SH.targetClass, ONTO.Entity))
    graph.add((ONTO.EntityShape, SH.property, rule))
    graph.add((rule, SH.path, SKOS.prefLabel))
    graph.add((rule, SH.minCount, Literal(1)))
    return graph


def save_graph(graph, path):
    """Serialize to a temporary sibling file, then replace atomically.

    A failed serialization leaves the previous graph file untouched and
    usable, and never leaves a stale temporary file behind.
    """
    path = str(path)
    temporary = path + ".tmp"
    try:
        graph.serialize(temporary, format="turtle")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
