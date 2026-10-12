# Current Architecture — text_to_ontology

> Machine-readable architecture map. Reconstructed **from source code only** (no docs consulted).
> Target audience: another AI/LLM agent that must navigate, modify, or extend this codebase.
> All facts below are taken directly from the files; function signatures are quoted verbatim.
> Last verified claim by claim against the code on 2026-10-12 (branch `trace-prefixes`, commit `4417f54`).

## Current pipeline (post-M7, windowed document publication)

The executable is the packaged CLI (five console scripts, §10); the root
scripts `ontology.py` and `view_ontology.py` are thin compatibility wrappers that add `src/` to
`sys.path` and delegate to `text_to_ontology.cli:main` and
`text_to_ontology.view_ontology:main`.

One source file is one *document* with a content-derived ID
(`doc-<sha256 of normalized text, 16 hex>`). A long document is split into
reproducible overlapping text windows; a short one stays a single whole-text
window. The pipeline is fully document-scoped:

1. **Windowing** (`windowing.py`) — splits the document into windows and
   packs them, preferring block/sentence boundaries, with overlap.
2. **Source staging** (`source_staging.py`) — one provisional *source staging
   graph* per document plus one *candidate graph per window*, held in a
   throwaway `RdflibGraphStore`. Nothing canonical may change while a
   document's windows are processed (a triple-level snapshot is verified after
   every window).
3. **Per-window extraction** (`pipeline._extract_window`) — context is
   selected from the *seed view* of the final ontology (`seed_view.py`: the
   schema plus declared statements and names) *and* from the staging graph
   (marked `(this document)`), the prompt goes to the LLM, a messy answer is
   sent back for bounded self-repair (`repair.py`), and the answer must pass
   `candidate_validation` every time. In data-only mode every window also
   carries the fixed blocks of §4.21 (document header, core schema, document
   anchors, same-folder entities), and records that only break a declared
   domain/range are dropped after repair instead of failing the window.
4. **Window admission** (`pipeline._admit_window`) — the validated package is
   planned against the source staging graph only (provisional IRIs, never
   canonical identities) and admitted into the staging graph; the candidate RDF
   is kept alongside as evidence.
   After the last window, data-only runs ask once per missing *expected
   link* (`link_check.py`, §4.24); an accepted answer is admitted like one
   more window.
5. **Reconciliation** (`source_reconciliation.py`) — one plain report for the
   complete source graph: local entities, aliases, overlap duplicates with
   their independent PROV/DQV supports, unresolved identities, conflicts.
6. **Source validation** (`source_validation.py`) — pySHACL over the complete
   source graph with combined configured shapes. Non-conformance raises
   `SourceValidationError`; the final ontology is untouched.
7. **Document merge** (`document_merge.py`) — window packages are collapsed
   into one deduplicated document package and canonical identity is decided
   **once** against the full configured canonical scope (schema + data
   graphs), via the same read-only `plan_graph_merge` policy.
8. **Publication** (`document_publication.py`) — the accepted triples and
   their `src:` source links (which file said what) go to the data graph, the
   document record goes to the provenance graph (the full per-window PROV/DQV
   candidate evidence too, but only with `--trace`), the proposed post-merge
   data is SHACL-validated, and target / provenance / review graphs are
   replaced in **one atomic** `store.publish(Publication(...))` call.
   `dry_run` returns the same plan without the call.

The default store is `RdflibGraphStore` persisted as TriG; graph roles come
from `GraphNames`. A `.ttl` output path explicitly selects
`LegacyTurtleDatasetStore`, which runs the same named-graph orchestration and
atomically exports the role union for compatibility.

Two sides, one rule: **the backend owns every fact and every decision; the
frontend owns pixels and input.** Concretely that means the page never decides
what is relevant, never validates, never writes, and never calls a model - it
draws what it is given and applies declarative view directives. §1.1 is the
authoritative map of that boundary.

Around that pipeline sit two entry paths:

- `text_to_ontology.starter` turns a short pasted description into a starter
  ontology (classes, relations, facts) and writes it in one atomic
  publication. It is a *separate* step from ingestion: nothing is extracted
  from a real source document while it runs.
- `text_to_ontology.studio` serves `frontend/triple-lens.html`, the studio
  frontend beside it (`studio.js` / `studio.css`), and a generic HTTP transport over the named
  operations in `operations.py`. The state and the jobs live in
  `workspace.Workspace`; the transport carries and nothing more. The page
  works unchanged without the server.

Data-only mode (`MergeConfig(require_declared_vocabulary=True)`, CLI
`--data-only`) is the lock that keeps the starter fixed: `vocabulary` reads the
declared classes/relations/facts once per run, the validation gate rejects
anything else (including relations/facts between the wrong classes), and
merge planning adds no declaration of its own.

Two read-only tools sit beside the pipeline: `text-to-ontology-health`
(`graph_health.py`, connectivity numbers) and `text-to-ontology-expect`
(`link_check.py`, declare the expected links the link check looks for).

---

## 1. Purpose

Reads text files (or a directory of text-like files), asks an LLM to extract
**entities**, **relations**, and literal **facts**, and publishes them into a
named-graph RDF dataset (`ontology.trig` by default: schema, shapes, target
data, provenance, and review graphs). Re-running against the same dataset adds
knowledge; identity resolution runs document-scoped and prevents duplicates.

The codebase has four layers:

1. **Write pipeline** — package modules that build and publish the dataset.
2. **Context selection layer** — modules that pick, render, and budget the part
   of the graph one source text needs, and put that into the extraction prompt.
   Nothing in this layer writes to the graph.
3. **Read-only derivation layer** — modules that generalize an existing graph
   (`graph_partition`, `graph_skeleton`, `graph_patterns`, plus the
   `ontology_views` façade) used by the context layer and the viewer.
4. **Viewer** — `view_ontology` / `view_report` / `view_html` render the same
   read-only views to the terminal or one self-contained HTML page (§4.36).

Two optional front doors sit in front of that: the **starter**
(`starter.py`: describe the world once, get the classes and relationships) and
the **studio** (`studio.py`: the same page plus create/ingest/reset, which is
the data-only path).

The prompt no longer carries the whole entity catalog or every property label.
It carries a layered selection (canonical + `(this document)` source-local)
capped by a token ceiling (§10); in data-only mode the whole core schema goes
first instead of the word-matched schema (§4.22).

### 1.1 Frontend and backend: who owns what

| Concern | Side | Where |
|---|---|---|
| dataset, source inbox, jobs, chat session, pending patches | backend | `workspace.py` |
| capability names + the published manifest | backend | `operations.py` |
| relevance (what a question is about), scope caps, model rendering | backend | `graph_scope.py`, `task_context.py` |
| prompts, their validation and overrides | backend | `prompts.py` |
| extraction, validation, merge policy, publication, provenance | backend | `pipeline.py` and the modules around it |
| patch parsing/checking/preview/apply | backend | `graph_edit.py` |
| HTTP routes, the page and its assets | transport (backend) | `studio.py` |
| parsing RDF **for display**, layout, filters, focus, details panel | frontend | `frontend/triple-lens.html` |
| top-bar actions, dialogs, the conversation, diff display, view directives applied | frontend | `frontend/studio.js`, `frontend/studio.css` |

**Only two boundaries exist.**

1. *Frontend → backend*: named operations over `GET`/`POST /api/op/<name>`.
   `GET /api/op/operations.list` is the manifest; every answer is one plain JSON
   record; an unknown name is the only 404; a failed operation answers
   `{ok: false, error}` so a page can show the message instead of breaking.
2. *Backend → frontend*: a declarative **view directive**
   `{replace, files: [{name, trig}], mode, focus, filters, hideIsolated,
   clearFilters, resetFilters}`, applied by `window.__lens.applyView` (§4.35).

**What each side must never do.**

- The frontend never calls a model, never reads a file or the dataset path on
  its own, never writes to the graph, never re-implements a rule (no SHACL, no
  vocabulary check, no diffing), and never decides which part of the graph
  matters. It may mislead the picture; it cannot corrupt the data.
- The backend never emits markup, never knows a control's id, and never decides
  how something is drawn beyond the view directive.
- The transport carries and nothing else: no state beyond the binding, no
  domain logic, no knowledge of what an operation means.

**Adding a capability** is three steps, and only the last one is frontend:

1. one small `def _thing(workspace, payload)` in `operations.py`;
2. one `Operation("thing.do", "what it is for", _thing, args=(...))` line;
3. a button in `frontend/studio.js` that calls `op.thingDo(...)`.

`studio.py` does not change. If the new capability should change the picture, it
returns a view directive and the studio frontend passes it to `applyView`.

**Changing what is shown** is one step: return a directive. The lens resolves
IRIs to nodes and filter keys to its internal sets itself, so the backend never
needs to know how the view is built.

---

## 2. Repository layout

Tracked files (`git ls-files`), grouped:

```
text_to_ontology_2/
├── pyproject.toml              # package metadata, deps (rdflib, pyshacl), 5 console scripts
├── uv.lock                     # locked dependency versions
├── README.md / AGENTS.md       # user guide / agent rules
├── ontology.py                 # compatibility wrapper → text_to_ontology.cli:main
├── view_ontology.py            # compatibility wrapper → text_to_ontology.view_ontology:main
├── ttl_to_trig.py              # plain RDF file → studio dataset (named graphs), §4.37
├── migrate_prefixes.py         # old dataset → the src:/trace: prefix layout, §4.37
├── trig_to_ttl.py              # export the target data graph of .trig files as .ttl, §4.37
├── ontology.trig               # default named-graph dataset (data, not code; §12)
├── ontology_bckp.trig          # a hand-kept older dataset copy (data)
├── seed_ontology.trig          # a starter schema (+ shapes) ready to copy in as a dataset
├── ecmp_seed.ttl               # a plain-Turtle example vocabulary for the RDF import path
├── backups/                    # dated dataset snapshots (.trig), data only
├── eval/gold.example.json      # fictional gold links for `text-to-ontology-health --gold`
├── reports/README.md           # what --report writes; reports/runs/ is git-ignored
├── frontend/triple-lens.html   # the viewer page (+ the view API; no studio code)
├── frontend/studio.js          # the studio frontend (loaded only when served)
├── frontend/studio.css         # its styles
├── scripts/install_smoke.sh    # wheel-into-a-clean-venv smoke test
├── docs/                       # this map, app_map.html, data_flow.html,
│                               # ingestion_connectivity_plan.md, backlog/, old/
├── task.md, teaching_material.html, opencode.json, .opencode/   # notes and tool config
├── src/text_to_ontology/       # the importable package (49 .py files)
└── tests/                      # unittest
    ├── store_contract.py       # shared GraphStore contract test base
    ├── connectivity_fixtures.py  # a small fictional starter (Project/Client/Technology)
    ├── fixtures/
    │   ├── miniature_repository.ttl   # frozen graph for partition/skeleton/pattern pins
    │   ├── documents/                 # windowing fixtures (crlf, long, unicode, …)
    │   └── shacl/                     # SHACL shape fixtures for source validation
    └── test_*.py               # 50 test modules (§13)
```

Not tracked but used at run time: `sources/inbox/` (the studio drop zone,
git-ignored with everything under `sources/`), `prompts.local.json` (prompt
overrides beside the dataset), `eval/*.local.json` (real gold links),
`reports/runs/*.md`, and `.env`.

Package modules (all in `src/text_to_ontology/`), by the section that
describes them: `__init__` / `__main__` / `cli` / `api` / `pipeline` (§3);
write pipeline §4.1–4.20; connectivity overview §4.21 and `schema_context`,
`document_context`, `link_check`, `seed_view`, `graph_health` §4.22–4.26;
`starter`, `prompts`, `graph_scope`, `graph_chat`, `graph_edit`,
`workspace`, `operations`, `studio`, and the frontend §4.27–4.35; the viewer
`view_ontology` / `view_report` / `view_html` §4.36; root scripts §4.37;
read-only derivation and context layers (`graph_partition`,
`graph_skeleton`, `graph_patterns`, `ontology_views`, `source_concepts`,
`task_context`, `context_render`, `prompt_budget`) §5.

Dependency: `rdflib>=7,<8` and `pyshacl>=0.30,<1` (pyproject.toml), Python 3.12+.

---

## 3. Entry point — `cli.py` → `api.py` → `pipeline.py`

### 3.1 `cli.py`

```
DEFAULT_GRAPH = Path("ontology.trig")
def build_parser():   # argparse; source (required), graph (optional, default DEFAULT_GRAPH),
                      # -v/--verbose, --report, --dry-run, --data-only, --no-link-check,
                      # --trace
def main(argv=None):  # builds adapters, calls run_text_to_graph; on RuntimeError/OSError:
                      # reporter.failed(error), "Error: ..." to stderr, SystemExit(1)
```

- If `args.graph.suffix.lower() == ".ttl"`,
  a `LocalTurtleStore` compatibility store is passed; otherwise `None` selects
  the default `RdflibGraphStore`.
- `--report`: reporter is verbose and writes to a timestamped Markdown file
  under `reports/runs/`; a successful run stays silent on the terminal.
- `-v/--verbose`: the same reporter writes everything to the terminal.
- `--data-only`: `MergeConfig(require_declared_vocabulary=True)`; ingestion may
  only use the vocabulary the starter ontology declares. `text_to_ontology.studio`
  always runs this way.
- `--no-link-check`: `ExtractionConfig(link_check=False)`; no expected-link
  questions after each document (§4.24).
- `--trace`: `ProcessingConfig(trace=True)`; also keep every window's model
  answer as candidate evidence (`trace:candidate/...`, PROV/DQV) in the
  provenance graph. Off by default; the studio never sets it (§7.1).
- `python -m text_to_ontology` runs the same `main` (`__main__.py`);
  `__init__.py` only holds `__version__ = "0.2.0"`.

### 3.2 `api.py`

One documented public function plus re-exported types; no logic of its own.

```
run_text_to_graph(request, graph_store=None, extractor=None, reporter=None) → RunResult
```

`__all__` (22 names): the configs `ContextConfig`, `ExtractionConfig`,
`MergeConfig`, `ProcessingConfig`, `ValidationConfig`, `WindowingConfig`;
`RunRequest`, `RunResult`, `DocumentResult`, `DocumentPublicationPlan`,
`SourceGraphArtifact`, `SourceValidationResult`; the errors
`PublicationValidationError`, `SourceValidationError`; the adapters and
stores `Extractor`, `Reporter`, `OpenRouterExtractor`, `GraphStore`,
`GraphNames`, `LocalTurtleStore`, `RdflibGraphStore`; and
`run_text_to_graph`. The module docstring holds a runnable minimal example.

The CLI is a thin adapter over it. The core pipeline never parses arguments,
reads environment variables, or exits the process.

### 3.3 `pipeline.py` — the run loop

Request dataclasses (all in `pipeline.py`):

- `WindowingConfig` — `target_tokens=800`, `overlap_tokens=100`,
  `strategy_version=2`, `count_tokens=estimate_tokens`.
- `ContextConfig` — `budget=dict(PROMPT_BUDGET)`.
- `ExtractionConfig` — `model=None`, `repair_attempts=2`, `link_check=True`,
  `max_link_checks=MAX_LINK_CHECKS` (5).
- `MergeConfig` — `min_auto_accept_confidence=0.80`,
  `require_declared_vocabulary=False`. With `require_declared_vocabulary`
  (data-only ingestion) the run reads the starter vocabulary once
  (`vocabulary.read_vocabulary`) and passes it to every window's validation
  gate and to the document planner; classes and relationships the starter does
  not declare are validation errors, and no plan may declare a class or a
  property.
- `ProcessingConfig` — how much a run keeps for diagnosis:
  `retain_staging_on_failure=False`, `trace=False` (with `trace`, the
  per-window candidate evidence is written to the provenance graph; CLI
  `--trace`; studio/workspace runs keep the default, off).
- `ValidationConfig` — `shape_graphs=()` (explicit SHACL graphs; empty keeps
  role shapes / legacy embedded shapes).
- `RunRequest` — `source`, `graph_path=Path("ontology.trig")`,
  `source_root=None` (the root that the prompt header's `Path:` is relative
  to; default: the source directory, or a single file's folder), the six
  configs, `graph_names=GraphNames()`, `prompts=None` (a
  `prompts.PromptLibrary`; None means the tested defaults), `dry_run=False`.

Result dataclasses:

- `DocumentResult` — `path`, `document_id`, `source_artifact`,
  `reconciliation_report`, `source_validation`, `publication_plan=None`,
  `publication_validation=None`, `link_check=None` (the link-check summary
  `{gaps, filled, not_established, dropped}`).
- `RunResult` — `graph_path`, `triples`, `files_total`, `files_saved`,
  `files_blank`, `windows_processed`, `documents`, `dry_run`.

Adapters (Protocols, replaceable): `Extractor` (`model()`, `extract(prompt)`),
`Reporter` (one method per checkpoint, including `link_check(summary)`; see
`run_report.RunReporter`). The pipeline also calls `reporter.line(...)`
(oversized core schema), which the Protocol does not declare.
`budget_for(text, budget, fixed_extra_tokens=0)` fills in `source_tokens` and
adds the fixed blocks' cost to `fixed_prompt_tokens`. The
concrete extractor is `llm.OpenRouterExtractor`; a fake is used in tests. Check
the store boundaries in `graph_store.GraphStore` / `graph_management.GraphStore`.

`run_text_to_graph` control flow:

```
system_prompt = prompts.render("extraction_system", library=request.prompts)
extractor = extractor or OpenRouterExtractor(model=request.extraction.model, system_prompt=system_prompt)
reporter  = reporter or RunReporter()
names.validate()
store     = _final_store(graph_store, request)      # RdflibGraphStore or LegacyTurtleDatasetStore
require_named_graphs(store, request.graph_path)      # PlainRdfError for a plain RDF file saved as .trig
roles     = initial_role_graphs(store, names)        # read schema/shapes/data/provenance/review; seed if empty
graph     = union_graphs(roles.values())
context   = seed_view(roles, names)                  # what every prompt may see (§4.25)
vocabulary = read_vocabulary(context) if request.merge.require_declared_vocabulary else None
schema_sha256 = schema_digest(schema role graphs)
if vocabulary:                                       # data-only
    core_schema = render_core_schema(context)        # None + reporter.line(...) when over schema_tokens
    expected = expected_links(union of shape role graphs)
files     = find_text_files(request.source, request.graph_path)
if not files: raise RuntimeError("No text-like files found")
for index, path in enumerate(files, start=1):
    raw_text = read_source(path)
    if not raw_text.strip(): reporter.blank_source(); blank_files += 1; continue
    document = make_source_document(path.name, raw_text, source_path=path.as_posix())
    before_snapshot = final_graphs_snapshot(graph)
    staged = _process_document(document, request, context, extractor, reporter, vocabulary,
                               path=path, core_schema=core_schema, expected=expected,
                               sources=canonical_graph(roles, names))  # data graph with src: links
    reconciliation = reconcile_document(document.document_id, staged.source_graph,
                                        staged.candidate_graphs, staged.admission_plans)
    artifact = build_source_artifact(document, staged.source_graph, request.windowing, models)
    validation = validate_source_graph(staged.source_graph, _source_shape_graphs(...))
    if not validation.conforms: raise SourceValidationError(validation, artifact, reconciliation, sidecar)
    if final_graphs_snapshot(graph) != before_snapshot: raise RuntimeError("...during source reconciliation")
    document_merge = plan_document_merge(canonical_graph(roles, names), document,
                                         staged.packages, staged.admission_plans, conf,
                                         planner=plan_graph_merge, vocabulary=vocabulary,
                                         configuration={extraction_system_sha256,
                                                        extraction_user_sha256, schema_sha256})
    publication_plan = compile_document_publication(document, document_merge, staged.candidate_graphs,
                                                    staged.packages, staged.admission_plans, roles, names, shapes,
                                                    trace=request.processing.trace)
    if not publication_plan.proposed_validation.conforms: raise PublicationValidationError(publication_plan)
    if request.dry_run: reporter.dry_run(...)
    else: publish_document(store, publication_plan); reporter.saved(...)
    roles.update(publication_plan.publication.graphs); graph = union_graphs(roles.values())
    context = seed_view(roles, names)
return RunResult(...)
```

`_process_document(document, request, final_graph, extractor, reporter,
vocabulary=None, path=None, core_schema=None, expected=(), sources=None)`
— `final_graph` here is the seed view; `sources` (the data graph with its
`src:` links) is read only to find what other files of the same folder
contributed, so ingestion never reads the provenance graph:

```
windows = plan_windows(document, request.windowing)
fixed = _fixed_context(..., sources)        # _FixedContext(vocabulary, core_schema, display_path,
                                            #   window_total, folder_text, folder_ids); None outside data-only
staging = RdflibGraphStore()
staging.put(staging_name, Graph())          # source_staging_graph_name(document_id)
source_graph = staging.get(staging_name)
snapshot = final_graphs_snapshot(final_graph)
for number, window in enumerate(windows, start=1):
    reporter.window_started(...)
    model, candidates = _extract_window(window, ..., vocabulary, document, fixed)  # context → LLM → repair → validate
    source_graph, counts, plan = _admit_window(window, candidates, ...)
    if final_graphs_snapshot(final_graph) != snapshot: raise RuntimeError(...)
    staging.put(staging_name, source_graph); reporter.window_admitted(...)
    packages.append((window, model, candidates)); admission_plans.append({window_id, plan})
if fixed and expected and request.extraction.link_check:
    link_packages, link_summary = check_document_links(...)       # §4.24
    for window, candidates in link_packages: _admit_window(...); packages/admission_plans.append(...)
    reporter.link_check(link_summary)
on BaseException: if retain_staging_on_failure → retain_staging(...) sidecar; reporter.staging_failed; raise
```

`_extract_window(..., vocabulary=None, document=None, fixed=None)`: builds the
fixed blocks (`_fixed_blocks`: document header, core schema, document anchors,
same-folder block; empty outside data-only), adds their estimated size to
`fixed_prompt_tokens` via `budget_for`, then `_window_context` (canonical +
source-local selection → `layered_context_text`, blocks placed first, the
word-matched `declared` section dropped when a core schema is shown,
same-folder ids added to `existing_ids`) → `make_prompt` →
`extract_validated(extractor, prompt, validator, max_repair_attempts=...)`.
If the answer is still invalid after repair, it parsed, and a vocabulary is
set, `drop_endpoint_mismatches` removes only the domain/range-mismatched
records and the rest is re-validated (`validation["dropped"]`). Any other
failure is `RuntimeError(outcome.raw_problem or format_validation_failure(...))`.

`_admit_window`: `build_provenance(Path(document.name), window.text, model)`
+ `window_id` ∈ provenance → `plan_window_admission(source_graph, candidates,
provenance, document_id, min_new_confidence)` (read-only, provisional
allocator) → `build_candidate_graph(...)` → `staging.put(window_candidate_graph_name(...))`
→ `apply_merge_plan(source_graph, plan)` → updated staging graph.

`_final_store`: store with `get`/`graph_names`/`publish` is used directly;
`None` → `RdflibGraphStore(path=...)`; a legacy store (`LocalTurtleStore`)
is wrapped in `LegacyTurtleDatasetStore(store, path, names, save_graph)`.

---

## 4. Module reference (write pipeline)

### 4.1 `graph_management.py` — legacy Turtle lifecycle + namespaces

Named-graph *dataset* roles live in `graph_store.py`; this module keeps the
compatibility single-Turtle path (used by `save_graph` in the `.ttl` adapter,
by the viewer for Turtle files, and by `open_graph`/`LocalTurtleStore`).

Namespaces (constants): `BASE = "http://example.org/text-ontology/"`;
business data `ONTO`, `ENTITY` (`entity/`), `CLASS` (`class/`), `RELATION`
(`relation/`), `FACT` (`fact/`); source attribution `SRC` (`source/`, prefix
`src:`); tracing `TRACE` (`trace/`, prefix `trace:`); and `DQV`
(`http://www.w3.org/ns/dqv#`, not bundled with rdflib). §7.1 explains the
three prefix families.

- `bind(graph)` — binds `onto, entity, class, relation, fact, src, trace, owl,
  rdf, rdfs, sh, skos, prov, dqv`.
- `is_tracing(triple)` — True when the subject **or** the predicate is in
  `trace:`. This is the one filter rule for run tracing.
- `is_source_attribution(triple)` — True when the subject or the predicate is
  in `src:` (which file said what).
- `open_graph(path)` — parse existing Turtle, else `seed_graph()`.
- `seed_graph()` — 8 triples: `onto:ontology owl:Ontology`, `onto:Entity
  owl:Class` + `rdfs:label "Entity"`, `onto:EntityShape sh:NodeShape`,
  `sh:targetClass onto:Entity`, one blank-node `sh:property` rule
  (`sh:path skos:prefLabel`, `sh:minCount 1`).
- `save_graph(graph, path)` — serialize to `<path>.tmp`, then atomic
  `os.replace`; a failure removes the temp file and leaves the old file intact.
- `GraphStore` Protocol + `LocalTurtleStore` (`load`/`save`) — the legacy
  adapter the CLI hands to `LegacyTurtleDatasetStore` for `.ttl` output.

### 4.2 `graph_store.py` — the named-graph boundary

The boundary domain modules see. `GraphStore` Protocol: `get(name)`,
`put(name, graph)`, `delete(name)`, `graph_names()`, `query(sparql, **)`,
`update(sparql, **)`, `publish(publication=None)`.

- `Publication` — dataclass `{graphs: dict name→Graph, deletions: tuple}`.
  `graphs` replaces complete named graphs; anything not mentioned is untouched.
  `_apply(dataset, publication)` removes each named graph's triples, adds the
  new ones, and `remove_graph` for deletions.
- `graph_names()` (on `RdflibGraphStore`) lists only named graphs holding at
  least one triple.
- `RdflibGraphStore` — `Dataset(default_union=True)` in memory with the project
  prefixes bound (`graph_management.bind`) both on the dataset and on the
  serialization clone, so persisted TriG is readable; optional
  `path` parsed as TriG. `publish` serializes a **clone** to `<path>.tmp` and
  `os.replace`s it, then applies the publication in memory — a failed write
  changes neither the file nor the dataset.
- `ReadOnlyGraphStore` — exposes only `get`/`graph_names`/`query` (the viewer
  wraps stores in it so viewing can never write).
- `GraphNames` — role names (defaults): `schema_graphs=[.../graphs/schema]`,
  `shape_graphs=[.../graphs/shapes]`, `data_graphs=[]`, `target_graph=
  .../graphs/data`, `provenance_graph=.../graphs/provenance`, `review_graph=
  .../graphs/review`, `staging_namespace=.../trace/staging/`. `validate()` fails on
  duplicate roles or a staging namespace not ending in `/` or `#`.
  `source_staging_graph(document_id)` derives a document's staging name.
- Migration/export helpers: `import_legacy_turtle(store, path, names)` (split a
  legacy Turtle union into schema/target/provenance via `partition_graph`),
  `export_graph_turtle(store, name)`, `export_dataset(store, fmt=...)`.
- `BASE_NAMESPACE = "http://example.org/text-ontology/"` (the role names
  above hang under it).
- **Plain RDF guard**: `PlainRdfError(RuntimeError)`; `unnamed_triples(store)`
  counts triples in the default graph (0 when the store has no `.dataset`);
  `require_named_graphs(store, path=None)` raises `PlainRdfError` when there
  are any — a plain RDF file saved as `.trig` would otherwise read as empty
  and the next publication (which serializes named graphs only) would drop
  it. The message points at `python ttl_to_trig.py FILE NEW.trig`.
  `run_text_to_graph` calls it before reading the roles;
  `Workspace.require_dataset()` guards the dataset view, ingestion, the graph
  editor, and the chat, and `Workspace.status()` reports the message as
  `error`.

### 4.3 `ingest_sources.py` — source discovery + reading

`TEXT_FILES = {.txt .md .rst .csv .json .jsonl .yaml .yml .xml .html .log}`
(suffix compared lower-case).
`find_text_files(source, graph_path)` accepts a directly-named file regardless
of extension, or recursively sorted, extension-filtered, graph-excluded files;
a missing source is `RuntimeError("Source does not exist: ...")`.
`read_source(path)` reads UTF-8 with `errors="replace"`.

### 4.4 `windowing.py` — stable documents and reproducible windows

Source-only module: knows text, digests, offsets — never RDF/LLM/graph files.

Constants: `WINDOW_STRATEGY_VERSION = 2`, `DEFAULT_TARGET_TOKENS = 800`,
`DEFAULT_OVERLAP_TOKENS = 100`, `MEDIA_TYPES` (`.txt/.md/.rst/.html/.htm/
.csv/.json/.xml` → media types).

- `normalize_text(raw_text)` — CRLF/CR → LF (the only normalization).
- `media_type_for(path)` — suffix → media type, default `text/plain`.
- `make_source_document(name, raw_text, media_type="text/plain", source_path="")`
  — `document_id = "doc-" + sha256(normalized text)[:16]`.
- `load_source_document(path)` — read + build one document.
- `plan_windows(document, config=None)` — blank (whitespace-only) documents
  yield `[]`; otherwise unit spans (blocks → sentences → hard chunks) are
  packed greedily with shared token overlap. Short documents get one
  `(0, len(text))` window. Window IDs are SHA-256 digests over strategy
  version, target/overlap, tokenizer name, document ID, index, start, end
  (`win-<sha256[:16]>`).
- The pipeline calls `make_source_document(path.name, raw_text,
  source_path=...)` without a media type, so pipeline documents are always
  `text/plain`; `media_type_for` is not used by the pipeline.

### 4.5 `source_parse.py` — prompt builder

- `context_block(context_text)` — headed context + `CONTEXT_RULES`, `""` when
  empty.
- `make_prompt(text, context_text="", library=None)` — renders the
  `extraction_user` template with `context` (the headed, explained context
  block) and `text`, so an edited prompt is used without this module changing.
- `parse_source(text, context_text="", library=None)` =
  `parse_prompt(make_prompt(...))`; `parse_prompt(prompt)` = `ask_llm(prompt)`.

### 4.6 `llm.py` — chat client, OpenRouter or Google (stdlib only)

- Constants: `DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"`,
  `OLD_DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b:nitro"` (kept for reference),
  `MAX_OUTPUT_TOKENS = 4_096`, `SYSTEM_PROMPT = "Extract knowledge. Return
  only JSON."`, `RETRY_STATUSES = {429, 500, 502, 503}`,
  `RETRY_WAITS = (2, 5, 15)`.
- `PROVIDERS` — one entry per provider: chat-completions URL, key variable,
  model variable, default model, extra headers. `openrouter`
  (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, default `DEFAULT_MODEL`,
  `X-OpenRouter-Title`) and `google` (the Gemini API's OpenAI-compatible
  endpoint; `GEMINI_API_KEY`, `GEMINI_MODEL`, default
  `gemini-3.1-flash-lite`). `provider_name()` reads `LLM_PROVIDER`
  (default `openrouter`; an unknown name is a `RuntimeError`); `provider()`
  returns that entry.
- `load_env(path=None)` — `.env` in the working directory: `KEY=value` lines
  (`#` comments skipped, a leading `export ` and surrounding quotes
  stripped), `setdefault`: a shell variable wins over `.env`.
- `model_name()` — the provider's model variable or its default;
  `max_output_tokens()` — the `OPENROUTER_MAX_TOKENS` variable, else the
  `MAX_OUTPUT_TOKENS` constant (4,096), for both providers.
- `ask_choice(prompt, system=None, model=None)` — the one request: `{"model",
  "temperature": 0, "max_tokens", "messages"}` plus, for Google,
  `reasoning_effort` from `GEMINI_REASONING_EFFORT` (default `none`; empty
  sends nothing). Bearer key (missing → `RuntimeError("Set <KEY> first")`),
  timeout 60 s. HTTP 429/500/502/503 are retried after 2, 5, and 15 s; any
  other HTTP error is `RuntimeError("<provider> error <code>: <message>")`.
- `ask_llm(...)` — the JSON answer: an empty answer (a model that spent every
  token reasoning) or non-JSON raises `InvalidResponseError` (what
  `repair.py` catches); Markdown-fenced JSON is accepted. `ask_llm_text(...)`
  — the same request, answer as plain text.
- `OpenRouterExtractor(model=None, system_prompt=None)` — the adapter for
  every provider despite its name. `model()` → override or `model_name()`;
  `extract(prompt)` → `ask_llm(prompt, system=self.system_prompt)` (the model
  override is sent when set), so the pipeline can hand it the (possibly
  edited) `extraction_system` text; `extract_text(prompt, system=None)` →
  `ask_llm_text(...)` for the graph chat, where `system` wins over the
  client's own message so a chat answer is prose, not JSON.

### 4.7 `repair.py` — bounded self-repair

- `repair_prompt(original=None, raw_problem=None, issues=(),
  shape=EXTRACTION_SHAPE)` — the model gets its own original answer back plus
  the deterministic, sorted issue list and one instruction: return the
  complete corrected JSON in the named shape (`EXTRACTION_SHAPE` is
  `"entities", "relations", "facts"`; `starter.STARTER_SHAPE` is the starter
  contract).
- `ExtractionOutcome` — `validation` (None when nothing parsed), `raw_problem`,
  `repair_attempts`, `response` (the last parsed answer, used by
  `drop_endpoint_mismatches`); `.ok` = `raw_problem is None` AND
  `validation["valid"]`.
- `extract_validated(extractor, prompt, validate, max_repair_attempts=0,
  shape=EXTRACTION_SHAPE)` —
  extract, validate, and while the answer is unparseable/invalid and attempts
  remain, send a repair prompt and validate again. **Every** attempt passes the
  same `validate` gate (the pipeline passes `validate_candidates`).

### 4.8 `candidate_validation.py` — validate + normalize

Read-only, fail-closed. Public contract:

- `validate_candidates(data, graph, allowed_existing_ids=(),
  vocabulary=None)` → `{valid, candidates|None, issues, counts}`.
- `format_validation_failure(result)` → deterministic CLI error text.
- With a `vocabulary` (data-only ingestion) a kind whose class IRI the starter
  does not declare is `entity.undeclared_kind`, an undeclared relation is
  `relation.undeclared_predicate`, and an undeclared fact is
  `fact.undeclared_predicate`; every message lists the declared names so the
  model can repair its answer.
- With a `vocabulary` there is also an **endpoint check** (`_check_endpoints`,
  pass 4b): a relation's subject/object and a fact's subject must have the
  declared domain/range class or a subclass (an `existing_id` entity is
  checked by its graph kind; a side with no declared domain/range is not
  checked). Codes `relation.domain_mismatch`, `relation.range_mismatch`,
  `fact.domain_mismatch` (`ENDPOINT_CODES`).
- `drop_endpoint_mismatches(data, validation)` → `(kept_data, {"records":
  [{section, record}], "messages": [...]})`, or `None` when any error other
  than an endpoint mismatch is present.

Normalization is conservative (NFKC, CRLF→LF, controls removed, one-line
whitespace collapsed, descriptions/facts preserved, dates/numbers never
coerced, fact JSON type part of the duplicate key). Passes: container →
entity normalization + confidence (required in `[0,1]`, missing/invalid codes)
→ relation/fact normalization → reference check → endpoint check (only with a
vocabulary) → label/role/type collisions →
exact dedupe (with `duplicate_confidence` lowering the kept value) →
graph-URI role/type compatibility. Graph-exact assertions are deliberately
**kept** so merge policy can plan corroboration and provenance. `existing_id`
is accepted only if it was rendered in the final budgeted prompt and still
exists in `entity_catalog(graph)` (with a kind-match check).

### 4.9 `candidate_graph.py` — one validated package → RDF candidate graph

- Constants: `CANDIDATE_MAPPING_VERSION = 2`, `PROVISIONAL`
  (`trace:provisional/`), `EXTRACTION_CONFIDENCE_METRIC`
  (`trace:metric/extraction-confidence`). `DQV` is imported from
  `graph_management` (and re-exported for `source_reconciliation`). Every IRI
  this module mints is tracing: `trace:candidate/<doc>/<window>/<section>/<i>`,
  `trace:document/`, `trace:window/`, `trace:activity/`, `trace:agent/`.
- `literal_value(value)` — conservative typed literals; real ISO dates become
  `xsd:date`, booleans/ints/floats typed, everything else a plain string.
- `provisional_entity_iri(document_id, local_id)` — the stable provisional IRI
  of one unresolved individual.
- `build_candidate_graph(candidates, document_id, window_id, activity_id,
  extractor_model, entity_iris=None, assertion_triples=None)` — deterministic:
  every record becomes a `prov:Collection`; asserted triples are present AND
  reified as `rdf:Statement` members; per-record confidence is a
  `dqv:QualityMeasurement` (xsd:decimal) against the project `dqv:Metric`;
  PROV-O chain: document → window → activity → `prov:SoftwareAgent`
  (all `trace:` IRIs). The graph is published only with `--trace`
  (`ProcessingConfig.trace`); staging and reconciliation always build it.
  Entities are typed with their kind class (not a `kind` string) with
  `skos/definition/altLabel`; relations/facts use `RELATION[slug]` /
  `FACT[slug]` IRIs. Same response always produces the same graph.

### 4.10 `source_staging.py` — one document, one provisional graph

- `STAGING_NAMESPACE = TRACE + "staging/"` (`trace:staging/`).
- `source_staging_graph_name(document_id)`, `window_candidate_graph_name(doc,
  window)` — stable graph names.
- `window_activity_id(document_id, window_id, model, candidates)` — PROV
  activity ID (`sha256(...)[:16]`).
- `provisional_allocator(document_id)` — slug-first `-2, -3, ...` allocation
  inside `trace:provisional/<doc>/`, so a staged entity can never claim a canonical
  identity.
- `plan_window_admission(source_graph, candidates, provenance, document_id,
  min_new_confidence=0.80)` — `plan_graph_merge` against the source staging
  graph only, with the provisional allocator.
- `final_graphs_snapshot(graph)` — `tuple(sorted(graph))` for immutability
  checks.
- `layered_context_text(canonical_package, source_package, budget_config,
  count_tokens)` — renders canonical + source-local items as one block;
  source-local items are prefixed `(this document)` per line and their
  resources forced `native: False` and `hide_uri: True` (no provisional IRI is
  shown, so it can never become an `existing_id`; reuse is by exact name and
  kind). `existing_ids` come only from canonical native resources that
  survived the budget. One shared
  budget (`allowance - assembly_overhead`) covers both; items drop whole,
  least relevant first.
- `retain_staging(store, document_id, graph_path)` — exports a failed
  document's staging graphs to `<graph_path>.staging/<document_id>.trig`.

### 4.11 `source_reconciliation.py` — complete-document report + artifact

- `SourceGraphArtifact` — `document_id`, `document_digest`, `graph_digest`,
  `window_strategy_version`, `candidate_mapping_version`,
  `extractor_identities`, `ntriples`.
- `canonical_ntriples(graph)` — RDF blank-node canonicalized, sorted N-Triples.
- `build_source_artifact(document, source_graph, windowing, models)` —
  deterministic export + association metadata.
- `reconcile_document(document_id, source_graph, candidate_graphs,
  admission_plans)` → plain report: `local_entities` (uri/name/kind/aliases),
  `aliases`, `duplicate_assertions` (triple + support_count + the independent
  candidate-graph/record/confidence supports), `unresolved_identities`
  (window/local_id/reason_codes/suggestions), `conflicts`, and `counts`.

### 4.12 `source_validation.py` — the SHACL gate

- `SourceValidationResult` — `conforms`, `report_graph`, `report_text`,
  `shape_graphs_checked`.
- `SourceValidationError(RuntimeError)` — carries `validation`,
  `source_artifact`, `reconciliation_report`, `sidecar_path`.
- `embedded_shape_graph(graph)` — copies legacy embedded SHACL shapes
  (recursively following shape-owned blank nodes).
- `combine_shape_graphs(shape_graphs)` — one isolated graph, blank nodes
  renamed per shape graph.
- `validate_source_graph(source_graph, shape_graphs)` — pySHACL over a copy
  (`inference="none"`, `abort_on_first=False`, `allow_infos=False`,
  `allow_warnings=True`: a `sh:Warning` result — such as an expected link,
  §4.24 — is reported but never makes the graph non-conformant).

### 4.13 `merge_policy.py` — read-only merge planning

Policy layer, unchanged in role but versioned 2. Constants:
`MERGE_POLICY_VERSION = 2`, `AUTO_ACCEPT_MIN_CONFIDENCE = 0.80`, `RDF_JSON`
(`rdf:JSON`), `FUNCTIONAL` / `INVERSE_FUNCTIONAL`.

- `canonical_json(value)` / `record_digest(record)` — the digest base.
- `proposed_entity_uri(entity)` — `trace:merge-proposed-entity/<sha256>`, a
  review-only provisional identity (never typed `onto:Entity`).
- `build_provenance(source_path, source_text, model)` →
  `{source_path, source_sha256, model, policy_version}`.
- `resolve_entities(candidates, graph, min_new_confidence=0.80,
  allocate_uri=None, provisional_uri=None)` — ordered identity decisions with
  a virtual catalog and URI reservation so two new entities cannot collide;
  `allocate_uri`/`provisional_uri` are injectable (staging passes the
  document's provisional allocator).
- `plan_graph_merge(graph, candidates, provenance, min_new_confidence=0.80,
  allocate_uri=None, provisional_uri=None, vocabulary=None)` → MergePlan:
  `{policy_version, provenance, event_uri, package_sha256, identities,
  entities, relations, facts, domain_triples, audit_triples, counts,
  diagnostics}`.

**Decision precedence** (read only; existing canonical values are never
overwritten): validation errors → identity ambiguity review → exact-triple
duplicate (corroboration, any confidence) → explicit functional /
inverse-functional conflict review → below-`min_new_confidence` review →
accept (with property declarations). Entity fields plan per-field outcomes
(`accept`/`duplicate`/`review`/`partial_review`/`none`); an alias claimed by
another same-kind entity routes only that alias to review.
With a `vocabulary`, planning is data-only: `_plan_new_entity` does not emit
`class_triples(kind)` and `_plan_assertion` emits no property declarations, so
a plan can only add individuals and statements. It also asks the vocabulary for
the class and predicate IRIs, so ingestion follows an imported ontology's own
names. Identity decisions and conflict handling are unchanged.

**Audit vocabulary** (all under `trace:`, types and predicates alike; support
partition; no timestamps, no raw source/prompt/response):
`trace:ExtractionEvent` at `trace:merge-event/<sha256>` (sourcePath,
sourceSha256, modelName, mergePolicyVersion, candidatePackageSha256) and
`trace:MergeCandidate` at `trace:merge-candidate/<event>/<section>-<i>-<digest>`
(wasExtractedIn, candidateSection, candidateIndex,
normalizedCandidate as `rdf:JSON`, extractionConfidence as `xsd:decimal`,
mergeDecision, decisionReason per code, fieldDecisions for entities,
resolvedEntity / proposedEntity, reified rdf:subject/predicate/object for
grounded assertions). Event URIs are SHA-256 digests over policy version,
source path, source digest, model, window/document/config, and package digest;
candidate URIs add section/index/record digest, so exact reruns reuse the same
audit resources.

### 4.14 `entity_lookup.py` — identity decisions

`CLOSE_SPELLING_THRESHOLD = 0.96`; `identity_key` (lossy NFKD→ascii);
`entity_catalog(graph)`; `identity_decision(entity, catalog,
planned_catalog=(), *, min_new_confidence=0.80, allocate_uri=None,
provisional_uri=None)` → `{local_id, status, uri, method, identity_score,
suggestions, reason_codes}`. Order: explicit id → unique same-kind exact
(planned_exact/exact_name/exact_alias) → ambiguous-exact review →
kind-collision review → close-spelling review-only suggestions →
inflected-form review (`source_concepts.same_name_stem`, same kind only,
method `inflected_form`, reason `identity.inflected_form`; never a merge) →
new (≥ confidence) or below-threshold review
(`identity.new_below_confidence`) with a provisional URI. `identify_entity`
remains as a legacy wrapper.

### 4.15 `graph_merge.py` — materialize a plan into a copy

- `slug` / `label` / `class_uri` / `class_triples` / `new_entity_uri` helpers.
- `apply_merge_plan(source_graph, plan)` — copies bindings + all triples,
  asserts only the plan's decided domain and audit triples, returns
  `(graph copy, counts)`. Input stays triple-identical. No identity/conflict
  logic.
- `merge_into_graph(graph, data)` — legacy direct merger for compatibility.

### 4.16 `document_merge.py` — one complete-document merge plan

- `DOCUMENT_MERGE_VERSION = 1`.
- `DocumentCandidateBundle` — `candidates`, `source_keys_by_window`,
  `local_id_by_source`.
- `build_document_candidates(document_id, packages, admission_plans)` —
  collapses window packages: safe source-local identities share one record;
  review-held identities stay separate and are reconsidered against the full
  canonical scope; exact overlap assertions become one planned assertion (the
  **strongest** confidence wins); entities combine aliases/descriptions.
- `plan_document_merge(canonical_graph, document, packages, admission_plans,
  min_new_confidence, planner=plan_graph_merge, vocabulary=None,
  configuration=None)` — resolves the whole reconciled source against the
  canonical scope **once**; adds `document_merge_version`,
  `configuration_sha256` (over `configuration` plus the version and the
  confidence floor), and an `identity_mapping` from source keys to final
  identity decisions. The pipeline passes the two extraction prompt digests
  and `schema_sha256` here, so a run artifact names the templates and the
  schema that produced it.

### 4.17 `document_publication.py` — compile + atomic publish

- `DocumentPublicationPlan` — `document_id`, `document_merge`,
  `proposed_validation`, `publication` (a `Publication`), `counts`.
- `PublicationValidationError` — `plan` + `validation`.
- `LegacyTurtleDatasetStore` — wraps a legacy `get/load/save` store; splits the
  loaded Turtle into in-memory roles and persists the union as one Turtle on
  each `publish` via `save_graph`.
- `split_legacy_graph(graph, names)` / `initial_role_graphs(store, names)` /
  `canonical_graph(roles, names)` (schema graphs + configured `data_graphs` +
  the target graph = the identity scope) / `shape_graphs(roles, names)` /
  `copy_graph` / `union_graphs`.
- `compile_document_publication(document, document_merge, candidate_graphs,
  packages, admission_plans, roles, names, validation_shapes=None,
  trace=False)` — copies the target graph, adds the plan's domain triples and
  the `src:` source links (`source_attribution`) to it; the provenance graph
  always gets `trace_sources` (the document record and which document
  supported each published entity and statement); only with `trace` does it
  also get the remapped per-window candidate evidence
  (`remap_candidate_evidence`: candidates, windows, activities, agents, DQV
  confidences, then `link_statement_sources`). It builds the review graph and
  SHACL-validates the proposed data (no mutation).
  Its `Publication` carries every role: target, provenance, and review are
  new; schema, shapes, and data-graph roles are copied through unchanged.
- `publish_document(store, plan)` — the one final `store.publish(...)`.
- `remap_candidate_evidence` / `_copy_evidence` — every PROV/DQV occurrence is
  kept while reified statements are remapped to their final identity (used
  only with `trace`).
- `build_review_graph(document, document_merge)` — withheld identities and
  assertions as `trace:review/<doc>/<digest>` `prov:Collection`s with
  `rdf:Statement` members and `prov:wasDerivedFrom trace:document/<id>`;
  `link_statement_sources` adds the document record and
  `trace:sourceDocument` / `trace:sourceFile` to each statement.

### 4.18 `publication_sources.py` — which source file said what

Two sides (§7.1): **business** source links (`src:`) go to the data graph;
**tracing** (`trace:`) goes to the provenance and review graphs.

Stable IRIs:

- `file_uri(document)` — `src:file/<sha256 of the path only>` (path =
  `source_path or name`). One node per path, so re-ingesting an edited file
  adds no new node; the same name in two folders gives two nodes.
- `statement_uri(triple)` — `src:statement/<sha256 of the three terms' n3()>`.
- `document_uri(document)` — `trace:document/<document_id>`: one *version* of
  a file's content, which is run history.

Business side (returned as a `Graph`, added to the target data graph):

- `source_attribution(document, document_merge, canonical)` — the file node
  (`a src:SourceFile`, `rdfs:label` file name, `src:path`); `src:fromFile`
  on each published entity (`published_entities`: identity not `review`,
  typed `onto:Entity` in `canonical`); and for each accepted or duplicate
  relation/fact triple present in `canonical` (`published_statements`) one
  `src:statement/<hash>` node (`a rdf:Statement`, `rdf:subject` /
  `rdf:predicate` / `rdf:object`, `src:fromFile`). Classes and properties get
  no source link (they are the starter's, not the texts'); withheld claims
  get none either.
- `forget_statement(graph, triple)` — removes the `src:statement` node of a
  triple that was removed (used by `graph_edit.publication`).

Tracing side:

- `document_record(graph, document)` — adds `trace:document/<id>`
  (`a prov:Entity`, `rdfs:label`, `trace:sourceFile` → the `src:file` node)
  and returns its IRI.
- `trace_sources(document, document_merge, canonical)` → `Graph`: the
  document record plus `trace:sourceDocument` on every published entity and
  `src:statement` node. Always written to provenance.
- `link_statement_sources(graph, document)` — adds the document record and
  `trace:sourceDocument` + `trace:sourceFile` to every reified
  `rdf:Statement` of evidence or review (skips the app-supplied `onto:Entity`
  root).

### 4.19 `run_report.py` — human-readable reporting

- `REPORT_DIRECTORY = Path("reports/runs")`; `default_report_path(source,
  started_at=None)` → the path below.
- `RunReporter(verbose=False, stream=None, extra_streams=(),
  markdown_streams=())` — one reporter object; plain terminal lines, verbose
  sections, code blocks, and Markdown-safe output (helpers `line`,
  `verbose_line`, `block`, `section`). Checkpoints: `run_started`,
  `source_started`, `blank_source`, `document_staging`, `window_started`,
  `context_selection`, `prompt_context`, `asking_model`, `llm_input`,
  `model_replied`, `validation` (also lists `validation["dropped"]`),
  `window_admitted`, `link_check`, `reconciliation`, `source_validation`,
  `publication_validation`, `merge_plan`, `dry_run`, `saved`,
  `staging_failed`, `finished`, `dry_run_finished`, `failed`.
- Report file name: `%Y-%m-%d_%H-%M-%S_%f_<source stem>.md`.
- Helpers `skeleton_label` / `skeleton_restriction` are shared with the viewer.

### 4.20 `vocabulary.py` — the starter vocabulary lock

Read-only, no writes. `Vocabulary(classes, relations, facts)` holds three
`{resource IRI: readable name}` dicts. `read_vocabulary(graph)` collects named
subjects of `owl:Class` / `rdfs:Class`, `owl:ObjectProperty`, and
`owl:DatatypeProperty` (blank nodes skipped, missing labels fall back to the
IRI).

**The starter is the naming authority.** `class_iri(kind)`,
`relation_iri(predicate)`, and `fact_iri(predicate)` return the declared IRI
whose label (or local name) folds to the same slug as the candidate's name, or
the generated `class:` / `relation:` / `fact:` IRI when nothing was declared.
That is what lets an imported RDF vocabulary keep its own IRIs instead of
gaining `class:*` twins: merge planning and the collision check both ask the
vocabulary. `_match(declared, generated, name)` and `local_name(iri)` are the
two small helpers (`_match` prefers the generated IRI when it is declared,
then a declared label or local name with the same slug).
`declares_class` / `declares_relation` / `declares_fact` answer "is this name
declared?" (used by `link_check.add_expected_link`). `class_names` /
`relation_names` / `fact_names` are sorted display names; `is_empty` is the
"no starter yet" signal the studio shows.

`read_vocabulary` also keeps each property's declared `rdfs:domain` /
`rdfs:range` (`domains`, `ranges` — ranges only for relations; one value
each, read with `graph.value`) and each class's declared parents
(`parents`). `is_a(class, wanted)` follows `rdfs:subClassOf` upward;
`domain_of`, `range_of`, and `label_of` are the readers the endpoint check,
the link check, and the health report use.

### 4.21 Connectivity in data-only ingestion (overview)

Data-only ingestion (the studio's mode, CLI `--data-only`) adds these to
every window and document; none of them runs in a legacy (non data-only) run:

- the **core schema** block — the whole starter schema, first in every
  window's context (§4.22);
- the **document header**, **document anchors**, and **same-folder** blocks
  (§4.23);
- the **endpoint check** in the validation gate (§4.8): a wrongly connected
  relation/fact goes through repair first; if only endpoint mismatches remain
  after repair, `drop_endpoint_mismatches` removes just those records and the
  window continues (`validation["dropped"]`, reported);
- the **link check** after the last window (§4.24), on by default
  (`ExtractionConfig.link_check`, CLI `--no-link-check`).

The four fixed blocks are shown before the selected context and paid by
adding their estimated size to `fixed_prompt_tokens` (`pipeline.budget_for`),
so they never squeeze the `context_tokens` allowance.

Two things apply in **every** run, not only data-only:

- **Seed view** (§4.25): every prompt's context, the vocabulary, and the chat
  read the seed view, not the full dataset.
- **Names**: `source_concepts.same_word_stem` / `same_name_stem` treat
  "Polpharma"/"Polpharmy" as one word (≥ 5 characters, endings ≤ 2 differ).
  `task_context` uses it as a `CONCEPT`-tier "inflected name match", so the
  existing card (with its `id:`) is shown; `entity_lookup.identity_decision`
  uses it only for a `review` decision (`inflected_form`), never a merge.
  Aliases are `skos:altLabel`, added through **Edit the graph**.

The studio keeps dropped folder structure under `sources/inbox/`
(`workspace._write_source` cleans each part and never leaves the inbox) and
passes the inbox as `RunRequest.source_root`, so the header shows
`client/project/notes.md`. The `src:path` of the file node in the data graph
is unchanged (the path as discovered). `graph_health.py` (§4.26) is the separate, read-only tool that
measures the result.

### 4.22 `schema_context.py` — the whole starter schema as one prompt block

Read-only. Constants: `HEADING` (`CORE SCHEMA — the only classes and
relationships you may use`), `RULES` (with a `${fallback}` slot),
`WITH_ROOT` / `WITHOUT_ROOT`.

- `render_core_schema(graph)` → one deterministic text block: every class
  sorted by label with its `rdfs:comment` as meaning (`onto:Entity`, when
  declared, comes last as "only for things that fit no class above");
  `Domain --relation--> Range: meaning` lines (`anything` when undeclared);
  `Domain . fact = Range` lines (`value` when undeclared); then three rules:
  the most specific kind, declared direction only, base-form names with other
  forms as aliases. The fallback rule is `WITH_ROOT` ("Use "Entity" only when
  no class fits; an Entity cannot be ... in a relationship") when
  `onto:Entity` is declared, else `WITHOUT_ROOT` ("Leave out anything no
  class fits."). Graph text goes through `context_render.clean`/`field`.
- `schema_digest(schema_graphs)` → 12 hex characters of the sha256 over
  blank-node-canonicalized, sorted triples; recorded in the run configuration
  as `schema_sha256` (in every run).
- The pipeline renders it once per run from the seed view. When its estimated
  size exceeds `PROMPT_BUDGET["schema_tokens"]` (3,000), the word-matched
  schema selection is used instead and `reporter.line("Core schema: N tokens
  is over the schema budget; ...")` says so. When it is shown, the
  word-matched `declared` section is left out of the selected context.

### 4.23 `document_context.py` — what a window knows about its document

Read-only. Constants: `MAX_TITLE_CHARACTERS = 200`, `MAX_ANCHORS = 8`,
`MAX_FOLDER_ANCHORS = 5`, `MAX_LINKS_PER_ANCHOR = 5`, and the three headings
`HEADER_HEADING`, `ANCHOR_HEADING`, `FOLDER_HEADING`.

- `document_title(text)` — the first Markdown heading, else the first
  non-empty line (≤ 200 characters).
- `heading_trail(text, start)` — the headings in force at a window's start,
  e.g. `# A > ## B`.
- `render_document_header(display_path, document_text, window, total)` —
  `DOCUMENT CONTEXT ...` with `Path:` (relative to `RunRequest.source_root`),
  `Title:`, `Section:`, `Window: k of n`. All text cleaned, so a path cannot
  forge a delimiter.
- `anchor_classes(vocabulary)` — the declared domain class of every
  relation (a class that is the subject of some relationship).
- `is_anchor(graph, entity, vocabulary, anchors)` — the entity's `onto:kind`
  is an anchor class or a subclass of one.
- `document_anchors(source_graph, vocabulary, limit=8)` — this document's
  staging entities of an anchor class, most connected first (triples touching
  them), then by name. `render_document_anchors(source_graph, vocabulary)` —
  cards with name, kind, aliases and up to 5 links, **without** `id:` (reuse
  is by exact name + kind); `""` when there are none.
- `folder_anchors(graph, sources, vocabulary, source_path, limit=5)` —
  canonical anchor entities whose `src:fromFile` node has a `src:path` in the
  same folder (the current file excluded), most supporting links first.
  `graph` is the seed view; `sources` is the data graph (the pipeline passes
  `canonical_graph(roles, names)`), so the provenance graph is not read.
  `render_folder_anchors(graph, entities)` — the same cards **with** `id:`; the pipeline adds those ids to the allowed
  `existing_ids`.

### 4.24 `link_check.py` — expected links, and one question per missing one

Constants: `EXPECTED = onto:expected/`, `MAX_LINK_CHECKS = 5`,
`MAX_CANDIDATES = 20`, `PASSAGE_TOKENS = 2_500`,
`MIN_EVIDENCE_CHARACTERS = 8`.

*Expected links* are SHACL `sh:minCount 1` + `sh:severity sh:Warning`
property shapes in the shapes graph. Because SHACL validation passes
`allow_warnings=True` (§4.12), they never block a document.

- `expected_link_shape(class_iri, relation_iri, question)` — the shape
  `onto:expected/<class>-<relation>` as a small graph (`sh:message` = the
  question).
- `expected_links(shapes_graph)` → sorted `[{class, relation, question}]`.
- `add_expected_link(store, class_name, relation_name, question="",
  names=None)` — the class and relation must be declared and the relation
  must start at that class (or a parent), else `ValueError`; publishes into
  the first shapes graph.
- `find_gaps(source_graph, canonical, expected, vocabulary, limit=5)` — a
  direct graph check (not pySHACL): this document's entities of the shape's class
  that lack the link, skipping those whose canonical twin (same kind, a
  shared name) already has it; most connected first.
- `select_passages(windows, names, cap=2_500, count_tokens=estimate_tokens)`
  — window 1 plus every window naming the subject or a candidate, in
  document order, whole, stopping before the cap.
- `object_candidates(source_graph, canonical, range_iri, vocabulary,
  passages, limit=20)` — entities of the range class, this document's first,
  then canonical ones (with their id); those the text names sort first; keys
  `c1…`.
- `link_check_prompt(gap, source_graph, vocabulary, candidates, passages,
  library=None)` — renders the `link_check_user` template (§4.28).
- `read_answer(answer, gap, source_graph, vocabulary, candidates, passages)`
  → `(package or None, dropped notes)`. The answer is `{"links": [{object,
  evidence, confidence}]}`; a link is kept only when its evidence is at least
  8 characters and appears (case- and whitespace-folded) in the passages,
  otherwise `link_check.unsupported_evidence`. The kept links become an
  ordinary candidate package.
- `link_window(document, gap, passages, index)` — a synthetic `TextWindow`
  `link-<sha256[:16]>` with the passages as text.
- `check_document_links(document, display_path, windows, source_graph,
  canonical, expected, vocabulary, extractor, reporter=None, library=None,
  limit=5)` → `(packages, summary)`; summary `{gaps, filled,
  not_established, dropped}`. Each package passes `validate_candidates(...,
  vocabulary=)`; there is no repair round, and an `InvalidResponseError`
  makes the gap "not established". The pipeline admits each package like a
  window, so reconciliation, provenance, and publication need no special
  case; the summary is `DocumentResult.link_check`.
- `main(argv)` — `text-to-ontology-expect GRAPH [CLASS RELATION [QUESTION]]
  [--list]`.

### 4.25 `seed_view.py` — the business-ontology view

Read-only. `NAMING = {skos:prefLabel, skos:altLabel, skos:definition,
rdfs:label, rdfs:comment, onto:kind}`.

- `keep_in_seed(triple, declared_terms, declared_classes,
  declared_properties)` — first drops every `src:` and `trace:` triple
  (`is_source_attribution` / `is_tracing`: which file said it is not part of
  what was said); then keeps a triple whose subject is a declared term, an
  `rdf:type` to a declared class, a `NAMING` triple, or a triple with a
  declared property.
- `seed_graphs(roles, names)` → `{graph name: Graph}`: schema graphs whole;
  data and target graphs filtered by `keep_in_seed`, with "declared" read from
  schema + data (so legacy runs that declared in the data graph still work).
  Provenance, review, shapes, `src:`/`trace:` triples, `owl:NamedIndividual`,
  and `skos:Concept` types are left out.
- `seed_view(roles, names)` — their union as one graph, prefixes bound.
- `store_roles(store, names)` — every role graph of a store.

Used by the pipeline (every prompt's context and the vocabulary; rebuilt
after each publication; the full data graph, with its `src:` links, is passed
separately to `folder_anchors`), `Workspace.seed_graph()` (the chat), and the `dataset`
operation's `view=seed` (default; `view=all` shows every role graph).

### 4.26 `graph_health.py` — connectivity numbers (`text-to-ontology-health`)

Read-only: no model call, nothing written. Constants: `NAME_PREDICATES`
(`skos:prefLabel`, `skos:altLabel`, `rdfs:label`), `DOCUMENT = trace:document/`.

- One function per number: `isolated_entities(data)`,
  `root_only_entities(data, vocabulary)`, `endpoint_violations(data,
  vocabulary)`, `missing_links(data, vocabulary, expected)` (expected links
  from `link_check.expected_links`; there is no built-in list),
  `duplicate_suspects(data, vocabulary)` (`same_name_stem` on pairs of
  entities; compares every pair), `uncovered_sources(provenance, folder)`
  (files whose `doc-<sha>` has no `trace:document/` record in provenance),
  `gold_scores(data, vocabulary, gold_links)` → `{gold, found, recall,
  checked, correct, precision, missing}`.
- `health_report(graph_path, sources=None, gold_path=None)` → dict; always
  uses the default `GraphNames()`; schema = schema graphs, data = target +
  data graphs.
- `format_report(report, limit=20)` → short text; `main(argv=None)` —
  `text-to-ontology-health GRAPH [--sources DIR] [--gold FILE] [--json]`.
- The gold file is `{"links": [{subject, predicate, object}]}`; see
  `eval/gold.example.json` (real ones are `eval/*.local.json`, git-ignored).

### 4.27 `starter.py` — the starter ontology

Constants: `DEFAULT_GRAPH = Path("ontology.trig")`, `MIN_CLASSES = 2`,
`MAX_CLASSES = 20`, `MAX_ASSERTIONS = 40`, `XSD_TYPES` (short name → XSD
datatype), `XSD_NAMES` (`"string, integer, decimal, float, boolean, date,
datetime, anyURI"`, the `${xsd_names}` value), `STARTER_SHAPE` (the repair
contract text), `STARTER_PROMPT`.

- `starter_prompt(text)` — one prompt: JSON with `classes`, `relations`,
  `facts`; relations carry domain + range class names, facts carry a domain and
  an optional XSD range; names must not be camelCase.
- `validate_starter(data)` — the same result shape as
  `candidate_validation.validate_candidates` (`{valid, candidates, issues,
  counts}`), so `repair.extract_validated` drives it unchanged. Rejects
  missing/unknown sections, empty or camelCase names, unknown domain/range
  classes, unknown literal ranges, duplicates, fewer than `MIN_CLASSES` or more
  than `MAX_CLASSES` classes, and more than `MAX_ASSERTIONS` relations + facts.
- `propose_starter(text, extractor, repair_attempts=2, library=None)` —
  prompt → repair → validated proposal, or `RuntimeError` with
  `format_starter_failure(...)`. `starter_prompt(text, library=None)` renders
  the `starter` template with the live class and assertion caps.
- `starter_publication(proposal, names=None)` — one `Publication` replacing the
  schema, shapes, target, provenance, and review roles: the seed's
  `onto:Entity` root and `EntityShape` shape survive, every class becomes
  `class:<slug>` (`owl:Class`, label, comment, `rdfs:subClassOf onto:Entity`),
  every relation `relation:<slug>` (`owl:ObjectProperty`, domain, range), every
  fact `fact:<slug>` (`owl:DatatypeProperty`, domain, range). Everything else
  starts empty, so an old dataset is replaced whole.
- `create_starter(text, graph_path, extractor=None, names=None)` — propose and
  publish; returns the proposal. It always uses the default prompts (only
  `Workspace.create_starter` passes its prompt library).
- `proposal_summary(proposal)` — the short plain-text listing.
- `build_parser()` / `main(argv)` — `text-to-ontology-starter [INFO|-] [GRAPH]
  [--model]`; reads a file or standard input. Importing an RDF document from
  the command line is the root script `ttl_to_trig.py SOURCE OUTPUT [--force]
  [--concepts-as-classes]` (§4.37).
- **Importing RDF instead of asking the model**: `RDF_SUFFIXES` (suffix →
  rdflib format), `RDF_FORMATS` (the order tried when the suffix says nothing),
  `RDF_SIGNS` (the content sniff). `looks_like_rdf(name, text)` trusts a known
  suffix and otherwise sniffs; `parse_rdf(text, name)` returns
  `(format, graph or Dataset)` and raises a `ValueError` listing what it tried;
  `import_publication(text, name, names)` returns one `Publication` plus a
  summary of counts and vocabulary, refusing a document that declares no
  classes or properties; `import_starter(text, name, graph_path, names)` writes
  it atomically; `import_summary(summary)` is the plain-text report.
  `_roles_from_parsed(parsed, names)` imports this project's own named graphs
  role for role when the document carries them (so an exported dataset can be
  edited and dropped back in), keeps any other named graph as data, and
  otherwise partitions the union: classes and properties to the schema,
  embedded SHACL shapes to the shapes graph, individuals and statements to the
  data graph, the rest as support. `_triples(parsed)` reads a graph or a
  dataset.

### 4.28 `prompts.py` — editable prompt templates

Every prompt the application sends is a named template here: defaults in code
(the tested wording), overrides in one JSON file beside the dataset. Templates
use `string.Template` placeholders (`${context}`, `${text}`), not
`str.format`, because these prompts carry JSON braces a human edits by hand and
should never have to escape.

- `DEFAULT_PROMPTS` — six templates: `extraction_system`, `extraction_user`,
  `starter`, `link_check_user`, `chat_system`, `chat_user`. The chat pair is
  what makes an answer prose (`chat_system`) written from one subgraph
  (`chat_user`). `link_check_user` is the one question per missing expected
  link (§4.24).
- `PROMPT_FIELDS` / `REQUIRED_FIELDS` — the placeholders a template may use and
  the ones it must keep: `extraction_user` `context`, `text` (both required);
  `starter` `text` required, `min_classes`, `max_classes`, `xsd_names`
  optional; `link_check_user` `question`, `relation`, `subject`,
  `candidates`, `passages` (the last three required); `chat_user`
  `question`, `history`, `scope_note`, `subgraph` (`question`, `subgraph`
  required).
- `ADVICE` — non-blocking hints for a human editor, for `extraction_user`,
  `link_check_user`, and `starter` (a missing `entities` list, a missing
  `confidence`, ...).
- `PREVIEW_VALUES` — the small fixed sample values the studio previews with.
- `PromptLibrary(path=None, defaults=None)` — `names()`, `text(name)`,
  `is_default(name)`, `fields(name)`, `required(name)`, `digest(name)` (12 hex
  characters, for run reports), `describe(name=None)` (the record the editor
  uses), `validate(name, text)` (an error string or None), `advice(name, text)`,
  `render(name, values)`, `set(name, text)`, `reset(name)` (True when there
  was an override to drop). Overrides live in
  `{"version": 1, "prompts": {...}}`; a corrupt file, or a stored template that
  no longer validates, is ignored rather than fatal; writes are atomic
  (`<file>.tmp` + `os.replace`) and only non-default entries are stored.
- `DEFAULT_FILE = "prompts.local.json"` — git-ignored, and the file sits next to
  the dataset it belongs to.
- Module helpers for callers without a library: `render`, `describe`, `digest`,
  and `DEFAULT_LIBRARY`.
- `ValueError` for a template that cannot be rendered (a missing value or an
  invalid placeholder) and `KeyError` for an unknown prompt name.
- The run configuration records the `extraction_system` and `extraction_user`
  digests (plus `schema_sha256`); the `link_check_user` digest is not
  recorded.

### 4.29 `graph_scope.py` — the relevant subgraph for one question

Read-only. Turns one topic text into a small, deterministic subgraph, with three
faces: TriG for a viewer, a view directive for a frontend, and compact lines for
a model. Constants: `MAX_TRIPLES = 300`, `MAX_TOKENS = 6000` (the token ceiling
for one question's subgraph, overridable per question), `MAX_FOCUS = 20`,
`MAX_NAMES = 60`, `SCOPE_GRAPH` (`.../graphs/scope`),
`SCOPE_FILE = "scope.trig"`, `DECLARATION_PREDICATES`, `DEFAULT_LIMITS`
(`{triples, focus, tokens}`; the `tokens` entry is not read — rendering uses
`budget or MAX_TOKENS`).

- `select(text, graph, carry_over=(), limits=None)` → `Scope`. It reuses
  `task_context.build_task_context` for relevance, so the same read-only
  selection extraction uses decides what a question is about; then it collects
  the statements around the matched resources.
- `_focus(matched, carry_over, graph, limit)` — the resources to expand: what
  matched now, else what the conversation was about, newest first.
- `loose_matches(text, graph, limit)` — the one bounded fallback when the strict
  layer matched nothing: the question's words (with `_word_forms`, so
  "countries" also tries "country") are looked up in the labels of everything
  the graph names; a word that matches a class brings that class's instances
  (`_instances_of`, direct and one `rdfs:subClassOf` level down) and, if there
  are none, the class itself. `focus_source` becomes `loose` when this was used,
  and `diagnostics["loose"]` says so. Without it, "what tools does the library
  have?" found nothing while the graph had a class labelled "Tool".
- `_collect(graph, nodes, context, limit)` — three passes: each focus node gets
  a fair share first (`per_node`, with a slice reserved for declarations), then
  the declarations and labels of everything mentioned, then the remainder. A
  well-connected node therefore cannot push the schema out of the scope.
- `_statements(graph, node)` — a node's statements in a stable and useful order:
  `rdf:type` and labels first, then the rest, then what points at the node.
- `Scope` — frozen dataclass with `question`, `nodes`, `triples`, `dropped`,
  `focus_source` (`matched` / `loose` / `carried` / `empty`), `diagnostics`, and
  the three faces: `trig_text()` (one named graph), `view(file_name=SCOPE_FILE)`
  (`{replace: [file_name], files, mode: "instances", clearFilters: true,
  hideIsolated: false, focus}`), and `render_for_model(budget=None,
  graph=None)`; plus `summary()` → `{question, nodes, triples, dropped,
  focus_source, diagnostics}`.
- `render_for_model` writes two blocks before the statements, both charged to
  the budget first: `PREFIXES` (from `_namespace_map`, so a model can write an
  edit proposal with real IRIs) and `NAMES` (`_header`, one quoted label per
  name, at most `MAX_NAMES`). The statements below use
  `statement(triple, prefixes)`: `a` for `rdf:type`, prefixed names, whole
  triples dropped when the budget runs out. It returns
  `{text, triples, dropped, tokens, named, names_dropped, prefixes}`.
  Repeating a full IRI and a label on every line used to cost about three
  quarters of the ceiling: on the reference graph the old renderer fitted 43 of
  199 triples at 2500 tokens, the compact one fits 69, and all 199 by 6000.
- `_namespace_map(triples, graph)` names only the namespaces these triples use:
  the graph's own prefix where it has a real one, a name derived from the
  namespace (`.../geo#` -> `geo`) when rdflib auto-bound `ns1`, and `ns1`,
  `ns2`... only as a last resort. Collisions are resolved among the rendered
  namespaces only, so an unrelated default binding cannot force `ns1`.
- `describe(triple, graph)` / `_term` / `label_of` / `_short` — the line
  renderer: qnames plus the preferred label where there is one.
- `parse_trig(text)` — reads a scope document back to one graph (tests,
  frontends that check what they were sent).

### 4.30 `graph_chat.py` — one conversation about the graph

Talking is a turn: select the relevant subgraph, render it, send the question
with a little history, remember the answer *and* the subgraph behind it. Asking
is injected, so this module never touches a network. Constants:
`HISTORY_TURNS = 6`, `MAX_TURNS = 200`, `TRANSCRIPT_VIEWS = 20`,
`MAX_FOCUS = graph_scope.DEFAULT_LIMITS["focus"]` (20).

- `Turn(role, text, scope, index, view)` — one thing said; `role` is `you` or
  `graph`, `scope` is the summary (for an answer it also carries `rendered`, how
  many triples reached the model, and `dropped_for_space`), `view` the directive
  that draws it. `ask` returns `{answer, scope, summary}` so a frontend can show
  both the subgraph and how much of it was sent.
- `ChatSession(library=None, history_turns=6, turns=(), focus=())` —
  `transcript()` (the newest `TRANSCRIPT_VIEWS` turns also carry their `view`,
  so a long conversation does not grow without bound), `recent()` (the last few
  turns for the prompt), `state()`, `reset()`, and
  `ask(message, graph, ask, limits=None, budget=None, on_step=None)`.
  `on_step(scope, rendered)` is called after selection so a frontend can show
  what is about to be sent.
- `_remember(scope)` — the focus for the next question: the newest matched
  resources first, then what was already being discussed, bounded by `MAX_FOCUS`.
- `chat_prompt(question, scope, history, graph=None, library=None,
  budget=None)` — the exact
  prompt one turn would send, for a preview or a test.

### 4.31 `graph_edit.py` — change the graph by hand, or from a proposal

An edit is a patch written the way a person writes Turtle: additions are plain
statements, removals are the same statement on a line that starts with `- `.
Parsing alone never applies anything: `preview` parses and checks and returns a
stable `patch_id`, and `apply` writes exactly the triples that were previewed.
Constants: `EDIT_BASE` (`TRACE + "edit/"` =
`http://example.org/text-ontology/trace/edit/`), `REMOVAL = "-"`,
`PREVIEW_LIMIT = 40`, `VOCABULARY_TYPES`, `SYSTEM_NAMESPACES`.

- `parse_patch(text)` → `(added, removed, errors)`. Prefix declarations are
  shared: they are read once from the top of the patch and prepended to every
  removal line, so a removal reads like the statement it deletes. Comments and
  blank lines are ignored; a removal without a full stop is still read.
- `check_patch(graph, added, removed, allow_new_vocabulary=False, shapes=())`
  → `(errors, warnings, proposed)`. It reports: a removal that is not in the
  graph (warning — the target state is still reached); new class or property
  declarations (error unless `allow_new_vocabulary`); statements that use a
  class or property nothing declares (error while the vocabulary is frozen, a
  warning when it is open, since a patch's own declarations count as declared);
  an IRI that would be both a class and a property (error); and SHACL violations
  in the proposed data graph (warning: a hand edit is the author's call, but
  they should see what the shapes say).
- `preview(graph, text, source="hand", allow_new_vocabulary=False, shapes=())`
  → `Patch`. `Patch.counts()`, `Patch.sample(limit)` (both sides of the diff),
  `Patch.summary()` (the plain record an operation returns).
- `publication(store, names, patch)` → `(Publication, evidence)`: the target and
  provenance graphs only, so the schema, shapes, and review graphs are never
  touched by an edit. A removed relation or fact also loses its
  `src:statement` node (`publication_sources.forget_statement`).
- `provenance_for(patch, edit_iri=None)` → `(edit_iri, evidence)`, all of it
  under `trace:`: one `prov:Activity` per patch (`trace:edit/<patch_id>`,
  labelled, with `trace:editSource`, `trace:editAdded`, `trace:editRemoved`)
  and one `rdf:Statement` + `prov:Entity` per added or removed triple at
  `trace:edit/<patch_id>/added|removed/<20-hex digest>`
  (`prov:wasGeneratedBy` / `prov:wasInvalidatedBy`).
- `fenced_turtle(text)` — every ```turtle / ```trig / bare ``` block of an
  answer, in order; this is how a chat answer's proposal is found.
- `data_turtle(graph, limit=None)` — the editable part of the graph as Turtle
  with its prefixes (`limit` is accepted but not used).

### 4.32 `workspace.py` — the application state and its long jobs

The backend state for one dataset, with no HTTP and no argument parsing.

- `Progress` — the one job a frontend polls: `claim(label)` takes the single
  job slot (returns `None` when a job already runs), `update(percent, detail)`
  moves the bar, `finish(result)` stores the answer, `snapshot(job_id)` returns
  `{ok, job_id, running, label, detail, percent, result}` where `result` is
  filled in only for the job id that asked (so a reloaded or stale page cannot
  pick up an earlier run's answer). `running_now` is the test helper.
- `_CountingExtractor(extractor, on_call)` — wraps the extractor so the starter
  job can say which model call (and repair attempt) it is waiting for.
- `_ProgressReporter(stream, file_name, file_number, files_total, progress)` —
  a `RunReporter` subclass: the ordinary run log plus one progress step per
  checkpoint (`source_started`, `document_staging`, `window_started`,
  `model_replied`, `window_admitted`, `saved`). The pipeline runs once per file
  and therefore always reports "1 of 1", so the workspace supplies the real
  file number and count; `_percent(within_file)` makes the bar span the whole
  drop. Note: `model_replied` always reports half of the current file's
  share, so for a document with 3 or more windows the bar steps back on a
  late window's reply (the docstring promises it never moves backwards).
- `Workspace(graph_path="ontology.trig", sources_dir="sources/inbox",
  model=None, names=None, extractor=None, prompts_path=None)` — `prompts` is
  the `PromptLibrary` for this dataset (default
  `<graph_path>.parent/prompts.local.json`), `extractor_for_run()` returns an
  injected extractor unchanged or builds an `OpenRouterExtractor` with the
  current `extraction_system` text, and the prompt methods `prompt_list()`,
  `prompt_save(name, text)`, `prompt_reset(name)`, `prompt_preview(name)` back
  the four `prompts.*` operations (an unknown name answers
  `{ok: false, error}`, never an exception).
  Reading: `canonical_graph()`
  (schema + configured data + target), `triple_count()`, `source_names()`,
  `require_dataset()` (`require_named_graphs`, §4.2), `status()` (`{ok, error,
  graph, triples, ready, classes, relations, facts, sources}`; `error` is the
  `PlainRdfError` message or None), `seed_graph()` (the seed view, §4.25),
  `dataset_text(view="seed")` (calls `require_dataset()`; `"seed"` → the seed
  graphs, `"all"` → every role graph including provenance and review, one
  TriG text with prefixes bound; anything else is `ValueError`),
  `progress_state(job_id)`.
  Writing: `reset()` (unlink the graph file, then every file under the inbox
  recursively and the folders left empty, deepest first, then re-open an
  empty store; `_check_reset_target` refuses when the inbox is the working
  directory, one of its parents, or the dataset's own directory),
  `create_starter(text, progress=None)` (propose + publish on this
  workspace's store with its prompt library, reporting model calls and the
  write step when a `progress` is given), `edit_current()` (`{ok, turtle,
  bytes, triples}` for the target data graph),
  `edit_preview(text, allow_new_vocabulary=False, source="hand")` (check a
  patch against `canonical_graph()` and the shape graphs and remember exactly
  what applying it would do; `self.edits` keeps only the latest checked
  `Patch`, under its `patch_id`), `edit_apply(patch_id)` (write exactly those
  triples, with PROV evidence, answering `{ok, evidence, log, status,
  turtle}`), `_with_proposals(turns)` (check any Turtle block in a chat answer
  and attach it as an unapplied proposal; called by `chat_ask` and
  `chat_state`), `chat_state()`, `chat_reset()`, `chat_ask(message,
  on_step=None, budget=None)` (calls `require_dataset()`; one turn over
  `seed_graph()`, answering `{ok, answer, scope: {..., view}, turns}`),
  `start_chat(message, budget=None)` and `_chat_job` (the same turn as the
  one background job, so the page gets the progress bar: 10 % "selecting the
  relevant subgraph", then 40 % "... asking the model"),
  `ask_text(prompt, system=None)` (a prose answer from the extractor, never
  JSON),
  `import_starter(name, text)` (parse an RDF document and publish it
  as the starter vocabulary in one write, answering
  `{ok, summary, log, status}` or `{ok: false, error}`),
  `ingest(files, log, progress=None)` (calls `require_dataset()`, skips blank
  texts, writes each dropped text into the inbox, then runs the pipeline once
  per file with `MergeConfig(require_declared_vocabulary=True)`,
  `source_root=self.sources_dir`, and `prompts=self.prompts`, reporting into
  `log` and moving the bar per file and window; returns the saved names
  relative to the inbox), `_write_source(name, text)` (keeps the dropped
  folder structure, cleans each part with `_safe_part`, never leaves the
  inbox, never overwrites: a clash becomes `notes.md-2`, `-3`, ...), and the
  two job launchers a transport uses:
  `start_starter(text)` / `start_ingest(files)` claim the slot, run the work in
  a daemon thread, and return the job id (or `None` when one is already
  running).
- Module constants: `DEFAULT_GRAPH = Path("ontology.trig")`,
  `DEFAULT_SOURCES = Path("sources/inbox")`.

### 4.33 `operations.py` — every capability as one named operation

The contract between a frontend and the backend: one registry of names, each
mapping to a small function `(workspace, payload) -> plain JSON record`. No
HTTP, no objects, no browser.

- `Operation(name, summary, handler, args=(), background=False)` — one
  capability and the metadata published to clients.
- `OPERATIONS` (tuple) / `REGISTRY` (name → operation). Adding a capability is
  one function plus one `Operation(...)` line; the transport never changes.
- `describe()` — the published manifest: name, summary, argument names, and
  whether it answers with a `job_id` instead of a result.
- `call(workspace, name, payload=None)` — run one operation; an unregistered
  name raises `UnknownOperation` (a `KeyError` subclass).
- The registry today (18): `status`, `dataset` (optional `view` = `seed` |
  `all`, answering `{ok, trig, view, name}`; `view` is read but not listed in
  `args`), `progress` (`job`), `reset`, `operations.list`, `starter.create`
  (`text`, background), `starter.import` (`name`, `text`), `ingest`
  (`files`, background), `chat.ask` (`message`, `budget`, background),
  `chat.state`, `chat.reset`, `edit.current`, `edit.preview` (`text`,
  `allow_new_vocabulary`), `edit.apply` (`patch_id`), `prompts.list`,
  `prompts.save` (`name`, `text`), `prompts.reset` (`name`),
  `prompts.preview` (`name`). There is no health operation.
- Payload helpers: `_started(workspace, job)` (the background answer, or the
  "a job is already running" refusal), `_integer`, `_truthy`, `_files`.

### 4.34 `studio.py` — the HTTP transport (and the page it serves)

Carries things and nothing else: no state, no domain logic.

- Constants: `PAGE_NAME = "frontend/triple-lens.html"`, `DEFAULT_PORT = 8765`,
  `ASSET_TYPES`.
- `find_page(explicit=None)` — the `frontend/triple-lens.html` page: the given
  path, then the working directory, then the repository root next to the
  package.
- `Assets(page=None)` — the files served: the page itself, plus `studio.js` and
  `studio.css` from the same `frontend/` directory. `body(path)` returns `(bytes,
  content_type)` for `/`, `/index.html`, and sibling files whose suffix is in
  `ASSET_TYPES` (`.js`, `.css`); anything else returns `(None, None)`, so path
  traversal or arbitrary files are refused.
- `StudioHandler` — a generic dispatcher, not a list of endpoints:
  `GET /` and the assets; `GET /api/op/<name>?arg=value` for read operations;
  `POST /api/op/<name>` with a JSON body for the rest. An unknown operation
  (or any other `/api/...` path) is a 404; an operation that raises
  `RuntimeError`, `OSError`, `ValueError`, or `KeyError` answers `{ok: false,
  error: "<Type>: message"}` with HTTP 200 so a page can show the message
  (other exception types are not caught).
- `StudioServer(ThreadingHTTPServer)` — `daemon_threads = True`,
  `allow_reuse_address = True`; threading
  exists only so a page can poll while a job runs, while the `Progress` slot in
  the workspace keeps graph writes strictly serial (one job at a time).
- `create_server(workspace, host="127.0.0.1", port=8765, tries=10, assets=None)`
  — a `StudioServer` with the workspace and assets bound to a handler subclass;
  a taken port falls through to the next free one (`port=0` binds any free
  port), and `main` prints the `server_address` it actually got, plus the
  manifest URL. A missing page is `Error: ...` and exit 1.
- `build_parser()` / `main(argv)` — `text-to-ontology-studio [--graph]
  [--sources] [--page] [--host] [--port] [--model] [--reset] [--no-browser]`;
  `--reset` cleans up and exits, otherwise it serves and prints the URL.

### 4.35 The frontend split

The page is the visualization; the studio frontend is a separate file that the
page loads only when it is served over HTTP. All three files live in
`frontend/`, apart from the Python package. §1.1 has the full ownership map;
this section is the file-level detail of the frontend half.

- `frontend/triple-lens.html` — the viewer: parsing, layout, details, filters,
  and the **view API** the studio frontend is allowed to use:
  `window.__lens.applyView(view)`, `clearFiles(names)`, `fileNames()`, plus the
  pre-existing `S`, `addText`, `afterLoad`, `setMode`, `tick`, `draw`. A view
  is one declarative record: `{replace, files: [{name, trig}], mode, focus,
  filters: {defId: [keys]}, hideIsolated, clearFilters, resetFilters}`; the lens
  resolves names to nodes and keys to filters itself. `resetFilters` says "this
  is a fresh set of files", so a small scope does not inherit the hiding a big
  dataset needed (the lens re-picks its own defaults). The page also owns the
  `#workspace` flex layout, so it renders standalone. Its
  `FILTER_NAMESPACE_FAMILIES` list groups IRIs into one filter entry per
  family: every `trace:` IRI (`/text-ontology/trace/`) is one entry and every
  `src:` IRI (`/text-ontology/source/`) another; the older families
  (`/review/`, `/candidate/`, `/source-file/`, ...) are kept for datasets made
  before the split.
- `frontend/studio.js` — the studio frontend: builds its own markup, talks
  only through named operations (`api/op/<name>`), and changes the picture only
  through the view API. It contains no domain logic, so a new backend
  capability needs only a new button here. It adds three things to the page:
  - a **studio row** in the top bar (`#studiobar`, under the lens's own row):
    the dataset status (file name, triples, sources), the view switch
    (`#stView`: **Seed ontology** / **Everything**, which calls `dataset
    {view}`, names the file `*.seed.trig` or `*.trig`, and applies it with
    `{replace: true, files, resetFilters: true}`), then one button per
    action — **Starter ontology…**, **Add sources…**, **Prompts…**, **Edit the
    graph…** — then **Clear view**, **Reset everything**, the last line the
    studio said (click it for the log), and **Log**; the progress bar for a
    long job sits directly under the row;
  - one **dialog** per action (`<dialog>` elements appended to the body):
    Starter ontology (description box, Create, an RDF/Turtle/TriG drop zone and
    file picker for import, the vocabulary in force), Add sources (a drop zone
    and picker that accept whole folders — the relative path,
    `entry.fullPath` / `webkitRelativePath`, is sent as the file name — and
    refuse RDF-looking files, decided in `studio.js` by suffix, with a pointer
    to the starter dialog), Prompts
    (template picker, monospace editor, validation and advice note, Preview,
    Save, Back to default), Edit the graph (loads the Turtle on open; Reload the
    graph, **allow new classes and relations**, Preview changes with a `+`/`-`
    diff and the warnings, then Apply changes — only enabled for the exact
    patch that was previewed), and the Run log;
  - the **conversation column** (`#studio`), which holds nothing but the chat:
    a transcript of bubbles (questions right, answers left with a small mark),
    a welcome message with suggested questions when the thread is empty, a
    "thinking" bubble that shows the job's progress detail while an answer is
    prepared, and a composer where Enter sends and Shift+Enter breaks a line.
    Each answer's footer says how many triples were selected, how many were
    beyond the limit, how many reached the model, and the focus, with **Show
    the subgraph** (replaces the canvas with exactly those triples, focused)
    and **With the full graph**; while a subgraph is on the canvas, **Show the
    full graph again** and **Export subgraph** appear above the composer. Export
    downloads the answer's stored TriG scope, including nodes outside the
    canvas's one-node focus. The options under the
    composer are the subgraph size (compact 2500 / normal 6000, the default /
    wide 12000 tokens, sent as `chat.ask {budget}`) and the "show the subgraph
    after each answer" checkbox (on by default); **New conversation** in the
    column's header forgets the thread, and a collapse button (`#stCollapse`)
    folds the column. A chat answer that contains a Turtle block also
    shows `proposed change: +N −M` with **Apply this patch**, which goes
    through the same preview id. A failed question stays in the transcript
    above the error bubble.
- `frontend/studio.css` — the studio frontend's styles, injected as a
  `<link>` by the loader in the page when it is not opened from `file://`.

### 4.36 The viewer — `view_ontology.py`, `view_report.py`, `view_html.py`

Read-only: the viewer never writes to a graph; only `--html` writes a file.

- `view_ontology.py` — `load_view_graph(path, name=None)`: a non-`.trig` path
  goes through `graph_management.open_graph`; a `.trig` path is wrapped in
  `ReadOnlyGraphStore(RdflibGraphStore(...))` and returns the union of all
  named graphs, or only graph `name`. Terminal reporters `report_partitions`,
  `report_skeleton_help`, `report_skeleton`, `report_patterns`, `label`.
  `main()` (no argv parameter): `[graph=ontology.trig] [-g/--named GRAPH]
  [-html/--html [FILE=ontology_views.html]]`.
- `view_report.py` — the views as plain data (no HTML, no writes).
  Constants `METATYPES`, `EVENT_FIELDS`; helpers `prefix_table`, `shorten`,
  `describe`, `triple_rows`, `class_entries`, `property_entries`,
  `skeleton_section`, `pattern_rows`, `instance_cards`, `shape_entries`,
  `event_entries`, `candidate_entries`, `header_rows`.
  `build_report(path, graph, views)` → `{graph: {path, triples, generated,
  counts, partitioned, prefixes}, triples, skeleton, patterns, instances,
  support: {events, candidates, shapes, header}}`.
- `view_html.py` — one self-contained page, no external assets.
  `PAGE_STYLE`, `PAGE_SCRIPT`, `escape`, `pipeline_diagram`, one
  `*_section(report)` per section (head, prefix, pipeline, partitions,
  skeleton, patterns, instances, support, controls, glossary);
  `render_page(report)` embeds the report as JSON with `</` escaped;
  `write_report(path, graph, views, destination)` writes the page and returns
  `destination`.

### 4.37 Root scripts

- `ontology.py` / `view_ontology.py` — compatibility wrappers: insert `src/`
  into `sys.path`, then call `text_to_ontology.cli:main` /
  `text_to_ontology.view_ontology:main` (the viewer wrapper turns an
  `OSError` into exit 1).
- `ttl_to_trig.py SOURCE OUTPUT [--force] [--concepts-as-classes]` — turns a
  plain RDF file into a role-split TriG dataset through
  `starter.import_publication` (keeping the file's own IRIs). It refuses
  SOURCE == OUTPUT, an existing OUTPUT without `--force`, and a file with no
  classes or properties. `--concepts-as-classes` (`concepts_as_classes(graph)`,
  `with_concepts_as_classes(text, name)`) also declares every `skos:Concept`
  an `owl:Class`, turns `skos:broader` into `rdfs:subClassOf`, and fills
  `rdfs:label` from `skos:prefLabel` and `rdfs:comment` from
  `dct:description` (else `skos:definition`). Unlike the two wrappers it has
  no `sys.path` shim, so the package must be installed (`pip install -e .`).
- `migrate_prefixes.py SOURCE OUTPUT [--keep-candidates]` — rewrites a
  dataset made before the `src:`/`trace:` split (§7.1) into a new file:
  entities with `onto:sourceFile` get `src:fromFile` to one `src:file/<hash
  of path>` node per path, published relations/facts get `src:statement`
  nodes (all in the data graph); candidates, windows, documents, review
  records, merge audit, provisional, staging, and edits move under `trace:`
  (old `onto:` tracing predicates and types too); the old
  `onto:statement/...` and `onto:source-file/...` records in provenance are
  dropped. The per-window candidate evidence (`candidate/`, `window/`,
  `activity/`, `agent/`, `metric/`) is dropped unless `--keep-candidates`,
  the same as a run without `--trace`. It refuses SOURCE == OUTPUT and an
  existing OUTPUT, and has a `sys.path` shim. `migrate(store, names,
  keep_candidates=False)` → `{graph name: Graph}`, read-only. On
  `ontology_bckp.trig` it gives 56 101 → 3 973 triples (47 466 with
  `--keep-candidates`); the health report and the seed view are identical
  before and after.
- `trig_to_ttl.py FILE.trig [...]` — writes the hard-coded target data graph
  (`.../graphs/data`) of each file to `<same name>.ttl`, overwriting it
  (`export_data_graph(trig_path)`; `main` returns 2 without arguments).

---

## 5. Module reference (read-only derivation and context layers)

None of these modules writes to a graph. They are reached by the pipeline
through `task_context.build_task_context()` and
`context_render.prepare_prompt_context()` (and, for one window,
`source_staging.layered_context_text()`), and by the viewer through
`ontology_views.build_ontology_views()`.

### 5.1 `graph_partition.py` — split one graph into 3 views

Imports (rdflib only). Constants: `SCHEMA_TYPES`, `TRACE_NAMESPACE` /
`SOURCE_NAMESPACE` (the `trace:` / `src:` strings, restated so the module
depends on rdflib only), `AUDIT_TYPES` (`trace:ExtractionEvent`,
`trace:MergeCandidate`), `SUPPORT_TYPES`
(`OWL.Ontology`, `SH.NodeShape`, `SH.PropertyShape`), `SCHEMA_AXIOMS`,
`ANNOTATIONS`, `RESTRICTION_TARGETS`.

- `owned_nodes / support_roles / restriction_roles / schema_roles /
  instance_roles` — role sets.
- `choose_view(triple, ...)` — priority: a predicate in `trace:` or `src:`, or
  a subject in `src:` → support (a `trace:` *subject* alone is **not**
  enough: a staging graph's provisional entities are `trace:provisional/...`
  and must stay instances for later windows); subject
  or object in support → support; opaque blank nodes → support; `rdf:type`
  schema/instance; restrictions → schema; schema axioms; annotations follow
  their subject's role; default = instance if the subject is an instance role
  else support.
- `partition_graph(source_graph)` → `(schema, instance, support)`, lossless and
  disjoint, inputs never mutated.

### 5.2 `graph_skeleton.py` — compact declared structural core

`supported_restriction`, `structural_triples`,
`create_graph_skeleton(schema_graph)` → explicit classes/object/datatype
properties, named subclass/domain/range axioms, labels, and only complete
supported restrictions (six forms). No inference; skeleton ⊆ schema input.

### 5.3 `graph_patterns.py` — empirical usage patterns

`eligible` (excludes `onto:kind` and RDF/RDFS/OWL/SH/SKOS
namespaces), `usable_classes` (most-specific explicit types), `object_ranges`,
`class_populations`, `observed_relationships(schema_graph, instance_graph)` →
sorted pattern records with occurrences/distinct subjects/population/coverage/
cardinality. Observations only; never written back.

### 5.4 `ontology_views.py` — the five views as one record

`build_ontology_views(source_graph)` → `{schema, instance, support, skeleton,
patterns}` (three partitions + skeleton from schema + patterns from
schema+instance).

### 5.5 `source_concepts.py` — what one text mentions

No rdflib, no `llm` (asserted by tests). Constants: `MAX_CHARACTERS = 200_000`,
`MAX_TOKENS = 5_000`, `MAX_CONCEPTS = 40`, `MAX_PHRASE_TOKENS = 3`,
`MAX_MENTION_TOKENS = 4`, `MAX_MATCH_TOKENS = 6`, `MIN_TOKEN_CHARACTERS = 2`,
`HEADING_CHARACTERS = 80`, `EARLY_CHARACTERS = 400`; weights: mention 3.0 /
phrase 2.0 / keyword 1.0, heading +2.0, repeat +0.5 each capped 3.0, early
+1.0.

- `normalize(text)` — NFKC, case folded, words single-spaced (Unicode
  preserving, unlike `entity_lookup.identity_key`).
- `extract_source_concepts(text)` → `list[{"text", "normalized", "kind",
  "weight", "origin", "position"}]`, sorted by `(-weight, position,
  normalized)`, capped at `MAX_CONCEPTS`. `kind` ∈ mention|phrase|keyword;
  `origin` ∈ heading|capitalized-span|frequency.
- `text_phrases(text, longest)` → normalized word-run → first position index.
- `same_word_stem(first, second)` / `same_name_stem(first, second)` — two
  words (or names, word by word) are the same word up to an inflected ending:
  `MIN_STEM_CHARACTERS = 5`, `MAX_ENDING_CHARACTERS = 2`. Used by
  `task_context` (inflected name match), `entity_lookup` (inflected-form
  review), and `graph_health` (duplicate suspects).

### 5.6 `task_context.py` — select the context one source needs

`DEFAULT_LIMITS`: classes 12, properties 16, restrictions
8, patterns 20, resources 15, examples 12, hierarchy_hops 1, instance_hops 1,
match_tokens 8, overlap_tokens 2, concepts 40, direct_matches 40. Tiers 1–8
(`DIRECT_NAME` → `INDIRECT`); relevance outranks frequency; all bounded
expansion with visited sets (cycles terminate). Returns a `ContextPackage`
{concepts, schema, patterns, resources, examples, labels, diagnostics}.
`build_task_context(text, source_graph, limits=None)` composes views +
concepts + `entity_catalog` and calls `select_task_context(text, concepts,
ontology_views, native_entities=None, limits=None)`. When no exact phrase or
concept matches a name, `stem_index` / `inflected_match` try
`same_name_stem` and record a `CONCEPT`-tier "inflected name match".
`local_name` is shared with the viewer and `run_report`.

### 5.7 `context_render.py` — render, assemble, budget

`render_context_items(package, namespace_manager=None)`
(items with section/priority/text/dependencies; sections declared / observed /
resources / examples), `assemble_context(rendered_items)` (fixed order, empty
sections omitted), `allowance(budget_config)` (context_tokens ceiling and/or
total-limit arithmetic; the smaller wins; raises `KeyError` when neither),
`assembly_overhead(...)` (headings + line breaks charged before packing),
`prepare_prompt_context(package, budget_config, count_tokens=estimate_tokens)`
→ `{text, budget, existing_ids}`. Rendering keeps declared vs observed apart;
datatype properties point at literals; unknown ranges stay `unknown`; only the
six supported restrictions get words, anything else renders as compact RDF;
native resources show `id:`, generic show `uri:` + "not usable as existing_id";
graph text is cleaned/defused/truncated (`MAX_FIELD_CHARACTERS = 240`,
`TRUNCATION_MARKER`, `GENERIC_NOTE`).

### 5.8 `prompt_budget.py` — estimate, allowance, packing

`PROMPT_BUDGET`: `total_limit 30_000`, `context_tokens 1_400`,
`schema_tokens 3_000` (the cap on the data-only core schema, §4.22),
`fixed_prompt_tokens 400`, `output_reserve 4_000`, `safety_margin 500`;
`DEFAULT_CHARS_PER_TOKEN = 3`.
`estimate_tokens`, `context_allowance` (clamped ≥ 0), `fit_context_items`
(with dependency bundles, never slices; `dropped_ids` names the dropped whole
items).

---

## 6. Data contracts & return types (quick reference)

| Module | Function | Return |
|---|---|---|
| `windowing` | `make_source_document(name, raw_text, ...)` | `SourceDocument` (`doc-<sha[:16]>`) |
| `windowing` | `plan_windows(document, config)` | `list[TextWindow]` ([] for blank) |
| `source_staging` | `layered_context_text(canonical, source, budget, count_tokens)` | `{text, budget, existing_ids}` |
| `source_staging` | `plan_window_admission(source_graph, candidates, provenance, doc_id, conf)` | MergePlan (provisional URIs) |
| `repair` | `extract_validated(extractor, prompt, validate, max_repair_attempts)` | `ExtractionOutcome` (`.ok`) |
| `candidate_graph` | `build_candidate_graph(...)` | deterministic candidate `Graph` (PROV/DQV) |
| `source_reconciliation` | `reconcile_document(doc_id, source_graph, candidate_graphs, plans)` | plain report dict |
| `source_reconciliation` | `build_source_artifact(document, source_graph, windowing, models)` | `SourceGraphArtifact` |
| `source_validation` | `validate_source_graph(source_graph, shapes)` | `SourceValidationResult` |
| `document_merge` | `plan_document_merge(canonical_graph, document, packages, plans, conf, planner)` | document merge dict + `merge_plan` |
| `document_publication` | `compile_document_publication(document, merge, candidates, packages, plans, roles, names, shapes, trace=False)` | `DocumentPublicationPlan` |
| `graph_store` | `RdflibGraphStore.publish(publication)` | atomic TriG persistence |
| `merge_policy` | `plan_graph_merge(graph, candidates, provenance, ...)` | MergePlan (see 4.13) |
| `entity_lookup` | `identity_decision(entity, catalog, ...)` | `{local_id, status, uri, method, identity_score, suggestions, reason_codes}` |
| `candidate_validation` | `validate_candidates(data, graph, allowed_existing_ids=(), vocabulary=None)` | plain dict `{valid, candidates\|None, issues, counts}` |
| `candidate_validation` | `drop_endpoint_mismatches(data, validation)` | `(kept_data, {records, messages})`, or `None` if any other error remains |
| `graph_store` | `require_named_graphs(store, path=None)` | nothing, or raises `PlainRdfError` |
| `graph_store` | `unnamed_triples(store)` | int (triples in the default graph) |
| `schema_context` | `render_core_schema(graph)` | the core schema text |
| `schema_context` | `schema_digest(schema_graphs)` | 12 hex characters |
| `document_context` | `render_document_header(display_path, document_text, window, total)` | header text |
| `document_context` | `document_anchors(source_graph, vocabulary, limit=8)` | list of entity IRIs |
| `document_context` | `render_document_anchors(source_graph, vocabulary)` / `render_folder_anchors(graph, entities)` | block text, or `""` |
| `document_context` | `folder_anchors(graph, sources, vocabulary, source_path, limit=5)` | list of canonical entity IRIs (`sources` = the data graph) |
| `seed_view` | `seed_graphs(roles, names)` / `store_roles(store, names)` | `{graph name: Graph}` |
| `seed_view` | `seed_view(roles, names)` | one `Graph` |
| `link_check` | `expected_links(shapes_graph)` | sorted `[{class, relation, question}]` |
| `link_check` | `add_expected_link(store, class_name, relation_name, question, names)` | the shapes graph (published), or `ValueError` |
| `link_check` | `find_gaps(source_graph, canonical, expected, vocabulary, limit)` | `[{entity, class, relation, question}]` |
| `link_check` | `check_document_links(...)` | `(packages, {gaps, filled, not_established, dropped})` |
| `graph_health` | `health_report(graph_path, sources=None, gold_path=None)` | plain dict |
| `graph_health` | `format_report(report, limit=20)` | short text |
| `prompts` | `PromptLibrary(path).render(name, values)` | the finished prompt text |
| `prompts` | `PromptLibrary(path).set(name, text)` | an error string, or None when stored |
| `prompts` | `PromptLibrary(path).describe()` | `[{name, text, default, required, fields, error, advice}]` |
| `vocabulary` | `read_vocabulary(graph)` | `Vocabulary` (declared classes/relations/facts) |
| `starter` | `validate_starter(data)` | `{valid, candidates, issues, counts}` |
| `starter` | `starter_publication(proposal, names)` | one `Publication` (five roles) |
| `starter` | `create_starter(text, graph_path, extractor, names)` | the proposal (already published) |
| `starter` | `looks_like_rdf(name, text)` | True when a dropped file is RDF |
| `starter` | `parse_rdf(text, name)` | `(format, graph or Dataset)`, or `ValueError` |
| `starter` | `import_publication(text, name, names)` | `(Publication, summary)` |
| `starter` | `import_starter(text, name, graph_path, names)` | the summary (already published) |
| `vocabulary` | `Vocabulary.class_iri(kind)` / `relation_iri(p)` / `fact_iri(p)` | the declared IRI, or the generated one |
| `graph_scope` | `select(text, graph, carry_over, limits)` | `Scope` (triples + view + model text) |
| `graph_scope` | `Scope.view(file_name)` | the directive a frontend applies |
| `graph_chat` | `ChatSession.ask(message, graph, ask, ...)` | `{answer, scope, summary}` (and two new turns) |
| `graph_chat` | `ChatSession.transcript()` | `[{role, text, scope, index, view}]` |
| `graph_edit` | `preview(graph, text, source, allow_new_vocabulary, shapes)` | `Patch` (triples, errors, warnings, `patch_id`) |
| `graph_edit` | `parse_patch(text)` | `(added, removed, errors)` |
| `graph_edit` | `publication(store, names, patch)` | `(Publication, evidence)` — target and provenance only |
| `graph_edit` | `fenced_turtle(answer)` | the Turtle blocks of an answer |
| `graph_edit` | `data_turtle(graph)` | the editable graph as Turtle |
| `workspace` | `Workspace.status()` | `{ok, error, graph, triples, ready, classes, relations, facts, sources}` |
| `workspace` | `Workspace.ingest(files, log, progress=None)` | list of saved source names (relative to the inbox) |
| `workspace` | `Workspace.dataset_text(view="seed")` | one TriG text (`seed` or `all`), or `ValueError` |
| `workspace` | `Workspace.start_starter(text)` / `start_ingest(files)` | job id, or `None` when a job runs |
| `workspace` | `Workspace.progress.snapshot(job_id)` | `{ok, job_id, running, label, detail, percent, result}` |
| `operations` | `call(workspace, name, payload)` | one plain JSON record (`UnknownOperation` for a bad name) |
| `operations` | `describe()` | `[{name, summary, args, background}]` |
| `studio` | `Assets(page).body(path)` | `(bytes, content_type)` or `(None, None)` |
| `studio` | `create_server(workspace, host, port, tries, assets)` | `StudioServer` (a `ThreadingHTTPServer`) |
| `graph_management` | `is_tracing(triple)` / `is_source_attribution(triple)` | bool (subject or predicate in `trace:` / `src:`) |
| `publication_sources` | `source_attribution(document, merge, canonical)` | new `Graph` of `src:` triples for the data graph |
| `publication_sources` | `trace_sources(document, merge, canonical)` | new `Graph` of `trace:` triples for the provenance graph |
| `publication_sources` | `link_statement_sources(graph, document)` | None (mutates the evidence/review graph) |
| `publication_sources` | `file_uri(document)` / `statement_uri(triple)` / `document_uri(document)` | `src:file/<hash>` / `src:statement/<hash>` / `trace:document/<id>` |
| `publication_sources` | `forget_statement(graph, triple)` | None (removes one `src:statement` node) |
| `migrate_prefixes` (root script) | `migrate(store, names, keep_candidates=False)` | `{graph name: Graph}` in the new layout (read-only) |
| `view_report` | `build_report(path, graph, views)` | plain report dict for the HTML page |
| `view_html` | `write_report(path, graph, views, destination)` | writes one self-contained HTML page, returns `destination` |

---

## 7. RDF dataset model (the named graphs)

- **Roles** (`GraphNames`): `schema` (declared classes/properties), `shapes`
  (SHACL shape graphs), `data` (target canonical data graph, with its `src:`
  source links), `provenance` (`trace:` run tracing), `review` (withheld
  candidates, `trace:` IRIs). The
  `entity:`/`class:`/`relation:`/`fact:` namespaces still name the resources
  inside the data graph (classes and properties keep an imported
  vocabulary's own IRIs, §4.20).
- **Seed** (virtual, via `seed_graph` → `split_legacy_graph`): `onto:ontology`,
  `onto:Entity`, `onto:EntityShape` (targets `onto:Entity`, requires
  `skos:prefLabel` minCount 1). Applied only when a store is wholly fresh.
- **Staging** (never canonical, in-memory per document): a document's source
  graph under `trace:staging/<doc>` and per-window candidate graphs under
  `trace:staging/<doc>/<window>`; entities use `trace:provisional/<doc>/...`
  IRIs.
- **Starter** (via `starter.starter_publication`, one atomic publication):
  `class:<slug>` `owl:Class` (+ label, comment, `rdfs:subClassOf onto:Entity`)
  in the schema graph, `relation:<slug>` `owl:ObjectProperty` and
  `fact:<slug>` `owl:DatatypeProperty` (+ label, comment, domain, range),
  the seed's `onto:Entity` root and `EntityShape`, everything else empty.
  This is the vocabulary data-only ingestion is locked to.
- **Each accepted entity** is typed `onto:Entity`, `owl:NamedIndividual`,
  `skos:Concept`, and its kind class (`class:<Kind>`, or the declared IRI in
  data-only mode); carries `skos:prefLabel`, `rdfs:label`, `onto:kind`,
  optional aliases/comment. The seed view (§4.25) hides the
  `owl:NamedIndividual` / `skos:Concept` types from prompts and the chat.
- **Each relation/fact** becomes `relation:<slug>`
  `owl:ObjectProperty` / `fact:<slug>` `owl:DatatypeProperty` with a label.
  In data-only mode the declarations are not written again: the statement
  itself is the only thing added, and every class/property declaration stays
  exactly as the starter wrote it (the schema and shapes graphs are copied
  through unchanged by every publication).
- **Source links** (data graph, from `publication_sources.source_attribution`):
  one `src:file/<hash of path>` node per source path (`a src:SourceFile`,
  `rdfs:label`, `src:path`); `src:fromFile` on each published entity; one
  `src:statement/<hash>` node (`a rdf:Statement` + subject/predicate/object +
  `src:fromFile`) per published relation/fact. Classes and properties get none.
- **Document records** (provenance graph, always): `trace:document/<id>`
  (`prov:Entity`, label, `trace:sourceFile` → the `src:file` node) and
  `trace:sourceDocument` on each published entity and `src:statement` node.
- **Candidate evidence** (provenance graph, **only with `--trace`**):
  per-record `trace:candidate/...` `prov:Collection` + `rdf:Statement`
  reification + `dqv:QualityMeasurement` (xsd:decimal) + the PROV chain
  (`trace:window/`, `trace:activity/`, `trace:agent/`,
  `trace:metric/extraction-confidence`), with `trace:sourceDocument` /
  `trace:sourceFile` on the statements.
- **Audit** (support partition, via merge policy; written into the in-memory
  staging graph by `apply_merge_plan`, not published by the pipeline; older
  datasets may hold some): `trace:ExtractionEvent` and
  `trace:MergeCandidate` records (`rdf:JSON` normalized candidates, decimal
  confidence, decision reasons; no timestamps, no raw text).
- **Review graph**: withheld identities and assertions as `trace:review/...`
  `prov:Collection` + reified statements + `prov:wasDerivedFrom` the
  `trace:document/` record, which is also written there (from
  `build_review_graph`).
- **Expected links** (shapes graph, via `link_check.add_expected_link`):
  `onto:expected/<class>-<relation>` node shapes with one `sh:minCount 1`,
  `sh:severity sh:Warning` property rule and an `sh:message` question.
- **Hand edits** (provenance graph, via `graph_edit`): one `prov:Activity`
  `trace:edit/<patch_id>` per applied patch plus one `rdf:Statement` per added
  or removed triple under `trace:edit/<patch_id>/added|removed/`.

### 7.1 Prefix families: business data, `src:`, `trace:`

Every IRI the app mints belongs to one of three families (all under
`BASE = http://example.org/text-ontology/`):

| Family | Prefix (namespace) | What it is | Where it lives |
|---|---|---|---|
| Business data | `onto:` `entity:` `class:` `relation:` `fact:` (and an imported vocabulary's own IRIs) | what the texts say | schema, shapes, data graphs |
| Source attribution | `src:` (`.../source/`) | which file said it | data graph, beside the business data |
| Tracing | `trace:` (`.../trace/`) | how the run got there: candidates, windows, activities, agents, metric, documents, review records, merge audit, provisional and staging IRIs, edits | provenance and review graphs (and in-memory staging) |

**The filter rule**: a triple is tracing when its **subject or its predicate**
is in `trace:` (`graph_management.is_tracing`). Dropping every tracing triple
loses no business data and no source link. `src:` triples are recognised the
same way (`is_source_attribution`). The seed view (prompts, chat, studio
`view=seed`) drops both families. Every PROV/DQV triple a run writes has a
`trace:` subject or predicate, so it is tracing too (a test pins this).

A short example of one published relation (data graph first, then provenance):

```turtle
# data graph: business data + src:
entity:acme       a class:client ; skos:prefLabel "Acme" ;
                  relation:uses entity:python ;
                  src:fromFile src:file/9f2c... .
src:file/9f2c...  a src:SourceFile ; rdfs:label "notes.md" ;
                  src:path "client/project/notes.md" .
src:statement/41d0...  a rdf:Statement ;
                  rdf:subject entity:acme ; rdf:predicate relation:uses ;
                  rdf:object entity:python ;
                  src:fromFile src:file/9f2c... .

# provenance graph: tracing
trace:document/doc-1a2b...  a prov:Entity ; rdfs:label "notes.md" ;
                  trace:sourceFile src:file/9f2c... .
entity:acme       trace:sourceDocument trace:document/doc-1a2b... .
src:statement/41d0...  trace:sourceDocument trace:document/doc-1a2b... .
```

The file node is keyed by the **path only**, so an edited file keeps its node;
the document (`doc-<content hash>`) is one version of its content and is
tracing. Without `--trace` a run writes only these document links to the
provenance graph (hand edits add their own `trace:edit/` records); with
`--trace` it also writes the per-window candidate evidence, which is most of a
dataset's size. The data graph is the same either way.
`migrate_prefixes.py` (§4.37) moves an older dataset to this layout.

---

## 8. Cross-module import graph (every package import)

Built from the `from .x import ...` lines of every module.

```
__main__.py ──► cli
cli.py ──► api (RunRequest, run_text_to_graph), graph_management (LocalTurtleStore),
           llm (OpenRouterExtractor), pipeline (ExtractionConfig, MergeConfig, ProcessingConfig),
           run_report (RunReporter, default_report_path)
api.py ──► graph_management, graph_store, document_publication, llm,
           source_reconciliation, source_validation, pipeline (re-exports; no logic)
pipeline.py ──► prompts, candidate_graph, candidate_validation (incl. drop_endpoint_mismatches),
                document_context, graph_management (save_graph), graph_merge,
                graph_store (incl. require_named_graphs), link_check, ingest_sources, llm,
                merge_policy, document_merge, document_publication, prompt_budget, repair,
                run_report, schema_context, seed_view, source_parse, source_staging,
                source_reconciliation, source_validation, task_context, vocabulary, windowing
document_publication.py ──► candidate_graph (provisional_entity_iri),
                            graph_management (TRACE, seed_graph), graph_partition,
                            publication_sources (document_uri, link_statement_sources,
                            source_attribution, trace_sources),
                            graph_store (GraphNames, Publication, RdflibGraphStore),
                            source_validation (embedded_shape_graph, validate_source_graph)
document_merge.py ──► candidate_graph (provisional_entity_iri), graph_merge (slug),
                      merge_policy (build_provenance, canonical_json, plan_graph_merge)
source_staging.py ──► candidate_graph (PROVISIONAL), context_render, merge_policy,
                      graph_management (TRACE), graph_merge, prompt_budget,
                      graph_store (lazy, inside retain_staging)
source_reconciliation.py ──► candidate_graph (CANDIDATE_MAPPING_VERSION, DQV), graph_management
source_validation.py ──► (pySHACL only, imported lazily)
merge_policy.py ──► entity_lookup, graph_management (incl. TRACE), graph_merge
entity_lookup.py ──► graph_management (ONTO), source_concepts (same_name_stem)
graph_merge.py ──► entity_lookup, graph_management
candidate_validation.py ──► candidate_graph (PROVISIONAL), entity_lookup, graph_management, graph_merge
candidate_graph.py ──► graph_management (DQV, FACT, RELATION, TRACE, bind), graph_merge (class_*, slug)
publication_sources.py ──► graph_management (ONTO, SRC, TRACE)
graph_store.py ──► graph_management (bind), graph_partition (legacy import)
vocabulary.py ──► graph_management (FACT, RELATION), graph_merge (class_uri, slug)
repair.py ──► llm (InvalidResponseError)
source_parse.py ──► prompts, llm (ask_llm)
windowing.py ──► prompt_budget (estimate_tokens)
schema_context.py ──► context_render (clean, field), graph_management (ONTO)
document_context.py ──► context_render (clean, field), graph_management (ONTO, SRC)
seed_view.py ──► graph_management (ONTO, bind, is_source_attribution, is_tracing), vocabulary
link_check.py ──► prompts, candidate_validation, context_render, document_context, entity_lookup,
                  graph_management, graph_merge, graph_store, llm, prompt_budget,
                  source_concepts (normalize), vocabulary, windowing (TextWindow)
graph_health.py ──► entity_lookup, graph_management, graph_store, ingest_sources,
                    link_check (expected_links), source_concepts, vocabulary,
                    windowing (make_source_document)
starter.py ──► prompts, document_publication (split_legacy_graph), graph_management, graph_merge,
               graph_partition, graph_store, llm, repair, source_validation (embedded_shape_graph),
               vocabulary
graph_scope.py ──► graph_management (BASE; CLASS/ENTITY/... lazily), prompt_budget, task_context
graph_chat.py ──► graph_scope, prompts
graph_edit.py ──► graph_management (TRACE, bind), publication_sources (forget_statement),
                  graph_store, source_validation, starter (parse_rdf), vocabulary
workspace.py ──► graph_edit, document_publication (shape_graphs), graph_chat, graph_management (bind),
                 graph_store (incl. PlainRdfError, require_named_graphs), llm, pipeline, prompts,
                 run_report, starter, seed_view, vocabulary
prompts.py ──► (stdlib only)
operations.py ──► (nothing from the package: it only names capabilities)
studio.py ──► operations (UnknownOperation, call), workspace (DEFAULT_GRAPH, DEFAULT_SOURCES, Workspace)
task_context.py ──► entity_lookup, graph_patterns (STRUCTURAL, eligible), ontology_views, source_concepts
context_render.py ──► prompt_budget, task_context (TEXT_PREDICATES, datatype_term)
ontology_views.py ──► graph_partition, graph_patterns, graph_skeleton
graph_patterns.py ──► graph_management (ONTO)
run_report.py ──► graph_partition, graph_skeleton, task_context (local_name)
view_report.py ──► graph_management (ONTO, TRACE), graph_patterns, run_report, task_context
view_html.py ──► view_report (build_report)
view_ontology.py ──► graph_management (open_graph), graph_store (ReadOnlyGraphStore, RdflibGraphStore),
                     ontology_views, run_report, task_context, view_html
root scripts: ontology.py → cli.main; view_ontology.py → view_ontology.main;
              ttl_to_trig.py → graph_store, starter; trig_to_ttl.py → rdflib only;
              migrate_prefixes.py → graph_management (BASE, ONTO, SRC, TRACE), graph_store,
                                    publication_sources (statement_uri), vocabulary
```

Deliberate seams: `source_concepts` / `prompt_budget` have no rdflib or `llm`;
`graph_partition` / `graph_skeleton` / `graph_management` / `llm` /
`ingest_sources` / `source_concepts` / `prompt_budget` / `prompts` /
`operations` import nothing from the package; `windowing` depends on
`prompt_budget.estimate_tokens` only. Three imports are lazy (inside a
function): pySHACL in `validate_source_graph`, `graph_store` in
`source_staging.retain_staging`, and the namespace constants in
`graph_scope`.

---

## 9. Composition diagram (what originates from what)

```
source files ──► find_text_files / read_source ──► make_source_document
                                                          │ (content-derived doc ID)
                                                          ▼
                              plan_windows()  →  overlapping TextWindows
                                                          │
                 per window:  task_context over the seed view  +  task_context over staging graph
                                                          │
                          layered_context_text()  →  one budgeted block (source items "(this document)")
                          data-only: header + core schema + document anchors + same folder placed first
                                                          │
                          make_prompt() → extract_validated() → [repair ≤ N]
                                                          │
                          validate_candidates(..., vocabulary=...)  (same gate every attempt;
                                                          undeclared class/predicate under data-only → error → window rejected;
                                                          only endpoint mismatches left → drop_endpoint_mismatches, window kept)
                                                          │
                          plan_window_admission(source staging graph only; trace:provisional/ IRIs)
                                                          │
                          build_candidate_graph()  →  window candidate graph (evidence, kept)
                          apply_merge_plan()  →  source staging graph grows
                                                          │ (all windows)
                          data-only: check_document_links() → one question per missing expected link;
                                     quoted answers admitted as synthetic windows "link-<hash>"
                                                          ▼
              reconcile_document()  →  report (entities, aliases, overlap supports, unresolved, conflicts)
              build_source_artifact()  →  deterministic N-Triples + metadata
              validate_source_graph()  →  pySHACL  (non-conformance → SourceValidationError)
                                                          │
              plan_document_merge(canonical scope, vocabulary)  →  identity decided ONCE
                                                          (accept/duplicate/review; no declarations in data-only mode)
                                                          │
              compile_document_publication()  →  proposed target (domain triples + src: source links)
                                                  + provenance (trace:document records;
                                                    candidate evidence only with --trace)
                                                  + review graph (trace:review/)
              validate_source_graph(proposed data)  →  (non-conformance → PublicationValidationError)
                                                          │
         publish_document(store, plan)   ←── one atomic store.publish() replacing target/provenance/review
         (or dry_run: report the same plan, never publish)
```

Outside the pipeline, the same store is driven by the starter and the studio:

```
initial information ──► starter_prompt() → extract_validated() → validate_starter()
                                                          │
                          starter_publication()  →  ONE publication replacing all five roles
                                                          │
                          schema + shapes graphs  =  the frozen starter vocabulary
                                                          ▼
page + panel ──► GET  /api/op/status|dataset?view=seed|all|operations.list|progress?job=N
             ──► POST /api/op/reset          → unlink dataset + inbox files → empty store
             ──► POST /api/op/starter.create → {job_id}   (the operation registry)
             ──► POST /api/op/ingest {files} → {job_id} → sources/inbox/ → run_text_to_graph(data_only)
             ──► POST /api/op/chat.ask {message, budget} → {job_id} → graph_scope + graph_chat over the seed view
             ──► POST /api/op/edit.preview / edit.apply → graph_edit → one publication (target + provenance)
             (studio ingestion keeps ProcessingConfig.trace off: no candidate evidence)
             (the transport only calls operations.call(workspace, name, payload))

The three long jobs (starter, ingestion, chat) run in one background thread
at a time; the page polls the `progress` operation every 400 ms and moves the
bar from the pipeline's own checkpoints (model call N for the starter; file,
window, and publication for ingestion; selection and the model call for the
chat). `progress` never touches the store, so polling while a publication
is being applied cannot read a half-written graph.
```

Identity scope: window admission sees only the source-local staging graph
(deferred); document merge sees the complete canonical scope. Selection narrows
the prompt, never the merge; validation decides admissibility; merge policy
decides identity, acceptance, corroboration, and conflicts; materialization and
publication only apply already-made decisions.

---

## 10. Constants & defaults quick reference

| Item | Value |
|---|---|
| Base namespace | `http://example.org/text-ontology/` |
| Business namespaces | `onto:` (base) `entity/ class/ relation/ fact/ expected/ graphs/(schema\|shapes\|data\|provenance\|review\|scope)` |
| Source namespace `src:` | `source/` → `file/<sha256 of path>`, `statement/<sha256 of triple>`; terms `src:SourceFile`, `src:path`, `src:fromFile` |
| Tracing namespace `trace:` | `trace/` → `candidate/ window/ activity/ agent/ metric/extraction-confidence document/ review/ provisional/ staging/ merge-event/ merge-candidate/ merge-proposed-entity/ edit/`; terms `trace:sourceDocument`, `trace:sourceFile`, the merge audit vocabulary (`ExtractionEvent`, `MergeCandidate`, `sourcePath`, ...), `editSource/editAdded/editRemoved` |
| Tracing switch | `ProcessingConfig.trace` (default `False`), CLI `--trace`; candidate evidence is published only when on |
| Default output dataset | `ontology.trig` (`.ttl` = explicit legacy Turtle compatibility) |
| Window target / overlap | `800` / `100` tokens (`WINDOW_STRATEGY_VERSION = 2`) |
| Document ID / window ID | `doc-<sha256[:16]>` / `win-<sha256[:16]>` |
| Merge policy version | `2` (`MERGE_POLICY_VERSION`) |
| Candidate mapping version | `2` (`CANDIDATE_MAPPING_VERSION`) |
| Document merge version | `1` (`DOCUMENT_MERGE_VERSION`) |
| Auto-accept confidence | `0.80` (`AUTO_ACCEPT_MIN_CONFIDENCE`) |
| Close-spelling threshold | `0.96` (`CLOSE_SPELLING_THRESHOLD`, review-only) |
| Default repair attempts | `2` (`ExtractionConfig.repair_attempts`) |
| Default LLM model | OpenRouter `google/gemma-4-26b-a4b-it:free` (`DEFAULT_MODEL`); Google `gemini-3.1-flash-lite` |
| Env vars | `LLM_PROVIDER` (default `openrouter`, or `google`); `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`; `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_REASONING_EFFORT` (default `none`); `OPENROUTER_MAX_TOKENS` (both providers) |
| LLM | OpenRouter `https://openrouter.ai/api/v1/chat/completions` (header `X-OpenRouter-Title: Simple Text to Ontology`) or Google `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`; temperature `0`, max output `4,096` tokens (`MAX_OUTPUT_TOKENS`), timeout `60` s, HTTP 429/500/502/503 retried after 2, 5, 15 s, system prompt `"Extract knowledge. Return only JSON."` |
| Accepted source extensions | `.txt .md .rst .csv .json .jsonl .yaml .yml .xml .html .log` |
| Seed graph size | 8 triples |
| Data-only ingestion | `MergeConfig.require_declared_vocabulary` (default `False`); CLI flag `--data-only`; the studio always sets it |
| Starter caps | `MIN_CLASSES` 2, `MAX_CLASSES` 20, `MAX_ASSERTIONS` 40 (`starter.py`) |
| Starter literal ranges | `XSD_TYPES`: string/text/integer/int/decimal/float/double/boolean/date/datetime/time/anyURI |
| Starter RDF import | `RDF_SUFFIXES` (`.ttl .turtle .trig .nt .n3 .nq .rdf .owl .jsonld .json`), `RDF_FORMATS` (`turtle trig nt nquads xml json-ld n3`), `RDF_SIGNS` (the content sniff) |
| Workspace | `DEFAULT_GRAPH` `ontology.trig`, `DEFAULT_SOURCES` `sources/inbox` (`workspace.py`) |
| Studio transport | `DEFAULT_PORT` 8765 (next free port when taken), page `frontend/triple-lens.html`, assets `.js`/`.css` beside it, host `127.0.0.1`, `StudioServer(ThreadingHTTPServer)`, one job at a time |
| Transport routes | `GET /` · `GET /studio.js` · `GET /studio.css` · `GET /api/op/<name>?arg=value` · `POST /api/op/<name>` |
| Operations (18) | `status` · `dataset {view}` · `progress {job}` · `reset` · `operations.list` · `starter.create {text}` → `{job_id}` · `starter.import {name, text}` · `ingest {files:[{name,text}]}` → `{job_id}` · `chat.ask {message, budget}` → `{job_id}` · `chat.state` · `chat.reset` · `edit.current` · `edit.preview {text, allow_new_vocabulary}` · `edit.apply {patch_id}` · `prompts.list` · `prompts.save {name, text}` · `prompts.reset {name}` · `prompts.preview {name}` |
| Studio jobs | starter: `model call N` at `min(10 + 25·N, 80)` % → `writing the schema and shapes` (88 %) → 100 %; ingestion: each file gets `1/files` of the bar; inside it window k starts at `(k-1)/n`, `model replied` is always at `1/2`, `admitted` at `k/n`, `published` at the end; chat: 10 % selecting, 40 % asking the model |
| Studio polling | panel polls `progress {job}` (400 ms) while `running` is true |
| Scope caps | `MAX_TRIPLES` 300, `MAX_TOKENS` 6000, `MAX_FOCUS` 20, `MAX_NAMES` 60, `SCOPE_FILE` `scope.trig`, `SCOPE_GRAPH` `.../graphs/scope`; studio subgraph sizes 2500 / 6000 / 12000 |
| Chat session | `HISTORY_TURNS` 6, `MAX_TURNS` 200, `TRANSCRIPT_VIEWS` 20 |
| Edits | `REMOVAL = "-"`, `PREVIEW_LIMIT` 40, `EDIT_BASE` `http://example.org/text-ontology/trace/edit/`; the vocabulary is frozen unless `allow_new_vocabulary` |
| Prompt templates | `extraction_system`, `extraction_user`, `starter`, `link_check_user`, `chat_system`, `chat_user`; placeholders `context`, `text`, `min_classes`, `max_classes`, `xsd_names`, `question`, `relation`, `subject`, `candidates`, `passages`, `history`, `scope_note`, `subgraph`; digest 12 hex characters |
| Prompt overrides | `prompts.local.json` beside the dataset (git-ignored); `{"version": 1, "prompts": {...}}`; only non-default entries are stored |
| Console scripts | `text-to-ontology` (`cli:main`) · `text-to-ontology-starter` (`starter:main`) · `text-to-ontology-studio` (`studio:main`) · `text-to-ontology-health` (`graph_health:main`) · `text-to-ontology-expect` (`link_check:main`) |
| Prompt budget | `total_limit 30_000 · context_tokens 1_400 · schema_tokens 3_000 · fixed_prompt_tokens 400 · output_reserve 4_000 · safety_margin 500`; `chars_per_token 3`; data-only fixed blocks are added to `fixed_prompt_tokens` per window |
| Link check | `MAX_LINK_CHECKS` 5 (`ExtractionConfig.max_link_checks`), `MAX_CANDIDATES` 20, `PASSAGE_TOKENS` 2 500, `MIN_EVIDENCE_CHARACTERS` 8; expected-link shapes `onto:expected/<class>-<relation>` |
| Document context | `MAX_TITLE_CHARACTERS` 200, `MAX_ANCHORS` 8, `MAX_FOLDER_ANCHORS` 5, `MAX_LINKS_PER_ANCHOR` 5 |
| Name stems | `MIN_STEM_CHARACTERS` 5, `MAX_ENDING_CHARACTERS` 2 (`source_concepts`) |
| Selection caps | classes 12, properties 16, restrictions 8, patterns 20, resources 15, examples 12 |
| Traversal caps | `hierarchy_hops` 1, `instance_hops` 1 |
| Matching caps | `concepts` 40, `direct_matches` 40, `match_tokens` 8, `overlap_tokens` 2 |
| Concept caps | `MAX_CHARACTERS` 200 000, `MAX_TOKENS` 5 000, `MAX_CONCEPTS` 40, `MAX_PHRASE_TOKENS` 3, `MAX_MENTION_TOKENS` 4, `MAX_MATCH_TOKENS` 6, `MIN_TOKEN_CHARACTERS` 2, `HEADING_CHARACTERS` 80, `EARLY_CHARACTERS` 400 |
| Concept weights | mention 3.0, phrase 2.0, keyword 1.0; heading +2.0; repeat +0.5 each (cap 3.0); early +1.0 |
| Field truncation | `MAX_FIELD_CHARACTERS` 240 (+ `TRUNCATION_MARKER`) |
| Report directory | `reports/runs/` |
| Dependencies | `rdflib>=7,<8`, `pyshacl>=0.30,<1`; Python 3.12+ |

`total_limit` is deliberately high so that it does not bind; it is not a
measured model window and must never be inferred or adjusted from
`OPENROUTER_MODEL`, which may name a router. `context_tokens` is the intended
lever on prompt size; where both apply the smaller wins.

---

## 11. Error handling summary

| Condition | Where | Error |
|---|---|---|
| Missing source path | `ingest_sources.find_text_files` | `RuntimeError("Source does not exist: {source}")` |
| No text-like files | `pipeline.run_text_to_graph` | `RuntimeError("No text-like files found")` |
| Unknown `LLM_PROVIDER` | `llm.provider_name` | `RuntimeError` naming the known providers |
| Missing API key | `llm.ask_choice` | `RuntimeError(f"Set {key} first")` (e.g. `Set GEMINI_API_KEY first`) |
| HTTP error (after retries for 429/500/502/503) | `llm.ask_choice` | `RuntimeError(f"{provider_name()} error {code}: {message}")` |
| Empty / non-JSON / invalid JSON answer | `llm.ask_llm` | `InvalidResponseError(...)` (caught by `repair._attempt`) |
| Plain RDF file saved as `.trig` (triples in the default graph) | `graph_store.require_named_graphs` (pipeline, workspace) | `PlainRdfError` pointing at `ttl_to_trig.py`; the studio's `status()` shows it as `error` |
| Invalid candidate package | `pipeline._extract_window` | `RuntimeError(format_validation_failure(...))` |
| Undeclared class/relation/fact (data-only) | `candidate_validation.validate_candidates` | validation errors `entity.undeclared_kind`, `relation.undeclared_predicate`, `fact.undeclared_predicate` → repair → rejected window |
| Relation/fact between the wrong classes (data-only) | `candidate_validation._check_endpoints` | `relation.domain_mismatch` / `relation.range_mismatch` / `fact.domain_mismatch` → repair; if only these remain, those records are dropped and the window continues (not an error) |
| Expected link with an unknown class/relation, or a relation that does not start at the class | `link_check.add_expected_link` | `ValueError` (the CLI prints `Error: ...`, exit 1) |
| Link-check evidence not quoted from the passages | `link_check.read_answer` | the link is dropped (`link_check.unsupported_evidence`), the gap is "not established" |
| Rejected starter proposal | `starter.propose_starter` | `RuntimeError(format_starter_failure(...))` |
| Unparseable RDF import | `starter.parse_rdf` | `ValueError` listing the formats tried |
| RDF import without vocabulary | `starter.import_publication` | `ValueError` naming the triple count |
| Page file not found | `studio.find_page` | `RuntimeError("Could not find frontend/triple-lens.html…")` |
| Studio port in use | `studio.main` | `Error: cannot listen on {host}:{port}` + `SystemExit(1)` |
| Unknown operation | `operations.call` / `StudioHandler` | `UnknownOperation` (a `KeyError`) / `{ok: false, error}` with HTTP 404 |
| Operation failure | `StudioHandler` | a `RuntimeError`/`OSError`/`ValueError`/`KeyError` → `{ok: false, error: "<Type>: message"}` with HTTP 200 (only unknown names are 404; other exception types are not caught) |
| Unknown dataset view | `Workspace.dataset_text` / `dataset` operation | `ValueError` / `{ok: false, error}` |
| Reset of an unsafe inbox | `Workspace._check_reset_target` | `RuntimeError("Refusing to reset ...")` when the inbox is the working directory, one of its parents, or the dataset's folder |
| Missing operation arguments | the operation itself | `{ok: false, error}` naming what was missing |
| Template that cannot be used | `prompts.PromptLibrary.validate` | an error string: empty, a missing required placeholder, an unknown placeholder, a bare `$` |
| Template that cannot be rendered | `prompts.PromptLibrary.render` | `ValueError` naming the missing value |
| Unknown prompt name | `PromptLibrary._known` → the workspace | `KeyError`, answered as `{ok: false, error}` |
| Empty chat question | `ChatSession.ask` / the operation | `ValueError` / `{ok: false, error}` |
| Extractor without text answers | `Workspace.ask_text` | `RuntimeError("…cannot answer with text…")` |
| Patch that does not parse | `graph_edit.parse_patch` | an error line naming the statement |
| Patch that changes the vocabulary | `graph_edit.check_patch` | an error naming the new IRIs, unless `allow_new_vocabulary` |
| Applying an unknown or stale patch | `Workspace.edit_apply` | `{ok: false, error: "…press Preview again…"}` |
| Source SHACL non-conformance | `pipeline.run_text_to_graph` | `SourceValidationError` (carries validation, artifact, report, sidecar) |
| Proposed-data SHACL non-conformance | `pipeline.run_text_to_graph` | `PublicationValidationError` (carries plan, validation) |
| Final graph changed mid-window | `pipeline._process_document` | `RuntimeError("the final ontology changed during window processing")` |
| Final graph changed during reconciliation | `pipeline.run_text_to_graph` | `RuntimeError("the final ontology changed during source reconciliation")` |
| Unknown export format | `graph_store.export_dataset` | `ValueError` |
| Duplicate role names / bad staging ns | `graph_store.GraphNames.validate` | `ValueError` |
| Budget without ceiling/arithmetic | `context_render.allowance` | `KeyError` |
| `main()` catches `RuntimeError`/`OSError` | `cli.main` | `reporter.failed(error)`, `Error: ...` to stderr, `SystemExit(1)` |

Source and publication validation errors leave the final graphs unchanged;
`--dry-run` never calls `store.publish`.

---

## 12. Current data snapshot (`ontology.trig`, as parsed from the file)

Recounted with rdflib on 2026-10-12 (commit `635c95c`). The file changes with
every starter, import, and ingestion, so the repository tests do **not** pin
these numbers.

| Named graph | Triples |
|---|---|
| `graphs/schema` | 316 |
| `graphs/data` (target) | 356 |
| `graphs/provenance` | 10 |
| `graphs/shapes` | — (not present) |
| `graphs/review` | — (not present) |
| default graph | 0 |
| all named graphs | 682 |

What it holds today is an **imported vocabulary, not extracted data**: an
ECMP/SKOS knowledge-asset vocabulary (`https://example.org/ecmp/...` IRIs,
compare `ecmp_seed.ttl`). The schema graph declares 39 classes, all with
ECMP IRIs: 35 glossary terms under `.../ecmp/lingaro/asset/` (`client`,
`project-repo`, `proposal`, `person`, `technology`, ... — SKOS concepts also
declared as classes, which is what `ttl_to_trig.py --concepts-as-classes`
produces) plus 4 `ecmp:vocab#` classes; and 9 object and 13 datatype
properties, also ECMP IRIs. The data graph holds 35 `skos:Concept` resources and a few
`ecmp:Domain` / `ecmp:CompanyProfile` / `ecmp:DataAsset` individuals; there
are no `onto:Entity` individuals and no `relation:*` / `fact:*` statements
yet, and no `onto:Entity` root class (so the core schema uses the "leave out
anything no class fits" rule, §4.22).

Other dataset files in the repository, for comparison:

| File | Graphs (triples) |
|---|---|
| `seed_ontology.trig` | schema 220 (5 classes incl. `onto:Entity`, 6 object + 34 datatype properties), shapes 5, provenance 1 |
| `ontology_bckp.trig` | schema 226, shapes 12, data 1 294, provenance 53 713, review 856 (old layout, before `src:`/`trace:`; `migrate_prefixes.py` gives 3 973 triples, or 47 466 with `--keep-candidates`) |
| `backups/ontology.init-schema-only.trig` | schema 226, shapes 12 |
| `backups/ontology.2026-10-09.before-connectivity.trig` | schema 226, shapes 5, data 5 779, provenance 172 464, review 1 680 |

Exact partition/skeleton/pattern numbers are pinned on the frozen miniature
in `tests/fixtures/miniature_repository.ttl`, not on a live dataset.

---

## 13. Test coverage map (the enforced contracts)

| Test file | What it pins down |
|---|---|
| `test_pipeline.py` | The public end-to-end loop with a fake extractor: blank-file skip, document staging, windows, admission, reconciliation, source validation, one atomic publication per document, dry-run, retention, error paths, result dataclasses. |
| `test_pipeline_windowing.py` | Long documents split into reproducible overlapping windows; every character accounted for; window IDs stable. |
| `test_pipeline_m6.py` | The complete-source gates: reconciliation report fields, source SHACL gate, artifact metadata, `SourceValidationError` leaves final graphs unchanged. |
| `test_pipeline_m7.py` | The document merge/publication stage: `plan_document_merge` once per document, proposed-data validation, `PublicationValidationError`, one `publish` call, dry-run plan. |
| `test_windowing.py` | Block/sentence/hard-chunk units, packing, overlap, blank documents, normalization, document/window IDs. |
| `test_source_staging.py` | Staging graph names, provisional allocation, window admission against the staging graph only, layered context marking, retention sidecar. |
| `test_repair.py` | Bounded self-repair: prompts, attempt limits, unparseable answers become problem text, every attempt re-validated, no bypass. |
| `test_candidate_graph.py` | PROV/DQV candidate graphs: collections, reification, decimal confidence, mapping version, determinism, typed literals. |
| `test_source_reconciliation.py` | Local entity/alias/duplicate-support/unresolved/conflict reports and deterministic artifact. |
| `test_source_validation.py` | pySHACL gate, shape combination, embedded-shape extraction, `SourceValidationResult` / `SourceValidationError`. |
| `test_graph_store.py` (via `store_contract.py`) | The GraphStore contract: get/put/delete/names/query/update, atomic replace, role graphs, legacy import/export. |
| `test_candidate_validation.py` | Structure, normalization, references, confidence in `[0,1]`, generated-URI role/type collisions, graph-exact candidates kept, fail-closed, `format_validation_failure`. |
| `test_merge_policy.py` | Identity decisions, URI reservation, accept/duplicate/review, corroboration, functional conflicts, audit vocabulary + deterministic URIs, read-only planning, counts. |
| `test_entity_lookup.py` | `identity_key`, catalog fields, resolution order, 0.96 threshold + ambiguity, kind-mismatch never resolves. |
| `test_graph_merge.py` | Helpers, typing, enrich vs overwrite, `apply_merge_plan` copy semantics, legacy `merge_into_graph`. |
| `test_graph_management.py` | Seed structure (8 triples), no reseed, prefix bindings, atomic save/round-trip. |
| `test_ingest_sources.py` | Direct-file acceptance, recursive/sorted/filtered discovery, graph exclusion, missing source, utf-8 replace. |
| `test_source_parse.py` | Prompt contains source + selected context + JSON contract (per-record confidence); `parse_source` delegates to `ask_llm`. |
| `test_llm_answer.py` | The chat client without a network: an empty answer is an `InvalidResponseError` naming the reason, a normal answer parses, `openrouter` is the default provider, `google` uses its own address/key/model and `reasoning_effort` (default `none`, configurable), a missing key names the variable, an unknown provider is a clear error, the model override is what is sent, a busy answer is retried and retries end. |
| `test_source_concepts.py` | Record fields/vocabularies, determinism, Unicode preservation, weighting/caps, word-boundary phrases, no rdflib/`llm` import. |
| `test_ontology_views.py` | The five fields; façade equals direct calls; lossless partition; observations never become declared structure. |
| `test_task_context.py` | Tier order, name/label/alias matching, bounded expansion, restriction bundles, patterns, native vs generic cards, caps, determinism. |
| `test_context_render.py` | Section order, declared vs observed, six restriction forms, defused delimiters, truncation, `existing_ids` derivation, allowance never exceeded. |
| `test_prompt_budget.py` | Estimator, allowance arithmetic, priority order, oversized items dropped whole, dependency bundles charged once, injected counters. |
| `test_graph_partition.py` | Role rules per triple, source/audit predicates, restrictions, remainder, lossless/disjoint/read-only invariants (sizes pinned on the frozen miniature). |
| `test_graph_skeleton.py` | Core retention, no inference, supported vs unsupported restrictions, subset invariant. |
| `test_graph_patterns.py` | Class/literal/unknown ranges, counting, coverage/cardinality, most-specific class, exclusions, ordering, read-only. |
| `test_publication_sources.py` | `SourceAttributionTest`: entities, relations, and facts name their files with `src:` in the data graph; one file node per path even when the content changes; the same file name in two folders keeps two nodes; withheld claims get no source link. `TracingTest`: candidates are kept only with `trace`; business data is identical with or without `trace`; every PROV/DQV triple is tracing; filtering `trace:` leaves only business data and source links; source links and `trace:` links are support when graphs are combined. |
| `test_migrate_prefixes.py` | `migrate_prefixes.py` on a small old-layout dataset: source links land in the data graph, tracing moves under `trace:` and the candidates are dropped, `--keep-candidates` keeps them under `trace:`. |
| `test_run_report.py` | Reporter streams, Markdown blocks, checkpoint methods. |
| `test_cli.py` | Argument parsing, `.ttl` compatibility selection, `--report` / `--dry-run` / `--trace` wiring (`--trace` keeps the candidate evidence), exit codes. |
| `test_view_html.py` | `view_html.write_report` renders `view_report.build_report` output as one self-contained page. |
| `test_install_smoke.py` | The package imports and the console script is installed. |
| `test_graph_edit.py` | Patch parsing (additions, removals, shared prefixes, a comment, a missing full stop, both kinds of parse error), fenced Turtle blocks, preview (stable id, both sides of the diff, new vocabulary frozen or allowed, undeclared use as error or warning, an absent removal as a warning, a class/property collision, SHACL as a warning), all edit evidence being tracing (`trace:edit/...`), a removed triple losing its `src:statement` node, the publication touching only target and provenance, and the workspace operations end to end (current, preview, apply, a refused patch never stored, the toggle travelling with the preview). |
| `test_graph_chat.py` | The scope selector: focus from the question, statements plus declarations, the triple cap with a reported `dropped`, a well-connected node not pushing the schema out, deterministic output, carry-over for a follow-up, an empty match, the TriG/view/model faces, and the summary. The chat: a turn answers from the subgraph, the transcript keeps each subgraph (bounded to the newest turns), history reaches the prompt, reset, an edited chat prompt, and the workspace operations end to end. |
| `test_prompts.py` | Every default template is valid, the `KeyError`/`ValueError` messages, the placeholder rules (required, unknown, bare `$`, escaped `$$`), the advisory checks, the override file (store, refuse, reload, reset, corrupt file, stale template), the digest, and that an edited template reaches `make_prompt`, `starter_prompt`, and `parse_source`. |
| `test_vocabulary.py` | `read_vocabulary` over the seed and a starter schema; slug-based `declares_*` matching; relations never read as facts; blank nodes skipped; unlabelled declarations fall back to the IRI. |
| `test_starter_import.py` | RDF detection (suffix and content sniff), `parse_rdf` for Turtle/TriG/unknown/garbage, partitioning a plain ontology into roles, importing this project's own named graphs role for role (keeping a foreign graph as data), refusing a document with no vocabulary, an atomic failure leaving the old dataset alone, the operation answers, and the end-to-end proof that data-only ingestion after an import types individuals with the imported classes and predicates and creates no `class:*` twins. |
| `test_starter.py` | Proposal checking (sections, camelCase names, unknown domain/range, duplicates, counts), repair of a messy answer, `starter_publication` roles and triples, `proposal_summary`, `create_starter` replacing an old dataset. |
| `test_data_only.py` | The data-only gate end to end: declared extraction accepted with the schema and shapes unchanged, undeclared kind/predicate rejected and nothing written, no declarations in a data-only plan, and the permissive default still declaring as before. |
| `test_studio.py` | Three layers in one file: `Workspace` status/dataset/reset/`_write_source` round trips, data-only ingestion and its error, and the job layer (progress from model calls and per-file/window checkpoints, a monotonic bar across several dropped files, a failed job finishing with its error, results handed only to the job that asked, one job at a time); the operation registry (manifest equals the registry, every operation answers plain JSON, unknown names raise, missing arguments are reported, a running job is refused); `Assets` (page + panel + styles served, traversal and unknown types refused); and the HTTP transport (`/`, `/studio.js`, `/studio.css`, `GET`/`POST /api/op/<name>`, 404 for unknown operations and old routes). |
| `test_connectivity_pipeline.py` | Data-only ingestion end to end with a fake extractor: a window that matches nothing still sees the whole core schema, the run records `schema_sha256`, an old `extraction_user` override still works, every window carries path/title/earlier anchors, earlier-window entities show no temporary IRI (a copied one is cleared, not fatal), a wrong link is repaired first and dropped alone if still wrong, the link check fills a gap from quoted evidence / adds nothing for an unquoted or empty answer / makes no call without a gap / can be switched off, a canonical client is a candidate with its `id:`, and same-folder entities reach a later file's prompt and may be used as `existing_id`. |
| `test_schema_context.py` | `render_core_schema`: every class/relation/fact once with its meaning, the root class last with its limit, order independent of triple order, graph text cannot forge prompt structure; `schema_digest` stable and schema-dependent. |
| `test_document_context.py` | Title from a heading / first line / nothing, heading trail by level, the header lines, a path cannot forge a delimiter, anchor classes = subjects of relationships, anchors most linked first and at most 8, no anchors → no block, same-folder entities only from files in that folder (read from `src:path` / `src:fromFile`). |
| `test_endpoint_checks.py` | Domain/range checks: declared direction passes, wrong subject/object class and a fact on the wrong class are mismatches, a subclass fits, an `existing_id` entity is checked by its graph kind, nothing new without a vocabulary, only the mismatched records are dropped, other errors keep the old behaviour; `read_vocabulary` reads domains, ranges, and parents. |
| `test_link_check.py` | Expected-link shapes read back (a violation shape is not one), a missing expected link warns but conforms, `add_expected_link` checks names, gaps (with/without the link, closed by a canonical twin, the limit), passages (first window plus windows naming a name, in order, the cap), candidates (range class only, named first, canonical with id), a quoted link becomes an ordinary package, unquoted evidence or an unknown key is dropped, a shapeless answer is nothing, and the `link_check_user` template validates and previews. |
| `test_name_forms.py` | `same_word_stem` / `same_name_stem` (same word with another ending, different words, word by word), an inflected name selects the existing card, an inflected form is held for review (`inflected_form`) only for the same kind, and an alias still resolves exactly. |
| `test_seed_view.py` | The seed view keeps the schema whole, declared statements/names/kinds, drops bookkeeping and undeclared statements, leaves out `src:` source links and provenance/review/shapes, counts declarations made in a data graph; `dataset` view `seed` is the default, `all` shows every named graph, an unknown view is a clear error, and the chat reads the seed view. |
| `test_graph_health.py` | Each health number on a small graph: isolated and root-only entities, endpoint violations, missing expected links, duplicate suspects, gold recall/precision, uncovered sources, and the whole report from a file. |
| `test_plain_rdf.py` | A plain RDF file saved as `.trig` is refused by ingestion and by the studio (`PlainRdfError`) and left alone; `ttl_to_trig.py`: classes to schema and individuals to data, `.trig` and `.ttl` sources split the same way, an existing output needs `--force`, a refused source never costs the existing output, the source is never the output, `--concepts-as-classes` (off by default) makes named, described classes with a hierarchy that can be an extracted kind, and a schema without a root class gets the "leave it out" rule. |

**Running the tests**: `.venv/bin/python -m unittest discover -s tests -p
'test_*.py'` (50 test modules). Status on 2026-10-12 (commit `4417f54`):
`Ran 1082 tests`, `FAILED (errors=8, skipped=2)` — only the 8 known errors
below.

**Known issue — 8 errors from a deleted file.** Eight tests still read the
repository's `ontology.ttl`, which commit `b90acdf` deleted, and fail with
`FileNotFoundError`: `test_graph_partition` (2: `RepositoryGraphTest`,
`InvariantTest`), `test_graph_patterns` (1), `test_ontology_views` (3),
`test_graph_skeleton` (1), and `test_pipeline` (1: `RepositoryGraphTest`).
They check that the working-tree dataset is never written; every other
contract in those files passes. They need a new target (for example
`ontology.trig` or a fixture) — not fixed yet.

---

## 14. Gotchas & non-obvious behavior (from source and tests)

1. **Content identity ≠ file identity**: a document ID is a digest of its
   normalized text, but the `src:file` node is a digest of the **path only**.
   The same content in two files shares one `trace:document/` record but keeps
   two `src:file` nodes; changed content in the same file creates a new
   document and keeps the same file node.
2. **Windows are reproducible but not content-faithful slices**: they tile the
   normalized text (spans never drop or duplicate characters), but boundaries
   can fall mid-sentence; `window_id` depends on strategy version, target/
   overlap, tokenizer name, document ID, index, and offsets.
3. **Staging never decides canonical identity**: `plan_window_admission` sees
   only the source staging graph; new entities get
   `trace:provisional/<doc>/...` IRIs; canonical resolution happens once at document merge.
4. **`existing_id` cannot resolve inside a window**: canonical resources are
   not in the staging graph, and source-local items are marked `native: False`
   and show no IRI, so nothing source-local can become a reusable
   `existing_id`. The same-folder block (§4.23) is the exception that *adds*
   canonical ids to the allowed `existing_ids`.
5. **The final ontology is invariant during windowing**: a triple-level
   snapshot is compared after every window and after reconciliation; any change
   raises `RuntimeError`.
6. **Repair never bypasses validation**: a repaired answer passes exactly the
   same `candidate_validation` gate; after `repair_attempts` failures (default
   2, 0 disables) the window is rejected — except in data-only mode when the
   only errors left are endpoint mismatches: then just those records are
   dropped and the rest of the window is re-validated and kept.
7. **Candidate graphs are evidence, not assertions**: asserted triples and
   their `rdf:Statement` reifications are both present, which is what lets
   reconciliation count independent supports without trusting reification alone.
8. **pySHACL runs over a copy** with `inference="none"`, `allow_infos=False`,
   and `allow_warnings=True` — a `sh:Warning` (such as an expected link) is
   reported but never blocks; shapes come from `ValidationConfig.shape_graphs`,
   else the configured shape roles, else legacy embedded shapes.
9. **Exact duplicates corroborate**: an existing exact triple is planned as
   `duplicate` (any confidence) and is never re-added; with `--trace` each
   window's confidence measurement stays as independent evidence in the
   provenance graph, and either way the document gets its own `src:fromFile`
   link on the existing `src:statement` node.
10. **Confidence semantics**: `confidence` is the model's confidence that the
    source text directly supports the complete record — not identity
    confidence, not world truth. New assertions below `0.80` go to review.
11. **Existing canonical values are never overwritten**: prefLabels/comments
    survive; a differing later name becomes an `altLabel`; a conflicting
    description goes to review (`conflict.existing_description`).
12. **Publication is one atomic store call**: target/provenance/review are
    replaced together; schema/shapes/data graphs are copied through. Failure
    leaves both the file and the in-memory dataset byte-identical.
13. **`--dry-run` computes everything, publishes nothing**: proposed sizes,
    plan, and validation are reported; `store.publish` is never called.
14. **`legacy .ttl` output is the same pipeline**: `LegacyTurtleDatasetStore`
    splits the Turtle into in-memory roles, orchestrates identical named-graph
    logic, and exports the role union as one Turtle via `save_graph`.
15. **`retain_staging_on_failure` only writes a sidecar** (`<graph>.staging/
    <doc>.trig`) when a window or a validation fails; the canonical file is
    never touched by staging.
16. **Audit is deterministic and additive**: event/candidate URIs are digests
    over policy version, source, model, and package, so exact reruns reuse the
    same resources; no timestamps and no raw source/prompt/response are stored.
17. **`identity_key`/`slug` folding is lossy** (NFKD→ascii drops characters with
    no decomposition) while `source_concepts.normalize` is Unicode-preserving —
    three normalizations coexist on purpose and must not be unified carelessly.
18. **Close spelling (≥ 0.96) and inflected forms are review-only**: they
    never auto-resolve; the candidate's preferred name (not its aliases) is
    compared with every name of same-kind entities; kind mismatch blocks
    resolution. An inflected form ("Polpharmy" vs "Polpharma") becomes
    `review` with `identity.inflected_form`.
19. **Skeleton does no inference** and drops unsupported/incomplete
    restrictions whole; patterns are observations that never become axioms.
20. **The context budget is charged pessimistically** (headings for every
    candidate section, `assembly_overhead` + 3 chars/token), so assembled text
    never overruns the stated allowance; if no number is configured,
    `allowance()` raises `KeyError` rather than inventing one.
21. **Selection narrows the prompt, not the merge**: whole-canonical identity
    is still resolved at document merge inside the planner.
22. **An `existing_id` must have actually been shown**: only ids rendered as
    `id:` in the final budgeted prompt that still exist in `entity_catalog`
    are accepted by validation.
23. **Validation fails closed**: one error rejects that window's whole package
    (the endpoint-only exception of #6 aside); duplicates are warnings, not
    errors. `format_validation_failure` never
    includes the raw model response.
24. **Fact duplicate keys include the JSON type**: `"1"`, `1`, and `true` are
    distinct facts; NaN/±infinity and collections are rejected.
25. **The viewer reads read-only**: `ReadOnlyGraphStore` wraps a TriG store and
    every view is built in memory; only `-html` writes a file (the HTML page).
26. **Data-only means no declaration ever**: with a vocabulary the gate refuses
    an undeclared kind or predicate and the planner emits no class/property
    declaration triples at all, so the schema, the shapes, and every class and
    property triple in the data graph are byte-identical before and after
    ingestion. `class_triples` is skipped for the same reason (it can carry a
    differently-cased label).
27. **Vocabulary matching is by generated IRI, not by spelling**: `Person`,
    `person`, and `PERSON` all fold to `class:person` and are accepted;
    a starter name in camelCase would fold differently on the way back
    (`label()` splits it), which is why `starter.validate_starter` refuses
    camelCase names and names that slug to `unnamed` (underscores pass:
    `has_part` is fine).
28. **A starter is written in one atomic publication** replacing all five
    roles, so re-running it replaces the previous starter instead of growing
    it; the previous data, provenance, and review graphs are gone.
29. **The studio owns no state of its own** beyond the dataset file and the
    inbox directory: `reset` unlinks the graph file and every file under the
    inbox (recursively), removes the folders left empty, and re-opens an
    empty in-memory store.
    The in-memory store is shared with the pipeline, so every answered request
    already sees the new state.
30. **The studio is additive**: `frontend/triple-lens.html` still works
    from `file://` (the studio script is not even loaded, and when it is served
    without a backend the connection probe fails and the studio row and column
    stay hidden); the studio markup lives in `studio.js`, reaching the lens
    only through `window.__lens`.
31. **Studio progress is real, not a spinner**: the starter counts model calls
    (a repair attempt shows as `model call 2 (repairing the answer)`), and
    ingestion moves per file and per window from the pipeline's own reporter
    checkpoints. The file number comes from the studio, not from the
    per-file run, so a three-file drop reads 0 % → 33 % → 67 % → 100 %
    instead of restarting at zero. Within one file the bar is *not* strictly
    monotonic: `model replied` is always reported at half of the file's
    share, so on a document with 3+ windows it steps back on late windows.
32. **Only one studio job at a time**: the `Progress` slot serializes the two
    long jobs even though the HTTP server is threaded, so graph writes never
    interleave; reads a page makes during a job (`progress`) do not touch the
    store.
33. **Prompts are data, not code**: every model prompt is a named
    `string.Template` in `prompts.py`. Overrides live in `prompts.local.json`
    beside the dataset, are validated before they are stored, and are ignored
    (not fatal) when a stored one stops validating. Because `Template` leaves
    braces alone, an edited JSON contract needs no escaping, and `$$` is a
    literal dollar. The two extraction digests (and `schema_sha256`) join the
    run configuration, so an artifact names the templates that produced it
    (the `link_check_user` digest is not recorded), and `extractor_for_run()`
    rebuilds the client per run so an edited system prompt takes effect.
34. **An imported vocabulary keeps its IRIs**: `Vocabulary.class_iri` /
    `relation_iri` / `fact_iri` resolve a candidate name to the *declared* IRI,
    so an imported `lib:Bike` is what new individuals are typed with and
    `lib:made-by` is what new statements use. Merge planning and the collision
    check both ask the vocabulary, which is why importing an ontology creates no
    `class:*` twins and does not dead-end the data-only gate. Individuals always
    stay in the project's `entity:` namespace; only classes and properties come
    from the starter.
35. **Importing RDF belongs to the starter step, not to ingestion**: a dropped
    RDF/Turtle/TriG file is parsed and replaces the dataset like any starter
    (`starter.import`, or `python ttl_to_trig.py`), while the Add
    sources zone refuses RDF-looking files (by suffix, in `studio.js`, which
    also catches `.json`) and points at the Starter ontology dialog — feeding
    a syntax file to the extractor would only produce noise.
36. **A chat answer is only as wide as its scope**: each turn shows the model
    one bounded subgraph of the seed view (300 triples, types and labels ranked first, a slice
    reserved for declarations) and nothing else; the transcript keeps that same
    subgraph, so a reader can always see what the answer was based on. A
    follow-up carries the previous focus over, which is what makes "and
    Germany?" work without repeating the question.
37. **The chat system prompt wins over the extractor's**: the same
    `OpenRouterExtractor` answers extraction (JSON, `extraction_system`) and
    chat (prose, `chat_system`); `extract_text(prompt, system)` takes the
    caller's system message, because the first live run answered the chat with
    JSON while the extraction contract was still in force.
38. **An edit is always previewed first**: `edit.preview` parses and checks a
    patch and stores the exact triples under a `patch_id`; `edit.apply` writes
    those stored triples and nothing else, so editing the text box after a
    preview invalidates the button until the next preview. A chat answer's
    Turtle block goes through the same path and is never applied by the model.
    Only the latest previewed patch is kept (`self.edits` holds one entry), and
    every chat answer with a Turtle block is previewed again whenever the chat
    state is read — so it can replace a pending hand-edit preview.
    Because the removal syntax is `- `, the parser shares the patch's prefix
    declarations with every removal line.
39. **Showing a subgraph means showing only it**: the panel's default is to
    replace the canvas with the scope's triples (`replace: ["scope.trig"]`,
    the scope file, `mode: "instances"`, `clearFilters`, `hideIsolated: false`,
    and the focus), because
    adding a handful of triples beside a large dataset is invisible. "With the
    full graph" keeps the additive behaviour, and "Show the full graph again"
    reloads the dataset with `resetFilters` so it comes back with the lens's own
    defaults. The panel also reports how many nodes the canvas ended up with, so
    an unexpected empty view says so instead of looking broken.
40. **A chat answer can be a proposal**: `_with_proposals` finds a fenced Turtle
    block in an answer and previews it, so the panel can offer to apply it; a
    proposal that would change the vocabulary or use undeclared names comes back
    with the same errors a hand patch gets, and the model's guess at the IRIs is
    exactly what that check catches.
41. **The strict matcher misses plurals, so there is one bounded fallback**:
    `loose_matches` runs only when the strict selection found no resources, and
    only against labels, with singular forms and one subclass level for class
    names. It is reported as `focus_source: "loose"`, so a reader can tell which
    path found the subgraph.
42. **One route, every capability**: the transport is a dispatcher over
    `operations.call`, so a new capability is one function plus one `Operation`
    line in `operations.py` — `studio.py` does not change, and an unknown name
    is the only 404. `GET` carries arguments in the query string (as strings;
    the operation coerces), `POST` carries a JSON body.
43. **The studio is not in the page**: `frontend/triple-lens.html` holds no studio
    markup, style, or logic, and loads `studio.js` / `studio.css` only when it
    is not opened from `file://`. The page owns `#workspace` layout so it still
    renders standalone, and the only contract between the two files is the
    `window.__lens` view API.
44. **A view is data, not code**: `applyView({replace, files, mode, focus,
    filters, hideIsolated, clearFilters, resetFilters})` is the whole
    picture-changing surface (`focus` is one node IRI); the lens resolves IRIs to nodes and filter keys to internal sets,
    and ignores junk, so a backend bug can mislead the picture but cannot break
    the viewer.
45. **Prompts see the seed view, not the dataset**: provenance, review,
    shapes, `src:` source links, `trace:` tracing, bookkeeping types, and
    statements with undeclared predicates never
    reach an extraction prompt or the chat. The core schema, the vocabulary,
    and every window's selection are read from `seed_view(roles, names)`,
    rebuilt after each publication; identity is still decided against the
    full `canonical_graph(roles, names)`.
46. **The data-only rules live in the core schema block, not in a template**:
    "most specific kind", "declared direction only", and "base-form names"
    are part of `render_core_schema`'s text, so they reach users with an old
    `extraction_user` override and no template had to change. A schema too
    big for `schema_tokens` falls back to word matching and loses those rules
    for that run (the report says so).
47. **The link check never invents a link**: one question per gap, at most
    `max_link_checks`, no repair round; a link is kept only when its evidence
    is quoted from the passages, and then it passes the same validation gate
    (endpoint check included) and the same admission as a window. No gap, no
    shapes, or `--no-link-check` → no extra model call.
48. **A plain RDF file is refused, not emptied**: triples in the default graph
    of a `.trig` file are invisible to every role read and would be dropped by
    the next publication, so ingestion and the studio stop with
    `PlainRdfError` and point at `ttl_to_trig.py`.
49. **`RunResult.windows_processed` counts link-check packages too**: it adds
    `len(staged.packages)`, which includes the synthetic `link-<hash>`
    windows.
50. **The `trace:` filter rule has one exception, in the partition**: a
    triple is tracing when its subject *or* predicate is in `trace:`
    (`is_tracing`, used by the seed view). `graph_partition.choose_view` is
    stricter: only a `trace:`/`src:` *predicate* or a `src:` *subject* makes a
    triple support. A `trace:` subject alone does not, because a staging
    graph's provisional entities are `trace:provisional/...` and must stay
    instances that a later window can see and reuse.
51. **Candidate evidence is written only with `--trace`**: without it
    (the default, and always in the studio) the provenance graph gets only the
    `trace:document/` records and `trace:sourceDocument` links; the per-window
    candidates, windows, activities, agents, and DQV confidences are built in
    memory (staging, reconciliation, the failure sidecar) and then dropped.
    The data graph is identical either way.
52. **One `src:file` node per path, for good**: the file IRI hashes only the
    path, so re-ingesting an edited file adds `src:fromFile` links to the same
    node and never removes old ones; renaming or moving a file makes a new
    node. Same-folder anchors (§4.23) read these `src:` links from the data
    graph, so ingestion never reads the provenance graph.
53. **A removed triple loses its source statement, not its entity links**: a
    hand edit that removes a relation or fact also removes its
    `src:statement` node; entity `src:fromFile` links stay.

---

*End of architecture map. Generated from source files only; no external documentation was consulted.*
