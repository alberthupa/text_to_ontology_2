"""The studio: status, starter, ingest, reset, and its tiny HTTP API."""

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from rdflib.namespace import RDF, SKOS

from text_to_ontology.graph_management import CLASS
from text_to_ontology.graph_store import GraphNames
from text_to_ontology.studio import Studio, create_server

PAGE = Path(__file__).resolve().parents[1] / "scripts" / "triple-lens.html"

PROPOSAL = {
    "classes": [{"name": "Person"}, {"name": "Organization"}],
    "relations": [{"name": "works-for", "domain": "Person",
                   "range": "Organization"}],
    "facts": [],
}

DECLARED = {
    "entities": [{"id": "e1", "name": "Alice", "kind": "Person",
                  "confidence": 0.9},
                 {"id": "e2", "name": "Acme", "kind": "Organization",
                  "confidence": 0.9}],
    "relations": [{"subject": "e1", "predicate": "works-for", "object": "e2",
                   "confidence": 0.9}],
    "facts": [],
}

UNDECLARED = {
    "entities": [{"id": "e1", "name": "Widget", "kind": "Product",
                  "confidence": 0.9}],
    "relations": [], "facts": [],
}


class FakeExtractor:
    """Answers one scripted list, in order, as the studio asks."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def model(self):
        return "fake-model"

    def extract(self, prompt):
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


class StudioTestBase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.graph = self.base / "ontology.trig"
        self.sources = self.base / "inbox"

    def studio(self, *answers):
        return Studio(graph_path=self.graph, sources_dir=self.sources,
                      page_path=PAGE, extractor=FakeExtractor(*answers))


class StudioTest(StudioTestBase):
    def test_an_empty_studio_is_not_ready(self):
        status = self.studio().status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["triples"], 0)
        self.assertEqual(status["classes"], [])
        self.assertEqual(status["sources"], [])

    def test_creating_a_starter_makes_the_studio_ready(self):
        studio = self.studio(PROPOSAL)
        proposal = studio.create_starter("people and companies")
        self.assertEqual(len(proposal["classes"]), 2)
        status = studio.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["classes"],
                         ["Entity", "Organization", "Person"])
        self.assertEqual(status["relations"], ["works for"])
        self.assertTrue(self.graph.exists())

    def test_ingesting_a_source_adds_data_only(self):
        studio = self.studio(PROPOSAL, DECLARED)
        studio.create_starter("people and companies")
        names = GraphNames()
        schema_before = set(studio.store.get(names.schema_graphs[0]))

        log = io.StringIO()
        saved = studio.ingest([("note.txt", "Alice works for Acme.")], log)

        self.assertEqual(saved, ["note.txt"])
        self.assertEqual(set(studio.store.get(names.schema_graphs[0])),
                         schema_before)
        self.assertIn("triples in the dataset", log.getvalue())
        data = studio.store.get(names.target_graph)
        self.assertIn((None, RDF.type, CLASS["person"]), data)
        self.assertIn((None, SKOS.prefLabel, None), data)
        self.assertEqual([path.name for path in self.sources.iterdir()],
                         ["note.txt"])

    def test_ingesting_undeclared_vocabulary_reports_an_error(self):
        studio = self.studio(PROPOSAL, UNDECLARED)
        studio.create_starter("people and companies")
        with self.assertRaises(RuntimeError) as caught:
            studio.ingest([("note.txt", "A widget.")], io.StringIO())
        self.assertIn("starter ontology", str(caught.exception))
        self.assertEqual(len(studio.store.get(GraphNames().target_graph)), 0)

    def test_dropped_names_are_made_safe_and_never_overwritten(self):
        studio = self.studio()
        first = studio._write_source("../../weird name!.txt", "one")
        second = studio._write_source("../../weird name!.txt", "two")
        self.assertEqual(first.parent, self.sources)
        self.assertEqual(first.name, "weird name.txt")
        self.assertEqual(second.name, "weird name.txt-2")
        self.assertEqual(second.read_text(encoding="utf-8"), "two")

    def test_reset_removes_the_dataset_and_the_inbox(self):
        studio = self.studio(PROPOSAL, DECLARED)
        studio.create_starter("people and companies")
        studio.ingest([("note.txt", "Alice works for Acme.")], io.StringIO())
        removed = studio.reset()
        self.assertFalse(self.graph.exists())
        self.assertEqual(list(self.sources.iterdir()), [])
        self.assertIn(str(self.graph), removed)
        self.assertFalse(studio.status()["ready"])

    def test_reset_refuses_a_directory_that_holds_the_project(self):
        studio = Studio(graph_path=self.graph, sources_dir=Path.cwd(),
                        page_path=PAGE)
        with self.assertRaises(RuntimeError) as caught:
            studio.reset()
        self.assertIn("Refusing to reset", str(caught.exception))

    def test_the_dataset_text_carries_the_starter_and_the_data(self):
        studio = self.studio(PROPOSAL, DECLARED)
        studio.create_starter("people and companies")
        studio.ingest([("note.txt", "Alice works for Acme.")], io.StringIO())
        trig = studio.dataset_text()
        self.assertIn("Person", trig)
        self.assertIn("Alice", trig)
        self.assertNotIn("graphs/provenance", trig)


class StudioServerTest(StudioTestBase):
    def test_a_taken_port_falls_back_to_the_next_free_one(self):
        studio = self.studio()
        first = create_server(studio, "127.0.0.1", 0)
        self.addCleanup(first.server_close)
        taken = first.server_address[1]
        second = create_server(studio, "127.0.0.1", taken)
        self.addCleanup(second.server_close)
        self.assertEqual(second.server_address[1], taken + 1)


class StudioHttpTest(StudioTestBase):
    def setUp(self):
        super().setUp()
        self.studio = self.studio(PROPOSAL, DECLARED)
        self.server = create_server(self.studio, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as response:
            return response.status, response.read()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())

    def test_status_the_page_and_the_dataset_answer(self):
        status, body = self.get("/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["ready"])

        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Triple Lens", body)
        # the controls the studio column promises: clear, reset, starter, drop
        for control in (b'id="stClear"', b'id="stReset"', b'id="stCreate"',
                        b'id="stDrop"', b'id="stStatus"', b'id="stLog"'):
            self.assertIn(control, body, control)

        status, body = self.get("/api/dataset")
        self.assertEqual(status, 200)
        self.assertIn("trig", json.loads(body))

    def test_the_starter_ingest_and_reset_round_trip(self):
        _status, result = self.post("/api/starter",
                                    {"text": "people and companies"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["status"]["ready"])
        self.assertEqual(result["status"]["classes"],
                         ["Entity", "Organization", "Person"])

        _status, result = self.post("/api/ingest", {"files": [
            {"name": "note.txt", "text": "Alice works for Acme."}]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["sources"], ["note.txt"])
        self.assertGreater(result["status"]["triples"], 0)

        _status, result = self.post("/api/reset", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["triples"], 0)
        self.assertFalse(result["status"]["ready"])

    def test_an_undeclared_ingestion_answers_with_an_error(self):
        self.post("/api/starter", {"text": "people and companies"})
        self.studio.extractor = FakeExtractor(UNDECLARED)
        _status, result = self.post("/api/ingest", {"files": [
            {"name": "note.txt", "text": "A widget."}]})
        self.assertFalse(result["ok"])
        self.assertIn("starter ontology", result["error"])

    def test_an_unknown_route_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/nothing")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
