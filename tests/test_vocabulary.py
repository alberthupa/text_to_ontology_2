"""The starter vocabulary lock: what data-only ingestion may use."""

import unittest

from rdflib import BNode, Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS

from text_to_ontology.graph_management import CLASS, ONTO, seed_graph
from text_to_ontology.graph_store import GraphNames
from text_to_ontology.starter import starter_publication
from text_to_ontology.vocabulary import read_vocabulary


PROPOSAL = {
    "classes": [
        {"name": "Person", "description": "a human being"},
        {"name": "Organization", "description": ""},
    ],
    "relations": [
        {"name": "works-for", "description": "", "domain": "Person",
         "range": "Organization"},
    ],
    "facts": [
        {"name": "founded-in", "description": "", "domain": "Organization",
         "range": "integer"},
    ],
}


def schema_of(proposal=PROPOSAL):
    names = GraphNames()
    publication = starter_publication(proposal, names)
    return names, publication.graphs[names.schema_graphs[0]]


class ReadVocabularyTest(unittest.TestCase):
    def test_a_fresh_seed_declares_only_entity(self):
        vocabulary = read_vocabulary(seed_graph())
        self.assertIn(str(ONTO.Entity), vocabulary.classes)
        self.assertEqual(vocabulary.relations, {})
        self.assertEqual(vocabulary.facts, {})
        self.assertFalse(vocabulary.is_empty)

    def test_a_starter_schema_declares_every_kind(self):
        _names, schema = schema_of()
        vocabulary = read_vocabulary(schema)
        self.assertEqual(vocabulary.class_names,
                         ["Entity", "Organization", "Person"])
        self.assertEqual(vocabulary.relation_names, ["works for"])
        self.assertEqual(vocabulary.fact_names, ["founded in"])

    def test_declarations_match_by_slug_not_by_spelling(self):
        _names, schema = schema_of()
        vocabulary = read_vocabulary(schema)
        self.assertTrue(vocabulary.declares_class("person"))
        self.assertTrue(vocabulary.declares_class("Person"))
        self.assertFalse(vocabulary.declares_class("Product"))
        self.assertTrue(vocabulary.declares_relation("works for"))
        self.assertTrue(vocabulary.declares_relation("works_for"))
        self.assertFalse(vocabulary.declares_relation("is-made-of"))
        self.assertTrue(vocabulary.declares_fact("Founded-In"))
        self.assertFalse(vocabulary.declares_fact("works-for"))

    def test_a_relation_is_never_read_as_a_fact(self):
        _names, schema = schema_of()
        vocabulary = read_vocabulary(schema)
        self.assertFalse(vocabulary.declares_fact("works-for"))
        self.assertFalse(vocabulary.declares_relation("founded-in"))

    def test_blank_nodes_are_not_vocabulary(self):
        graph = Graph()
        graph.add((BNode(), RDF.type, OWL.Class))
        graph.add((CLASS["person"], RDF.type, OWL.Class))
        graph.add((CLASS["person"], RDFS.label, Literal("Person")))
        vocabulary = read_vocabulary(graph)
        self.assertEqual(vocabulary.class_names, ["Person"])
        self.assertEqual(len(vocabulary.classes), 1)

    def test_an_unlabelled_declaration_falls_back_to_its_iri(self):
        graph = Graph()
        graph.add((CLASS["thing"], RDF.type, OWL.Class))
        vocabulary = read_vocabulary(graph)
        self.assertEqual(vocabulary.class_names, [str(CLASS["thing"])])


if __name__ == "__main__":
    unittest.main()
