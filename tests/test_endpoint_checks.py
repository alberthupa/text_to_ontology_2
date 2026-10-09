"""Relations and facts must connect the classes the starter declares."""

import unittest

from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from connectivity_fixtures import answer, entity, relation, schema_graph, vocabulary
from text_to_ontology.candidate_validation import (
    drop_endpoint_mismatches,
    validate_candidates,
)
from text_to_ontology.graph_management import CLASS, ONTO


def codes(result):
    return {issue["code"] for issue in result["issues"]}


class EndpointGateTest(unittest.TestCase):
    def setUp(self):
        self.schema = schema_graph()
        self.vocabulary = vocabulary()

    def check(self, data, graph=None, allowed=()):
        return validate_candidates(data, graph or self.schema, allowed,
                                   vocabulary=self.vocabulary)

    def test_the_declared_direction_passes(self):
        result = self.check(answer(
            [entity("e1", "VAF", "Project"), entity("e2", "Farmexa", "Client")],
            [relation("e1", "has client", "e2")]))
        self.assertTrue(result["valid"], result["issues"])

    def test_a_wrong_subject_class_is_a_domain_mismatch(self):
        result = self.check(answer(
            [entity("e1", "Lingo", "Entity"), entity("e2", "Farmexa", "Client")],
            [relation("e1", "has client", "e2")]))
        self.assertIn("relation.domain_mismatch", codes(result))
        message = next(issue["message"] for issue in result["issues"]
                       if issue["code"] == "relation.domain_mismatch")
        self.assertIn("goes Project --has client--> Client", message)
        self.assertIn("'Lingo' is Entity", message)

    def test_a_wrong_object_class_is_a_range_mismatch(self):
        result = self.check(answer(
            [entity("e1", "VAF", "Project"), entity("e2", "Kafka", "Technology")],
            [relation("e1", "has client", "e2")]))
        self.assertEqual(codes(result), {"relation.range_mismatch"})

    def test_a_fact_on_the_wrong_class_is_a_domain_mismatch(self):
        result = self.check(answer(
            [entity("e1", "Farmexa", "Client")], [],
            [{"subject": "e1", "predicate": "project summary",
              "value": "x", "confidence": 0.9}]))
        self.assertEqual(codes(result), {"fact.domain_mismatch"})

    def test_a_subclass_fits_its_parents_domain(self):
        schema = schema_graph()
        schema.add((CLASS["pilot"], RDF.type, URIRef(
            "http://www.w3.org/2002/07/owl#Class")))
        schema.add((CLASS["pilot"], RDFS.label, Literal("Pilot")))
        schema.add((CLASS["pilot"], RDFS.subClassOf, CLASS["project"]))
        from text_to_ontology.vocabulary import read_vocabulary
        result = validate_candidates(answer(
            [entity("e1", "VAF", "Pilot"), entity("e2", "Farmexa", "Client")],
            [relation("e1", "has client", "e2")]), schema, (),
            vocabulary=read_vocabulary(schema))
        self.assertTrue(result["valid"], result["issues"])

    def test_an_existing_entity_is_checked_by_its_graph_kind(self):
        graph = schema_graph()
        client = URIRef("http://example.org/text-ontology/entity/farmexa")
        for triple in ((client, RDF.type, ONTO.Entity),
                       (client, ONTO.kind, Literal("Client")),
                       (client, SKOS.prefLabel, Literal("Farmexa"))):
            graph.add(triple)
        result = self.check(answer(
            [entity("e1", "VAF", "Project"),
             entity("e2", "Farmexa", "Client", existing_id=str(client))],
            [relation("e1", "has client", "e2")]), graph, [str(client)])
        self.assertTrue(result["valid"], result["issues"])

    def test_without_a_vocabulary_nothing_new_is_checked(self):
        result = validate_candidates(answer(
            [entity("e1", "Lingo", "Entity"), entity("e2", "Farmexa", "Client")],
            [relation("e1", "has client", "e2")]), self.schema, ())
        self.assertNotIn("relation.domain_mismatch", codes(result))


class DropTest(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocabulary()
        self.schema = schema_graph()

    def test_only_the_wrongly_connected_records_are_dropped(self):
        data = answer(
            [entity("e1", "VAF", "Project"), entity("e2", "Kafka", "Technology")],
            [relation("e1", "has client", "e2"),
             relation("e1", "uses technology", "e2")])
        result = validate_candidates(data, self.schema, (),
                                     vocabulary=self.vocabulary)
        kept, dropped = drop_endpoint_mismatches(data, result)
        self.assertEqual(kept["relations"],
                         [relation("e1", "uses technology", "e2")])
        self.assertEqual(len(dropped["records"]), 1)
        self.assertTrue(validate_candidates(kept, self.schema, (),
                                            vocabulary=self.vocabulary)["valid"])

    def test_any_other_error_keeps_the_old_behaviour(self):
        data = answer(
            [entity("e1", "VAF", "Project"), entity("e2", "Kafka", "Gadget")],
            [relation("e1", "has client", "e2")])
        result = validate_candidates(data, self.schema, (),
                                     vocabulary=self.vocabulary)
        self.assertIsNone(drop_endpoint_mismatches(data, result))


class VocabularyTest(unittest.TestCase):
    def test_domains_ranges_and_parents_are_read(self):
        found = vocabulary()
        prop = str(found.relation_iri("has client"))
        self.assertEqual(found.domain_of(prop), str(CLASS["project"]))
        self.assertEqual(found.range_of(prop), str(CLASS["client"]))
        self.assertTrue(found.is_a(CLASS["project"], ONTO.Entity))
        self.assertFalse(found.is_a(ONTO.Entity, CLASS["project"]))


if __name__ == "__main__":
    unittest.main()
