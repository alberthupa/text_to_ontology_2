# Current Architecture — text_to_ontology

> Machine-readable architecture map. Reconstructed **from source code only** (no docs consulted).
> Target audience: another AI/LLM agent that must navigate, modify, or extend this codebase.
> All facts below are taken directly from the files; function signatures are quoted verbatim.

---

## 1. Purpose

Reads text files (or a directory of text-like files), asks an LLM to extract
**entities**, **relations**, and literal **facts**, and merges them into a single
RDF/OWL/SHACL/SKOS Turtle graph (`ontology.ttl` by default). Re-running against the
same graph adds knowledge; entity resolution prevents duplicates.

The codebase has three layers:

1. **Write pipeline** — actually executed by `ontology.py`; builds the graph.
2. **Read-only derivation layer** — three modules that generalize an existing graph
   (`graph_partition`, `graph_skeleton`, `graph_patterns`). Since proposal 05 phase
   5D these are reached by the pipeline, through the façade in §5.4.
3. **Context selection layer** (proposal 05) — five modules that pick, render, and
   budget the part of the current graph one source text needs, and put that in the
   extraction prompt. Nothing in this layer writes to the graph.

The prompt no longer carries the whole entity catalog or every property label. It
carries a per-source selection, capped by a token ceiling (§10).

---

## 2. Repository layout

```
text_to_ontology_2/
├── ontology.py              # entry point: CLI + run loop
├── ingest_sources.py        # source discovery + reading
├── source_parse.py          # prompt builder
├── candidate_validation.py  # [read-only] validate + normalize candidates before merge
├── merge_policy.py          # [read-only] identity/acceptance/conflict planning + provenance
├── llm.py                   # OpenRouter HTTP client (stdlib only)
├── entity_lookup.py         # entity resolution (local fallback)
├── graph_merge.py           # write parsed results into graph
├── graph_management.py      # open / seed / bind / save graph; owns namespaces
├── graph_partition.py       # [read-only] split graph into schema/instance/support
├── graph_skeleton.py        # [read-only] compact declared structural core
├── graph_patterns.py        # [read-only] empirical usage patterns
├── ontology_views.py        # [read-only] façade: the five derived views as one record
├── source_concepts.py       # [read-only] what one text mentions (no RDF, no LLM)
├── task_context.py          # [read-only] select the context one source needs
├── context_render.py        # [read-only] render + assemble + budget that context
├── prompt_budget.py         # [read-only] token estimate, allowance, packing
├── ontology.ttl             # output graph (data, not code)
├── requirements.txt         # rdflib>=7,<8
├── .env                     # OPENROUTER_API_KEY, OPENROUTER_MODEL
├── README.md / next_steps.md# notes (not architecture source)
├── sources/                 # 5 geopolitical briefs (.md) — sample input
└── tests/                   # one unittest file per module + pipeline
    ├── test_pipeline.py
    ├── test_ingest_sources.py
    ├── test_source_parse.py
    ├── test_candidate_validation.py
    ├── test_merge_policy.py
    ├── test_entity_lookup.py
    ├── test_graph_merge.py
    ├── test_graph_management.py
    ├── test_graph_partition.py
    ├── test_graph_skeleton.py
    ├── test_graph_patterns.py
    ├── test_ontology_views.py
    ├── test_source_concepts.py
    ├── test_task_context.py
    ├── test_context_render.py
    └── test_prompt_budget.py
```

Dependency: only `rdflib` (`requirements.txt`: `rdflib>=7,<8`).

---

## 3. Entry point — `ontology.py`

### 3.1 Imports

- stdlib: `argparse`, `sys`, `time`, `pathlib.Path`
- project:
  - `candidate_validation.format_validation_failure, validate_candidates`
  - `context_render.prepare_prompt_context`
  - `graph_management.open_graph, save_graph`
  - `graph_merge.merge_into_graph`
  - `ingest_sources.find_text_files, read_source`
  - `llm.model_name`
  - `prompt_budget.PROMPT_BUDGET, estimate_tokens`
  - `source_parse.parse_source`
  - `task_context.build_task_context`

Two module-level helpers keep `main()` short:

- `budget_for(text)` → `dict(PROMPT_BUDGET, source_tokens=estimate_tokens(text))`
- `report_context(budget)` → prints items kept, `used/budget` tokens, items dropped
- `report_validation(validation)` → prints normalized entity/relation/fact counts and the
  number of duplicates removed

### 3.2 `main()` — control flow

```
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=Path("ontology.ttl"))
    args = parser.parse_args()

    graph  = open_graph(args.graph)
    files  = find_text_files(args.source, args.graph)
    if not files:
        raise RuntimeError("No text-like files found")

    args.graph.parent.mkdir(parents=True, exist_ok=True)
    for path in files:
        print(f"Reading {path}", flush=True)
        text = read_source(path)
        if not text.strip():
            continue                          # blank files skipped BEFORE any work
        # Read only, and rebuilt for every file.
        context = build_task_context(text, graph)
        prompt_context = prepare_prompt_context(context, budget_for(text))
        report_context(prompt_context["budget"])
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, prompt_context["text"])   # LLM call
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        validation = validate_candidates(extraction, graph,
                                         prompt_context["existing_ids"])  # read only
        report_validation(validation)
        if not validation["valid"]:
            raise RuntimeError(format_validation_failure(validation))
        provenance = build_provenance(path, text, model)
        plan = plan_graph_merge(graph, validation["candidates"],
                                provenance)      # read only
        report_plan(plan)
        updated, counts = apply_merge_plan(graph, plan)   # graph copy
        save_graph(updated, args.graph)          # atomic, AFTER EACH FILE
        graph = updated                          # only after a successful save
        print(f"  {counts['new_entities']} new, "
              f"{counts['resolved_entities']} resolved, "
              f"{counts['relation_triples']} relations, "
              f"{counts['fact_triples']} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")
```

### 3.3 Entry guard / error handling

```
if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
```

- Catches only `RuntimeError` and `OSError`; prints to stderr; exit code 1.
- Other exception types propagate (uncaught).

### 3.4 Key behaviors (pipeline-level)

- **Per-file save**: the graph is written to disk after *each* file, so file N+1 sees file N's result both in memory (the `graph` object) and on disk.
- **Sequential context**: each file's prompt receives context *selected from* everything
  merged so far — not the whole catalog. A resource merged from file N reaches file N+1's
  prompt only if file N+1 gives a reason to select it.
- **Views are never cached across a merge**: `build_task_context()` re-derives the partition,
  skeleton, and patterns per file, because the graph changed.
- **Blank file skip**: whitespace-only sources never reach the LLM, and no context is built
  for them.
- **Context construction is read only**: no selection, score, or diagnostic is written into
  the graph, and a failed LLM call leaves the saved graph byte-identical.
- **Validation gate (phase 06)**: each non-empty source's answer is validated and normalized
  *before* any merge planning. Any validation error rejects the whole candidate package
  for that source — planning, materialization, provenance, and `save_graph()` never run, the
  in-memory graph and the on-disk file are unchanged, and the CLI exits on the `RuntimeError`.
  Only `existing_id` values actually rendered as `id:` in the final budgeted prompt (and still
  present in the native catalog) may be trusted as LLM-directed identities. Every entity,
  relation, and fact record must carry a numeric `confidence` in `[0, 1]`.
- **Merge policy gate (phase 07)**: after validation, `plan_graph_merge()` decides every
  identity (`existing`/`new`/`review` with reason codes), every assertion outcome
  (`accept`/`duplicate`/`review`), and builds deterministic audit triples — all read only.
  Close spellings never auto-merge; new assertions below `AUTO_ACCEPT_MIN_CONFIDENCE` (0.80)
  go to review; exact existing triples corroborate without re-adding; explicit functional /
  inverse-functional conflicts go to review; existing labels, descriptions, and canonical
  triples are never overwritten. `apply_merge_plan()` then materializes the completed plan
  into a **graph copy**, and `save_graph()` replaces the file atomically (temp sibling +
  `os.replace`). The returned graph becomes the next file's active graph only after a
  successful save.

---

## 4. Module reference (write pipeline)

### 4.1 `graph_management.py` — graph lifecycle + namespaces

Imports (rdflib): `BNode, Graph, Literal, Namespace`; `OWL, RDF, RDFS, SH, SKOS`.

**Constants** (URI namespaces):

| Name | Value |
|---|---|
| `BASE` | `http://example.org/text-ontology/` |
| `ONTO` | `Namespace(BASE)` |
| `ENTITY` | `Namespace(BASE + "entity/")` |
| `CLASS` | `Namespace(BASE + "class/")` |
| `RELATION` | `Namespace(BASE + "relation/")` |
| `FACT` | `Namespace(BASE + "fact/")` |

**Functions**:

- `bind(graph)` — binds prefixes `onto, entity, class, relation, fact, owl, rdf, rdfs, sh, skos`.
- `open_graph(path)`:
  - Creates `Graph()`, calls `bind`.
  - If `path.exists()`: `graph.parse(path, format="turtle")` and return (existing graph is **never reseeded**).
  - Else seed 8 triples and return:
    1. `(ONTO.ontology, RDF.type, OWL.Ontology)`
    2. `(ONTO.Entity, RDF.type, OWL.Class)`
    3. `(ONTO.Entity, RDFS.label, Literal("Entity"))`
    4. `rule = BNode()`
    5. `(ONTO.EntityShape, RDF.type, SH.NodeShape)`
    6. `(ONTO.EntityShape, SH.targetClass, ONTO.Entity)`
    7. `(ONTO.EntityShape, SH.property, rule)`
    8. `(rule, SH.path, SKOS.prefLabel)`
    9. `(rule, SH.minCount, Literal(1))`
  - Opening a missing path does **not** write to disk (only `save_graph` writes).
- `save_graph(graph, path)` — serializes to a temporary sibling file
  (`<path>.tmp`) and atomically replaces the target with `os.replace` only after
  serialization succeeds. A failed save leaves the previous file byte-identical
  and never leaves a stale temporary file.

---

### 4.2 `ingest_sources.py` — source discovery + reading

No project imports.

**Constant**:

```
TEXT_FILES = {".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".yaml", ".yml",
              ".xml", ".html", ".log"}
```

**Functions**:

- `find_text_files(source, graph_path)`:
  - If `source.is_file()`: return `[source]` (a directly-named file is accepted **regardless of extension**).
  - If not `source.is_dir()`: `raise RuntimeError(f"Source does not exist: {source}")`.
  - Else: resolve `graph_path`; return `sorted(...)` of recursive `source.rglob("*")` results where `path.is_file()`, `path.resolve() != graph_path` (excludes the output graph), and `path.suffix.lower() in TEXT_FILES`.
- `read_source(path)` — `path.read_text(encoding="utf-8", errors="replace")` (invalid bytes become `U+FFFD`).

---

### 4.3 `llm.py` — OpenRouter client (stdlib only)

Imports (stdlib): `json, os, urllib.error, urllib.request, pathlib.Path`.

**Constant**:

```
DEFAULT_MODEL = "openrouter/pareto-code:nitro"
```

**Functions**:

- `load_env(path=None)`:
  - Default path: `Path(__file__).with_name(".env")`.
  - Parses `KEY=value` lines. Skips blank lines, `#` comments, lines without `=`.
  - Strips leading `export `. Strips matching single/double quotes around values.
  - `os.environ.setdefault(name, value)` — **never overrides** existing env vars.
- `model_name()` — `load_env()` then `os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)`.
- `ask_llm(prompt)`:
  - `load_env()`; reads `OPENROUTER_API_KEY`; if missing → `raise RuntimeError("Set OPENROUTER_API_KEY first")`.
  - POSTs JSON to `https://openrouter.ai/api/v1/chat/completions`:
    ```
    {"model": model_name(), "temperature": 0,
     "messages": [
       {"role": "system", "content": "Extract knowledge. Return only JSON."},
       {"role": "user",   "content": prompt}]}
    ```
  - Headers: `Authorization: Bearer <key>`, `Content-Type: application/json`,
    `X-OpenRouter-Title: "Simple Text to Ontology"`.
  - `urlopen(request, timeout=60)`.
  - Reads `answer = json.load(response)["choices"][0]["message"]["content"]`.
  - On `urllib.error.HTTPError`: `raise RuntimeError(f"OpenRouter error {code}: {message}")`.
  - On success: locates `{` (first) to `}` (last) in `answer` (accepts Markdown-fenced JSON);
    if no `{`/`}` → `raise RuntimeError(f"The model did not return JSON:\n{answer}")`;
    `json.loads(answer[start:end+1])`; on `JSONDecodeError` →
    `raise RuntimeError(f"The model returned invalid JSON:\n{answer}")`.
  - Returns the parsed JSON object.

---

### 4.4 `source_parse.py` — prompt builder

Imports: `llm.ask_llm`. Nothing else — no `json`, no rdflib, no `entity_lookup`.
Since phase 5D this module receives context instead of discovering it.

**Functions**:

- `context_block(context_text)` — the selected context, headed
  `ONTOLOGY CONTEXT - selected for this source, not the whole ontology:` and followed by
  `CONTEXT_RULES`. Returns `""` for empty or whitespace-only context, so the heading and
  rules never appear without content.
- `make_prompt(text, context_text="")` — one f-string: the instruction line, the context
  block (if any), the unchanged `existing_id` resolution paragraph, the required JSON
  shape, the endpoint constraint, and `SOURCE` between `---` delimiters.
- `parse_source(text, context_text="")` — `return ask_llm(make_prompt(text, context_text))`.
  Takes no graph and cannot mutate one.

**`CONTEXT_RULES`** (module constant, stated to the model): only an exact `id:` value may
be reused as `existing_id`; a `uri:` value is context, not an identifier; observed usage is
evidence about current data, not a rule; the context is a selection, so real things missing
from it are still worth extracting.

**Required JSON contract** (verbatim shape in the prompt):

```json
{
  "entities": [
    {"id": "e1", "name": "preferred name", "kind": "Person",
     "description": "short source-grounded description",
     "aliases": ["other source name"], "existing_id": null}
  ],
  "relations": [
    {"subject": "e1", "predicate": "works for", "object": "e2"}
  ],
  "facts": [
    {"subject": "e1", "predicate": "birth date", "value": "1950-01-01"}
  ]
}
```

Constraints stated to the model: relation endpoints and fact subjects must reference
entity ids; `existing_id` must be an existing entity's exact id or `null`; every record
carries a required `confidence` (0.0–1.0) defined as *the model's confidence that the source
text directly supports this complete record* — not identity confidence, not world truth,
not source authority; return JSON only.

---

### 4.5 `entity_lookup.py` — entity resolution

Imports: `re, unicodedata`; `difflib.SequenceMatcher`; rdflib `URIRef`, `RDF, RDFS, SKOS`;
`graph_management.ONTO`.

**Functions**:

- `identity_key(text)`:
  ```
  text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
  return re.sub(r"[^a-z0-9]", "", text.lower())
  ```
  Normalizes case/accents/punctuation. Gotcha: letters with no NFKD decomposition are dropped, not folded.
- `entity_catalog(graph)` → `list[dict]`, one per `graph.subjects(RDF.type, ONTO.Entity)`:
  ```
  {"id": str(uri),
   "names": sorted({prefLabel, altLabel values}),
   "kind": str(graph.value(uri, ONTO.kind) or ""),
   "description": str(graph.value(uri, RDFS.comment) or "")}
  ```
  Sorted by URI string. Only explicit `onto:Entity` subjects are listed.
- `identify_entity(entity, catalog)` → `URIRef | None`. Resolution order:
  1. **`existing_id`** — if `entity["existing_id"]` is a key in `{item["id"]}` → return that `URIRef`.
  2. **Exact name+kind** — `new_names = [name, *aliases]`; `new_kind = identity_key(kind)`.
     Match catalog items where `new_kind` is non-empty, `new_kind == identity_key(item["kind"])`,
     and normalized name sets intersect. If exactly **one** match → return it.
  3. **Close spelling** — same kind only; `max(SequenceMatcher(...).ratio())` over catalog names
     vs `identity_key(entity["name"])` (preferred name only, aliases NOT used). Keep scores ≥ 0.96;
     sort descending; return the top if unique (`len(close)==1` or strict winner). Else `None`.
  - Missing/different kind never resolves (steps 2 and 3 both require kind equality).

**Phase 07 addition** — `identity_decision(entity, catalog, planned_catalog=(), *,
min_new_confidence=0.80, allocate_uri=None, provisional_uri=None)` returns one reasoned
record `{local_id, status, uri, method, score, suggestions, reason_codes}`:
`status` ∈ `existing | new | review`; `method` ∈ `explicit_id, exact_name, exact_alias,
planned_exact, new, ambiguous_exact, kind_collision, close_spelling`. Resolution order:
explicit id → unique same-kind exact match → ambiguous exact review → cross-kind label
review → close-spelling review-only suggestion (≥ 0.96, never auto-resolves) → new
(if confidence ≥ threshold) or below-threshold review with a deterministic provisional URI.
Read only; deterministic across graph insertion order. `identify_entity()` remains as a
legacy wrapper for direct callers; the active pipeline uses the rich operation.

---

### 4.6 `graph_merge.py` — write results into the graph

Imports: `re, unicodedata`; rdflib `Literal`, `OWL, RDF, RDFS, SKOS`;
`entity_lookup.entity_catalog, identify_entity`;
`graph_management.CLASS, ENTITY, FACT, ONTO, RELATION`.

**Functions**:

- `slug(text)` — NFKD→ascii→lower, `re.sub(r"[^a-z0-9]+", "-", ...).strip("-") or "unnamed"`.
- `label(text)` — `re.sub(r"([a-z])([A-Z])", r"\1 \2")` then `re.sub(r"[_-]+", " ").strip()`.
  (camelCase/snake_case/kebab → readable.)
- `new_entity_uri(graph, name)` — `stem = slug(name)`, tries `ENTITY[stem]`, `ENTITY[stem-2]`, …;
  returns first URI where `(uri, None, None) not in graph`.
- `merge_into_graph(graph, data)` → `(new_count, resolved_count, relation_count, fact_count)`:
  - **Entities** (processed in order; `entity_catalog(graph)` is recomputed per entity, so a later
    entity in the *same* response can resolve to one added just above):
    - skip if `not entity.get("id") or not entity.get("name")`.
    - `uri = identify_entity(entity, entity_catalog(graph))`; `None` → `new_entity_uri` (`new_count += 1`), else `resolved_count += 1`.
    - `local_ids[str(entity["id"])] = uri`.
    - `kind = label(entity.get("kind") or "Entity")`; `kind_uri = CLASS[slug(kind)]`.
    - Add class declaration: `(kind_uri, RDF.type, OWL.Class)`, `(kind_uri, RDFS.subClassOf, ONTO.Entity)`, `(kind_uri, RDFS.label, Literal(kind))`.
    - Add entity typing: `(uri, RDF.type, ONTO.Entity)`, `(uri, RDF.type, OWL.NamedIndividual)`,
      `(uri, RDF.type, SKOS.Concept)`, `(uri, RDF.type, kind_uri)`, `(uri, ONTO.kind, Literal(kind))`.
    - Naming: if no `SKOS.prefLabel` → add `prefLabel` + `RDFS.label` = name;
      elif existing `prefLabel != name` → add `SKOS.altLabel` = name. Then add each alias as `SKOS.altLabel`.
    - If `description` present and no existing `RDFS.comment` → add `(uri, RDFS.comment, Literal(description))`
      (existing comment is **not** overwritten).
  - **Relations**: for each `{subject, predicate, object}`: map endpoints via `local_ids` (str keys);
    require subject, object, and non-empty predicate. `predicate = RELATION[slug(name)]`;
    add `(predicate, RDF.type, OWL.ObjectProperty)` + `(predicate, RDFS.label, Literal(label(name)))`;
    add the triple; count only if `(subject, predicate, object_) not in graph` beforehand.
  - **Facts**: for each `{subject, predicate, value}`: require subject, non-empty predicate, and
    `value is not None`. `predicate = FACT[slug(name)]`; `value = Literal(fact["value"])`;
    add `(predicate, RDF.type, OWL.DatatypeProperty)` + `(predicate, RDFS.label, Literal(label(name)))`;
    add triple; count only if new.
  - Returns the 4-tuple of counts.

Semantics: relations become `relation:*` `owl:ObjectProperty`s; facts become `fact:*`
`owl:DatatypeProperty`s; kinds become `class:*` `owl:Class`es subclassing `onto:Entity`.

**Phase 07 addition** — `apply_merge_plan(source_graph, plan)` materializes an
already-complete merge plan into a **copy**: it copies namespace bindings and all source
triples, asserts only the plan's decided domain and audit triples, and reports
`{new_entities, resolved_entities, relation_triples, fact_triples, metadata_triples,
duplicates, review, audit_triples}`. It contains no identity or conflict logic; the input
graph stays triple-identical, including on failure. `merge_into_graph()` remains unchanged
as a tested compatibility path for direct callers.

---

### 4.7 `candidate_validation.py` — validate + normalize before merge

A read-only gate between `parse_source` and `merge_into_graph`. It understands the supported
response structure, normalizes it deterministically and conservatively, and returns either a
normalized, deduplicated package or a deterministic failure — it never writes to a graph and
never calls `identify_entity()`.

Imports: `math, re, unicodedata`; rdflib `Literal, URIRef`, `OWL, RDF, RDFS, SKOS`;
`entity_lookup.entity_catalog, identity_key`; `graph_management.CLASS, FACT, ONTO, RELATION`;
`graph_merge.label, slug`.

**Public contract**:

- `validate_candidates(data, graph, allowed_existing_ids=())` → `ValidationResult`:
  ```
  {"valid": bool,
   "candidates": {"entities", "relations", "facts"} | None,
   "issues": [{"code", "severity", "path", "related_paths", "message"}],
   "counts": {"input", "normalized", "duplicates_removed",
              "normalized_fields", "errors", "warnings"}}
  ```
  `candidates` is `None` whenever `valid` is false, and keeps the same three-section public
  shape `merge_into_graph()` already accepts. A valid result may still carry warnings.
- `format_validation_failure(result)` → a concise deterministic `str` for the CLI (issue count,
  then one `path [code]: message` line per error). Never includes the raw model response.

**Supported raw shape** (the extraction prompt's JSON; unchanged):

- Top level must be a mapping with **exactly** `entities`, `relations`, `facts` (each a list).
  Missing/unknown/non-list sections or a non-mapping top level are errors.
- Entity fields: `id` (required, `^[A-Za-z][A-Za-z0-9_-]*$`), `name` (required), `kind`
  (optional; empty/missing → `Entity` with a warning), `description` (string|null), `aliases`
  (list of strings), `existing_id` (string|null, trimmed exact match only).
- Relation fields: `subject`, `predicate`, `object`. Fact fields: `subject`, `predicate`,
  `value` (`str | bool | int | finite float`). Unknown record fields are errors.

**Normalization rules** (conservative; never reinterprets):

- Unicode NFKC; CRLF/CR → LF; disallowed controls removed; surrounding whitespace trimmed;
  internal whitespace collapsed for one-line identifiers/names/kinds/aliases/predicates but
  preserved in descriptions and fact strings; dates/numbers in strings are never coerced; the
  JSON scalar type of a fact value is preserved and becomes part of its duplicate key (so
  `"1"`, `1`, and `true` stay distinct).

**Passes** (deterministic; a sort key `(section, index, field, code, message)` orders issues):

1. container; 2. entity normalization + local-ID index + repeated-id/existing-id detection;
3. relation/fact normalization (`empty`/`unnamed`/URI-looking predicates rejected);
4. reference check (relation endpoints and fact subjects must name a *valid* local entity);
5. exact duplicate removal (entities, relations, facts, aliases — warnings, not errors);
6. generated-URI compatibility: kind/property role collisions and `object`↔`datatype` type
   collisions at `class:[slug]` / `relation:[slug]` / `fact:[slug]`, plus two candidate
   predicate spellings that slug to one URI but to different `label()`s;
7. graph-exact duplicate removal, only where endpoints carry an explicit `existing_id`;
8. finalize (sort issues, compute counts, drop `candidates` on any error).

Provable-only checks: no identity search, no inferred domain/range/membership, and two
differing values are never declared contradictory without an explicit policy.

**Phase 07 changes** — every record now requires a numeric `confidence` in `[0, 1]`
(Booleans, NaN, ±infinity rejected; integers and floats normalize to one float
representation; codes `*.missing_confidence` / `*.invalid_confidence`). Intra-package
duplicates with differing confidence keep the lower value plus a `*.duplicate_confidence`
warning naming both positions. Graph-exact relation/fact candidates are **no longer
removed** here: they stay in normalized output so merge policy can plan their
corroboration and provenance (`relation.graph_duplicate` / `fact.graph_duplicate` are
gone). All structural, endpoint, existing-ID, role, and collision checks are unchanged,
and the package-level fail-closed gate is unchanged.

---

### 4.8 `merge_policy.py` — read-only merge planning (phase 07)

The policy layer between validation and materialization. It decides identity,
acceptance, corroboration, and conflict handling against the **complete** graph,
and builds deterministic provenance — all without mutating anything.

Imports: `hashlib, json, decimal.Decimal`; rdflib `Literal, URIRef`,
`OWL, RDF, RDFS, SKOS`; `entity_lookup.entity_catalog, identity_decision,
identity_key`; `graph_management.CLASS, ENTITY, FACT, ONTO, RELATION`;
`graph_merge.label, slug`.

**Constants**: `MERGE_POLICY_VERSION = 1`, `AUTO_ACCEPT_MIN_CONFIDENCE = 0.80`,
`RDF_JSON` (the `rdf:JSON` URI; rdflib 7 has no `RDF.json` term).

**Functions**:

- `canonical_json(value)` — UTF-8, sorted keys, compact separators, list order
  preserved. The serialization every digest depends on.
- `record_digest(record)` — SHA-256 hex of the canonical JSON.
- `proposed_entity_uri(entity)` — `onto:merge-proposed-entity/<sha256>`; the
  deterministic review-only identity of a below-threshold otherwise-new entity.
- `build_provenance(source_path, source_text, model)` → `{source_path (POSIX
  text, unresolved), source_sha256, model, policy_version}`.
- `resolve_entities(candidates, graph)` → `{local_id: decision}`. Ordered;
  earlier accepted new entities enter a virtual catalog (`planned_exact`);
  allocated URIs are reserved so two new entities cannot collide pre-mutation.
- `plan_graph_merge(graph, candidates, provenance)` → the **MergePlan**:
  `{policy_version, provenance, event_uri, package_sha256, identities,
  entities, relations, facts, domain_triples, audit_triples, counts,
  diagnostics}`. Assertion decisions carry section/index, outcome
  (`accept`/`duplicate`/`review`), confidence, sorted reason codes, the exact
  triple when grounded, and conflicting triples. `counts` covers identities
  (new/resolved/review), assertions (accepted/duplicate/review), entity
  summaries (accept/duplicate/review/partial_review), and triple totals.

**Decision precedence**: validation errors → identity ambiguity review →
exact-triple duplicate (any confidence) → explicit functional /
inverse-functional conflict review → below-threshold confidence review →
accept. Differing values on unmarked properties are ordinary multi-valued RDF
and coexist. Existing `skos:prefLabel`, `rdfs:comment`, and canonical triples
are never overwritten; alias ownership by another same-kind entity routes that
alias (only) to review.

**Audit vocabulary** (all under `onto:`, never blank nodes, always in the
support partition): `onto:ExtractionEvent` (typed by `rdf:type`; carries
`onto:sourcePath`, `onto:sourceSha256`, `onto:modelName`,
`onto:mergePolicyVersion`, `onto:candidatePackageSha256`) and
`onto:MergeCandidate` (linked by `onto:wasExtractedIn`; carries
`onto:candidateSection`, `onto:candidateIndex`, `onto:normalizedCandidate`
as `rdf:JSON`, `onto:extractionConfidence` as `xsd:decimal`,
`onto:mergeDecision`, `onto:decisionReason` per code, `onto:fieldDecisions`
for entities, `onto:resolvedEntity` when canonically resolved,
`onto:proposedEntity` for review-only provisional identities, and
`rdf:subject`/`rdf:predicate`/`rdf:object` reification for grounded
relations/facts). Event URIs: `onto:merge-event/<sha256>` over policy version,
source path, source digest, model, and package digest; candidate URIs:
`onto:merge-candidate/<event-sha>/<section>-<index>-<record-sha>`. Exact
reruns reuse audit resources; no timestamps, no raw source/prompt/response,
no schema declarations for the audit classes (so they never enter task
context).

**Reason codes**: `identity.ambiguous_exact`, `identity.kind_collision`,
`identity.close_spelling`, `identity.new_below_confidence`,
`dependency.unresolved_entity`, `confidence.below_auto_accept`,
`alias.claimed_by_other_entity`, `conflict.existing_description`,
`conflict.functional_value`, `conflict.inverse_functional_value`,
`assertion.exact_duplicate`.

## 5. Module reference (read-only derivation and context layers)

None of these modules writes to a graph. Since phase 5D the pipeline reaches all of them,
through `task_context.build_task_context()` and `context_render.prepare_prompt_context()`.
§5.1–5.3 derive general views of a graph; §5.4–5.8 select and shape the part of it one
source text needs.

### 5.1 `graph_partition.py` — split into 3 views

Imports (rdflib only): `BNode, Graph, Literal`; `OWL, RDF, RDFS, SH, SKOS`.

**Constants** (sets of rdflib terms):

| Name | Members |
|---|---|
| `SCHEMA_TYPES` | `OWL.Class, RDFS.Class, RDFS.Datatype, RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty` |
| `SUPPORT_TYPES` | `OWL.Ontology, SH.NodeShape, SH.PropertyShape` |
| `AUDIT_TYPES` | `onto:ExtractionEvent, onto:MergeCandidate` (phase 07; base namespace restated locally to keep the rdflib-only dependency) |
| `SCHEMA_AXIOMS` | `RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range, OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith, OWL.inverseOf` |
| `ANNOTATIONS` | `RDFS.label, RDFS.comment, SKOS.prefLabel, SKOS.altLabel, SKOS.definition` |
| `RESTRICTION_TARGETS` | `OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass, OWL.onDataRange` |

**Functions**:

- `owned_nodes(graph, root)` — `{root}` plus every blank node reachable from `root` via object position (BFS).
- `support_roles(graph)` — subjects typed with any `SUPPORT_TYPES` or `AUDIT_TYPES` type, plus their `owned_nodes`. Reified `rdf:subject`/`rdf:object` links do not pull domain endpoints into support: only the audit subject's own triples move.
- `restriction_roles(graph)` — blank nodes typed `OWL.Restriction` that also have `OWL.onProperty`, plus `owned_nodes`.
- `schema_roles(graph, restrictions)` — set of: subjects of `SCHEMA_TYPES`; subject+object of `SCHEMA_AXIOMS` triples;
  objects of `RESTRICTION_TARGETS` predicates on restriction nodes. Then filtered to exclude `BNode`/`Literal`.
- `instance_roles(graph, schema)` — subjects `s` with `(s, RDF.type, t)` where `t` is not in
  `SCHEMA_TYPES`/`SUPPORT_TYPES` and (`t in {OWL.NamedIndividual, SKOS.Concept}` or `t in schema`).
- `partition_graph(source_graph)` → `(schema_graph, instance_graph, support_graph)`:
  1. Compute `support_nodes`, `restrictions`, `schema_nodes`, `instance_nodes`.
  2. `opaque` = blank nodes not in `support_nodes` and not in `restrictions`.
  3. Create three empty `Graph()`s; copy every namespace binding from source into each.
  4. For every triple, call `choose_view(...)` and add to the named view
     (`"schema"` → schema, `"instance"` → instance, anything else → support).
  5. Return the 3-tuple.
- `choose_view(triple, support_nodes, restrictions, schema_nodes, instance_nodes, opaque)` → `"support"|"schema"|"instance"`.
  Priority (first match wins):
  1. subject or object in `support_nodes` → `"support"`.
  2. subject or object in `opaque` → `"support"`.
  3. `predicate == RDF.type`: object in `SCHEMA_TYPES` or `== OWL.Restriction` → `"schema"`;
     else `"instance"` if subject in `instance_nodes`, else `"support"`.
  4. subject in `restrictions` → `"schema"`.
  5. `predicate in SCHEMA_AXIOMS` → `"schema"` if subject in `schema_nodes`, else `"support"`.
  6. `predicate in ANNOTATIONS` → `"schema"` if subject in `schema_nodes`;
     `"instance"` if subject in `instance_nodes`; else `"support"`.
  7. default → `"instance"` if subject in `instance_nodes`, else `"support"`.

**Invariants (enforced by tests)**:
- Lossless + disjoint: `schema ∪ instance ∪ support == source`, pairwise intersections empty,
  `len(schema)+len(instance)+len(support) == len(source)`.
- Read-only: source graph and the on-disk `ontology.ttl` are unchanged.

---

### 5.2 `graph_skeleton.py` — compact declared structural core

Imports (rdflib only): `BNode, Graph, Literal, URIRef`; `OWL, RDF, RDFS, SKOS`.

**Constants**:

| Name | Members |
|---|---|
| `SKELETON_TYPES` | `OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty` |
| `NAMED_AXIOMS` | `RDFS.subClassOf, RDFS.domain, RDFS.range` |
| `ANNOTATIONS` | `RDFS.label, RDFS.comment, SKOS.prefLabel, SKOS.altLabel, SKOS.definition` |
| `SUPPORTED_CONSTRAINTS` | `OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.cardinality, OWL.minCardinality, OWL.maxCardinality` |

**Functions**:

- `supported_restriction(schema_graph, node)` → `(triples, {prop, value}) | None`:
  - Collect `parts[predicate] = [objects]` for all outgoing triples of `node`.
  - Reject unless exactly three distinct predicates each with exactly one value.
  - Reject unless `parts[RDF.type] == [OWL.Restriction]` and `OWL.onProperty in parts`.
  - `constraint = (parts keys − {RDF.type, OWL.onProperty}).pop()`; reject if not in `SUPPORTED_CONSTRAINTS`.
  - Reject if `onProperty` value or constraint value is a `BNode`.
  - Cardinality constraints (`cardinality/minCardinality/maxCardinality`) require the value be a `Literal`.
  - Other constraints (except `hasValue`) require a `URIRef` value.
  - Returns the 3 triples `[(node,RDF.type,OWL.Restriction),(node,OWL.onProperty,prop),(node,constraint,value)]` and `{prop, value}`.
- `structural_triples(schema_graph)` → `(triples:set, named:set)`:
  - `SKELETON_TYPES` declarations with `URIRef` subjects.
  - `NAMED_AXIOMS` where both subject and object are `URIRef`.
  - For `(subject, RDFS.subClassOf, node)` where subject is `URIRef` and node is `BNode`:
    if `supported_restriction` returns a result, keep the subclass link + the restriction's triples;
    add subject and any `URIRef` in `{prop, value}` to `named`.
- `create_graph_skeleton(schema_graph)` → `Graph`:
  1. `triples, named = structural_triples(schema_graph)`.
  2. For every `resource in named`, copy its `ANNOTATIONS` triples from the schema.
  3. Build a new `Graph`, copy namespace bindings, add all `triples`, return it.

**Invariants**: skeleton ⊆ schema input (subset, no inference); unsupported/incomplete
restrictions are omitted **whole** (never half-copied); schema input unchanged.

---

### 5.3 `graph_patterns.py` — empirical usage patterns

Imports: `collections.Counter`, `statistics.median`; rdflib `Literal, URIRef`,
`OWL, RDF, RDFS, SH, SKOS, XSD`; `graph_management.ONTO`.

**Constants**:

| Name | Value / meaning |
|---|---|
| `METATYPES` | `{OWL.NamedIndividual, SKOS.Concept, OWL.Thing, RDFS.Resource}` — types that say a resource exists, not what it is |
| `STRUCTURAL` | `tuple(str(ns) for ns in (RDF, RDFS, OWL, SH, SKOS))` — namespace strings treated as modeling, not domain |
| `EXCLUDED` | `{ONTO.kind}` — project identity metadata excluded |

**Functions**:

- `eligible(predicate)` — `predicate not in EXCLUDED and not str(predicate).startswith(STRUCTURAL)`.
- `ancestors(schema_graph, class_)` — set of all `URIRef` superclasses reachable via explicit `rdfs:subClassOf` (BFS).
- `usable_classes(schema_graph, instance_graph, resource, cache)` — cached.
  `types` = `URIRef` `RDF.type` objects of resource not in `METATYPES`.
  `specific` = types with no other type in `ancestors(...)` (most-specific; drops superclasses).
  Returns `tuple(sorted(specific or types, key=str))`. Subclass cycles fall back to all stated types.
- `subject_classes(schema_graph, instance_graph, resource, cache)` — `usable_classes(...) or (None,)`.
- `object_ranges(schema_graph, instance_graph, target, cache)` → tuple of `(kind, range)`:
  - `Literal` → `("datatype", datatype)`; missing datatype → `RDF.langString` if language-tagged else `XSD.string`.
  - else → per `usable_classes`: `("class", c)`; if none → `(("unknown", None),)`.
- `class_populations(schema_graph, instance_graph, cache)` — `Counter` of distinct `RDF.type` subjects per usable class.
- `observed_relationships(schema_graph, instance_graph)` → `list[dict]`:
  1. `population = class_populations(...)`.
  2. For each `(subject, predicate, target)` in instance where `eligible(predicate)`:
     for each subject class × each object range, increment `values_per_subject[(class, predicate, kind, range)][subject]`.
  3. Build `records = [pattern_record(key, counts, population) ...]`.
  4. Sort by `(str(subject_class), str(predicate), range_kind, str(range))`.
  5. Return records.
- `pattern_record(key, counts, population)` → dict:
  ```
  {"subject_class": class_, "predicate": predicate, "range_kind": kind, "range": range_,
   "occurrences": sum(values),
   "distinct_subjects": len(values),
   "class_population": population.get(class_) if class_ is not None else None,
   "coverage": len(values)/size if size else None,
   "cardinality_min": min(values),
   "cardinality_median": float(median(values)),
   "cardinality_max": max(values)}
  ```

Notes: observations only (never written back); rare patterns are never dropped; cardinality is
summarized over *participating* subjects only (class members with no value are captured by `coverage`).

---

### 5.4 `ontology_views.py` — the five derived views as one record

Imports: `graph_partition.partition_graph`, `graph_skeleton.create_graph_skeleton`,
`graph_patterns.observed_relationships`. Nine lines of body, no logic of its own.

- `build_ontology_views(source_graph)` → `{"schema", "instance", "support", "skeleton",
  "patterns"}`. The first four are `Graph`s of statements the source itself makes; `patterns`
  is a `list[dict]` of observations. Keeping them in one record names them together; it does
  not make them the same kind of statement.

### 5.5 `source_concepts.py` — what one text mentions

Imports: `re`, `unicodedata`. **No rdflib and no `llm`** — asserted by a test, so a future
NLP/NER/embedding/small-model implementation can replace the body without touching anything
else.

- `normalize(text)` — NFKC, case folded, words single-spaced. Not ASCII-folding: accents and
  non-Latin scripts survive (unlike `entity_lookup.identity_key`).
- `extract_source_concepts(text)` → `list[{"text", "normalized", "kind", "weight", "origin",
  "position"}]`, sorted by `(-weight, position, normalized)`, capped at `MAX_CONCEPTS`.
  `kind` ∈ `mention | phrase | keyword`; `origin` ∈ `heading | capitalized-span | frequency`.
  A capitalized span is a mention *candidate* — never a claimed `Person`/`Organization`.
- `text_phrases(text, longest)` → `{normalized word run: first position}`. Task matching uses
  this so names only match whole words (`art` cannot match inside `particle`, and
  `Berlin, Paris` is not the phrase `Berlin Paris`).

### 5.6 `task_context.py` — select the context one source needs

Imports: rdflib terms; `entity_lookup.entity_catalog`; `graph_patterns.STRUCTURAL, eligible`;
`ontology_views.build_ontology_views`; `source_concepts` (3 helpers).

- `select_task_context(text, concepts, ontology_views, native_entities=None, limits=None)` —
  the independently testable selector.
- `build_task_context(text, source_graph, limits=None)` — composition: views + concepts +
  `entity_catalog(source_graph)`, then the selector.

Returns a **ContextPackage**: `{"concepts", "schema", "patterns", "resources", "examples",
"labels", "diagnostics"}`. Each item is
`{"id", "kind", "value", "priority", "reason", "direct"}` with `kind` ∈ `class | property |
restriction | pattern | resource | example`. Item ids are content-derived and stable
(a restriction's id never uses its blank-node identifier). `labels` maps every URI the
surviving items mention to its names, with the decoded local name as fallback, so rendering
never needs the graph again.

**Priority tiers** (lower is more relevant; ties break on item id):

| Tier | Constant | Meaning |
|---|---|---|
| 1 | `DIRECT_NAME` | a resource name or alias occurs in the source |
| 2 | `DIRECT_LABEL` | a class, property, or predicate label occurs in the source |
| 3 | `CONCEPT` | an extracted concept equals a name or local name |
| 4 | `OVERLAP` | the source shares content words with a description |
| 5 | `DEPENDENCY` | structure a direct match needs (parent/child, domain/range endpoint, restriction, a resource's type) |
| 6 | `CONNECTED` | an observation about a directly matched class or property |
| 7 | `NEIGHBOR` | a one-hop assertion, or the resource at its far end |
| 8 | `INDIRECT` | an observation reached only through a matched resource |

Task relevance outranks empirical frequency by construction: a frequent pattern the source
gives no reason to see is never selected at all.

**Bounded expansion**: one hierarchy hop, visited sets everywhere (so subclass cycles
terminate), restrictions copied whole from the skeleton, and an assertion becomes an example
only when its predicate matters for a reason other than the resource itself (tier < 8) or its
far endpoint was directly matched — otherwise one hub would drag its whole neighbourhood in.

### 5.7 `context_render.py` — render, assemble, budget

Imports: rdflib `BNode, Literal`, `OWL, RDF, RDFS`; `prompt_budget` (3 functions);
`task_context.TEXT_PREDICATES, datatype_term`.

- `render_context_items(context_package, namespace_manager=None)` →
  `list[{"id", "section", "priority", "text", "dependencies"}]`, sorted by
  `(section order, priority, id)`. `section` ∈ `declared | observed | resources | examples`.
- `assemble_context(rendered_items)` → one string: fixed section order, empty sections
  omitted.
- `prepare_prompt_context(context_package, budget_config, count_tokens=estimate_tokens)` →
  `{"text", "budget", "existing_ids"}`. `existing_ids` is the sorted list of native resource
  `id:` values whose cards survived budget packing — derived from the structured package and the
  kept rendered-item ids, never by parsing prompt text. It is what `validate_candidates` takes
  as `allowed_existing_ids`.
- `allowance(budget_config)` — a stated `context_tokens` ceiling, the `context_allowance()`
  arithmetic, or **both, in which case the smaller wins**. Neither present, or incomplete
  arithmetic, raises `KeyError` rather than inventing a number.

Rendering rules that must not regress: a datatype property points at `literal value (...)`,
never at an apparent entity; an unknown observed range stays `unknown`; the six
skeleton-supported restriction forms get careful wording and anything else renders as compact
RDF (`rdfs:subClassOf [ owl:onProperty ... ]`) rather than invented modality; a generic
resource shows `uri:` plus `not usable as existing_id` while a native entity shows `id:`;
labels and descriptions are flattened, control characters removed, and runs of `- = ` # _ * ~`
collapsed so graph text cannot forge a heading, fence, or source delimiter; long fields are
cut at a word boundary with `TRUNCATION_MARKER`.

`assembly_overhead()` charges headings and line breaks against the allowance *before*
packing, for every section the candidates could fill — deliberately pessimistic so the
assembled text can never overrun the allowance.

### 5.8 `prompt_budget.py` — estimate, allowance, packing

Imports: `math.ceil`. Nothing else.

- `estimate_tokens(text, chars_per_token=DEFAULT_CHARS_PER_TOKEN)` — `ceil(len/divisor)`.
- `context_allowance(total_limit, fixed_prompt_tokens, source_tokens, output_reserve,
  safety_margin)` — clamped at 0, never negative.
- `fit_context_items(rendered_items, token_budget, count_tokens=estimate_tokens)` →
  `{"items", "used_tokens", "budget_tokens", "dropped_ids", "item_costs", "estimator"}`.
  Considers items in `(priority, id)` order, takes an item only with its transitive
  `dependencies` and only when the whole bundle fits, and **never slices**: an oversized item
  is dropped whole and named in `dropped_ids`.
- `PROMPT_BUDGET` — the approved production numbers (§10).

The counter is a callable argument throughout: an exact model tokenizer can replace it later
without touching selection or rendering.

---

## 6. Data contracts & return types (quick reference)

| Producer | Function | Return |
|---|---|---|
| `entity_lookup` | `entity_catalog(graph)` | `list[{"id","names","kind","description"}]` |
| `entity_lookup` | `identify_entity(entity, catalog)` | `URIRef \| None` |
| `graph_merge` | `merge_into_graph(graph, data)` | `(new, resolved, relations, facts)` ints |
| `graph_partition` | `partition_graph(graph)` | `(schema:Graph, instance:Graph, support:Graph)` |
| `graph_skeleton` | `create_graph_skeleton(schema)` | `Graph` |
| `graph_patterns` | `observed_relationships(schema, instance)` | `list[dict]` (see 5.3) |
| `llm` | `ask_llm(prompt)` | parsed JSON object |
| `source_parse` | `parse_source(text, context_text="")` | the LLM's parsed JSON object |
| `ontology_views` | `build_ontology_views(graph)` | `{"schema","instance","support","skeleton","patterns"}` |
| `source_concepts` | `extract_source_concepts(text)` | `list[{"text","normalized","kind","weight","origin","position"}]` |
| `source_concepts` | `text_phrases(text, longest)` | `dict[str, int]` (word run → first position) |
| `task_context` | `build_task_context(text, graph, limits=None)` | ContextPackage (see 5.6) |
| `task_context` | `select_task_context(text, concepts, views, native_entities=None, limits=None)` | ContextPackage |
| `context_render` | `render_context_items(package, namespace_manager=None)` | `list[{"id","section","priority","text","dependencies"}]` |
| `context_render` | `assemble_context(rendered_items)` | `str` |
| `context_render` | `prepare_prompt_context(package, budget_config, count_tokens=...)` | `{"text", "budget", "existing_ids"}` |
| `candidate_validation` | `validate_candidates(data, graph, allowed_existing_ids=())` | `ValidationResult` (see 4.7) |
| `candidate_validation` | `format_validation_failure(result)` | `str` |
| `merge_policy` | `build_provenance(path, text, model)` | `{"source_path","source_sha256","model","policy_version"}` |
| `merge_policy` | `plan_graph_merge(graph, candidates, provenance)` | MergePlan (see 4.8) |
| `merge_policy` | `resolve_entities(candidates, graph)` | `{local_id: identity decision}` |
| `graph_merge` | `apply_merge_plan(source_graph, plan)` | `(new graph, result counts)` |
| `prompt_budget` | `estimate_tokens(text, chars_per_token=3)` | `int` |
| `prompt_budget` | `context_allowance(total, fixed, source, reserve, margin)` | `int` (≥ 0) |
| `prompt_budget` | `fit_context_items(items, budget, count_tokens=...)` | `{"items","used_tokens","budget_tokens","dropped_ids","item_costs","estimator"}` |

---

## 7. RDF graph model (what gets written, and where)

- **Namespaces**: `entity:` (individuals), `class:` (kinds), `relation:` (object properties),
  `fact:` (datatype properties), `onto:` (ontology + `Entity` + `EntityShape` + `kind`).
- **Seed**: `onto:ontology` (owl:Ontology), `onto:Entity` (owl:Class), `onto:EntityShape`
  (sh:NodeShape targeting `onto:Entity`, one `sh:property` requiring `skos:prefLabel` minCount 1).
- **Each merged entity** is typed: `onto:Entity`, `owl:NamedIndividual`, `skos:Concept`, `class:<Kind>`.
  It carries `skos:prefLabel`, `rdfs:label`, `onto:kind`, optional `skos:altLabel`(s), optional `rdfs:comment`.
- **Each Kind class**: `owl:Class`, `rdfs:subClassOf onto:Entity`, `rdfs:label`.
- **Each relation**: `relation:<slug>` `owl:ObjectProperty` + `rdfs:label`; each assertion `(s,p,o)`.
- **Each fact**: `fact:<slug>` `owl:DatatypeProperty` + `rdfs:label`; each assertion `(s,p,Literal)`.

---

## 8. Cross-module import graph

Arrows = "imports from".

```
ontology.py ──► candidate_validation.py (validate_candidates, format_validation_failure),
                context_render.py (prepare_prompt_context), graph_management.py,
                graph_merge.py (apply_merge_plan), ingest_sources.py, llm.py (model_name),
                merge_policy.py (build_provenance, plan_graph_merge),
                prompt_budget.py (PROMPT_BUDGET, estimate_tokens),
                source_parse.py, task_context.py (build_task_context)
merge_policy.py ──► entity_lookup.py (entity_catalog, identity_decision, identity_key),
                    graph_management.py (CLASS, ENTITY, FACT, ONTO, RELATION),
                    graph_merge.py (label, slug)
source_parse.py ──► llm.py (ask_llm)
candidate_validation.py ──► entity_lookup.py (entity_catalog, identity_key),
                           graph_management.py (CLASS, FACT, ONTO, RELATION),
                           graph_merge.py (label, slug)
graph_merge.py ──► entity_lookup.py (entity_catalog, identify_entity),
                   graph_management.py (CLASS, ENTITY, FACT, ONTO, RELATION)
entity_lookup.py ──► graph_management.py (ONTO)
graph_patterns.py ──► graph_management.py (ONTO)

context_render.py ──► prompt_budget.py, task_context.py (TEXT_PREDICATES, datatype_term)
task_context.py ──► entity_lookup.py (entity_catalog),
                    graph_patterns.py (STRUCTURAL, eligible),
                    ontology_views.py, source_concepts.py
ontology_views.py ──► graph_partition.py, graph_skeleton.py, graph_patterns.py

graph_partition.py ──► (rdflib only)
graph_skeleton.py ──► (rdflib only)
graph_management.py ──► (rdflib only)
prompt_budget.py ──► (stdlib only)
source_concepts.py ──► (stdlib only)
llm.py ──► (stdlib only)
ingest_sources.py ──► (stdlib only)
```

- The derivation layer is now reached by the pipeline, but only through `ontology_views.py`
  and only for reading.
- `graph_partition` and `graph_skeleton` do **not** depend on `graph_management` (they use raw
  rdflib namespaces). `graph_patterns` depends on `graph_management.ONTO` for the `EXCLUDED` set.
- `source_parse.py` no longer imports `entity_lookup` or rdflib. `entity_lookup` itself is
  unchanged and is still used at merge time against the **whole** graph, so a resource left out
  of the prompt is still available for local resolution.
- `source_concepts.py` and `prompt_budget.py` are the two deliberate seams for future
  replacement (NLP/small model; exact tokenizer). Neither imports rdflib or `llm`.
- `candidate_validation` imports `graph_merge` only for the pure `slug()`/`label()` helpers,
  and does **not** import `ontology`, `source_parse`, or any graph-saving function — validation
  stays outside graph mutation.

---

## 9. Two-stage read-only composition (what originates from what)

```
ontology.ttl  (single merged graph — the only origin)
      │
      ▼  partition_graph()
   ┌──────────┬──────────┬──────────┐
   │ schema   │ instance │ support  │   (disjoint, lossless)
   │ (TBox)   │ (ABox)   │ (header+ │
   │          │          │  SHACL)  │
   └────┬─────┴────┬─────┴──────────┘
        │          │
        ▼          ▼
 create_graph_skeleton(schema)          observed_relationships(schema, instance)
        │          └──────────────┬────────────────┘
        ▼                         ▼
 declared structural core    empirical usage patterns
 (what ontology claims)      (what data actually does)
```

Since phase 5D one more stage sits on top, per source text:

```
source text ──► extract_source_concepts()          [no RDF, no LLM]
                       │
current graph ──► build_ontology_views()  ─────────┐
                                                   ▼
                       select_task_context()  →  ContextPackage
                       (tiers 1-4 direct, 5-8 bounded expansion)
                                                   │
                       render_context_items()  ────┤  declared / observed /
                                                   │  resources / examples
                       fit_context_items()  ───────┤  complete items only
                                                   ▼
assemble_context()  →  one prompt block
                                                    │
                       parse_source(text, block) ──► LLM
                                                    │
                       validate_candidates()  ─────► read only;
                       (normalize, dedupe,          │  any error stops here
                        refs, roles, confidence)    │
                                                    ▼
                       build_provenance() + plan_graph_merge() ──► read only;
                       (identity, accept/duplicate/ │  any failure stops here
                        review, audit triples)      │
                                                    ▼
                       apply_merge_plan()  ───────► a graph copy
                                                    │
                       save_graph() (atomic) ─────► the whole graph again
```

Selection narrows the prompt, never the merge; validation decides admissibility;
merge policy decides identity, acceptance, corroboration, and conflicts against the
complete graph; materialization only applies already-made decisions to a copy.
`identity_decision()` still sees the full catalog. Between them, `candidate_validation`
treats the LLM reply as an untrusted proposal: it verifies structure, references, and
confidence, normalizes, removes intra-package duplicates, and rejects provable role/type
conflicts — still without ever performing identity search or writing to the graph.

- **`support` is consumed by neither tool** — kept apart so metadata/constraints never leak into
  the class/property view.
- **Skeleton** needs only `schema`; **patterns** needs *both* `schema` (for class hierarchy/ranges)
  and `instance` (for actual assertions).
- Complementarity: a pattern with no matching skeleton axiom indicates a missing `domain`/`range`;
  high-coverage patterns can later be turned into SHACL shapes and fed back into the schema.

---

## 10. Constants & defaults quick reference

| Item | Value |
|---|---|
| Base namespace | `http://example.org/text-ontology/` |
| Sub-namespaces | `entity/`, `class/`, `relation/`, `fact/` |
| Default output graph | `ontology.ttl` |
| Default LLM model | `openrouter/pareto-code:nitro` |
| Model env var | `OPENROUTER_MODEL` |
| API key env var | `OPENROUTER_API_KEY` |
| LLM endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| LLM temperature | `0` |
| LLM system prompt | `"Extract knowledge. Return only JSON."` |
| LLM timeout | `60` s |
| Request title header | `"Simple Text to Ontology"` |
| Accepted source extensions | `.txt .md .rst .csv .json .jsonl .yaml .yml .xml .html .log` |
| Seed graph size | 8 triples |
| Close-spelling threshold | `0.96` (SequenceMatcher ratio; review-only since phase 07) |
| Merge policy version | `1` (`merge_policy.MERGE_POLICY_VERSION`) |
| Auto-accept confidence | `0.80` (`merge_policy.AUTO_ACCEPT_MIN_CONFIDENCE`) |
| Dependency | `rdflib>=7,<8` |

Context selection and prompt budget (proposal 05). The budget numbers were approved by the
user on 2026-08-17 after seeing phase 5C measurements:

| Item | Value | Where |
|---|---|---|
| `total_limit` | `30_000` | `prompt_budget.PROMPT_BUDGET` |
| `context_tokens` (ceiling) | `1_400` | same |
| `fixed_prompt_tokens` | `400` | same (measured 331) |
| `output_reserve` | `4_000` | same |
| `safety_margin` | `500` | same |
| `DEFAULT_CHARS_PER_TOKEN` | `3` | `prompt_budget` |
| Selection caps | classes 12, properties 16, restrictions 8, patterns 20, resources 15, examples 12 | `task_context.DEFAULT_LIMITS` |
| Traversal caps | `hierarchy_hops` 1, `instance_hops` 1 | same |
| Matching caps | `concepts` 40, `direct_matches` 40, `match_tokens` 8, `overlap_tokens` 2 | same |
| Concept extraction caps | `MAX_CONCEPTS` 40, `MAX_TOKENS` 5000, `MAX_CHARACTERS` 200 000 | `source_concepts` |
| Concept weights | mention 3.0, phrase 2.0, keyword 1.0; heading +2.0; repeat +0.5 each, capped 3.0; early +1.0 | same |
| Field truncation | `MAX_FIELD_CHARACTERS` 240 | `context_render` |

`total_limit` is deliberately high so that it does not bind; **it is not a measured model
window** and must never be inferred or adjusted from `OPENROUTER_MODEL`, which may name a
router. `context_tokens` is the intended lever on prompt size, and where both apply the
smaller wins.

---

## 11. Error handling summary

| Condition | Module | Error |
|---|---|---|
| Missing source path | `ingest_sources` | `RuntimeError("Source does not exist: {source}")` |
| No text files found | `ontology` | `RuntimeError("No text-like files found")` |
| Missing API key | `llm` | `RuntimeError("Set OPENROUTER_API_KEY first")` |
| OpenRouter HTTP error | `llm` | `RuntimeError(f"OpenRouter error {code}: {message}")` |
| Non-JSON model reply | `llm` | `RuntimeError(f"The model did not return JSON:\n{answer}")` |
| Invalid JSON reply | `llm` | `RuntimeError(f"The model returned invalid JSON:\n{answer}")` |
| Invalid candidate package | `ontology` (via `format_validation_failure`) | `RuntimeError(f"{n} validation error(s): ...")` |
| `main()` catches `RuntimeError`/`OSError` | `ontology` | print to stderr, `SystemExit(1)` |

---

## 12. Current data snapshot (`ontology.ttl`, as parsed from the file)

- **Triples**: 685 total → partition: `schema` 177 · `instance` 502 · `support` 6
  (support = `onto:ontology` + `onto:EntityShape`). `skeleton` == `schema` == 177.
- **Entities**: 45. Kinds: `Entity` (default) 12, `Location` 11, `Event` 8, `Policy` 6,
  `Organization` 4, `Person` 3, `Infrastructure` 1.
- **Entity → kind** (exact):

  | Kind | Entities |
  |---|---|
  | Event | conflict-involving-iran, energy-shock, nvidia-gpu-routing-attempts, orthodox-easter-ceasefire, paris-preparatory-talks, regional-conflicts, russia-ukraine-war, trump-xi-summit |
  | Entity (default) | advanced-chips, defense-manufacturing, electric-vehicles, emerging-military-technologies, energy-markets, energy-transition, long-range-strike-capacity, maritime-security, nato-burden-sharing, rare-earths, renewable-energy-systems, world-economic-forum-2026-global-risks-work |
  | Infrastructure | russian-refining-capacity |
  | Location | canada, china, east-asia, europe, iran, middle-east, paris, russia, strait-of-hormuz, ukraine, united-states |
  | Organization | european-union, nato, nvidia, world-economic-forum |
  | Person | donald-trump, kirill-dmitriev, xi-jinping |
  | Policy | allied-hormuz-maritime-security-commitments, chinese-export-controls, coordinated-mineral-strategy, nato-2-percent-defense-spending-target, temporary-us-sanctions-waiver-on-russian-oil, us-export-restrictions |

- **Classes**: 8 `owl:Class` — the root `onto:Entity` plus 7 `class:*` kinds (`entity`,
  `event`, `infrastructure`, `location`, `organization`, `person`, `policy`). `class:entity`
  carries the sources that report no kind (the validator's `Entity` default).
- **Properties**: 39 `relation:*` object properties, 38 `fact:*` datatype properties (each with an `rdfs:label`).
- **Patterns**: 84 pattern records derived from the instance view.
- **Sources**: 5 `.md` briefs (global risk; US–China–EU semiconductors; critical minerals;
  Russia–Ukraine sanctions; NATO posture and burden sharing).

> Note: a handful of repository-graph tests (`test_graph_partition.RepositoryGraphTest`,
> `test_graph_skeleton.RepositoryGraphTest`, parts of `test_graph_patterns`) still pin the
> *previous* snapshot's numbers (169/43/120/6 triples and 17 patterns) and currently fail
> against this grown graph. They are data-snapshot assertions, not logic failures; re-run the
> pipeline snapshot numbers or update the pinned values to make them green again.

---

## 13. Test coverage map (the enforced contracts)

| Test file | What it pins down |
|---|---|
| `test_pipeline.py` | blank-file skip; per-file save + growing context; graph dir creation; default `ontology.ttl`; progress lines; error paths; rerun resolves (0 new / 1 resolved, name becomes altLabel); **5D**: a mentioned entity reaches the prompt and an unmentioned one does not; the old catalog block is gone; context rebuilt per file; zero allowance still a valid prompt; the budget line is printed; the context stays within the ceiling; an entity absent from the prompt still resolves at merge time; a failed call leaves the saved graph byte-identical; the repository graph is untouched; **6C**: normalized candidates reach the merger; the `Validated:` report and duplicate count; non-mapping / bad-endpoint / hallucinated-`existing_id` responses reject the file; a valid prompt-`existing_id` resolves; no merge or save after a validation error; a rejected source leaves the file byte-identical; prior files stay saved and later files are not processed; duplicate-only warnings still merge; blank files bypass validation/merge/save; **07**: plan → apply → save ordering with `report_plan`; a mixed package reports accepts, duplicates, and reviews; duplicate corroboration is reported and not re-added; a review-only package is saved without domain assertions; a planning failure leaves both graphs unchanged; a save failure leaves the old file usable; the next file resolves an accepted entity but not a proposal |
| `test_ingest_sources.py` | direct file accepts any extension; directory = recursive+sorted+extension-filtered+graph-excluded; missing source error; utf-8 replace |
| `test_source_parse.py` | prompt contains source + the given context + JSON contract; the context heading, id/uri rule, and "not a rule" wording; the old catalog block is absent and the module no longer imports `entity_catalog`/rdflib; empty and whitespace-only context omit the block; `parse_source` delegates to `ask_llm` |
| `test_ontology_views.py` | the five fields; façade equals the direct calls on rich, sparse, and repository graphs; lossless partition; skeleton gains no domain/range; observations never become declared structure; foreign individuals need no `onto:Entity`; prefixes survive on all four graphs; sources unchanged |
| `test_source_concepts.py` | record fields and vocabularies; blank and punctuation-only input; determinism and tie order; Unicode without accent stripping; caseless scripts; mentions claim no type; comma separation; heading/repetition/early weighting and the repetition cap; deduplication; caps; no rdflib/`llm` import; the phrase index |
| `test_task_context.py` | package/item/match shapes and diagnostics; label, prefLabel, altLabel, and local-name matching; word boundaries; tier order; declared domain/range and their absence; one hierarchy hop, no second hop, cycles terminate; restriction bundles with blank-node-independent ids; patterns by predicate, subject class, class range, datatype, unknown range; declared vs observed conflict; native vs generic cards; the preferred name; examples and hub protection; unrelated source, empty graph, empty source; every cap; determinism; immutability; the label map |
| `test_context_render.py` | rendered-item shape and stable ids; classes with/without parents; object vs datatype properties; declared domain/range and their absence; all six supported restriction forms; unsupported forms as RDF with no invented modality; pattern evidence, datatype and unknown ranges, classless subjects; the evidence heading; declared/observed kept apart; native card fields and the duplicate-`kind` rule; generic cards refused as `existing_id`; object and literal assertions; label → prefix → URI; flattened newlines, defused delimiters, stripped controls; field truncation; section order and omission; composition, the allowance never exceeded, both-limits arithmetic, refused configs, injected counters, caps with the token cap, immutability; **6C**: `existing_ids` is returned sorted, empty for a zero budget / generic resources / schema+patterns+examples, and derived only from native resource cards |
| `test_prompt_budget.py` | estimator on empty/ASCII/Unicode/multiline and a changed divisor; allowance arithmetic clamped at zero; priority order; usage never exceeding the allowance; id tie-breaking; zero allowance; oversized items dropped whole; multiline items all-or-nothing; injected counters and the estimator name; dependency bundles charged once, dropped together, never invented; per-item costs, dropped order, empty result, immutability |
| `test_entity_lookup.py` | `identity_key` normalization; catalog fields/sorting; `existing_id` precedence; exact name+kind (unique only); 0.96 threshold + tie ambiguity; kind-mismatch never resolves |
| `test_graph_merge.py` | slug/label; URI suffix uniqueness; full typing; enrich vs overwrite (comment not overwritten, differing name→altLabel); skip invalid records/endpoints; dedup; sequential visibility; count order `(new, resolved, relations, facts)`; **07**: `apply_merge_plan` copies bindings and triples, asserts only plan triples, reports the extended counts, leaves the input triple-identical even on failure |
| `test_candidate_validation.py` | result/issue/count field sets; container errors; record + field shape; id grammar and no type coercion; NFKC/line-ending/control/whitespace normalization; description internal whitespace; date/number strings not coerced; kind defaulting; alias normalization/dedup; literal types and the typed duplicate key; NaN/inf/collection rejection; empty/`unnamed`/URI-looking predicates; deterministic issue order; invalid result exposes no candidates; input immutability; `existing_id` allowed/present/kind-match rules; duplicate ids and existing ids; unknown references; relation/fact duplicates and kept+removed paths; graph-exact duplicates only with explicit ids; no `identify_entity` import; relation/fact/kind role and type collisions; compatible pre-existing properties; slug-colliding label pairs; new predicates accepted; non-contradiction of differing values; determinism across insertion order; graph immutability; `format_validation_failure`; **07**: required numeric confidence in `[0,1]`, missing/invalid confidence codes, duplicate-confidence warnings keeping the lower value, graph-exact candidates kept for policy corroboration |
| `test_merge_policy.py` | canonical JSON + record digests; provenance fields; identity decisions (explicit id, exact name/alias, planned exact, ambiguous exact review, kind collision review, close-spelling review-only suggestions, below-threshold provisional URI); URI reservation so two new entities cannot collide; assertion outcomes accept/duplicate/review with reason codes; exact-triple corroboration without re-adding; functional / inverse-functional conflict review; existing labels/descriptions never overwritten; alias claimed by another same-kind entity routes only that alias to review; audit vocabulary (`ExtractionEvent`, `MergeCandidate`, reified assertions, `rdf:JSON` normalized candidate, decimal confidence); event/candidate URI determinism across reruns; no timestamps or raw source/prompt/response in the graph; counts and diagnostics; read-only planning |
| `test_graph_management.py` | seed structure (isomorphic, 8 triples); no reseed on existing; prefix bindings; save/reload round-trip; **07**: atomic save via temp sibling + `os.replace`; failed serialization leaves the old file byte-identical and no stale temp file |
| `test_graph_partition.py` | role classification per triple; restrictions; remainder; dual-role; lossless+disjoint+read-only invariants; repo-graph snapshot sizes (pinned values currently behind the grown graph — see §12) |
| `test_graph_skeleton.py` | core retention; exclusion of instances/support; supported vs unsupported restrictions; no inference; skeleton ⊆ input |
| `test_graph_patterns.py` | class/literal/unknown ranges; counting; coverage/cardinality; most-specific class; exclusions; deterministic ordering; read-only |

---

## 14. Gotchas & non-obvious behavior (from tests)

1. **Non-ASCII lossy folding**: `identity_key`/`slug` NFKD→ascii drops characters with no
   decomposition (e.g. `ł` disappears entirely) instead of transliterating.
2. **`slug` fallback**: an input that normalizes to empty becomes `"unnamed"`.
3. **Exact-name match requires equal kind**; a missing kind on either side (parsed or catalog) blocks resolution.
4. **Two exact matches** (same normalized name + kind) → no resolution (ambiguity), even though step 1 (`existing_id`) would resolve.
5. **Close-spelling uses only the preferred name** (`entity["name"]`), never aliases.
6. **Existing `rdfs:comment` is never overwritten**; a later description is dropped.
7. **Existing `skos:prefLabel` is kept**; a later differing preferred name becomes an `altLabel`.
8. **Blank text files are skipped before the LLM call**.
9. **The output graph is excluded from directory ingestion** by resolved-path comparison.
10. **`.env` loading never overrides** already-set environment variables (`setdefault`).
11. **Opening a missing graph does not write to disk**; only `save_graph` does.
12. **`partition`/`skeleton`/`patterns` must never mutate** their inputs or the on-disk graph.
13. **Skeleton does no inference**: no transitive subclass closure, no inferred domains/ranges,
    no declarations for range-only resources.
14. **Unsupported/incomplete OWL restrictions are dropped whole** by the skeleton (never half-copied).
15. **The prompt is a selection, not the graph**: an entity in the graph reaches the prompt only
    if the source gives a reason to select it. This is why `test_pipeline` asserts both that a
    mentioned entity appears *and* that an unmentioned one does not.
16. **Selection narrows the prompt, not the merge**: `identify_entity()` still runs against the
    whole catalog, so an entity omitted from the prompt can still be resolved rather than
    duplicated.
17. **`onto:Entity` is not required** to be selectable as context, but only entities in
    `entity_catalog()` are rendered with an `id:` the model may reuse; everything else gets
    `uri:` and an explicit "not usable as existing_id".
18. **Two normalizations coexist on purpose**: `entity_lookup.identity_key` (ASCII-folding, for
    merge-time identity) and `source_concepts.normalize` (Unicode-preserving, for source
    matching). Do not unify them without deciding what merge identity should mean.
19. **`source_concepts` uses whole-word runs**, so a hyphenated source term matches a spaced
    label, and a short label cannot match inside a longer word.
20. **The context budget is charged pessimistically** (headings for every candidate section, a
    3-characters-per-token divisor), so the assembled context always fits the stated allowance
    and usually undershoots it.
21. **Observations never become axioms**: a pattern record is copied into the package and
    rendered under an "EVIDENCE, NOT AN ONTOLOGY RULE" heading; nothing writes it back as
    `rdfs:domain`/`rdfs:range`.
22. **Tier-8 observations are deliberately weak**: reached only through a matched resource's
    class, dropped first by the budget, and excluded from the reasons that justify pulling in a
    hub's neighbouring assertions.
23. **Validation fails closed**: one error rejects the whole candidate package for that source
    — there is no partial merge. Duplicates are warnings, not errors.
24. **`existing_id` must have been shown**: an `existing_id` is accepted only if the id was
    rendered as `id:` in the *final* budgeted prompt and still exists in `entity_catalog()`.
    Merge-time name/kind/close-spelling fallback still runs for `existing_id: null`, unchanged.
25. **The validator never calls `identify_entity()`**: it checks only explicit ids and provable
    URI-role/type conflicts, and removes graph-exact duplicates only where both endpoints carry
    an explicit `existing_id`. Identity search stays a point-7 merge concern.
26. **Fact duplicate keys include the JSON type**: `"1"`, `1`, and `true` are distinct facts;
    NaN/±infinity and collections are rejected outright.
27. **`slug` collisions are caught only within one section**: two predicates that slug to one
    URI but to different `label()`s are an error; existing labels at a generated URI are treated
    as harmless formatting (the slug/label asymmetry is a known migration, not fixed here).
28. **Three normalizations coexist on purpose**: `entity_lookup.identity_key` (merge identity),
    `source_concepts.normalize` (source matching), and `candidate_validation`'s field
    normalization (stable representation) are deliberately not unified.

---

*End of architecture map. Generated from source files only; no external documentation was consulted.*
