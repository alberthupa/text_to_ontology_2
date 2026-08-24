"""Proposal 5D: the extraction prompt receives selected context, not a graph."""

import unittest
from unittest import mock

from text_to_ontology import source_parse
from text_to_ontology.graph_management import ENTITY
from text_to_ontology.source_parse import make_prompt, parse_prompt, parse_source


CONTEXT = """RELEVANT DECLARED ONTOLOGY
- [class] Policy is a kind of Entity.
- [object property] waives sanctions on: domain Policy; range Location.

OBSERVED USAGE — EVIDENCE, NOT AN ONTOLOGY RULE
- Policy --waives sanctions on--> Location
  occurrences=1; subjects=1/1; cardinality=1/1/1

RELEVANT EXISTING RESOURCES
- name: Acme Corp
  id: http://example.org/text-ontology/entity/acme-corp
  type: Entity, Company
- name: green widget
  uri: http://example.com/other/widget1 (existing resource; not usable as existing_id)

REPRESENTATIVE CURRENT ASSERTIONS
- Acme Corp --waives sanctions on--> Russia"""

SOURCE = "Acme Corp waives sanctions on Russia."


class ContextTest(unittest.TestCase):
    """Case 1: whatever context was selected is what the prompt carries."""

    def setUp(self):
        self.prompt = make_prompt(SOURCE, CONTEXT)

    def test_the_source_text_is_included(self):
        self.assertIn(SOURCE, self.prompt)

    def test_every_selected_context_line_is_included(self):
        for line in CONTEXT.split("\n"):
            self.assertIn(line, self.prompt)

    def test_the_declared_and_observed_sections_stay_distinguishable(self):
        self.assertIn("RELEVANT DECLARED ONTOLOGY", self.prompt)
        self.assertIn("EVIDENCE, NOT AN ONTOLOGY RULE", self.prompt)
        self.assertLess(self.prompt.index("RELEVANT DECLARED ONTOLOGY"),
                        self.prompt.index("EVIDENCE, NOT AN ONTOLOGY RULE"))

    def test_an_exact_existing_id_survives_intact(self):
        self.assertIn(str(ENTITY["acme-corp"]), self.prompt)

    def test_the_context_is_headed_as_a_selection(self):
        self.assertIn("ONTOLOGY CONTEXT", self.prompt)
        self.assertIn("not the whole ontology", self.prompt)

    def test_the_prompt_says_which_identifiers_may_be_reused(self):
        self.assertIn('Only an exact "id:" value', self.prompt)
        self.assertIn('A "uri:" value is', self.prompt)

    def test_the_prompt_says_observed_usage_is_not_a_rule(self):
        self.assertIn("evidence about the", self.prompt)
        self.assertIn("not a rule you must follow", self.prompt)

    def test_the_prompt_admits_the_context_is_incomplete(self):
        self.assertIn("still worth extracting", self.prompt)


class NoGlobalContextTest(unittest.TestCase):
    """Case 2: nothing is discovered from the graph in here any more."""

    def test_the_prompt_builder_takes_text_and_context_only(self):
        self.assertEqual(make_prompt(SOURCE, CONTEXT),
                         make_prompt(SOURCE, context_text=CONTEXT))

    def test_the_old_global_catalog_block_is_gone(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertNotIn("EXISTING ENTITIES:", prompt)
        self.assertNotIn("EXISTING PROPERTY NAMES", prompt)

    def test_the_module_no_longer_reaches_for_the_catalog(self):
        self.assertFalse(hasattr(source_parse, "entity_catalog"))
        with open(source_parse.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("entity_catalog", body)
        self.assertNotIn("rdflib", body)

    def test_material_that_was_not_selected_is_absent(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertNotIn(str(ENTITY["beta-corp"]), prompt)
        self.assertNotIn("birth date", prompt.split("SOURCE:")[0].replace(
            '"birth date"', ""))


class ContractTest(unittest.TestCase):
    """Case 3: the extraction contract is exactly what it was."""

    def test_the_requested_json_shape_is_unchanged(self):
        for fragment in ('"entities"', '"relations"', '"facts"', '"existing_id"',
                         '"aliases"', '"predicate"', '"value"', '"kind"',
                         "Return JSON only."):
            self.assertIn(fragment, make_prompt(SOURCE, CONTEXT))

    def test_the_entity_resolution_rule_is_unchanged(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertIn("Entity resolution is important.", prompt)
        self.assertIn("only when it is the same real thing in this context", prompt)
        self.assertIn("A similar name alone is not enough.", prompt)
        self.assertIn("Otherwise use null.", prompt)

    def test_local_response_identifiers_are_still_required(self):
        self.assertIn("Relation endpoints and fact subjects must use ids from "
                      "entities.", make_prompt(SOURCE, CONTEXT))

    def test_every_record_shape_carries_a_confidence(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertEqual(prompt.count('"confidence"'), 3)

    def test_confidence_is_defined_as_direct_source_support(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertIn("confidence from 0.0 to 1.0", prompt)
        self.assertIn("directly supports that complete record", prompt)
        self.assertIn("not confidence that an identity", prompt)
        self.assertIn("not source authority", prompt)

    def test_the_source_is_delimited(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        self.assertIn("SOURCE:\n---\n", prompt)
        self.assertTrue(prompt.endswith("---"))


class EmptyContextTest(unittest.TestCase):
    """Case 4: no context selected is a valid prompt, not a broken one."""

    def test_an_empty_context_omits_the_context_block(self):
        prompt = make_prompt(SOURCE, "")
        self.assertNotIn("ONTOLOGY CONTEXT", prompt)
        self.assertNotIn('Only an exact "id:" value', prompt)

    def test_an_empty_context_keeps_the_source_and_the_contract(self):
        prompt = make_prompt(SOURCE, "")
        self.assertIn(SOURCE, prompt)
        self.assertIn('"entities"', prompt)
        self.assertIn("Return JSON only.", prompt)
        self.assertIn("Entity resolution is important.", prompt)

    def test_a_whitespace_only_context_is_treated_as_empty(self):
        self.assertEqual(make_prompt(SOURCE, "   \n\t "), make_prompt(SOURCE, ""))

    def test_the_context_argument_is_optional(self):
        self.assertEqual(make_prompt(SOURCE), make_prompt(SOURCE, ""))

    def test_the_prompt_is_deterministic(self):
        self.assertEqual(make_prompt(SOURCE, CONTEXT), make_prompt(SOURCE, CONTEXT))


class ParseSourceTest(unittest.TestCase):
    """Case 5: the entry point sends that prompt and returns the answer."""

    def test_the_prompt_is_sent_and_the_answer_returned_unchanged(self):
        answer = {"entities": [], "relations": [], "facts": []}
        with mock.patch.object(source_parse, "ask_llm", return_value=answer) as asked:
            self.assertIs(parse_source(SOURCE, CONTEXT), answer)
        asked.assert_called_once_with(make_prompt(SOURCE, CONTEXT))

    def test_the_context_reaches_the_model(self):
        with mock.patch.object(source_parse, "ask_llm", return_value={}) as asked:
            parse_source(SOURCE, CONTEXT)
        self.assertIn(str(ENTITY["acme-corp"]), asked.call_args.args[0])

    def test_parsing_without_context_still_works(self):
        with mock.patch.object(source_parse, "ask_llm", return_value={}) as asked:
            parse_source(SOURCE)
        asked.assert_called_once_with(make_prompt(SOURCE, ""))

    def test_an_already_built_prompt_can_be_sent_without_rebuilding_it(self):
        prompt = make_prompt(SOURCE, CONTEXT)
        answer = {"entities": [], "relations": [], "facts": []}
        with mock.patch.object(source_parse, "ask_llm", return_value=answer) as asked:
            self.assertIs(parse_prompt(prompt), answer)
        asked.assert_called_once_with(prompt)


if __name__ == "__main__":
    unittest.main()
