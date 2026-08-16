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

The codebase has two layers:

1. **Write pipeline** — actually executed by `ontology.py`; builds the graph.
2. **Read-only derivation layer** — three modules that generalize an existing graph;
   **not imported or called by the pipeline** (only by their own tests).

---

## 2. Repository layout

```
text_to_ontology_2/
├── ontology.py              # entry point: CLI + run loop
├── ingest_sources.py        # source discovery + reading
├── source_parse.py          # prompt builder
├── llm.py                   # OpenRouter HTTP client (stdlib only)
├── entity_lookup.py         # entity resolution (local fallback)
├── graph_merge.py           # write parsed results into graph
├── graph_management.py      # open / seed / bind / save graph; owns namespaces
├── graph_partition.py       # [read-only] split graph into schema/instance/support
├── graph_skeleton.py        # [read-only] compact declared structural core
├── graph_patterns.py        # [read-only] empirical usage patterns
├── ontology.ttl             # output graph (data, not code)
├── requirements.txt         # rdflib>=7,<8
├── .env                     # OPENROUTER_API_KEY, OPENROUTER_MODEL
├── README.md / next_steps.md# notes (not architecture source)
├── sources/                 # 4 geopolitical briefs (.md) — sample input
└── tests/                   # one unittest file per module + pipeline
    ├── test_pipeline.py
    ├── test_ingest_sources.py
    ├── test_source_parse.py
    ├── test_entity_lookup.py
    ├── test_graph_merge.py
    ├── test_graph_management.py
    ├── test_graph_partition.py
    ├── test_graph_skeleton.py
    └── test_graph_patterns.py
```

Dependency: only `rdflib` (`requirements.txt`: `rdflib>=7,<8`).

---

## 3. Entry point — `ontology.py`

### 3.1 Imports

- stdlib: `argparse`, `sys`, `time`, `pathlib.Path`
- project:
  - `graph_management.open_graph, save_graph`
  - `graph_merge.merge_into_graph`
  - `ingest_sources.find_text_files, read_source`
  - `llm.model_name`
  - `source_parse.parse_source`

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
            continue                          # blank files skipped BEFORE LLM call
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, graph)   # LLM call
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        counts = merge_into_graph(graph, extraction)
        save_graph(graph, args.graph)            # saved AFTER EACH FILE
        print(f"  {counts[0]} new, {counts[1]} resolved, "
              f"{counts[2]} relations, {counts[3]} facts")
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
- **Sequential context**: each file's prompt includes the entity catalog of everything merged so far.
- **Blank file skip**: whitespace-only sources never reach the LLM.

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
- `save_graph(graph, path)` — `graph.serialize(path, format="turtle")`.

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

Imports: `json`; rdflib `OWL, RDF, RDFS`; `entity_lookup.entity_catalog`; `llm.ask_llm`.

**Functions**:

- `make_prompt(text, graph)`:
  - `entities = json.dumps(entity_catalog(graph), ensure_ascii=False)`.
  - `properties = sorted({str(name) for property_type in (OWL.ObjectProperty, OWL.DatatypeProperty) for uri in graph.subjects(RDF.type, property_type) for name in graph.objects(uri, RDFS.label)})`
    — i.e. every `rdfs:label` of every `owl:ObjectProperty` / `owl:DatatypeProperty` in the graph, sorted, deduplicated. Unlabelled properties are excluded.
  - Returns an f-string with: `EXISTING ENTITIES`, `EXISTING PROPERTY NAMES`,
    resolution instructions (`existing_id` rules), the required JSON shape, and `SOURCE`.
- `parse_source(text, graph)` — `return ask_llm(make_prompt(text, graph))`. Does not mutate the graph.

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
entity ids; `existing_id` must be an existing entity's exact id or `null`; return JSON only.

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

---

## 5. Module reference (read-only derivation layer)

These modules are **not** imported by the pipeline. They are imported only by their own tests.

### 5.1 `graph_partition.py` — split into 3 views

Imports (rdflib only): `BNode, Graph, Literal`; `OWL, RDF, RDFS, SH, SKOS`.

**Constants** (sets of rdflib terms):

| Name | Members |
|---|---|
| `SCHEMA_TYPES` | `OWL.Class, RDFS.Class, RDFS.Datatype, RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty` |
| `SUPPORT_TYPES` | `OWL.Ontology, SH.NodeShape, SH.PropertyShape` |
| `SCHEMA_AXIOMS` | `RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range, OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith, OWL.inverseOf` |
| `ANNOTATIONS` | `RDFS.label, RDFS.comment, SKOS.prefLabel, SKOS.altLabel, SKOS.definition` |
| `RESTRICTION_TARGETS` | `OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass, OWL.onDataRange` |

**Functions**:

- `owned_nodes(graph, root)` — `{root}` plus every blank node reachable from `root` via object position (BFS).
- `support_roles(graph)` — subjects typed with any `SUPPORT_TYPES` type, plus their `owned_nodes`.
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
| `source_parse` | `parse_source(text, graph)` | the LLM's parsed JSON object |

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
ontology.py ──► graph_management.py, graph_merge.py, ingest_sources.py,
                llm.py (model_name), source_parse.py
source_parse.py ──► entity_lookup.py (entity_catalog), llm.py (ask_llm)
graph_merge.py ──► entity_lookup.py (entity_catalog, identify_entity),
                   graph_management.py (CLASS, ENTITY, FACT, ONTO, RELATION)
entity_lookup.py ──► graph_management.py (ONTO)
graph_patterns.py ──► graph_management.py (ONTO)

graph_partition.py ──► (rdflib only)
graph_skeleton.py ──► (rdflib only)
graph_management.py ──► (rdflib only)
llm.py ──► (stdlib only)
ingest_sources.py ──► (stdlib only)
```

- `graph_partition.py`, `graph_skeleton.py`, `graph_patterns.py` are **not** imported by any
  pipeline module. They are imported only by their own tests.
- `graph_partition` and `graph_skeleton` do **not** depend on `graph_management` (they use raw
  rdflib namespaces). `graph_patterns` depends on `graph_management.ONTO` for the `EXCLUDED` set.

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
| Close-spelling threshold | `0.96` (SequenceMatcher ratio) |
| Dependency | `rdflib>=7,<8` |

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
| `main()` catches `RuntimeError`/`OSError` | `ontology` | print to stderr, `SystemExit(1)` |

---

## 12. Current data snapshot (`ontology.ttl`, as parsed from the file)

- **Triples**: 169 total → partition: `schema` 43 · `instance` 120 · `support` 6
  (support = `onto:ontology` + `onto:EntityShape`).
- **Entities**: 20. Kinds: `Location` 9, `Organization` 4, `Person` 3, `Event` 2,
  `Policy` 1, `Infrastructure` 1.
- **Entity → kind** (exact):

  | Kind | Entities |
  |---|---|
  | Location | china, east-asia, europe, iran, paris, russia, strait-of-hormuz, ukraine, united-states |
  | Organization | european-union, nato, nvidia, world-economic-forum |
  | Person | donald-trump, kirill-dmitriev, xi-jinping |
  | Event | orthodox-easter-ceasefire, russia-ukraine-war |
  | Policy | temporary-us-sanctions-waiver-on-russian-oil |
  | Infrastructure | russian-refining-capacity |

- **Properties**: 17 `relation:*` object properties, 16 `fact:*` datatype properties (each with an `rdfs:label`).
- **Patterns**: 18 assertions aggregate into 17 pattern records (some shared-literal property spans two subjects).
- **Sources**: 4 `.md` briefs (global risk; US–China–EU semiconductors; critical minerals;
  Russia–Ukraine sanctions).

---

## 13. Test coverage map (the enforced contracts)

| Test file | What it pins down |
|---|---|
| `test_pipeline.py` | blank-file skip; per-file save + growing context; graph dir creation; default `ontology.ttl`; progress lines; error paths; rerun resolves (0 new / 1 resolved, name becomes altLabel) |
| `test_ingest_sources.py` | direct file accepts any extension; directory = recursive+sorted+extension-filtered+graph-excluded; missing source error; utf-8 replace |
| `test_source_parse.py` | prompt contains source + catalog + property labels + JSON contract; `parse_source` delegates to `ask_llm` and is read-only |
| `test_entity_lookup.py` | `identity_key` normalization; catalog fields/sorting; `existing_id` precedence; exact name+kind (unique only); 0.96 threshold + tie ambiguity; kind-mismatch never resolves |
| `test_graph_merge.py` | slug/label; URI suffix uniqueness; full typing; enrich vs overwrite (comment not overwritten, differing name→altLabel); skip invalid records/endpoints; dedup; sequential visibility; count order `(new, resolved, relations, facts)` |
| `test_graph_management.py` | seed structure (isomorphic, 8 triples); no reseed on existing; prefix bindings; save/reload round-trip |
| `test_graph_partition.py` | role classification per triple; restrictions; remainder; dual-role; lossless+disjoint+read-only invariants; repo graph sizes (169/43/120/6) |
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

---

*End of architecture map. Generated from source files only; no external documentation was consulted.*
