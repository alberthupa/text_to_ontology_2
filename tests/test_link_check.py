"""Expected links, gaps, passages, candidates, and quoted evidence."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SH, SKOS

from connectivity_fixtures import starter_store, vocabulary
from text_to_ontology import prompts
from text_to_ontology.graph_management import CLASS, ONTO, RELATION
from text_to_ontology.graph_store import GraphNames
from text_to_ontology.link_check import (
    add_expected_link,
    expected_link_shape,
    expected_links,
    find_gaps,
    object_candidates,
    read_answer,
    select_passages,
)
from text_to_ontology.source_validation import validate_source_graph
from text_to_ontology.windowing import TextWindow

EXPECTED = [{"class": str(CLASS["project"]),
             "relation": str(RELATION["has-client"]),
             "question": "Which client?"}]


def add(graph, name, kind, base="http://x/staging/"):
    uri = URIRef(base + name.lower())
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, CLASS[kind.lower()]))
    graph.add((uri, ONTO.kind, Literal(kind)))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    return uri


def window(index, text):
    return TextWindow(f"w{index}", "d", index, text, 0, 0, 1, 2)


class ShapeTest(unittest.TestCase):
    def test_a_shape_reads_back_as_an_expected_link(self):
        shape = expected_link_shape(CLASS["project"], RELATION["has-client"],
                                    "Which client?")
        self.assertEqual(expected_links(shape), EXPECTED)

    def test_a_violation_shape_is_not_an_expected_link(self):
        shape = expected_link_shape(CLASS["project"], RELATION["has-client"], "")
        for rule in shape.subjects(SH.severity, SH.Warning):
            shape.set((rule, SH.severity, SH.Violation))
        self.assertEqual(expected_links(shape), [])

    def test_a_missing_expected_link_warns_but_conforms(self):
        data = Graph()
        add(data, "VAF", "Project")
        shape = expected_link_shape(CLASS["project"], RELATION["has-client"], "q")
        result = validate_source_graph(data, [shape])
        self.assertTrue(result.conforms)
        self.assertIn("Warning", result.report_text)

    def test_add_expected_link_checks_names(self):
        with tempfile.TemporaryDirectory() as directory:
            store = starter_store(Path(directory) / "o.trig")
            add_expected_link(store, "Project", "has client", "Which client?")
            shapes = store.get(GraphNames().shape_graphs[0])
            self.assertEqual(expected_links(shapes), EXPECTED)
            with self.assertRaises(ValueError):
                add_expected_link(store, "Gadget", "has client")
            with self.assertRaises(ValueError):
                add_expected_link(store, "Client", "has client")


class GapTest(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocabulary()
        self.source = Graph()
        self.project = add(self.source, "VAF", "Project")

    def test_a_project_without_a_client_is_a_gap(self):
        gaps = find_gaps(self.source, Graph(), EXPECTED, self.vocabulary)
        self.assertEqual([gap["entity"] for gap in gaps], [self.project])

    def test_a_project_with_a_client_is_not(self):
        client = add(self.source, "Farmexa", "Client")
        self.source.add((self.project, RELATION["has-client"], client))
        self.assertEqual(find_gaps(self.source, Graph(), EXPECTED,
                                   self.vocabulary), [])

    def test_a_client_already_in_the_graph_closes_the_gap(self):
        canonical = Graph()
        same = add(canonical, "VAF", "Project", base="http://x/final/")
        client = add(canonical, "Farmexa", "Client", base="http://x/final/")
        canonical.add((same, RELATION["has-client"], client))
        self.assertEqual(find_gaps(self.source, canonical, EXPECTED,
                                   self.vocabulary), [])

    def test_at_most_the_limit(self):
        for number in range(7):
            add(self.source, f"P{number}", "Project")
        self.assertEqual(len(find_gaps(self.source, Graph(), EXPECTED,
                                       self.vocabulary, limit=5)), 5)


class PassageTest(unittest.TestCase):
    def test_first_window_and_windows_naming_the_subject_in_order(self):
        windows = [window(0, "title"), window(1, "nothing here"),
                   window(2, "VAF again"), window(3, "and Farmexa")]
        passages = select_passages(windows, ["VAF", "Farmexa"])
        self.assertEqual(passages, "title\n...\nVAF again\n...\nand Farmexa")

    def test_the_cap_stops_before_overflow(self):
        windows = [window(0, "a" * 30), window(1, "VAF " + "b" * 30)]
        self.assertEqual(select_passages(windows, ["VAF"], cap=15), "a" * 30)


class CandidateTest(unittest.TestCase):
    def test_range_class_only_named_first_canonical_with_id(self):
        source, canonical = Graph(), Graph()
        add(source, "VAF", "Project")
        add(source, "Zeta", "Client")
        known = add(canonical, "Farmexa", "Client", base="http://x/final/")
        add(canonical, "Kafka", "Technology", base="http://x/final/")
        found = object_candidates(source, canonical, str(CLASS["client"]),
                                  vocabulary(), "for Farmexa")
        self.assertEqual([(item["key"], item["names"][0], item["existing_id"])
                          for item in found],
                         [("c1", "Farmexa", str(known)), ("c2", "Zeta", None)])


class AnswerTest(unittest.TestCase):
    def setUp(self):
        self.source = Graph()
        self.project = add(self.source, "VAF", "Project")
        self.gap = {"entity": self.project, **EXPECTED[0]}
        self.candidates = [{"key": "c1", "names": ["Farmexa"], "kind": "Client",
                            "existing_id": None}]
        self.passages = "Comparison of Copilot with VAF\nfor   Farmexa's request."

    def read(self, links):
        return read_answer({"links": links}, self.gap, self.source,
                           vocabulary(), self.candidates, self.passages)

    def test_a_quoted_link_becomes_an_ordinary_package(self):
        package, dropped = self.read([{
            "object": "c1", "confidence": 0.9,
            "evidence": "with VAF for Farmexa's request"}])
        self.assertEqual(dropped, [])
        self.assertEqual(package["relations"], [{
            "subject": "s", "predicate": "has client", "object": "c1",
            "confidence": 0.9}])
        self.assertEqual([item["name"] for item in package["entities"]],
                         ["VAF", "Farmexa"])

    def test_unquoted_evidence_or_unknown_candidates_are_dropped(self):
        package, dropped = self.read([
            {"object": "c1", "confidence": 0.9, "evidence": "Farmexa paid"},
            {"object": "c9", "confidence": 0.9, "evidence": "VAF"}])
        self.assertIsNone(package)
        self.assertEqual(len(dropped), 2)

    def test_a_shapeless_answer_is_nothing(self):
        package, dropped = read_answer([], self.gap, self.source, vocabulary(),
                                       self.candidates, self.passages)
        self.assertIsNone(package)


class PromptTest(unittest.TestCase):
    def test_the_template_is_valid_and_previews(self):
        library = prompts.PromptLibrary()
        self.assertIsNone(library.validate(
            "link_check_user", library.text("link_check_user")))
        rendered = library.render("link_check_user",
                                  prompts.PREVIEW_VALUES["link_check_user"])
        self.assertIn("Farmexa", rendered)
        self.assertIn('"links"', rendered)


if __name__ == "__main__":
    unittest.main()
