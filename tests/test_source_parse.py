"""Baseline: turning one source text into a parsing prompt."""

import json
import unittest
from unittest import mock

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

import source_parse
from graph_management import ENTITY, FACT, ONTO, RELATION
from source_parse import make_prompt, parse_source


def add_entity(graph, local, name, kind, aliases=(), description=""):
    uri = ENTITY[local]
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    graph.add((uri, ONTO.kind, Literal(kind)))
    for alias in aliases:
        graph.add((uri, SKOS.altLabel, Literal(alias)))
    if description:
        graph.add((uri, RDFS.comment, Literal(description)))
    return uri


class PromptTest(unittest.TestCase):
    """Case 6: source text, catalog entities, and property labels appear."""

    def setUp(self):
        self.graph = Graph()
        add_entity(
            self.graph, "acme-corp", "Acme Corp", "Company",
            aliases=["ACME"], description="A maker of things.",
        )
        add_entity(self.graph, "ada-lovelace", "Ada Lovelace", "Person")
        self.graph.add((RELATION["works-for"], RDF.type, OWL.ObjectProperty))
        self.graph.add((RELATION["works-for"], RDFS.label, Literal("works for")))
        self.graph.add((FACT["birth-date"], RDF.type, OWL.DatatypeProperty))
        self.graph.add((FACT["birth-date"], RDFS.label, Literal("birth date")))
        self.prompt = make_prompt("Ada Lovelace works for Acme Corp.", self.graph)

    def test_source_text_is_included(self):
        self.assertIn("Ada Lovelace works for Acme Corp.", self.prompt)

    def test_every_catalog_entity_is_included(self):
        self.assertIn(str(ENTITY["acme-corp"]), self.prompt)
        self.assertIn(str(ENTITY["ada-lovelace"]), self.prompt)
        self.assertIn("A maker of things.", self.prompt)
        self.assertIn("ACME", self.prompt)

    def test_object_and_datatype_property_labels_are_included(self):
        self.assertIn(json.dumps(["birth date", "works for"]), self.prompt)

    def test_unlabelled_properties_are_not_included(self):
        self.graph.add((RELATION["silent"], RDF.type, OWL.ObjectProperty))
        prompt = make_prompt("text", self.graph)
        self.assertIn(json.dumps(["birth date", "works for"]), prompt)

    def test_requested_json_shape_is_unchanged(self):
        for fragment in (
            '"entities"', '"relations"', '"facts"',
            '"existing_id"', '"aliases"', '"predicate"', '"value"',
            "Return JSON only.",
        ):
            self.assertIn(fragment, self.prompt)

    def test_empty_graph_still_produces_a_prompt(self):
        prompt = make_prompt("Some text.", Graph())
        self.assertIn("Some text.", prompt)
        self.assertIn("EXISTING ENTITIES:\n[]", prompt)
        self.assertIn("[]", prompt)


class ParseSourceTest(unittest.TestCase):
    """The entry point sends the built prompt and returns the model's answer."""

    def test_the_prompt_is_sent_and_the_answer_returned_unchanged(self):
        graph = Graph()
        add_entity(graph, "acme-corp", "Acme Corp", "Company")
        answer = {"entities": [], "relations": [], "facts": []}

        with mock.patch.object(source_parse, "ask_llm", return_value=answer) as asked:
            self.assertIs(parse_source("Acme Corp exists.", graph), answer)

        asked.assert_called_once_with(make_prompt("Acme Corp exists.", graph))

    def test_parsing_does_not_change_the_graph(self):
        graph = Graph()
        add_entity(graph, "acme-corp", "Acme Corp", "Company")
        before = set(graph)

        with mock.patch.object(source_parse, "ask_llm", return_value={}):
            parse_source("Acme Corp exists.", graph)

        self.assertEqual(set(graph), before)


if __name__ == "__main__":
    unittest.main()
