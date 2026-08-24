"""Proposal 2: what the current instance data actually does, with evidence."""

import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from text_to_ontology.graph_partition import partition_graph
from text_to_ontology.graph_patterns import observed_relationships


REPOSITORY = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPOSITORY / "ontology.ttl"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "miniature_repository.ttl"
EX = Namespace("http://example.com/other/")


def schema_graph():
    """Three domain classes below one root, with the properties they use."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    for name in ("person", "location", "organization"):
        graph.add((CLASS[name], RDF.type, OWL.Class))
        graph.add((CLASS[name], RDFS.subClassOf, ONTO.Entity))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((FACT.born, RDF.type, OWL.DatatypeProperty))
    return graph


def individual(graph, uri, *classes):
    """An individual as the merge step writes one: metatypes and a class."""
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, OWL.NamedIndividual))
    graph.add((uri, RDF.type, SKOS.Concept))
    for class_ in classes:
        graph.add((uri, RDF.type, class_))
    return uri


def only(records):
    """The single expected record, with a readable failure when there are more."""
    assert len(records) == 1, records
    return records[0]


class ResourcePatternTest(unittest.TestCase):
    """Case 1: a resource-valued assertion is a class-property-class pattern."""

    def test_a_relation_between_two_typed_individuals(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        acme = individual(instance, ENTITY.acme, CLASS.organization)
        instance.add((ada, RELATION.knows, acme))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["subject_class"], CLASS.person)
        self.assertEqual(record["predicate"], RELATION.knows)
        self.assertEqual(record["range"], CLASS.organization)
        self.assertEqual(record["range_kind"], "class")

    def test_the_same_property_to_two_object_classes_makes_two_patterns(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, RELATION.knows,
                      individual(instance, ENTITY.acme, CLASS.organization)))
        instance.add((ada, RELATION.knows,
                      individual(instance, ENTITY.paris, CLASS.location)))
        ranges = {r["range"] for r in observed_relationships(schema_graph(), instance)}
        self.assertEqual(ranges, {CLASS.organization, CLASS.location})


class LiteralPatternTest(unittest.TestCase):
    """Cases 2 and 3: literals report the datatype they carry."""

    def literal_range(self, value):
        instance = Graph()
        instance.add((individual(instance, ENTITY.ada, CLASS.person), FACT.born, value))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["range_kind"], "datatype")
        return record["range"]

    def test_a_plain_string_reports_xsd_string(self):
        self.assertEqual(self.literal_range(Literal("1815")), XSD.string)

    def test_an_explicitly_typed_literal_reports_its_datatype(self):
        self.assertEqual(
            self.literal_range(Literal(1815, datatype=XSD.gYear)), XSD.gYear)

    def test_an_integer_literal_reports_xsd_integer(self):
        self.assertEqual(self.literal_range(Literal(1815)), XSD.integer)

    def test_a_language_tagged_literal_reports_rdf_lang_string(self):
        self.assertEqual(
            self.literal_range(Literal("Ada", lang="en")), RDF.langString)


class CountingTest(unittest.TestCase):
    """Cases 4 and 5: occurrences and distinct subjects are different facts."""

    def test_a_duplicate_triple_is_counted_once(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, FACT.born, Literal("1815")))
        instance.add((ada, FACT.born, Literal("1815")))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["occurrences"], 1)
        self.assertEqual(record["distinct_subjects"], 1)

    def test_one_subject_with_several_values_separates_the_two_counts(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        individual(instance, ENTITY.grace, CLASS.person)
        instance.add((ada, FACT.born, Literal("1815")))
        instance.add((ada, FACT.born, Literal("1816")))
        instance.add((ada, FACT.born, Literal("1817")))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["occurrences"], 3)
        self.assertEqual(record["distinct_subjects"], 1)


class EvidenceTest(unittest.TestCase):
    """Cases 6 and 7, per decision gate 4: zero, one, and several values."""

    def population_fixture(self):
        """Four people: one with three values, one with one, two with none."""
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        grace = individual(instance, ENTITY.grace, CLASS.person)
        individual(instance, ENTITY.alan, CLASS.person)
        individual(instance, ENTITY.edsger, CLASS.person)
        for value in ("1815", "1816", "1817"):
            instance.add((ada, FACT.born, Literal(value)))
        instance.add((grace, FACT.born, Literal("1906")))
        return instance

    def test_coverage_uses_the_subject_class_population(self):
        record = only(observed_relationships(
            schema_graph(), self.population_fixture()))
        self.assertEqual(record["occurrences"], 4)
        self.assertEqual(record["distinct_subjects"], 2)
        self.assertEqual(record["class_population"], 4)
        self.assertAlmostEqual(record["coverage"], 0.5)

    def test_cardinality_covers_only_participating_subjects(self):
        record = only(observed_relationships(
            schema_graph(), self.population_fixture()))
        self.assertEqual(record["cardinality_min"], 1)
        self.assertEqual(record["cardinality_median"], 2.0)
        self.assertEqual(record["cardinality_max"], 3)

    def test_population_counts_class_members_that_never_participate(self):
        instance = self.population_fixture()
        individual(instance, ENTITY.acme, CLASS.organization)
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["class_population"], 4)


class ClassChoiceTest(unittest.TestCase):
    """Cases 8 and 9, per decision gate 3: the most specific domain class."""

    def test_metatypes_and_superclasses_do_not_swamp_the_domain_class(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, FACT.born, Literal("1815")))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertEqual(record["subject_class"], CLASS.person)

    def test_a_deeper_class_wins_over_its_declared_superclass(self):
        schema = schema_graph()
        schema.add((EX.Scientist, RDF.type, OWL.Class))
        schema.add((EX.Scientist, RDFS.subClassOf, CLASS.person))
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person, EX.Scientist)
        instance.add((ada, FACT.born, Literal("1815")))
        record = only(observed_relationships(schema, instance))
        self.assertEqual(record["subject_class"], EX.Scientist)

    def test_two_incomparable_classes_produce_two_patterns(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person, CLASS.organization)
        instance.add((ada, FACT.born, Literal("1815")))
        records = observed_relationships(schema_graph(), instance)
        self.assertEqual(
            [r["subject_class"] for r in records],
            [CLASS.organization, CLASS.person],
        )
        for record in records:
            self.assertEqual(record["occurrences"], 1)


class MissingClassTest(unittest.TestCase):
    """Case 10: an unclassified resource is reported, never invented."""

    def test_an_untyped_subject_reports_no_class_and_no_coverage(self):
        instance = Graph()
        instance.add((ENTITY.mystery, FACT.born, Literal("1815")))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertIsNone(record["subject_class"])
        self.assertIsNone(record["class_population"])
        self.assertIsNone(record["coverage"])
        self.assertEqual(record["occurrences"], 1)

    def test_an_untyped_object_is_reported_as_unknown(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, RELATION.knows, ENTITY.mystery))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertIsNone(record["range"])
        self.assertEqual(record["range_kind"], "unknown")

    def test_a_metatype_only_subject_reports_no_class(self):
        instance = Graph()
        instance.add((ENTITY.ada, RDF.type, OWL.NamedIndividual))
        instance.add((ENTITY.ada, RDF.type, SKOS.Concept))
        instance.add((ENTITY.ada, FACT.born, Literal("1815")))
        record = only(observed_relationships(schema_graph(), instance))
        self.assertIsNone(record["subject_class"])


class ExcludedPredicateTest(unittest.TestCase):
    """Case 11: naming, typing, and structure are not relationship patterns."""

    def test_annotations_types_and_kind_produce_no_patterns(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, RDFS.label, Literal("Ada")))
        instance.add((ada, RDFS.comment, Literal("A person")))
        instance.add((ada, SKOS.prefLabel, Literal("Ada")))
        instance.add((ada, SKOS.altLabel, Literal("Lovelace")))
        instance.add((ada, SKOS.definition, Literal("Somebody")))
        instance.add((ada, ONTO.kind, Literal("Person")))
        self.assertEqual(observed_relationships(schema_graph(), instance), [])

    def test_schema_predicates_produce_no_patterns(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, RDFS.subClassOf, ONTO.Entity))
        instance.add((ada, OWL.sameAs, ENTITY.grace))
        self.assertEqual(observed_relationships(schema_graph(), instance), [])


class RetentionTest(unittest.TestCase):
    """Case 12: a pattern seen once is still a pattern."""

    def test_a_single_occurrence_pattern_is_kept(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        instance.add((ada, FACT.born, Literal("1815")))
        for index in range(20):
            other = individual(instance, ENTITY[f"p{index}"], CLASS.organization)
            instance.add((other, FACT.born, Literal("1900")))
        records = observed_relationships(schema_graph(), instance)
        self.assertIn(CLASS.person, [r["subject_class"] for r in records])


class OrderingTest(unittest.TestCase):
    """Case 13: the same graphs always produce the same list."""

    def mixed(self):
        instance = Graph()
        ada = individual(instance, ENTITY.ada, CLASS.person)
        acme = individual(instance, ENTITY.acme, CLASS.organization)
        paris = individual(instance, ENTITY.paris, CLASS.location)
        instance.add((ada, RELATION.knows, acme))
        instance.add((acme, RELATION.knows, paris))
        instance.add((paris, FACT.born, Literal("1815")))
        instance.add((ada, FACT.born, Literal("1815")))
        return instance

    def test_repeated_runs_agree(self):
        schema, instance = schema_graph(), self.mixed()
        first = observed_relationships(schema, instance)
        second = observed_relationships(schema, instance)
        self.assertEqual(first, second)

    def test_records_are_sorted_by_subject_class_then_predicate(self):
        records = observed_relationships(schema_graph(), self.mixed())
        keys = [(str(r["subject_class"]), str(r["predicate"])) for r in records]
        self.assertEqual(keys, sorted(keys))

    def test_a_missing_class_sorts_without_raising(self):
        instance = self.mixed()
        instance.add((ENTITY.mystery, FACT.born, Literal("1900")))
        records = observed_relationships(schema_graph(), instance)
        self.assertIn(None, [r["subject_class"] for r in records])


class ImmutabilityTest(unittest.TestCase):
    """Case 14: neither input graph is touched."""

    def test_both_inputs_are_unchanged(self):
        schema, instance = schema_graph(), OrderingTest().mixed()
        before = (set(schema), set(instance))
        observed_relationships(schema, instance)
        self.assertEqual((set(schema), set(instance)), before)


class MiniatureRepositoryTest(unittest.TestCase):
    """The frozen miniature graph, read only."""

    def records(self):
        graph = Graph()
        graph.parse(FIXTURE_PATH, format="turtle")
        schema, instance, _ = partition_graph(graph)
        return observed_relationships(schema, instance)

    def test_the_eight_assertions_aggregate_into_four_patterns(self):
        records = self.records()
        self.assertEqual(len(records), 4)
        self.assertEqual(sum(r["occurrences"] for r in records), 8)

    def test_every_subject_and_object_class_is_specific(self):
        specific = {CLASS.person, CLASS.location, CLASS.organization}
        for record in self.records():
            self.assertIn(record["subject_class"], specific)
            if record["range_kind"] == "class":
                self.assertIn(record["range"], specific)

    def test_the_shared_literal_property_reports_two_subjects(self):
        record = only([
            r for r in self.records()
            if r["predicate"] == FACT.affects
        ])
        self.assertEqual(record["subject_class"], CLASS.location)
        self.assertEqual(record["range"], XSD.string)
        self.assertEqual(record["occurrences"], 2)
        self.assertEqual(record["distinct_subjects"], 2)
        self.assertEqual(record["class_population"], 2)
        self.assertAlmostEqual(record["coverage"], 1.0)
        self.assertEqual(record["cardinality_max"], 1)

    def test_the_repository_file_is_not_written(self):
        original = GRAPH_PATH.read_bytes()
        self.records()
        self.assertEqual(GRAPH_PATH.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
