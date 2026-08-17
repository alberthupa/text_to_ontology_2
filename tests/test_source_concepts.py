"""Proposal 5B: what one source text mentions, before any ontology is opened."""

import unittest

import source_concepts
from source_concepts import (
    MAX_CONCEPTS, extract_source_concepts, normalize, text_phrases,
)


FIELDS = {"text", "normalized", "kind", "weight", "origin", "position"}
KINDS = {"mention", "phrase", "keyword"}
ORIGINS = {"heading", "capitalized-span", "frequency"}


def forms(concepts):
    return [concept["normalized"] for concept in concepts]


def by_form(concepts, normalized):
    """The one record for a normalized form, or a readable failure."""
    found = [c for c in concepts if c["normalized"] == normalized]
    assert len(found) == 1, (normalized, forms(concepts))
    return found[0]


class RecordShapeTest(unittest.TestCase):
    """Case 1: every record carries the agreed fields and nothing else."""

    def test_each_record_has_exactly_the_agreed_fields(self):
        for concept in extract_source_concepts("Ada Lovelace wrote notes."):
            self.assertEqual(set(concept), FIELDS)

    def test_field_types_and_vocabularies_are_stable(self):
        for concept in extract_source_concepts("# Notes\nAda Lovelace wrote."):
            self.assertIsInstance(concept["text"], str)
            self.assertIsInstance(concept["normalized"], str)
            self.assertIn(concept["kind"], KINDS)
            self.assertIn(concept["origin"], ORIGINS)
            self.assertIsInstance(concept["weight"], float)
            self.assertIsInstance(concept["position"], int)

    def test_no_record_carries_an_ontology_uri(self):
        text = "Ada Lovelace works at http://example.org/text-ontology/entity/acme"
        for concept in extract_source_concepts(text):
            self.assertEqual(set(concept), FIELDS)
            self.assertNotIn("://", concept["text"])
            self.assertNotIn("://", concept["normalized"])


class BlankInputTest(unittest.TestCase):
    """Case 2: nothing said means nothing extracted."""

    def test_blank_and_whitespace_only_input_yield_no_concepts(self):
        for text in ("", "   ", "\n\n\t ", "\r\n"):
            self.assertEqual(extract_source_concepts(text), [])

    def test_punctuation_only_input_yields_no_concepts(self):
        self.assertEqual(extract_source_concepts("--- ... !!!"), [])


class DeterminismTest(unittest.TestCase):
    """Case 3: the same text always gives the same list in the same order."""

    text = "Sanctions on oil. Oil sanctions matter. Sanctions again."

    def test_repeated_runs_agree_exactly(self):
        self.assertEqual(
            extract_source_concepts(self.text), extract_source_concepts(self.text))

    def test_records_are_sorted_by_weight_then_position_then_form(self):
        concepts = extract_source_concepts(self.text)
        keys = [(-c["weight"], c["position"], c["normalized"]) for c in concepts]
        self.assertEqual(keys, sorted(keys))

    def test_equal_weight_ties_fall_back_to_position_then_form(self):
        concepts = extract_source_concepts("zebra apple\nzebra apple")
        tied = [c for c in concepts if c["kind"] == "keyword"]
        self.assertEqual([c["normalized"] for c in tied], ["zebra", "apple"])


class UnicodeTest(unittest.TestCase):
    """Case 4: non-ASCII letters are matched, not discarded."""

    def test_accented_and_non_latin_words_survive_normalization(self):
        concepts = extract_source_concepts("Łódź café Ελλάδα Москва")
        for form in ("łódź", "café", "ελλάδα", "москва"):
            self.assertIn(form, forms(concepts))

    def test_normalization_folds_case_without_stripping_accents(self):
        self.assertEqual(normalize("CAFÉ"), "café")
        self.assertEqual(normalize("Straße"), "strasse")
        self.assertEqual(normalize("  Ada   Lovelace  "), "ada lovelace")

    def test_a_script_without_case_still_produces_concepts(self):
        concepts = extract_source_concepts("会社 東京")
        self.assertGreater(len(concepts), 0)


class MentionTest(unittest.TestCase):
    """Case 5: a capitalized span is a candidate, never a claimed type."""

    def test_a_capitalized_span_is_kept_whole(self):
        concepts = extract_source_concepts("Ada Lovelace met Charles Babbage today.")
        self.assertIn("ada lovelace", forms(concepts))
        self.assertIn("charles babbage", forms(concepts))

    def test_a_mention_claims_no_semantic_type(self):
        concept = by_form(
            extract_source_concepts("Ada Lovelace met Charles Babbage today."),
            "ada lovelace")
        self.assertEqual(concept["kind"], "mention")
        self.assertNotIn("Person", concept.values())
        self.assertEqual(set(concept), FIELDS)

    def test_a_comma_does_not_join_two_mentions(self):
        concepts = extract_source_concepts("Berlin, Paris and Rome are cities.")
        self.assertNotIn("berlin paris", forms(concepts))
        self.assertIn("berlin", forms(concepts))

    def test_a_mention_outweighs_a_bare_keyword_in_the_same_position(self):
        concepts = extract_source_concepts("Ada Lovelace wrote about machinery.")
        self.assertGreater(
            by_form(concepts, "ada lovelace")["weight"],
            by_form(concepts, "machinery")["weight"])

    def test_the_display_form_keeps_the_original_capitalization(self):
        concept = by_form(
            extract_source_concepts("Ada Lovelace wrote."), "ada lovelace")
        self.assertEqual(concept["text"], "Ada Lovelace")


class WeightingTest(unittest.TestCase):
    """Case 6: headings, repetition, and early position are explicit weights."""

    def test_a_heading_term_outweighs_the_same_term_used_once_in_prose(self):
        heading = extract_source_concepts("# Sanctions\nThe report is long.")
        prose = extract_source_concepts("The report is long.\nSanctions appear late.")
        self.assertGreater(
            by_form(heading, "sanctions")["weight"],
            by_form(prose, "sanctions")["weight"])

    def test_a_heading_term_records_its_origin(self):
        concepts = extract_source_concepts("# Sanctions policy\nA long sentence here.")
        self.assertEqual(by_form(concepts, "sanctions")["origin"], "heading")

    def test_a_repeated_phrase_outweighs_a_phrase_used_once(self):
        text = ("export controls matter. export controls again. export controls once "
                "more. quiet corner exists.")
        concepts = extract_source_concepts(text)
        self.assertGreater(
            by_form(concepts, "export controls")["weight"],
            by_form(concepts, "quiet corner")["weight"])

    def test_repetition_weight_is_capped(self):
        many = extract_source_concepts(" ".join(["sanctions apply."] * 200))
        few = extract_source_concepts(" ".join(["sanctions apply."] * 8))
        self.assertEqual(
            by_form(many, "sanctions")["weight"],
            by_form(few, "sanctions")["weight"])

    def test_position_records_the_first_occurrence(self):
        concepts = extract_source_concepts("alpha beta.\nThe alpha returns later.")
        self.assertEqual(by_form(concepts, "alpha")["position"], 0)


class DeduplicationTest(unittest.TestCase):
    """Case 7: one record per normalized form, with the strongest reason."""

    def test_case_variants_collapse_into_one_record(self):
        concepts = extract_source_concepts("Sanctions matter. sanctions matter. SANCTIONS.")
        self.assertEqual(len([c for c in concepts if c["normalized"] == "sanctions"]), 1)

    def test_the_collapsed_record_keeps_the_strongest_kind(self):
        concepts = extract_source_concepts("markets fell. Markets fell again.")
        self.assertEqual(by_form(concepts, "markets")["kind"], "mention")

    def test_every_normalized_form_appears_once(self):
        concepts = extract_source_concepts(
            "# Oil sanctions\nOil sanctions on Russia. Russia answered on oil.")
        self.assertEqual(len(forms(concepts)), len(set(forms(concepts))))


class StopWordTest(unittest.TestCase):
    """Case 8: the documented minimal stop-word policy, and its limits."""

    def test_the_policy_is_documented_in_the_module(self):
        self.assertIn("stop-word", source_concepts.__doc__)
        self.assertIn("version-one", source_concepts.__doc__)

    def test_bare_function_words_are_not_concepts(self):
        concepts = extract_source_concepts("The report is on the table and it was there.")
        for form in ("the", "is", "on", "and", "it", "was"):
            self.assertNotIn(form, forms(concepts))

    def test_a_phrase_neither_starts_nor_ends_with_a_function_word(self):
        for form in forms(extract_source_concepts("The price of oil is high today.")):
            self.assertFalse(form.startswith("the "), form)
            self.assertFalse(form.endswith(" of"), form)

    def test_a_function_word_inside_a_phrase_is_kept(self):
        concepts = extract_source_concepts("The price of oil is high today.")
        self.assertIn("price of oil", forms(concepts))


class CapTest(unittest.TestCase):
    """Case 9: cost stays bounded however long the source is."""

    def test_the_concept_cap_holds_on_oversized_input(self):
        text = " ".join(f"term{index} follows here." for index in range(4000))
        concepts = extract_source_concepts(text)
        self.assertEqual(len(concepts), MAX_CONCEPTS)

    def test_phrases_never_exceed_the_configured_length(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        for concept in extract_source_concepts(text):
            self.assertLessEqual(
                len(concept["normalized"].split()), source_concepts.MAX_MENTION_TOKENS)

    def test_a_very_long_source_still_returns_promptly_and_bounded(self):
        concepts = extract_source_concepts("Sanctions on oil. " * 20000)
        self.assertLessEqual(len(concepts), MAX_CONCEPTS)


class IndependenceTest(unittest.TestCase):
    """Case 10: this module knows nothing about RDF or model transport."""

    def test_the_module_imports_neither_rdflib_nor_the_llm_transport(self):
        source = source_concepts.__file__
        with open(source, encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("rdflib", body)
        self.assertNotIn("import llm", body)
        self.assertNotIn("from llm", body)

    def test_extraction_needs_no_graph_argument(self):
        self.assertGreater(len(extract_source_concepts("Oil sanctions bite.")), 0)


class PhraseIndexTest(unittest.TestCase):
    """Case 11: the matching index used by task context, kept RDF-free here."""

    def test_a_label_matches_only_at_word_boundaries(self):
        phrases = text_phrases("The particle accelerator runs.")
        self.assertIn("particle accelerator", phrases)
        self.assertNotIn("art", phrases)

    def test_the_index_reports_the_first_position(self):
        phrases = text_phrases("oil rises. oil falls.")
        self.assertEqual(phrases["oil"], 0)

    def test_case_and_punctuation_do_not_prevent_a_match(self):
        phrases = text_phrases("Waives Sanctions On Russia, today.")
        self.assertIn("waives sanctions on", phrases)

    def test_a_run_broken_by_punctuation_is_not_a_phrase(self):
        phrases = text_phrases("Berlin, Paris")
        self.assertNotIn("berlin paris", phrases)

    def test_an_empty_text_has_an_empty_index(self):
        self.assertEqual(text_phrases(""), {})


if __name__ == "__main__":
    unittest.main()
