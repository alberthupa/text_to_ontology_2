# Architecture Proposal — text_to_ontology

A proposal for turning the current collection of loose-but-working modules into a
modular, API-like pipeline. Written before any code changes; this is the target,
not the present state.

---

## 1. Core idea

**The RDF graph is the only currency between modules.**

Every module is a function with roughly the same shape:

```
output_graph_or_data = module(input_graph, text_or_params)
```

Rules for every module:

1. Takes a graph (or a view/partition of one) plus plain parameters.
2. Text-carrying modules additionally take a piece of text.
3. Does **one** thing.
4. Either returns derived data (read-only) or produces new triples (write).
5. Never talks to another module directly except through the orchestrator.
6. Speaks only standard semantics: RDF, RDFS, OWL, SKOS, SHACL, SPARQL,
   common vocabularies (foaf, prov, dcterms...). Nothing custom that could be
   expressed with an existing standard.

This is already ~80% true of the codebase today (`task_context`, `merge_policy`,
`graph_partition` are all read-only functions over a graph). The proposal mostly
formalizes it and changes the storage underneath.

---

## 2. Layered picture

```
┌─────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR  (run_pipeline.py — the only place that       │
│  knows the order of steps; replaces today's ontology.py     │
│  run loop with explicit, visible stages)                    │
└──────────┬──────────────────────────────────────────────────┘
           │ calls modules in sequence
┌──────────▼──────────────────────────────────────────────────┐
│  MODULES (each independent, testable, replaceable)          │
│                                                             │
│  ingest        text files / dir ──► SourceDocument list    │
│  windower      long text ──► ordered overlapping windows    │
│  context       graph + window ──► prompt context            │
│  extract       window + context ──► candidate JSON          │
│  validate      candidates ──► normalized candidates         │
│  plan          graph + candidates ──► merge plan            │
│  merge         plan ──► SPARQL INSERT into the store        │
│  check         graph ──► SHACL conformance report           │
│  report        graph/views ──► terminal / markdown / html   │
└──────────┬──────────────────────────────────────────────────┘
           │ one shared interface
┌──────────▼──────────────────────────────────────────────────┐
│  GRAPH STORE ADAPTER  (graph_store.py — the single place    │
│  that knows WHERE triples live)                             │
│                                                             │
│   open()  query(SPARQL)  insert(SPARQL/ttl)                 │
│   load_ttl(file, named_graph)   export_ttl(named_graph)     │
│   named graphs: schema / instance / support / per-source    │
└──────────┬──────────────────────────────────────────────────┘
           │ implemented by
┌──────────▼──────────────────────────────────────────────────┐
│  backends:                                                  │
│   • rdflib memory + .ttl file   (today, good for tests)     │
│   • Apache Jena Fuseki (SPARQL HTTP server)  ← the goal     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Graph store: replace "one ttl file" with Jena

### Why

- The main graph will keep growing; loading the whole `.ttl` into rdflib for
  every run does not scale.
- Future inputs include *many* graphs and SHACL shape files — these need to
  coexist, not be concatenated into one blob.
- SPARQL becomes the natural read/write language between modules, which fits
  the "common currency" idea better than Python objects.

### What

Use **Apache Jena Fuseki** running locally (docker or binary). It gives:

- persistent TDB2 storage,
- full SPARQL 1.1 query/update over HTTP,
- multiple named graphs in one dataset,
- trivially exportable back to `.ttl` anytime (`export_ttl`) — ttl remains the
  interchange format, just not the primary storage anymore.

### The adapter (the only new abstraction)

One small module, `graph_store.py`, with a deliberately boring interface:

```python
store = open_store("fuseki:http://localhost:3030/mydata")   # or "memory:ontology.ttl"
store.load_ttl(path, graph_name="urn:app:schema")           # put a shapes file in
store.query("SELECT ... WHERE ...")                         # SPARQL SELECT
store.update("INSERT DATA { ... }")                          # SPARQL UPDATE
store.export_ttl(graph_name="urn:app:instance", path=...)   # get ttl out
```

- Everything above the adapter never touches HTTP or rdflib parse/save directly.
- The rdflib-memory backend keeps working so tests stay fast and dependency-free;
  Fuseki is used for real runs once the graph outgrows memory.
- Today's partition logic (`schema / instance / support`) maps cleanly onto
  **named graphs**: instead of re-partitioning on every run, triples are inserted
  into the right named graph at merge time. Partitioning becomes a write-time
  decision rather than a repeated read-time computation.

### Named graph layout

| Named graph | Content |
|---|---|
| `urn:app:schema` | classes, properties, axioms (the declared skeleton lives here) |
| `urn:app:shapes` | SHACL shapes, loaded from external shape files |
| `urn:app:instance` | extracted entities, relations, facts |
| `urn:app:support` | provenance / audit records (extraction events, decisions) |
| `urn:app:source/<sha256>` | optional per-source sub-graph, enables selective un-merge |

No custom vocabulary needed: provenance uses `prov:` / `dcterms:` terms inside
`support`.

---

## 4. The modules

Each is a folder-module with a clear contract. Most exist already under other
names — the mapping is listed.

| # | Module (proposed name) | Input → Output | Maps to today |
|---|---|---|---|
| 1 | `ingest_sources` | file/dir → list of `SourceDocument{path, text, sha256}` | same |
| 2 | `text_windower` | `SourceDocument` + max size → ordered, overlapping windows (paragraph boundaries, ~10% overlap); short texts pass through as one window | **new** |
| 3 | `context_builder` | store + window → budgeted prompt context | `task_context` + `context_render` + `prompt_budget` |
| 4 | `extractor` | window + context → candidate JSON | `source_parse` + `llm` |
| 5 | `candidate_validation` | candidates → normalized candidates or failure report | same (+ repair loop from backlog #1) |
| 6 | `merge_policy` | store + candidates + provenance → MergePlan (read-only) | same |
| 7 | `graph_merge` | MergePlan → SPARQL INSERTs via store | same, writes go through adapter |
| 8 | `shape_check` | store → SHACL validation report (pyshacl or Fuseki's built-in SHACL) | **new** (backlog #8) |
| 9 | `views` / `report` | store → schema/instance/support views, patterns, human reports | `graph_partition`, `graph_skeleton`, `graph_patterns`, `view_*` |

Notes:

- **Windowing (module 2)** solves the "super long input" requirement without
  changing anything downstream: a window *is* a source text. Provenance records
  `(source sha256, window index)` so every merged triple traces back to its
  exact window. Windows are processed in order, and because context is rebuilt
  per window, entities created by window N are visible to window N+1 — the
  existing per-file behavior, generalized.
- **Repair loop**: on validation failure, feed issues + original JSON back to
  the LLM (bounded retries) before rejecting — backlog item #1 slots in here.
- Modules stay importable and individually runnable (`python -m` style CLIs),
  which keeps them honest about their contracts.

---

## 5. Skeleton parametrization

Today the seed/skeleton is hard-coded (8 triples in `open_graph`). Requirement:
parametrize how the skeleton enters the graph, since longer inputs need richer
starting structure.

Proposal:

- A **seed graph is just an input graph** — nothing special. The orchestrator
  accepts `--seed some.ttl --shapes some_shapes.ttl` (repeatable) and loads them
  into `urn:app:schema` / `urn:app:shapes` before any extraction runs.
- If no seed is given, fall back to today's minimal built-in seed (kept as a
  tiny `.ttl` file shipped with the project, not code).
- How much skeleton the LLM sees per prompt becomes a **parameter of
  `context_builder`** (e.g. `skeleton_mode = none | relevant | full`), defaulting
  to what happens today (relevance-selected, token-budgeted).

## 6. Seed graph builder — separate tool later

Because seeds are plain ttl inputs, the future seed-builder tool is fully
decoupled: any tool that emits valid ttl (a UI, an editor, another script) works
as the seed builder. Later it becomes `build_seed.py`: its own CLI that loads
classes/properties/shapes (possibly from spreadsheets, wikis, or existing
ontologies) and writes a seed `.ttl` — consumed exactly like any user-supplied
seed. No change needed in the pipeline itself.

---

## 7. Orchestration flow

One script, linear and boring, so anyone can read the whole app top-to-bottom:

```python
def run(source_path, store, options):
    documents = ingest_sources.find(source_path)

    for document in documents:
        if store.source_already_processed(document.sha256):   # backlog #3
            continue
        for window in text_windower.split(document, options.window_size):
            context   = context_builder.build(store, window, options)
            raw       = extractor.extract(window.text, context)
            repaired  = candidate_validation.validate(raw)     # includes repair loop
            plan      = merge_policy.plan(store, repaired.candidates, provenance(document, window))
            counts    = graph_merge.apply(store, plan)          # SPARQL INSERT
            shape_check.report_if_requested(store)
    report.summarize(store, options)
```

Every step is a pure function call with graph-or-text in, data-out; the
orchestrator owns ordering, retries, and reporting. Failure of one window leaves
everything already committed intact (per-window commits via the store).

---

## 8. What moves where (migration plan, small steps)

1. **Introduce `graph_store.py`** with the memory/rdflib backend only; route all
   opens/saves through it. No behavior change. *(small)*
2. **Split `ingest` and add `text_windower`**; loop body runs per window.
   Provenance gains window index. *(small)*
3. **Named-graph layout**: write-time partitioning (insert into schema /
   instance / support named graphs) while still persisting to one ttl file.
   Read-side partitioners remain as compatibility views. *(medium)*
4. **Add Fuseki backend** to the adapter; switch real runs to
   `--store fuseki:...`. Memory backend stays for tests. *(medium)*
5. **Skeleton/seed parametrization**: `--seed/--shapes` flags, seed ttl file,
   `skeleton_mode` parameter. *(small)*
6. **Backlog items** land naturally afterwards: repair loop (#1), provenance via
   `prov:` in support graph (#2 — largely exists), idempotent skip by sha256 (#3),
   SHACL enforcement (#8), typed facts (#7).

Each step keeps tests green and the CLI usable; nothing is a big-bang rewrite.

---

## 9. What deliberately stays out of scope

- No custom vocabulary or meta-model — vanilla RDFS/OWL/SKOS/SHACL + foaf/prov/dcterms only.
- No framework, plugin registry, or abstract base classes — modules are plain
  functions; the "API" is their signatures and the graph.
- No inference engine beyond what Jena/OWL offers for free; extraction quality
  comes from prompting + SHACL checks, not reasoning tricks.
- No database beyond Jena; no message queues, no services. One process, one store.
