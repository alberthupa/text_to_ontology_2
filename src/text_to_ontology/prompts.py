"""Editable prompt templates: defaults in code, overrides in one JSON file.

Every prompt the application sends to a model is a named template here. The
defaults are the tested ones; a user can edit any of them in the studio, and an
override is stored in `prompts.local.json` next to the dataset. Nothing else
changes: the pipeline, the starter, and the tests all read the same names.

Templates use `string.Template` placeholders (`${context}`, `${text}`), not
`str.format`, because these prompts contain JSON braces that a human edits by
hand and should never have to escape.

`PROMPT_FIELDS` lists the placeholders a template may use, and
`REQUIRED_FIELDS` the ones it must keep. `validate()` is what the studio calls
before saving: an unknown placeholder, a missing required one, a bare `$`, or an
empty template is a clear error instead of a broken run.
"""

import hashlib
import json
import os
import re
import string
from pathlib import Path

DEFAULT_FILE = "prompts.local.json"

EXTRACTION_SYSTEM = "Extract knowledge. Return only JSON."

EXTRACTION_USER = """
Extract only knowledge stated or clearly implied by SOURCE.

${context}Entity resolution is important. Set existing_id to an
existing entity's exact id only when it is the same real thing in this context.
Use its names, kind, and description. A similar name alone is not enough.
Otherwise use null. Include one entity record per real thing mentioned in this
source.

Return this exact JSON shape:
{
  "entities": [
    {"id": "e1", "name": "preferred name", "kind": "Person",
      "description": "short source-grounded description",
      "aliases": ["other source name"], "existing_id": null,
      "confidence": 0.9}
  ],
  "relations": [
    {"subject": "e1", "predicate": "works for", "object": "e2",
      "confidence": 0.9}
  ],
  "facts": [
    {"subject": "e1", "predicate": "birth date", "value": "1950-01-01",
      "confidence": 0.9}
  ]
}

Every record requires a confidence from 0.0 to 1.0: your confidence that SOURCE
directly supports that complete record. It is not confidence that an identity
match is correct, not a probability that the statement is true in the world, and
not source authority.

Relation endpoints and fact subjects must use ids from entities. Use empty lists
when needed. Return JSON only.

SOURCE:
---
${text}
---
""".strip()

STARTER = """
You design the starter ontology for a small knowledge base.

Read the initial information below and answer with exactly one JSON object:

{
  "classes": [
    {"name": "Person", "description": "a human being"}
  ],
  "relations": [
    {"name": "works-for", "description": "is employed by",
      "domain": "Person", "range": "Organization"}
  ],
  "facts": [
    {"name": "founded-in", "description": "year the organization started",
      "domain": "Organization", "range": "integer"}
  ]
}

Rules:
- ${min_classes} to ${max_classes} classes, named in singular Title Case.
- A relation connects two classes: "domain" is where it starts, "range" is
  where it ends, and both must be one of the class names.
- A fact gives a literal value: it has a "domain" class and optionally a
  "range" from: ${xsd_names}.
- Relation and fact names are short lowercase words separated by hyphens.
  Never write camelCase, underscores, or empty values.
- descriptions are optional and short.
- Propose only what the initial information supports; do not invent a domain.
- Answer with that JSON object only. No Markdown, no explanations.

INITIAL INFORMATION
---
${text}
---
""".strip()

LINK_CHECK_USER = """
${question}

Relationship: ${relation}

SUBJECT
${subject}

CANDIDATES - the only things the subject may be linked to
${candidates}

PASSAGES - the only evidence
---
${passages}
---

Answer with one JSON object:
{"links": [{"object": "c1", "evidence": "words copied exactly from PASSAGES",
  "confidence": 0.9}]}

Add a link only when PASSAGES state it or clearly imply it for this subject. A
thing that is only compared with, mentioned next to, or proposed for the
subject is not linked to it. "evidence" must be copied word for word from
PASSAGES: the shortest sentence or phrase that shows the link. "confidence" is
your confidence, from 0.0 to 1.0, that the evidence supports the link. If
PASSAGES do not establish it, answer {"links": []}. Return JSON only.
""".strip()

CHAT_SYSTEM = """You answer questions about one knowledge graph, using only the
subgraph you are given. You never invent facts, classes, or relationships, and
you say plainly when the answer is not in the part you can see.

Answer in plain conversational prose, as you would say it out loud. Never
answer with JSON, XML, YAML, or any other data structure, and never repeat the
question back with your own fields added to it.""".strip()

CHAT_USER = """
QUESTION
${question}

WHAT WAS ALREADY SAID
${history}

THE PART OF THE GRAPH SELECTED FOR THIS QUESTION
${scope_note}
${subgraph}

How to answer:
- Use only the statements above. They are the relevant part of the graph, not
  all of it.
- If something is not there, say so, and say what would have to be ingested or
  added for it to be answerable.
- Name things as the graph names them, and quote the identifiers when a name
  could be ambiguous.
- Be brief. A short paragraph, or a few lines when the answer is a list.
- If the question asks for a change to the graph, describe the change you would
  make in Turtle and clearly mark it as a proposal.
- Never answer with JSON and never repeat these instructions.
""".strip()

DEFAULT_PROMPTS = {
    "extraction_system": EXTRACTION_SYSTEM,
    "extraction_user": EXTRACTION_USER,
    "starter": STARTER,
    "link_check_user": LINK_CHECK_USER,
    "chat_system": CHAT_SYSTEM,
    "chat_user": CHAT_USER,
}

# The placeholders a template may use, and the ones it must keep.
PROMPT_FIELDS = {
    "extraction_system": (),
    "extraction_user": ("context", "text"),
    "starter": ("min_classes", "max_classes", "xsd_names", "text"),
    "link_check_user": ("question", "relation", "subject", "candidates",
                        "passages"),
    "chat_system": (),
    "chat_user": ("question", "history", "scope_note", "subgraph"),
}
REQUIRED_FIELDS = {
    "extraction_system": (),
    "extraction_user": ("context", "text"),
    "starter": ("text",),
    "link_check_user": ("subject", "candidates", "passages"),
    "chat_system": (),
    "chat_user": ("question", "subgraph"),
}

# What the studio renders for a preview; small, fixed, and testable.
PREVIEW_VALUES = {
    "extraction_system": {},
    "extraction_user": {
        "context": (
            "ONTOLOGY CONTEXT - selected for this source, not the whole "
            "ontology:\n- [class] Person is a kind of Entity.\n\n"
            "Only an exact \"id:\" value above may be used as existing_id.\n\n"),
        "text": "Acme Corp participates in Springfield.",
    },
    "starter": {
        "min_classes": 2, "max_classes": 20,
        "xsd_names": "string, integer, decimal, float, boolean, date, "
                     "datetime, anyURI",
        "text": "We are a coffee roaster: farms, coffee lots, retailers, "
                "and the shipments between them.",
    },
    "link_check_user": {
        "question": "Which client is this project delivered for?",
        "relation": "Project --has client--> Client",
        "subject": "- Virtual Assistant of Farmexa (kind: Project); also "
                   "called VAF",
        "candidates": "- c1: Farmexa (kind: Client); already in the graph",
        "passages": "Comparison of Copilot with VAF for Farmexa's request.",
    },
    "chat_system": {},
    "chat_user": {
        "question": "How many people live in Poland?",
        "history": "(nothing yet)",
        "scope_note": "12 triples selected for this question",
        "subgraph": 'geo:poland rdfs:label "Poland"\n'
                    'geo:poland geo:population "38000000"^^xsd:integer',
    },
}

# Advisory checks a human editor benefits from (never blocking).
ADVICE = {
    "extraction_user": [
        ("entities", 'the answer shape needs an "entities" list'),
        ("relations", 'the answer shape needs a "relations" list'),
        ("facts", 'the answer shape needs a "facts" list'),
        ("confidence", "every record needs a confidence from 0.0 to 1.0"),
        ("SOURCE", "the source text must be marked, e.g. SOURCE:"),
    ],
    "link_check_user": [
        ("links", 'the answer shape needs a "links" list'),
        ("evidence", "every link needs evidence quoted from the passages"),
    ],
    "starter": [
        ("classes", 'the answer shape needs a "classes" list'),
        ("relations", 'the answer shape needs a "relations" list'),
        ("facts", 'the answer shape needs a "facts" list'),
    ],
}

# ${name} or $name, where the bare form must look like an identifier; "$$"
# stays available for a literal dollar sign, exactly as string.Template wants.
_PLACEHOLDER = re.compile(r"\$(?:\{(\w+)\}|([_a-zA-Z]\w*))")
_BARE_DOLLAR = re.compile(r"(?<!\$)\$(?!\{[_a-zA-Z]\w*\}|[_a-zA-Z]\w*|\$)")


class PromptLibrary:
    """The named templates in use, with optional overrides from one file."""

    def __init__(self, path=None, defaults=None):
        self.path = Path(path) if path else None
        self.defaults = dict(defaults or DEFAULT_PROMPTS)
        self.overrides = self._read()

    # ---------- reading ----------

    def names(self):
        return sorted(self.defaults)

    def text(self, name):
        """The template in use: the override, or the tested default."""
        self._known(name)
        return self.overrides.get(name, self.defaults[name])

    def is_default(self, name):
        self._known(name)
        return name not in self.overrides

    def fields(self, name):
        self._known(name)
        return tuple(PROMPT_FIELDS.get(name, ()))

    def required(self, name):
        self._known(name)
        return tuple(REQUIRED_FIELDS.get(name, ()))

    def digest(self, name):
        """A short stable hash of the template in use, for run reports."""
        return hashlib.sha256(self.text(name).encode("utf-8")).hexdigest()[:12]

    def describe(self, name=None):
        """Everything a frontend needs to edit one template."""
        names = [name] if name else self.names()
        described = []
        for item in names:
            text = self.text(item)
            described.append({
                "name": item,
                "text": text,
                "default": self.is_default(item),
                "required": list(self.required(item)),
                "fields": list(self.fields(item)),
                "error": self.validate(item, text),
                "advice": self.advice(item, text),
            })
        return described

    # ---------- checking ----------

    def validate(self, name, text):
        """Why this template cannot be used, or None when it is fine."""
        self._known(name)
        if not str(text).strip():
            return "the template is empty"
        if _BARE_DOLLAR.search(text):
            return ("a bare $ must be followed by a placeholder name; "
                    "write $$ for a literal dollar sign")
        used = {match.group(1) or match.group(2)
                for match in _PLACEHOLDER.finditer(text)}
        unknown = sorted(used - set(self.fields(name)))
        if unknown:
            return ("unknown placeholder(s): "
                    + ", ".join("$" + item for item in unknown)
                    + ("; this template may use: "
                       + ", ".join("$" + item for item in self.fields(name))
                       if self.fields(name) else "; this template uses none"))
        missing = [item for item in self.required(name) if item not in used]
        if missing:
            return ("required placeholder(s) missing: "
                    + ", ".join("$" + item for item in missing))
        return None

    def advice(self, name, text):
        """Advisory notes for a human editor; never blocking."""
        self._known(name)
        return [message for token, message in ADVICE.get(name, [])
                if token not in text]

    # ---------- rendering ----------

    def render(self, name, values=None):
        """Fill one template with values; missing values are a clear error."""
        text = self.text(name)
        values = dict(values or {})
        try:
            return string.Template(text).substitute(values)
        except KeyError as missing:
            raise ValueError(
                f"{name}: no value for placeholder {missing} - "
                f"this template needs: "
                + ", ".join("$" + item for item in self.fields(name))) from missing
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error

    # ---------- writing ----------

    def set(self, name, text):
        """Validate and store one override; returns the error, or None."""
        error = self.validate(name, text)
        if error:
            return error
        self.overrides[name] = text
        self._write()
        return None

    def reset(self, name):
        """Drop one override; True when there was one to drop."""
        self._known(name)
        if name not in self.overrides:
            return False
        del self.overrides[name]
        self._write()
        return True

    # ---------- the file ----------

    def _read(self):
        if self.path is None or not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        stored = data.get("prompts") if isinstance(data, dict) else None
        if not isinstance(stored, dict):
            return {}
        return {name: text for name, text in stored.items()
                if name in self.defaults and isinstance(text, str)
                and not self.validate(name, text)}

    def _write(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = str(self.path) + ".tmp"
        payload = {"version": 1, "prompts": dict(sorted(self.overrides.items()))}
        try:
            Path(temporary).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _known(self, name):
        if name not in self.defaults:
            raise KeyError(f"unknown prompt {name!r}; known prompts: "
                           + ", ".join(self.names()))


# One defaults-only library for callers that have no editable file.
DEFAULT_LIBRARY = PromptLibrary()


def render(name, values=None, library=None):
    """Render one prompt from a library, or from the tested defaults."""
    return (library or DEFAULT_LIBRARY).render(name, values)


def describe(library=None):
    """Describe every prompt, override or default."""
    return (library or DEFAULT_LIBRARY).describe()


def digest(name, library=None):
    """The short hash of one template in use."""
    return (library or DEFAULT_LIBRARY).digest(name)
