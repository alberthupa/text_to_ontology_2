"""The health numbers, one by one, on small graphs."""

import json
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from connectivity_fixtures import starter_store, vocabulary
from text_to_ontology.graph_health import (
    duplicate_suspects,
    endpoint_violations,
    gold_scores,
    health_report,
    isolated_entities,
    missing_links,
    root_only_entities,
    uncovered_sources,
)
from text_to_ontology.graph_management import CLASS, ONTO, RELATION
from text_to_ontology.graph_store import GraphNames, Publication
from text_to_ontology.link_check import add_expected_link
from text_to_ontology.windowing import make_source_document

E = "http://example.org/text-ontology/entity/"


def add(graph, name, kind=None):
    uri = URIRef(E + name.lower().replace(" ", "-"))
    graph.add((uri, RDF.type, ONTO.Entity))
    if kind:
        graph.add((uri, RDF.type, CLASS[kind.lower()]))
        graph.add((uri, ONTO.kind, Literal(kind)))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    return uri


class NumbersTest(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocabulary()
        self.data = Graph()
        self.project = add(self.data, "VAF", "Project")
        self.client = add(self.data, "Farmexa", "Client")
        self.loose = add(self.data, "Lingo")

    def test_isolated_and_root_only(self):
        self.data.add((self.project, RELATION["has-client"], self.client))
        self.assertEqual(isolated_entities(self.data), [self.loose])
        self.assertEqual(root_only_entities(self.data, self.vocabulary),
                         [self.loose])

    def test_endpoint_violations(self):
        self.data.add((self.project, RELATION["has-client"], self.client))
        self.assertEqual(endpoint_violations(self.data, self.vocabulary), [])
        self.data.add((self.loose, RELATION["has-client"], self.client))
        self.data.add((self.client, URIRef(
            "http://example.org/text-ontology/fact/project-summary"),
            Literal("x")))
        found = endpoint_violations(self.data, self.vocabulary)
        self.assertEqual(sorted((item["predicate"], item["subject"],
                                 tuple(item["problems"])) for item in found),
                         [("has client", "Lingo", ("domain",)),
                          ("project summary", "Farmexa", ("domain",))])

    def test_missing_links(self):
        expected = [{"class": str(CLASS["project"]),
                     "relation": str(RELATION["has-client"]), "question": ""}]
        self.assertEqual(missing_links(self.data, self.vocabulary, expected),
                         [{"entity": "VAF", "relation": "has client"}])
        self.data.add((self.project, RELATION["has-client"], self.client))
        self.assertEqual(missing_links(self.data, self.vocabulary, expected), [])

    def test_duplicate_suspects(self):
        other = add(self.data, "Farmexy", "Client")
        loose = add(self.data, "Farmexie")
        tool = add(self.data, "Farmexo", "Technology")
        pairs = {(item["first"], item["second"])
                 for item in duplicate_suspects(self.data, self.vocabulary)}
        self.assertIn(("Farmexa", "Farmexy"), pairs)
        self.assertIn(("Farmexa", "Farmexie"), pairs)
        self.assertNotIn(("Farmexa", "Farmexo"), pairs)
        self.assertNotIn(("Farmexo", "Farmexy"), pairs)

    def test_gold_recall_and_precision(self):
        wrong = add(self.data, "Acme", "Client")
        self.data.add((self.project, RELATION["has-client"], wrong))
        self.data.add((self.project, SKOS.altLabel, Literal("Virtual Assistant")))
        gold = [
            {"subject": "Virtual Assistant", "predicate": "has client",
             "object": "Farmexa"},
            {"subject": "VAF", "predicate": "has client", "object": "Acme"},
        ]
        scores = gold_scores(self.data, self.vocabulary, gold)
        self.assertEqual((scores["found"], scores["recall"]), (1, 0.5))
        self.assertEqual((scores["checked"], scores["correct"]), (1, 1))
        self.data.add((self.project, RELATION["has-client"], add(
            self.data, "Bogus", "Client")))
        scores = gold_scores(self.data, self.vocabulary, gold)
        self.assertEqual((scores["checked"], scores["correct"]), (2, 1))


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)

    def test_uncovered_sources(self):
        folder = self.base / "notes"
        (folder / "a").mkdir(parents=True)
        (folder / "a" / "seen.md").write_text("seen text", encoding="utf-8")
        (folder / "a" / "new.md").write_text("new text", encoding="utf-8")
        provenance = Graph()
        seen = make_source_document("seen.md", "seen text")
        provenance.add((URIRef("http://example.org/text-ontology/trace/document/"
                               + seen.document_id), RDF.type, ONTO.Document))
        self.assertEqual(uncovered_sources(provenance, folder), ["a/new.md"])

    def test_the_whole_report_from_a_file(self):
        path = self.base / "ontology.trig"
        store = starter_store(path)
        add_expected_link(store, "Project", "has client")
        names = GraphNames()
        data = Graph()
        add(data, "VAF", "Project")
        store.publish(Publication(graphs={names.target_graph: data}))
        gold = self.base / "gold.json"
        gold.write_text(json.dumps({"links": [
            {"subject": "VAF", "predicate": "has client",
             "object": "Farmexa"}]}), encoding="utf-8")
        report = health_report(path, gold_path=gold)
        self.assertEqual(report["entities"], 1)
        self.assertEqual(report["missing_links"],
                         [{"entity": "VAF", "relation": "has client"}])
        self.assertEqual(report["gold"]["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
