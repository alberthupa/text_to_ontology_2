"""Every capability of the application, as one named operation.

This module is the contract between a frontend and the backend. The HTTP
transport, the tests, and any future frontend all call the same names, and the
same names are published to a page (`operations.list`) so a client never has to
guess what exists. Each operation takes a plain JSON payload and returns a
plain JSON record - no objects, no HTTP, no browser.

An operation is either:

  * immediate - it answers with the result; or
  * background - it starts the one long job and answers with a `job_id`, which
    the caller then follows with `progress`.

Adding a capability means adding one small function here and one line in the
`OPERATIONS` tuple. Nothing else in the codebase needs to change, and
`describe()` keeps the documentation and the frontend honest.
"""

from dataclasses import dataclass


class UnknownOperation(KeyError):
    """The caller asked for a name that is not in the registry."""


@dataclass(frozen=True)
class Operation:
    """One named capability: what it is for, what it reads, how it answers."""

    name: str
    summary: str
    handler: object
    args: tuple = ()
    background: bool = False


# ---------- the operations ----------

def _status(workspace, payload):
    return workspace.status()


def _dataset(workspace, payload):
    return {"ok": True, "trig": workspace.dataset_text()}


def _progress(workspace, payload):
    return workspace.progress_state(_integer(payload.get("job")))


def _reset(workspace, payload):
    removed = workspace.reset()
    log = ("Removed:\n" + "\n".join(f"  {path}" for path in removed) + "\n") \
        if removed else "Nothing to remove.\n"
    return {"ok": True, "removed": removed, "log": log,
            "status": workspace.status()}


def _starter_create(workspace, payload):
    text = str(payload.get("text") or "")
    if not text.strip():
        return {"ok": False, "error": "no starter description was given"}
    return _started(workspace, workspace.start_starter(text))


def _starter_import(workspace, payload):
    name = str(payload.get("name") or "starter.ttl")
    text = str(payload.get("text") or "")
    if not text.strip():
        return {"ok": False, "error": "no RDF file content was given"}
    return workspace.import_starter(name, text)


def _ingest(workspace, payload):
    files = _files(payload)
    if not files:
        return {"ok": False, "error": "no source files were given"}
    return _started(workspace, workspace.start_ingest(files))


def _prompts_list(workspace, payload):
    return workspace.prompt_list()


def _prompts_save(workspace, payload):
    name = str(payload.get("name") or "")
    if not name:
        return {"ok": False, "error": "no prompt name was given"}
    return workspace.prompt_save(name, str(payload.get("text") or ""))


def _prompts_reset(workspace, payload):
    name = str(payload.get("name") or "")
    if not name:
        return {"ok": False, "error": "no prompt name was given"}
    return workspace.prompt_reset(name)


def _prompts_preview(workspace, payload):
    name = str(payload.get("name") or "")
    if not name:
        return {"ok": False, "error": "no prompt name was given"}
    return workspace.prompt_preview(name)


def _chat_ask(workspace, payload):
    message = str(payload.get("message") or "")
    if not message.strip():
        return {"ok": False, "error": "no question was given"}
    return _started(workspace, workspace.start_chat(message))


def _chat_state(workspace, payload):
    return workspace.chat_state()


def _chat_reset(workspace, payload):
    return workspace.chat_reset()


def _operations(workspace, payload):
    return {"ok": True, "operations": describe()}


OPERATIONS = (
    Operation("status", "dataset size, starter vocabulary, and inbox", _status),
    Operation("dataset", "the canonical ontology as one TriG text", _dataset),
    Operation("progress", "the running job, and its answer for one job id",
              _progress, args=("job",)),
    Operation("reset", "delete the dataset file and the inbox", _reset),
    Operation("starter.create",
              "propose a starter ontology from a pasted description",
              _starter_create, args=("text",), background=True),
    Operation("starter.import", "import an RDF/Turtle/TriG file as the starter",
              _starter_import, args=("name", "text")),
    Operation("ingest", "ingest dropped texts, data-only",
              _ingest, args=("files",), background=True),
    Operation("chat.ask", "one question about the graph, answered from the "
              "relevant subgraph", _chat_ask, args=("message",),
              background=True),
    Operation("chat.state", "the conversation so far", _chat_state),
    Operation("chat.reset", "forget the conversation", _chat_reset),
    Operation("operations.list", "this list of named capabilities", _operations),
    Operation("prompts.list", "the editable prompt templates and their state",
              _prompts_list),
    Operation("prompts.save", "validate and store one edited prompt template",
              _prompts_save, args=("name", "text")),
    Operation("prompts.reset", "go back to the tested default for one template",
              _prompts_reset, args=("name",)),
    Operation("prompts.preview", "render one template with sample values",
              _prompts_preview, args=("name",)),
)

REGISTRY = {operation.name: operation for operation in OPERATIONS}


def describe():
    """The published manifest: name, purpose, arguments, and how it answers."""
    return [{"name": operation.name,
             "summary": operation.summary,
             "args": list(operation.args),
             "background": operation.background}
            for operation in sorted(OPERATIONS, key=lambda item: item.name)]


def call(workspace, name, payload=None):
    """Run one named operation over one workspace.

    Raises `UnknownOperation` for a name that is not registered; every other
    failure is the operation's own error, which the transport reports.
    """
    operation = REGISTRY.get(name)
    if operation is None:
        raise UnknownOperation(name)
    return operation.handler(workspace, payload or {})


# ---------- payload helpers ----------

def _started(workspace, job):
    """The answer of a background operation, or why it could not start."""
    if job is None:
        return {"ok": False,
                "error": "a job is already running; wait for it",
                "status": workspace.status()}
    return {"ok": True, "job_id": job, "status": workspace.status()}


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _files(payload):
    """Dropped texts read from a payload: [(name, text), ...]."""
    files = payload.get("files")
    if not isinstance(files, list):
        return []
    return [(str(item.get("name") or "source.txt"), str(item.get("text") or ""))
            for item in files if isinstance(item, dict)]
