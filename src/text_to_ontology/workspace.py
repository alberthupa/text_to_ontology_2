"""The application's state and its long jobs - everything the studio can do.

`Workspace` is the whole backend state for one dataset: where the graph lives,
where dropped sources land, the store, the extractor, and one progress slot for
the long jobs. It contains no HTTP, no argument parsing, and no browser code:
`operations.py` names what it can do, `studio.py` carries it over HTTP, and the
tests drive it directly.

The two long jobs (creating the starter ontology, ingesting sources) run in a
background thread while a frontend polls `progress_state`, so a page can show a
real progress bar. Only one job may run at a time, which keeps graph writes
serial.
"""

import io
import threading
from pathlib import Path

from rdflib import Dataset, Graph

from .graph_chat import ChatSession
from .graph_management import bind
from .graph_store import GraphNames, RdflibGraphStore
from .llm import OpenRouterExtractor
from .pipeline import MergeConfig, RunRequest, run_text_to_graph
from .prompts import DEFAULT_FILE, PREVIEW_VALUES, PromptLibrary
from .run_report import RunReporter
from .starter import (
    import_publication, import_summary, proposal_summary, propose_starter,
    starter_publication,
)
from .vocabulary import read_vocabulary

DEFAULT_GRAPH = Path("ontology.trig")
DEFAULT_SOURCES = Path("sources/inbox")


class Progress:
    """The one running job, as the frontend polling it sees it.

    `claim` takes the single job slot; `update` moves the bar; `finish`
    stores the answer the page is waiting for. A result is handed out only to
    the job id that asked for it, so a stale page cannot pick up an old run.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.job_id = 0
        self.running = False
        self.label = ""
        self.detail = ""
        self.percent = 0
        self.result = None

    def claim(self, label):
        """Take the job slot, or return None when a job is already running."""
        with self.lock:
            if self.running:
                return None
            self.job_id += 1
            self.running = True
            self.label = label
            self.detail = "starting…"
            self.percent = 0
            self.result = None
            return self.job_id

    def update(self, percent=None, detail=None):
        with self.lock:
            if percent is not None:
                self.percent = max(0, min(100, int(percent)))
            if detail is not None:
                self.detail = detail

    def finish(self, result):
        with self.lock:
            self.running = False
            self.percent = 100
            self.detail = "done" if result.get("ok") else "failed"
            self.result = result

    def snapshot(self, job_id=None):
        with self.lock:
            mine = job_id is not None and job_id == self.job_id
            return {"ok": True, "job_id": self.job_id,
                    "running": self.running, "label": self.label,
                    "detail": self.detail, "percent": self.percent,
                    "result": self.result if mine else None}

    @property
    def running_now(self):
        with self.lock:
            return self.running


class _CountingExtractor:
    """Counts model calls so a frontend can name the attempt it is waiting for."""

    def __init__(self, extractor, on_call):
        self.extractor = extractor
        self.on_call = on_call
        self.calls = 0

    def model(self):
        return self.extractor.model()

    def extract(self, prompt):
        self.calls += 1
        self.on_call(self.calls)
        return self.extractor.extract(prompt)


class _ProgressReporter(RunReporter):
    """The ordinary run log, plus one progress step per pipeline checkpoint.

    The pipeline runs once per file, so it always reports "1 of 1"; the
    workspace passes the real file number and file count in so the bar spans
    the whole drop instead of restarting for every file.
    """

    def __init__(self, stream, file_name, file_number, files_total,
                 progress=None):
        super().__init__(verbose=True, stream=stream)
        self.progress = progress
        self.file_name = file_name
        self.file_number = file_number
        self.files_total = max(1, files_total)
        self.window_number = 1
        self.windows = 1

    def source_started(self, path, index, total, graph_size):
        self._step(self._percent(0), f"{self.file_name}: starting")
        super().source_started(path, index, total, graph_size)

    def document_staging(self, document_id, staging_name, windows):
        self.windows = max(1, windows)
        self._step(None, f"{windows} window(s) in this document")
        super().document_staging(document_id, staging_name, windows)

    def window_started(self, number, total, window_id):
        self.window_number, self.windows = number, max(1, total)
        self._step(self._percent((number - 1) / total),
                   f"{self.file_name}: window {number}/{total}, "
                   f"asking the model")
        super().window_started(number, total, window_id)

    def model_replied(self, extraction, elapsed):
        self._step(self._percent(0.5),
                   f"{self.file_name}: window {self.window_number}/"
                   f"{self.windows}, model replied in {elapsed:.1f}s")
        super().model_replied(extraction, elapsed)

    def window_admitted(self, number, total, counts, source_size):
        self._step(self._percent(number / total),
                   f"{self.file_name}: window {number}/{total} admitted")
        super().window_admitted(number, total, counts, source_size)

    def saved(self, graph_path, before_size, updated, counts):
        self._step(self._percent(1.0), f"{self.file_name}: published")
        super().saved(graph_path, before_size, updated, counts)

    def _percent(self, within_file):
        done = self.file_number - 1 + max(0.0, min(1.0, within_file))
        return round(100 * done / self.files_total)

    def _step(self, percent, detail):
        if self.progress is not None:
            self.progress.update(percent=percent, detail=detail)


class Workspace:
    """One dataset, its source inbox, and the jobs that change them."""

    def __init__(self, graph_path=DEFAULT_GRAPH, sources_dir=DEFAULT_SOURCES,
                 model=None, names=None, extractor=None, prompts_path=None):
        self.names = names or GraphNames()
        self.graph_path = Path(graph_path)
        self.sources_dir = Path(sources_dir)
        self.model = model
        # An injected extractor is used as-is; otherwise one is built per run,
        # so an edited extraction_system prompt takes effect immediately.
        self.extractor = extractor
        # Prompt overrides live beside the dataset they belong to.
        self.prompts = PromptLibrary(
            prompts_path or self.graph_path.parent / DEFAULT_FILE)
        self.store = RdflibGraphStore(path=self.graph_path)
        self.progress = Progress()
        self.chat = ChatSession(library=self.prompts)

    def extractor_for_run(self):
        """The extractor this run should use, with the prompts in force now."""
        if self.extractor is not None:
            return self.extractor
        return OpenRouterExtractor(
            model=self.model,
            system_prompt=self.prompts.render("extraction_system"))

    # ---------- reading ----------

    def canonical_graph(self):
        """Schema, configured data graphs, and the target data graph."""
        graph = Graph()
        for name in (*self.names.schema_graphs, *self.names.data_graphs,
                     self.names.target_graph):
            for triple in self.store.get(name):
                graph.add(triple)
        return graph

    def triple_count(self):
        return sum(1 for _ in self.store.dataset.quads((None, None, None, None)))

    def source_names(self):
        if not self.sources_dir.is_dir():
            return []
        return sorted(path.name for path in self.sources_dir.iterdir()
                      if path.is_file())

    def status(self):
        """One small record a frontend shows: sizes, starter, and inbox."""
        vocabulary = read_vocabulary(self.canonical_graph())
        return {
            "ok": True,
            "graph": str(self.graph_path),
            "triples": self.triple_count(),
            "ready": not vocabulary.is_empty,
            "classes": vocabulary.class_names,
            "relations": vocabulary.relation_names,
            "facts": vocabulary.fact_names,
            "sources": self.source_names(),
        }

    def dataset_text(self):
        """The canonical ontology as TriG, without provenance bookkeeping."""
        wanted = [*self.names.schema_graphs, *self.names.shape_graphs,
                  *self.names.data_graphs, self.names.target_graph]
        data = Dataset()
        bind(data)
        for name in wanted:
            for subject, predicate, object_ in self.store.get(name):
                data.add((subject, predicate, object_, name))
        return data.serialize(format="trig")

    def progress_state(self, job_id=None):
        """The running job, and its answer once it has one for this job id."""
        return self.progress.snapshot(job_id)

    # ---------- writing ----------

    def reset(self):
        """Delete the dataset file and every source in the inbox."""
        self._check_reset_target()
        removed = []
        if self.graph_path.exists():
            self.graph_path.unlink()
            removed.append(str(self.graph_path))
        if self.sources_dir.is_dir():
            for path in sorted(self.sources_dir.iterdir()):
                if path.is_file():
                    path.unlink()
                    removed.append(str(path))
        self.store = RdflibGraphStore(path=self.graph_path)
        return removed

    def _check_reset_target(self):
        """Refuse to empty a directory that also holds the project itself."""
        inbox = self.sources_dir.resolve()
        cwd = Path.cwd().resolve()
        if inbox == cwd or inbox in cwd.parents:
            raise RuntimeError(
                f"Refusing to reset {inbox}: it is the working directory or "
                f"one of its parents. Point --sources at its own folder.")
        if inbox == self.graph_path.resolve().parent:
            raise RuntimeError(
                f"Refusing to reset {inbox}: it also holds {self.graph_path}. "
                f"Point --sources at its own folder.")

    def create_starter(self, text, progress=None):
        """Propose a starter ontology from pasted text and install it."""
        extractor = self.extractor_for_run()
        if progress is not None:
            def model_call(calls):
                progress.update(
                    percent=min(10 + 25 * calls, 80),
                    detail=f"model call {calls}"
                           + ("" if calls == 1 else " (repairing the answer)"))
            extractor = _CountingExtractor(extractor, model_call)
        proposal = propose_starter(text, extractor, library=self.prompts)
        if progress is not None:
            progress.update(percent=88, detail="writing the schema and shapes")
        self.store.publish(starter_publication(proposal, self.names))
        return proposal

    # ---------- the two jobs a frontend can watch ----------

    def start_starter(self, text):
        """Run create_starter in the background; None when one is running."""
        job = self.progress.claim("Creating the starter ontology")
        if job is None:
            return None
        threading.Thread(target=self._starter_job, args=(text,),
                         daemon=True).start()
        return job

    def start_ingest(self, files):
        """Run ingest in the background; None when one is running."""
        job = self.progress.claim("Ingesting sources")
        if job is None:
            return None
        threading.Thread(target=self._ingest_job, args=(files,),
                         daemon=True).start()
        return job

    def _starter_job(self, text):
        log = io.StringIO()
        try:
            proposal = self.create_starter(text, progress=self.progress)
            log.write("Starter ontology installed:\n"
                      + proposal_summary(proposal) + "\n")
            result = {"ok": True, "proposal": proposal, "log": log.getvalue()}
        except (RuntimeError, OSError, ValueError) as error:
            result = {"ok": False, "error": str(error), "log": log.getvalue()}
        result["status"] = self.status()
        self.progress.finish(result)

    def _ingest_job(self, files):
        log = io.StringIO()
        try:
            names = self.ingest(files, log, progress=self.progress)
            result = {"ok": True, "sources": names, "log": log.getvalue()}
        except (RuntimeError, OSError, ValueError) as error:
            result = {"ok": False, "error": str(error), "log": log.getvalue()}
        result["status"] = self.status()
        self.progress.finish(result)

    def ingest(self, files, log, progress=None):
        """Write dropped sources into the inbox and ingest each one.

        The ordinary run log goes to `log`; when a `progress` object is given,
        every pipeline checkpoint also moves its bar.
        """
        written = []
        for name, text in files:
            if not text.strip():
                continue
            written.append(self._write_source(name, text))
        if progress is not None:
            progress.update(percent=0,
                            detail=f"{len(written)} file(s) written to the inbox")
        for number, path in enumerate(written, start=1):
            log.write(f"\n=== {path.name} ===\n")
            result = run_text_to_graph(
                RunRequest(source=path, graph_path=self.graph_path,
                           merge=MergeConfig(require_declared_vocabulary=True),
                           prompts=self.prompts),
                graph_store=self.store,
                extractor=self.extractor_for_run(),
                reporter=_ProgressReporter(log, path.name, number,
                                           len(written), progress),
            )
            log.write(f"\n{path.name}: {result.triples} triples in the dataset\n")
        return [path.name for path in written]

    # ---------- talking to the graph ----------

    def ask_text(self, prompt, system=None):
        """One text answer from the configured extractor (never JSON).

        The system message comes from the caller (the chat prompt), not from
        the extractor, whose own message is the JSON extraction contract.
        """
        extractor = self.extractor_for_run()
        answer = getattr(extractor, "extract_text", None)
        if answer is None:
            raise RuntimeError(
                "the configured extractor cannot answer with text, so the "
                "graph chat cannot run")
        return answer(prompt, system=system)

    def chat_state(self):
        """The conversation so far, and what it is currently about."""
        return self.chat.state()

    def chat_reset(self):
        """Forget the conversation."""
        state = self.chat.reset()
        return {**state, "log": "Conversation cleared.\n"}

    def chat_ask(self, message, on_step=None):
        """One chat turn: select the relevant subgraph, ask, remember."""
        if not str(message or "").strip():
            return {"ok": False, "error": "no question was given"}
        try:
            outcome = self.chat.ask(message, self.canonical_graph(),
                                    self.ask_text, on_step=on_step)
        except (RuntimeError, OSError, ValueError) as error:
            return {"ok": False, "error": str(error),
                    "turns": self.chat.transcript()}
        scope = outcome["scope"]
        return {"ok": True, "answer": outcome["answer"],
                "scope": {**scope.summary(), "view": scope.view()},
                "turns": self.chat.transcript()}

    def start_chat(self, message):
        """Run one chat turn in the background; None when a job is running."""
        job = self.progress.claim("Talking to the graph")
        if job is None:
            return None
        self.progress.update(percent=10, detail="selecting the relevant subgraph")
        threading.Thread(target=self._chat_job, args=(message,),
                         daemon=True).start()
        return job

    def _chat_job(self, message):
        def note(scope, rendered):
            self.progress.update(
                percent=40,
                detail=f"{rendered['triples']} triples selected"
                       + (f" ({rendered['dropped']} left out)" 
                          if rendered["dropped"] else "")
                       + "; asking the model")

        result = self.chat_ask(message, on_step=note)
        self.progress.finish(result)

    def import_starter(self, name, text):
        """Make a dropped RDF document the starter ontology, in one write."""
        if not str(text).strip():
            return {"ok": False, "error": "the file is empty"}
        try:
            publication, summary = import_publication(text, name, self.names)
        except (ValueError, OSError) as error:
            return {"ok": False, "error": str(error)}
        self.store.publish(publication)
        return {"ok": True, "summary": summary,
                "log": f"Imported {name}\n" + import_summary(summary) + "\n",
                "status": self.status()}

    # ---------- prompts ----------

    def prompt_list(self):
        """Every prompt template, with its override state and any problem."""
        return {"ok": True, "prompts": self.prompts.describe()}

    def prompt_save(self, name, text):
        """Validate and store one edited template."""
        try:
            error = self.prompts.set(name, text)
        except KeyError as unknown:
            return {"ok": False, "error": str(unknown.args[0])}
        if error:
            return {"ok": False, "error": error,
                    "prompts": self.prompts.describe()}
        return {"ok": True, "log": f"{name} saved to {self.prompts.path}\n",
                "prompts": self.prompts.describe()}

    def prompt_reset(self, name):
        """Go back to the tested default for one template."""
        try:
            self.prompts.reset(name)
        except KeyError as unknown:
            return {"ok": False, "error": str(unknown.args[0])}
        return {"ok": True, "log": f"{name} is back to its default\n",
                "prompts": self.prompts.describe()}

    def prompt_preview(self, name):
        """Render one template with its sample values, for the editor."""
        try:
            error = self.prompts.validate(name, self.prompts.text(name))
        except KeyError as unknown:
            return {"ok": False, "error": str(unknown.args[0])}
        if error:
            return {"ok": False, "error": error}
        try:
            rendered = self.prompts.render(name, dict(PREVIEW_VALUES.get(name, {})))
        except ValueError as failure:
            return {"ok": False, "error": str(failure)}
        return {"ok": True, "prompt": rendered,
                "values": dict(PREVIEW_VALUES.get(name, {}))}

    def _write_source(self, name, text):
        """One dropped file, saved under a safe name in the inbox."""
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        stem = "".join(character for character in Path(name).name
                       if character.isalnum() or character in "._- ") or "source"
        target = self.sources_dir / stem
        number = 2
        while target.exists():
            target = self.sources_dir / f"{stem}-{number}"
            number += 1
        target.write_text(text, encoding="utf-8")
        return target
