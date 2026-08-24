"""M6 pipeline gate: reconcile and validate before final planning."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdflib import Graph
from rdflib.namespace import RDF, SH

from text_to_ontology import pipeline
from text_to_ontology.api import (
    RunRequest,
    ValidationConfig,
    run_text_to_graph,
)
from text_to_ontology.graph_management import LocalTurtleStore, open_graph, save_graph
from text_to_ontology.llm import InvalidResponseError
from text_to_ontology.run_report import RunReporter
from text_to_ontology.source_validation import SourceValidationError

try:
    from .test_pipeline import FakeExtractor, entity_response
except ImportError:
    from test_pipeline import FakeExtractor, entity_response


SHAPES = Path(__file__).parent / "fixtures" / "shacl"


def shape(name):
    graph = Graph()
    graph.parse(SHAPES / name, format="turtle")
    return graph


class PipelineSourceValidationTest(unittest.TestCase):
    def test_a_conformant_document_returns_its_reconciliation_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            result = run_text_to_graph(
                RunRequest(
                    source=source, graph_path=root / "graph.ttl",
                    validation=ValidationConfig(
                        shape_graphs=(shape("label_shape.ttl"),))),
                graph_store=LocalTurtleStore(),
                extractor=FakeExtractor(entity_response("Acme Corp")),
                reporter=RunReporter(stream=io.StringIO()),
            )

        self.assertEqual(len(result.documents), 1)
        document = result.documents[0]
        self.assertTrue(document.source_validation.conforms)
        self.assertEqual(document.reconciliation_report["counts"]
                         ["local_entities"], 1)
        self.assertEqual(len(document.source_artifact.graph_digest), 64)

    def test_non_conformance_stops_before_final_planning_and_keeps_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            graph_path = root / "graph.ttl"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            initial = open_graph(graph_path)
            save_graph(initial, graph_path)
            before = graph_path.read_bytes()
            request = RunRequest(
                source=source, graph_path=graph_path,
                validation=ValidationConfig(
                    shape_graphs=(shape("founded_year_shape.ttl"),)))

            with mock.patch.object(
                    pipeline, "plan_graph_merge",
                    side_effect=AssertionError("final planning ran")):
                with self.assertRaises(SourceValidationError) as caught:
                    run_text_to_graph(
                        request,
                        graph_store=LocalTurtleStore(),
                        extractor=FakeExtractor(entity_response("Acme Corp")),
                        reporter=RunReporter(stream=io.StringIO()),
                    )

            error = caught.exception
            self.assertFalse(error.validation.conforms)
            self.assertTrue(list(error.validation.report_graph.subjects(
                RDF.type, SH.ValidationReport)))
            self.assertIn("Acme Corp", error.source_artifact.ntriples)
            self.assertEqual(error.reconciliation_report["counts"]
                             ["local_entities"], 1)
            self.assertEqual(graph_path.read_bytes(), before)


class FinalGraphImmutabilityTest(unittest.TestCase):
    def test_repair_reconciliation_and_validation_only_observe_final_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            graph_path = root / "graph.ttl"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            save_graph(open_graph(graph_path), graph_path)
            before = graph_path.read_bytes()
            observed = []
            real_reconcile = pipeline.reconcile_document
            real_validate = pipeline.validate_source_graph

            def reconcile(*args, **kwargs):
                observed.append(("reconcile", graph_path.read_bytes()))
                return real_reconcile(*args, **kwargs)

            def validate(*args, **kwargs):
                observed.append(("validate", graph_path.read_bytes()))
                return real_validate(*args, **kwargs)

            def invalid_json():
                raise InvalidResponseError("invalid JSON: broken")

            extractor = FakeExtractor(
                invalid_json,
                entity_response("Acme Corp"),
            )
            with mock.patch.object(pipeline, "reconcile_document", reconcile), \
                    mock.patch.object(pipeline, "validate_source_graph", validate):
                run_text_to_graph(
                    RunRequest(source=source, graph_path=graph_path),
                    graph_store=LocalTurtleStore(), extractor=extractor,
                    reporter=RunReporter(stream=io.StringIO()),
                )

        self.assertEqual([name for name, _content in observed],
                         ["reconcile", "validate"])
        self.assertTrue(all(content == before for _name, content in observed))

    def test_exhausted_repairs_leave_the_final_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            graph_path = root / "graph.ttl"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            save_graph(open_graph(graph_path), graph_path)
            before = graph_path.read_bytes()
            with self.assertRaises(RuntimeError):
                run_text_to_graph(
                    RunRequest(source=source, graph_path=graph_path),
                    graph_store=LocalTurtleStore(),
                    extractor=FakeExtractor({}, {}, {}),
                    reporter=RunReporter(stream=io.StringIO()),
                )
            self.assertEqual(graph_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
