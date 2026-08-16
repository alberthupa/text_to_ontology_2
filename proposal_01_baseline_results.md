# Proposal 01: Baseline Results

Actual observations of the pipeline. Nothing here is predicted; every number was
produced by running the code.

## Environment

- Python 3.12.3 (`.venv/bin/python`)
- rdflib 7.6.0
- Branch `proposal-01/current-pipeline`
- No network access and no API key were used. The LLM boundary is patched in
  every test.

## Commands used

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python ontology.py --help
git diff --check
git status --short
```

## Architecture as built

### Module map

Every module has one role in the run. Imports go one direction only; there are
no cycles and no shared generic module.

```text
ontology.py                CLI and main(); the pipeline is readable top to bottom
  |
  |-> ingest_sources.py    find the files, read the text        (no imports at all)
  |-> source_parse.py      build the prompt, ask the model
  |     |-> entity_lookup.py   for the catalog sent as context
  |     |-> llm.py             transport
  |-> graph_merge.py       write parsed knowledge into the graph
  |     |-> entity_lookup.py   identity decision, once per entity
  |     |-> graph_management.py  namespaces
  |-> graph_management.py  open, seed, bind, save                (rdflib only)
  |-> llm.py               model_name() for the progress message (stdlib only)
```

`entity_lookup.py` imports `graph_management.py` for the project namespace and
nothing else. `llm.py` is a leaf. Nothing imports `ontology.py`.

### `ontology.py` — orchestration

```python
main()
```

The only executable entry point. It defines the two CLI arguments, opens the
graph, discovers the sources, and then loops: read, skip if blank, parse, merge,
save, print counts. It owns every `print()`, the LLM timing, and the top-level
conversion of `RuntimeError` and `OSError` into `Error: ...` with exit code 1.

It holds no namespaces, no triple construction, no prompt text, no matching
logic, and no HTTP.

### `ingest_sources.py` — locate and read

```python
TEXT_FILES                          # the accepted directory extensions
find_text_files(source, graph_path) # -> [Path, ...]
read_source(path)                   # -> str
```

A directly named file is returned as-is, whatever its extension. A directory is
searched recursively, results are sorted, only `TEXT_FILES` extensions are kept,
and the output graph is excluded by resolved path. A missing source raises
`RuntimeError("Source does not exist: ...")`. Reading is UTF-8 with
`errors="replace"`. The empty-source skip lives in `main()`, not here.

### `source_parse.py` — one source to candidate knowledge

```python
make_prompt(text, graph)  # -> str
parse_source(text, graph) # -> dict from the model
```

`parse_source()` is the entry point; it builds the prompt and hands it to
`llm.ask_llm()`. The prompt carries three things: the source text, the full
entity catalog from `entity_lookup.entity_catalog()`, and the sorted set of
`rdfs:label` values on every `owl:ObjectProperty` and `owl:DatatypeProperty`.

It still receives the whole graph because the prompt is still built from the
whole catalog. That is the seam where a semantic skeleton would later replace
"send everything".

The model is asked for this shape, and the merge step expects exactly it:

```json
{
  "entities":  [{"id": "e1", "name": "...", "kind": "...",
                 "description": "...", "aliases": ["..."], "existing_id": null}],
  "relations": [{"subject": "e1", "predicate": "works for", "object": "e2"}],
  "facts":     [{"subject": "e1", "predicate": "birth date", "value": "1950-01-01"}]
}
```

`id` values are local to one response. "Facts" are characteristics with literal
values. This module never writes to the graph.

### `entity_lookup.py` — is this entity already here?

```python
identity_key(text)                # -> normalized comparison string
entity_catalog(graph)             # -> [{"id", "names", "kind", "description"}, ...]
identify_entity(entity, catalog)  # -> URIRef or None
```

Catalog membership is exactly `?e rdf:type onto:Entity`. A resource that is only
an `owl:NamedIndividual`, a `skos:Concept`, or an instance of a domain class is
not in the catalog. `names` merges `skos:prefLabel` and `skos:altLabel`; `kind`
and `description` take the first `onto:kind` and `rdfs:comment`.

`identify_entity()` decides in this order:

1. the model's `existing_id`, if it is a key of the current catalog;
2. an exact normalized match of the parsed name or any parsed alias against any
   catalog name, requiring equal normalized kinds and exactly one match;
3. a close spelling of the parsed preferred name only, same kind requirement,
   accepted at similarity `>= 0.96` and only when strictly better than the
   runner-up;
4. otherwise `None`.

The contract is deliberately narrow: `URIRef` or `None`. It creates no URI, adds
no triple, and has no threshold policy, semantic search, or human review. This
module is the single place where a future identity pipeline gets built.

### `graph_merge.py` — write it into the graph

```python
slug(text)                    # -> URI-safe local name
label(text)                   # -> readable label
new_entity_uri(graph, name)   # -> unused entity: URI, numeric suffix on collision
merge_into_graph(graph, data) # -> (new, resolved, new_relations, new_facts)
```

`merge_into_graph()` walks `data["entities"]` in the order returned, and for
each one calls `entity_lookup.identify_entity()` against a catalog rebuilt from
the current graph, then writes that entity immediately. **This ordering is
load-bearing**: the second mention of a company in one response resolves to the
entity the first mention just created. An all-at-once lookup phase would break
it, which is why the catalog is not cached.

Each processed entity is typed `onto:Entity`, `owl:NamedIndividual`,
`skos:Concept`, and its generated `class:` domain class; the class is declared
`owl:Class`, `rdfs:subClassOf onto:Entity`, and labeled. A missing kind becomes
`Entity`. The first preferred name becomes both `skos:prefLabel` and
`rdfs:label`; a later differing one becomes `skos:altLabel`; aliases become
`skos:altLabel`. A description is written only when `rdfs:comment` is absent —
existing descriptions are never overwritten.

Relations need both endpoints to be local ids that were processed. Facts need a
processed subject and a non-`None` value. Counts report only newly added
triples, so replaying a response reports zeros.

It does not read files, build prompts, call the model, or touch the filesystem.

### `graph_management.py` — lifecycle and vocabulary

```python
BASE, ONTO, ENTITY, CLASS, RELATION, FACT
bind(graph)
open_graph(path)        # -> existing graph, or a freshly seeded one
save_graph(graph, path) # Turtle serialization
```

URIs live under `http://example.org/text-ontology/`, split into `entity/`,
`class/`, `relation/`, and `fact/`. A missing graph file is seeded with eight
triples: the `owl:Ontology` declaration, the `onto:Entity` class and its label,
and the SHACL node shape requiring at least one `skos:prefLabel`. An existing
file is parsed and never re-seeded.

Scope is intentionally narrow — lifecycle and base vocabulary. It is not a
place to put merge rules, context selection, or future skeleton logic.

### `llm.py` — transport

```python
DEFAULT_MODEL, load_env(path=None), model_name(), ask_llm(prompt)
```

Unchanged by this proposal. It loads `.env`, picks the model, posts one
chat-completion request to OpenRouter, converts HTTP failures into
`RuntimeError`, and extracts the JSON object from the reply, tolerating a
Markdown code fence. No prompt text lives here.

### Data that crosses module boundaries

| Value | Produced by | Consumed by |
|---|---|---|
| `[Path, ...]` | `find_text_files()` | `main()` |
| source `str` | `read_source()` | `main()`, `parse_source()` |
| parsed `dict` (entities/relations/facts) | `parse_source()` | `merge_into_graph()` |
| catalog `list[dict]` | `entity_catalog()` | `make_prompt()`, `identify_entity()` |
| `URIRef` or `None` | `identify_entity()` | `merge_into_graph()` |
| `(new, resolved, relations, facts)` | `merge_into_graph()` | `main()` printing |

### Invariants worth not breaking later

- Identity is decided in exactly one place: `entity_lookup.identify_entity()`.
- The catalog is rebuilt per entity, never cached across a merge.
- Each entity is merged before the next is identified.
- The graph is serialized after every source file, not once at the end.
- Parsing never mutates the graph; merging never performs I/O.

### Test layout

One test file per module role, mirroring the code:

```text
tests/test_ingest_sources.py    discovery, filtering, encoding
tests/test_source_parse.py      prompt content, parse_source() entry point
tests/test_entity_lookup.py     catalog shape and the full match order
tests/test_graph_merge.py       triples, skip rules, counts, sequential visibility
tests/test_graph_management.py  seeding, reopening, binding, saving
tests/test_pipeline.py          main() end to end with the LLM patched
```

`tests/test_pipeline.py` patches `source_parse.ask_llm`, so no test reaches the
network or needs a key.

## Running it right now

### One-time setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then create `.env` beside `ontology.py` (this repository already has one, with
`OPENROUTER_API_KEY` and `OPENROUTER_MODEL` set; the model currently resolves to
`openrouter/pareto-code:nitro`):

```text
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL=openrouter/pareto-code:nitro
```

### The tests, which need neither key nor network

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s tests -v          # per-test names
.venv/bin/python -m unittest tests.test_entity_lookup      # one module
```

### Running the program

```bash
.venv/bin/python ontology.py --help
```

Both of these call the model and cost tokens, and both write the graph in
place:

```bash
# every supported file under sources/, into the repository graph
.venv/bin/python ontology.py sources/ ontology.ttl

# one file; the graph argument defaults to ontology.ttl
.venv/bin/python ontology.py sources/01_global_risk_overview.md
```

To try it without touching the committed graph, write somewhere else:

```bash
.venv/bin/python ontology.py sources/ /tmp/scratch.ttl
```

Re-running against the same graph adds to it. Entities that resolve are
enriched rather than duplicated, so a second identical run typically prints
`0 new, N resolved`.

### Inspecting the result

```bash
head -40 ontology.ttl
```

```bash
.venv/bin/python -c "
from pathlib import Path
from entity_lookup import entity_catalog
from graph_management import open_graph
graph = open_graph(Path('ontology.ttl'))
print(len(graph), 'triples')
for item in entity_catalog(graph):
    print(f\"{item['kind']:<14} {item['names']}\")
"
```

At the time of writing, the committed `ontology.ttl` holds 169 triples and 12
catalog entities.

### Using the modules directly

The pieces are importable on their own, which is the point of the refactor:

```python
from pathlib import Path

from graph_management import open_graph, save_graph
from graph_merge import merge_into_graph
from ingest_sources import find_text_files, read_source
from source_parse import parse_source

graph = open_graph(Path("ontology.ttl"))
for path in find_text_files(Path("sources"), Path("ontology.ttl")):
    text = read_source(path)
    if not text.strip():
        continue
    print(merge_into_graph(graph, parse_source(text, graph)))
    save_graph(graph, Path("ontology.ttl"))
```

Swap `parse_source(text, graph)` for a literal dict to exercise the merge
without spending a request:

```python
merge_into_graph(graph, {
    "entities": [{"id": "e1", "name": "Acme Corp", "kind": "Company",
                  "description": "A maker of things.", "aliases": ["ACME"]}],
    "relations": [], "facts": [],
})
```

### Checking identity behavior by hand

```bash
.venv/bin/python -c "
from pathlib import Path
from entity_lookup import entity_catalog, identify_entity
from graph_management import open_graph
catalog = entity_catalog(open_graph(Path('ontology.ttl')))
print(identify_entity({'name': 'European Union', 'kind': 'Organization',
                       'aliases': ['EU'], 'existing_id': None}, catalog))
"
```

It prints the matching URI or `None`, using the same rules the merge step uses.

## Stage 1: behavior captured before any code moved

72 deterministic tests were written against the untouched `ontology.py` and all
passed. They cover the 22 minimum baseline cases of the proposal.

| Test file | Baseline cases |
|---|---|
| `tests/test_graph_management.py` | 1, 2 |
| `tests/test_ingest_sources.py` | 3, 4 |
| `tests/test_source_parse.py` | 6 |
| `tests/test_entity_lookup.py` | 7, 8, 9, 10, 11, 12, 13 |
| `tests/test_graph_merge.py` | 14, 15, 16, 17, 18, 19, 20, 22 |
| `tests/test_pipeline.py` | 5, 21 |

## Measured run

A fixed two-file run with a patched LLM response, then a third replay of the
second response against the same graph.

| Observation | Value |
|---|---|
| New graph triples (seed only) | 8 |
| New graph entity catalog size | 0 |
| File 1 prompt characters | 1053 |
| File 1 counts (new, resolved, relations, facts) | 2, 0, 1, 1 |
| Triples after file 1 | 37 |
| Catalog size after file 1 | 2 |
| File 2 prompt characters | 1341 |
| File 2 counts | 1, 1, 1, 1 |
| Triples after file 2 | 50 |
| Catalog size after file 2 | 3 |
| Replay of the same response, counts | 0, 2, 0, 0 |
| Replay triples added | 0 |
| Final triples | 50 |
| Saved Turtle size | 2032 bytes |

The prompt grows from 1053 to 1341 characters after two entities enter the
graph, because the whole catalog and every labeled property are resent.

## Observed duplicate, ambiguity, and conflict behavior

- Replaying an identical response added no triples and reported `0` new
  relations and `0` new facts, while still reporting `2` resolved entities.
- `acme corp` resolved to the existing `Acme Corp` through normalized name plus
  equal normalized kind. Its differing preferred name was stored as
  `skos:altLabel`, and its competing description did **not** replace the
  existing `rdfs:comment`.
- A relation whose object was an unknown local id, and a fact whose value was
  `null`, were both silently skipped, and their properties were not declared.
- Two catalog entities matching one candidate exactly resolve to nothing; the
  tie is not broken.
- A close spelling resolves only at similarity `0.96` or above, with an equal
  normalized kind, and only when it is strictly better than the next candidate.

## Behavior found during baselining that the proposal did not describe

`slug()` and `identity_key()` both normalize with NFKD and then encode to ASCII
with `errors="ignore"`. Characters that have no NFKD decomposition are dropped
instead of folded. Polish `ł` is the clear example:

```text
slug("Zażółć Gęślą")         -> "zazoc-gesla"
identity_key("Zażółć Gęślą") -> "zazocgesla"
```

The accented vowels fold correctly; only `ł` disappears. This is recorded, not
corrected. Proposal 1 preserves it, and the tests pin the current result so that
any future change to it is a deliberate decision rather than an accident.

## Stage-by-stage verification after each move

Every stage ran the full suite before the next stage began.

| Stage | Change | Tests | Behavior |
|---|---|---|---|
| 1 | Baseline tests added, no production change | 72 passed | unchanged |
| 2 | `graph_management.py` extracted, `save_graph()` added | 72 passed | unchanged |
| 3 | `ingest_sources.py` extracted | 72 passed | unchanged |
| 4 | `entity_lookup.py` extracted, `resolve` renamed | 72 passed | unchanged |
| 5 | `source_parse.py` extracted, `parse_source()` added | 74 passed | unchanged |
| 6 | `graph_merge.py` extracted, `add_knowledge` renamed | 74 passed | unchanged |
| 7 | `ontology.py` reduced to the CLI and `main()` | 74 passed | unchanged |

Two tests were added at stage 5 for `parse_source()`, the one function that did
not exist before the refactor. Nothing else in the suite changed except import
lines pointing at the module that now owns each function.

### Deviation from the written stage order

Stage 7 lists "remove now-unused imports" as its own step. Those imports were
removed in stage 6 instead, because stage 6 is what made them unused and
committing a module full of dead imports would have been a knowingly broken
intermediate state. No behavior depends on this.

### Function renames

| Before | After |
|---|---|
| `ontology.resolve()` | `entity_lookup.identify_entity()` |
| `ontology.add_knowledge()` | `graph_merge.merge_into_graph()` |

A repository search found no caller outside `ontology.py` and the tests, so no
compatibility aliases were kept.

## Final verification

The measured run above was repeated against the finished modules and produced
identical numbers: 8 seed triples, prompts of 1053 and 1341 characters, counts
of `2, 0, 1, 1` then `1, 1, 1, 1`, a replay of `0, 2, 0, 0` adding no triples,
and 50 final triples in a 2032-byte Turtle file.

```text
.venv/bin/python -m unittest discover -s tests   -> Ran 74 tests, OK
.venv/bin/python -m compileall <all modules>     -> no errors
.venv/bin/python ontology.py --help              -> usage: ontology.py [-h] source [graph]
.venv/bin/python ontology.py /nope/absent.txt    -> Error: Source does not exist, exit 1
git diff --check                                 -> nothing
git status --short                               -> only intended files
```

No future-only module was created: `graph_skeleton.py` and
`graph_module_extract.py` do not exist.

The repository's own `ontology.ttl` was never written by the tests or by the
measurement script; both use temporary directories.

## Live LLM observation

None recorded. The user did not ask for one, and no deterministic test needs it.
