# Dead simple text to ontology

This is a deliberately small experiment, not a framework. Give it one text file
or a directory of text-like files. It asks an LLM to extract entities,
relations, and literal facts, then saves them in an RDF dataset with named
graphs (`ontology.trig` by default).

Every source file is one document with a stable content-derived ID. A long
document is split into reproducible overlapping windows, and each window's
answer is admitted into that document's own *source staging graph* before
anything canonical happens: a later window sees what earlier windows already
extracted (clearly marked `(this document)` in its prompt), repeated names are
reconciled inside the document instead of duplicated, and anything ambiguous or
conflicting is held for review rather than silently merged. After the last
window, the complete source graph gets an explicit reconciliation report and is
validated against every configured SHACL shape graph. Identity against the
whole configured canonical scope is then decided once for the complete
document: an exact
identifier or a unique exact name/alias match resolves to the existing entity,
an ambiguous or close-spelling match is held for review, and only confident,
unambiguous records create new entities. The proposed data is SHACL-validated,
then target, provenance, and review graphs are published in one atomic call.

## Starter ontology, then data only

The quickest way in is the studio: a small local page with the Triple Lens
graph in the middle, a studio row in the top bar with one button per action,
and a conversation with the graph on the right.

```bash
pip install -e .
text-to-ontology-studio            # prints a localhost URL and opens it
```

The studio row reads, left to right: the dataset (file name, triples, sources),
then **Starter ontology…**, **Add sources…**, **Prompts…**, **Edit the graph…**,
then **Clear view** and **Reset everything**, the last thing the studio said,
and **Log**. Each "…" button opens a dialog for that one action; the progress
bar for a long job appears under the row. The right-hand column is only the
conversation with the graph.

1. **Create the starter ontology.** Paste a few sentences about the world
   ("We roast coffee, we buy green coffee from farms, we sell bags to cafes").
   The model proposes the classes, relations, and facts; they are checked and
   written as the dataset's schema and shapes. The same thing from the command
   line, reading a file or standard input:

   ```bash
   text-to-ontology-starter notes.md ontology.trig
   echo "We roast coffee and sell it to cafes." | text-to-ontology-starter - ontology.trig
   ```

   Already have an ontology? Drop an RDF/Turtle/TriG file on the Starter
   ontology dialog (or choose it there) and it is **imported** instead of asked: its classes and relations become the starter
   vocabulary, its individuals become data, and its own IRIs are kept — after
   the import, ingestion types and links new individuals with *those* names. A
   file that declares no classes or properties is refused, and a failed import
   leaves the previous dataset untouched. On the command line:

   ```bash
   text-to-ontology-starter --import my_ontology.ttl ontology.trig
   ```

Both long steps run in the background while the page polls the `progress`
operation, so the studio shows a progress bar under the studio row: the
starter counts model calls (including repairs), and ingestion counts files and
windows (`n2.txt: window 1/1, asking the model` → `admitted` → `published`).
Only one job runs at a time, so graph writes never interleave.

2. **Ingest.** Press **Add sources…** and drop text files or folders on the
   dialog, or choose files. Dropped folders are searched recursively and their
   directory structure is not retained. Each file is
   written into `sources/inbox/` and ingested through the ordinary pipeline.
   Ingestion is **data-only**: the starter's classes and relationships are
   frozen, so a dropped text can add individuals and statements but can never
   add, rename, or retype a class or a relationship. A record that names
   vocabulary the starter does not declare is refused, and the model is asked
   to repair its answer using the declared vocabulary.

   The same restriction on the command line is `--data-only`:

   ```bash
   text-to-ontology sources/inbox/ ontology.trig --data-only
   ```

   Without `--data-only` the older behaviour is unchanged: a new kind or a new
   predicate is declared as it is extracted. The studio always uses data-only.

3. **Edit the ingestion prompt.** **Prompts…** opens the prompt sent for every
   source window: pick a template (`extraction_user` is the main one,
   `extraction_system` is the system message, `starter` is the starter prompt),
   edit it, and press **Save prompt**. Placeholders stay in the text — the
   panel tells you which ones are required and which are allowed, refuses a
   template that would break a run, and shows advisory notes (a missing
   `entities` list, a missing `confidence`). **Preview** renders the template
   with sample values, and **Back to default** restores the tested wording.
   Saved edits live in `prompts.local.json` next to the dataset (git-ignored);
   the digest of the templates in force is recorded in every run's
   configuration, so a report always names the prompt that produced it.

4. **Talk to the graph.** The right-hand column is a chat and nothing else:
   your questions on the right, the graph's answers on the left, Enter sends
   (Shift+Enter for a new line), and while an answer is being prepared the
   graph's bubble shows what the backend is doing. Every question is answered from
   only the relevant part of the graph, and **you see that part**: after each
   answer the canvas switches to exactly the selected triples, with the matched
   resource focused, and the answer's footer says how many triples were selected
   and how many were left out for space. Each answer keeps a **Show the
   subgraph** link (and **With the full graph** if you would rather see it
   beside everything); while a subgraph is on the canvas, **Show the full graph
   again** sits above the question box and restores the dataset.
   The subgraph-size picker trades breadth for tokens: *compact* (2 500
   tokens) for a quick question, *normal* (6 000, the default) which fits a
   whole class listing, or *wide* (12 000) for a big comparison. Each answer
   says how many triples were selected **and how many reached the model**, so
   a partial answer is never a surprise. The "show the subgraph
   after each answer" checkbox turns the automatic part off, and **New
   conversation** forgets the thread.

   <sub>Chat controls, exactly as they read: Show the subgraph · With the
   full graph · Show the full graph again · show the subgraph after each
   answer · New conversation.</sub> A follow-up like "and Germany?" keeps the
   topic because the matched resources are carried over, and when something is
   not in the graph the answer says so and what would have to be added.

   The same conversation is available over the operations API
   (`chat.ask`, `chat.state`, `chat.reset`), so a script can talk to the graph
   without the page.

5. **Edit the graph.** **Edit the graph…** opens the data graph as Turtle
   (it loads on open; **Reload the graph** re-reads it). Change it —
   additions are ordinary statements, a line starting with `- ` removes one —
   then press **Preview changes** to see exactly what would change (additions,
   removals, and any warnings), and **Apply changes** to write precisely what
   you previewed. New classes and relations are refused unless you tick
   *allow new classes and relations*, which keeps the same data-only rule
   ingestion follows. Every applied edit is recorded in the provenance graph as
   one `prov:Activity` plus a statement record per triple.

   A chat answer that proposes a change comes back with the same preview
   attached: the answer's footer shows `proposed change: +N −M` with an **Apply
   this patch** link, and the model's invented identifiers are exactly what the
   checks catch before anything is written. Nothing a model writes is ever
   applied on its own.

   <sub>Controls read exactly: Reload the graph, Preview changes, Apply
   changes, Apply this patch, allow new classes and relations.</sub>

6. **Reset.** **Reset everything** in the top bar deletes the dataset file
   and every source in the inbox; **Clear view** next to it only unloads the
   dataset from the graph view and deletes nothing. Without the page:

   ```bash
   text-to-ontology-studio --reset
   ```

   Deleting `ontology.trig` by hand is the same thing; the next run starts a
   fresh dataset.

The studio serves `frontend/triple-lens.html`, the studio frontend beside it
(`frontend/studio.js`, `frontend/studio.css`), and one generic JSON path over a registry of named
operations, and binds to localhost only. `GET /api/op/operations.list` lists
everything a client may ask for; adding a capability is one small function in
`src/text_to_ontology/operations.py`, never a new route. The state and the two
long jobs live in `src/text_to_ontology/workspace.py`; the transport carries and
nothing else.
Opened straight from disk, the same page is exactly the standalone viewer: no
server, no studio, everything read in the browser.

## Frontend and backend

One rule: **the backend owns every fact and every decision; the frontend owns
pixels and input.** So the page never decides what matters in a graph, never
validates, never writes, and never calls a model — and the backend never emits
markup or cares which button exists.

| Concern | Side | File |
|---|---|---|
| dataset, inbox, long jobs, chat session, pending patches | backend | `src/text_to_ontology/workspace.py` |
| every capability, as one named operation + manifest | backend | `src/text_to_ontology/operations.py` |
| relevance, scope caps, what a model is shown | backend | `src/text_to_ontology/graph_scope.py` |
| prompts and their validation | backend | `src/text_to_ontology/prompts.py` |
| patch parse/check/preview/apply, provenance | backend | `src/text_to_ontology/graph_edit.py` |
| HTTP routes, page + assets | transport | `src/text_to_ontology/studio.py` |
| RDF parsing for display, layout, filters, details | frontend | `frontend/triple-lens.html` |
| top-bar actions, dialogs, the conversation, diff view | frontend | `frontend/studio.js`, `frontend/studio.css` |

The two boundaries:

1. **UI → backend**: **named operations** over `GET`/`POST /api/op/<name>`.
   `GET /api/op/operations.list` lists every capability, each answer is one JSON
   record, and a failure answers `{ok: false, error}` so the page can show it.
2. **backend → UI**: a **view directive** —
   `{replace, files, mode, focus, filters, hideIsolated, clearFilters,
   resetFilters}` — applied by `window.__lens.applyView`. The backend says
   *what* to show; the lens decides how to draw it.

Adding a capability is one function plus one `Operation(...)` line in
`operations.py`, and a button in the studio frontend. `studio.py` does not change, and if
the capability should change the picture it just returns a view directive.
`docs/current_architecture.md` §1.1 is the detailed version of this map.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

`pyproject.toml` is the single dependency declaration (`rdflib` and `pyshacl`
are the runtime dependencies); there is no `requirements.txt`. Python 3.12+ is
required.
The tests need the same editable install:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Configure OpenRouter

Create a `.env` file in the directory you run the program from:

```text
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL=qwen/qwen3.5-35b-a3b:nitro
```

`OPENROUTER_MODEL` is optional; its default is the speed-optimized Qwen model
`qwen/qwen3.5-35b-a3b:nitro`. It keeps requests within the Qwen model family
while selecting the fastest available provider. You can also use exported shell
variables:

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="qwen/qwen3.5-35b-a3b:nitro"
```

Requests cap model output at 4,096 tokens so OpenRouter does not reserve the
model's much larger default response allowance when checking available credits.

## Use

After installing, use one of three equivalent commands (the console script,
the module entry point, or the legacy root wrapper):

```bash
text-to-ontology notes.txt ontology.trig
python3 -m text_to_ontology notes.txt ontology.trig
python ontology.py notes.txt ontology.trig
```

Add another file to that same graph:

```bash
text-to-ontology more_notes.md ontology.trig
```

Or recursively read all supported text-like files in a directory:

```bash
text-to-ontology documents/ ontology.trig
```

If the second argument is omitted, the output is `ontology.trig`:

```bash
text-to-ontology documents/
```

Save a detailed report as a timestamped Markdown file under `reports/runs/`:

```bash
text-to-ontology documents/ ontology.trig --report
```

`--report` writes to the file only, so a successful run stays silent in the
terminal. The report includes the exact system and user messages sent to the
extraction LLM. Generated reports are ignored by Git because
they may be large and may contain source-derived information.

Preview the exact plan and both SHACL results without writing final graphs:

```bash
text-to-ontology documents/ ontology.trig --dry-run
```

Passing a `.ttl` output path keeps the explicit legacy single-Turtle
compatibility mode. New datasets should use `.trig`, which preserves target,
provenance, review, schema, and shape graph roles.

## Call it from Python

The public API is one function. The CLI is a thin adapter over it:

```python
from pathlib import Path

from text_to_ontology.api import RunRequest, run_text_to_graph
from text_to_ontology.llm import OpenRouterExtractor
from text_to_ontology.run_report import RunReporter

result = run_text_to_graph(
    RunRequest(source=Path("notes.txt"), graph_path=Path("ontology.trig")),
    extractor=OpenRouterExtractor(),
    reporter=RunReporter(verbose=False),
)
print(result.triples, "triples in", result.graph_path)
```

`RunRequest` carries the source, the graph path, and the configuration:
`WindowingConfig` (window target/overlap size in tokens), `ContextConfig`,
`ExtractionConfig`, `MergeConfig`, `ValidationConfig` (optional explicit SHACL
shape graphs), `GraphNames`, `ProcessingConfig`, and `dry_run`
(`retain_staging_on_failure` exports a failed document's staging graphs to a
sidecar TriG file next to the output graph for diagnosis; by default they are
discarded; `require_declared_vocabulary` turns ingestion data-only, so the
classes and relationships already declared are the only ones the model may
use).
When the model's answer is messy — unparseable JSON or a contract violation —
it is sent back to the model for self-repair up to
`ExtractionConfig(repair_attempts=...)` times (default 2; 0 disables repair)
before the window is rejected. Every answer, repaired or not, must pass the
same validation gate.
On success, `RunResult.documents` contains each document's reconciliation
report, source and proposed-data SHACL reports, exact publication plan, and
deterministic canonical N-Triples source
artifact. Its metadata associates the export with the document digest,
window-strategy version, candidate-mapping version, and extractor identities.
SHACL non-conformance raises `SourceValidationError`; the source artifact,
reconciliation report, and standard SHACL report remain available on that
exception while the final graphs stay unchanged. `PublicationValidationError`
does the same for a proposed post-merge SHACL failure.
Any adapter can be replaced — pass an object with `model()` and
`extract(prompt)` as the extractor (a fake in tests), or a named graph store
with `get(...)` and `publish(...)`. The core pipeline
never parses arguments, reads environment variables, or exits the process.

## Look at the graph

The viewer derives five read-only views of an existing graph and explains each
one: the schema / instance / support partitions, the declared skeleton copied
out of the schema, and the usage patterns observed in the instance data.

```bash
python view_ontology.py ontology.trig              # union of named graphs
python view_ontology.py ontology.trig -g GRAPH_IRI # one named graph
python view_ontology.py other.ttl                  # legacy Turtle still works
python view_ontology.py -html                      # write ontology_views.html
python view_ontology.py ontology.trig -html out.html
```

The HTML page is one standalone file with no external assets. Besides the same
numbers the terminal prints, it walks through how each view is derived, browses
every statement, every declared class and property, every observed pattern,
every entity, and the whole provenance trail, and ends with a glossary. Its
search boxes, filters, and sliders only change what is displayed — what a view
contains is decided in the code before the page is generated, and there are no
filter options on the command line for the same reason.

For each document the run prints one line about its staging graph and windows,
for example `Document doc-13ed72f8: 6 window(s); staging graph ...`, plus one
`Window k/n admitted ...` line per window showing how the source graph grew.
After the last window it prints `Reconciled source:` and `SHACL source
validation:` lines before any final merge plan is built.
The numbers behind the prompt budget live in `PROMPT_BUDGET` in
`prompt_budget.py`; `context_tokens` is the ceiling
on how much ontology context one prompt may carry, and lowering it makes the
prompt smaller by dropping the least relevant items first.

Each non-empty window's answer is validated before it may change anything. The
run prints a `Validated:` line for each window, then one document-level
`Planned:` line and a proposed-data SHACL result before anything final is
written. Every record the model returns must carry a
`confidence` from 0.0 to 1.0 — the model's confidence that the source text
directly supports that complete record. New assertions below `0.80` confidence
are not merged; they are retained as review records instead. Exact duplicates
of existing statements are kept as corroboration evidence, not re-added, and
disagreements with explicit functional constraints go to review rather than
overwriting anything: existing canonical statements are never replaced
automatically.

Every valid extraction leaves independent standard PROV/DQV evidence in the
provenance graph. Duplicate canonical assertions are not re-added, but each
source/window confidence measurement remains separate. Withheld candidates are
represented in the review graph. A validation or publication error leaves all
final graphs unchanged. Each successful non-empty source document makes exactly
one atomic publication call.

The provenance graph also contains direct source links:

- Documents are `prov:Entity` resources identified by content, with filenames
  in `rdfs:label` and `onto:sourceFile` links to file records.
- File records carry `rdfs:label` (filename) and `onto:sourcePath` (the input
  path as supplied/discovered). Identical content in different files shares a
  document but retains separate file records; changed content creates a new
  document and file-version record.
- Each published statement has a stable `onto:statement/<hash>` resource,
  typed `rdf:Statement` and `prov:Entity`, with `rdf:subject`, `rdf:predicate`,
  and `rdf:object`. Its `prov:wasDerivedFrom` and `onto:sourceFile` values
  accumulate supporting documents and files across runs.
- Domain instances, classes, and properties carry `onto:sourceDocument` and
  `onto:sourceFile` summaries. These custom properties mean that information
  about the resource was supported by the linked source; they do not mean
  that every assertion about it came from every listed file.

Only accepted statements and corroborating duplicates contribute to these
published summaries. Extraction and review statement records retain their own
direct source links, including for withheld claims. Application-supplied root
class declarations are excluded from document-source summaries. All source
metadata stays in the provenance/review graphs in the same TriG file, and is
classified as support metadata by the viewer. Existing datasets gain these
links as documents are processed; old files are not automatically backfilled.

## Files

All importable code lives in the `text_to_ontology` package under `src/`.
The root scripts `ontology.py` and `view_ontology.py` are thin compatibility
wrappers that call the packaged modules, so both old workflows keep working.

The pipeline that runs when you invoke the program:

- `src/text_to_ontology/api.py` — the documented public API and its exports
- `src/text_to_ontology/pipeline.py` — the run loop, the request/result
  dataclasses, and the extractor/reporter contracts
- `src/text_to_ontology/cli.py` — the command line: argument parsing, adapters,
  exit codes (also reachable as `python3 -m text_to_ontology`)
- `src/text_to_ontology/prompts.py` — every model prompt as a named, validated,
  editable template (defaults in code, overrides in `prompts.local.json`)
- `src/text_to_ontology/graph_scope.py` — the relevant subgraph for one
  question, as TriG, as a view directive, and as text for a model
- `src/text_to_ontology/graph_chat.py` — one conversation about the graph; each
  answer keeps the subgraph it was written from
- `src/text_to_ontology/graph_edit.py` — patches (additions plus `- ` removals):
  parse, check, preview, apply by id, with PROV evidence
- `src/text_to_ontology/vocabulary.py` — the starter vocabulary read back out
  of a graph: which classes, relations, and facts ingestion may use, and which
  IRI each name means (so an imported ontology keeps its own)
- `src/text_to_ontology/starter.py` — the starter ontology: one prompt, one
  checked proposal, one atomic write (`text-to-ontology-starter`)
- `src/text_to_ontology/workspace.py` — the application state for one dataset:
  the store, the inbox, the extractor, the progress slot, and the two long jobs
- `src/text_to_ontology/operations.py` — every capability as one named
  operation in one registry, with no HTTP in it
- `src/text_to_ontology/studio.py` — the local HTTP transport: the lens page,
  its panel, and `/api/op/<name>` (`text-to-ontology-studio`)
- `src/text_to_ontology/run_report.py` — normal and verbose run reporting to
  the terminal, a file, or any supplied text stream
- `src/text_to_ontology/ingest_sources.py` — finding and reading source files
- `src/text_to_ontology/source_parse.py` — building the prompt and parsing the
  LLM's answer
- `src/text_to_ontology/candidate_validation.py` — validating and normalizing a
  response before merge
- `src/text_to_ontology/merge_policy.py` — read-only merge planning: identity
  decisions, acceptance, corroboration, conflict review, and provenance
- `src/text_to_ontology/entity_lookup.py` — deciding whether an entity is
  already in the graph
- `src/text_to_ontology/candidate_graph.py` — turning one validated response
  into an inspectable RDF candidate graph with PROV-O/DQV confidence
- `src/text_to_ontology/source_staging.py` — one provisional source graph per
  document: stable staging-graph names, source-local admission planning, the
  marked layered prompt context, and diagnostic retention on failure
- `src/text_to_ontology/source_reconciliation.py` — the complete-document
  report, overlap support accounting, and deterministic source artifacts
- `src/text_to_ontology/source_validation.py` — explicit shape-graph combining
  and the pySHACL gate with its standard validation report
- `src/text_to_ontology/document_merge.py` — one complete-document candidate
  package and one canonical identity/merge planning pass
- `src/text_to_ontology/document_publication.py` — proposed-data validation,
  PROV/DQV remapping, review material, dry-run plan, and atomic publication
- `src/text_to_ontology/publication_sources.py` — document/file metadata and
  source summaries for published statements, instances, classes, and predicates
- `src/text_to_ontology/windowing.py` — stable documents and reproducible
  overlapping text windows
- `src/text_to_ontology/graph_merge.py` — materializing a completed plan (and
  the legacy direct merger) into the graph
- `src/text_to_ontology/graph_management.py` — opening, seeding, naming, and
  atomically saving the graph
- `src/text_to_ontology/llm.py` — the tiny OpenRouter client

Choosing what the LLM gets to see. All read-only: none of these writes to the
graph, and each one can be read, tested, or replaced on its own:

- `src/text_to_ontology/source_concepts.py` — what one text mentions, before
  any ontology is opened. Deliberately simple for now, and free of RDF so it
  can later be replaced by NLP, NER, embeddings, or a small model without
  changing anything else
- `src/text_to_ontology/task_context.py` — align the text with the graph and
  select the relevant classes, properties, observed usage, resources, and
  example assertions
- `src/text_to_ontology/context_render.py` — turn that selection into compact
  lines an LLM can read, keeping declared structure and observed usage visibly
  apart
- `src/text_to_ontology/prompt_budget.py` — estimate tokens and keep only the
  complete items that fit. The token counter is swappable for a real tokenizer
  later

Read-only tools that derive smaller views of an existing graph:

- `src/text_to_ontology/graph_partition.py` — split a graph into schema,
  instance, and support views
- `src/text_to_ontology/graph_skeleton.py` — copy the explicit class and
  property core out of a schema view
- `src/text_to_ontology/graph_patterns.py` — report which
  class-property-range patterns the instance data actually contains, with
  evidence
- `src/text_to_ontology/ontology_views.py` — hand back all of the above as one
  group of views
- `src/text_to_ontology/view_ontology.py` — the viewer's command line: print
  those views, or write them as an explained HTML page
- `src/text_to_ontology/view_report.py` — turn the views into plain data, with
  no HTML anywhere in it
- `src/text_to_ontology/view_html.py` — render that data as one self-contained
  page, explanations included

And the rest:

- `pyproject.toml` — package metadata and the two dependencies (`rdflib`,
  `pyshacl`)
- `frontend/triple-lens.html` — the one self-contained viewer page (it also
  exposes the `window.__lens` view API the studio draws through)
- `frontend/studio.js` / `frontend/studio.css` — the studio frontend (top-bar
  actions, dialogs, the conversation), loaded only when the page is served;
  controls and view directives, no domain logic
- `scripts/install_smoke.sh` — the wheel-into-a-clean-venv smoke test
- `sources/inbox/` — where the studio keeps the files you drop (git-ignored)
- `tests/fixtures/miniature_repository.ttl` — the frozen miniature graph the
  exact partition/skeleton/pattern tests run against
- `ontology.trig` — the named-graph dataset created by the default run

The accepted directory file extensions are listed near the top of
`ingest_sources.py`. A directly supplied file is always read, regardless of
extension.

## Read more
TTL Graph Generalization techniques
What about wiki?
