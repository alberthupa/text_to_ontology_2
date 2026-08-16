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
