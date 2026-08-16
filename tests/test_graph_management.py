"""Baseline: graph lifecycle — opening, seeding, and prefix binding."""

import tempfile
import unittest
from pathlib import Path

from rdflib import BNode, Graph, Literal
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS

from ontology import BASE, ONTO, bind, open_graph


def save_graph(graph, path):
    """The serialization the program performs after every source file."""
    graph.serialize(path, format="turtle")


def seed_graph():
    """The structure a brand-new graph is expected to contain."""
    graph = Graph()
    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))
    rule = BNode()
    graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
    graph.add((ONTO.EntityShape, SH.targetClass, ONTO.Entity))
    graph.add((ONTO.EntityShape, SH.property, rule))
    graph.add((rule, SH.path, SKOS.prefLabel))
    graph.add((rule, SH.minCount, Literal(1)))
    return graph


class MissingPathTest(unittest.TestCase):
    """Case 1: opening a missing path creates the base ontology and shape."""

    def test_new_graph_matches_the_seed_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            graph = open_graph(Path(folder) / "absent.ttl")
        self.assertEqual(len(graph), 8)
        self.assertTrue(isomorphic(graph, seed_graph()))

    def test_new_graph_is_not_written_to_disk_by_opening(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "absent.ttl"
            open_graph(path)
            self.assertFalse(path.exists())


class ExistingGraphTest(unittest.TestCase):
    """Case 2: opening an existing Turtle file preserves its triples."""

    def test_existing_triples_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "graph.ttl"
            original = seed_graph()
            original.add((ONTO.Extra, RDF.type, OWL.Class))
            original.add((ONTO.Extra, RDFS.label, Literal("Extra")))
            original.serialize(path, format="turtle")

            reopened = open_graph(path)
        self.assertTrue(isomorphic(reopened, original))

    def test_existing_graph_is_not_reseeded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "graph.ttl"
            small = Graph()
            small.add((ONTO.Extra, RDF.type, OWL.Class))
            small.serialize(path, format="turtle")

            reopened = open_graph(path)
        self.assertEqual(len(reopened), 1)


class BindingTest(unittest.TestCase):
    def test_project_prefixes_are_bound(self):
        graph = Graph()
        bind(graph)
        bound = {prefix: str(uri) for prefix, uri in graph.namespaces()}
        self.assertEqual(bound["onto"], BASE)
        self.assertEqual(bound["entity"], BASE + "entity/")
        self.assertEqual(bound["class"], BASE + "class/")
        self.assertEqual(bound["relation"], BASE + "relation/")
        self.assertEqual(bound["fact"], BASE + "fact/")
        for prefix in ("owl", "rdf", "rdfs", "sh", "skos"):
            self.assertIn(prefix, bound)


class SaveTest(unittest.TestCase):
    """Saving writes Turtle that reloads to the same graph."""

    def test_saved_graph_reloads_identically(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "graph.ttl"
            graph = open_graph(path)
            save_graph(graph, path)
            self.assertTrue(path.exists())
            self.assertTrue(isomorphic(open_graph(path), graph))


if __name__ == "__main__":
    unittest.main()
