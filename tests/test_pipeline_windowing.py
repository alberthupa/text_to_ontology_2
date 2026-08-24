"""M5: incremental source graphs across windows, final ontology untouched."""

import io
import tempfile
import unittest
from pathlib import Path

from text_to_ontology import pipeline
from text_to_ontology.api import (
    ExtractionConfig,
    ProcessingConfig,
    RunRequest,
    run_text_to_graph,
)
from text_to_ontology.graph_management import LocalTurtleStore
from text_to_ontology.run_report import RunReporter
from text_to_ontology.windowing import plan_windows, make_source_document
from text_to_ontology.windowing import WindowingConfig as SplitterConfig


class FakeExtractor:
    """Answers each prompt from a queue and records what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def model(self):
        return "test-model"

    def extract(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        return response() if callable(response) else response


def acme_response():
    return {
        "entities": [{
            "id": "e1", "name": "Acme Corp", "kind": "Company",
            "description": "", "aliases": [],
            "existing_id": None, "confidence": 0.9,
        }],
        "relations": [], "facts": [],
    }


def raise_error(message):
    def explode():
        raise RuntimeError(message)
    return explode


SMALL_WINDOWS = dict(target_tokens=60, overlap_tokens=0)


def make_request(source, graph_path, **overrides):
    """A request cutting the long fixture into many small windows."""
    return RunRequest(
        source=Path(source), graph_path=Path(graph_path),
        windowing=pipeline.WindowingConfig(**SMALL_WINDOWS),
        extraction=ExtractionConfig(repair_attempts=0),
        **overrides)


def paragraph(times=6):
    return ("Acme Corp grew steadily and hired new people. " * times).strip()


def long_text(blocks=5):
    return "\n\n".join(paragraph() for _ in range(blocks)) + "\n"


def window_count(text, target_tokens=60, overlap_tokens=0):
    document = make_source_document("notes.txt", text)
    windows = plan_windows(document, SplitterConfig(
        target_tokens=target_tokens, overlap_tokens=overlap_tokens))
    return len(windows)


def run_api(source, graph_path, fake_extractor, request=None):
    output = io.StringIO()
    reporter = RunReporter(stream=output)
    if request is None:
        request = make_request(source, graph_path)
    result = run_text_to_graph(
        request,
        graph_store=LocalTurtleStore(),
        extractor=fake_extractor,
        reporter=reporter,
    )
    return result, output.getvalue()


class StagingCreationTest(unittest.TestCase):
    """M5-AC1: one stable staging graph exists before the first window."""

    def test_each_document_announces_its_staging_graph_before_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text(long_text(), encoding="utf-8")
            expected = window_count(long_text())
            fake = FakeExtractor(*[acme_response() for _ in range(expected)])
            result, printed = run_api(source, graph_path, fake)

        self.assertGreaterEqual(expected, 2)
        self.assertIn("Document doc-", printed)
        self.assertIn("/staging/doc-", printed)
        self.assertEqual(result.windows_processed, expected)
        # One extraction call per window, in order.
        self.assertEqual(len(fake.prompts), expected)


class FinalOntologyUntouchedTest(unittest.TestCase):
    """M5-AC5: nothing final changes until the document completes."""

    def test_the_final_file_does_not_exist_while_windows_are_processed(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            text = long_text()
            source.write_text(text, encoding="utf-8")
            expected = window_count(text)

            seen_during_windows = []

            def observe():
                seen_during_windows.append(graph_path.exists())
                return acme_response()

            fake = FakeExtractor(*[observe for _ in range(expected)])
            run_api(source, graph_path, fake)

            self.assertFalse(any(seen_during_windows))
            self.assertTrue(graph_path.exists())

    def test_the_second_document_sees_only_the_first_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            second = root / "02.txt"
            second.write_text(long_text(), encoding="utf-8")
            expected = window_count(long_text())

            sizes = []

            def observe():
                sizes.append(len(graph_path.read_text(encoding="utf-8")))
                return acme_response()

            fake = FakeExtractor(acme_response(),
                                 *[observe for _ in range(expected)])
            run_api(root, graph_path, fake)

            after_first = len(graph_path.read_text(encoding="utf-8"))
            # The file was identical after every window of document two,
            # and only grew once the document's publication completed.
            self.assertTrue(sizes)
            self.assertTrue(all(size == sizes[0] for size in sizes))
            self.assertGreater(after_first, sizes[0])


class CrossWindowIdentityTest(unittest.TestCase):
    """M5-AC6: later windows reuse earlier-window entities without duplicating."""

    def test_a_repeated_entity_is_admitted_once_and_corroborated_after(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            text = long_text()
            source.write_text(text, encoding="utf-8")
            expected = window_count(text)
            _, printed = run_api(
                source, graph_path,
                FakeExtractor(*[acme_response() for _ in range(expected)]))

        self.assertIn("Window 1/%d admitted 1 new entities" % expected, printed)
        for number in range(2, expected + 1):
            self.assertIn(
                f"Window {number}/{expected} admitted 0 new entities", printed)


class LayeredPromptContextTest(unittest.TestCase):
    """M5-AC4/T5: window N sees earlier-window knowledge, clearly marked."""

    def test_source_local_context_is_marked_from_the_second_window_on(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            text = long_text()
            source.write_text(text, encoding="utf-8")
            expected = window_count(text)
            fake = FakeExtractor(*[acme_response() for _ in range(expected)])
            run_api(source, graph_path, fake)

        self.assertNotIn("(this document)", fake.prompts[0])
        for prompt in fake.prompts[1:]:
            self.assertIn("(this document) - name: Acme Corp", prompt)


class WindowFailureTest(unittest.TestCase):
    """M5-AC8: a window failure leaves final graphs unchanged."""

    def setUp(self):
        self.text = long_text()
        self.expected = window_count(self.text)

    def build(self, source):
        source.write_text(self.text, encoding="utf-8")
        return FakeExtractor(acme_response(), raise_error("window broke"))

    def test_a_failure_propagates_and_discards_staging_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text(self.text, encoding="utf-8")
            request = make_request(source, graph_path)
            output = io.StringIO()
            with self.assertRaises(RuntimeError):
                run_text_to_graph(
                    request,
                    graph_store=LocalTurtleStore(),
                    extractor=self.build(source),
                    reporter=RunReporter(stream=output),
                )

            self.assertFalse(graph_path.exists())
            self.assertFalse((root / "graph.ttl.staging").exists())
        self.assertIn("discarded", output.getvalue())

    def test_retention_configured_keeps_a_diagnostic_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text(self.text, encoding="utf-8")
            request = make_request(
                source, graph_path,
                processing=ProcessingConfig(retain_staging_on_failure=True))
            output = io.StringIO()
            with self.assertRaises(RuntimeError):
                run_text_to_graph(
                    request,
                    graph_store=LocalTurtleStore(),
                    extractor=FakeExtractor(
                        acme_response(), raise_error("window broke")),
                    reporter=RunReporter(stream=output),
                )

            sidecars = list((root / "graph.ttl.staging").glob("doc-*.trig"))
            self.assertEqual(len(sidecars), 1)
            content = sidecars[0].read_text(encoding="utf-8")
            self.assertIn("staging/doc-", content)
            self.assertFalse(graph_path.exists())
        self.assertIn("retained for diagnosis", output.getvalue())


class DirectorySeparationTest(unittest.TestCase):
    """M5-AC9: every file is its own document with its own staging graph."""

    def test_two_files_get_two_documents_and_ordered_processing(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text("Beta Corp exists.", encoding="utf-8")

            class Ordered(FakeExtractor):
                def extract(self, prompt):
                    if "Beta" in prompt:
                        order.append("second")
                    else:
                        order.append("first")
                    return super().extract(prompt)

            order = []
            fake = Ordered(acme_response(), {
                "entities": [{
                    "id": "e1", "name": "Beta Corp", "kind": "Company",
                    "description": "", "aliases": [],
                    "existing_id": None, "confidence": 0.9,
                }],
                "relations": [], "facts": [],
            })
            result, printed = run_api(root, graph_path, fake)

        self.assertEqual(order, ["first", "second"])
        self.assertEqual(result.files_total, 2)
        self.assertEqual(result.files_saved, 2)
        self.assertEqual(printed.count("Document doc-"), 2)


class ReportingDistinctionTest(unittest.TestCase):
    """M5-AC10: candidate, source-graph, and publication counts stay apart."""

    def test_window_lines_and_publication_lines_are_distinguishable(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            text = long_text()
            source.write_text(text, encoding="utf-8")
            expected = window_count(text)
            _, printed = run_api(
                source, graph_path,
                FakeExtractor(*[acme_response() for _ in range(expected)]))

        self.assertIn("Validated:", printed)          # window candidate counts
        self.assertIn("admitted 1 new entities", printed)  # source-graph growth
        self.assertIn("Planned:", printed)                 # final publication plan
        self.assertIn("1 new, 0 resolved", printed)        # publication counts
        self.assertEqual(printed.count("admitted"), expected)


if __name__ == "__main__":
    unittest.main()
