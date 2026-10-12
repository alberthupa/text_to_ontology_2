"""Open, seed, name, and save the one canonical Turtle graph."""

import os
from pathlib import Path
from typing import Protocol

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, PROV, RDF, RDFS, SH, SKOS


# Change this when you want permanent URIs of your own.
BASE = "http://example.org/text-ontology/"

# Business data: what the texts say.
ONTO = Namespace(BASE)
ENTITY = Namespace(BASE + "entity/")
CLASS = Namespace(BASE + "class/")
RELATION = Namespace(BASE + "relation/")
FACT = Namespace(BASE + "fact/")

# Source attribution, kept with the business data: which file said it.
#   src:file/<hash>       one node per source file (rdfs:label, src:path)
#   src:statement/<hash>  one relation or fact, with src:fromFile links
SRC = Namespace(BASE + "source/")

# Tracing: how the run got there (candidates, windows, model calls, review).
# Everything under this prefix can be filtered out without losing business
# data: a triple is tracing when its subject or its predicate is in `trace:`.
TRACE = Namespace(BASE + "trace/")

# DQV is not bundled with rdflib's namespace module; it is a W3C vocabulary.
DQV = Namespace("http://www.w3.org/ns/dqv#")


def bind(graph):
    for prefix, namespace in {
        "onto": ONTO, "entity": ENTITY, "class": CLASS, "relation": RELATION,
        "fact": FACT, "src": SRC, "trace": TRACE, "owl": OWL, "rdf": RDF,
        "rdfs": RDFS, "sh": SH, "skos": SKOS, "prov": PROV, "dqv": DQV,
    }.items():
        graph.bind(prefix, namespace)


def is_tracing(triple):
    """Whether one triple is run tracing rather than business data."""
    subject, predicate, _object = triple
    return str(subject).startswith(TRACE) or str(predicate).startswith(TRACE)


def is_source_attribution(triple):
    """Whether one triple says which file something came from."""
    subject, predicate, _object = triple
    return str(subject).startswith(SRC) or str(predicate).startswith(SRC)


def open_graph(path):
    if path.exists():
        graph = Graph()
        bind(graph)
        graph.parse(path, format="turtle")
        return graph

    return seed_graph()


def seed_graph():
    """The small initial ontology and shape graph, without file access."""
    graph = Graph()
    bind(graph)

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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = str(path) + ".tmp"
    try:
        graph.serialize(temporary, format="turtle")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class GraphStore(Protocol):
    """How the pipeline reads one graph in and writes it back out."""

    def load(self, path):
        """Return the graph stored at path, seeding it when absent."""

    def save(self, graph, path):
        """Persist the graph to path atomically."""


class LocalTurtleStore:
    """The default store: one Turtle file with an atomic replace on save."""

    def load(self, path):
        return open_graph(path)

    def save(self, graph, path):
        save_graph(graph, path)
