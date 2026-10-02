"""A tiny local studio: the Triple Lens page plus reset, starter, and ingest.

Run it, open the printed address, and the lens grows a right-hand column:

  1. paste a short description and create the starter ontology,
  2. drop source files to ingest them,
  3. reset everything and start again.

The server is deliberately plain: standard-library HTTP, one request at a
time, bound to localhost, and it only ever touches the configured dataset
file and the source inbox directory. Ingestion is data-only: the starter
classes and relationships cannot change.

    python3 -m text_to_ontology.studio
    text-to-ontology-studio --graph ontology.trig --reset
"""

import argparse
import io
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from rdflib import Dataset, Graph

from .graph_management import bind
from .graph_store import GraphNames, RdflibGraphStore
from .llm import OpenRouterExtractor
from .pipeline import MergeConfig, RunRequest, run_text_to_graph
from .run_report import RunReporter
from .starter import proposal_summary, propose_starter, starter_publication
from .vocabulary import read_vocabulary

DEFAULT_GRAPH = Path("ontology.trig")
DEFAULT_SOURCES = Path("sources/inbox")
DEFAULT_PORT = 8765
PAGE_NAME = "scripts/triple-lens.html"


def find_page(explicit=None):
    """The Triple Lens page: the given path, then the usual repository paths."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.cwd() / PAGE_NAME)
    candidates.append(Path(__file__).resolve().parents[2] / PAGE_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"Could not find {PAGE_NAME}; start the studio from the project "
        f"directory or pass --page")


class Studio:
    """Everything the studio can do, with no HTTP in it."""

    def __init__(self, graph_path=DEFAULT_GRAPH, sources_dir=DEFAULT_SOURCES,
                 page_path=None, model=None, names=None, extractor=None):
        self.names = names or GraphNames()
        self.graph_path = Path(graph_path)
        self.sources_dir = Path(sources_dir)
        self.page_path = Path(page_path) if page_path else find_page()
        self.extractor = extractor or OpenRouterExtractor(model=model)
        self.store = RdflibGraphStore(path=self.graph_path)

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
        """One small record the page shows: sizes, starter, and inbox."""
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

    # ---------- writing ----------

    def reset(self):
        """Delete the dataset file and every source in the inbox."""
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

    def create_starter(self, text):
        """Propose a starter ontology from pasted text and install it."""
        proposal = propose_starter(text, self.extractor)
        self.store.publish(starter_publication(proposal, self.names))
        return proposal

    def ingest(self, files, log):
        """Write dropped sources into the inbox and ingest each one."""
        written = []
        for name, text in files:
            if not text.strip():
                continue
            written.append(self._write_source(name, text))
        reporter = RunReporter(verbose=True, stream=log)
        for path in written:
            log.write(f"\n=== {path.name} ===\n")
            result = run_text_to_graph(
                RunRequest(source=path, graph_path=self.graph_path,
                           merge=MergeConfig(require_declared_vocabulary=True)),
                graph_store=self.store,
                extractor=self.extractor,
                reporter=reporter,
            )
            log.write(f"\n{path.name}: {result.triples} triples in the dataset\n")
        return [path.name for path in written]

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


class StudioHandler(BaseHTTPRequestHandler):
    """The studio's tiny JSON API, plus the lens page itself."""

    studio = None
    server_version = "TextToOntologyStudio"

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._page()
        if self.path == "/api/status":
            return self._json(self.studio.status())
        if self.path == "/api/dataset":
            return self._json({"ok": True, "trig": self.studio.dataset_text()})
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        payload = self._payload()
        log = io.StringIO()
        try:
            if self.path == "/api/reset":
                removed = self.studio.reset()
                if removed:
                    log.write("Removed:\n"
                              + "\n".join(f"  {path}" for path in removed) + "\n")
                else:
                    log.write("Nothing to remove.\n")
                answer = {"removed": removed, "log": log.getvalue()}
            elif self.path == "/api/starter":
                proposal = self.studio.create_starter(payload.get("text", ""))
                log.write("Starter ontology installed:\n"
                          + proposal_summary(proposal) + "\n")
                answer = {"proposal": proposal, "log": log.getvalue()}
            elif self.path == "/api/ingest":
                names = self.studio.ingest(
                    self._files(payload), log)
                answer = {"sources": names, "log": log.getvalue()}
            else:
                return self._json({"ok": False, "error": "not found"}, 404)
        except (RuntimeError, OSError, ValueError) as error:
            return self._json({"ok": False, "error": str(error),
                               "log": log.getvalue(),
                               "status": self.studio.status()})
        return self._json({**answer, "ok": True,
                           "status": self.studio.status()})

    # ---------- request helpers ----------

    def _page(self):
        body = self.studio.page_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _payload(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _files(self, payload):
        """The dropped texts: [{name, text}, ...]."""
        files = payload.get("files")
        if not isinstance(files, list):
            return []
        return [(str(item.get("name") or "source.txt"), str(item.get("text") or ""))
                for item in files if isinstance(item, dict)]

    def log_message(self, fmt, *args):
        print(f"[studio] {self.address_string()} {fmt % args}")


def create_server(studio, host="127.0.0.1", port=DEFAULT_PORT):
    """One plain HTTP server, one request at a time."""
    handler = type("BoundStudioHandler", (StudioHandler,), {"studio": studio})
    return HTTPServer((host, port), handler)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Open the Triple Lens studio: starter ontology, "
                    "drag-and-drop ingestion, and reset.")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH,
                        help="the TriG dataset to work on (default ontology.trig)")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES,
                        help="where dropped source files are kept "
                             "(default sources/inbox)")
    parser.add_argument("--page", type=Path, default=None,
                        help="the Triple Lens HTML page to serve")
    parser.add_argument("--host", default="127.0.0.1",
                        help="the address to listen on (default: localhost only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"the port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--model", default=None,
                        help="the OpenRouter model to use")
    parser.add_argument("--reset", action="store_true",
                        help="delete the dataset and the inbox, then exit")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open the studio in a browser")
    return parser


def main(argv=None):
    """Start the studio, or reset everything with --reset."""
    args = build_parser().parse_args(argv)
    try:
        studio = Studio(graph_path=args.graph, sources_dir=args.sources,
                        page_path=args.page, model=args.model)
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}")
        raise SystemExit(1) from error

    if args.reset:
        removed = studio.reset()
        print(f"Removed {len(removed)} path(s):")
        for path in removed:
            print(f"  {path}")
        return

    try:
        server = create_server(studio, args.host, args.port)
    except OSError as error:
        print(f"Error: cannot listen on {args.host}:{args.port}: {error}")
        raise SystemExit(1) from error
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Triple Lens studio on {url}")
    print(f"Dataset: {studio.graph_path}   Sources: {studio.sources_dir}")
    print("Press Ctrl-C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
