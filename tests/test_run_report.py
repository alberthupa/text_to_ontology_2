"""Run reporting stays human-readable and independent of stdout."""

import io
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, URIRef

from text_to_ontology.graph_management import ENTITY, RELATION, bind
from text_to_ontology.run_report import RunReporter, default_report_path


class RunReporterTest(unittest.TestCase):
    def test_default_report_path_contains_time_and_source_name(self):
        started = datetime(2026, 8, 23, 14, 5, 6, 123456,
                           tzinfo=timezone.utc)

        path = default_report_path(Path("source notes.md"), started)

        self.assertEqual(
            path,
            Path("reports/runs/2026-08-23_14-05-06_123456_source-notes.md"),
        )

    def test_output_can_be_sent_to_any_text_stream(self):
        stream = io.StringIO()
        reporter = RunReporter(stream=stream)

        reporter.source_started(Path("notes.txt"), 1, 1, 8)
        reporter.finished(Graph(), Path("graph.ttl"))

        self.assertIn("Reading notes.txt", stream.getvalue())
        self.assertIn("Saved 0 triples to graph.ttl", stream.getvalue())

    def test_markdown_sink_gets_hard_breaks_without_changing_console(self):
        console = io.StringIO()
        markdown = io.StringIO()
        reporter = RunReporter(
            stream=console,
            extra_streams=[markdown],
            markdown_streams=[markdown],
        )

        reporter.line("one line")

        self.assertEqual(console.getvalue(), "one line\n")
        self.assertEqual(markdown.getvalue(), "one line  \n")

    def test_normal_mode_omits_verbose_details(self):
        stream = io.StringIO()
        reporter = RunReporter(verbose=False, stream=stream)

        reporter.model_replied({"entities": [], "relations": [], "facts": []}, 1.2)

        output = stream.getvalue()
        self.assertIn("Model replied in 1.2 seconds", output)
        self.assertNotIn("Parsed JSON", output)

    def test_exact_llm_input_is_shown_as_two_code_blocks(self):
        stream = io.StringIO()
        reporter = RunReporter(verbose=True, stream=stream)

        reporter.llm_input("system text", "instruction\nSOURCE:\nsource text")

        output = stream.getvalue()
        self.assertIn("System message:\n```text\nsystem text\n```", output)
        self.assertIn("User message (instructions + selected context + source):\n"
                      "```text\ninstruction\nSOURCE:\nsource text\n```", output)

    def test_verbose_plan_shows_identity_method_reasons_and_triples(self):
        stream = io.StringIO()
        graph = Graph()
        bind(graph)
        reporter = RunReporter(verbose=True, stream=stream)
        candidates = {
            "entities": [{"id": "e1", "name": "Alice", "confidence": 0.9}],
            "relations": [{"subject": "e1", "predicate": "knows",
                           "object": "e1", "confidence": 0.9}],
            "facts": [],
        }
        plan = {
            "policy_version": 1,
            "identities": {
                "e1": {"status": "new", "uri": ENTITY.alice,
                       "method": "new", "reason_codes": [],
                       "suggestions": []},
            },
            "entities": [{"local_id": "e1", "summary": "accept",
                          "fields": {"kind": {"outcome": "accept"}}}],
            "relations": [{"index": 0, "outcome": "review",
                           "confidence": 0.9,
                           "reason_codes": ["conflict.functional_value"],
                           "triple": (ENTITY.alice, RELATION.knows,
                                      ENTITY.alice),
                           "conflicts": [(ENTITY.alice, RELATION.knows,
                                          URIRef("http://example.org/other"))]}],
            "facts": [],
            "counts": {
                "identities": {"new": 1, "resolved": 0, "review": 0},
                "assertions": {"accepted": 0, "duplicate": 0, "review": 1},
                "entity_summaries": {"accept": 1, "duplicate": 0,
                                     "review": 0, "partial_review": 0},
                "domain_triples": 10,
                "audit_triples": 20,
            },
        }

        reporter.merge_plan(plan, candidates, graph)

        output = stream.getvalue()
        self.assertIn("[7] Merge plan: policy v1", output)
        self.assertIn("Identity e1: NEW", output)
        self.assertIn("method: new", output)
        self.assertIn("Relation[0]: REVIEW", output)
        self.assertIn("reason: conflict.functional_value", output)
        self.assertIn("entity:alice -- relation:knows --> entity:alice", output)


if __name__ == "__main__":
    unittest.main()
