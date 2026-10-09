"""Inflected names: found in context, held for review, never merged blindly."""

import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from connectivity_fixtures import schema_graph
from text_to_ontology.entity_lookup import identity_decision
from text_to_ontology.graph_management import CLASS, ONTO
from text_to_ontology.source_concepts import same_name_stem, same_word_stem
from text_to_ontology.task_context import build_task_context


class StemTest(unittest.TestCase):
    def test_same_word_with_another_ending(self):
        self.assertTrue(same_word_stem("Farmexa", "Farmexy"))
        self.assertTrue(same_word_stem("farmexa", "farmexami"))
        self.assertTrue(same_word_stem("Polpharma", "Polpharmy"))
        self.assertTrue(same_word_stem("rag", "RAG"))

    def test_different_words_stay_different(self):
        self.assertFalse(same_word_stem("pharma", "pharmindex"))
        self.assertFalse(same_word_stem("rag", "rug"))
        self.assertFalse(same_word_stem("Python", "Pythia"))

    def test_names_compare_word_by_word(self):
        self.assertTrue(same_name_stem("Bank Farmexa", "Bank Farmexy"))
        self.assertFalse(same_name_stem("Farmexa", "Farmexa Group"))
        self.assertFalse(same_name_stem("Bank Polski", "Banku Polskiego"))


def graph_with_client():
    graph = schema_graph()
    uri = URIRef("http://example.org/text-ontology/entity/farmexa")
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, CLASS["client"]))
    graph.add((uri, ONTO.kind, Literal("Client")))
    graph.add((uri, SKOS.prefLabel, Literal("Farmexa")))
    return graph, uri


class SelectionTest(unittest.TestCase):
    def test_an_inflected_name_selects_the_existing_card(self):
        graph, uri = graph_with_client()
        context = build_task_context(
            "Porównanie na potrzeby zapytania Farmexy.", graph)
        matches = [found for found in context["diagnostics"]["matches"]
                   if found["target"] == str(uri)]
        self.assertEqual(matches[0]["reason"], "inflected name match")
        self.assertIn(str(uri), [str(entry["value"]["uri"])
                                 for entry in context["resources"]])


class IdentityTest(unittest.TestCase):
    catalog = [{"id": "http://x/farmexa", "names": ["Farmexa"],
                "kind": "Client", "description": ""}]

    def decide(self, name, kind="Client", aliases=()):
        return identity_decision(
            {"id": "e1", "name": name, "kind": kind, "aliases": list(aliases),
             "confidence": 0.95},
            self.catalog, allocate_uri=lambda name: URIRef("http://x/new"))

    def test_an_inflected_form_is_held_for_review(self):
        decision = self.decide("Farmexy")
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "inflected_form")
        self.assertEqual(decision["suggestions"][0]["uri"], "http://x/farmexa")

    def test_another_kind_is_not_suggested(self):
        self.assertEqual(self.decide("Farmexy", kind="Technology")["status"],
                         "new")

    def test_an_alias_still_resolves_exactly(self):
        decision = self.decide("Farmexy", aliases=["Farmexa"])
        self.assertEqual((decision["status"], decision["method"]),
                         ("existing", "exact_alias"))


if __name__ == "__main__":
    unittest.main()
