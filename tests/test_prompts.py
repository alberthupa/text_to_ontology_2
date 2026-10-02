"""Editable prompt templates: defaults, validation, overrides, rendering."""

import json
import tempfile
import unittest
from pathlib import Path

from text_to_ontology import prompts
from text_to_ontology.prompts import PromptLibrary
from text_to_ontology.source_parse import make_prompt, parse_source
from text_to_ontology.starter import starter_prompt


class DefaultsTest(unittest.TestCase):
    def setUp(self):
        self.library = PromptLibrary()

    def test_every_prompt_has_a_default_and_a_valid_template(self):
        self.assertEqual(self.library.names(),
                         ["chat_system", "chat_user", "extraction_system",
                          "extraction_user", "starter"])
        for name in self.library.names():
            self.assertIsNone(self.library.validate(name, self.library.text(name)),
                              name)
            self.assertTrue(self.library.is_default(name), name)

    def test_a_missing_value_is_a_clear_error(self):
        with self.assertRaises(ValueError) as caught:
            self.library.render("starter")
        self.assertIn("min_classes", str(caught.exception))
        self.assertIn("this template needs", str(caught.exception))

    def test_an_unknown_prompt_name_is_a_clear_error(self):
        with self.assertRaises(KeyError) as caught:
            self.library.text("nope")
        self.assertIn("unknown prompt", str(caught.exception))
        self.assertIn("extraction_user", str(caught.exception))

    def test_the_digest_is_stable_and_text_dependent(self):
        self.assertEqual(self.library.digest("extraction_user"),
                         PromptLibrary().digest("extraction_user"))
        self.assertNotEqual(self.library.digest("extraction_user"),
                            self.library.digest("extraction_system"))

    def test_the_module_helpers_use_the_defaults(self):
        self.assertEqual(prompts.describe(), self.library.describe())
        self.assertEqual(prompts.digest("extraction_system"),
                         self.library.digest("extraction_system"))
        self.assertEqual(prompts.render("extraction_system"),
                         "Extract knowledge. Return only JSON.")


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.library = PromptLibrary()
        self.good = self.library.text("extraction_user")

    def test_the_defaults_pass(self):
        for name in self.library.names():
            self.assertIsNone(self.library.validate(name, self.library.text(name)))

    def test_an_empty_template_is_refused(self):
        self.assertIn("empty", self.library.validate("extraction_user", "   "))

    def test_a_missing_required_placeholder_is_refused(self):
        error = self.library.validate("extraction_user", "just words")
        self.assertIn("$context", error)
        self.assertIn("$text", error)

    def test_an_unknown_placeholder_is_refused(self):
        error = self.library.validate("extraction_user",
                                      "${context} ${text} ${sneaky}")
        self.assertIn("$sneaky", error)
        self.assertIn("may use", error)

    def test_a_bare_dollar_is_refused_but_an_escaped_one_is_fine(self):
        self.assertIn("literal dollar",
                      self.library.validate("extraction_user",
                                            "${context} ${text} costs $5"))
        self.assertIsNone(self.library.validate(
            "extraction_user", "${context} ${text} costs $$5"))

    def test_advice_warns_about_a_broken_answer_shape(self):
        advice = self.library.advice("extraction_user", "${context} ${text}")
        self.assertTrue(any("entities" in line for line in advice), advice)
        self.assertTrue(any("confidence" in line for line in advice), advice)
        self.assertEqual(
            self.library.advice("extraction_user", self.good), [])

    def test_validation_and_rendering_agree(self):
        for text in ("just words", "${context} ${text} ${nope}",
                     "${context} ${text} costs $5"):
            self.assertIsNotNone(self.library.validate("extraction_user", text),
                                 text)


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "prompts.local.json"
        self.library = PromptLibrary(self.path)

    def test_an_edit_is_stored_and_used(self):
        edited = self.library.text("extraction_user").replace(
            "Extract only knowledge", "Extract every fact")
        self.assertIsNone(self.library.set("extraction_user", edited))
        self.assertFalse(self.library.is_default("extraction_user"))
        self.assertIn("Extract every fact",
                      make_prompt("SRC", "CTX", library=self.library))
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 1)
        self.assertIn("extraction_user", stored["prompts"])

    def test_a_refused_edit_is_not_stored(self):
        self.assertIsNotNone(self.library.set("extraction_user", "no markers"))
        self.assertTrue(self.library.is_default("extraction_user"))
        self.assertFalse(self.path.exists())

    def test_an_override_survives_a_reload(self):
        self.library.set("extraction_system", "Answer with JSON only.")
        reopened = PromptLibrary(self.path)
        self.assertEqual(reopened.text("extraction_system"),
                         "Answer with JSON only.")
        self.assertEqual(reopened.digest("extraction_system"),
                         self.library.digest("extraction_system"))

    def test_reset_goes_back_to_the_default(self):
        self.library.set("extraction_system", "Answer with JSON only.")
        self.assertTrue(self.library.reset("extraction_system"))
        self.assertEqual(self.library.text("extraction_system"),
                         prompts.EXTRACTION_SYSTEM)
        self.assertFalse(self.library.reset("extraction_system"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"version": 1, "prompts": {}})

    def test_a_corrupt_file_is_ignored_instead_of_crashing(self):
        self.path.write_text("{not json", encoding="utf-8")
        library = PromptLibrary(self.path)
        self.assertTrue(library.is_default("extraction_user"))

    def test_a_stored_template_that_no_longer_validates_is_ignored(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "prompts": {"extraction_user": "no placeholders",
                        "unknown_name": "whatever"}}), encoding="utf-8")
        library = PromptLibrary(self.path)
        self.assertTrue(library.is_default("extraction_user"))
        self.assertNotIn("unknown_name", library.names())

    def test_describe_reports_the_state_a_frontend_needs(self):
        self.library.set("extraction_system", "Answer with JSON only.")
        described = {item["name"]: item for item in self.library.describe()}
        self.assertEqual(described["extraction_system"]["default"], False)
        self.assertEqual(described["extraction_system"]["text"],
                         "Answer with JSON only.")
        self.assertEqual(described["extraction_user"]["required"],
                         ["context", "text"])
        self.assertIsNone(described["extraction_user"]["error"])


class WiredPromptsTest(unittest.TestCase):
    """The edited templates reach the two prompt builders, not a copy."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.library = PromptLibrary(
            Path(self.directory.name) / "prompts.local.json")

    def test_the_extraction_prompt_uses_the_edited_template(self):
        # ${context} receives the headed, explained context block, so the
        # edited wording shows up around it rather than instead of it.
        self.library.set("extraction_user",
                         "${context}MARKER ${text} TAIL")
        prompt = make_prompt("SRC", "CTX", library=self.library)
        self.assertTrue(prompt.startswith("ONTOLOGY CONTEXT"), prompt[:60])
        self.assertIn("MARKER SRC TAIL", prompt)

    def test_the_starter_prompt_uses_the_edited_template_and_live_caps(self):
        self.library.set("starter", "Caps ${min_classes}-${max_classes}\\n${text}")
        rendered = starter_prompt("a bike shop", library=self.library)
        self.assertIn("Caps 2-20", rendered)
        self.assertIn("a bike shop", rendered)

    def test_a_rendered_default_carries_no_placeholders(self):
        for name in ("extraction_user", "starter"):
            values = dict(prompts.PREVIEW_VALUES[name])
            rendered = self.library.render(name, values)
            self.assertNotIn("${", rendered, name)

    def test_parse_source_asks_with_the_edited_template(self):
        self.library.set("extraction_user", "${context}ASKED ${text}")
        from unittest import mock
        with mock.patch("text_to_ontology.source_parse.ask_llm",
                        return_value={"entities": []}) as asked:
            parse_source("SRC", "CTX", library=self.library)
        self.assertIn("ASKED SRC", asked.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
