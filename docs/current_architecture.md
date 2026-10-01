# Current Architecture — text_to_ontology

> Machine-readable architecture map. Reconstructed **from source code only** (no docs consulted).
> Target audience: another AI/LLM agent that must navigate, modify, or extend this codebase.
> All facts below are taken directly from the files; function signatures are quoted verbatim.

## Current pipeline (post-M7, windowed document publication)

The executable is the packaged CLI; the root scripts `ontology.py` and
`view_ontology.py` are thin compatibility wrappers that add `src/` to
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
   selected from the final ontology *and* from the staging graph (marked
   `(this document)`), the prompt goes to the LLM, a messy answer is sent back
   for bounded self-repair (`repair.py`), and the answer must pass
   `candidate_validation` every time.
4. **Window admission** (`pipeline._admit_window`) — the validated package is
   planned against the source staging graph only (provisional IRIs, never
   canonical identities) and admitted into the staging graph; the candidate RDF
   is kept alongside as evidence.
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
8. **Publication** (`document_publication.py`) — PROV/DQV evidence is remapped
   onto the decided canonical statements, document/file source records are
   materialized, the proposed post-merge data is SHACL-validated, and target /
   provenance / review graphs are replaced in **one atomic**
   `store.publish(Publication(...))` call. `dry_run` returns the same plan
   without the call.

The default store is `RdflibGraphStore` persisted as TriG; graph roles come
from `GraphNames`. A `.ttl` output path explicitly selects
`LegacyTurtleDatasetStore`, which runs the same named-graph orchestration and
atomically exports the role union for compatibility.

---

## 1. Purpose

Reads text files (or a directory of text-like files), asks an LLM to extract
**entities**, **relations**, and literal **facts**, and publishes them into a
named-graph RDF dataset (`ontology.trig` by default: schema, shapes, target
data, provenance, and review graphs). Re-running against the same dataset adds
knowledge; identity resolution runs document-scoped and prevents duplicates.

The codebase has three applied layers plus the packaged viewer:

1. **Write pipeline** — package modules that build and publish the dataset.
2. **Context selection layer** — modules that pick, render, and budget the part
   of the graph one source text needs, and put that into the extraction prompt.
   Nothing in this layer writes to the graph.
3. **Read-only derivation layer** — modules that generalize an existing graph
   (`graph_partition`, `graph_skeleton`, `graph_patterns`, plus the
   `ontology_views` façade) used by the context layer and the viewer.
4. **Viewer** — `view_ontology` / `view_report` / `view_html` render the same
   read-only views to the terminal or one self-contained HTML page.

The prompt no longer carries the whole entity catalog or every property label.
It carries a layered selection (canonical + `(this document)` source-local)
capped by a token ceiling (§10).

---

## 2. Repository layout

```
text_to_ontology_2/
├── pyproject.toml              # package metadata + deps (rdflib, pyshacl)
├── uv.lock                     # locked dependency versions
├── ontology.py                 # compatibility wrapper → text_to_ontology.cli
├── view_ontology.py            # compatibility wrapper → text_to_ontology.view_ontology
├── trig_to_ttl.py              # export the data graph of a .trig file as .ttl
├── ontology.trig               # default named-graph dataset (data, not code)
├── ontology.ttl                # legacy Turtle export of the data graph
├── reports/runs/               # --report Markdown output (git-ignored)
├── docs/                       # this map + app_map.html + data_flow.html
├── src/text_to_ontology/       # the importable package (35 .py files)
└── tests/                      # unittest: one file per module + pipeline
    ├── store_contract.py       # shared GraphStore contract test base
    ├── fixtures/
    │   ├── miniature_repository.ttl   # frozen graph for partition/skeleton/pattern pins
    │   ├── documents/                 # windowing fixtures (crlf, long, unicode, …)
    │   └── shacl/                     # SHACL shape fixtures for source validation
    └── test_*.py               # 31 test modules
```

Dependency: `rdflib>=7,<8` and `pyshacl>=0.30,<1` (pyproject.toml), Python 3.12+.

---

## 3. Entry point — `cli.py` → `api.py` → `pipeline.py`

### 3.1 `cli.py`

```
def build_parser():   # argparse; source (required), graph (default ontology.trig),
                      # -v/--verbose, --report, --dry-run
def main(argv=None):  # builds adapters, calls run_text_to_graph, exit code 1 on
                      # RuntimeError/OSError (printed to stderr)
```

- `graph` default: `Path("ontology.trig")`. If `args.graph.suffix == ".ttl"`,
  a `LocalTurtleStore` compatibility store is passed; otherwise `None` selects
  the default `RdflibGraphStore`.
- `--report`: reporter is verbose and writes to a timestamped Markdown file
  under `reports/runs/`; a successful run stays silent on the terminal.
- `-v/--verbose`: the same reporter writes everything to the terminal.

### 3.2 `api.py`

One documented public function plus re-exported types (`__all__`):

```
run_text_to_graph(request, graph_store=None, extractor=None, reporter=None) → RunResult
```

The CLI is a thin adapter over it. The core pipeline never parses arguments,
reads environment variables, or exits the process.

### 3.3 `pipeline.py` — the run loop

Request dataclasses (all in `pipeline.py`):

- `WindowingConfig` — `target_tokens=800`, `overlap_tokens=100`,
  `strategy_version=2`, `count_tokens=estimate_tokens`.
- `ContextConfig` — `budget=dict(PROMPT_BUDGET)`.
- `ExtractionConfig` — `model=None`, `repair_attempts=2`.
- `MergeConfig` — `min_auto_accept_confidence=0.80`.
- `ProcessingConfig` — `retain_staging_on_failure=False`.
- `ValidationConfig` — `shape_graphs=()` (explicit SHACL graphs; empty keeps
  role shapes / legacy embedded shapes).
- `RunRequest` — `source`, `graph_path=Path("ontology.trig")`, the five configs,
  `graph_names=GraphNames()`, `dry_run=False`.

Result dataclasses:

- `DocumentResult` — `path`, `document_id`, `source_artifact`,
  `reconciliation_report`, `source_validation`, `publication_plan`,
  `publication_validation`.
- `RunResult` — `graph_path`, `triples`, `files_total`, `files_saved`,
  `files_blank`, `windows_processed`, `documents`, `dry_run`.

Adapters (Protocols, replaceable): `Extractor` (`model()`, `extract(prompt)`),
`Reporter` (one method per checkpoint, see `run_report.RunReporter`). The
concrete extractor is `llm.OpenRouterExtractor`; a fake is used in tests. Check
the store boundaries in `graph_store.GraphStore` / `graph_management.GraphStore`.

`run_text_to_graph` control flow:

```
extractor = extractor or OpenRouterExtractor(model=request.extraction.model)
reporter  = reporter or RunReporter()
store     = _final_store(graph_store, request)      # RdflibGraphStore or LegacyTurtleDatasetStore
roles     = initial_role_graphs(store, names)        # read schema/shapes/data/provenance/review; seed if empty
graph     = union_graphs(roles.values())
files     = find_text_files(request.source, request.graph_path)
if not files: raise RuntimeError("No text-like files found")
for index, path in enumerate(files, start=1):
    raw_text = read_source(path)
    if not raw_text.strip(): reporter.blank_source(); blank_files += 1; continue
    document = make_source_document(path.name, raw_text, source_path=path.as_posix())
    before_snapshot = final_graphs_snapshot(graph)
    staged = _process_document(document, request, graph, extractor, reporter)  # windows → staging
    reconciliation = reconcile_document(document.document_id, staged.source_graph,
                                        staged.candidate_graphs, staged.admission_plans)
    artifact = build_source_artifact(document, staged.source_graph, request.windowing, models)
    validation = validate_source_graph(staged.source_graph, _source_shape_graphs(...))
    if not validation.conforms: raise SourceValidationError(validation, artifact, reconciliation, sidecar)
    assert final graph snapshot unchanged
    document_merge = plan_document_merge(canonical_graph(roles, names), document,
                                         staged.packages, staged.admission_plans, conf, planner=plan_graph_merge)
    publication_plan = compile_document_publication(document, document_merge, staged.candidate_graphs,
                                                    staged.packages, staged.admission_plans, roles, names, shapes)
    if not publication_plan.proposed_validation.conforms: raise PublicationValidationError(publication_plan)
    if request.dry_run: reporter.dry_run(...)
    else: publish_document(store, publication_plan); reporter.saved(...)
    roles.update(publication_plan.publication.graphs); graph = union_graphs(roles.values())
return RunResult(...)
```

`_process_document` (per document):

```
windows = plan_windows(document, request.windowing)
staging = RdflibGraphStore()
staging.put(staging_name, Graph())          # source_staging_graph_name(document_id)
source_graph = staging.get(staging_name)
snapshot = final_graphs_snapshot(final_graph)
for number, window in enumerate(windows, start=1):
    model, candidates = _extract_window(window, ...)   # context → LLM → repair → validate
    source_graph, counts, plan = _admit_window(window, candidates, ...)
    if final_graphs_snapshot(final_graph) != snapshot: raise RuntimeError(...)
    staging.put(staging_name, source_graph)
    packages.append((window, model, candidates)); admission_plans.append({window_id, plan})
on BaseException: if retain_staging_on_failure → retain_staging(...) sidecar; reporter.staging_failed; raise
```

`_extract_window`: builds canonical + source-local context via
`_window_context` → `layered_context_text` → `make_prompt` →
`extract_validated(extractor, prompt, validator, max_repair_attempts=...)` →
`RuntimeError(repair/validation failure)` on failure.

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

Namespaces (constants): `BASE = "http://example.org/text-ontology/"`,
`ONTO`, `ENTITY` (`entity/`), `CLASS` (`class/`), `RELATION` (`relation/`),
`FACT` (`fact/`).

- `bind(graph)` — binds `onto, entity, class, relation, fact, owl, rdf, rdfs, sh, skos`.
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
- `RdflibGraphStore` — `Dataset(default_union=True)` in memory; optional
  `path` parsed as TriG. `publish` serializes a **clone** to `<path>.tmp` and
  `os.replace`s it, then applies the publication in memory — a failed write
  changes neither the file nor the dataset.
- `ReadOnlyGraphStore` — exposes only `get`/`graph_names`/`query` (the viewer
  wraps stores in it so viewing can never write).
- `GraphNames` — role names (defaults): `schema_graphs=[.../graphs/schema]`,
  `shape_graphs=[.../graphs/shapes]`, `data_graphs=[]`, `target_graph=
  .../graphs/data`, `provenance_graph=.../graphs/provenance`, `review_graph=
  .../graphs/review`, `staging_namespace=.../staging/`. `validate()` fails on
  duplicate roles or a staging namespace not ending in `/` or `#`.
  `source_staging_graph(document_id)` derives a document's staging name.
- Migration/export helpers: `import_legacy_turtle(store, path, names)` (split a
  legacy Turtle union into schema/target/provenance via `partition_graph`),
  `export_graph_turtle(store, name)`, `export_dataset(store, fmt=...)`.

### 4.3 `ingest_sources.py` — source discovery + reading

Identical contract to the earlier version; `TEXT_FILES` is unchanged.
`find_text_files(source, graph_path)` accepts a directly-named file regardless
of extension, or recursively sorted, extension-filtered, graph-excluded files.
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
  version, target/overlap, tokenizer name, document ID, index, start, end.

### 4.5 `source_parse.py` — prompt builder

- `context_block(context_text)` — headed context + `CONTEXT_RULES`, `""` when
  empty.
- `make_prompt(text, context_text="")` — instruction, context, entity
  resolution paragraph, exact JSON contract (entities/relations/facts with
  per-record `confidence`), and `SOURCE` between `---` delimiters.
- `parse_source(text, context_text="")` = `parse_prompt(make_prompt(...))`;
  `parse_prompt(prompt)` = `ask_llm(prompt)`.

### 4.6 `llm.py` — OpenRouter client (stdlib only)

- `DEFAULT_MODEL = "openrouter/pareto-code:nitro"`,
  `SYSTEM_PROMPT = "Extract knowledge. Return only JSON."`.
- `InvalidResponseError(RuntimeError)` — the answer is not one parseable JSON
  object (this is what `repair.py` catches).
- `load_env(path=Path(".env"))` — `KEY=value` lines, `setdefault`, never
  overrides existing env vars.
- `model_name()` — `OPENROUTER_MODEL` or the default.
- `ask_llm(prompt)` — POSTs `{"model", "temperature": 0, "messages": [
  {system}, {user}]}` to `https://openrouter.ai/api/v1/chat/completions` with
  bearer key, JSON content type, and `X-OpenRouter-Title: "Simple Text to
  Ontology"`, timeout 60 s. Accepts Markdown-fenced JSON; raises
  `RuntimeError` for HTTP errors, `InvalidResponseError` for non-JSON or
  `JSONDecodeError`.
- `OpenRouterExtractor(model=None)` — `model()` → override or `model_name()`;
  `extract(prompt)` → `ask_llm(prompt)`.

### 4.7 `repair.py` — bounded self-repair

- `repair_prompt(original=None, raw_problem=None, issues=())` — the model gets
  its own original answer back plus the deterministic, sorted issue list and
  one instruction: return the complete corrected JSON, nothing else.
- `ExtractionOutcome` — `validation` (None when nothing parsed), `raw_problem`,
  `repair_attempts`; `.ok` = parsed AND `validation["valid"]`.
- `extract_validated(extractor, prompt, validate, max_repair_attempts=0)` —
  extract, validate, and while the answer is unparseable/invalid and attempts
  remain, send a repair prompt and validate again. **Every** attempt passes the
  same `validate` gate (the pipeline passes `validate_candidates`).

### 4.8 `candidate_validation.py` — validate + normalize (unchanged gate)

Read-only, fail-closed. Public contract:

- `validate_candidates(data, graph, allowed_existing_ids=())` →
  `{valid, candidates|None, issues, counts}`.
- `format_validation_failure(result)` → deterministic CLI error text.

Normalization is conservative (NFKC, CRLF→LF, controls removed, one-line
whitespace collapsed, descriptions/facts preserved, dates/numbers never
coerced, fact JSON type part of the duplicate key). Passes: container →
entity normalization + confidence (required in `[0,1]`, missing/invalid codes)
→ relation/fact normalization → reference check → label/role/type collisions →
exact dedupe (with `duplicate_confidence` lowering the kept value) →
graph-URI role/type compatibility. Graph-exact assertions are deliberately
**kept** so merge policy can plan corroboration and provenance. `existing_id`
is accepted only if it was rendered in the final budgeted prompt and still
exists in `entity_catalog(graph)` (with a kind-match check).

### 4.9 `candidate_graph.py` — one validated package → RDF candidate graph

- Constants: `CANDIDATE_MAPPING_VERSION = 2`, `CANDIDATE_BASE`
  (`http://example.org/text-ontology/`), `PROVISIONAL` namespace,
  `EXTRACTION_CONFIDENCE_METRIC` (`.../metric/extraction-confidence`), DQV
  namespace (not in rdflib).
- `literal_value(value)` — conservative typed literals; real ISO dates become
  `xsd:date`, booleans/ints/floats typed, everything else a plain string.
- `provisional_entity_iri(document_id, local_id)` — the stable provisional IRI
  of one unresolved individual.
- `build_candidate_graph(candidates, document_id, window_id, activity_id,
  extractor_model, entity_iris=None, assertion_triples=None)` — deterministic:
  every record becomes a `prov:Collection`; asserted triples are present AND
  reified as `rdf:Statement` members; per-record confidence is a
  `dqv:QualityMeasurement` (xsd:decimal) against the project `dqv:Metric`;
  PROV-O chain: document → window → activity → `prov:SoftwareAgent`.
  Entities are typed with their kind class (not a `kind` string) with
  `skos/definition/altLabel`; relations/facts use `RELATION[slug]` /
  `FACT[slug]` IRIs. Same response always produces the same graph.

### 4.10 `source_staging.py` — one document, one provisional graph

- `STAGING_NAMESPACE = CANDIDATE_BASE + "staging/"`.
- `source_staging_graph_name(document_id)`, `window_candidate_graph_name(doc,
  window)` — stable graph names.
- `window_activity_id(document_id, window_id, model, candidates)` — SHA-256
  PROV activity ID.
- `provisional_allocator(document_id)` — slug-first `-2, -3, ...` allocation
  inside `provisional/<doc>/`, so a staged entity can never claim a canonical
  identity.
- `plan_window_admission(source_graph, candidates, provenance, document_id,
  min_new_confidence=0.80)` — `plan_graph_merge` against the source staging
  graph only, with the provisional allocator.
- `final_graphs_snapshot(graph)` — `tuple(sorted(graph))` for immutability
  checks.
- `layered_context_text(canonical_package, source_package, budget_config,
  count_tokens)` — renders canonical + source-local items as one block;
  source-local items are prefixed `(this document)` per line and their
  resources forced `native: False` (never reusable `existing_id`). One shared
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
  (`inference="none"`, `abort_on_first=False`).

### 4.13 `merge_policy.py` — read-only merge planning

Policy layer, unchanged in role but versioned 2. Constants:
`MERGE_POLICY_VERSION = 2`, `AUTO_ACCEPT_MIN_CONFIDENCE = 0.80`, `RDF_JSON`
(`rdf:JSON`), `FUNCTIONAL` / `INVERSE_FUNCTIONAL`.

- `canonical_json(value)` / `record_digest(record)` — the digest base.
- `proposed_entity_uri(entity)` — `onto:merge-proposed-entity/<sha256>`, a
  review-only provisional identity (never typed `onto:Entity`).
- `build_provenance(source_path, source_text, model)` →
  `{source_path, source_sha256, model, policy_version}`.
- `resolve_entities(candidates, graph, min_new_confidence=0.80,
  allocate_uri=None, provisional_uri=None)` — ordered identity decisions with
  a virtual catalog and URI reservation so two new entities cannot collide;
  `allocate_uri`/`provisional_uri` are injectable (staging passes the
  document's provisional allocator).
- `plan_graph_merge(graph, candidates, provenance, min_new_confidence=0.80,
  allocate_uri=None, provisional_uri=None)` → MergePlan:
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

**Audit vocabulary** (all under `onto:`; support partition; no timestamps, no
raw source/prompt/response): `onto:ExtractionEvent` (sourcePath, sourceSha256,
modelName, mergePolicyVersion, candidatePackageSha256) and
`onto:MergeCandidate` (wasExtractedIn, candidateSection, candidateIndex,
normalizedCandidate as `rdf:JSON`, extractionConfidence as `xsd:decimal`,
mergeDecision, decisionReason per code, fieldDecisions for entities,
resolvedEntity / proposedEntity, reified rdf:subject/predicate/object for
grounded assertions). Event URIs are SHA-256 digests over policy version,
source path, source digest, model, window/document/config, and package digest;
candidate URIs add section/index/record digest, so exact reruns reuse the same
audit resources.

### 4.14 `entity_lookup.py` — identity decisions (unchanged contract)

`CLOSE_SPELLING_THRESHOLD = 0.96`; `identity_key` (lossy NFKD→ascii);
`entity_catalog(graph)`; `identity_decision(entity, catalog,
planned_catalog=(), *, min_new_confidence=0.80, allocate_uri=None,
provisional_uri=None)` → `{local_id, status, uri, method, identity_score,
suggestions, reason_codes}`. Order: explicit id → unique same-kind exact
(planned_exact/exact_name/exact_alias) → ambiguous-exact review →
kind-collision review → close-spelling review-only suggestions → new (≥
confidence) or below-threshold review with a provisional URI. `identify_entity`
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
  min_new_confidence, planner=plan_graph_merge)` — resolves the whole
  reconciled source against the canonical scope **once**; adds
  `document_merge_version`, `configuration_sha256`, and an `identity_mapping`
  from source keys to final identity decisions.

### 4.17 `document_publication.py` — compile + atomic publish

- `DocumentPublicationPlan` — `document_id`, `document_merge`,
  `proposed_validation`, `publication` (a `Publication`), `counts`.
- `PublicationValidationError` — `plan` + `validation`.
- `LegacyTurtleDatasetStore` — wraps a legacy `get/load/save` store; splits the
  loaded Turtle into in-memory roles and persists the union as one Turtle on
  each `publish` via `save_graph`.
- `split_legacy_graph(graph, names)` / `initial_role_graphs(store, names)` /
  `canonical_graph(roles, names)` (schema + data graphs = the identity scope) /
  `shape_graphs(roles, names)`.
- `compile_document_publication(document, document_merge, candidate_graphs,
  packages, admission_plans, roles, names, validation_shapes=None)` — copies
  the target graph, adds the plan's domain triples, remaps candidate evidence
  onto decided canonical statements, materializes document/file source links,
  builds the review graph, and SHACL-validates the proposed data (no mutation).
- `publish_document(store, plan)` — the one final `store.publish(...)`.
- `remap_candidate_evidence` / `_copy_evidence` — every PROV/DQV occurrence is
  kept while reified statements are remapped to their final identity.
- `build_review_graph(document, document_merge)` — withheld identities and
  assertions as `prov:Collection` with `rdf:Statement` members and
  `prov:wasDerivedFrom`.

### 4.18 `publication_sources.py` — document/file source links + summaries

- `source_records(graph, document)` — `onto:document/<id>` and
  `onto:source-file/<sha>` as `prov:Entity` records with `rdfs:label` and
  (`onto:sourceFile` / `onto:sourcePath`). Content identity is separate from
  file identity: identical content in different files shares a document but
  keeps separate file records.
- `link_statement_sources(graph, document_uri, file_uri)` — attaches
  `prov:wasDerivedFrom` + `onto:sourceFile` to evidence statements (skips the
  app-supplied `onto:Entity` root).
- `materialize_sources(graph, document, document_merge, canonical)` — for each
  accepted/corroborated canonical triple, a stable `onto:statement/<sha>`
  (`rdf:Statement` + `prov:Entity` reification) with derived-from/source-file;
  domain individuals, classes, and properties receive `onto:sourceDocument` +
  `onto:sourceFile` summaries.
- `supported_triples(document_merge, canonical)` — only accepted, duplicate,
  and corroborated triples (review never gets sources).

### 4.19 `run_report.py` — human-readable reporting

- `REPORT_DIRECTORY = Path("reports/runs")`; `default_report_path(source,
  started_at=None)` → `<timestamp>_<source>.md`.
- `RunReporter(verbose=False, stream=None, extra_streams=(),
  markdown_streams=())` — one reporter object; plain terminal lines, verbose
  sections, code blocks, and Markdown-safe output. Checkpoints: `run_started`,
  `source_started`, `blank_source`, `document_staging`, `window_started`,
  `context_selection`, `prompt_context`, `asking_model`, `llm_input`,
  `model_replied`, `validation`, `window_admitted`, `reconciliation`,
  `source_validation`, `publication_validation`, `merge_plan`, `dry_run`,
  `saved`, `staging_failed`, `finished`, `dry_run_finished`, `failed`.
- Helpers `skeleton_label` / `skeleton_restriction` are shared with the viewer.

---

## 5. Module reference (read-only derivation and context layers)

None of these modules writes to a graph. They are reached by the pipeline
through `task_context.build_task_context()` and
`context_render.prepare_prompt_context()` (and, for one window,
`source_staging.layered_context_text()`), and by the viewer through
`ontology_views.build_ontology_views()`.

### 5.1 `graph_partition.py` — split one graph into 3 views

Imports (rdflib only). Constants: `SCHEMA_TYPES`, `AUDIT_TYPES`
(`onto:ExtractionEvent`, `onto:MergeCandidate`), `SOURCE_PREDICATES`
(`onto:sourceDocument`, `onto:sourceFile`, `onto:sourcePath`), `SUPPORT_TYPES`
(`OWL.Ontology`, `SH.NodeShape`, `SH.PropertyShape`), `SCHEMA_AXIOMS`,
`ANNOTATIONS`, `RESTRICTION_TARGETS`.

- `owned_nodes / support_roles / restriction_roles / schema_roles /
  instance_roles` — role sets.
- `choose_view(triple, ...)` — priority: source predicates → support; subject
  or object in support → support; opaque blank nodes → support; `rdf:type`
  schema/instance; restrictions → schema; schema axioms; annotations follow
  their subject's role; default = instance if the subject is an instance role
  else support.
- `partition_graph(source_graph)` → `(schema, instance, support)`, lossless and
  disjoint, inputs never mutated.

### 5.2 `graph_skeleton.py` — compact declared structural core

Unchanged contract: `supported_restriction`, `structural_triples`,
`create_graph_skeleton(schema_graph)` → explicit classes/object/datatype
properties, named subclass/domain/range axioms, labels, and only complete
supported restrictions (six forms). No inference; skeleton ⊆ schema input.

### 5.3 `graph_patterns.py` — empirical usage patterns

Unchanged contract: `eligible` (excludes `onto:kind` and RDF/RDFS/OWL/SH/SKOS
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

### 5.6 `task_context.py` — select the context one source needs

Unchanged contract. `DEFAULT_LIMITS`: classes 12, properties 16, restrictions
8, patterns 20, resources 15, examples 12, hierarchy_hops 1, instance_hops 1,
match_tokens 8, overlap_tokens 2, concepts 40, direct_matches 40. Tiers 1–8
(`DIRECT_NAME` → `INDIRECT`); relevance outranks frequency; all bounded
expansion with visited sets (cycles terminate). Returns a `ContextPackage`
{concepts, schema, patterns, resources, examples, labels, diagnostics}.
`build_task_context(text, source_graph, limits=None)` composes views +
concepts + `entity_catalog`.

### 5.7 `context_render.py` — render, assemble, budget

Unchanged contract: `render_context_items(package, namespace_manager=None)`
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

Unchanged contract. `PROMPT_BUDGET` (approved 2026-08-17):
`total_limit 30_000`, `context_tokens 1_400`, `fixed_prompt_tokens 400`,
`output_reserve 4_000`, `safety_margin 500`; `DEFAULT_CHARS_PER_TOKEN = 3`.
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
| `document_publication` | `compile_document_publication(document, merge, candidates, packages, plans, roles, names, shapes)` | `DocumentPublicationPlan` |
| `graph_store` | `RdflibGraphStore.publish(publication)` | atomic TriG persistence |
| `merge_policy` | `plan_graph_merge(graph, candidates, provenance, ...)` | MergePlan (see 4.13) |
| `entity_lookup` | `identity_decision(entity, catalog, ...)` | `{status, uri, method, identity_score, suggestions, reason_codes}` |
| `candidate_validation` | `validate_candidates(data, graph, allowed_existing_ids=())` | `ValidationResult` |
| `publication_sources` | `materialize_sources(graph, document, merge, canonical)` | None (mutates the evidence graph) |
| `view_report` | `build_report(path, graph, views)` | plain report dict for the HTML page |
| `view_html` | `write_report(...)` | writes one self-contained HTML page |

---

## 7. RDF dataset model (the named graphs)

- **Roles** (`GraphNames`): `schema` (declared classes/properties), `shapes`
  (SHACL shape graphs), `data` (target canonical data graph), `provenance`
  (evidence + source links), `review` (withheld candidates). The Lturtle
  `entity:`/`class:`/`relation:`/`fact:` namespaces still name the resources
  inside the data graph.
- **Seed** (virtual, via `seed_graph` → `split_legacy_graph`): `onto:ontology`,
  `onto:Entity`, `onto:EntityShape` (targets `onto:Entity`, requires
  `skos:prefLabel` minCount 1). Applied only when a store is wholly fresh.
- **Staging** (never canonical, in-memory per document): a document's source
  graph under `.../staging/<doc>` and per-window candidate graphs under
  `.../staging/<doc>/<window>`; entities use `provisional/<doc>/...` IRIs.
- **Each accepted entity** is typed `onto:Entity`, `owl:NamedIndividual`,
  `skos:Concept`, and `class:<Kind>`; carries `skos:prefLabel`, `rdfs:label`,
  `onto:kind`, optional aliases/comment.
- **Each relation/fact** becomes `relation:<slug>`
  `owl:ObjectProperty` / `fact:<slug>` `owl:DatatypeProperty` with a label.
- **Evidence** (provenance graph): per-record `prov:Collection` +
  `rdf:Statement` reification + `dqv:QualityMeasurement` (xsd:decimal) + the
  PROV chain; plus `onto:statement/<sha>` source links and
  `onto:sourceDocument` / `onto:sourceFile` summaries (from
  `publication_sources`).
- **Audit** (support partition, via merge policy): `onto:ExtractionEvent` and
  `onto:MergeCandidate` records (`rdf:JSON` normalized candidates, decimal
  confidence, decision reasons; no timestamps, no raw text).
- **Review graph**: withheld identities and assertions as `prov:Collection` +
  reified statements + `prov:wasDerivedFrom` (from `build_review_graph`).

---

## 8. Cross-module import graph (main edges)

```
cli.py ──► api.py (RunRequest, run_text_to_graph),
           graph_management.py (LocalTurtleStore), llm.py (OpenRouterExtractor),
           run_report.py (RunReporter, default_report_path)
api.py  ──► pipelines + stores (re-exports; no logic of its own)
pipeline.py ──► windowing, source_staging, source_parse, llm, repair,
                candidate_validation, candidate_graph, source_reconciliation,
                source_validation, document_merge, document_publication,
                merge_policy, entity_lookup (indirect), graph_merge,
                graph_store, graph_management, ingest_sources, task_context,
                prompt_budget, run_report
document_publication.py ──► graph_store (GraphNames, Publication, RdflibGraphStore),
                            graph_partition (partition), graph_management (seed_graph),
                            candidate_graph (PROVISIONAL), publication_sources,
                            source_validation
document_merge.py ──► merge_policy, candidate_graph, graph_merge
source_staging.py ──► merge_policy (plan_graph_merge, canonical_json),
                      candidate_graph, context_render, prompt_budget, graph_merge
source_reconciliation.py ──► candidate_graph (DQV), graph_management (ONTO...)
source_validation.py ──► (pySHACL only, imported lazily)
merge_policy.py ──► entity_lookup, graph_management, graph_merge
candidate_validation.py ──► entity_lookup (entity_catalog, identity_key),
                            graph_management, graph_merge (class_uri, label, slug)
candidate_graph.py ──► graph_management (FACT, RELATION, bind), graph_merge (class_*)
graph_store.py ──► graph_partition (for legacy import)
task_context.py ──► entity_lookup, graph_patterns (STRUCTURAL, eligible), ontology_views, source_concepts
context_render.py ──► prompt_budget, task_context (TEXT_PREDICATES, datatype_term)
ontology_views.py ──► graph_partition, graph_skeleton, graph_patterns
view_report.py ──► graph_management (ONTO), graph_patterns, run_report, task_context
view_ontology.py ──► graph_management, graph_store (ReadOnlyGraphStore, RdflibGraphStore),
                     ontology_views, run_report, view_html, task_context
```

Deliberate seams: `source_concepts` / `prompt_budget` have no rdflib or `llm`;
`graph_partition` / `graph_skeleton` / `graph_management` / `llm` /
`ingest_sources` / `source_concepts` / `prompt_budget` have no project imports
(except `graph_patterns` → `graph_management.ONTO`); `windowing` depends on
`prompt_budget.estimate_tokens` only; pySHACL is imported lazily inside
`validate_source_graph`.

---

## 9. Composition diagram (what originates from what)

```
source files ──► find_text_files / read_source ──► make_source_document
                                                          │ (content-derived doc ID)
                                                          ▼
                              plan_windows()  →  overlapping TextWindows
                                                          │
                 per window:  task_context over final graph  +  task_context over staging graph
                                                          │
                          layered_context_text()  →  one budgeted block (source items "(this document)")
                                                          │
                          make_prompt() → extract_validated() → [repair ≤ N]
                                                          │
                          validate_candidates()  (same gate every attempt; any error → window rejected)
                                                          │
                          plan_window_admission(source staging graph only; PROVISIONAL IRIs)
                                                          │
                          build_candidate_graph()  →  window candidate graph (evidence, kept)
                          apply_merge_plan()  →  source staging graph grows
                                                          │ (all windows)
                                                          ▼
              reconcile_document()  →  report (entities, aliases, overlap supports, unresolved, conflicts)
              build_source_artifact()  →  deterministic N-Triples + metadata
              validate_source_graph()  →  pySHACL  (non-conformance → SourceValidationError)
                                                          │
              plan_document_merge(canonical scope)  →  identity decided ONCE (accept/duplicate/review)
                                                          │
              compile_document_publication()  →  proposed target + remapped evidence + review graph
              validate_source_graph(proposed data)  →  (non-conformance → PublicationValidationError)
                                                          │
         publish_document(store, plan)   ←── one atomic store.publish() replacing target/provenance/review
         (or dry_run: report the same plan, never publish)
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
| Role / resource namespaces | `entity/ class/ relation/ fact/ graphs/(schema\|shapes\|data\|provenance\|review) provisional/ metric/ staging/ candidate/ document/ source-file/ statement/ review/` |
| Default output dataset | `ontology.trig` (`.ttl` = explicit legacy Turtle compatibility) |
| Window target / overlap | `800` / `100` tokens (`WINDOW_STRATEGY_VERSION = 2`) |
| Document ID / window ID | `doc-<sha256[:16]>` / `win-<sha256[:16]>` |
| Merge policy version | `2` (`MERGE_POLICY_VERSION`) |
| Candidate mapping version | `2` (`CANDIDATE_MAPPING_VERSION`) |
| Document merge version | `1` (`DOCUMENT_MERGE_VERSION`) |
| Auto-accept confidence | `0.80` (`AUTO_ACCEPT_MIN_CONFIDENCE`) |
| Close-spelling threshold | `0.96` (`CLOSE_SPELLING_THRESHOLD`, review-only) |
| Default repair attempts | `2` (`ExtractionConfig.repair_attempts`) |
| Default LLM model | `openrouter/pareto-code:nitro` |
| Env vars | `OPENROUTER_MODEL` / `OPENROUTER_API_KEY` |
| LLM | `https://openrouter.ai/api/v1/chat/completions`, temperature `0`, timeout `60` s, title `"Simple Text to Ontology"`, system prompt `"Extract knowledge. Return only JSON."` |
| Accepted source extensions | `.txt .md .rst .csv .json .jsonl .yaml .yml .xml .html .log` |
| Seed graph size | 8 triples |
| Prompt budget | `total_limit 30_000 · context_tokens 1_400 · fixed_prompt_tokens 400 · output_reserve 4_000 · safety_margin 500`; `chars_per_token 3` |
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
| Missing API key | `llm.ask_llm` | `RuntimeError("Set OPENROUTER_API_KEY first")` |
| OpenRouter HTTP error | `llm.ask_llm` | `RuntimeError(f"OpenRouter error {code}: {message}")` |
| Non-JSON / invalid JSON answer | `llm.ask_llm` | `InvalidResponseError(...)` (caught by `repair._attempt`) |
| Invalid candidate package | `pipeline._extract_window` | `RuntimeError(format_validation_failure(...))` |
| Source SHACL non-conformance | `pipeline.run_text_to_graph` | `SourceValidationError` (carries validation, artifact, report, sidecar) |
| Proposed-data SHACL non-conformance | `pipeline.run_text_to_graph` | `PublicationValidationError` (carries plan, validation) |
| Final graph changed mid-window | `pipeline._process_document` | `RuntimeError("the final ontology changed during window processing")` |
| Duplicate role names / bad staging ns | `graph_store.GraphNames.validate` | `ValueError` |
| Budget without ceiling/arithmetic | `context_render.allowance` | `KeyError` |
| `main()` catches `RuntimeError`/`OSError` | `cli.main` | print to stderr, `SystemExit(1)` |

Source and publication validation errors leave the final graphs unchanged;
`--dry-run` never calls `store.publish`.

---

## 12. Current data snapshot (`ontology.trig`, as parsed from the file)

The dataset holds five roles. Current sizes at the time of writing
(numbers grow with every run, so the repository tests do **not** pin them):

| Named graph | Current triples |
|---|---|
| `graphs/schema` | ~2 (seed ontology structure) |
| `graphs/shapes` | ~5 (the embedded `EntityShape` from the seed) |
| `graphs/data` (target) | ~10 900 |
| `graphs/review` | ~2 700 |
| `graphs/provenance` | ~111 700 |
| union of all graphs | ~125 300 |

Entity kinds currently present include `Person`, `Organization`, `Brand`,
`Project`, `Place`, `Technology`, `Concept`, `Process`, `Component`, and many
more; domain properties include ~344 `relation:*` and ~486 `fact:*` predicates
with ~1 100 relation and ~1 150 fact assertions. Exact partition/skeleton/
pattern numbers are pinned on the frozen miniature in
`tests/fixtures/miniature_repository.ttl`, not on the live dataset.

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
| `test_llm.py` | No dedicated file — `llm` is exercised through the patched boundary. |
| `test_source_concepts.py` | Record fields/vocabularies, determinism, Unicode preservation, weighting/caps, word-boundary phrases, no rdflib/`llm` import. |
| `test_ontology_views.py` | The five fields; façade equals direct calls; lossless partition; observations never become declared structure. |
| `test_task_context.py` | Tier order, name/label/alias matching, bounded expansion, restriction bundles, patterns, native vs generic cards, caps, determinism. |
| `test_context_render.py` | Section order, declared vs observed, six restriction forms, defused delimiters, truncation, `existing_ids` derivation, allowance never exceeded. |
| `test_prompt_budget.py` | Estimator, allowance arithmetic, priority order, oversized items dropped whole, dependency bundles charged once, injected counters. |
| `test_graph_partition.py` | Role rules per triple, source/audit predicates, restrictions, remainder, lossless/disjoint/read-only invariants (sizes pinned on the frozen miniature). |
| `test_graph_skeleton.py` | Core retention, no inference, supported vs unsupported restrictions, subset invariant. |
| `test_graph_patterns.py` | Class/literal/unknown ranges, counting, coverage/cardinality, most-specific class, exclusions, ordering, read-only. |
| `test_publication_sources.py` | Document/file records, statement source links, resource summaries, review never gets sources. |
| `test_run_report.py` | Reporter streams, Markdown blocks, checkpoint methods. |
| `test_cli.py` | Argument parsing, `.ttl` compatibility selection, `--report` / `--dry-run` wiring, exit codes. |
| `test_view_html.py` | `view_html.write_report` renders `view_report.build_report` output as one self-contained page. |
| `test_install_smoke.py` | The package imports and the console script is installed. |

---

## 14. Gotchas & non-obvious behavior (from source and tests)

1. **Content identity ≠ file identity**: a document ID is a digest of its
   normalized text. The same content in two files shares one document but keeps
   two `onto:source-file` records; changed content creates a new document.
2. **Windows are reproducible but not content-faithful slices**: they tile the
   normalized text (spans never drop or duplicate characters), but boundaries
   can fall mid-sentence; `window_id` depends on strategy version, target/
   overlap, tokenizer name, document ID, index, and offsets.
3. **Staging never decides canonical identity**: `plan_window_admission` sees
   only the source staging graph; new entities get `provisional/<doc>/...`
   IRIs; canonical resolution happens once at document merge.
4. **`existing_id` cannot resolve inside a window**: canonical resources are
   not in the staging graph, and source-local items are marked `native: False`,
   so nothing source-local can become a reusable `existing_id`.
5. **The final ontology is invariant during windowing**: a triple-level
   snapshot is compared after every window and after reconciliation; any change
   raises `RuntimeError`.
6. **Repair never bypasses validation**: a repaired answer passes exactly the
   same `candidate_validation` gate; after `repair_attempts` failures (default
   2, 0 disables) the window is rejected.
7. **Candidate graphs are evidence, not assertions**: asserted triples and
   their `rdf:Statement` reifications are both present, which is what lets
   reconciliation count independent supports without trusting reification alone.
8. **pySHACL runs over a copy** with `inference="none"` and no infos/warnings;
   shapes come from `ValidationConfig.shape_graphs`, else the configured shape
   roles, else legacy embedded shapes.
9. **Exact duplicates corroborate**: an existing exact triple is planned as
   `duplicate` (any confidence) and is never re-added; each window's confidence
   measurement stays as independent evidence in the provenance graph.
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
18. **Close spelling (≥ 0.96) is review-only**: it never auto-resolves and uses
    only the preferred name, never aliases; kind mismatch blocks resolution.
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
23. **Validation fails closed**: one error rejects that window's whole package;
    duplicates are warnings, not errors. `format_validation_failure` never
    includes the raw model response.
24. **Fact duplicate keys include the JSON type**: `"1"`, `1`, and `true` are
    distinct facts; NaN/±infinity and collections are rejected.
25. **The viewer reads read-only**: `ReadOnlyGraphStore` wraps a TriG store and
    every view is built in memory; only `-html` writes a file (the HTML page).

---

*End of architecture map. Generated from source files only; no external documentation was consulted.*