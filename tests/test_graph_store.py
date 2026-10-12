"""Milestone 3: the local RDF dataset store, its contract, and its boundary."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, SH

from text_to_ontology.graph_store import (
    GraphNames,
    Publication,
    RdflibGraphStore,
    export_dataset,
    export_graph_turtle,
    import_legacy_turtle,
)
from text_to_ontology.graph_management import open_graph

from store_contract import ReadOnlyRules, StoreContract, Terms, pair_graph

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY = FIXTURES / "miniature_repository.ttl"


class InMemoryStoreTest(StoreContract, ReadOnlyRules, unittest.TestCase):
    """The same contract, with no file behind it."""

    def make_store(self):
        return RdflibGraphStore()


class PersistedStoreTest(StoreContract, unittest.TestCase):
    """The same contract with durability added."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "dataset.trig"
        self.store = self.make_store()

    def make_store(self):
        return RdflibGraphStore(path=self.path)

    def test_contents_survive_reopening(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.publish()
        reopened = RdflibGraphStore(path=self.path)
        self.assertTrue(isomorphic(
            reopened.get(Terms.named), pair_graph(Terms.alice, Terms.bob)))
        self.assertEqual(reopened.graph_names(), [Terms.named])

    def test_a_failed_publication_keeps_the_previous_file_and_memory(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.publish()
        good_bytes = self.path.read_bytes()

        broken = pair_graph(Terms.bob, Terms.carol)
        with unittest.mock.patch.object(
                Graph, "serialize", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                self.store.publish(
                    Publication(graphs={Terms.other: broken}))

        # The file still holds the previous dataset...
        self.assertEqual(self.path.read_bytes(), good_bytes)
        self.assertFalse(Path(str(self.path) + ".tmp").exists())
        # ...and the in-memory store is untouched and fully usable.
        self.assertEqual(len(self.store.get(Terms.other)), 0)
        self.store.update(
            f"INSERT DATA {{ GRAPH <{Terms.named}> {{ "
            f"<{Terms.carol}> <{Terms.knows}> <{Terms.alice}> }} }}")
        self.store.publish()
        reopened = RdflibGraphStore(path=self.path)
        self.assertIn((Terms.carol, Terms.knows, Terms.alice),
                      reopened.get(Terms.named))


class ExportRoundTripTest(unittest.TestCase):
    """Turtle per graph; TriG and N-Quads for the complete dataset."""

    def setUp(self):
        self.store = RdflibGraphStore()
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.put(Terms.other, pair_graph(Terms.bob, Terms.carol))

    def reimported(self, text, fmt):
        fresh = RdflibGraphStore()
        fresh.dataset.parse(data=text, format=fmt)
        return fresh

    def test_one_named_graph_exports_as_turtle_and_round_trips(self):
        turtle = export_graph_turtle(self.store, Terms.named)
        reparsed = Graph()
        reparsed.parse(data=turtle, format="turtle")
        self.assertTrue(isomorphic(reparsed, pair_graph(Terms.alice, Terms.bob)))

    def round_trip_case(self, fmt):
        text = export_dataset(self.store, fmt)
        fresh = self.reimported(text, fmt)
        self.assertEqual(sorted(map(str, fresh.graph_names())),
                         sorted(map(str, self.store.graph_names())))
        for name in self.store.graph_names():
            self.assertTrue(isomorphic(fresh.get(name), self.store.get(name)),
                            f"graph {name} changed through {fmt}")

    def test_the_complete_dataset_round_trips_through_trig(self):
        self.round_trip_case("trig")

    def test_the_complete_dataset_round_trips_through_nquads(self):
        self.round_trip_case("nquads")

    def test_unknown_export_formats_are_rejected(self):
        with self.assertRaises(ValueError):
            export_dataset(self.store, "turtle")


class LegacyImportTest(unittest.TestCase):
    """AC5: the combined ontology.ttl migrates into named graphs losslessly."""

    def test_every_legacy_triple_lands_in_exactly_one_configured_graph(self):
        legacy = open_graph(LEGACY)
        names = GraphNames()
        names.validate()
        store = RdflibGraphStore()
        counts = import_legacy_turtle(store, LEGACY, names)

        self.assertEqual(
            sum(counts.values()), len(legacy),
            "the three role graphs must together hold every source triple")
        combined = Graph()
        for name in store.graph_names():
            for triple in store.get(name):
                combined.add(triple)
        self.assertTrue(isomorphic(combined, legacy))

    def test_each_role_lands_where_the_configuration_says(self):
        names = GraphNames()
        store = RdflibGraphStore()
        counts = import_legacy_turtle(store, LEGACY, names)

        self.assertGreater(counts["schema"], 0)
        self.assertGreater(len(store.get(names.schema_graphs[0])), 0)
        self.assertGreater(len(store.get(names.target_graph)), 0)

    def test_seed_shapes_become_provenance_support_material(self):
        names = GraphNames()
        store = RdflibGraphStore()
        import_legacy_turtle(store, LEGACY, names)
        shapes = list(store.get(names.provenance_graph).triples(
            (None, RDF.type, SH.NodeShape)))
        self.assertTrue(shapes)


class GraphNamesTest(unittest.TestCase):
    """AC3: explicit roles, validated in one place."""

    def test_defaults_are_valid_and_distinct(self):
        names = GraphNames()
        names.validate()
        roles = {names.target_graph, names.provenance_graph, names.review_graph}
        self.assertEqual(len(roles), 3)
        self.assertEqual(names.schema_graphs[0], URIRef(
            "http://example.org/text-ontology/graphs/schema"))

    def test_duplicate_role_names_are_rejected(self):
        names = GraphNames(target_graph=URIRef("http://example.com/same"),
                           provenance_graph=URIRef("http://example.com/same"))
        with self.assertRaises(ValueError):
            names.validate()

    def test_staging_namespace_must_be_a_namespace(self):
        names = GraphNames(staging_namespace="http://example.com/staging")
        with self.assertRaises(ValueError):
            names.validate()

    def test_source_staging_graph_uses_the_namespace(self):
        names = GraphNames()
        self.assertEqual(
            str(names.source_staging_graph("doc-abc123")),
            "http://example.org/text-ontology/trace/staging/doc-abc123")


class ViewerDatasetTest(unittest.TestCase):
    """T9: the viewer reads named graphs or legacy Turtle, changing nothing."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "dataset.trig"
        store = RdflibGraphStore(path=self.path)
        store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        store.put(Terms.other, pair_graph(Terms.bob, Terms.carol))
        store.publish()
        self.before = self.path.read_bytes()

    def test_the_union_of_named_graphs_is_viewed_without_writing(self):
        from text_to_ontology.view_ontology import load_view_graph
        combined = load_view_graph(self.path)
        self.assertEqual(len(combined), 4)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_one_named_graph_can_be_selected_for_viewing(self):
        from text_to_ontology.view_ontology import load_view_graph
        selected = load_view_graph(self.path, name=str(Terms.other))
        self.assertTrue(isomorphic(selected, pair_graph(Terms.bob, Terms.carol)))
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_legacy_turtle_files_are_still_viewed_directly(self):
        from text_to_ontology.view_ontology import load_view_graph
        turtle_path = Path(self.folder.name) / "legacy.ttl"
        open_graph(LEGACY).serialize(turtle_path, format="turtle")
        viewed = load_view_graph(turtle_path)
        self.assertGreater(len(viewed), 0)


if __name__ == "__main__":
    unittest.main()
