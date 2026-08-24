# Text-to-ontology implementation plan

## Document purpose

This is an independent handoff document for evolving the current experiment into
a packaged, modular text-to-RDF application. A developer or coding agent should
be able to execute it without access to the conversation that produced it.

The plan is acceptance-driven:

1. Each milestone first states what it must achieve.
2. Its acceptance criteria define observable completion.
3. Its tasks explicitly point to the acceptance criteria they satisfy.
4. A milestone is complete only when every acceptance criterion has recorded
   evidence and the completion record has been filled in.

Within a milestone, task mappings use short criterion names: for example,
`M5-T2 → AC2, AC3` means that task exists to satisfy `M5-AC2` and `M5-AC3`.
Tasks are subordinate to acceptance criteria. If a criterion changes, review
its mapped tasks instead of executing an obsolete checklist mechanically.

The architectural background is in:

- `README.md`
- `docs/current_architecture.md`
- `docs/data_flow.html`
- `docs/prompt_context_budget.md`
- `docs/ox_recommendations.md`
- `docs/architecture_proposal_openai.md`

Where this plan differs from the older proposal, this plan is authoritative. In
particular, it incorporates the later decisions about document-level staging,
confidence representation, and Python packaging.

## Status and ownership

- Overall status: [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete
- Plan owner:
- Technical owner:
- Started: 2026-08-24
- Target release:
- Last updated: 2026-08-24
- Current milestone: M6 (source reconciliation and validation) is next
- Current branch:
- Overall notes:

Use only one status checkbox on each status line. Anyone changing milestone
status must add a dated entry to that milestone's completion record.

## Fixed architectural decisions

These decisions are inputs to the implementation. A milestone may not quietly
change them. Record a new architecture decision before deviating from one.

1. The application is a **modular monolith**, not a set of microservices.
2. One source document is one input file. A directory is an ordered collection
   of source documents.
3. A long document is split into stable windows.
4. Windows incrementally build a graph that contains knowledge extracted from
   that source document only.
5. The final ontology is not changed while a document's windows are being
   processed.
6. Only after the complete source graph has been reconciled and validated is it
   resolved against and merged into the final ontology.
7. There is exactly one final publication transaction per non-empty source
   document.
8. The final merge stays sequential and single-writer. Parallel extraction is a
   later optimization.
9. The durable data model is an RDF dataset containing named graphs. Turtle is
   an import/export format, not the long-term database abstraction.
10. Modules read and write graphs through a small graph-store boundary. They do
    not open Turtle files or create Jena connections themselves.
11. The LLM may continue returning JSON. Valid JSON is converted into an RDF
    candidate graph immediately after response validation.
12. Context relevance and context token budgeting remain separate operations.
13. Declared RDFS/OWL structure and empirically observed usage remain separate.
    Observed patterns never become axioms automatically.
14. Semantic infrastructure uses RDF, RDFS, OWL, SKOS, SHACL, PROV-O, DQV,
    Dublin Core Terms, XSD, and other established vocabularies where they fit.
    Do not create custom workflow, provenance, confidence, or validation
    predicates/classes.
15. Project-owned IRIs are allowed for domain concepts, individuals, graph
    names, run resources, and instances of standard classes such as
    `dqv:Metric`. This is unavoidable domain identification, not a custom
    semantic mechanism.
16. The project starts as one installable Python distribution using
    `pyproject.toml` and a `src/` layout.
17. The Python API is the core product. The CLI, future app, and future skills
    are thin adapters over that API and may not copy core pipeline logic.
18. Code and names must remain simple and self-explanatory for a developer who
    is not advanced.

## Target processing model

```text
source file
   |
   v
SourceDocument --> stable TextWindows
   |
   v
create empty source-local named graph
   |
   +--> window 1 --> window candidate graph --+
   |                                          |
   +--> window 2 --> window candidate graph --+--> source-local merge
   |                                          |    and reconciliation
   +--> window N --> window candidate graph --+
                                                  |
                                                  v
                                      complete source graph
                                                  |
                              document validation + SHACL
                                                  |
                                                  v
                                 one read-only final merge plan
                                                  |
                                      dry-run returns here
                                                  |
                                                  v
                                  one atomic publication to the
                                  final data/provenance/review graphs
```

While processing a window, context selection may read the configured final data
graphs, schema graphs, shape graphs, and the part of the source graph built from
earlier windows. It must not copy unrelated final-ontology assertions into the
source graph. A source-graph assertion must be supported by the source text.

## Terminology

| Term | Meaning in this plan |
|---|---|
| Source document | One directly supplied file or one file discovered in a directory |
| Window | A reproducible text slice with document ID, index, and offsets |
| Window candidate graph | RDF produced from one LLM response before source-local reconciliation |
| Source graph | The incrementally built RDF graph supported by all windows of one source document |
| Final ontology | The configured canonical data graph(s), schema graph(s), and shape graph(s) |
| Target graph | The canonical data graph that receives accepted domain triples |
| Provenance graph | A named graph holding PROV-O, RDF reification, and DQV measurements |
| Review graph | A named graph holding source candidates withheld from canonical data |
| Local admission | A window assertion is safe enough to enter the source graph; this is not final publication |
| Publication | The single document-level transaction that updates final named graphs |
| Extraction confidence | Model-reported confidence that a complete source record is directly supported by the text |
| Identity score | Similarity evidence for a possible entity mapping; it is not extraction confidence |
| Merge decision | Accept, duplicate/corroborate, or review; it is not a confidence value |

## Global engineering rules

Every milestone must preserve these rules unless its acceptance criteria
explicitly replace one.

- Keep the orchestration readable from top to bottom.
- Prefer plain functions and dataclasses over inheritance and registries.
- Do not add a generic module framework or dynamic DAG engine.
- Do not add a dependency merely to avoid a small, clear function.
- Do not use a live LLM in the normal automated test suite.
- Do not use a live Jena server in the normal unit test suite.
- Test data lives in fixtures or temporary directories, never in the mutable
  repository `ontology.ttl`.
- Read-only modules must not mutate their input graph or graph store.
- Only the publisher may update final data, provenance, or review graphs.
- Do not silently truncate source text.
- Do not silently resolve ambiguous identities.
- Do not overwrite canonical labels, descriptions, or explicitly constrained
  values without a reviewed policy decision.
- Do not serialize secrets, raw API keys, or `.env` contents into reports,
  graphs, fixtures, or Git.
- Any persisted run artifact must be deterministic where practical and must
  state which non-deterministic external response produced it.
- Update user-facing documentation in the same milestone that changes a public
  command or data contract.

## Initial packaging choices

Use these names unless an accepted architecture decision changes them:

| Packaging concern | Initial choice |
|---|---|
| Distribution name | `text-to-ontology` |
| Import package | `text_to_ontology` |
| Console command | `text-to-ontology` |
| Source layout | `src/text_to_ontology/` |
| Build backend | Hatchling through standard `pyproject.toml` metadata |
| Runtime dependency at M0 | `rdflib>=7,<8` |
| Test framework | Existing standard-library `unittest` suite |
| Legacy command during migration | Root `ontology.py` as a temporary compatibility wrapper |

Choose the minimum supported Python version during M0 by checking the current
code and running the suite on that version; record it in `requires-python`. Do
not claim support for an untested version. `pyproject.toml` is the dependency
source of truth. A lock file may pin the development/application environment,
and `requirements.txt` may exist temporarily only if its compatibility role or
generation procedure is documented.

## Verification levels

Use the smallest appropriate test, but satisfy all applicable levels before a
milestone is complete.

1. **Unit tests:** one module with in-memory inputs and no external services.
2. **Contract tests:** the same observable store/extractor behavior exercised
   against every adapter.
3. **Pipeline tests:** fake extractor plus temporary store through the public
   Python API.
4. **CLI tests:** installed console command using temporary paths.
5. **Integration tests:** local Fuseki/Jena only when the Jena milestone is
   reached.
6. **Manual smoke test:** a small real source, only when credentials and explicit
   permission to call an external model are available.

Normal local test command before packaging:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Normal local test command after packaging:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

The project may later add a shorter `make check` or `uv run` command, but it must
continue to call the same deterministic suite.

## Current baseline recorded on 2026-08-24

- Branch at inspection: `master`
- Latest inspected commit: `2f8da8b added report`
- Python command available: `python3`
- `python` command: not available
- Dependency declaration: `requirements.txt` with `rdflib>=7,<8`
- `pyproject.toml`: absent
- Test result: 632 tests run, 6 failures
- Known failing areas:
  - repository-graph size assertions in `test_graph_partition`;
  - repository-graph assertions in `test_graph_patterns`;
  - repository-graph size assertion in `test_graph_skeleton`.
- Cause: tests inspect the mutable repository `ontology.ttl`, which had grown to
  4,305 triples while the tests still expected an old snapshot.

Milestone 0 must replace this red, mutable baseline with deterministic fixtures.
Do not merely update expected counts to the latest mutable graph.

## Milestone dependency map

```text
M0  deterministic baseline + packaging
 |
 v
M1  public API + thin CLI
 |
 +-----------> M2 source documents + windowing
 |                 |
 v                 v
M3 graph store + local RDF dataset
 |                 |
 +--------+--------+
          v
M4 window candidate RDF + confidence/provenance
          |
          v
M5 incremental source graph, final ontology untouched
          |
          v
M6 complete-source reconciliation, repair, and validation
          |
          v
M7 one document-level final merge transaction
          |
          v
M8 SPARQL context/skeleton over multiple named graphs
          |
     +----+----+
     v         v
M9 seed tool  M10 Jena/Fuseki adapter
     \         /
      +---+---+
          v
M11 CLI/app/skill adapter readiness
          |
          v
M12 measured scale optimizations
```

Do not start a milestone until all of its incoming dependencies meet their
acceptance criteria, unless the work is an isolated spike on a separate branch.
A spike is disposable research and may not be merged as production code without
the normal milestone acceptance evidence.

## Milestone dashboard

| Milestone | Status | Owner | Branch | Completion commit | Completed |
|---|---|---|---|---|---|
| M0 Baseline and packaging | [x] | ox-alpha agent | milestone/m00-packaging-baseline | 7c27e2c | 2026-08-24 |
| M1 Public API and thin CLI | [x] | ox-alpha agent | milestone/m01-public-api-cli | (pending commit) | 2026-08-24 |
| M2 Documents and windowing | [x] | ox-alpha agent | milestone/m02-documents-windowing | (pending commit) | 2026-08-24 |
| M3 Local RDF dataset/store | [x] | ox-alpha agent | milestone/m03-local-graph-store | (pending commit) | 2026-08-24 |
| M4 Candidate RDF and confidence | [x] | ox-alpha agent | milestone/m04-candidate-rdf-confidence | (pending commit) | 2026-08-24 |
| M5 Incremental source graph | [x] | ox-alpha agent | milestone/m05-incremental-source-graph | (pending commit) | 2026-08-24 |
| M6 Source reconciliation and validation | [ ] | | | | |
| M7 One final document merge | [ ] | | | | |
| M8 SPARQL context and skeleton | [ ] | | | | |
| M9 Separate seed tool | [ ] | | | | |
| M10 Jena/Fuseki adapter | [ ] | | | | |
| M11 Product adapter readiness | [ ] | | | | |
| M12 Scale optimizations | [ ] | | | | |

`[ ]` means not complete. Replace it with `[x]` only after recording acceptance
evidence in the milestone and updating the completion record.

---

## M0 — Deterministic baseline and installable package

### Intended achievement

Make the repository safely changeable. The tests must be green and independent
of mutable user data, and the project must install as a normal Python package
from `pyproject.toml` without changing current short-source behavior.

### Status

- [ ] Not started  [ ] In progress  [x] Complete

### Acceptance criteria

- **M0-AC1:** `python3 -m unittest discover -s tests -p 'test_*.py'` passes with
  zero failures and does not read the mutable repository `ontology.ttl` in tests
  that assert exact graph contents or sizes.
- **M0-AC2:** The six baseline failures are repaired using stable test fixtures
  or invariant assertions, not by pinning new counts from the current graph.
- **M0-AC3:** `pyproject.toml` is the authoritative declaration for build system,
  project metadata, Python requirement, and runtime dependencies.
- **M0-AC4:** Code intended for import lives under `src/text_to_ontology/` and can
  be imported after an editable install from outside the repository root.
- **M0-AC5:** A wheel can be built and installed into a clean temporary virtual
  environment; its installed package contains required prompt/query/static
  resources.
- **M0-AC6:** The existing direct script workflow remains available during the
  transition or has an explicitly documented replacement with equivalent
  behavior.
- **M0-AC7:** No API key, `.env`, generated report, mutable ontology output, or
  test cache is added to the distribution or Git.

### Tasks derived from the acceptance criteria

- [x] **M0-T1 → AC1, AC2:** Add small RDF fixtures representing the exact
  partition, skeleton, and pattern cases currently tested against
  `ontology.ttl`.
- [x] **M0-T2 → AC1, AC2:** Change exact snapshot tests to load fixtures. Keep a
  separate repository-graph smoke test limited to invariants that remain true as
  the user graph grows.
- [x] **M0-T3 → AC3:** Add `pyproject.toml` using standard `[build-system]` and
  `[project]` metadata. Keep runtime dependencies minimal.
- [x] **M0-T4 → AC3:** Move development/test dependencies into a standard
  dependency group. Decide whether `requirements.txt` is temporarily generated
  or removed; document the decision.
  (No dev-only dependencies exist beyond the standard library; the placeholder
  PEP 735 group is documented in `pyproject.toml`, and `requirements.txt` was
  removed.)
- [x] **M0-T5 → AC4, AC6:** Create `src/text_to_ontology/` and move modules in
  small groups while preserving readable imports. Use compatibility wrappers if
  necessary so one move does not require a repository-wide rewrite.
  (Done in one coherent move; root `ontology.py`/`view_ontology.py` wrappers.)
- [x] **M0-T6 → AC5:** Package prompts, SPARQL files, and future shapes using
  package resources rather than paths relative to the working directory.
  (Prompts/SPARQL are Python string constants inside package modules today, so
  they ship in the wheel by definition; no non-Python resource files exist yet.
  The only file-relative resource was `.env`, which is user configuration now
  loaded from the working directory. Revisit when prompts/SPARQL become files.)
- [x] **M0-T7 → AC5:** Add an installation smoke test that imports the package
  from a directory outside the repository.
- [x] **M0-T8 → AC7:** Review `.gitignore` and build inclusion rules.
- [x] **M0-T9 → AC1–AC7:** Update README installation and test commands.

### Required evidence

- [x] Full test output summary:
  `python3 -m unittest discover -s tests -p 'test_*.py'` after
  `pip install -e .` → `Ran 633 tests in 1.4s  OK (skipped=1)`; the one skip is
  the opt-in installation smoke test. The six baseline failures are gone.
- [x] Wheel filename and clean-install command:
  `dist/text_to_ontology-0.1.0-py3-none-any.whl`;
  `python3 -m venv <tmp> && <tmp>/bin/pip install dist/*.whl` then run
  `scripts/install_smoke.sh` (automated by `tests/test_install_smoke.py`,
  env `TEXT_TO_ONTOLOGY_INSTALL_SMOKE=1`).
- [x] Import smoke-test result: with cwd outside the repository, the installed
  package imports and reports `version: 0.1.0` from site-packages.
- [x] List of fixture-backed tests: `MiniatureRepositoryTest` in
  `tests/test_graph_partition.py`, `tests/test_graph_patterns.py`, and
  `tests/test_graph_skeleton.py`, all loading the frozen
  `tests/fixtures/miniature_repository.ttl`. The repository `ontology.ttl` is
  now read only by invariant smoke tests (lossless partitioning, file-untouched).
- [x] `git diff --check` result: clean (no whitespace errors or conflict
  markers).

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m00-packaging-baseline
- Commits: 8b732c5, ae46925, f6297ff, 7c27e2c (+ plan-status update commit)
- Pull request/review: not opened; local branch only
- Files materially changed: all modules moved to `src/text_to_ontology/`;
  root `ontology.py`/`view_ontology.py` are thin wrappers; tests updated to
  package imports plus new fixture and install-smoke test; `pyproject.toml`
  added; `requirements.txt` removed; `.gitignore`, `README.md` updated;
  `scripts/install_smoke.sh` added
- Decisions made:
  - `requires-python = ">=3.12"` — the only version the suite was actually run
    on; no untested version is claimed.
  - `requirements.txt` removed; `pyproject.toml` is the single dependency
    declaration (no dev-only dependencies exist beyond the standard library).
  - Running the suite requires the documented editable install; the discovery
    command itself is unchanged.
  - `.env` is loaded from the working directory instead of beside the module
    file, which keeps the documented workflow after packaging.
  - Restored `report_skeleton` into `view_ontology.py`; the terminal viewer had
    been broken since commit 2f8da8b deleted it from `ontology.py`.
- Known follow-ups: console entry point `[project.scripts]`, public API module,
  and `python3 -m text_to_ontology` belong to M1; no non-Python resource files
  exist yet, so package-resource loading will be exercised when prompts/SPARQL
  become files.
- Acceptance evidence location: this section; full outputs reproducible via
  the commands recorded above.

---

## M1 — Public Python API and thin CLI

### Intended achievement

Create one stable application entry point that can later be called by a CLI,
web app, notebook, or skill. Remove orchestration from argument parsing without
changing current short-source behavior.

### Status

- [ ] Not started  [ ] In progress  [x] Complete

### Acceptance criteria

- **M1-AC1:** The package exposes `run_text_to_graph(request, graph_store,
  extractor, reporter) -> RunResult` from a documented public module.
  (Met: `src/text_to_ontology/api.py` documents and exports it; implemented in
  `pipeline.py`.)
- **M1-AC2:** `RunRequest`, `RunResult`, and module-specific configuration are
  named dataclasses with self-explanatory fields; there is no general untyped
  parameter bag. (Met: `RunRequest`, `RunResult`, `WindowingConfig`,
  `ContextConfig`, `ExtractionConfig`, `MergeConfig` in `pipeline.py`.)
- **M1-AC3:** The core API does not parse command-line arguments, read process
  environment variables, or call `sys.exit`. (Met: `pipeline.py` has none of
  the three; environment loading stays inside the `OpenRouterExtractor`
  adapter in `llm.py`.)
- **M1-AC4:** The installed CLI only parses input, creates configured adapters,
  calls the public API, and translates errors to exit codes. (Met: `cli.py`.)
- **M1-AC5:** A fake extractor and temporary local store can run the full API in
  tests without network access. (Met: `FakeExtractor` in
  `tests/test_pipeline.py`; `LocalTurtleStore` on temp directories.)
- **M1-AC6:** For a short, one-window source, the CLI retains current validation,
  merge-planning, reporting, and atomic-save behavior. (Met: the ported
  `tests/test_pipeline.py` assertions are unchanged in substance.)
- **M1-AC7:** `python3 -m text_to_ontology` and the installed console command call
  the same CLI function. (Met: `OneCliFunctionTest`.)

### Tasks derived from the acceptance criteria

- [x] **M1-T1 → AC2:** Define `RunRequest`, `RunResult`, `WindowingConfig`,
  `ContextConfig`, `ExtractionConfig`, `MergeConfig`, and graph-name settings.
  (`WindowingConfig` holds strategy version 1 = whole-text window until M2;
  graph-name settings are deferred to M3's named-graph store — see decisions.)
- [x] **M1-T2 → AC1, AC3:** Move the readable run loop into `pipeline.py` and
  expose it through `api.py`. (`ontology.py` module removed.)
- [x] **M1-T3 → AC3, AC5:** Define small extractor and reporter protocols based
  on actual calls rather than speculative methods. (`Extractor`: `model()` +
  `extract(prompt)`; `Reporter`: exactly the `RunReporter` call sites.)
- [x] **M1-T4 → AC4, AC7:** Create `cli.py`, `__main__.py`, and a
  `[project.scripts]` entry in `pyproject.toml`
  (`text-to-ontology = "text_to_ontology.cli:main"`).
- [x] **M1-T5 → AC4:** Keep environment loading in the OpenRouter adapter or CLI
  composition root, never in the core pipeline. (`load_env` stays inside
  `model_name()`/`ask_llm()`; the pipeline never touches `os.environ`.)
- [x] **M1-T6 → AC5, AC6:** Port current pipeline tests to the public API with a
  fake extractor and temporary store. (`tests/test_pipeline.py` rewritten.)
- [x] **M1-T7 → AC6, AC7:** Add installed-command tests for success, validation
  failure, missing source, `--report`, and verbose output.
  (`tests/test_cli.py`.)
- [x] **M1-T8 → AC1–AC7:** Document the public API and minimal Python example.
  (README "Call it from Python" section; `api.py` docstring example.)

### Required evidence

- [x] Public API example and returned `RunResult`: README "Call it from
  Python"; `RunResult(graph_path, triples, files_total, files_saved,
  files_blank)`.
- [x] CLI/API equivalence test names: `test_the_module_entry_is_the_cli_function`,
  `test_python_dash_m_prints_usage_without_network_access`,
  `test_the_installed_console_command_prints_the_same_usage` in
  `tests/test_cli.py`; console script also checked by `scripts/install_smoke.sh`.
- [x] Full deterministic test result:
  `python3 -m unittest discover -s tests -p 'test_*.py'` after
  `pip install -e .` → `Ran 641 tests ... OK (skipped=1)`; the skip is the
  opt-in installation smoke test.
- [x] Network calls observed during tests: zero — extraction runs through
  `FakeExtractor` or a patched `llm.ask_llm`; subprocess tests only run
  `--help`.

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m01-public-api-cli
- Commits: pending commit on this branch
- Pull request/review: not opened; local branch only
- Decisions made:
  - Version bumped 0.1.0 → 0.2.0 (new public API + console command).
  - Configuration dataclasses carry only real knobs that exist today:
    `ContextConfig.budget` copies `PROMPT_BUDGET`;
    `MergeConfig.min_auto_accept_confidence` is threaded through
    `plan_graph_merge`/`resolve_entities` with the unchanged default of 0.80;
    `WindowingConfig.strategy_version` documents version 1 (whole-text window)
    until real windowing lands in M2.
  - Graph-name settings deferred to M3: today's `GraphStore` contract is just
    `load(path)`/`save(graph, path)` over one Turtle file; named graphs arrive
    with the RDF dataset milestone.
  - The old package module `ontology.py` was deleted rather than kept as a
    shim; the root `ontology.py` wrapper now calls `cli.main`.
  - Error handling moved into `cli.main`: it prints `Error: ...` to stderr and
    raises `SystemExit(1)` (M1-AC4), so `__main__` needs no try/except of its
    own.
  - `save_graph` now creates missing parent directories itself (moved out of
    the run loop).
- Known follow-ups: `WindowingConfig` becomes meaningful in M2;
  `GraphStore` grows its real contract in M3; prompts/SPARQL as packaged
  resource files remain a future change.
- Acceptance evidence location: this section; outputs reproducible via the
  recorded commands.

---

## M2 — Stable source documents and complete windowing

### Intended achievement

Represent every source as a reproducible document and split long documents into
overlapping windows without losing text. This milestone is source-only: it must
not depend on RDF, the LLM, or the graph store.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [x] Complete

### Acceptance criteria

- **M2-AC1:** `SourceDocument` records a stable content-derived document ID,
  source name, normalized text, media type, and content digest.
- **M2-AC2:** `TextWindow` records a stable window ID, document ID, index, text,
  character offsets, token estimate, and window-strategy version.
- **M2-AC3:** A short source below the target size produces exactly one window
  with the complete source text.
- **M2-AC4:** Long sources split on headings/paragraphs first, sentences second,
  and a hard boundary only when a single sentence cannot fit.
- **M2-AC5:** Configured overlap is present between adjacent windows, but every
  source character outside deliberate normalized line-ending differences is
  covered by at least one window and the document tail is never lost.
- **M2-AC6:** Window IDs and boundaries are deterministic for the same document,
  configuration, tokenizer, and strategy version.
- **M2-AC7:** Token counting is injected. The current character estimator works
  as a fallback and a model-aware tokenizer can be added without changing the
  window algorithm.
- **M2-AC8:** Blank documents produce no extraction windows and a clear skip
  result.
- **M2-AC9:** The windowing module imports neither RDFLib nor an LLM adapter.

### Tasks derived from the acceptance criteria

- [x] **M2-T1 → AC1, AC2:** Implement the source and window dataclasses and
  stable digest rules. Document normalization before hashing.
- [x] **M2-T2 → AC4:** Implement heading/paragraph segmentation and paragraph
  packing.
- [x] **M2-T3 → AC4:** Implement sentence fallback and final hard split for an
  oversized sentence.
- [x] **M2-T4 → AC5:** Implement token-based overlap while preserving offsets.
- [x] **M2-T5 → AC3, AC5, AC6:** Add reconstruction/coverage tests, including a
  unique marker in the final characters of a very long document.
- [x] **M2-T6 → AC6:** Include strategy version and window parameters in the
  stable window ID input.
- [x] **M2-T7 → AC7:** Adapt token-estimator injection already used by prompt
  budgeting.
- [x] **M2-T8 → AC8, AC9:** Add blank and import-boundary tests.
- [x] **M2-T9 → AC1–AC9:** Add fixtures for one short document, a long
  paragraph-based document, one oversized sentence, Unicode, and CRLF input.

### Required evidence

- [x] Source coverage test result:
  `python3 -m unittest discover -s tests -p 'test_*.py'` after `pip install -e .`
  → `Ran 666 tests ... OK (skipped=1)`; the skip is the opt-in install smoke
  test. Coverage tests assert the union of window `[start, end)` spans equals
  the full normalized text for every fixture and for the uploaded long sample
  (41 windows at defaults; 53 at target=600/overlap=60).
- [x] Tail-marker test result: with target=600/overlap=60 the last window of
  the long sample ends `...become bolder builders themselves.` — the document
  tail survives all splits; an oversized-sentence fixture's final words end its
  last window too.
- [x] Determinism test result: two runs give identical IDs/spans; changing
  strategy version, target tokens, or tokenizer *name* (same counts) changes
  every window ID while leaving boundaries intact (`DeterminismTest`).
- [x] Example document/window IDs: document `doc-13ed72f888288435` (digest
  `13ed72f888288435...e752`, media type `text/markdown`); first windows of that
  document: `win-ccc5213fe5b14915`, `win-01b219f82e49ae74`,
  `win-b7b9a77947f744d5`.
- [x] Import-boundary test result: AST scan of `windowing.py` import roots ⊆
  {hashlib, re, dataclasses, pathlib, text_to_ontology}; module source contains
  neither "rdflib" nor "llm" (`ImportBoundaryTest`).

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m02-documents-windowing (to be cut when committing;
  work currently sits on milestone/m01-public-api-cli)
- Commits: pending commit on this branch
- Pull request/review: not opened; local branch only
- Strategy version introduced: 2 (version 1 remains the pipeline's whole-text
  placeholder until per-window orchestration lands in M5)
- Decisions made:
  - New source-only module `src/text_to_ontology/windowing.py`; it imports no
    RDFLib and no LLM adapter, enforced by an AST-based test.
  - Document identity: full SHA-256 over the normalized text is the digest;
    `document_id = "doc-" + digest[:16]`. Normalization is line endings only
    (`\r\n`/`\r` → `\n`), so CRLF/LF twins hash identically.
  - Window identity: SHA-256 over strategy version, target/overlap token
    settings, tokenizer name, document ID, index, and offsets, prefixed
    `win-`.
  - Defaults: target 800 tokens, overlap 100 tokens, using
    `prompt_budget.estimate_tokens` as the injected fallback counter.
  - Segmentation tiles the text exactly — blocks absorb trailing blank lines,
    and heading gaps are closed into the preceding span — so coverage holds by
    construction rather than by repair.
  - The sentence splitter is deliberately plain (sentence-ending punctuation
    followed by whitespace/end); abbreviations like "J.D." may split. Simple
    and reproducible beats linguistically clever.
  - A blank (whitespace-only) document yields an empty window list; that empty
    list is the documented skip result.
  - The user-supplied long input was copied to
    `tests/fixtures/documents/long_article.md` so the deterministic suite stays
    self-contained; `sources/` remains user data.
- Known follow-ups: wire real windows into the pipeline loop and make
  `pipeline.WindowingConfig` delegate to this module (M5); richer media-type
  detection if ever needed.
- Acceptance evidence location: this section; outputs reproducible via the
  recorded commands.

---

## M3 — Local RDF dataset and graph-store boundary

### Intended achievement

Replace direct file ownership in domain modules with a small store API and use an
RDFLib dataset with named graphs locally. Preserve safe local persistence and
human-readable RDF import/export.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [x] Complete

### Acceptance criteria

- **M3-AC1:** A small `GraphStore` contract supports focused SPARQL query/update,
  graph get/put/delete, and one publication operation with atomic semantics.
- **M3-AC2:** `RdflibGraphStore` implements the contract using
  `rdflib.Dataset` and passes a backend-independent store contract suite.
- **M3-AC3:** Graph roles are explicit configuration: schema graphs, shape
  graphs, data graphs, target graph, provenance graph, review graph, and source
  staging graph namespace.
- **M3-AC4:** Domain modules do not open paths, parse Turtle, serialize RDF, or
  know whether the store is local or remote.
- **M3-AC5:** The current combined `ontology.ttl` can be imported without data
  loss into configured named graphs through an explicit compatibility/import
  operation.
- **M3-AC6:** One named graph can be exported as Turtle; the complete dataset can
  be exported as TriG or N-Quads and round-tripped isomorphically.
- **M3-AC7:** Failed local publication leaves the previous persisted dataset
  usable and unchanged.
- **M3-AC8:** Read-only store operations cannot accidentally call an update path
  in tests.

### Tasks derived from the acceptance criteria

- [x] **M3-T1 → AC1:** Define the smallest store protocol required by existing
  use cases. Avoid backend-specific methods in public signatures.
- [x] **M3-T2 → AC2, AC8:** Write the store contract tests before implementing
  the RDFLib adapter.
- [x] **M3-T3 → AC2:** Implement in-memory and persisted RDFLib dataset modes.
- [x] **M3-T4 → AC3:** Define `GraphNames` configuration and graph-name
  validation in one place.
- [x] **M3-T5 → AC4:** Move parse/serialize/file behavior out of graph domain
  modules and into the adapter/import-export boundary.
- [x] **M3-T6 → AC5:** Implement an explicit legacy Turtle importer. Use the
  existing partitioner only for migration/compatibility, not as the normal
  dataset role mechanism.
- [x] **M3-T7 → AC6:** Implement Turtle, TriG, and N-Quads export/round-trip
  tests.
- [x] **M3-T8 → AC7:** Retain copy-plus-atomic-replace behavior for local
  persistence and test injected serialization/persistence failures.
- [x] **M3-T9 → AC1–AC8:** Update the viewer to accept configured named graphs or
  a legacy Turtle import without changing the stored dataset.

### Required evidence

- [x] Store contract test names and result:
  `tests/store_contract.py` defines the backend-independent cases — fresh-store
  emptiness, put/get isomorphic round trip, isolated `get` copies,
  replace-whole puts, deletion, graph-name listing, cross-graph SPARQL query,
  bound-variable query, SPARQL Update into one named graph, atomic
  publication bundles, no-change publish (`StoreContract`), plus read-only
  wrapper rules hiding every write path while reads still work
  (`ReadOnlyRules`). They run unchanged against both adapters as
  `InMemoryStoreTest` and `PersistedStoreTest`. Full suite:
  `python3 -m unittest discover -s tests -p 'test_*.py'` →
  `Ran 706 tests ... OK (skipped=1)`.
- [x] Legacy import triple/quad comparison:
  `test_every_legacy_triple_lands_in_exactly_one_configured_graph` imports
  `tests/fixtures/miniature_repository.ttl`; schema + instance + support counts
  sum to exactly the legacy triple count, and the union of the three named
  graphs is isomorphic to the source.
- [x] TriG/N-Quads round-trip result: `ExportRoundTripTest` exports two named
  graphs through TriG and N-Quads; both formats reimport with identical graph
  names and per-graph isomorphism; single-graph Turtle export round-trips too;
  unknown formats raise ValueError.
- [x] Injected publication-failure result:
  `test_a_failed_publication_keeps_the_previous_file_and_memory` patches
  `Graph.serialize` to raise "disk full": publish raises, the previous `.trig`
  bytes are unchanged, no `.tmp` file remains, the in-memory dataset is
  untouched, and a later successful publish persists new content.
- [x] Search showing domain modules no longer open/parse graph files:
  `grep -n "\.parse(\|\.serialize(\|read_text\|write_text\|open(" src/text_to_ontology/*.py`
  excluding the store/adapter/viewer/CLI files shows only
  `ingest_sources.py:23` and `windowing.py:116`, which read *source text*
  files, never graphs. RDF parse/serialize now lives only in
  `graph_management.py` (legacy Turtle adapter), `graph_store.py` (the
  boundary), and the viewer/CLI adapters.

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m03-local-graph-store
- Commits: pending commit on this branch
- Pull request/review: not opened; local branch only
- Dataset persistence format: rdflib `Dataset` (default_union=True), serialized
  as TriG to a temporary sibling file and moved into place with `os.replace`.
- Decisions made:
  - The contract is `get`/`put`/`delete`/`graph_names`/`query`/`update`/
    `publish(Publication)` in `graph_store.py`. `put`/`delete` are in-memory
    staging; durability happens only through `publish` - one explicit atomic
    step, matching AC1's single publication operation.
  - `get` returns an isolated copy so callers can never mutate stored state by
    accident; contract-tested.
  - Publication failure safety: the changes are applied to a clone, serialized,
    and only then applied to the live dataset - so a failed serialization or
    write leaves both file and memory unchanged (AC7).
  - `GraphNames` holds every role from AC3 (schema/shape/data lists, target,
    provenance, review, staging namespace), validates uniqueness and namespace
    shape in one method, and derives source staging graph names per document ID
    for M5.
  - Read-only enforcement is a wrapper class exposing only reads (AC8): it has
    no put/delete/update/publish attributes at all, tested.
  - Legacy import maps partitioner output losslessly: schema structure →
    schema graph, instance data → target graph, support material (ontology
    header, SHACL shapes, audit records, unclassified) → provenance graph. The
    partitioner is used for migration only, per the plan.
  - The viewer accepts a `.trig` dataset (union of all named graphs, or one
    selected via `-g/--named`) wrapped read-only, or any legacy `.ttl` file as
    before; viewing cannot change what is stored.
  - `tests/` became a package (`__init__.py`) so the contract mixin can be
    shared by future adapter test modules.
  - The pipeline keeps `LocalTurtleStore` for this milestone; moving the run
    loop onto named graphs belongs to M5/M7 windowed orchestration.
- Known follow-ups: migrate pipeline and merge/reporting paths onto
  `RdflibGraphStore` when windowed processing lands (M5/M7); whole-dataset
  serialization on each publish is fine at current scale but should be revisited
  in M12 if it dominates runtime.
- Acceptance evidence location: this section; outputs reproducible via the
  recorded commands.

---

## M4 — Window candidate RDF and standards-based confidence

### Intended achievement

Convert each structurally valid LLM response into an inspectable RDF graph before
any merge. Preserve per-record extraction confidence using standard RDF,
PROV-O, and DQV terms without inventing infrastructure predicates.

### Status

- [ ] Not started  [ ] In progress  [x] Complete

### Acceptance criteria

- **M4-AC1:** The extraction adapter still accepts the explicit JSON response
  contract; untrusted JSON cannot write any graph.
- **M4-AC2:** Valid normalized records produce a window candidate graph with
  deterministic provisional IRIs for unresolved individuals.
- **M4-AC3:** Candidate triples use configured existing schema IRIs where known,
  RDF types instead of a string-valued kind in RDF, SKOS/RDFS labels according to
  their meanings, and XSD datatypes for safely recognized values.
- **M4-AC4:** Each extraction record is represented as a standard
  `prov:Collection` whose statement members are identified using RDF 1.1
  reification. The source assertion itself is also present in the candidate
  graph; reification alone is not treated as assertion.
- **M4-AC5:** Each record's extraction confidence is a
  `dqv:QualityMeasurement` computed on that record collection, measured against
  a project-owned instance of `dqv:Metric`, and stored as `xsd:decimal` in
  `[0,1]`.
- **M4-AC6:** The source document, source window, extraction activity, extractor
  software agent/model, candidate record, and confidence measurement are linked
  with PROV-O.
- **M4-AC7:** Extraction confidence, identity score, and merge decision remain
  separate fields/concepts. No code derives one from another.
- **M4-AC8:** Candidate RDF plus its provenance/measurement metadata round-trips
  without losing the association between JSON record, emitted triples, source
  window, and confidence.
- **M4-AC9:** No custom RDF class or property is introduced for candidate,
  confidence, provenance, validation, workflow, or merge status.

### Tasks derived from the acceptance criteria

- [x] **M4-T1 → AC1:** Keep and test the current response-validation gate as the
  only path into candidate graph construction.
  (The gate is unchanged; `build_candidate_graph` accepts only the normalized
  package that `validate_candidates` returns, and repair never bypasses it.)
- [x] **M4-T2 → AC2, AC3:** Define deterministic provisional IRI and vocabulary
  mapping rules. Make blank-node avoidance explicit for candidate individuals.
  (Provisional IRIs are `.../provisional/{document_id}/{local_id}`; all record,
  statement, and measurement resources use deterministic IRIs — no blank nodes.)
- [x] **M4-T3 → AC3:** Add conservative literal datatype parsing and tests for
  dates, integers, decimals, booleans, strings, invalid dates, and leading-zero
  identifiers.
- [x] **M4-T4 → AC4:** Implement record collections and RDF 1.1 statement
  reification using only RDF/PROV terms.
- [x] **M4-T5 → AC5:** Define the extraction-confidence metric as an instance of
  `dqv:Metric`; add measurement construction and range tests.
  (Metric IRI: `http://example.org/text-ontology/metric/extraction-confidence`.)
- [x] **M4-T6 → AC6:** Build the PROV-O chain from document/window through
  extraction activity to candidate record and measurement.
- [x] **M4-T7 → AC7:** Rename ambiguous existing fields so extraction confidence
  and identity similarity cannot be confused.
  (Identity decisions now carry `identity_score`; extraction records keep
  `confidence`. No code derives one from the other.)
- [x] **M4-T8 → AC8:** Add serialization and parse-back tests with multiple
  records supporting the same RDF triple at different confidence values.
- [x] **M4-T9 → AC9:** Add a vocabulary allow-list test for infrastructure
  predicates/classes while allowing project-owned domain terms and resource
  identifiers.
- [x] **M4-T10 → AC1–AC9:** Document the candidate graph with one complete Turtle
  example and explain that DQV is the selected interoperable pattern, not a
  universal confidence law. (`docs/candidate_graph.md`.)

### Required evidence

- [x] Candidate Turtle example: `docs/candidate_graph.md`, generated from the
  module's output for one entity plus one date fact; shows assertions,
  reified evidence, DQV measurements, metric declaration, and PROV chain.
- [x] JSON-to-RDF round-trip test result:
  `RoundTripTest.test_turtle_round_trip_is_isomorphic` serializes a built
  candidate graph to Turtle, parses it back, and asserts full isomorphism;
  `..._evidence_still_points_at_its_triple` verifies a record's reified member
  still names an asserted triple after the round trip. Full suite:
  `python3 -m unittest discover -s tests -p 'test_*.py'` →
  `Ran 732 tests ... OK (skipped=1)`.
- [x] Confidence range/type test result:
  `ConfidenceMeasurementTest` asserts every record has exactly one
  `dqv:QualityMeasurement` with `dqv:value` typed `xsd:decimal` in `[0,1]`,
  pointing at the project-owned `dqv:Metric`.
- [x] Vocabulary allow-list result:
  `VocabularyTest.test_only_allowed_predicates_appear` walks every triple of a
  built graph and requires each predicate to be one of the allowed standard
  terms (RDF/RDFS/SKOS/PROV/DQV) or a generated domain property (class:/fact:/
  relation:) — no custom infrastructure predicates;
  `test_kind_strings_became_types_not_literals` confirms kinds are types.
- [x] Example showing two independent confidence measurements for one triple:
  `AssertionAndEvidenceTest.test_two_records_can_support_one_triple_at_
  different_confidence` builds a package where two relation records assert the
  identical triple with confidences 0.85 and 0.55; both record collections
  reify it and two separate measurements carry the two values.

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m04-candidate-rdf-confidence
- Commits: pending commit on this branch
- Pull request/review: not opened; local branch only
- Candidate mapping version: 1 (`CANDIDATE_MAPPING_VERSION`)
- Metric IRI: `http://example.org/text-ontology/metric/extraction-confidence`
- Decisions made:
  - New module `candidate_graph.py`: validated package in, deterministic RDF
    graph out. It has no path to raw LLM answers; only `validate_candidates`
    output reaches it (AC1).
  - All candidate resources get deterministic IRIs under
    `http://example.org/text-ontology/` (candidate/, provisional/, document/,
    window/, activity/, agent/, metric/); blank nodes are avoided entirely so
    graphs can be compared and merged by IRI later.
  - Kinds map to generated class IRIs typed `owl:Class` with
    `rdfs:subClassOf onto:Entity`, mirroring what merge policy declares today;
    the string-valued kind literal is gone from candidate graphs.
  - Conservative literals: ISO calendar dates → `xsd:date`, JSON bool/int/
    finite float → their XSD types via `Decimal(str(v))` for floats; leading
    zero strings and impossible dates stay plain literals.
  - User-requested early delivery of bounded self-repair (originally M6-T1/T2):
    new `repair.py` coordinator sends the model its own original answer plus
    the deterministic issue list up to `ExtractionConfig.repair_attempts`
    times (default 2). Unparseable answers surface as the new
    `llm.InvalidResponseError` (a `RuntimeError`) and become repair prompts
    quoting the raw text; network failures propagate untouched. Repaired
    answers pass through exactly the same validation gate; exhausted attempts
    reject the window as before. Two pipeline tests were updated to disable
    repair explicitly since they encode immediate-rejection semantics.
  - Identity similarity renamed to `identity_score` across entity_lookup /
    reports / merge-policy tests (AC7): `confidence` is now exclusively
    extraction confidence.
  - rdflib does not bundle a DQV namespace, so the W3C namespace is defined
    locally in one place.
- Known follow-ups: the pipeline still merges candidates through the legacy
  direct path; wiring candidate graphs into source staging graphs and per-window
  admission belongs to M5/M7. The verbose reporter prints final validation
  counts only, not per-repair-attempt detail.
- Acceptance evidence location: this section; outputs reproducible via the
  recorded commands.

---

## M5 — Incremental source graph across all windows

### Intended achievement

Process every window into one source-local graph while leaving the final
ontology unchanged. Later windows must benefit from earlier source-local
knowledge, and the completed source graph must be inspectable before any final
identity resolution or publication.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [x] Complete

### Acceptance criteria

- **M5-AC1:** Processing a non-empty document creates one stable source staging
  graph before its first window.
- **M5-AC2:** Each window creates its own candidate graph, validates it, and then
  performs a source-local admission plan against the current source graph.
- **M5-AC3:** Source-local admission may reconcile provisional entities against
  earlier windows of the same document, but it does not perform final identity
  resolution against canonical individuals.
- **M5-AC4:** Context for window N may read schema/shape/final graphs and the
  source graph through window N-1, but the source graph contains only assertions
  supported by this source document.
- **M5-AC5:** No target, provenance, or final review graph changes after any
  individual window. A quad-level snapshot before the document equals the
  snapshot after every pre-publication window.
- **M5-AC6:** A later window can refer to a provisional entity created by an
  earlier window without creating a duplicate when exact local identity evidence
  is unambiguous.
- **M5-AC7:** Ambiguous local identity and explicit local conflicts are retained
  for document reconciliation rather than silently resolved.
- **M5-AC8:** A window failure leaves final graphs unchanged and records whether
  the source staging graph was retained for diagnosis or discarded according to
  explicit configuration.
- **M5-AC9:** A directory processes each file as a separate source graph and
  never combines files merely because they share a parent directory.
- **M5-AC10:** Reporter output clearly distinguishes window candidate counts,
  source-graph growth, and final publication counts.

### Tasks derived from the acceptance criteria

- [x] **M5-T1 → AC1, AC9:** Add deterministic source graph naming from document
  digest and graph namespace configuration.
  (`source_staging.source_staging_graph_name` / `window_candidate_graph_name`
  under `.../text-ontology/staging/{document_id}[/{window_id}]`; the document
  ID is already the content digest prefix.)
- [x] **M5-T2 → AC2:** Add a readable per-window orchestration loop inside the
  per-document loop. (`pipeline._process_document`: staging dataset, one
  candidate graph + admission plan + snapshot check per window.)
- [x] **M5-T3 → AC2, AC3:** Extract the current identity/merge rules into a
  source-local admission policy that sees only the source graph for individual
  identity decisions. (`plan_window_admission` reuses merge policy with a
  provisional allocator; canonical resources are absent from the staging
  catalog, so existing_id hints cannot resolve there.)
- [x] **M5-T4 → AC3, AC4:** Store canonical identity hints from prompt context as
  operational merge hints, not as already-decided canonical mappings in the
  source graph.
  (Hints survive only inside audit records (`onto:normalizedCandidate`) of the
  staging graph and drive final publication planning; staged entity URIs are
  always provisional.)
- [x] **M5-T5 → AC4:** Extend context selection inputs with the source graph and
  mark source-local versus canonical context clearly in prompt rendering.
  (`layered_context_text`: two selection packages, one shared budget,
  source-local lines prefixed `(this document)`, provisional resources never
  offered as `existing_id`.)
- [x] **M5-T6 → AC5, AC8:** Add final-graph snapshot assertions around every
  window success and failure path.
  (`final_graphs_snapshot` compared after every window inside
  `_process_document`; failure-path file-immutability covered by tests.)
- [x] **M5-T7 → AC6, AC7:** Add fixtures where an entity crosses a window
  boundary, has an exact repeated name, has an alias, and has an ambiguous name.
  (`tests/test_source_staging.py` repeated-name/kind-collision cases;
  `tests/test_pipeline_windowing.py` cross-window Acme Corp fixture.)
- [x] **M5-T8 → AC8:** Define staging retention configuration and cleanup rules.
  (`ProcessingConfig.retain_staging_on_failure`; default discards in-memory
  staging, retention exports `<graph>.staging/<document_id>.trig`.)
- [x] **M5-T9 → AC9:** Add a two-file directory test proving separate source
  graphs and ordered per-document handling. (`DirectorySeparationTest`.)
- [x] **M5-T10 → AC10:** Update verbose/report output with document/window/source
  graph terminology. (`RunReporter.document_staging`, `.window_started`,
  `.window_admitted`, `.staging_failed`; publication counts unchanged.)

### Required evidence

- [x] Multi-window source graph triple/quad summary: a four-paragraph fixture
  (target 60 tokens, no overlap) produced 6 windows. Window 1 admitted 1 new
  entity and grew the source staging graph to 25 triples; windows 2–6 repeated
  the same exact name, were corroborated locally (`0 new entities` each), and
  the source graph ended at 42 triples (growth is audit/evidence only — no
  duplicate domain assertions). Reporter lines: `Document doc-…: 6 window(s);
  staging graph …/staging/doc-…`, `Window k/6 admitted …`.
- [x] Final graph before/after-each-window equality evidence:
  `FinalOntologyUntouchedTest` shows the output file does not even exist while
  any window runs, and that document two observes only document one's
  publication throughout its windows. Additionally `_process_document` takes a
  `final_graphs_snapshot` before window 1 and raises
  "the final ontology changed during window processing" if it ever differs.
- [x] Cross-window identity test result:
  `AdmissionTest.test_a_repeated_exact_name_from_an_earlier_window_resolves`
  (second window's record resolves `existing`/`exact_name` to the first
  window's provisional IRI) and
  `CrossWindowIdentityTest` at pipeline level (`Window 1/6 admitted 1 new`,
  windows 2–6 admit 0 new).
- [x] Ambiguous local identity test result:
  `AdmissionTest.test_a_local_name_collision_is_retained_not_silently_resolved`:
  two same-name/different-kind records stage exactly one entity; the colliding
  record is retained with `identity.kind_collision`; a later window mentioning
  the colliding name is held again instead of silently merged.
- [x] Window-failure retention/cleanup results: `WindowFailureTest`. Default:
  failure propagates, the final file does not exist/is unchanged, no sidecar is
  written, reporter prints `Staging graphs of doc-… discarded`. With
  `retain_staging_on_failure=True`: `graph.ttl.staging/doc-….trig` exists,
  contains the `staging/doc-…` graphs, parses as TriG, and reporter prints
  `retained for diagnosis`.

Full deterministic suite: `python3 -m unittest discover -s tests -p 'test_*.py'`
→ `Ran 757 tests ... OK (skipped=1)`; the skip is the opt-in install smoke test.

### Completion record

- Owner: ox-alpha coding agent
- Started: 2026-08-24
- Completed: 2026-08-24
- Branch: milestone/m05-incremental-source-graph
- Commits: pending commit on this branch
- Pull request/review: not opened; local branch only
- Source graph naming version: 1
  (`.../text-ontology/staging/{document_id}` for the source graph,
  `.../{document_id}/{window_id}` for window candidate graphs)
- Decisions made:
  - New module `source_staging.py`; admission reuses merge policy unchanged
    except for URI allocation: new staged entities get deterministic
    provisional IRIs `provisional/{document_id}/{slug}[-n]` via
    `merge_policy.plan_graph_merge(..., allocate_uri=...)` (the planner now
    accepts injected allocators; defaults preserve canonical behavior).
  - The staging area is an in-memory `RdflibGraphStore` per run holding one
    source staging graph plus one M4 candidate graph per window under stable
    names; it is discarded unless retention is configured (AC8), in which case
    a failed document's graphs are atomically exported to a TriG sidecar next
    to the output graph.
  - Canonical `existing_id` hints never resolve inside staging (canonical
    resources are not in its catalog); they survive in audit records and still
    drive final publication planning (M5-T4).
  - Prompt context for window N layers two selection packages into one shared
    budget: canonical context plus source-graph context with every line marked
    `(this document)`; provisional resources render as generic URIs, never as
    reusable `existing_id` values (M5-T5).
  - Interim publication remains the direct per-window merge against the
    complete canonical graph, saved once per completed document; it is clearly
    marked as the path M7 replaces with one document-level transaction.
    User-facing behavior for short (one-window) documents is unchanged.
  - `RunResult` gained `windows_processed`; `pipeline.WindowingConfig` now
    carries real target/overlap/tokenizer settings and feeds `plan_windows`
    directly.
  - A blank document still produces no windows and no staging work; the
    snapshot guard makes mid-document canonical drift an explicit error.
- Known follow-ups: replace the interim direct publication with the single
  document-level read-only plan + atomic transaction (M7); remap reified
  candidate statements/DQV measurements onto canonical evidence (M7-T7);
  persist staging graphs through the configured store rather than in-memory
  when a use case demands cross-run inspection.
- Acceptance evidence location: this section; outputs reproducible via the
  recorded commands and fixtures.

---

## M6 — Complete-source reconciliation, repair, and validation

### Intended achievement

Turn the incrementally admitted source graph into one coherent document-level
proposal. Repair malformed model responses in a bounded way, reconcile overlap
duplicates and local conflicts, validate the complete result, and stop before
the final ontology is touched.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M6-AC1:** A structurally invalid LLM response receives at most the configured
  number of repair attempts using the original response and deterministic issue
  list; final failure rejects that window.
- **M6-AC2:** Repair never bypasses normal response validation or changes already
  admitted earlier windows.
- **M6-AC3:** Exact overlap duplicates become multiple provenance supports for
  one source-graph assertion rather than duplicate assertions.
- **M6-AC4:** Document reconciliation produces an explicit report for local
  entities, aliases, duplicate assertions, unresolved identities, and conflicts.
- **M6-AC5:** The complete source graph is validated against every configured
  applicable SHACL shape graph before final merge planning.
- **M6-AC6:** SHACL non-conformance prevents final planning but leaves the source
  graph and machine-readable validation report inspectable.
- **M6-AC7:** Source-graph serialization is deterministic modulo RDF graph
  canonicalization, and an export can be associated with document digest,
  window-strategy version, candidate-mapping version, and extractor identity.
- **M6-AC8:** The final ontology remains quad-identical through all repair,
  reconciliation, and source-validation success/failure paths.

### Tasks derived from the acceptance criteria

- [ ] **M6-T1 → AC1, AC2:** Add a bounded repair coordinator around extraction
  response validation. Use the existing JSON contract for repaired output.
- [ ] **M6-T2 → AC1:** Add tests for first-repair success, exhausted repairs,
  invalid repaired JSON, and network failure during repair.
- [ ] **M6-T3 → AC3:** Reconcile duplicate record collections while retaining
  every independent PROV/DQV evidence record.
- [ ] **M6-T4 → AC4:** Define and implement a plain document reconciliation
  report; do not create an RDF workflow vocabulary for the report.
- [ ] **M6-T5 → AC5, AC6:** Add the SHACL adapter and combine configured shape
  graphs explicitly for source validation.
- [ ] **M6-T6 → AC5:** Add shape fixtures for valid data, a missing required
  label, datatype mismatch, and constraints spread across multiple shape graphs.
- [ ] **M6-T7 → AC6:** Persist or return the standard SHACL validation report in
  the run result without publishing source assertions.
- [ ] **M6-T8 → AC7:** Add source-graph canonical digest/export metadata and
  deterministic tests.
- [ ] **M6-T9 → AC8:** Add final-dataset equality assertions to every new failure
  path.

### Required evidence

- [ ] Repair-attempt test matrix:
- [ ] Duplicate assertion with multiple provenance supports example:
- [ ] SHACL valid/non-conformant results:
- [ ] Complete source graph export path or returned artifact:
- [ ] Final graph immutability result:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- SHACL dependency/configuration:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M7 — One document-level final merge and publication

### Intended achievement

Resolve the complete source graph against the final ontology once, produce one
read-only merge plan, validate the proposed result, and publish accepted domain
triples plus provenance/review information in one atomic document transaction.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M7-AC1:** Final identity resolution runs once per document after source
  reconciliation and searches the complete configured canonical identity scope.
- **M7-AC2:** Every provisional source entity receives an explicit existing/new/
  review decision with reason codes in the operational merge report.
- **M7-AC3:** Decision precedence preserves current safe behavior: ambiguous
  identity review; exact triple corroboration; explicit OWL functional or
  inverse-functional conflict review; confidence threshold; otherwise accept.
- **M7-AC4:** A dry run returns the exact merge plan and validation result that
  would be published while leaving all final graphs unchanged.
- **M7-AC5:** The proposed post-merge data is SHACL-validated before publication.
- **M7-AC6:** Publication is called exactly once for a successful source document
  and updates target, provenance, and review graphs atomically.
- **M7-AC7:** An injected failure before or during publication leaves every final
  graph unchanged and usable.
- **M7-AC8:** Exact existing triples are not re-added but receive additional
  source/window provenance and retain their independent confidence measurements.
- **M7-AC9:** Confidence is not collapsed into one canonical-triple number. A
  canonical assertion can be supported by multiple source-specific DQV
  measurements.
- **M7-AC10:** Re-running the same document/configuration is idempotent for domain
  triples and deterministic evidence identifiers.
- **M7-AC11:** With a directory input, each completed file has one publication
  transaction, and file N+1 reads final knowledge published by file N.

### Tasks derived from the acceptance criteria

- [ ] **M7-T1 → AC1, AC2:** Adapt identity resolution to consume the complete
  source graph and return a source-IRI-to-canonical-IRI mapping plan.
- [ ] **M7-T2 → AC3:** Port current merge-policy precedence into document-level
  tests before replacing the old per-file candidate package path.
- [ ] **M7-T3 → AC4:** Add dry-run to `RunRequest`, API result, reporter, and CLI.
- [ ] **M7-T4 → AC5:** Build a proposed union/delta view for SHACL validation
  without mutating the store.
- [ ] **M7-T5 → AC6:** Compile target/provenance/review changes into one store
  publication operation.
- [ ] **M7-T6 → AC7:** Inject plan, validation, serialization, and publication
  failures and compare all named graphs before/after.
- [ ] **M7-T7 → AC8, AC9:** Remap reified source statements and DQV measurements
  to canonical triple evidence without losing source-specific occurrences.
- [ ] **M7-T8 → AC10:** Use document/configuration/package digests for stable
  event and evidence identifiers; add exact rerun tests.
- [ ] **M7-T9 → AC11:** Add a two-document test showing exactly two ordered
  publications and growing final context only between documents.
- [ ] **M7-T10 → AC1–AC11:** Remove or clearly mark the legacy direct merge path
  after all compatibility tests use document-level publication.

### Required evidence

- [ ] Publisher call-count tests:
- [ ] Dry-run equality/no-write result:
- [ ] Identity decision fixture results:
- [ ] Injected atomic-publication failure result:
- [ ] Multi-source confidence/provenance query result:
- [ ] Exact rerun result:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Merge-policy version:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M8 — SPARQL context and parameterized skeleton over named graphs

### Intended achievement

Make context and identity access scale beyond an in-memory full graph. Query
explicit lists of schema, shape, final data, and source graphs with focused
SPARQL while preserving current selection/budget semantics.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M8-AC1:** `ContextConfig` explicitly selects schema graphs, shape graphs,
  data graphs, source graph inclusion, hierarchy hops, instance hops, per-kind
  caps, observed-pattern inclusion, and token budget.
- **M8-AC2:** Context selection uses focused store queries and does not fetch or
  materialize the complete final data graph for each window.
- **M8-AC3:** The skeleton provider has one simple replaceable function contract
  and its default strategy returns only explicit class/property declarations,
  labels, subclass/domain/range, and complete supported restrictions.
- **M8-AC4:** The skeleton performs no inference and never promotes observed
  patterns into declared RDFS/OWL/SHACL.
- **M8-AC5:** Context still separates declared structure, observed evidence,
  canonical resources, source-local resources, and examples when rendered.
- **M8-AC6:** Relevance selection still precedes budget packing, and items plus
  their dependencies remain all-or-nothing under the budget.
- **M8-AC7:** Only canonical entity IRIs actually rendered to the model may be
  returned as explicit existing-identity hints. Final merge identity search is
  still complete and independent of prompt inclusion.
- **M8-AC8:** SPARQL templates are packaged resources with descriptive names;
  source text is passed through safe bindings or RDF terms, never concatenated
  into queries.
- **M8-AC9:** The same context contract tests pass against the RDFLib store and
  are ready to run unchanged against a remote adapter.

### Tasks derived from the acceptance criteria

- [ ] **M8-T1 → AC1:** Finish explicit context/graph configuration and validation.
- [ ] **M8-T2 → AC2:** Inventory current full-graph scans and replace them with
  bounded queries, starting with labels/types and exact identity candidates.
- [ ] **M8-T3 → AC3, AC4:** Define and implement `select_skeleton(...)` with the
  explicit-only default strategy.
- [ ] **M8-T4 → AC5:** Include source-local context as a separate rendered
  section without leaking staging status into domain RDF vocabulary.
- [ ] **M8-T5 → AC6, AC7:** Port existing context priority, dependency, budget,
  and allowed-existing-ID tests unchanged where possible.
- [ ] **M8-T6 → AC8:** Move SPARQL text into packaged resource files and add
  unsafe-input tests using quotes, braces, Unicode, and SPARQL-looking source
  text.
- [ ] **M8-T7 → AC9:** Add backend-independent context query fixtures to the
  store contract suite.
- [ ] **M8-T8 → AC2:** Add query diagnostics sufficient to show selected graph
  names and bounded result counts without logging raw source text by default.

### Required evidence

- [ ] Full-graph scan inventory before/after:
- [ ] Context equivalence tests:
- [ ] No-inference/declared-vs-observed tests:
- [ ] Unsafe source-text SPARQL test result:
- [ ] Query diagnostics example:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Skeleton strategy version:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M9 — Separate seed-graph tool

### Intended achievement

Remove implicit seed creation from normal extraction and provide a separate,
explicit tool for importing/building schema and shape graphs with validation and
a dry-run plan.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M9-AC1:** The normal text-extraction command never silently creates an
  ontology or SHACL seed when configured graphs are missing.
- **M9-AC2:** A separate seed API and CLI command can import multiple RDF schema
  files and multiple SHACL shape files into explicitly named graphs.
- **M9-AC3:** The tool validates RDF syntax, graph-name configuration, vocabulary
  role compatibility, and SHACL shape usability before writing.
- **M9-AC4:** Dry run shows input graphs, destination graph names, triple counts,
  validation results, and overwrite/add behavior without changing the store.
- **M9-AC5:** Write mode uses one atomic store publication operation and refuses
  destructive replacement unless explicitly requested.
- **M9-AC6:** The tool can export imported schema/shape graphs as Turtle and the
  complete seed dataset as TriG/N-Quads.
- **M9-AC7:** The seed tool does not ingest ordinary documents, call the
  extraction model, run normal fact merging, or promote observed patterns.
- **M9-AC8:** The current eight-triple seed can be supplied as an explicit
  compatibility fixture/template, not hidden application behavior.

### Tasks derived from the acceptance criteria

- [ ] **M9-T1 → AC1:** Change missing-graph behavior to a clear error that points
  to the seed command.
- [ ] **M9-T2 → AC2:** Add seed request/result dataclasses and one public seed
  function using the existing graph store.
- [ ] **M9-T3 → AC2, AC8:** Package the legacy seed as an explicit optional RDF
  resource.
- [ ] **M9-T4 → AC3:** Implement syntax/role/shape preflight validation.
- [ ] **M9-T5 → AC4:** Implement deterministic seed plan and dry-run reporting.
- [ ] **M9-T6 → AC5:** Implement atomic add/replace publication with explicit
  overwrite authorization and tests.
- [ ] **M9-T7 → AC6:** Reuse graph export functions from M3.
- [ ] **M9-T8 → AC7:** Add tests proving no extractor is constructed or called.
- [ ] **M9-T9 → AC1–AC8:** Add README examples for empty store, custom schema,
  multiple shapes, dry run, and export.

### Required evidence

- [ ] Missing-seed error example:
- [ ] Multi-schema/multi-shape import result:
- [ ] Dry-run no-change result:
- [ ] Refused overwrite and explicit overwrite results:
- [ ] No-extractor-call test:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Seed template/version:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M10 — Apache Jena Fuseki/TDB2 adapter

### Intended achievement

Run the same public pipeline against a remote Jena-backed RDF dataset without
changing source, context, validation, identity, or merge domain modules.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M10-AC1:** `FusekiGraphStore` satisfies the same backend-independent store
  contract suite as `RdflibGraphStore`, except explicitly documented backend
  capabilities.
- **M10-AC2:** Focused reads use the SPARQL Query protocol, mutations use SPARQL
  Update, and bulk named-graph transfer uses the Graph Store Protocol.
- **M10-AC3:** One document publication is atomic. Prefer one SPARQL Update
  request containing the complete accepted/review/provenance change or another
  demonstrably transactional Jena operation; do not simulate a transaction with
  several unprotected HTTP writes.
- **M10-AC4:** Network timeouts, authentication failures, malformed responses,
  query failures, and update failures become concise application errors without
  leaking credentials.
- **M10-AC5:** A local Fuseki integration fixture can create an isolated dataset,
  import schema/shapes/data, run the pipeline with a fake extractor, verify
  named-graph results, and clean up its own test data.
- **M10-AC6:** The adapter never downloads the whole final dataset for routine
  context or identity operations.
- **M10-AC7:** Running the same deterministic fixture against RDFLib and Fuseki
  yields isomorphic accepted/source/provenance/review graph results, allowing for
  documented serialization differences.
- **M10-AC8:** Jena is optional. Installing and using the local RDFLib backend
  does not require Java, Fuseki, or Jena-specific Python dependencies.

### Tasks derived from the acceptance criteria

- [ ] **M10-T1 → AC1:** Parameterize the existing store contract suite and list
  any capability differences before implementation.
- [ ] **M10-T2 → AC2:** Implement query, update, and graph-store HTTP operations
  behind the store boundary.
- [ ] **M10-T3 → AC3:** Implement atomic publication as a single server-side
  operation and add a forced-failure integration test.
- [ ] **M10-T4 → AC4:** Add timeouts, authentication configuration, status/body
  error handling, and secret-redaction tests.
- [ ] **M10-T5 → AC5:** Add a documented local Fuseki test setup that uses an
  isolated dataset and does not target a developer's real data.
- [ ] **M10-T6 → AC6:** Add request tracing in integration tests and assert that
  routine operations do not call full dataset export endpoints.
- [ ] **M10-T7 → AC7:** Run the same end-to-end fixture and compare graph
  isomorphism across both adapters.
- [ ] **M10-T8 → AC8:** Keep Jena/client dependencies in an optional packaging
  extra if additional dependencies are required.
- [ ] **M10-T9 → AC1–AC8:** Document endpoint configuration, authentication,
  dataset creation assumptions, backup, and migration from the local store.

### Required evidence

- [ ] Fuseki version and test setup:
- [ ] Cross-backend contract result:
- [ ] Atomic failure result:
- [ ] Cross-backend isomorphism result:
- [ ] Request trace showing bounded access:
- [ ] Credential redaction result:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Tested Jena/Fuseki version:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M11 — CLI, app, and independent skill adapter readiness

### Intended achievement

Prove that one packaged core can support multiple products without copying
pipeline logic or pulling every product dependency into every installation.

This milestone establishes adapter boundaries. It does not require a polished
production web UI or a marketplace of skills.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M11-AC1:** The Python distribution exposes a documented, versioned public API
  sufficient for CLI, app, and skill adapters.
- **M11-AC2:** The CLI is installed through `[project.scripts]`, uses only the
  public API, and remains usable through `python3 -m text_to_ontology`.
- **M11-AC3:** Optional app dependencies are packaging extras or belong to a
  separate app distribution; the core/library installation remains small.
- **M11-AC4:** A minimal app adapter can submit a run request and serialize a run
  result without importing CLI code or duplicating pipeline orchestration.
- **M11-AC5:** A reference independent skill can invoke a stable CLI command or
  public Python API and contains no copied extraction/context/merge logic.
- **M11-AC6:** Prompts, SPARQL templates, default shapes, and other required
  assets are loadable through package resources from an installed wheel.
- **M11-AC7:** Adapter contract tests prove that equivalent inputs reach the same
  public request and yield the same domain result through Python API, CLI, and
  reference app/skill adapters.
- **M11-AC8:** Distribution names, import package name, command name, versioning
  policy, and supported Python versions are documented.

### Tasks derived from the acceptance criteria

- [ ] **M11-T1 → AC1:** Review the public API surface and mark internal modules as
  non-public by convention and documentation.
- [ ] **M11-T2 → AC1, AC8:** Add semantic versioning/release notes policy for
  request/result and stored-plan contracts.
- [ ] **M11-T3 → AC2:** Complete CLI entry-point and module execution tests from
  an installed wheel.
- [ ] **M11-T4 → AC3, AC4:** Build the smallest possible reference app adapter
  behind an optional extra or separate package. It may be a single endpoint or
  callable; do not build a UI framework here.
- [ ] **M11-T5 → AC5:** Build one reference skill wrapper with instructions and a
  thin call to the installed CLI/API. Document what must be configured by the
  skill host.
- [ ] **M11-T6 → AC6:** Add installed-wheel resource tests.
- [ ] **M11-T7 → AC7:** Add one shared fixture exercised through API, CLI, app,
  and skill wrapper with the same fake extractor/store.
- [ ] **M11-T8 → AC8:** Document install commands for core, SHACL, Jena, app, and
  development extras/groups.

### Required evidence

- [ ] Public API surface:
- [ ] Installed CLI smoke result:
- [ ] Minimal app request/result example:
- [ ] Reference skill location and invocation:
- [ ] Cross-adapter equivalence test:
- [ ] Installed resource test:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Released package version:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## M12 — Measured scale, idempotency, and operational improvements

### Intended achievement

Add only optimizations justified by measured behavior after the correct
document-level pipeline and both store adapters exist. Preserve deterministic
publication and RDF as the source of truth.

### Status

- [ ] Not started  [ ] In progress  [ ] Blocked  [ ] Complete

### Acceptance criteria

- **M12-AC1:** Source/window/configuration digests detect exact reruns and can
  skip external extraction without changing final graph semantics.
- **M12-AC2:** Replacing or removing a source uses provenance to remove a
  canonical assertion only when no retained source still supports it.
- **M12-AC3:** Skeleton/context caches are rebuildable, keyed by explicit input
  graph versions/fingerprints, and never treated as canonical data.
- **M12-AC4:** An optional entity text index accelerates suggestions but final
  identity decisions still query/verify canonical RDF and preserve ambiguity
  review.
- **M12-AC5:** Performance measurements cover at least graph size, source size,
  window count, SPARQL calls, transferred rows/bytes, context-selection time,
  extraction time, reconciliation time, and publication time.
- **M12-AC6:** Parallel extraction is introduced only if measurements justify it;
  source reconciliation and final document publication remain deterministic and
  ordered.
- **M12-AC7:** A real tokenizer can be selected per extraction model, with the
  deterministic character estimator retained as fallback.
- **M12-AC8:** All optimizations have an off switch and produce the same accepted
  RDF result as the unoptimized reference path for deterministic fixtures.

### Tasks derived from the acceptance criteria

- [ ] **M12-T1 → AC5:** Establish repeatable local and Jena benchmark fixtures
  before changing performance behavior.
- [ ] **M12-T2 → AC1:** Add extraction-result lookup by complete processing
  fingerprint and exact rerun tests.
- [ ] **M12-T3 → AC2:** Implement support counting from provenance and source
  replacement/removal planning with dry run and atomic publication.
- [ ] **M12-T4 → AC3:** Add schema/skeleton cache with explicit invalidation and
  cache-equivalence tests.
- [ ] **M12-T5 → AC4:** Add an optional index interface and one implementation
  only after exact SPARQL lookup is measured as insufficient.
- [ ] **M12-T6 → AC5:** Add structured timing/count metrics without logging raw
  source text or secrets.
- [ ] **M12-T7 → AC6:** If justified, parallelize only external window extraction;
  preserve stable result ordering and single document publication.
- [ ] **M12-T8 → AC7:** Add tokenizer adapters and model/config fingerprinting.
- [ ] **M12-T9 → AC8:** Run optimized/unoptimized equivalence tests for every
  optimization.

### Required evidence

- [ ] Before/after benchmark report:
- [ ] Rerun skip result:
- [ ] Safe source-removal result with two supporting sources:
- [ ] Cache/index equivalence result:
- [ ] Optimized/unoptimized graph isomorphism result:
- [ ] Decision on parallel extraction and evidence:

### Completion record

- Owner:
- Started:
- Completed:
- Branch:
- Commits:
- Pull request/review:
- Benchmark environment:
- Decisions made:
- Known follow-ups:
- Acceptance evidence location:

---

## Release gates

### Gate A — safe architectural foundation

Requires M0 through M3 complete.

- [ ] Clean deterministic test suite
- [ ] Installable package
- [ ] Public Python API and thin CLI
- [ ] Stable source/window records
- [ ] Local named-graph dataset behind a store contract

### Gate B — correct document-level text-to-graph pipeline

Requires M4 through M7 complete.

- [ ] Inspectable RDF candidate graph per window
- [ ] Standards-based confidence and provenance
- [ ] Incremental source graph across windows
- [ ] Complete-source reconciliation and SHACL validation
- [ ] Exactly one atomic final merge per source document
- [ ] Dry run and failure immutability

This is the first release that fully realizes the central architectural goal.

### Gate C — scalable semantic-store operation

Requires M8 through M10 complete.

- [ ] Focused SPARQL context and identity access
- [ ] Multiple schema and shape graphs
- [ ] Separate seed tool
- [ ] Jena/Fuseki adapter with cross-backend contracts

### Gate D — product versatility and optimization

Requires M11; M12 items are selected based on need.

- [ ] Stable core usable by CLI, app, and independent skills
- [ ] Optional dependencies do not inflate core installation
- [ ] Only measured optimizations are enabled

## Git working instructions

These instructions apply to every milestone.

### Before starting work

1. Read `AGENTS.md`, `README.md`, this plan, and the architecture documents
   relevant to the milestone.
2. Inspect the worktree before doing anything:

   ```bash
   git status --short
   git branch --show-current
   git log --oneline -5
   ```

3. Treat every existing uncommitted or untracked file as user-owned. Do not
   delete, reset, overwrite, stage, or reformat unrelated work.
4. Determine the repository's actual default/integration branch. At the time
   this plan was written it was `master`, but do not assume it will remain so.
5. Create one branch per milestone from the agreed integration point:

   ```bash
   git switch -c milestone/m00-packaging-baseline
   ```

   Use names such as `milestone/m05-source-graph`. If the user already supplied
   a branch or worktree, use it instead of creating another one.
6. Record the owner, start date, and branch in the milestone before or with the
   first implementation commit.

### While working

- Keep commits small and aligned with acceptance criteria.
- Prefer a commit message such as `m05: keep final graphs unchanged per window`.
- One commit may satisfy several closely related criteria, but its message/body
  should name them.
- Add tests with or before the behavior they verify.
- Use explicit paths when staging. Do not use `git add .` in a dirty worktree.
- Check what will be committed:

  ```bash
  git status --short
  git diff -- path/to/file
  git add path/to/file path/to/test
  git diff --cached --stat
  git diff --cached
  ```

- Never commit `.env`, API keys, generated run reports, local RDF databases,
  mutable source graphs, build output, caches, or editor files.
- Never use `git reset --hard`, broad checkout/restore commands, or destructive
  cleanup to handle unrelated changes.
- Do not amend or rewrite commits that may already be shared unless explicitly
  authorized.
- Do not push, merge, tag, or open a pull request unless the user or repository
  workflow authorizes it.

### Before declaring a milestone complete

1. Run targeted tests while developing, then the complete deterministic suite.
2. Run whitespace/conflict-marker checks:

   ```bash
   git diff --check
   rg -n '^(<<<<<<<|=======|>>>>>>>)' .
   ```

3. Build/install the package when packaging or resources are affected.
4. Run the applicable contract/integration tests stated in the milestone.
5. Review the complete branch diff against its base. Confirm that every changed
   file is relevant to an acceptance criterion.
6. Fill every required-evidence checkbox with a command, test name, report path,
   or concise result.
7. Fill the completion record and change the milestone/dashboard checkbox only
   after all acceptance criteria pass.
8. Commit the plan status/evidence update. It may be part of the final milestone
   commit or a small follow-up documentation commit.
9. Provide a handoff summary containing:

   - achieved outcome;
   - acceptance criteria passed;
   - exact test/build commands and results;
   - commits;
   - migrations or manual actions required;
   - known follow-ups and risks.

### Handling a blocked milestone

Do not mark a milestone complete because most criteria pass. Mark it blocked and
record:

- the exact unmet acceptance criterion;
- commands and evidence showing the blocker;
- work already completed;
- safe next action;
- whether any partial commits are suitable for review or should remain unmerged.

Do not weaken an acceptance criterion merely to finish a milestone. If a
criterion is wrong, record and review an explicit plan change.

## Architecture decision log template

Use this section or a separate `docs/decisions/` record when implementation
reveals a choice that changes contracts, stored RDF, compatibility, or milestone
scope.

### ADR-___ — Short decision title

- Status: Proposed / Accepted / Superseded
- Date:
- Decision owner:
- Milestone:
- Context:
- Options considered:
- Decision:
- Why this is the simplest adequate choice:
- Consequences:
- Migration/compatibility effect:
- Acceptance criteria affected:
- Commit:

## Handoff log

Add one entry whenever work changes hands.

### YYYY-MM-DD — Milestone/owner

- Branch:
- Last commit:
- Current status:
- Completed acceptance criteria:
- Remaining acceptance criteria:
- Tests currently passing:
- Tests currently failing and why:
- Uncommitted files that must be preserved:
- Next recommended task:
- Decisions/questions requiring owner input:

## Standards and packaging references

Use these as semantic/packaging references; do not copy their entire complexity
into the application when a smaller conforming pattern is enough.

- RDF 1.1 Concepts: <https://www.w3.org/TR/rdf11-concepts/>
- RDF Schema 1.1: <https://www.w3.org/TR/rdf-schema/>
- OWL 2 overview: <https://www.w3.org/TR/owl2-overview/>
- SKOS reference: <https://www.w3.org/TR/skos-reference/>
- SHACL: <https://www.w3.org/TR/shacl/>
- SPARQL 1.1 Query: <https://www.w3.org/TR/sparql11-query/>
- SPARQL 1.1 Update: <https://www.w3.org/TR/sparql11-update/>
- SPARQL 1.1 Graph Store Protocol:
  <https://www.w3.org/TR/sparql11-http-rdf-update/>
- PROV-O: <https://www.w3.org/TR/prov-o/>
- Data Quality Vocabulary: <https://www.w3.org/TR/vocab-dqv/>
- Python `pyproject.toml` guide:
  <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/>
- Python `src/` layout guidance:
  <https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/>

RDF 1.2 triple terms and `rdf:reifies` may later simplify statement metadata,
but they are not the initial interoperability baseline. Adopting them requires a
separate compatibility decision covering RDFLib, Jena, SPARQL, serialization,
and existing stored evidence.

## Final completion checklist

- [ ] All required milestones are complete and dashboard status is accurate.
- [ ] Gate B is complete for the document-level source-graph architecture.
- [ ] Gate C is complete before claiming production Jena support.
- [ ] All accepted RDF can be traced to source document and window evidence.
- [ ] Confidence measurements remain per source occurrence.
- [ ] Long-source tail coverage is tested.
- [ ] Final graphs remain unchanged until one document-level publication.
- [ ] One source document causes at most one successful final publication.
- [ ] Local and Jena store adapters pass the shared contracts when Jena support
  is claimed.
- [ ] CLI, app, and skill adapters contain no copied pipeline logic.
- [ ] README and architecture/data-flow documentation match implemented behavior.
- [ ] Clean install, full tests, package build, and applicable integration tests
  pass from documented commands.
- [ ] No secrets or local/generated data are tracked.
- [ ] Final handoff log contains the release commit and remaining optional work.
