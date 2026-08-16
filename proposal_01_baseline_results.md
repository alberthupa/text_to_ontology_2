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

| Stage | Change | Tests | Behavior |
|---|---|---|---|
| 1 | Baseline tests added, no production change | 72 passed | unchanged |

Later rows are added only after each stage has actually run.

## Live LLM observation

None recorded. The user did not ask for one, and no deterministic test needs it.
