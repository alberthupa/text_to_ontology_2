"""The backend surface: workspace, named operations, and the HTTP transport."""

import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from rdflib.namespace import RDF, SKOS

from text_to_ontology.graph_management import CLASS
from text_to_ontology.graph_store import GraphNames
from text_to_ontology.operations import REGISTRY, UnknownOperation, call, describe
from text_to_ontology.studio import Assets, create_server
from text_to_ontology.workspace import Workspace

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "triple-lens.html"

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
    """Answers one scripted list, in order, as the workspace asks."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def model(self):
        return "fake-model"

    def extract(self, prompt):
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


class BlockingExtractor(FakeExtractor):
    """Waits until the test lets it answer, so a job can be observed running."""

    def __init__(self, *answers):
        super().__init__(*answers)
        self.released = threading.Event()
        self.started = threading.Event()

    def extract(self, prompt):
        self.started.set()
        self.released.wait(5)
        return super().extract(prompt)


def wait_for_job(workspace, timeout=10):
    """Wait for the workspace's one job to finish and return its result."""
    deadline = time.monotonic() + timeout
    while workspace.progress.running_now:
        if time.monotonic() > deadline:
            raise AssertionError("the studio job did not finish in time")
        time.sleep(0.02)
    return workspace.progress.snapshot(workspace.progress.job_id)["result"]


class WorkspaceTestBase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.graph = self.base / "ontology.trig"
        self.sources = self.base / "inbox"

    def workspace(self, *answers):
        return Workspace(graph_path=self.graph, sources_dir=self.sources,
                         extractor=FakeExtractor(*answers))


class WorkspaceTest(WorkspaceTestBase):
    def test_an_empty_workspace_is_not_ready(self):
        status = self.workspace().status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["triples"], 0)
        self.assertEqual(status["classes"], [])
        self.assertEqual(status["sources"], [])

    def test_creating_a_starter_makes_the_workspace_ready(self):
        workspace = self.workspace(PROPOSAL)
        proposal = workspace.create_starter("people and companies")
        self.assertEqual(len(proposal["classes"]), 2)
        status = workspace.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["classes"],
                         ["Entity", "Organization", "Person"])
        self.assertEqual(status["relations"], ["works for"])
        self.assertTrue(self.graph.exists())

    def test_ingesting_a_source_adds_data_only(self):
        workspace = self.workspace(PROPOSAL, DECLARED)
        workspace.create_starter("people and companies")
        names = GraphNames()
        schema_before = set(workspace.store.get(names.schema_graphs[0]))

        log = io.StringIO()
        saved = workspace.ingest([("note.txt", "Alice works for Acme.")], log)

        self.assertEqual(saved, ["note.txt"])
        self.assertEqual(set(workspace.store.get(names.schema_graphs[0])),
                         schema_before)
        self.assertIn("triples in the dataset", log.getvalue())
        data = workspace.store.get(names.target_graph)
        self.assertIn((None, RDF.type, CLASS["person"]), data)
        self.assertIn((None, SKOS.prefLabel, None), data)
        self.assertEqual([path.name for path in self.sources.iterdir()],
                         ["note.txt"])

    def test_ingesting_undeclared_vocabulary_reports_an_error(self):
        workspace = self.workspace(PROPOSAL, UNDECLARED)
        workspace.create_starter("people and companies")
        with self.assertRaises(RuntimeError) as caught:
            workspace.ingest([("note.txt", "A widget.")], io.StringIO())
        self.assertIn("starter ontology", str(caught.exception))
        self.assertEqual(
            len(workspace.store.get(GraphNames().target_graph)), 0)

    def test_dropped_names_are_made_safe_and_never_overwritten(self):
        workspace = self.workspace()
        first = workspace._write_source("../../weird name!.txt", "one")
        second = workspace._write_source("../../weird name!.txt", "two")
        self.assertEqual(first.parent, self.sources)
        self.assertEqual(first.name, "weird name.txt")
        self.assertEqual(second.name, "weird name.txt-2")
        self.assertEqual(second.read_text(encoding="utf-8"), "two")

    def test_reset_removes_the_dataset_and_the_inbox(self):
        workspace = self.workspace(PROPOSAL, DECLARED)
        workspace.create_starter("people and companies")
        workspace.ingest([("note.txt", "Alice works for Acme.")], io.StringIO())
        removed = workspace.reset()
        self.assertFalse(self.graph.exists())
        self.assertEqual(list(self.sources.iterdir()), [])
        self.assertIn(str(self.graph), removed)
        self.assertFalse(workspace.status()["ready"])

    def test_reset_refuses_a_directory_that_holds_the_project(self):
        workspace = Workspace(graph_path=self.graph, sources_dir=Path.cwd())
        with self.assertRaises(RuntimeError) as caught:
            workspace.reset()
        self.assertIn("Refusing to reset", str(caught.exception))

    def test_the_dataset_text_carries_the_starter_and_the_data(self):
        workspace = self.workspace(PROPOSAL, DECLARED)
        workspace.create_starter("people and companies")
        workspace.ingest([("note.txt", "Alice works for Acme.")], io.StringIO())
        trig = workspace.dataset_text()
        self.assertIn("Person", trig)
        self.assertIn("Alice", trig)
        self.assertNotIn("graphs/provenance", trig)


class WorkspaceJobTest(WorkspaceTestBase):
    def test_a_starter_job_reports_progress_and_its_result(self):
        workspace = self.workspace()
        workspace.extractor = BlockingExtractor(PROPOSAL)
        job = workspace.start_starter("people and companies")
        self.assertIsNotNone(job)
        self.assertTrue(workspace.extractor.started.wait(5))
        while_working = workspace.progress.snapshot()
        self.assertTrue(while_working["running"])
        self.assertIn("model call 1", while_working["detail"])
        workspace.extractor.released.set()
        result = wait_for_job(workspace)
        self.assertTrue(result["ok"], result)
        self.assertIn("Starter ontology installed", result["log"])
        self.assertTrue(result["status"]["ready"])
        self.assertEqual(workspace.progress.snapshot()["percent"], 100)

    def test_an_ingest_job_reports_files_and_windows(self):
        workspace = self.workspace(PROPOSAL, DECLARED)
        workspace.create_starter("people and companies")
        recorded = []
        real_update = workspace.progress.update

        def record(percent=None, detail=None):
            if detail is not None:
                recorded.append(detail)
            real_update(percent=percent, detail=detail)

        workspace.progress.update = record
        workspace.extractor = BlockingExtractor(DECLARED)
        workspace.start_ingest([("note.txt", "Alice works for Acme.")])
        self.assertTrue(workspace.extractor.started.wait(5))
        while_working = workspace.progress.snapshot()
        self.assertTrue(while_working["running"])
        self.assertIn("note.txt", while_working["detail"])
        self.assertIn("window 1/1", while_working["detail"])
        workspace.extractor.released.set()
        result = wait_for_job(workspace)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sources"], ["note.txt"])
        self.assertTrue(any("starting" in detail for detail in recorded), recorded)
        self.assertTrue(any("asking the model" in detail for detail in recorded),
                        recorded)
        self.assertTrue(any("window 1/1 admitted" in detail for detail in recorded),
                        recorded)
        self.assertTrue(any("published" in detail for detail in recorded), recorded)
        self.assertEqual(workspace.progress.snapshot()["percent"], 100)

    def test_progress_spans_every_dropped_file(self):
        workspace = self.workspace(PROPOSAL, DECLARED, DECLARED)
        workspace.create_starter("people and companies")
        recorded = []
        real_update = workspace.progress.update

        def record(percent=None, detail=None):
            if percent is not None:
                recorded.append((percent, detail))
            real_update(percent=percent, detail=detail)

        workspace.progress.update = record
        workspace.ingest([("a.txt", "Alice works for Acme."),
                          ("b.txt", "Acme hired Alice as a person.")],
                         io.StringIO(), progress=workspace.progress)
        percents = [percent for percent, _detail in recorded]
        self.assertEqual(percents, sorted(percents), recorded)
        # the second file continues where the first ended instead of at zero
        second = [percent for percent, detail in recorded
                  if detail and "b.txt" in detail and "asking" in detail]
        self.assertTrue(second, recorded)
        self.assertGreaterEqual(second[0], 50, recorded)

    def test_a_failed_job_still_finishes_with_an_error(self):
        workspace = self.workspace(PROPOSAL, UNDECLARED)
        workspace.create_starter("people and companies")
        workspace.start_ingest([("note.txt", "A widget.")])
        result = wait_for_job(workspace)
        self.assertFalse(result["ok"])
        self.assertIn("starter ontology", result["error"])
        self.assertFalse(workspace.progress.running_now)

    def test_only_one_job_runs_at_a_time(self):
        workspace = self.workspace()
        workspace.extractor = BlockingExtractor(PROPOSAL)
        self.assertIsNotNone(workspace.start_starter("people and companies"))
        self.assertTrue(workspace.extractor.started.wait(5))
        self.assertIsNone(workspace.start_starter("something else"))
        self.assertIsNone(workspace.start_ingest([("note.txt", "text")]))
        workspace.extractor.released.set()
        self.assertTrue(wait_for_job(workspace)["ok"])

    def test_a_result_is_only_handed_to_the_job_that_asked(self):
        workspace = self.workspace(PROPOSAL)
        first = workspace.start_starter("people and companies")
        wait_for_job(workspace)
        self.assertIsNotNone(workspace.progress.snapshot(first)["result"])
        self.assertIsNone(workspace.progress.snapshot(0)["result"])
        second = workspace.start_starter("people and companies")
        wait_for_job(workspace)
        self.assertGreater(second, first)
        # a reloaded or stale page cannot pick up an earlier run's answer
        self.assertIsNone(workspace.progress.snapshot(first)["result"])
        self.assertIsNotNone(workspace.progress.snapshot(second)["result"])


class OperationsTest(WorkspaceTestBase):
    def test_the_manifest_names_every_operation(self):
        names = [item["name"] for item in describe()]
        self.assertEqual(names, sorted(names))
        self.assertEqual(set(names), set(REGISTRY))
        for item in describe():
            self.assertTrue(item["summary"], item)
            self.assertIsInstance(item["args"], list)
            self.assertIsInstance(item["background"], bool)
        self.assertEqual(
            {item["name"] for item in describe() if item["background"]},
            {"chat.ask", "ingest", "starter.create"})

    def test_every_operation_answers_a_plain_record(self):
        workspace = self.workspace(PROPOSAL)
        for name in ("status", "dataset", "progress", "reset",
                     "operations.list"):
            answer = call(workspace, name, {})
            self.assertIsInstance(answer, dict, name)
            json.dumps(answer)          # must survive the transport
        answer = call(workspace, "starter.create",
                      {"text": "people and companies"})
        self.assertTrue(answer["ok"], answer)
        result = wait_for_job(workspace)
        self.assertTrue(result["ok"], result)

    def test_an_unknown_operation_is_an_error(self):
        with self.assertRaises(UnknownOperation):
            call(self.workspace(), "does.not.exist")

    def test_missing_arguments_are_reported_not_crashed(self):
        workspace = self.workspace()
        empty = call(workspace, "starter.create", {})
        self.assertFalse(empty["ok"])
        self.assertIn("description", empty["error"])
        nothing = call(workspace, "ingest", {"files": []})
        self.assertFalse(nothing["ok"])
        self.assertIn("source files", nothing["error"])
        self.assertIsNone(call(workspace, "progress", {})["result"])

    def test_a_running_job_is_refused_through_the_operation(self):
        workspace = self.workspace()
        workspace.extractor = BlockingExtractor(PROPOSAL)
        started = call(workspace, "starter.create", {"text": "people"})
        self.assertTrue(started["ok"], started)
        self.assertTrue(workspace.extractor.started.wait(5))
        refused = call(workspace, "ingest",
                       {"files": [{"name": "a.txt", "text": "text"}]})
        self.assertFalse(refused["ok"])
        self.assertIn("already running", refused["error"])
        workspace.extractor.released.set()
        wait_for_job(workspace)


class PromptOperationsTest(WorkspaceTestBase):
    def test_the_prompt_list_carries_everything_the_editor_needs(self):
        listed = call(self.workspace(), "prompts.list", {})
        self.assertTrue(listed["ok"])
        names = [item["name"] for item in listed["prompts"]]
        self.assertEqual(names, ["chat_system", "chat_user",
                                 "extraction_system", "extraction_user",
                                 "starter"])
        for item in listed["prompts"]:
            self.assertIn("text", item)
            self.assertIn("default", item)
            self.assertIn("required", item)
            self.assertIn("error", item)

    def test_saving_a_prompt_validates_then_stores_it(self):
        workspace = self.workspace()
        refused = call(workspace, "prompts.save",
                       {"name": "extraction_user", "text": "no markers"})
        self.assertFalse(refused["ok"])
        self.assertIn("$context", refused["error"])
        saved = call(workspace, "prompts.save",
                     {"name": "extraction_system", "text": "ONLY JSON PLEASE"})
        self.assertTrue(saved["ok"], saved)
        self.assertIn("prompts.local.json", saved["log"])
        edited = [item for item in saved["prompts"]
                  if item["name"] == "extraction_system"][0]
        self.assertFalse(edited["default"])
        self.assertEqual(edited["text"], "ONLY JSON PLEASE")

    def test_resetting_a_prompt_restores_the_default(self):
        workspace = self.workspace()
        call(workspace, "prompts.save",
             {"name": "extraction_system", "text": "ONLY JSON PLEASE"})
        reset = call(workspace, "prompts.reset",
                     {"name": "extraction_system"})
        self.assertTrue(reset["ok"])
        self.assertTrue([item for item in reset["prompts"]
                         if item["name"] == "extraction_system"][0]["default"])

    def test_a_preview_renders_the_template(self):
        workspace = self.workspace()
        preview = call(workspace, "prompts.preview",
                       {"name": "extraction_user"})
        self.assertTrue(preview["ok"], preview)
        self.assertIn("Acme Corp participates in Springfield", preview["prompt"])
        self.assertNotIn("${", preview["prompt"])

    def test_a_missing_name_is_reported(self):
        for name in ("prompts.save", "prompts.reset", "prompts.preview"):
            answer = call(self.workspace(), name, {})
            self.assertFalse(answer["ok"], name)
            self.assertIn("name", answer["error"])

    def test_an_unknown_name_is_reported_by_the_operation(self):
        answer = call(self.workspace(), "prompts.save",
                      {"name": "nope", "text": "x"})
        self.assertFalse(answer["ok"])
        self.assertIn("unknown prompt", answer["error"])

    def test_an_edited_system_prompt_reaches_the_run(self):
        # With no injected extractor, one is built per run from the prompts.
        workspace = Workspace(graph_path=self.graph, sources_dir=self.sources)
        workspace.prompts.set("extraction_system", "EDITED FOR A RUN")
        self.assertEqual(workspace.extractor_for_run().system_prompt,
                         "EDITED FOR A RUN")
        # An injected extractor is never replaced.
        injected = self.workspace(DECLARED)
        self.assertIs(injected.extractor_for_run(), injected.extractor)


class AssetsTest(unittest.TestCase):
    def test_the_page_and_the_panel_beside_it_are_served(self):
        assets = Assets(PAGE)
        html, page_type = assets.body("/")
        self.assertIn("text/html", page_type)
        self.assertIn(b"Triple Lens", html)
        self.assertIn(b"studio.js", html)          # the loader, not the panel
        self.assertNotIn(b'id="studio"', html)     # the panel is not in the page
        script, script_type = assets.body("/studio.js")
        self.assertEqual(script_type, "text/javascript; charset=utf-8")
        # The top-bar actions, the dialogs behind them, and the chat column.
        for control in (b"stProgress", b'id="stClear"', b'id="stReset"',
                        b'id="stOpenStarter"', b'id="stCreate"',
                        b'id="stOpenSources"', b'id="stDrop"',
                        b'id="stOpenPrompts"', b'id="stOpenEdit"',
                        b'id="stLog"', b'id="stChatText"', b'id="stChatSend"'):
            self.assertIn(control, script, control)
        self.assertIn(b"webkitGetAsEntry", script)
        self.assertIn(b"filesFromEntry", script)
        self.assertIn(b"dropZone(dropEl, ingest, true)", script)
        _css, css_type = assets.body("/studio.css")
        self.assertEqual(css_type, "text/css; charset=utf-8")

    def test_only_the_page_and_its_siblings_are_served(self):
        assets = Assets(PAGE)
        for path in ("/../studio.py", "/etc/passwd", "/studio.json",
                     "/src/text_to_ontology/studio.py"):
            body, content_type = assets.body(path)
            self.assertIsNone(body, path)
            self.assertIsNone(content_type, path)


class StudioServerTest(WorkspaceTestBase):
    def test_a_taken_port_falls_back_to_the_next_free_one(self):
        workspace = self.workspace()
        first = create_server(workspace, "127.0.0.1", 0)
        self.addCleanup(first.server_close)
        taken = first.server_address[1]
        second = create_server(workspace, "127.0.0.1", taken)
        self.addCleanup(second.server_close)
        self.assertEqual(second.server_address[1], taken + 1)


class StudioHttpTest(WorkspaceTestBase):
    def setUp(self):
        super().setUp()
        self.workspace = self.workspace(PROPOSAL, DECLARED)
        self.server = create_server(self.workspace, "127.0.0.1", 0,
                                    assets=Assets(PAGE))
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

    def op_get(self, name, args=None):
        query = "&".join(f"{key}={value}" for key, value in (args or {}).items())
        _status, body = self.get(f"/api/op/{name}" + (f"?{query}" if query else ""))
        return json.loads(body)

    def op_post(self, name, args):
        return self.post(f"/api/op/{name}", args)[1]

    def job(self, name, args):
        """Start one background operation over HTTP and poll it like a page."""
        started = self.op_post(name, args)
        self.assertTrue(started.get("job_id"), started)
        job_id = started["job_id"]
        seen = []
        deadline = time.monotonic() + 30
        while True:
            state = self.op_get("progress", {"job": job_id})
            if state["detail"]:
                seen.append(state["detail"])
            if not state["running"]:
                break
            if time.monotonic() > deadline:
                raise AssertionError("the job did not finish in time")
            time.sleep(0.01)
        self.assertEqual(state["percent"], 100)
        state["seen"] = seen
        return state["result"], state

    def test_the_page_its_assets_and_the_manifest_answer(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Triple Lens", body)
        status, body = self.get("/studio.js")
        self.assertEqual(status, 200)
        self.assertIn(b"api/op/", body)
        status, body = self.get("/studio.css")
        self.assertEqual(status, 200)
        self.assertIn(b"#studio", body)

        manifest = self.op_get("operations.list")
        self.assertTrue(manifest["ok"])
        self.assertIn("ingest", [item["name"] for item in manifest["operations"]])

    def test_status_and_dataset_answer_as_operations(self):
        status = self.op_get("status")
        self.assertFalse(status["ready"])
        data = self.op_get("dataset")
        self.assertIn("trig", data)

    def test_the_starter_ingest_and_reset_round_trip(self):
        result, state = self.job("starter.create",
                                 {"text": "people and companies"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["status"]["ready"])
        self.assertEqual(result["status"]["classes"],
                         ["Entity", "Organization", "Person"])
        self.assertIn("Creating the starter ontology", state["label"])

        result, state = self.job("ingest", {"files": [
            {"name": "note.txt", "text": "Alice works for Acme."}]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sources"], ["note.txt"])
        self.assertGreater(result["status"]["triples"], 0)
        self.assertIn("Ingesting sources", state["label"])

        result = self.op_post("reset", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["triples"], 0)
        self.assertFalse(result["status"]["ready"])

    def test_an_undeclared_ingestion_answers_with_an_error(self):
        self.job("starter.create", {"text": "people and companies"})
        self.workspace.extractor = FakeExtractor(UNDECLARED)
        result, _state = self.job("ingest", {"files": [
            {"name": "note.txt", "text": "A widget."}]})
        self.assertFalse(result["ok"])
        self.assertIn("starter ontology", result["error"])

    def test_a_running_job_is_visible_and_a_second_one_is_refused(self):
        self.workspace.extractor = BlockingExtractor(PROPOSAL)
        started = self.op_post("starter.create", {"text": "people and companies"})
        self.assertTrue(started["ok"], started)
        self.assertTrue(self.workspace.extractor.started.wait(5))

        # what a page is polling while the model is thinking
        state = self.op_get("progress", {"job": started["job_id"]})
        self.assertTrue(state["running"])
        self.assertIn("Creating the starter ontology", state["label"])
        self.assertIn("model call 1", state["detail"])
        self.assertIsNone(state["result"])

        refused = self.op_post("ingest", {"files": [
            {"name": "note.txt", "text": "text"}]})
        self.assertFalse(refused["ok"])
        self.assertIn("already running", refused["error"])
        self.workspace.extractor.released.set()
        wait_for_job(self.workspace)

    def test_an_unknown_operation_or_route_is_a_404(self):
        for path in ("/api/op/nope", "/api/nothing", "/api/status"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(path)
            self.assertEqual(caught.exception.code, 404, path)


if __name__ == "__main__":
    unittest.main()
