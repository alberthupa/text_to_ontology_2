"""Source links (src:) in the data graph, tracing (trace:) elsewhere."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.namespace import OWL, PROV, RDF, RDFS

from text_to_ontology.api import RunRequest
from text_to_ontology.graph_management import (
    CLASS, ENTITY, FACT, ONTO, RELATION, SRC, TRACE, is_tracing,
)
from text_to_ontology.graph_partition import partition_graph
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.pipeline import ProcessingConfig
from text_to_ontology.publication_sources import statement_uri
from tests.test_pipeline_m7 import CountingStore, FakeExtractor, entity, run


def response(confidence=0.9):
    return {
        "entities": [entity("a", "Alice", "Person"),
                     entity("b", "Acme", "Company")],
        "relations": [{"subject": "a", "predicate": "works for",
                       "object": "b", "confidence": confidence}],
        "facts": [{"subject": "a", "predicate": "age", "value": 30,
                   "confidence": confidence}],
    }


WORKS_FOR = (ENTITY.alice, RELATION["works-for"], ENTITY.acme)
AGE = (ENTITY.alice, FACT.age, Literal(30))


def file_paths(data, resource):
    """The src:path of every file a resource or statement came from."""
    return {str(data.value(file, SRC.path))
            for file in data.objects(resource, SRC.fromFile)}


class SourceAttributionTest(unittest.TestCase):
    def test_entities_relations_and_facts_name_their_files(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "out.trig"
            sources = []
            for number, confidence in ((1, 0.9), (2, 0.7)):
                source = root / f"{number}.txt"
                source.write_text(f"Source {number}: Alice works for Acme.")
                sources.append(source.as_posix())
                run(RunRequest(source=source, graph_path=path),
                    FakeExtractor(response(confidence)), CountingStore(path))
            data = RdflibGraphStore(path).get(names.target_graph)
        for resource in (ENTITY.alice, ENTITY.acme):
            self.assertEqual(file_paths(data, resource), set(sources))
        for triple in (WORKS_FOR, AGE):
            node = statement_uri(triple)
            self.assertEqual((data.value(node, RDF.subject),
                              data.value(node, RDF.predicate),
                              data.value(node, RDF.object)), triple)
            self.assertEqual(file_paths(data, node), set(sources))
        labels = {str(data.value(file, RDFS.label))
                  for file in data.subjects(RDF.type, SRC.SourceFile)}
        self.assertEqual(labels, {"1.txt", "2.txt"})
        # Classes and properties are the starter's, not the texts'.
        for resource in (CLASS.person, RELATION["works-for"], FACT.age,
                         ONTO.Entity):
            self.assertFalse(list(data.objects(resource, SRC.fromFile)))

    def test_one_file_node_per_path_even_when_its_content_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            store = CountingStore()
            for number in (1, 2):
                source.write_text(f"Version {number} about Alice.")
                run(RunRequest(source=source, graph_path=root / "out.trig"),
                    FakeExtractor(response()), store)
        data = store.get(GraphNames().target_graph)
        self.assertEqual(len(set(data.objects(ENTITY.alice, SRC.fromFile))), 1)
        # The two content versions are run history: two trace documents.
        provenance = store.get(GraphNames().provenance_graph)
        self.assertEqual(
            len(set(provenance.objects(ENTITY.alice, TRACE.sourceDocument))), 2)

    def test_same_file_name_in_different_folders_keeps_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CountingStore()
            paths = [root / part / "notes.txt" for part in ("a", "b")]
            for path in paths:
                path.parent.mkdir()
                path.write_text("Alice works for Acme.")
                run(RunRequest(source=path, graph_path=root / "out.trig"),
                    FakeExtractor(response()), store)
        data = store.get(GraphNames().target_graph)
        self.assertEqual(file_paths(data, ENTITY.alice),
                         {path.as_posix() for path in paths})

    def test_withheld_claims_get_no_source_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CountingStore()
            for number in (1, 2):
                source = root / f"{number}.txt"
                source.write_text(f"Source {number} about Alice.")
                package = response()
                if number == 2:
                    package["relations"][0]["confidence"] = 0.2
                    package["relations"][0]["predicate"] = "might join"
                    package["facts"][0].update(value=99, confidence=0.2)
                    package["entities"].append(
                        entity("c", "Uncertain", "Risk", 0.2))
                run(RunRequest(source=source, graph_path=root / "out.trig"),
                    FakeExtractor(package), store)
        data = store.get(GraphNames().target_graph)
        self.assertEqual(len(file_paths(data, statement_uri(AGE))), 1)
        self.assertFalse(list(data.triples(
            (statement_uri((ENTITY.alice, FACT.age, Literal(99))), None, None))))
        review = store.get(GraphNames().review_graph)
        statements = list(review.subjects(RDF.type, RDF.Statement))
        self.assertTrue(statements)
        for statement in statements:
            self.assertTrue(str(statement).startswith(str(TRACE)))
            self.assertTrue(list(review.objects(statement, TRACE.sourceFile)))


class TracingTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "1.txt"
        self.source.write_text("Alice works for Acme.")

    def ingest(self, trace):
        store = CountingStore()
        run(RunRequest(source=self.source, graph_path=self.root / "out.trig",
                       processing=ProcessingConfig(trace=trace)),
            FakeExtractor(response()), store)
        return store

    def test_candidates_are_kept_only_with_trace(self):
        names = GraphNames()
        without = self.ingest(False).get(names.provenance_graph)
        with_trace = self.ingest(True).get(names.provenance_graph)
        candidate = str(TRACE) + "candidate/"
        self.assertFalse(any(str(s).startswith(candidate)
                             for s in without.subjects()))
        self.assertTrue(any(str(s).startswith(candidate)
                            for s in with_trace.subjects()))
        self.assertGreater(len(with_trace), len(without))

    def test_business_data_is_the_same_with_or_without_trace(self):
        names = GraphNames()
        self.assertEqual(set(self.ingest(False).get(names.target_graph)),
                         set(self.ingest(True).get(names.target_graph)))

    def test_every_prov_and_dqv_triple_is_tracing(self):
        store = self.ingest(True)
        for name in store.graph_names():
            for triple in store.get(name):
                if str(triple[1]).startswith((str(PROV), "http://www.w3.org/ns/dqv#")) \
                        or str(triple[2]).startswith(str(PROV)):
                    self.assertTrue(is_tracing(triple), triple)

    def test_filtering_trace_leaves_only_business_and_source_links(self):
        store = self.ingest(True)
        allowed = (str(ONTO), str(OWL), str(RDF), str(RDFS),
                   "http://www.w3.org/2004/02/skos/core#",
                   "http://www.w3.org/ns/shacl#")
        names = GraphNames()
        for name in (names.target_graph, *names.schema_graphs):
            for triple in store.get(name):
                if is_tracing(triple):
                    continue
                for term in triple[:2]:
                    self.assertTrue(str(term).startswith(allowed), triple)
                    self.assertFalse(str(term).startswith(str(TRACE)), triple)

    def test_source_links_are_support_when_graphs_are_combined(self):
        graph = Graph()
        graph.add((ENTITY.alice, RDF.type, ONTO.Entity))
        graph.add((ONTO.Entity, RDF.type, OWL.Class))
        links = [(ENTITY.alice, SRC.fromFile, SRC["file/x"]),
                 (ENTITY.alice, TRACE.sourceDocument, TRACE["document/x"])]
        for link in links:
            graph.add(link)
        schema, instance, support = partition_graph(graph)
        for link in links:
            self.assertIn(link, support)
            self.assertNotIn(link, instance)
            self.assertNotIn(link, schema)


if __name__ == "__main__":
    unittest.main()
