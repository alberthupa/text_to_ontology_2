"""Baseline: turning one source text into a parsing prompt."""

import json
import unittest

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontology import ENTITY, FACT, ONTO, RELATION, make_prompt


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


if __name__ == "__main__":
    unittest.main()
