"""Data-only ingestion: the starter vocabulary cannot change."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from text_to_ontology.candidate_validation import validate_candidates
from text_to_ontology.graph_management import CLASS, ONTO, RELATION
from text_to_ontology.merge_policy import plan_graph_merge
from text_to_ontology.pipeline import MergeConfig, RunRequest, run_text_to_graph
from text_to_ontology.run_report import RunReporter
from text_to_ontology.starter import starter_publication, validate_starter
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.vocabulary import read_vocabulary


PROPOSAL = validate_starter({
    "classes": [{"name": "Person"}, {"name": "Organization"}],
    "relations": [{"name": "works-for", "domain": "Person",
                   "range": "Organization"}],
    "facts": [{"name": "founded-in", "domain": "Organization",
               "range": "integer"}],
})["candidates"]

DECLARED = {
    "entities": [
        {"id": "e1", "name": "Alice", "kind": "Person", "confidence": 0.9},
        {"id": "e2", "name": "Acme", "kind": "Organization",
         "confidence": 0.9},
    ],
    "relations": [{"subject": "e1", "predicate": "works-for", "object": "e2",
                   "confidence": 0.9}],
    "facts": [{"subject": "e2", "predicate": "founded-in", "value": 1999,
               "confidence": 0.9}],
}

UNDECLARED = {
    "entities": [{"id": "e1", "name": "Widget", "kind": "Product",
                  "confidence": 0.9}],
    "relations": [{"subject": "e1", "predicate": "made-of", "object": "e1",
                   "confidence": 0.9}],
    "facts": [],
}


class FakeExtractor:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def model(self):
        return "fake-model"

    def extract(self, prompt):
        self.calls += 1
        return self.answer


def starter_store(path):
    store = RdflibGraphStore(path=path)
    store.publish(starter_publication(PROPOSAL))
    return store


class ValidationGateTest(unittest.TestCase):
    def setUp(self):
        self.names = GraphNames()
        self.schema = starter_publication(PROPOSAL, self.names) \
            .graphs[self.names.schema_graphs[0]]
        self.vocabulary = read_vocabulary(self.schema)

    def test_declared_kinds_and_predicates_pass(self):
        result = validate_candidates(DECLARED, self.schema, (),
                                     vocabulary=self.vocabulary)
        self.assertTrue(result["valid"], result["issues"])

    def test_an_undeclared_kind_is_an_error_naming_the_vocabulary(self):
        result = validate_candidates(UNDECLARED, self.schema, (),
                                     vocabulary=self.vocabulary)
        self.assertFalse(result["valid"])
        issue = next(issue for issue in result["issues"]
                     if issue["code"] == "entity.undeclared_kind")
        self.assertIn("Person", issue["message"])
        self.assertIn("Organization", issue["message"])

    def test_an_undeclared_predicate_is_an_error(self):
        result = validate_candidates(UNDECLARED, self.schema, (),
                                     vocabulary=self.vocabulary)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("relation.undeclared_predicate", codes)

    def test_without_a_vocabulary_nothing_is_locked(self):
        result = validate_candidates(UNDECLARED, self.schema, ())
        self.assertTrue(result["valid"], result["issues"])


class MergePlanTest(unittest.TestCase):
    def setUp(self):
        self.names = GraphNames()
        self.schema = starter_publication(PROPOSAL, self.names) \
            .graphs[self.names.schema_graphs[0]]

    def plan(self, vocabulary):
        return plan_graph_merge(
            self.schema, DECLARED,
            {"source_path": "note.txt", "source_sha256": "x",
             "model": "fake", "policy_version": 2},
            vocabulary=vocabulary)

    def test_data_only_plan_declares_no_class_or_property(self):
        plan = self.plan(read_vocabulary(self.schema))
        declared = set(self.schema.subjects(RDF.type, OWL.Class)) \
            | set(self.schema.subjects(RDF.type, OWL.ObjectProperty)) \
            | set(self.schema.subjects(RDF.type, OWL.DatatypeProperty))
        talked_about = [triple for triple in plan["domain_triples"]
                        if triple[0] in declared]
        self.assertEqual(talked_about, [])
        self.assertIn((CLASS["person"], RDF.type, OWL.Class), self.schema)

    def test_a_free_plan_still_declares_as_before(self):
        plan = self.plan(None)
        self.assertTrue(any(triple[1] == RDF.type
                            and triple[2] in (OWL.Class, OWL.ObjectProperty,
                                              OWL.DatatypeProperty)
                            for triple in plan["domain_triples"]))


class DataOnlyRunTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.graph = self.base / "ontology.trig"
        self.source = self.base / "note.txt"
        self.source.write_text("Alice works for Acme.", encoding="utf-8")
        self.store = starter_store(self.graph)
        self.names = GraphNames()
        self.schema_before = set(self.store.get(self.names.schema_graphs[0]))
        self.shapes_before = set(self.store.get(self.names.shape_graphs[0]))

    def run_with(self, answer, data_only=True):
        request = RunRequest(
            source=self.source, graph_path=self.graph,
            merge=MergeConfig(require_declared_vocabulary=data_only))
        return run_text_to_graph(
            request, graph_store=self.store,
            extractor=FakeExtractor(answer), reporter=RunReporter())

    def schema_triples(self):
        return set(self.store.get(self.names.schema_graphs[0]))

    def test_a_declared_extraction_adds_data_and_leaves_schema_identical(self):
        result = self.run_with(DECLARED)
        self.assertEqual(result.files_saved, 1)
        self.assertEqual(self.schema_triples(), self.schema_before)
        self.assertEqual(set(self.store.get(self.names.shape_graphs[0])),
                         self.shapes_before)
        data = self.store.get(self.names.target_graph)
        subject = next(data.subjects(predicate=RELATION["works-for"]))
        self.assertIsNotNone(subject)

    def test_an_undeclared_extraction_is_rejected_and_changes_nothing(self):
        data_before = set(self.store.get(self.names.target_graph))
        with self.assertRaises(RuntimeError) as caught:
            self.run_with(UNDECLARED)
        self.assertIn("starter ontology", str(caught.exception))
        self.assertEqual(self.schema_triples(), self.schema_before)
        self.assertEqual(set(self.store.get(self.names.target_graph)),
                         data_before)

    def test_without_the_lock_new_vocabulary_is_still_added(self):
        self.run_with(UNDECLARED, data_only=False)
        data = self.store.get(self.names.target_graph)
        self.assertIn((CLASS["product"], RDF.type, OWL.Class), data)
        self.assertIn((RELATION["made-of"], RDF.type, OWL.ObjectProperty), data)


if __name__ == "__main__":
    unittest.main()
