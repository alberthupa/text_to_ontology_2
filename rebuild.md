# Graph-centered knowledge application — rebuild project specification

Date: 2026-10-12  
Last updated: 2026-10-23  
Status: proposed implementation specification for a new project  
Priorities: clean code, clear architecture, interchangeable RDF storage, shared capabilities across interfaces.

## 1. Purpose and desired result

Build a Python application that turns source documents into a curated, evidence-backed RDF knowledge graph and lets people and agents inspect, query, discuss, and edit that graph.

The application starts with an existing or generated ontology. It extracts knowledge from documents, resolves identities against accepted knowledge, validates proposed statements, preserves source evidence, and publishes accepted changes. It also provides graph health analysis, bounded graph context for LLMs, and previewable graph editing.

The same capabilities must be available through a public Python API, an HTTP API, CLI commands/scripts, a web UI, and agent skills. Skills invoke the CLI, HTTP API, or optional MCP tools; they do not implement a separate application.

Persistent RDF storage must be selected through configuration. Required adapters for this rebuild are local TriG and Apache Jena/Fuseki. Amazon Neptune RDF is a future adapter target, not an implementation requirement or release gate. A backend switch must not require changing extraction, identity, validation, editing, or chat logic. Backend differences must be explicit and tested.

Create a new repository/package. Treat the old repository as a source of algorithms, behavior examples, fixtures, and UI assets. Do not import it at runtime or copy its package wholesale. Rewrite boundaries first, then selectively adapt useful functions.

### New project identity and workspace

- Repository and directory name: `text_to_ontology_3`.
- Python import package: `text_to_ontology_3`; distribution name: `text-to-ontology-3`.
- On the current machine, create the project at `/home/albert/repos2/text_to_ontology_3`, beside the reference repository. On another machine, use the same sibling-directory arrangement under a suitable workspace root.
- Initialize an independent Git repository, virtual environment, dependency lock, and test configuration. Do not nest the project inside `text_to_ontology_2` or use a worktree of its history.
- Keep a separate reference checkout of `text_to_ontology_2` at the pinned code commit below. Fetch the specification separately from the reference branch; do not reset an existing working checkout to obtain the baseline.
- Creating or configuring a hosted Git repository is separate from initializing the local repository; its remote URL has not yet been selected.

## 2. Source baseline and how to use this specification

Reference repository: https://github.com/alberthupa/text_to_ontology_2  
Reference branch: `trace-prefixes`  
Reviewed commit: `ac18ec97ef1482f5c81fd3a1128334ab992fa9fe`

Pinned source browser: https://github.com/alberthupa/text_to_ontology_2/tree/ac18ec97ef1482f5c81fd3a1128334ab992fa9fe

The pinned commit is the authoritative code baseline, including the later `src:`/`trace:` prefix separation, provenance migration, and studio response handling. Use the exact commit rather than the moving branch tip when reading or adapting code. The rebuild specification is maintained separately on the reference branch. Local dataset edits and backup files are not part of this handoff.

All old-code paths below are relative to that repository and commit. Unless stated otherwise, Python module references live under `src/text_to_ontology/`. Old tests live under `tests/`; frontend assets live under `frontend/`.

Read these first:

- [README](https://github.com/alberthupa/text_to_ontology_2/blob/ac18ec97ef1482f5c81fd3a1128334ab992fa9fe/README.md): product behavior and current entry points.
- [Current architecture](https://github.com/alberthupa/text_to_ontology_2/blob/ac18ec97ef1482f5c81fd3a1128334ab992fa9fe/docs/current_architecture.md): pipeline, named graphs, module contracts, and current limitations.
- [Connectivity plan](https://github.com/alberthupa/text_to_ontology_2/blob/ac18ec97ef1482f5c81fd3a1128334ab992fa9fe/docs/ingestion_connectivity_plan.md): graph quality rules and measured failure cases. Its header reports P0–P6 implemented, with real-model baseline/comparison work still pending.
- `docs/app_map.html` and `docs/data_flow.html`: supporting navigation maps.

These describe the old app, not mandatory architecture for the new one. Files under `docs/old/` are historical proposals, not current requirements. The pinned source and applicable tests resolve discrepancies in old documentation.

For each task: read its listed sources; implement the new contract; adapt the smallest useful code; add behavior-focused verification; document deliberate behavior differences. Record source provenance in `docs/reuse-map.md`. A task is complete only when its acceptance condition is demonstrated.

## 3. Product scope and invariants

### Required capabilities

1. Create a starter ontology from text; import an existing RDF ontology while preserving its IRIs.
2. Ingest one document or a collection, including reproducible windowing for long documents.
3. Extract entities, relationships, and literal facts using a replaceable model provider.
4. Resolve identities, handle aliases, and flag ambiguity and conflicts for review.
5. Validate vocabulary, relationship endpoints, and SHACL constraints.
6. Preserve provenance, confidence/support metadata, and document-to-statement links.
7. Inspect graph neighborhoods, structural views, expected-link gaps, and quality metrics.
8. Answer questions from a bounded, inspectable graph context.
9. Preview and apply graph edits; keep chat-generated edits as proposals.
10. Import/export datasets and report job progress and outcomes.

### Behavioral invariants

- Schema, shapes, data, provenance, review, and temporary candidate/staging content have explicit roles and graph IRIs.
- A document is processed in staging before accepted knowledge changes. Failed extraction/validation must not publish that document's partial knowledge.
- Successful publication commits domain statements and their evidence/review records together.
- Re-ingesting a changed document replaces that source's earlier contributions atomically. Statements still supported by other documents or explicit curation remain; re-ingesting unchanged content creates no duplicate statements or evidence.
- Data-only ingestion cannot silently expand the ontology. Schema modification is a separate explicit capability.
- Identity ambiguity is reported; uncertain matches are not silently merged.
- Missing links may be proposed only from supporting content. Folder paths are context hints unless a separate, explicit policy permits another use.
- Dry run executes planning and validation but performs no persistent mutation, including no persistent failed-staging retention.
- An applied patch is the reviewed patch, against the reviewed dataset revision. A stale preview is refused.
- Every interface invokes the same rules. No graph business logic lives in the UI, CLI, HTTP handlers, skills, or MCP handlers.
- No use case relies on a backend's internal dataset, connection object, or local file layout.

## 4. Architecture decisions to establish before features

Use a modular monolith with hexagonal architecture. Organize the core by meaningful capabilities; use small functions and straightforward composition. Do not introduce microservices, a generic workflow engine, a DI framework, or deep inheritance hierarchies for this rebuild.

### Dependency rules

- `domain` contains meaning, policies, and deterministic graph transformations. It does not import application services, adapters, HTTP frameworks, provider SDKs, or filesystem code.
- `application` orchestrates use cases and defines ports. It imports domain code and port contracts, never concrete adapters.
- `adapters` implement ports and convert external representations.
- `interfaces` translate input/output and call application services. They do not perform merge, validation, identity, or publication decisions.
- `bootstrap` is the composition root. It may import all layers to wire them together.
- Presentation directives and HTTP models are built outside domain services. A shared result should describe graph scope, changes, evidence, and errors; a web presenter decides how to display it.

RDF is a deliberate domain technology. RDFLib terms and small detached `Graph` values may be used in domain computation. Persistent `Dataset` access, network connections, parse/serialize I/O, and storage ownership stay in adapters. Do not recreate RDF as a large custom object model. Use typed dataclasses for requests, results, graph scope, proposed changes, and identity decisions where they make contracts clearer.

Suggested layout (names may change; dependencies may not):

```text
src/text_to_ontology_3/
    domain/
        ontology/
        ingestion/
        curation/
        context/
        analysis/
    application/
        services/
        ports/
        contracts/
    adapters/
        storage/
        models/
        validation/
        sources/
        jobs/
        state/
    interfaces/
        python/
        cli/
        http/
        mcp/
        presenters/
    bootstrap/
frontend/
skills/
tests/
    unit/
    application/
    storage_contract/
    integration/
    acceptance/
docs/
    adr/
    reuse-map.md
```

Avoid creating empty abstractions solely to fill this tree. Add a module when it has a clear responsibility. Use one authoritative contract per dependency; do not keep old and new `GraphStore` types with different meanings.

### RDF storage contract

Define persistent storage independently from document-local working graphs. Suggested operations are `read_snapshot(scope)`, `query(query, scope)`, `publish(change_set, expected_revision, operation_id)`, and `inspect()`. Final names and signatures are an Epic E02 deliverable.

| Contract concern | Required decision |
| --- | --- |
| Graph scope | Explicit graph IRIs/roles. Never depend on a backend's implicit default union. |
| Snapshot | Immutable-to-caller detached RDF data plus an opaque revision token. Define consistency across included graphs. |
| Change set | Quad additions/removals, intentional graph replacements/deletions, expected revision, and stable operation ID. |
| Publication | All-or-nothing durable commit for the selected scope; all application writers use this path. |
| Revision | Prevent stale publication, including changes to schema/shapes that affected validation. Use a conservative dataset revision initially. |
| Idempotency | Retry after a lost response must not duplicate domain statements or provenance activities. Persist operation identity with the publication. |
| Query result | Stable SELECT/ASK/CONSTRUCT representations; preserve RDF term types. Provider result objects stay inside adapters. |
| RDF identity | Preserve datatype/language tags and named graphs. Define blank-node scope, replacement, and deletion semantics. |
| Capability reporting | Declare supported operations and limits; unsupported guarantees fail clearly. |
| Import/export | Serialization formats are interchange concerns; a `.trig` extension does not select a backend. |

Do not expose an unguarded persistent `update()` that bypasses publication/revision rules. Separate read access from mutation access. Do not preserve the old contract's ambiguous meaning of "change memory now, persist later" for remote adapters.

A generic SPARQL endpoint is not automatically a conforming transactional store. Each adapter must prove snapshot and atomic publication behavior under the single-writer execution model. If a backend cannot satisfy the contract natively, document and test a versioned-graph/publication-pointer design or mark the configuration unsupported. Never silently weaken atomicity.

Local TriG requires atomic file replacement and defined crash durability. One application process owns a writable dataset at a time; use a simple exclusive local ownership lock to refuse a second local writer. Jena/Fuseki deployments likewise use one configured application writer with no external writers. Distributed locking, multi-writer coordination, and remote compare-and-swap protocols are outside this rebuild. Keep a dataset revision for stale edit previews and accidental stale requests within the supported execution model.

### Execution and state

Use cases are callable synchronously. A job runner optionally wraps them for background execution. Use one active write operation per dataset, covering preparation through publication. Refuse another write with a clear busy result while ingestion or another write is active. Do not add automatic re-planning, conflict retry loops, distributed queues, or multi-writer coordination. Direct CLI writes must acquire local dataset ownership or use the running application API.

Documents, job records, chat sessions, prompt overrides, and pending previews are separate state concerns. A simple SQLite sidecar is a suitable initial adapter for durable application state; original document bytes can live in a source adapter. Store graph knowledge/evidence in RDF without forcing every operational record into RDF. Keep sidecar state coordinated by operation IDs; do not claim a distributed transaction across SQLite and the RDF store.

### Crash recovery and authoritative publication receipts

The RDF store's durable publication receipt is authoritative for whether a knowledge change committed. SQLite job state is an operational projection and must be reconciled with receipts after interruption; a stale job status cannot override a committed publication.

- Allocate and persist an operation ID before submitting a write. A batch has a parent job ID and stable per-document publication IDs, so recovery can distinguish committed documents from unfinished ones.
- Publish the receipt atomically with domain, evidence, review, and source-revision changes through the same guarded storage operation. Include dataset ID, operation ID, a fingerprint of the intended change, resulting revision, and enough outcome/source-revision information to reconstruct the committed result. Keep receipts outside business-context selection.
- Expose receipt lookup through the storage port. Check for an existing receipt before rejecting a retried request for its now-stale expected revision. The same operation ID and fingerprint returns the prior committed result without writing again; reusing the ID for a different change returns a structured error.
- On startup or job recovery, reconcile interrupted writes by operation ID. A matching receipt marks that publication committed and repairs missing/stale SQLite result state, including when the process died after RDF commit but before recording job completion or returning a response.
- If authoritative lookup confirms no receipt and no request remains in flight, record the publication as interrupted/uncommitted. Preserve earlier committed batch documents. Resuming unfinished work must use the normal validation and guarded publication path; never infer success from staging files or progress events.
- A timeout, unavailable RDF store, or request that may still be in flight leaves commit outcome unknown. Reconcile or retry with the same operation ID; do not label it failed/uncommitted, submit a new ID, or compensate by deleting possibly committed knowledge. Serialize receipt lookup and publication through the single writer; do not allow overlapping retries. Resolve an unknown in-flight publication before accepting another write.
- Receipts must survive process restarts and later dataset revisions. Do not prune them in this rebuild. They establish publication outcomes, not a complete backup of chat sessions, source bytes, or every job event.
- Add failure-injection coverage for interruption before publication, atomic publication failure, commit followed by lost response, commit followed by failed SQLite update, unavailable receipt lookup, same-ID retry after later revisions, and recovery of a partially completed batch. Verify no duplicate statements/evidence and no false success or loss of committed data.

### Preserve the existing graph-context token budgeting

The reference implementation already selects relevant graph material, renders it compactly, and shrinks the context to the remaining prompt allowance. Adapt this mechanism rather than designing a replacement from scratch. Keep relevance selection, rendering, and token fitting separately callable and testable.

Read these sources at the pinned code commit:

- `task_context.py`: `build_task_context` / `select_task_context` select relevant schema, patterns, resources, and example assertions with deterministic priorities and bounded expansion.
- `context_render.py`: `render_context_items`, `assembly_overhead`, `allowance`, and `prepare_prompt_context` render complete items, charge headings/separators, and apply the configured allowance.
- `prompt_budget.py`: `context_allowance` computes remaining capacity; `fit_context_items` keeps priority-ordered complete items together with their required dependencies and reports omitted IDs, costs, used tokens, and counter identity.
- `source_staging.py`: `layered_context_text` fits canonical and source-local context together under one shared allowance, marking earlier-window knowledge as `(this document)`.
- `pipeline.py`: `budget_for`, `_fixed_blocks`, `_window_context`, and `_extract_window` integrate per-window source cost and fixed blocks into extraction. The core-schema setup in `run_text_to_graph` uses the whole schema when it fits its separate allowance and falls back to word-matched schema selection when it does not.
- `graph_scope.py`: `Scope.render_for_model` provides the separate chat rendering path: compact prefixes/names, charge the header, and omit whole triples when its supplied budget runs out. `graph_chat.py` consumes this rendering. This path currently takes a supplied graph budget; it does not itself compute the full remaining model window.
- Verification sources: `tests/test_prompt_budget.py`, `tests/test_context_render.py`, `tests/test_source_staging.py`, `tests/test_schema_context.py`, and the scope/rendering tests in `tests/test_graph_chat.py`.

Preserve the extraction allowance calculation:

```text
remaining = max(0, total_limit - fixed_prompt_tokens - source_tokens
                   - output_reserve - safety_margin)
context_allowance = min(context_tokens, remaining)
```

Here `fixed_prompt_tokens` includes the extra cost charged for document headers, core schema, anchors, and same-folder hints. Charge rendering overhead before fitting items. When only an explicit context ceiling is configured, the reference renderer also accepts that mode; never silently invent missing budget values. Preserve whole-item/dependency fitting, deterministic selection, zero allowance producing empty optional context, and diagnostics showing what was omitted. Context shrinking does not mutate the stored graph or truncate the source document.

The current default counter is `estimate_tokens`: `ceil(character_count / 3)`. It is an estimate, not a model tokenizer. Lower-level fitting/rendering functions accept an injected `count_tokens` callable, while the current extraction integration explicitly uses the estimator. The reference defaults are `total_limit=30000`, `context_tokens=1400`, `schema_tokens=3000`, base `fixed_prompt_tokens=400`, `output_reserve=4000`, and `safety_margin=500`. The total limit is configured, not discovered from a model name.

In the rebuild, retain the estimator fallback and expose the counter through composition/configuration so a model tokenizer can be injected consistently into source sizing, fixed-block sizing, rendering, and fitting. Report which counter and limits were used. Preserve the existing full-schema/word-matched fallback behavior; exceeding the separate schema allowance is not by itself a reason to reject ingestion. Validation still uses the full configured vocabulary and shapes.

As an explicit integration improvement, check the final assembled request against the configured input allowance using the selected counter, including customized prompts and fixed blocks. Shrink optional graph context first. If mandatory content still exceeds that allowance, return a structured budget error before the model call. This final-request check is a rebuild requirement, not a claim about a guarantee already provided by the reference implementation.

### Document identity and re-ingestion policy

- A source occurrence has a stable identity within a dataset, separate from its content hash. For files, use a configured source collection ID plus normalized relative path; for supplied text, accept an explicit source key. Do not use a machine-specific absolute path as the portable identity.
- Identical content at different source keys represents separate supporting occurrences. Re-ingesting an unchanged occurrence with the same effective processing configuration is an idempotent no-op. A deliberate reprocess or changed effective configuration may produce a new extraction revision, replacing the previous one rather than accumulating duplicate support.
- Changed content at the same source key creates a proposed replacement revision. Stage, reconcile, and validate the complete replacement before changing accepted knowledge.
- Commit removal of that source's obsolete support and addition of its new support in one guarded publication. Preserve statements supported by another source or explicit curation; remove an obsolete statement only when no retained support remains. Preserve entity IRIs still referenced by retained statements; do not perform implicit orphan-entity cleanup.
- Extraction, validation, or publication failure leaves the source's previous accepted revision and contributions intact. An empty replacement follows the same validation/publication rules; it cannot bypass configured constraints.
- A renamed/moved source key is a new occurrence unless an explicit relocation operation identifies it as the same source. A file missing from a later directory scan is not an implicit deletion request. Automatic relocation and source deletion workflows are outside this rebuild unless separately specified.
- Track accepted source revision and statement support durably enough to rebuild operational indexes after a crash. Legacy statements without known support must not be deleted automatically by source replacement.

## 5. Delivery sequence and milestone gates

| Milestone | Epics | Demonstration |
| --- | --- | --- |
| M0: foundations | E00–E02 | Enforced dependency rules; typed core contracts; storage contract suite with memory/local adapters. |
| M1: storage proof | E03 | One shared graph use case runs unchanged on local TriG and Jena/Fuseki. Core services have no dependency on either concrete adapter. |
| M2: reliable knowledge publication | E04–E06 | Import ontology, ingest a multi-window document, validate and commit evidence-backed knowledge on two backends. |
| M3: inspection and curation | E07–E08 | Health, bounded graph chat, and revision-safe edit preview/apply. |
| M4: all invocation surfaces | E09–E10 | Python/API/CLI/UI/skills invoke shared services; jobs survive the documented lifecycle. |
| M5: release parity | E11 | TriG and Jena pass adapter gates; migration, packaging, and end-to-end parity pass. |

E03 proves storage interchangeability on TriG and Jena/Fuseki before feature architecture is accepted. No Neptune account, credentials, infrastructure, SDK, live spike, or adapter implementation is required for this rebuild. E09's schemas/operation registry begin in E01 and its adapters grow with each completed use case.

## 6. Epics and implementation tasks

### E00 — Establish a new project and behavioral baseline

**Goal:** create a clean starting point and preserve important behavior without inheriting the old structure.  
**Depends on:** none.  
**Epic acceptance:** new project runs independently; agreed invariants and representative fixtures are documented.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E00.1 | Initialize package, dependency lock, CLI entry point, test runner, formatter/linter, type checker, and CI. Choose a supported Python version explicitly. | `pyproject.toml`, `scripts/install_smoke.sh`, `tests/test_install_smoke.py` | Install built package in a clean environment and execute a minimal command. |
| E00.2 | Write ADRs for layering, RDFLib value use, graph roles, publication semantics, and multiple interfaces. Add architectural rules to the new `AGENTS.md`. | `AGENTS.md`, architecture docs | Rules are specific enough to reject a use case importing a concrete store. |
| E00.3 | Build fictional fixtures covering named graphs, aliases, conflicts, evidence, invalid endpoints, long documents, and custom ontology IRIs. Separate product invariants from old incidental outputs. | `tests/fixtures/`, `tests/connectivity_fixtures.py`, `tests/test_connectivity_pipeline.py`, `tests/test_starter_import.py` | A behavior inventory lists required outcomes and deliberate changes; no client dataset is committed. |
| E00.4 | Create reuse map with old path/function, destination, retain/rewrite/retire decision, and verifying test. | All sources listed below | Every reused module can be traced; old package is not a runtime dependency. |

### E01 — Define application boundaries and shared contracts

**Goal:** make every capability invocable without a browser or CLI.  
**Depends on:** E00.  
**Epic acceptance:** a small use case runs through direct Python and a fake interface with the same result; imports obey the architecture.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E01.1 | Define typed requests/results/errors, dataset IDs, graph scopes, operation IDs, and graph-role configuration. Separate application input from backend file paths. | Dataclasses in `pipeline.py`; `GraphNames` in `graph_store.py` | Requests can identify a remote dataset without containing a TriG path. |
| E01.2 | Define ports for extraction/text generation, SHACL validation, source retrieval, progress reporting, and application state. Keep interfaces focused. | `Extractor`/`Reporter` in `pipeline.py`, `llm.py`, `source_validation.py`, `workspace.py` | Application tests inject fakes; no network, file access, or concrete adapter construction occurs in services. |
| E01.3 | Create composition root and validated configuration; assemble adapters there. Fail clearly on incompatible configuration. | `cli.py`, `_final_store` in `pipeline.py`, `Workspace.__init__`, provider setup in `llm.py` | Backend/model can be selected in config; configuration/environment reads remain outside core logic. |
| E01.4 | Define operation catalog with input/output schemas, read/write classification, background eligibility, and error codes. Reserve stable capability names. | `operations.py` | Catalog describes shared services, not `Workspace` methods; transport-specific fields are outside domain results. |
| E01.5 | Add dependency checks and a thin public Python facade; keep request validation consistent across adapters. | `api.py`, CLI/API tests | CI catches forbidden imports; public API exports the new contracts, not the legacy store. |

### E02 — Design and implement backend-neutral RDF persistence

**Goal:** establish the highest-priority boundary before feature migration.  
**Depends on:** E01.  
**Epic acceptance:** memory and TriG adapters pass the same contract, including single-writer ownership, restart, and failure behavior.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E02.1 | Finalize snapshot/query/publication/inspection ports and revision semantics. Separate persistent store from detached working graphs. | `graph_store.py`, `document_publication.py` | Contract defines visibility, durability, graph scope, term identity, stale reads, and errors without referencing local memory. |
| E02.2 | Define `GraphChangeSet` with additions/removals/replacements/deletions and an atomic durable publication receipt plus lookup port. Follow the authoritative-receipt recovery policy above. Reject conflicting instructions; define retry behavior and provenance activity IDs. | `Publication`, `DocumentPublicationPlan`, `graph_edit.publication`, `publication_sources.py` | Matching operation ID/fingerprint returns the prior receipt even after later revisions; mismatched reuse errors; serialized retries do not republish. New stale publications are rejected, and failed publication leaves no receipt. |
| E02.3 | Implement memory adapter for fast application tests and a TriG adapter with explicit locking, version checks, atomic replacement, and rollback/failure cleanup. | `RdflibGraphStore`, `_atomic_write`, graph-store tests | A second local writer is refused by the ownership lock; injected failure leaves prior committed dataset intact. |
| E02.4 | Rewrite/extend shared store tests for snapshots, explicit graph scope, RDF terms/blank nodes, atomic multi-graph commit, stale-preview protection, and idempotency. Verify reopen/restart behavior and refusal of a second local writer. | `tests/store_contract.py`, `tests/test_graph_store.py`, `tests/test_plain_rdf.py` | Identical contract suite runs for both adapters; persistence cases reopen the adapter; ownership tests use a separate process. |
| E02.5 | Implement import/export codec services. Separate plain RDF import and role assignment from reading an established dataset. Define graph-isomorphism comparison. | `import_legacy_turtle`, `export_dataset`, `ttl_to_trig.py`, `trig_to_ttl.py`, `starter.parse_rdf` | Round-trip keeps named graph content, literals, and blank-node meaning; default-graph input cannot silently disappear. |

### E03 — Prove storage interchangeability with remote RDF backends

**Goal:** uncover storage assumptions before rebuilding the large pipeline.  
**Depends on:** E02.  
**Epic acceptance:** local and Jena run the same shared use case; future adapters can implement the documented ports without changing application/domain code.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E03.1 | Implement reusable SPARQL transport/result normalization where genuinely common. Keep binding serialization, errors, timeouts, and authentication at adapter boundaries. | `GraphStore.query`; existing query contract tests | SELECT/ASK/CONSTRUCT results preserve RDF terms; special characters and IRIs are handled safely. |
| E03.2 | Implement Jena/Fuseki adapter against a specified deployment mode. Verify multi-graph atomic publication and durable revisions under the single-writer deployment using current official docs and live integration tests. | No old Jena adapter exists; use E02 contract | A failed publication cannot partially update data/provenance/review; the application serializes writes and refuses a stale edit preview. |
| E03.3 | Document the extension procedure for a future RDF adapter, with Neptune as a future target. List required ports, configuration registration, capability declarations, and contract tests. Keep endpoint/authentication/transaction details inside adapters. | E02 ports and contract suite; no old Neptune adapter exists | TriG and Jena use the same services and contract suite. Documented extension points require no changes to application/domain logic; no Neptune implementation, placeholder adapter, SDK, credentials, or live tests are added. Neptune support remains unverified until a later adapter passes its own live gates. |
| E03.4 | Run a shared vertical slice: import a tiny ontology, query it, publish evidence with a fact, export, reopen, and compare. | `GraphNames`, import/export helpers, store tests | Same application service and expected RDF meaning on TriG and Jena. |
| E03.5 | Document adapter capability matrix, external-writer rules, operational setup, and backend switching. | New work | Changing config is sufficient for the slice; provider-specific code is absent from core. |

### E04 — Rebuild ontology creation, import, and vocabulary management

**Goal:** establish authoritative schema and shapes before ingestion.  
**Depends on:** E02; E03 storage proof before accepting feature architecture.  
**Epic acceptance:** generated/imported ontology uses the same validation/publication path on two backends.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E04.1 | Adapt pure ontology proposal normalization and validation; expose `ProposeOntology` separately from committing it. | `starter.validate_starter`, `_normalize`, related helpers; `tests/test_starter.py` | Invalid proposal is inspectable and cannot change persisted graphs. |
| E04.2 | Implement `ImportOntology` with explicit format/role mapping and preservation of supplied IRIs. Isolate parsing in codec adapters. | `starter.import_publication`, `_roles_from_parsed`, `tests/test_starter_import.py` | Custom class/property IRIs remain authoritative for later ingestion; failed import leaves dataset unchanged. |
| E04.3 | Rebuild vocabulary reading and class/property/endpoint rules; preserve subclass and datatype behavior. Document extraction-policy checks separately from formal OWL/RDFS inference. | `vocabulary.py`, `candidate_validation.py`, endpoint/data-only tests | Frozen vocabulary rejects undeclared use; domain/range checks are clearly defined application policy. |
| E04.4 | Implement `CommitOntology` with revision check and explicit replacement policy when data already exists. Validate affected data or refuse unsafe schema replacement. | `starter_publication`, `Workspace.create_starter/import_starter` | Ontology changes cannot silently invalidate existing knowledge or erase unrelated roles. |

### E05 — Rebuild document processing, extraction, and context

**Goal:** prepare candidate knowledge without touching the accepted graph.  
**Depends on:** E04; ports from E01.  
**Epic acceptance:** deterministic source preparation and fake-model extraction produce a complete, inspectable staged document.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E05.1 | Introduce `SourceDocument` and source adapters for file/directory and supplied text. Separate content ID from source occurrence/path; preserve relative paths and title/heading hints. | `ingest_sources.py`, `windowing.make_source_document`, `Workspace._write_source`, `document_context.py` | Identical content at two paths retains both source occurrences without duplicating knowledge blindly. |
| E05.2 | Adapt reproducible windowing and normalization as pure functions. Version the strategy. | `windowing.py`, `tests/test_windowing.py`, document fixtures | Unicode, CRLF, overlap, boundaries, oversized sentences, and document/window IDs remain tested. |
| E05.3 | Adapt the existing selection/rendering/fitting flow described in "Preserve the existing graph-context token budgeting" above. Preserve the separate schema allowance and word-matched fallback, one shared canonical/source-local context allowance, anchors, and same-folder hints. Wire an injectable counter consistently and check the final assembled request. | `schema_context.py`, `task_context.py`, `source_concepts.py`, `context_render.py`, `document_context.py`, `prompt_budget.py`, `source_staging.layered_context_text`, `pipeline.budget_for/_window_context/_extract_window`; budgeting/rendering/staging/schema tests | Port tests proving long source shrinks context below its ceiling, exhausted allowance yields empty optional context, dependencies fit together, injected counters are honored, and dropped items are reported. Add coverage for fixed blocks, oversized-schema fallback, customized prompts, and mandatory-content overflow before a model call. Later windows retain document subject; full-vocabulary validation remains independent of prompt selection. |
| E05.4 | Implement configured model adapters and prompt repository; adapt bounded repair separately from transport retries. Record model/config/prompt/schema digests. | `llm.py`, `prompts.py`, `source_parse.py`, `repair.py`, related tests | Fake extractor works through the same port; malformed output has bounded repair; timeouts and provider errors are structured. |
| E05.5 | Adapt candidate normalization, endpoint validation, and candidate RDF/evidence construction. | `candidate_validation.py`, `candidate_graph.py`, candidate and endpoint tests | Candidate IRIs remain provisional; confidence is not treated as proof; invalid records have inspectable issues. |
| E05.6 | Implement document-local working graph and window admission. Reuse selection/merge policies where useful without instantiating a persistent adapter in domain code. | `source_staging.py`, `_extract_window`, `_admit_window`, `_process_document` in `pipeline.py` | Each window sees staged earlier knowledge; accepted dataset is unchanged throughout preparation. |

### E06 — Rebuild reconciliation, merge planning, and reliable publication

**Goal:** convert a staged document into one validated, revision-safe accepted change.  
**Depends on:** E05 and E03 proof.  
**Epic acceptance:** multi-window ingestion publishes statements, evidence, and review together; failure and stale revision leave accepted knowledge unchanged.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E06.1 | Adapt document reconciliation, aliases, overlap deduplication, and identity resolution. Make thresholds/config explicit. | `source_reconciliation.py`, `entity_lookup.py`, `merge_policy.py`, `document_merge.py`, related tests | Ambiguity/conflicts create review records; repeated windows retain independent supports without duplicate canonical entities. |
| E06.2 | Implement whole-document SHACL validation through a validation port, initially pySHACL over detached values. Distinguish warning policy from blocking errors. | `source_validation.py`, `tests/fixtures/shacl/`, source-validation tests | Backend choice does not alter configured validation policy; reports preserve actionable focus/path details. |
| E06.3 | Build pure publication planner producing a change set and post-change validation result. Remap candidate evidence to canonical statement identities. Avoid replacing unchanged role graphs. | `document_publication.py`, `graph_merge.py`, `publication_sources.py`, publication tests | Only intended changes are written; each accepted statement has correct remapped evidence. |
| E06.4 | Implement `IngestDocuments` service composing the document phases and guarded commit. Hold the single-writer slot through preparation/publication; do not re-plan or retry automatically on a revision mismatch. Return a clear stale-state error if an unexpected mismatch occurs. Define per-document partial success for batches. | `run_text_to_graph` in `pipeline.py`, pipeline/windowing tests | Completed documents remain committed after a later failure; current document has no partial commit; dry run never mutates persistent state. |
| E06.5 | Rebuild expected-link checks as evidence-backed candidate proposals, using the same validation/planning path. | `link_check.py`, `document_context.py`, connectivity plan/tests | No supporting evidence yields "not established"; endpoint/vocabulary rules are still enforced. |
| E06.6 | Add run results/events, stable per-document operation IDs, receipt-based recovery, and optional failed-staging retention as a separate explicit policy. | `run_report.py`, `SourceGraphArtifact`, `retain_staging`, E02 receipt port | Retry after response loss does not duplicate evidence; reports distinguish committed, failed, uncommitted, and unknown outcomes. Partial-batch recovery retains committed documents and reconciles their results from RDF receipts. |
| E06.7 | Implement source revision replacement using the document identity and re-ingestion policy above. Plan support removals/additions and resulting domain changes together; preserve other-source, curated, and unknown legacy support. | Source/evidence construction in `publication_sources.py`, E02 guarded publication, new source-revision fixtures | Unchanged ingestion is a no-op; changed content removes only unsupported obsolete statements; shared statements and entity identities survive; failed replacement preserves the previous revision; identical content at two paths retains two supports. |

### E07 — Rebuild graph reading, quality analysis, and graph chat

**Goal:** make graph-derived capabilities independent of UI and storage implementation.  
**Depends on:** E04; E06 for populated acceptance fixtures.  
**Epic acceptance:** read-only capabilities return equivalent results on supported backends and cannot publish changes.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E07.1 | Adapt deterministic graph partition/skeleton/pattern/vocabulary views. Keep read scope explicit. | `graph_partition.py`, `graph_skeleton.py`, `graph_patterns.py`, `ontology_views.py`, `seed_view.py` | Schema, business data, and evidence are not accidentally mixed; existing structural fixtures remain useful. |
| E07.2 | Implement `AnalyzeGraphHealth` returning structured metrics; move path/gold-file loading and report formatting to adapters. | `graph_health.py`, health/connectivity tests | Isolates, root-only entities, endpoints, missing links, duplicate suspects, coverage, and gold scores are independently testable. |
| E07.3 | Implement bounded graph scope/neighborhood retrieval and inspectable context artifacts. Separate scope data from `view()` directives. Begin with documented snapshot size limits; add focused remote queries as a measured optimization. | `graph_scope.py`, `task_context.py`, scope/chat tests | Graph and token caps are explicit; term identity survives; no mandatory full remote-dataset download for every display operation. |
| E07.4 | Implement `AskGraph` using scoped context, model text generation, and a session-state port. Keep the exact context/evidence available to callers. | `graph_chat.py`, `Workspace.chat_ask`, chat tests | Answer result identifies scope and dataset revision; unsupported claims cannot masquerade as graph facts. |
| E07.5 | Translate proposed RDF edits in chat into previews, never implicit commits. | `graph_edit.fenced_turtle`, `Workspace._with_proposals` | Asking a question cannot mutate knowledge; proposals use E08's preview contract. |

### E08 — Rebuild graph curation and revision-safe editing

**Goal:** allow deliberate edits through every interface with the same checks.  
**Depends on:** E04, E02; integrate chat after E07.  
**Epic acceptance:** the reviewed changes are exactly those applied, with provenance and stale-state protection.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E08.1 | Adapt patch parsing and deterministic change calculation. Define blank-node edits and absent removals explicitly. | `graph_edit.py`, `tests/test_graph_edit.py` | Parse errors are structured; additions/removals are inspectable without writing. |
| E08.2 | Implement `PreviewGraphEdit`: vocabulary, collision, endpoint, and SHACL checks; store immutable preview artifact, policy version, and dataset revision. | `graph_edit.check_patch`, `Workspace.edit_preview` | Preview result includes exact changes, issues, and an ID usable outside the current web process. |
| E08.3 | Implement `ApplyGraphEdit` loading the preview and atomically publishing changes plus provenance. Bind preview to dataset/policy/revision; define expiration and replay behavior. | `graph_edit.publication`, `Workspace.edit_apply` | Stale preview is refused; a duplicate apply has a defined idempotent result; missing preview never reconstructs unreviewed changes. |
| E08.4 | Expose review listing and explicit resolution of ambiguous identities/conflicts. Define accept/reject/merge decisions and their evidence trail. | `build_review_graph`, merge-policy review decisions | Review changes pass the same publication boundary and cannot bypass schema/identity rules. |

### E09 — Implement Python, CLI, HTTP, jobs, and optional MCP surfaces

**Goal:** expose one capability set across invocation methods.  
**Depends on:** E01; add interfaces incrementally with E04–E08.  
**Epic acceptance:** representative operations behave consistently through Python, CLI, and HTTP; agent tools delegate to these same services.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E09.1 | Complete public Python facade for ontology, ingestion, health, query/context, chat, edits, and import/export. | `api.py`, `operations.py` | Importable API contains typed contracts and services, not provider SDK objects. |
| E09.2 | Implement one coherent CLI with subcommands and `--json`, defined exit codes, stdin/file inputs, and configuration selection. Keep utility scripts as thin CLI/API clients. | `cli.py`; `main` functions in starter/health/view modules; root wrappers | JSON stdout contains only machine-readable result; progress/logging goes to stderr; backend switch requires no command logic changes. |
| E09.3 | Implement HTTP API, preferably with typed schemas/OpenAPI; choose and record framework in an ADR. Map domain errors to consistent status/error codes. | `studio.py`, `operations.py`, studio tests | Handlers validate/map only; no HTTP types leak into services; read-only routes cannot mutate. |
| E09.4 | Implement job-runner and job-state adapters. Support submit/status/result, structured progress, cooperative cancellation before commit, and receipt-based restart reconciliation with SQLite state. Start with local execution and serialized per-dataset writes. | `Progress`, background job methods, `_ProgressReporter` in `workspace.py`, E02 receipt port | A crash after RDF commit but before SQLite update is recovered as committed without republishing. Interrupted/unknown outcomes remain explicit; unavailable lookup cannot produce false success/failure; job IDs and storage guards remain authoritative for their respective roles. |
| E09.5 | Add contract tests comparing direct Python, CLI JSON, and HTTP results using fake models and the same datasets. | CLI/studio/pipeline tests | Invalid vocabulary, stale edits, dry run, and failed publication have equivalent meaning on each surface. |
| E09.6 | If MCP is needed, implement a thin tool adapter from the operation catalog; expose schemas and distinguish reads from writes. | `operations.py` as a manifest reference; no old MCP implementation | Tool invocation calls shared services; tool names/results are tested; no duplicate extraction or editing logic. |

### E10 — Rebuild the web UI and deliver agent skills

**Goal:** keep the graph-centered user experience while making it a client of stable capabilities.  
**Depends on:** E09 and relevant services.  
**Epic acceptance:** users and agents can complete ontology → ingest → inspect → preview/apply workflows without special backend paths.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E10.1 | Reuse/refactor graph viewer and studio assets. Preserve graph focus, filters, views, source details, and relevant-context display. Build a web presenter for display directives. | `frontend/triple-lens.html`, `frontend/studio.js`, `frontend/studio.css`, `view_html.py` | Domain/application results contain no DOM IDs or markup; frontend only displays and gathers input. |
| E10.2 | Connect UI to typed operations/job API with stable error and conflict handling. Use bounded graph views rather than obligatory whole-dataset export. | `studio.js`, `Workspace.dataset_text`, `Scope.view` | UI works unchanged with TriG and Jena configuration; stale edit prompts a new preview. |
| E10.3 | Create skills for ontology creation/import, document ingestion, graph health/inspection, and edit review. Give prerequisites, input/output expectations, example invocations, failure handling, and write semantics. | README workflows, operation manifest; no old skills to port | Skills invoke documented CLI/API/MCP operations and contain no Python business logic or backend-specific direct writes. |
| E10.4 | Exercise skills with machine-readable outputs and an unavailable-service/conflict scenario. Keep provider-specific setup in deployment docs. | New CLI/API contracts | A skill can inspect status, submit ingestion, poll its job, interpret results, and request a fresh preview after conflict. |

### E11 — Validate parity, migrate data, and release

**Goal:** finish the rebuild with demonstrated behavior and storage portability.  
**Depends on:** E03–E10.  
**Epic acceptance:** representative workflows pass on TriG and Jena; release can be installed and configured independently.

| Task | What to implement | Old sources to inspect/reuse | Acceptance |
| --- | --- | --- | --- |
| E11.1 | Build end-to-end acceptance suite: imported ontology, multi-window extraction, aliases/conflicts, SHACL failure, provenance, expected links, chat proposal, edit conflict, retry, and export. | Pipeline/connectivity/starter/edit/chat tests | Tests check public behavior and RDF meaning; no live model required for deterministic CI. |
| E11.2 | Complete live Jena/Fuseki adapter contract tests for publication, revision, authentication where configured, and retry behavior. Record supported versions/modes. | E03 work, new adapter suite | All advertised backends pass their contract gates. Neptune is listed only as a future adapter target and is excluded from this release gate. |
| E11.3 | Implement explicit legacy TriG/Turtle import and graph-role migration. Provide dry-run inventory, backup instructions, and integrity checks. | Existing dataset codecs, `ttl_to_trig.py`, legacy adapter behavior | Migration preserves intended graph meaning/evidence and explains intentional changes; existing data is never silently overwritten. |
| E11.5 | Measure snapshot/query/publication cost and graph size limits; document current scaling envelope and targeted next improvements. | Old snapshot/publication flow as baseline | Large-graph bottlenecks are measured; no blanket promise of constant-memory ingestion or native inference parity. |
| E11.6 | Finish installation/deployment docs, configuration examples, operation catalog, storage matrix, ADRs, reuse map, and operator recovery procedures. | README/install-smoke patterns | Clean install and example workflow work without the old repo; dependencies and backend setup are explicit. |

## 7. Source reuse guidance

| Old code group | Recommended treatment |
| --- | --- |
| `windowing.py`, identity/merge policies, graph derivation algorithms | Strong reuse candidates; adapt into pure domain modules and preserve meaningful tests. |
| `candidate_validation.py`, `vocabulary.py`, connectivity helpers | Retain behavior selectively; extract policy/config and avoid carrying hidden module dependencies. |
| `source_validation.py` | Keep validation semantics; move pySHACL invocation behind an adapter. |
| `candidate_graph.py`, provenance materialization, document reconciliation | Preserve RDF meaning and evidence identities; verify with fictional fixtures. |
| `pipeline.py` | Use phase ordering and tests as a reference. Rewrite orchestration against new ports; do not preserve concrete defaults/path dependencies. |
| `graph_store.py` | Reuse local mechanics where sound; redesign persistent contract, locking, revision checks, and commit semantics. |
| `document_publication.py` | Reuse evidence remapping and validation logic; replace wholesale role replacement with intentional change planning. |
| `workspace.py` | Decompose responsibilities into services/state/job adapters; do not copy as the new central backend object. |
| `operations.py` | Retain discoverable capability idea; upgrade schemas and delegate to services. |
| `graph_scope.py`, `graph_chat.py` | Preserve bounded context and inspectability; separate presentation and session storage. |
| `llm.py`, prompt repository | Adapt into explicit model/config/state adapters; keep transport and parsing/repair separate. |
| `studio.py`, CLI/main functions | Rewrite as thin interfaces; preserve behavior where useful. |
| Viewer/frontend assets | Reuse visual behavior; replace application coupling with typed API clients/presenters. |
| Legacy Turtle lifecycle and root wrapper scripts | Keep only explicit migration/compatibility utilities if justified. |
| Old tests | Reuse fixtures and domain invariants. Rewrite tests that encode path defaults, global workspace state, or in-memory persistence assumptions. |

## 8. Definition of done for every epic

- Its application services can be called directly without HTTP, a browser, or command parsing.
- No new dependency violation or concrete backend access exists in domain/application code.
- Required behavior is tested at the smallest useful level, plus interface/storage contract tests where boundaries matter.
- Storage writes use guarded publication; read-only services receive read-only ports.
- Requests/results/errors are documented and serializable at interface boundaries.
- Source reuse is recorded; old implementation is not a production dependency.
- Feature works with injected fakes; live-model variability is evaluated separately.
- Existing accepted graph remains intact on documented failure paths.
- Code is readable by an intermediate Python developer: focused functions, explicit arguments, simple control flow, no unexplained generic machinery.

## 9. Deliberate first-release limits

- Implement TriG and Jena/Fuseki storage only. Preserve a documented adapter boundary for future Neptune support; do not claim Neptune compatibility before a real adapter proves the required guarantees.

- Support one application writer per dataset. Refuse overlapping writes; exclude external writers and distributed/multi-writer operation. Retain a simple revision check for stale previews, with no automatic conflict retry or re-planning.
- Begin with detached snapshots for operations requiring full SHACL/identity scope, with documented size limits. Storage interchangeability and large-graph scalability are separate goals.
- Do not promise identical native reasoning/search features across databases. Add inference or full-text search as separate capability ports when needed.
- Do not add a plugin framework, distributed event bus, event sourcing, or generic workflow DSL solely for hypothetical future needs.
- Preserve stable behavior, not every historical flag or implementation detail. Record removed/changed behavior in migration notes.

## 10. First implementation instruction

Start with E00, E01, and E02. The first useful running slice is: configure storage → import a tiny named-graph dataset → read/query it → publish a revision-guarded change with evidence → export and reopen it. Prove that same slice on local TriG and Jena before rebuilding extraction.

For each subsequent capability, build the shared use case first, then expose it through Python/CLI/HTTP. Add UI and skills once the operation contract is stable. Complete the behavior and adapter gates before claiming feature parity.

### Independent-agent execution and progress

- Read the new project's `AGENTS.md` and this specification before implementing. Start with E00–E02 and demonstrate the local storage slice; then prove the same slice on Jena/Fuseki in E03 before accepting feature architecture.
- Maintain `docs/progress.md` as the durable handoff ledger. Record the current task, completed task IDs, relevant files/commits, commands and verification outcomes, decisions, blockers, and the next concrete step. Update it after each completed task and before handing off unfinished work.
- Mark a task complete only when its acceptance condition has evidence. Distinguish passed checks, failed checks, and checks not run. Record unavailable dependencies explicitly and continue independent work where possible. Do not claim full completion while required checks remain pending.
- Make routine implementation choices using this plan and the simplicity rule. Record them in the ledger or an ADR when architectural. Ask for clarification only when a material product decision is absent; do not expand scope to solve hypothetical future needs.
- Implement E07's basic graph reading/chat independently of edit proposals. Complete E08's preview/apply mechanism before integrating E07.5 chat-generated edit proposals; a proposal always uses that shared preview contract.
- At handoff, summarize implemented behavior, verification evidence, remaining tasks/blockers, and the next action. Keep enough context in repository files for a fresh agent to resume without this conversation.
