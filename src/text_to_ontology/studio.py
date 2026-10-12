"""The studio's HTTP transport: the lens page, its assets, and named operations.

This module only carries things. All state and behaviour live in
`workspace.Workspace`, and every capability is a named operation in
`operations.py`. The routes are deliberately generic:

    GET  /                      the lens page (frontend/triple-lens.html)
    GET  /studio.js             the studio frontend: top-bar actions, dialogs, chat
    GET  /studio.css            its styles
    GET  /api/op/<name>?...     one read-only operation, arguments in the query
    POST /api/op/<name>         one operation, arguments as a JSON body

The manifest of operation names is itself an operation: `operations.list`.
Adding a capability therefore never touches this file.

Run it, open the printed address, and the lens grows a studio row in its top
bar (starter ontology, sources, prompts, graph editing, reset) and a
conversation column on the right.

    python3 -m text_to_ontology.studio
    text-to-ontology-studio --graph ontology.trig --reset
"""

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .operations import UnknownOperation, call
from .workspace import DEFAULT_GRAPH, DEFAULT_SOURCES, Workspace

DEFAULT_PORT = 8765
PAGE_NAME = "frontend/triple-lens.html"
# The frontend lives in frontend/ beside the page; only these suffixes are
# served from there, everything else is refused.
ASSET_TYPES = {".js": "text/javascript; charset=utf-8",
               ".css": "text/css; charset=utf-8"}


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


class Assets:
    """The files the transport serves: the page and the panel beside it."""

    def __init__(self, page=None):
        self.page = find_page(page)
        self.directory = self.page.parent

    def body(self, path):
        """The bytes and content type for one URL path, or (None, None)."""
        if path in ("/", "/index.html"):
            return self.page.read_bytes(), "text/html; charset=utf-8"
        suffix = Path(path).suffix
        if suffix not in ASSET_TYPES:
            return None, None
        candidate = self.directory / Path(path).name
        if not candidate.is_file():
            return None, None
        return candidate.read_bytes(), ASSET_TYPES[suffix]


class StudioHandler(BaseHTTPRequestHandler):
    """One generic dispatcher over the operation registry."""

    workspace = None
    assets = None
    server_version = "TextToOntologyStudio"

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if not path.startswith("/api/"):
            body, content_type = self.assets.body(path)
            if body is None:
                return self._json({"ok": False, "error": "not found"}, 404)
            return self._bytes(body, content_type)
        if not path.startswith("/api/op/"):
            return self._json({"ok": False, "error": "not found"}, 404)
        payload = {name: values[-1] for name, values in parse_qs(query).items()}
        return self._run(path[len("/api/op/"):], payload)

    def do_POST(self):
        path, _, _query = self.path.partition("?")
        if not path.startswith("/api/op/"):
            return self._json({"ok": False, "error": "not found"}, 404)
        return self._run(path[len("/api/op/"):], self._payload())

    def _run(self, name, payload):
        """One named operation; unknown names are the only 404."""
        try:
            answer = call(self.workspace, name, payload)
        except UnknownOperation:
            return self._json({"ok": False, "error": f"unknown operation {name!r}"},
                              404)
        except (RuntimeError, OSError, ValueError, KeyError) as error:
            # A bug in one operation must not kill the connection; the page
            # shows the message and keeps working.
            return self._json({"ok": False, "error": f"{type(error).__name__}: {error}"})
        return self._json(answer)

    # ---------- request helpers ----------

    def _bytes(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(body)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(body)

    def _write(self, body):
        """Send the body; a client that already hung up is not an error.

        A browser tab closed mid-load, a reload, or an editor probing the
        port can drop the connection before the page is sent. Nothing is
        lost: there is nobody left to answer.
        """
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _payload(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def log_message(self, fmt, *args):
        print(f"[studio] {self.address_string()} {fmt % args}")


class StudioServer(ThreadingHTTPServer):
    """Threads only so a page can poll while one job runs; writes stay serial."""

    daemon_threads = True
    allow_reuse_address = True


def create_server(workspace, host="127.0.0.1", port=DEFAULT_PORT, tries=10,
                  assets=None):
    """The studio's HTTP server.

    If the requested port is taken (another tool may well be sitting on it),
    the next free port is used instead; `server_address` has the real one.
    """
    assets = assets or Assets()
    handler = type("BoundStudioHandler", (StudioHandler,),
                   {"workspace": workspace, "assets": assets})
    last_error = None
    for candidate in (port, *range(port + 1, port + tries)) if port else (0,):
        try:
            return StudioServer((host, candidate), handler)
        except OSError as error:
            last_error = error
    raise last_error


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
                        help=f"the port to listen on (default {DEFAULT_PORT}; "
                             f"the next free port is used when it is taken)")
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
        workspace = Workspace(graph_path=args.graph, sources_dir=args.sources,
                              model=args.model)
        assets = Assets(args.page)
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}")
        raise SystemExit(1) from error

    if args.reset:
        removed = workspace.reset()
        print(f"Removed {len(removed)} path(s):")
        for path in removed:
            print(f"  {path}")
        return

    try:
        server = create_server(workspace, args.host, args.port, assets=assets)
    except OSError as error:
        print(f"Error: cannot listen on {args.host}:{args.port}: {error}")
        raise SystemExit(1) from error
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Triple Lens studio on {url}")
    print(f"Dataset: {workspace.graph_path}   Sources: {workspace.sources_dir}")
    print(f"Operations: {url}api/op/operations.list")
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
