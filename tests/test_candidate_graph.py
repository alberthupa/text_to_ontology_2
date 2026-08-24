"""Milestone 4: validated extraction packages become RDF candidate graphs."""

import unittest
from decimal import Decimal

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD

from text_to_ontology.candidate_graph import DQV

from text_to_ontology.candidate_graph import (
    CANDIDATE_BASE,
    EXTRACTION_CONFIDENCE_METRIC,
    build_candidate_graph,
    literal_value,
    provisional_entity_iri,
)
from text_to_ontology.graph_management import CLASS, FACT, ONTO, RELATION


def sample_package():
    """One valid package: two entities, one relation, facts of every shape."""
    return {
        "entities": [
            {"id": "e1", "name": "Ada Lovelace", "kind": "Person",
             "description": "Wrote the first program.", "aliases": ["Ada"],
             "existing_id": None, "confidence": 0.9},
            {"id": "e2", "name": "Analytical Engine", "kind": "Machine",
             "description": "", "aliases": [],
             "existing_id": None, "confidence": 0.8},
        ],
        "relations": [
            {"subject": "e1", "predicate": "programmed", "object": "e2",
             "confidence": 0.85},
        ],
        "facts": [
            {"subject": "e1", "predicate": "birth date",
             "value": "1815-12-10", "confidence": 0.95},
            {"subject": "e1", "predicate": "famous", "value": True,
             "confidence": 0.7},
            {"subject": "e1", "predicate": "shoe size", "value": 5,
             "confidence": 0.5},
            {"subject": "e2", "predicate": "weight tons", "value": 3.5,
             "confidence": 0.6},
            {"subject": "e2", "predicate": "serial number",
             "value": "0007", "confidence": 0.99},
            {"subject": "e2", "predicate": "review date",
             "value": "2026-13-45", "confidence": 0.3},
        ],
    }


def built(package=None):
    return build_candidate_graph(
        package if package is not None else sample_package(),
        document_id="doc-abc123", window_id="win-def456",
        activity_id="act-789", extractor_model="test-model")


class LiteralTypingTest(unittest.TestCase):
    """AC3/T3: only unambiguous values get an XSD datatype."""

    def test_each_supported_shape_maps_to_its_datatype(self):
        cases = [
            ("1815-12-10", XSD.date),
            (True, XSD.boolean),
            (5, XSD.integer),
            (3.5, XSD.decimal),
            ("0007", None),           # leading zeros are identifiers, not numbers
            ("2026-13-45", None),     # an impossible date stays a string
            ("just words", None),
        ]
        for value, datatype in cases:
            literal = literal_value(value)
            self.assertEqual(literal.datatype, datatype,
                             f"{value!r} typed as {literal.datatype}")

    def test_floats_keep_a_stable_decimal_representation(self):
        self.assertEqual(str(literal_value(0.1)), "0.1")


class DeterminismTest(unittest.TestCase):
    """AC2/AC6: the same inputs always produce the same graph."""

    def test_two_builds_are_isomorphic_with_identical_resource_iris(self):
        first, second = built(), built()
        self.assertTrue(isomorphic(first, second))
        self.assertEqual(sorted(map(str, first.subjects())),
                         sorted(map(str, second.subjects())))

    def test_provisional_entity_iris_come_from_document_and_local_id(self):
        self.assertEqual(
            provisional_entity_iri("doc-abc123", "e1"),
            URIRef(CANDIDATE_BASE + "provisional/doc-abc123/e1"))


class AssertionAndEvidenceTest(unittest.TestCase):
    """AC4: assertions exist, and each record reifies what it supported."""

    def setUp(self):
        self.graph = built()

    def records(self):
        return sorted(self.graph.subjects(RDF.type, PROV.Collection), key=str)

    def test_every_record_is_a_prov_collection_with_reified_members(self):
        records = self.records()
        self.assertEqual(len(records),
                         len(sample_package()["entities"])
                         + len(sample_package()["relations"])
                         + len(sample_package()["facts"]))
        for record in records:
            members = list(self.graph.objects(record, PROV.hadMember))
            self.assertTrue(members, f"{record} has no evidence members")
            for member in members:
                self.assertIn((member, RDF.type, RDF.Statement), self.graph)

    def test_reified_statements_match_asserted_triples(self):
        for statement in self.graph.subjects(RDF.type, RDF.Statement):
            triple = tuple(next(self.graph.objects(statement, role))
                           for role in (RDF.subject, RDF.predicate, RDF.object))
            self.assertIn(triple, self.graph,
                          f"reification without assertion: {triple}")

    def test_two_records_can_support_one_triple_at_different_confidence(self):
        doubled = sample_package()
        doubled["relations"].append({
            "subject": "e1", "predicate": "programmed", "object": "e2",
            "confidence": 0.55})
        graph = built(doubled)
        relation = (URIRef(CANDIDATE_BASE + "provisional/doc-abc123/e1"),
                    RELATION["programmed"],
                    URIRef(CANDIDATE_BASE + "provisional/doc-abc123/e2"))
        self.assertIn(relation, graph)
        supporters = []
        for record in graph.subjects(PROV.hadMember, None):
            for member in graph.objects(record, PROV.hadMember):
                if (graph.value(member, RDF.subject) == relation[0]
                        and graph.value(member, RDF.predicate) == relation[1]
                        and graph.value(member, RDF.object) == relation[2]):
                    measurement = graph.value(subject=None,
                                              predicate=DQV.computedOn,
                                              object=record)
                    supporters.append(graph.value(measurement, DQV.value))
        self.assertEqual(len(supporters), 2)
        self.assertEqual({str(value) for value in supporters},
                         {"0.85", "0.55"})


class ConfidenceMeasurementTest(unittest.TestCase):
    """AC5: confidence is a DQV measurement on the record collection."""

    def setUp(self):
        self.graph = built()

    def test_the_metric_is_declared_once_as_a_dqv_metric(self):
        self.assertIn((EXTRACTION_CONFIDENCE_METRIC, RDF.type, DQV.Metric),
                      self.graph)

    def test_every_record_has_one_decimal_measurement_in_range(self):
        for record in self.graph.subjects(RDF.type, PROV.Collection):
            found = list(self.graph.subjects(DQV.computedOn, record))
            self.assertEqual(len(found), 1, str(record))
            measurement = found[0]
            value = self.graph.value(measurement, DQV.value)
            self.assertEqual(value.datatype, XSD.decimal)
            number = Decimal(str(value))
            self.assertGreaterEqual(number, Decimal("0"))
            self.assertLessEqual(number, Decimal("1"))
            self.assertIn((measurement, DQV.isMeasurementOf,
                           EXTRACTION_CONFIDENCE_METRIC), self.graph)


class ProvenanceChainTest(unittest.TestCase):
    """AC6: document, window, activity, agent, records, measurements linked."""

    def setUp(self):
        self.graph = built()

    def test_the_chain_runs_from_document_to_activity(self):
        document = URIRef(CANDIDATE_BASE + "document/doc-abc123")
        window = URIRef(CANDIDATE_BASE + "window/win-def456")
        activity = URIRef(CANDIDATE_BASE + "activity/act-789")
        agent = self.graph.value(activity, PROV.wasAssociatedWith)
        self.assertIn((window, PROV.wasDerivedFrom, document), self.graph)
        self.assertIn((activity, PROV.used, window), self.graph)
        self.assertIn((agent, RDF.type, PROV.SoftwareAgent), self.graph)
        self.assertEqual(str(self.graph.value(agent, RDFS.label)),
                         "test-model")

    def test_records_and_measurements_name_the_activity(self):
        activity = URIRef(CANDIDATE_BASE + "activity/act-789")
        generated = set(self.graph.subjects(PROV.wasGeneratedBy, activity))
        records = set(self.graph.subjects(RDF.type, PROV.Collection))
        measurements = set(self.graph.subjects(RDF.type,
                                               DQV.QualityMeasurement))
        self.assertTrue(records <= generated)
        self.assertTrue(measurements <= generated)


class VocabularyTest(unittest.TestCase):
    """AC9: standard vocabularies plus generated domain terms - nothing else."""

    def test_only_allowed_predicates_appear(self):
        generated_namespaces = (str(CLASS), str(FACT), str(RELATION))
        allowed = {
            RDF.type, RDF.subject, RDF.predicate, RDF.object,
            RDFS.label, RDFS.subClassOf,
            SKOS.definition, SKOS.altLabel,
            PROV.hadMember, PROV.wasGeneratedBy, PROV.used,
            PROV.wasAssociatedWith, PROV.wasDerivedFrom,
            DQV.computedOn, DQV.isMeasurementOf, DQV.value,
        }
        for subject, predicate, object_ in built():
            allowed_here = predicate in allowed or any(
                str(predicate).startswith(namespace)
                for namespace in generated_namespaces)
            self.assertTrue(allowed_here, f"unexpected predicate {predicate}")

    def test_kind_strings_became_types_not_literals(self):
        graph = built()
        ada = URIRef(CANDIDATE_BASE + "provisional/doc-abc123/e1")
        person = CLASS["person"]
        self.assertIn((ada, RDF.type, person), graph)
        self.assertIsNone(graph.value(ada, ONTO.kind),
                          "kind must be a type, not a string literal")


class EntityMappingTest(unittest.TestCase):
    """AC3: labels and definitions follow their standard meanings."""

    def test_entity_names_descriptions_and_aliases_use_rdfs_and_skos(self):
        graph = built()
        ada = URIRef(CANDIDATE_BASE + "provisional/doc-abc123/e1")
        self.assertEqual(str(graph.value(ada, RDFS.label)), "Ada Lovelace")
        self.assertEqual(str(graph.value(ada, SKOS.definition)),
                         "Wrote the first program.")
        self.assertIn((ada, SKOS.altLabel, Literal("Ada")), graph)
        person = graph.value(ada, RDF.type)
        self.assertIn((person, RDF.type, OWL.Class), graph)
        self.assertIn((person, RDFS.subClassOf, ONTO.Entity), graph)


class RoundTripTest(unittest.TestCase):
    """AC8: candidate graphs survive serialization with associations intact."""

    def test_turtle_round_trip_is_isomorphic(self):
        original = built()
        reparsed = Graph()
        reparsed.parse(data=original.serialize(format="turtle"),
                       format="turtle")
        self.assertTrue(isomorphic(original, reparsed))

    def test_round_tripped_evidence_still_points_at_its_triple(self):
        reparsed = Graph()
        reparsed.parse(data=built().serialize(format="turtle"),
                       format="turtle")
        record = next(iter(sorted(
            reparsed.subjects(RDF.type, PROV.Collection), key=str)))
        member = reparsed.value(record, PROV.hadMember)
        triple = tuple(reparsed.value(member, role)
                       for role in (RDF.subject, RDF.predicate, RDF.object))
        self.assertIn(triple, reparsed)


if __name__ == "__main__":
    unittest.main()
