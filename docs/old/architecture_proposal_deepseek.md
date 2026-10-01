# Architecture Proposal — text_to_ontology (deepseek)

A proposal for turning the current collection of loose-but-working modules into a
modular, API-like pipeline. It is a target picture, not a description of today's
code, and nothing here is implemented yet.

---

## 0. The idea in one paragraph

**The RDF graph is the only thing modules share.**

Every step is a small, independent function that takes a graph (and maybe a piece
of text and some parameters) and returns a graph or some derived data. A single
thin orchestrator wires them together in order. Nothing else imports anything
else, and the only "language" that crosses module boundaries is RDF — read with
SPARQL, exchanged as Turtle. Storage sits behind one small adapter, so the same
code runs on an in-memory rdflib graph today and on Apache Jena/Fuseki when the
graph grows too big for memory.

---

## 1. The core principle: graph is the common currency

```text
graph + text/params  -->  module  -->  graph (or derived data)
```

Rules for every module:

1. Takes a graph (or a view/named-graph of one) plus plain parameters.
2. The early steps additionally take **text**; the later steps never see text.
3. Does **one** thing.
4. Either returns derived data (read-only) or produces new triples (write).
5. Never imports another module. Only the orchestrator calls modules.
6. Speaks only standard semantics: RDF, RDFS, OWL, SKOS, SHACL, SPARQL, plus
   common vocabularies (foaf, prov, dcterms). Nothing custom that an existing
   standard already expresses.

This is already ~80% true today: `task_context`, `merge_policy`, `graph_partition`
are already read-only functions over a graph. The proposal mostly *formalizes*
that and changes the storage underneath.

---

## 2. What "API-like" means here (the module contract)

There is no plugin registry and no framework. The "API" is a small set of
conventions:

- One module = one file, one obvious public function named after the module's
  verb (`window()`, `extract()`, `plan()`, `merge()`).
- Read modules never mutate their input: `something(graph, params) -> data`.
- Write modules never mutate their input either: they return a new graph, or
  write through the store adapter (§5). Today's `apply_merge_plan` already
  follows this "return a copy" rule.
- The currency is a `rdflib.Graph` or a store handle — not a bespoke Python
  object — unless the step's job is to *leave* RDF. The three steps that leave
  RDF are `ingest` and `window` (they produce text) and `extract` (it produces
  JSON for the LLM to read). Everything else passes graphs or SPARQL results.
- Each module is independently testable and importable, so any single step can
  be replaced without touching its neighbours.

Why this matters: today the "loose files" feeling comes not from too many files,
but from `ontology.py` knowing every import and every step's order. Moving that
knowledge into an explicit orchestrator and giving each step a stable signature
is what makes it a pipeline instead of a pile.

---

## 3. Directory layout

Keep it flat and obvious. One folder for the modules is enough; no deep nesting.

```text
text_to_ontology/
├── pipeline.py             # the orchestrator: CLI + the explicit run loop
├── store.py                # graph store adapter (memory / fuseki backends)
├── vocab.py                # the ONE place every URI/prefix is defined
├── seeds/
│   └── default.ttl         # the minimal built-in seed, shipped as data not code
├── modules/
│   ├── ingest.py           # find + read sources
│   ├── window.py           # split long text into overlapping windows
│   ├── seed.py             # load seed + shape files into their named graphs
│   ├── context.py          # select + render + budget the context one window needs
│   ├── extract.py          # LLM call: window + context -> candidate JSON
│   ├── validate.py         # normalize candidates, or fail with a report
│   ├── plan.py             # identity + conflict decisions (read-only)
│   ├── merge.py            # materialize a plan into the store
│   ├── check.py            # SHACL conformance
│   └── report.py           # views, patterns, terminal/markdown/html output
├── llm.py                  # the tiny OpenRouter client (a leaf, not a module)
└── tests/
```

Names are chosen to read like a sentence: *ingest → window → seed → context →
extract → validate → plan → merge → check → report*. Reading the folder tells
you the whole flow.

`vocab.py` is important for the "nothing custom" rule (§9): every namespace
(`onto`, `entity`, `class`, `relation`, `fact`, and the standard `rdf, rdfs,
owl, skos, sh, foaf, prov, dcterms, xsd`) is declared in exactly one place, so
nobody invents a URI by hand inside a module.

---

## 4. The modules

| # | Module | Does one thing | Input → Output | Maps from today |
|---|---|---|---|---|
| 1 | `ingest` | find and read source files | file/dir → `list[SourceDocument{path, text, sha256}]` | `ingest_sources.py` |
| 2 | `window` | split long text, keep short text whole | `SourceDocument` + max size → ordered overlapping windows | **new** |
| 3 | `seed` | load seed + shape ttl into the store | ttl path + graph name → nothing (writes schema/shapes) | hard-coded in `graph_management.open_graph` |
| 4 | `context` | select, render, and budget the relevant graph | store + window → prompt-context text + `existing_ids` | `task_context` + `context_render` + `prompt_budget` |
| 5 | `extract` | ask the LLM for candidates | window + context → candidate JSON | `source_parse` + `llm` |
| 6 | `validate` | normalize and check candidates | candidates → normalized candidates \| failure report | `candidate_validation` (+ repair loop, backlog #1) |
| 7 | `plan` | decide identity and conflicts against the full graph | store + candidates + provenance → merge plan (read-only) | `merge_policy` + `entity_lookup` |
| 8 | `merge` | write the plan into the store | plan → SPARQL INSERTs | `graph_merge` (writes via adapter) |
| 9 | `check` | validate the graph against its shapes | store → SHACL conformance report | **new** (backlog #8) |
| 10 | `report` | derive views and human reports | store → schema/instance/support, patterns, html/md | `graph_partition`, `graph_skeleton`, `graph_patterns`, `view_*` |

Notes on the trickier ones:

- **`window` (module 2)** solves the "super long input" requirement without
  changing anything downstream. A window *is* a source text, so every module
  after it stays identical. Provenance records `(source sha256, window index)`
  so each merged triple traces back to its exact window (§6).
- **`context` (module 4)** keeps the existing two-stage narrowing intact —
  `task_context` decides what is *relevant*, `prompt_budget` decides what
  *fits* — just grouped under one name so the flow reads cleanly. The three
  current files can become internal functions of one module; the tests already
  cover the seams.
- **`plan` (module 7)** keeps the important property that identity resolution
  runs against the *complete* graph, not just the prompt's selection. The
  prompt is a window onto the graph; the merge is decided against all of it.
- **`merge` (module 8)** is the only module that changes the graph, and it does
  so by turning an already-complete plan into SPARQL `INSERT` statements. No
  decision logic lives here — the plan is final before merge runs.

---

## 5. Graph store: replace "one ttl file" with a store adapter

### Why

- The main graph keeps growing; parsing the whole `.ttl` into rdflib every run
  does not scale.
- Future inputs include *many* graphs and SHACL shape files, which need to
  coexist rather than be concatenated into one blob.
- SPARQL becomes the natural read/write language between modules — which is
  exactly the "common currency" idea.

### The adapter (the only new abstraction)

One small module, `store.py`, with a deliberately boring interface:

```python
store = open_store("memory:ontology.ttl")              # tests, small graphs
store = open_store("fuseki:http://localhost:3030/ds")  # real runs, big graphs

store.load_ttl(path, graph_name="urn:app:schema")      # put a file in a named graph
store.query("SELECT ?s ?p ?o WHERE { ... }")           # SPARQL SELECT
store.update("INSERT DATA { ... }")                    # SPARQL UPDATE
store.export_ttl(graph_name=None, path="out.ttl")      # get ttl out again
store.source_already_processed(sha256)                 # idempotent re-run (backlog #3)
```

- Nothing above the adapter ever touches HTTP or rdflib parse/save directly.
- `memory:` uses rdflib's `Dataset` (which supports named graphs), so the two
  backends share one interface and tests stay fast and dependency-free.
- `fuseki:` is Apache Jena Fuseki running locally (Docker or binary): persistent
  TDB2 storage, full SPARQL 1.1 query/update over HTTP, multiple named graphs.
  TTL remains the *interchange* format (`load_ttl`/`export_ttl`), just not the
  primary storage.

### Named graph layout

Today the schema/instance/support split is recomputed at read time by
`graph_partition`. With a store, partitioning becomes a **write-time decision**:
triples are inserted into the right named graph at merge/seed time.

| Named graph | Content |
|---|---|
| `urn:app:schema` | classes, properties, axioms (the declared skeleton) |
| `urn:app:shapes` | SHACL shapes, loaded from external shape files |
| `urn:app:instance` | extracted entities, relations, facts |
| `urn:app:support` | provenance / audit records (extraction events, decisions) |
| `urn:app:source/<sha256>` | optional per-source sub-graph, enables selective un-merge |

The named-graph IRIs are a *storage* detail, not a vocabulary — they name where
triples live, not what they mean, so they don't violate the "nothing custom"
rule. The read-side views in `report` remain as compatibility queries for the
`memory:` backend and for human inspection.

---

## 6. Long text: windowing

A new, tiny `window` module handles inputs too long for one prompt.

- Split on paragraph boundaries, capped at a maximum size (characters or
  tokens), with ~10% overlap so an entity mentioned across a boundary isn't lost.
- Short texts pass through as a single window — the common case stays unchanged.
- Windows are processed **in order**, and because context is rebuilt per window,
  entities created by window N are visible to window N+1. This is the existing
  per-file behavior, generalized.
- Provenance records `(source sha256, window index)` so every triple can be
  traced to an exact window — which also enables selective un-merge later.

Nothing downstream changes: a window *is* a source text.

---

## 7. Skeleton parametrization

Today the seed is eight hard-coded triples in `open_graph`. Requirement:
parametrize how the skeleton enters the graph, because longer inputs need richer
starting structure.

Proposal:

- **A seed graph is just an input graph — nothing special.** The orchestrator
  accepts repeatable `--seed some.ttl` and `--shapes some_shapes.ttl` flags and
  loads them into `urn:app:schema` / `urn:app:shapes` before extraction runs.
- With no seed given, fall back to a minimal `seeds/default.ttl` shipped with
  the project (data, not code).
- How much skeleton the LLM sees per prompt becomes a **parameter of `context`**:
  `skeleton_mode = none | relevant | full`, defaulting to today's behavior
  (`relevant`, relevance-selected and token-budgeted).

---

## 8. Seed graph builder — a separate tool later

Because seeds are plain ttl inputs, the future seed-builder is fully decoupled:
any tool that emits valid ttl (a UI, an editor, another script) is a seed
builder. Later this becomes its own `build_seed.py` CLI that loads
classes/properties/shapes (from spreadsheets, wikis, or existing ontologies) and
writes a seed `.ttl` — consumed by the pipeline exactly like any user-supplied
seed. No pipeline change is required when it appears.

---

## 9. Vocabulary policy: vanilla standards, nothing custom

The hard rule. The domain data gets its own IRIs (that's unavoidable — extracted
entities are new); the *plumbing* must reuse standards.

**Keep as-is (already standard):**
- Entities typed `rdf:type` + `owl:NamedIndividual` + `skos:Concept` + `class:<Kind>`.
- Naming via `skos:prefLabel` / `skos:altLabel` / `rdfs:label`.
- Descriptions via `rdfs:comment`.
- Kinds as `owl:Class` subclasses of `onto:Entity`.

**Change to standard vocabularies:**
- Provenance/audit: today it uses custom `onto:ExtractionEvent` / `onto:MergeCandidate`.
  Move to **PROV** (`prov:Activity` for an extraction, `prov:wasDerivedFrom`,
  `prov:generated`) and **DCTERMS** (`dcterms:source`, `dcterms:description`).
- The `onto:kind` literal is redundant — the kind is already expressed by
  `rdf:type` to a `class:<Kind>`. Drop it.
- Where the LLM names a common kind, prefer a common vocabulary: `Person` →
  `foaf:Person`, `Organization` → `foaf:Organization`, name → `foaf:name`.
  This is a natural later alignment, not a first step.

**Reserve the app's own namespace (`onto:` / `entity:` / `class:` / `relation:` /
`fact:`) only for the discovered domain IRIs** — the things being described, not
the machinery describing them.

`vocab.py` is the enforcement point: all URIs are defined there, so a review of
one file tells you whether the project is still "vanilla".

---

## 10. Orchestrator flow

One script, linear and boring, so anyone can read the whole app top to bottom:

```python
def run(source_path, store, options):
    documents = ingest.find(source_path)

    seed.load_default_or_user_seed(store, options.seed, options.shapes)

    for document in documents:
        if store.source_already_processed(document.sha256) and not options.force:
            continue

        for window in window.split(document, options.window_size):
            context   = context.build(store, window, options.skeleton_mode)
            raw       = extract.extract(window.text, context.text)
            repaired  = validate.validate(raw, store, context.existing_ids)  # includes repair loop
            plan      = plan.plan(store, repaired.candidates, provenance(document, window))
            merge.apply(store, plan)
            check.report_if_requested(store)

    report.summarize(store, options)
```

Every step is a function call with graph-or-text in, data out. The orchestrator
owns ordering, retries, and reporting. A window that fails leaves everything
already committed intact (per-window commits through the store).

---

## 11. Backlog → where each item lands

The `ox_recommendations.md` items map cleanly onto the new structure:

| # | Backlog item | Lands in |
|---|---|---|
| 1 | Repair loop instead of all-or-nothing validation | `validate` (bounded retries before hard reject) |
| 2 | Provenance on merged triples | `merge` + `urn:app:support` via `prov:` |
| 3 | Re-run idempotency | `ingest` (sha256) + `store.source_already_processed` |
| 4 | Cache derived views | `context` (cache the skeleton on a schema fingerprint) |
| 5 | Stronger entity resolution | `plan` (embedding tier slots in beside string matching) |
| 6 | Chunk long sources | `window` (this proposal's module 2) |
| 7 | Typed facts (XSD dates/numbers) | `validate` (normalize) + `merge` (declare `rdfs:range`) |
| 8 | Enforce SHACL | `check` (pyshacl or Fuseki's built-in SHACL) |
| 9a | Real tokenizer | `context` (the estimator is already injectable) |
| 9b | `--dry-run` | `pipeline` (run through `plan`, skip `merge`) |
| 9c | Parallel extraction | `pipeline` (concurrent `extract`, sequential `merge`) |

---

## 12. Migration plan — small steps, each keeping tests green

No big-bang rewrite. Each step leaves the CLI usable and the existing tests
passing (the data-snapshot tests that are already stale aside).

1. **Add `store.py`** with the `memory:` backend only; route all open/save calls
   through it. No behavior change. *(small)*
2. **Split `ingest`, add `window`**; the loop body runs per window. Provenance
   gains a window index. *(small)*
3. **Named-graph layout**: write-time partitioning (insert into schema / shapes /
   instance / support), while still persisting to one ttl file. The read-side
   partitioners remain as compatibility views. *(medium)*
4. **Add the `fuseki:` backend**; real runs opt in with `--store fuseki:...`.
   `memory:` stays the default for tests and small graphs. *(medium)*
5. **Seed/skeleton parametrization**: `--seed` / `--shapes` flags, a shipped
   `default.ttl`, and the `skeleton_mode` parameter. *(small)*
6. **Vocabulary cleanup**: move audit records from `onto:` to `prov:`/`dcterms:`
   and drop the redundant `onto:kind` literal. *(small, one-time migration)*
7. **Backlog items** land naturally afterwards in the slots above (§11).

---

## 13. What deliberately stays out of scope

- No custom vocabulary or meta-model — vanilla RDFS/OWL/SKOS/SHACL plus
  foaf/prov/dcterms only.
- No plugin registry, no abstract base classes, no dependency-injection
  framework. Modules are plain functions; the "API" is their signatures and the
  graph.
- No inference engine beyond what Jena/OWL offer for free. Extraction quality
  comes from prompting plus SHACL checks, not reasoning tricks.
- No database beyond Jena; no message queues, no microservices. One process,
  one store, one orchestrator.
