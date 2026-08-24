"""The graph-store boundary: named graphs behind one small, replaceable API.

Domain modules see only the `GraphStore` contract - get/put/delete one named
graph, focused SPARQL query/update, and one atomic `publish` operation. They
never open files, parse Turtle, or know whether the store is local or remote.

`RdflibGraphStore` is the local adapter: an rdflib Dataset in memory, kept
durable by serializing the whole dataset and atomically replacing one TriG
file. A failed publication leaves both the file and the in-memory dataset
exactly as they were.

This module is also the import/export boundary of the application:

    import_legacy_turtle   the explicit migration path from the combined
                           legacy ontology.ttl into configured named graphs;
    export_graph_turtle    one named graph as human-readable Turtle;
    export_dataset         the whole dataset as TriG or N-Quads.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from rdflib import Dataset, Graph, URIRef
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID

from .graph_partition import partition_graph


@dataclass
class Publication:
    """Everything one atomic publication changes.

    `graphs` replaces the named graphs' complete contents; `deletions`
    removes whole named graphs. Anything not mentioned stays untouched.
    """

    graphs: dict = field(default_factory=dict)
    deletions: tuple = ()


class GraphStore(Protocol):
    """How domain modules touch graphs. Nothing more is allowed."""

    def get(self, name) -> Graph:
        """An isolated copy of one named graph; empty when it does not exist."""

    def put(self, name, graph):
        """Replace one named graph's content with `graph`, in memory."""

    def delete(self, name):
        """Remove one named graph entirely, in memory."""

    def graph_names(self) -> list:
        """Every named graph currently present."""

    def query(self, sparql, **bindings):
        """Run a read-only SPARQL query over all named graphs at once."""

    def update(self, sparql, **bindings):
        """Run one SPARQL Update operation over all named graphs."""

    def publish(self, publication=None):
        """Persist everything so far, plus this bundle, as one atomic step."""


def _apply(dataset, publication):
    """Put and delete exactly what the publication names."""
    for name, graph in publication.graphs.items():
        name = URIRef(name)
        dataset.remove((None, None, None, name))
        for subject, predicate, object_ in graph:
            dataset.add((subject, predicate, object_, name))
    for name in publication.deletions:
        name = URIRef(name)
        dataset.remove((None, None, None, name))
        # Removing the last triple does not drop the context itself.
        dataset.store.remove_graph(name)


class RdflibGraphStore:
    """The local adapter: an rdflib Dataset, optionally persisted as TriG."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.dataset = Dataset(default_union=True)
        if self.path and self.path.exists():
            self.dataset.parse(self.path, format="trig")

    def get(self, name):
        copy = Graph()
        for triple in self.dataset.triples((None, None, None, URIRef(name))):
            copy.add(triple)
        return copy

    def put(self, name, graph):
        _apply(self.dataset, Publication(graphs={URIRef(name): graph}))

    def delete(self, name):
        _apply(self.dataset, Publication(deletions=(name,)))

    def graph_names(self):
        """Every named graph that currently holds at least one triple."""
        return sorted(
            context.identifier for context in self.dataset.contexts()
            if isinstance(context.identifier, URIRef)
            and context.identifier != DATASET_DEFAULT_GRAPH_ID
            and len(context) > 0
        )

    def query(self, sparql, **bindings):
        return self.dataset.query(sparql, initBindings=bindings or None)

    def update(self, sparql, **bindings):
        self.dataset.update(sparql, initBindings=bindings or None)

    def publish(self, publication=None):
        """Write through a serialized clone first; failure changes nothing."""
        prospective = self._clone_with(publication)
        if self.path is not None:
            _atomic_write(prospective, self.path)
        if publication is not None:
            _apply(self.dataset, publication)

    def _clone_with(self, publication):
        clone = Dataset()
        for subject, predicate, object_, name in self.dataset.quads((None, None, None, None)):
            if name != DATASET_DEFAULT_GRAPH_ID:
                clone.add((subject, predicate, object_, name))
        if publication is not None:
            _apply(clone, publication)
        return clone


def _atomic_write(dataset, path):
    """Serialize to a temporary sibling, then replace atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = str(path) + ".tmp"
    try:
        dataset.serialize(temporary, format="trig")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class ReadOnlyGraphStore:
    """A wrapper that exposes only the reading half of the contract."""

    def __init__(self, store):
        self._store = store

    def get(self, name):
        return self._store.get(name)

    def graph_names(self):
        return self._store.graph_names()

    def query(self, sparql, **bindings):
        return self._store.query(sparql, **bindings)


BASE_NAMESPACE = "http://example.org/text-ontology/"


@dataclass
class GraphNames:
    """Which named graph plays which role. Validated in one place."""

    schema_graphs: list = field(
        default_factory=lambda: [URIRef(BASE_NAMESPACE + "graphs/schema")])
    shape_graphs: list = field(
        default_factory=lambda: [URIRef(BASE_NAMESPACE + "graphs/shapes")])
    data_graphs: list = field(default_factory=list)
    target_graph: URIRef = URIRef(BASE_NAMESPACE + "graphs/data")
    provenance_graph: URIRef = URIRef(BASE_NAMESPACE + "graphs/provenance")
    review_graph: URIRef = URIRef(BASE_NAMESPACE + "graphs/review")
    staging_namespace: str = BASE_NAMESPACE + "staging/"

    def validate(self):
        """Fail loudly on duplicate roles or an unusable staging namespace."""
        single = [self.target_graph, self.provenance_graph, self.review_graph]
        every = [str(name) for name in
                 single + self.schema_graphs + self.shape_graphs
                 + self.data_graphs]
        if len(set(every)) != len(every):
            duplicated = sorted(
                name for name in set(every) if every.count(name) > 1)
            raise ValueError(
                f"Graph names must be unique across roles: {duplicated}")
        if not self.staging_namespace.endswith(("/", "#")):
            raise ValueError("staging_namespace must end with '/' or '#'")

    def source_staging_graph(self, document_id):
        """The staging graph name for one source document."""
        return URIRef(f"{self.staging_namespace}{document_id}")


def import_legacy_turtle(store, path, names):
    """Import the combined legacy ontology.ttl into configured named graphs.

    The existing partitioner decides where each triple belongs: schema
    structure into the schema graph, instance data into the target graph,
    and support material (ontology header, shapes, audit records, anything
    unclassified) into the provenance graph. Nothing is dropped.
    """
    legacy = Graph()
    legacy.parse(path, format="turtle")
    schema, instance, support = partition_graph(legacy)
    store.publish(Publication(graphs={
        names.schema_graphs[0]: schema,
        names.target_graph: instance,
        names.provenance_graph: support,
    }))
    return {"schema": len(schema), "instance": len(instance),
            "support": len(support)}


def export_graph_turtle(store, name):
    """One named graph as human-readable Turtle text."""
    return store.get(name).serialize(format="turtle")


def export_dataset(store, fmt="trig"):
    """The complete dataset as TriG or N-Quads text."""
    if fmt not in ("trig", "nquads"):
        raise ValueError("format must be 'trig' or 'nquads'")
    dataset = Dataset()
    for name in store.graph_names():
        for subject, predicate, object_ in store.get(name):
            dataset.add((subject, predicate, object_, URIRef(name)))
    return dataset.serialize(format=fmt)
