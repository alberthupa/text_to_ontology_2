"""Proposal 06: validating and normalizing candidate packages before merge."""

import math
import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from text_to_ontology import candidate_validation
from text_to_ontology.candidate_validation import (
    format_validation_failure, normalize_oneline, normalize_text,
    validate_candidates,
)
from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION


RESULT_FIELDS = {"valid", "candidates", "issues", "counts"}
ISSUE_FIELDS = {"code", "severity", "path", "related_paths", "message"}
COUNT_FIELDS = {"input", "normalized", "duplicates_removed", "normalized_fields",
                "errors", "warnings"}
SECTION_COUNTS = {"entities", "relations", "facts"}
DUP_COUNTS = {"entities", "relations", "facts", "aliases"}


def add_entity(graph, local, name, kind, aliases=(), description=""):
    """Write one catalog-visible entity the way the merge step writes it."""
    uri = ENTITY[local]
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    graph.add((uri, ONTO.kind, Literal(kind)))
    for alias in aliases:
        graph.add((uri, SKOS.altLabel, Literal(alias)))
    if description:
        graph.add((uri, RDFS.comment, Literal(description)))
    return uri


def entity(identifier, name, kind="Company", description="", aliases=(),
           existing_id=None, confidence=0.9):
    return {"id": identifier, "name": name, "kind": kind,
            "description": description, "aliases": list(aliases),
            "existing_id": existing_id, "confidence": confidence}


VALID_PACKAGE = {
    "entities": [entity("e1", "Acme Corp"), entity("e2", "Ada Lovelace",
                                                   kind="Person")],
    "relations": [{"subject": "e1", "predicate": "employs", "object": "e2", "confidence": 0.9}],
    "facts": [{"subject": "e2", "predicate": "birth date",
               "value": "1815-12-10", "confidence": 0.9}],
}


def issue_codes(result, severity=None):
    return [issue["code"] for issue in result["issues"]
            if severity is None or issue["severity"] == severity]


class ResultShapeTest(unittest.TestCase):
    """6A.3: the result, issue, and counts field sets are pinned."""

    def test_generic_kind_checks_the_canonical_root_uri_for_collisions(self):
        graph = Graph()
        graph.add((ONTO.Entity, RDF.type, OWL.ObjectProperty))
        result = validate_candidates({
            "entities": [entity("e1", "A thing", kind="Entity")],
            "relations": [], "facts": [],
        }, graph)
        self.assertFalse(result["valid"])
        self.assertIn("kind.role_collision", issue_codes(result))

    def test_valid_result_has_exactly_the_agreed_fields(self):
        result = validate_candidates(dict(VALID_PACKAGE), Graph())
        self.assertEqual(set(result), RESULT_FIELDS)
        self.assertEqual(set(result["counts"]), COUNT_FIELDS)
        self.assertEqual(set(result["counts"]["input"]), SECTION_COUNTS)
        self.assertEqual(set(result["counts"]["normalized"]), SECTION_COUNTS)
        self.assertEqual(set(result["counts"]["duplicates_removed"]), DUP_COUNTS)

    def test_every_issue_has_exactly_the_agreed_fields(self):
        result = validate_candidates({"entities": [{"id": "e1"}], "relations": [],
                                      "facts": []}, Graph())
        for issue in result["issues"]:
            self.assertEqual(set(issue), ISSUE_FIELDS)

    def test_a_valid_result_keeps_the_three_section_public_shape(self):
        result = validate_candidates(dict(VALID_PACKAGE), Graph())
        self.assertEqual(set(result["candidates"]), {"entities", "relations", "facts"})


class ContainerTest(unittest.TestCase):
    """6A.4, 6A.5: the top-level value and its sections."""

    def test_a_non_mapping_response_is_rejected(self):
        for value in (None, [], "x", 3, True):
            result = validate_candidates(value, Graph())
            self.assertFalse(result["valid"])
            self.assertIsNone(result["candidates"])
            self.assertIn("structure.not_mapping", issue_codes(result))
            self.assertEqual(result["counts"]["errors"], 1)

    def test_a_missing_section_is_an_error(self):
        result = validate_candidates({"entities": [], "relations": []}, Graph())
        self.assertFalse(result["valid"])
        self.assertIn("structure.missing_section", issue_codes(result))

    def test_an_unknown_top_level_field_is_an_error(self):
        result = validate_candidates(
            {"entities": [], "relations": [], "facts": [], "notes": []}, Graph())
        self.assertFalse(result["valid"])
        self.assertIn("structure.unknown_section", issue_codes(result))

    def test_a_non_list_section_is_an_error(self):
        result = validate_candidates(
            {"entities": [], "relations": {}, "facts": []}, Graph())
        self.assertFalse(result["valid"])
        self.assertIn("structure.section_not_list", issue_codes(result))

    def test_a_container_failure_exposes_no_candidates(self):
        result = validate_candidates({"entities": "nope"}, Graph())
        self.assertIsNone(result["candidates"])


class RecordShapeTest(unittest.TestCase):
    """6A.6, 6A.8: records and their fields."""

    def test_a_non_mapping_record_is_rejected(self):
        result = validate_candidates(
            {"entities": [None], "relations": ["x"], "facts": [42]}, Graph())
        for code in ("entity.not_mapping", "relation.not_mapping",
                     "fact.not_mapping"):
            self.assertIn(code, issue_codes(result))

    def test_unknown_entity_relation_and_fact_fields_are_errors(self):
        result = validate_candidates({
            "entities": [dict(entity("e1", "Acme"), extra=1)],
            "relations": [{"subject": "e1", "predicate": "p", "object": "e1",
                           "extra": 2, "confidence": 0.9}],
            "facts": [{"subject": "e1", "predicate": "p", "value": "x",
                       "extra": 3, "confidence": 0.9}],
        }, Graph())
        self.assertIn("entity.unknown_field", issue_codes(result))
        self.assertIn("relation.unknown_field", issue_codes(result))
        self.assertIn("fact.unknown_field", issue_codes(result))


class IdentifierTest(unittest.TestCase):
    """6A.9: ids are strings and follow the local-ID grammar."""

    def grammar_cases(self):
        yield "e1", True
        yield "E1", True
        yield "entity_2", True
        yield "entity-2", True
        yield "a", True
        yield "2e", False
        yield "_e", False
        yield "e 1", False
        yield "e.1", False
        yield "", False
        yield "http://x", False

    def test_the_grammar_accepts_and_rejects_as_documented(self):
        for identifier, accepted in self.grammar_cases():
            result = validate_candidates(
                {"entities": [entity(identifier, "Acme")],
                 "relations": [], "facts": []}, Graph())
            if accepted:
                self.assertTrue(result["valid"], identifier)
            else:
                self.assertFalse(result["valid"], identifier)
                self.assertIn("entity.invalid_id", issue_codes(result))

    def test_a_non_string_id_is_never_coerced(self):
        for identifier in (1, 1.5, True, None, [], {}):
            result = validate_candidates(
                {"entities": [entity(identifier, "Acme")],
                 "relations": [], "facts": []}, Graph())
            self.assertFalse(result["valid"])
            self.assertIn("entity.invalid_id", issue_codes(result))


class NormalizationTest(unittest.TestCase):
    """6A.10, 6A.13, 6A.17: deterministic and conservative normalization."""

    def test_nfkc_and_whitespace_are_applied_to_names(self):
        result = validate_candidates(
            {"entities": [{"id": "e1", "name": "  Caf\u00e9 \u3000Corp  ",
                            "confidence": 0.9}],
             "relations": [], "facts": []}, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["name"],
                         "Caf\u00e9 Corp")

    def test_line_endings_and_control_characters_are_removed(self):
        result = validate_candidates({
            "entities": [{
                "id": "e1",
                "name": "We\x07ird\r\nNa\u0000me",
                "description": "first\r\nsecond\x01lin\u007fe",
                "confidence": 0.9,
            }],
            "relations": [], "facts": [],
        }, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["name"],
                         "We ird Na me")
        self.assertEqual(result["candidates"]["entities"][0]["description"],
                         "first\nsecond lin e")

    def test_description_keeps_meaningful_internal_whitespace(self):
        description = "a   line\n\n  with\tspaces  "
        result = validate_candidates(
            {"entities": [entity("e1", "Acme", description=description)],
             "relations": [], "facts": []}, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["description"],
                         "a   line\n\n  with\tspaces")

    def test_a_date_looking_string_is_not_coerced(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "born",
                       "value": "1950-01-01", "confidence": 0.9}],
        }, Graph())
        value = result["candidates"]["facts"][0]["value"]
        self.assertIsInstance(value, str)
        self.assertEqual(value, "1950-01-01")

    def test_a_numeric_looking_string_is_not_coerced(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "code", "value": "42", "confidence": 0.9}],
        }, Graph())
        self.assertIsInstance(result["candidates"]["facts"][0]["value"], str)


class KindTest(unittest.TestCase):
    """6A.11: a missing or empty kind becomes Entity with a warning."""

    def test_a_missing_kind_defaults_to_entity(self):
        result = validate_candidates(
            {"entities": [{"id": "e1", "name": "Acme", "confidence": 0.9}],
             "relations": [], "facts": []}, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(result["candidates"]["entities"][0]["kind"], "Entity")
        self.assertIn("entity.kind_defaulted", issue_codes(result, "warning"))

    def test_an_empty_kind_defaults_to_entity(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme", kind="  ")],
             "relations": [], "facts": []}, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["kind"], "Entity")
        self.assertIn("entity.kind_defaulted", issue_codes(result, "warning"))

    def test_a_non_string_kind_is_an_error(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme", kind=5)],
             "relations": [], "facts": []}, Graph())
        self.assertIn("entity.invalid_kind", issue_codes(result))


class AliasTest(unittest.TestCase):
    """6A.12: alias normalization, order, and removal of empty/duplicate/name."""

    def test_aliases_are_normalized_ordered_and_deduplicated(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme Corp",
                                aliases=["ACME", "  acme ", "", "  ACME  ",
                                         "Acme Corp"])],
            "relations": [], "facts": [],
        }, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["aliases"],
                         ["ACME", "acme"])
        self.assertEqual(result["counts"]["duplicates_removed"]["aliases"], 3)

    def test_an_alias_equal_to_the_name_is_removed(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme", aliases=["Acme"])],
            "relations": [], "facts": [],
        }, Graph())
        self.assertEqual(result["candidates"]["entities"][0]["aliases"], [])

    def test_non_list_aliases_are_an_error(self):
        result = validate_candidates(
            {"entities": [{"id": "e1", "name": "Acme", "aliases": "ACME",
                            "confidence": 0.9}],
             "relations": [], "facts": []}, Graph())
        self.assertIn("entity.invalid_aliases", issue_codes(result))


class LiteralTypeTest(unittest.TestCase):
    """6A.14, 6A.15, 6A.16: supported literals and the typed-key rule."""

    def test_supported_literal_types_are_preserved(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [
                {"subject": "e1", "predicate": "s", "value": "x", "confidence": 0.9},
                {"subject": "e1", "predicate": "b", "value": True, "confidence": 0.9},
                {"subject": "e1", "predicate": "i", "value": 7, "confidence": 0.9},
                {"subject": "e1", "predicate": "f", "value": 1.5, "confidence": 0.9},
            ],
        }, Graph())
        types = [type(fact["value"]).__name__
                 for fact in result["candidates"]["facts"]]
        self.assertEqual(types, ["str", "bool", "int", "float"])

    def test_string_1_integer_1_and_boolean_true_stay_distinct(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [
                {"subject": "e1", "predicate": "v", "value": "1", "confidence": 0.9},
                {"subject": "e1", "predicate": "v", "value": 1, "confidence": 0.9},
                {"subject": "e1", "predicate": "v", "value": True, "confidence": 0.9},
            ],
        }, Graph())
        values = [fact["value"] for fact in result["candidates"]["facts"]]
        self.assertEqual(len(values), 3)
        self.assertIn("1", values)
        self.assertIn(1, values)
        self.assertIn(True, values)

    def test_unsupported_fact_values_are_rejected(self):
        for value in (None, [], {}, float("nan"), float("inf")):
            result = validate_candidates({
                "entities": [entity("e1", "Acme")],
                "relations": [],
                "facts": [{"subject": "e1", "predicate": "v", "value": value, "confidence": 0.9}],
            }, Graph())
            self.assertFalse(result["valid"], repr(value))
            self.assertIn("fact.invalid_value", issue_codes(result))


class PredicateTest(unittest.TestCase):
    """6A.18, 6A.19: predicate labels and URI-looking input."""

    def test_an_empty_predicate_is_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [{"subject": "e1", "predicate": "", "object": "e1", "confidence": 0.9}],
            "facts": [{"subject": "e1", "predicate": "   ", "value": "x", "confidence": 0.9}],
        }, Graph())
        self.assertIn("relation.empty_predicate", issue_codes(result))
        self.assertIn("fact.empty_predicate", issue_codes(result))

    def test_a_predicate_with_no_usable_local_name_is_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [{"subject": "e1", "predicate": "!!!", "object": "e1", "confidence": 0.9}],
            "facts": [],
        }, Graph())
        self.assertIn("relation.unnamed_predicate", issue_codes(result))

    def test_a_uri_looking_predicate_is_an_error(self):
        for predicate in ("http://example.org/worksFor", "ex:worksFor"):
            result = validate_candidates({
                "entities": [entity("e1", "Acme")],
                "relations": [{"subject": "e1", "predicate": predicate,
                               "object": "e1", "confidence": 0.9}],
                "facts": [],
            }, Graph())
            self.assertFalse(result["valid"], predicate)
            self.assertIn("relation.uri_predicate", issue_codes(result))

    def test_unicode_direction_is_unchanged(self):
        self.assertEqual(normalize_oneline("\u00e9"), "\u00e9")
        self.assertEqual(normalize_text("\u00e9"), "\u00e9")


class FallthroughTest(unittest.TestCase):
    """6A.21, 6A.22: invalid results cannot merge, inputs are not mutated."""

    def test_an_invalid_result_exposes_no_mergeable_candidates(self):
        result = validate_candidates(
            {"entities": [{"id": "bad id", "name": "Acme", "confidence": 0.9}],
             "relations": [], "facts": []}, Graph())
        self.assertFalse(result["valid"])
        self.assertIsNone(result["candidates"])

    def test_the_input_is_not_mutated(self):
        data = {
            "entities": [entity("e1", "  Acme   ", aliases=[" ACME "])],
            "relations": [{"subject": "e1", "predicate": "  p  ", "object": "e1", "confidence": 0.9}],
            "facts": [{"subject": "e1", "predicate": "  f ", "value": "  x ", "confidence": 0.9}],
        }
        before = repr(data)
        validate_candidates(data, Graph())
        self.assertEqual(repr(data), before)


class ExistingIdTest(unittest.TestCase):
    """6B.1 to 6B.7: explicit existing_id handling."""

    def setUp(self):
        self.graph = Graph()
        self.uri = add_entity(self.graph, "acme-corp", "Acme Corp", "Company")
        self.allowed = [str(self.uri)]

    def test_a_rendered_and_present_id_is_accepted(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp", existing_id=str(self.uri))],
             "relations": [], "facts": []},
            self.graph, self.allowed)
        self.assertTrue(result["valid"])
        self.assertEqual(result["candidates"]["entities"][0]["existing_id"],
                         str(self.uri))

    def test_an_id_absent_from_the_prompt_is_rejected(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp", existing_id=str(self.uri))],
             "relations": [], "facts": []},
            self.graph, [])
        self.assertFalse(result["valid"])
        self.assertIn("entity.existing_id_not_allowed", issue_codes(result))

    def test_an_allowed_id_missing_from_the_graph_is_rejected(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp",
                                 existing_id=str(ENTITY["ghost"]))],
             "relations": [], "facts": []},
            self.graph, [str(ENTITY["ghost"])])
        self.assertFalse(result["valid"])
        self.assertIn("entity.existing_id_not_allowed", issue_codes(result))

    def test_a_null_existing_id_is_left_for_merge_time_fallback(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp", existing_id=None)],
             "relations": [], "facts": []},
            self.graph, self.allowed)
        self.assertTrue(result["valid"])
        self.assertIsNone(result["candidates"]["entities"][0]["existing_id"])

    def test_a_matching_kind_is_compatible(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp", kind="company",
                                 existing_id=str(self.uri))],
             "relations": [], "facts": []},
            self.graph, self.allowed)
        self.assertTrue(result["valid"])

    def test_a_mismatching_kind_is_an_error(self):
        result = validate_candidates(
            {"entities": [entity("e1", "Acme Corp", kind="Person",
                                 existing_id=str(self.uri))],
             "relations": [], "facts": []},
            self.graph, self.allowed)
        self.assertFalse(result["valid"])
        self.assertIn("entity.existing_id_kind_mismatch", issue_codes(result))

    def test_two_ids_claiming_one_existing_id_is_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme", existing_id=str(self.uri)),
                         entity("e2", "Other", existing_id=str(self.uri))],
            "relations": [], "facts": [],
        }, self.graph, self.allowed)
        self.assertIn("entity.duplicate_existing_id", issue_codes(result))


class EntityDuplicateTest(unittest.TestCase):
    """6B.8, 6B.9, 6B.10: repeated and conflicting local records."""

    def test_identical_repeated_records_are_deduplicated(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e1", "Acme")],
            "relations": [], "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["entities"]), 1)
        self.assertIn("entity.duplicate_record", issue_codes(result, "warning"))

    def test_conflicting_records_under_one_id_are_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e1", "Beta")],
            "relations": [], "facts": [],
        }, Graph())
        self.assertIn("entity.duplicate_id", issue_codes(result))


class ReferenceTest(unittest.TestCase):
    """6B.11, 6B.12, 6B.13: relation and fact references."""

    def test_unknown_references_are_errors(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [{"subject": "e1", "predicate": "p", "object": "ghost", "confidence": 0.9},
                          {"subject": "ghost", "predicate": "p", "object": "e1", "confidence": 0.9}],
            "facts": [{"subject": "ghost", "predicate": "f", "value": "x", "confidence": 0.9}],
        }, Graph())
        self.assertIn("relation.unknown_object", issue_codes(result))
        self.assertIn("relation.unknown_subject", issue_codes(result))
        self.assertIn("fact.unknown_subject", issue_codes(result))

    def test_a_reference_to_an_invalid_entity_is_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("bad id", "Beta")],
            "relations": [{"subject": "e1", "predicate": "p", "object": "bad id", "confidence": 0.9}],
            "facts": [],
        }, Graph())
        self.assertIn("relation.unknown_object", issue_codes(result))

    def test_a_self_relation_is_valid(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [{"subject": "e1", "predicate": "owns", "object": "e1", "confidence": 0.9}],
            "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])


class AssertionDuplicateTest(unittest.TestCase):
    """6B.14, 6B.15, 6B.16: assertion duplicates with typed keys."""

    def test_relation_duplicates_are_removed_after_normalization(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [
                {"subject": "e1", "predicate": "works for", "object": "e2", "confidence": 0.9},
                {"subject": "e1", "predicate": "  works  for ", "object": "e2", "confidence": 0.9},
            ],
            "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["relations"]), 1)
        self.assertIn("relation.duplicate", issue_codes(result, "warning"))

    def test_fact_duplicates_use_typed_keys(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "n", "value": 1, "confidence": 0.9},
                      {"subject": "e1", "predicate": "n", "value": 1, "confidence": 0.9}],
        }, Graph())
        self.assertEqual(len(result["candidates"]["facts"]), 1)

    def test_duplicate_warnings_name_kept_and_removed_paths(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [
                {"subject": "e1", "predicate": "p", "object": "e2", "confidence": 0.9},
                {"subject": "e1", "predicate": "p", "object": "e2", "confidence": 0.9},
            ],
            "facts": [],
        }, Graph())
        duplicate = next(i for i in result["issues"]
                         if i["code"] == "relation.duplicate")
        self.assertEqual(duplicate["path"], "relations[1].predicate")
        self.assertEqual(duplicate["related_paths"], ["relations[0].predicate"])


class GraphDuplicateTest(unittest.TestCase):
    """Proposal 07A: graph-exact assertions are retained for merge planning."""

    def setUp(self):
        self.graph = Graph()
        self.acme = add_entity(self.graph, "acme-corp", "Acme Corp", "Company")
        self.ada = add_entity(self.graph, "ada-lovelace", "Ada Lovelace", "Person")
        self.graph.add((self.acme, RELATION["employs"], self.ada))
        self.graph.add((self.ada, FACT["birth-date"], Literal("1815-12-10")))
        self.allowed = [str(self.acme), str(self.ada)]

    def test_an_existing_relation_is_retained_for_planning(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme Corp", existing_id=str(self.acme)),
                         entity("e2", "Ada Lovelace", kind="Person",
                                existing_id=str(self.ada))],
            "relations": [{"subject": "e1", "predicate": "employs",
                           "object": "e2", "confidence": 0.9}],
            "facts": [],
        }, self.graph, self.allowed)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["relations"]), 1)
        self.assertEqual(result["counts"]["duplicates_removed"]["relations"], 0)
        self.assertNotIn("relation.graph_duplicate", issue_codes(result))

    def test_an_existing_fact_is_retained_for_planning(self):
        result = validate_candidates({
            "entities": [entity("e1", "Ada Lovelace", kind="Person",
                                existing_id=str(self.ada))],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "birth date",
                       "value": "1815-12-10", "confidence": 0.9}],
        }, self.graph, self.allowed)
        self.assertEqual(len(result["candidates"]["facts"]), 1)
        self.assertEqual(result["counts"]["duplicates_removed"]["facts"], 0)
        self.assertNotIn("fact.graph_duplicate", issue_codes(result))

    def test_validation_does_not_import_identity_search(self):
        with open(candidate_validation.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("identify_entity", body)


class CollisionTest(unittest.TestCase):
    """6B.20 to 6B.26: generated-URI role and label collisions."""

    def test_a_relation_uri_already_typed_as_datatype_is_an_error(self):
        graph = Graph()
        graph.add((RELATION["works-for"], RDF.type, OWL.DatatypeProperty))
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [{"subject": "e1", "predicate": "works for",
                           "object": "e2", "confidence": 0.9}],
            "facts": [],
        }, graph)
        self.assertFalse(result["valid"])
        self.assertIn("relation.type_collision", issue_codes(result))

    def test_a_fact_uri_already_typed_as_object_is_an_error(self):
        graph = Graph()
        graph.add((FACT["birth-date"], RDF.type, OWL.ObjectProperty))
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "birth date",
                       "value": "x", "confidence": 0.9}],
        }, graph)
        self.assertIn("fact.type_collision", issue_codes(result))

    def test_a_kind_uri_used_as_a_property_is_an_error(self):
        graph = Graph()
        graph.add((CLASS["company"], RDF.type, OWL.ObjectProperty))
        result = validate_candidates(
            {"entities": [entity("e1", "Acme", kind="Company")],
             "relations": [], "facts": []}, graph)
        self.assertIn("kind.role_collision", issue_codes(result))

    def test_a_kind_uri_used_as_an_entity_is_an_error(self):
        graph = Graph()
        graph.add((CLASS["company"], RDF.type, ONTO.Entity))
        result = validate_candidates(
            {"entities": [entity("e1", "Acme", kind="Company")],
             "relations": [], "facts": []}, graph)
        self.assertIn("kind.role_collision", issue_codes(result))

    def test_a_compatible_existing_property_is_accepted(self):
        graph = Graph()
        graph.add((RELATION["works-for"], RDF.type, OWL.ObjectProperty))
        graph.add((RELATION["works-for"], RDFS.label, Literal("works for")))
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [{"subject": "e1", "predicate": "works for",
                           "object": "e2", "confidence": 0.9}],
            "facts": [],
        }, graph)
        self.assertTrue(result["valid"])

    def test_spellings_that_share_a_label_and_uri_are_deduplicated(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [
                {"subject": "e1", "predicate": "works for", "object": "e2", "confidence": 0.9},
                {"subject": "e1", "predicate": "works-for", "object": "e2", "confidence": 0.9},
            ],
            "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["relations"]), 1)

    def test_distinct_labels_colliding_under_slug_are_an_error(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [
                {"subject": "e1", "predicate": "birth date", "object": "e2", "confidence": 0.9},
                {"subject": "e1", "predicate": "birth.date", "object": "e2", "confidence": 0.9},
            ],
            "facts": [],
        }, Graph())
        self.assertIn("relation.label_collision", issue_codes(result))

    def test_a_genuinely_new_predicate_is_accepted(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [{"subject": "e1", "predicate": "completely new",
                           "object": "e2", "confidence": 0.9}],
            "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])

    def test_differing_values_are_not_contradictory(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "email",
                       "value": "a@example.com", "confidence": 0.9},
                      {"subject": "e1", "predicate": "email",
                       "value": "b@example.com", "confidence": 0.9}],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["facts"]), 2)


class ConfidenceTest(unittest.TestCase):
    """Proposal 07A: required per-record extraction confidence."""

    def package(self, entity_confidence=0.9, relation_confidence=0.9,
                fact_confidence=0.9):
        relations = [{"subject": "e1", "predicate": "p", "object": "e2"}]
        facts = [{"subject": "e2", "predicate": "f", "value": "x"}]
        if relation_confidence is not None:
            for record in relations:
                record["confidence"] = relation_confidence
        if fact_confidence is not None:
            for record in facts:
                record["confidence"] = fact_confidence
        entities = [entity("e1", "Acme"), entity("e2", "Beta")]
        if entity_confidence is None:
            for record in entities:
                record.pop("confidence")
        else:
            for record in entities:
                record["confidence"] = entity_confidence
        return {"entities": entities, "relations": relations, "facts": facts}

    def test_boundary_values_are_accepted_and_normalized(self):
        for value in (0, 1, 0.80, 0.79, 0.81):
            result = validate_candidates(self.package(entity_confidence=value),
                                         Graph())
            self.assertTrue(result["valid"], repr(value))
            self.assertEqual(
                result["candidates"]["entities"][0]["confidence"],
                float(value))
            self.assertIsInstance(
                result["candidates"]["entities"][0]["confidence"], float)

    def test_integer_and_float_inputs_normalize_to_one_representation(self):
        one = validate_candidates(self.package(entity_confidence=1), Graph())
        two = validate_candidates(self.package(entity_confidence=1.0), Graph())
        self.assertEqual(
            one["candidates"]["entities"][0]["confidence"],
            two["candidates"]["entities"][0]["confidence"])

    def test_a_missing_confidence_rejects_the_record(self):
        for section, code in (("entity_confidence", "entity.missing_confidence"),
                              ("relation_confidence",
                               "relation.missing_confidence"),
                              ("fact_confidence", "fact.missing_confidence")):
            result = validate_candidates(
                self.package(**{section: None}), Graph())
            self.assertFalse(result["valid"], code)
            self.assertIn(code, issue_codes(result))

    def test_invalid_confidence_values_are_rejected_with_exact_paths(self):
        for value in ("0.9", True, False, -0.1, 1.1, float("nan"),
                      float("inf"), [0.5]):
            result = validate_candidates(
                self.package(entity_confidence=value), Graph())
            self.assertFalse(result["valid"], repr(value))
            issue = next(issue for issue in result["issues"]
                         if issue["code"] == "entity.invalid_confidence")
            self.assertEqual(issue["path"],
                             f"entities[0].confidence")

    def test_invalid_relation_and_fact_confidence_paths(self):
        result = validate_candidates(
            self.package(relation_confidence="x", fact_confidence=2.0), Graph())
        codes = issue_codes(result)
        self.assertIn("relation.invalid_confidence", codes)
        self.assertIn("fact.invalid_confidence", codes)

    def test_duplicate_entity_records_keep_the_lower_confidence(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme", confidence=0.9),
                         entity("e1", "Acme", confidence=0.5)],
            "relations": [], "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["entities"]), 1)
        self.assertEqual(result["candidates"]["entities"][0]["confidence"], 0.5)
        warning = next(issue for issue in result["issues"]
                       if issue["code"] == "entity.duplicate_confidence")
        self.assertEqual(warning["path"], "entities[1].confidence")
        self.assertEqual(warning["related_paths"], ["entities[0].confidence"])

    def test_duplicate_assertions_keep_the_lower_confidence(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e2", "Beta")],
            "relations": [
                {"subject": "e1", "predicate": "p", "object": "e2",
                 "confidence": 0.9},
                {"subject": "e1", "predicate": "p", "object": "e2",
                 "confidence": 0.4},
            ],
            "facts": [],
        }, Graph())
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["candidates"]["relations"]), 1)
        self.assertEqual(result["candidates"]["relations"][0]["confidence"], 0.4)
        warning = next(issue for issue in result["issues"]
                       if issue["code"] == "relation.duplicate_confidence")
        self.assertEqual(warning["path"], "relations[1].confidence")
        self.assertEqual(warning["related_paths"], ["relations[0].confidence"])

    def test_identical_duplicates_do_not_warn_about_confidence(self):
        result = validate_candidates({
            "entities": [entity("e1", "Acme"), entity("e1", "Acme")],
            "relations": [], "facts": [],
        }, Graph())
        self.assertNotIn("entity.duplicate_confidence", issue_codes(result))

    def test_every_normalized_candidate_carries_confidence(self):
        result = validate_candidates(dict(VALID_PACKAGE), Graph())
        for section in ("entities", "relations", "facts"):
            for record in result["candidates"][section]:
                self.assertIn("confidence", record)
                self.assertIsInstance(record["confidence"], float)


class ImmutabilityTest(unittest.TestCase):
    """6B.28, 6B.29: determinism and read-only graph guarantees."""

    def sample(self):
        graph = Graph()
        add_entity(graph, "acme-corp", "Acme Corp", "Company")
        graph.add((RELATION["works-for"], RDF.type, OWL.DatatypeProperty))
        return graph

    def test_the_source_graph_is_triple_identical_after_validation(self):
        graph = self.sample()
        before = set(graph)
        validate_candidates({
            "entities": [entity("e1", "Acme", kind="Company")],
            "relations": [{"subject": "e1", "predicate": "works for",
                           "object": "e1", "confidence": 0.9}],
            "facts": [],
        }, graph, [])
        self.assertEqual(set(graph), before)
        self.assertEqual(len(graph), len(before))

    def test_insertion_order_does_not_change_output(self):
        first = Graph()
        second = Graph()
        for a, b in (((RELATION["x"], RDF.type, OWL.ObjectProperty),
                      (RELATION["y"], RDF.type, OWL.DatatypeProperty)),
                     ((RELATION["y"], RDF.type, OWL.DatatypeProperty),
                      (RELATION["x"], RDF.type, OWL.ObjectProperty))):
            first.add(a)
            second.add(b)
        data = {
            "entities": [entity("e1", "Acme")],
            "relations": [{"subject": "e1", "predicate": "x", "object": "e1", "confidence": 0.9}],
            "facts": [],
        }
        one = validate_candidates(data, first)
        two = validate_candidates(data, second)
        self.assertEqual(one["issues"], two["issues"])
        self.assertEqual(one["counts"], two["counts"])


class FormatFailureTest(unittest.TestCase):
    """format_validation_failure is concise and deterministic."""

    def test_the_message_lists_codes_and_paths(self):
        result = validate_candidates(
            {"entities": [{"id": "e1"}], "relations": [], "facts": []}, Graph())
        message = format_validation_failure(result)
        self.assertIn("validation error(s)", message)
        self.assertIn("entity.missing_name", message)
        self.assertIn("entities[0]", message)

    def test_the_message_is_deterministic(self):
        data = {"entities": [{"id": "e1"}, {"id": "e2"}],
                "relations": [], "facts": []}
        one = format_validation_failure(validate_candidates(data, Graph()))
        two = format_validation_failure(validate_candidates(data, Graph()))
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
