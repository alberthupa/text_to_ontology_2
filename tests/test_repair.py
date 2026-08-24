"""Milestone 4 (user-requested): bounded LLM self-repair for messy answers."""

import io
import tempfile
import unittest
from pathlib import Path

from text_to_ontology.api import run_text_to_graph
from text_to_ontology.graph_management import LocalTurtleStore, open_graph
from text_to_ontology.llm import InvalidResponseError
from text_to_ontology.repair import extract_validated, repair_prompt
from text_to_ontology.run_report import RunReporter

try:  # works both as a package module and as a discovered top-level module
    from .test_pipeline import FakeExtractor, entity_response
except ImportError:
    from test_pipeline import FakeExtractor, entity_response


class ScriptedExtractor:
    """Answers each prompt in turn; raises when a response is a string error."""

    def __init__(self, *script):
        self.script = list(script)
        self.prompts = []

    def model(self):
        return "test-model"

    def extract(self, prompt):
        self.prompts.append(prompt)
        step = self.script.pop(0) if self.script else None
        if isinstance(step, InvalidResponseError):
            raise step
        if step is None:
            raise AssertionError("no scripted answer left")
        return step


def strict_validation(result):
    """A stand-in gate: valid only for the known-good sample package."""
    good = entity_response("Acme Corp")
    ok = result == good or result.get("fixed") is True
    return {
        "valid": ok,
        "candidates": result if ok else None,
        "issues": [] if ok else [{
            "severity": "error", "path": "entities[0]",
            "message": "not the expected package",
            "code": "entity.not_mapping", "related_paths": [],
        }],
        "counts": {},
    }


class FirstAttemptTest(unittest.TestCase):
    def test_a_good_first_answer_needs_no_repair(self):
        extractor = ScriptedExtractor(entity_response("Acme Corp"))
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 0)
        self.assertEqual(len(extractor.prompts), 1)

    def test_zero_attempts_rejects_a_messy_answer_immediately(self):
        outcome = extract_validated(
            ScriptedExtractor({}), "prompt", strict_validation,
            max_repair_attempts=0)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 0)


class RepairSuccessTest(unittest.TestCase):
    def test_an_unparseable_answer_is_repaired_from_the_raw_text(self):
        raw = 'oops {"entities": [broken'
        extractor = ScriptedExtractor(
            InvalidResponseError(f"The model returned invalid JSON:\n{raw}"),
            entity_response("Acme Corp"),
        )
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 1)
        self.assertIn(raw, extractor.prompts[1])
        self.assertIn("JSON", extractor.prompts[1])

    def test_a_contract_violation_is_repaired_with_the_issue_list(self):
        extractor = ScriptedExtractor({}, entity_response("Acme Corp"))
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 1)
        followup = extractor.prompts[1]
        self.assertIn("entities[0]", followup)
        self.assertIn("not the expected package", followup)
        self.assertIn("{}", followup)

    def test_the_second_repair_can_still_succeed(self):
        extractor = ScriptedExtractor({}, {}, entity_response("Acme Corp"))
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 2)


class RepairFailureTest(unittest.TestCase):
    def test_exhausted_attempts_reject_the_window(self):
        extractor = ScriptedExtractor({}, {}, {})
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 2)

    def test_a_network_failure_propagates_instead_of_being_repaired(self):
        class DownExtractor(ScriptedExtractor):
            def extract(self, prompt):
                self.prompts.append(prompt)
                raise RuntimeError("OpenRouter error 503: upstream down")

        with self.assertRaises(RuntimeError):
            extract_validated(DownExtractor(), "prompt", strict_validation,
                              max_repair_attempts=3)

    def test_invalid_json_returned_by_repair_uses_the_remaining_bound(self):
        extractor = ScriptedExtractor(
            {},
            InvalidResponseError("The model returned invalid JSON: broken"),
            entity_response("Acme Corp"),
        )
        outcome = extract_validated(extractor, "prompt", strict_validation,
                                    max_repair_attempts=2)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.repair_attempts, 2)
        self.assertIn("broken", extractor.prompts[2])

    def test_a_network_failure_during_repair_propagates(self):
        class RepairGoesDown(ScriptedExtractor):
            def extract(self, prompt):
                self.prompts.append(prompt)
                if len(self.prompts) == 1:
                    return {}
                raise RuntimeError("OpenRouter error 503 during repair")

        extractor = RepairGoesDown()
        with self.assertRaisesRegex(RuntimeError, "during repair"):
            extract_validated(extractor, "prompt", strict_validation,
                              max_repair_attempts=3)
        self.assertEqual(len(extractor.prompts), 2)


class PromptShapeTest(unittest.TestCase):
    def test_the_prompt_names_the_problem_and_shows_the_original(self):
        prompt = repair_prompt(original={"entities": [1]},
                               issues=[{"severity": "error", "path": "$.x",
                                        "message": "bad"}])
        self.assertIn("broke the contract", prompt)
        self.assertIn("$.x", prompt)
        self.assertIn('"entities": [', prompt)

    def test_an_unparseable_answer_is_quoted_verbatim(self):
        prompt = repair_prompt(raw_problem="garbage { not json")
        self.assertIn("not one parseable JSON object", prompt)
        self.assertIn("garbage { not json", prompt)

    def test_issue_order_is_deterministic(self):
        issues = [
            {"severity": "error", "path": "facts[1]", "message": "second"},
            {"severity": "error", "path": "entities[0]", "message": "first"},
        ]
        forward = repair_prompt(original={}, issues=issues)
        backward = repair_prompt(original={}, issues=reversed(issues))
        self.assertEqual(forward, backward)


class PipelineRepairTest(unittest.TestCase):
    """End to end: one messy window, repaired once, file still saved."""

    def test_a_messy_window_is_repaired_and_the_run_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            fake = FakeExtractor({}, entity_response("Acme Corp"))
            from text_to_ontology.api import RunRequest
            result = run_text_to_graph(
                RunRequest(source=source, graph_path=root / "graph.ttl"),
                graph_store=LocalTurtleStore(),
                extractor=fake,
                reporter=RunReporter(verbose=False, stream=io.StringIO()),
            )
            graph = open_graph(root / "graph.ttl")
        self.assertEqual(result.files_saved, 1)
        self.assertEqual(len(fake.prompts), 2)
        self.assertGreater(len(graph), 0)


if __name__ == "__main__":
    unittest.main()
