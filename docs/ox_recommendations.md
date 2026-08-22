# ox_recommendations.md

Optimization recommendations for the text_to_ontology pipeline, in priority order.
Each point includes a brief implementation direction — main approach, not full design.

## 1. Repair loop instead of all-or-nothing validation gate

One bad candidate currently rejects the whole file's package. Feed validation
failures back to the LLM for a corrected answer before rejecting.

**Implementation hint:** in `ontology.py`'s loop, wrap the
`validate_candidates` → failure path in a retry (e.g. 2 attempts). On failure,
build a repair prompt from `format_validation_failure(result)` — original JSON
plus the issue list — and call `parse_source`-style `ask_llm` again. Reuse the
existing JSON contract; only the instruction block changes. Keep the hard
reject as the final fallback.


## Albert's note
deep dive on entity resolution / deduplication
first, there should be some entity index - is it here? what type of matching is there
second, there should be extracted subgraph before graph merge


## 2. Provenance on merged triples

Can't tell which source file produced a triple — blocks debugging, selective
un-merge, and safe re-runs.

**Implementation hint:** add an `ONTO`-namespace annotation property
(e.g. `prov:source`) in `graph_management.bind()`. In `graph_merge.merge_into_graph`,
attach it to every triple the merge adds (rdflib makes this awkward on plain
triples — simplest is either reification, or a parallel "assertions" graph
`{triple: source_file}` kept in memory and serialized into a small
provenance section of `ontology.ttl`, or per-source named graphs via
`rdflib.Dataset`). Keep it lightweight: one source-file URI per merged triple.

## 3. Re-run idempotency

Re-running the same file relies on graph-exact dedupe that only works with
explicit ids.

**Implementation hint:** with provenance in place (point 2), hash each source
file (sha256 of normalized text) at ingest time in `ingest_sources.read_source`,
store the hash alongside the source annotation, and skip files whose hash is
already present. A `--force` CLI flag in `ontology.py` re-processes anyway.

## 4. Cache the derived views

Views are rebuilt from the full graph per file, but the skeleton depends only
on the schema partition, which rarely changes between merges.

**Implementation hint:** in `task_context.build_task_context`, cache
`create_graph_skeleton(schema)` keyed on a cheap schema fingerprint
(e.g. `hash(sorted(schema))` or triple count + last-modified of the merge).
Recompute `graph_patterns.observed_relationships` each file (instance data
changes often); reuse the skeleton when the fingerprint is unchanged.

## 5. Stronger entity resolution

Exact name+kind and the 0.96 spelling threshold miss paraphrases
("US" vs "United States") and risk false merges.

**Implementation hint:** shift resolution primary responsibility into the
prompt: the context block already lists existing entities with ids — add an
explicit instruction ("if the entity matches one of these, set existing_id")
and treat the LLM's `existing_id` as the first resolution signal (it already
is in `entity_lookup.identify_entity`, step ①). Keep string matching as
fallback only. Later, embeddings over `entity_catalog` descriptions slot in
as a middle tier — `identify_entity`'s signature already takes a catalog,
so an embedding-similarity pass is a local change.

## 6. Chunk long sources

The fixed source-side budget means long files are effectively truncated —
their later content is never processed.

**Implementation hint:** in `ontology.py` (or a small helper next to
`ingest_sources`), split text exceeding the source budget into overlapping
chunks (paragraph boundaries, ~10% overlap) and run the existing loop body
per chunk. No changes needed downstream — each chunk is just "a source text".
Track chunk index in the provenance annotation (point 2).

## 7. Typed facts

Dates and numbers are plain string literals — no datatypes, no normalization.

**Implementation hint:** in `candidate_validation` normalization, detect
ISO-date-shaped values (`datetime.date.fromisoformat` try/except) and numeric
values; on success, emit `Literal(value, datatype=XSD.date / XSD.decimal)`.
Declare corresponding `rdfs:range` on auto-created `fact:*` properties in
`graph_merge` so the skeleton reflects the typing.

## 8. Enforce the SHACL shape

A shape is seeded but never validated against after merges.

**Implementation hint:** add `pyshacl` as a dependency. After
`merge_into_graph` and before `save_graph`, run `pyshacl.validate` on the
graph (or on the candidate subgraph against the full one) and treat
conformance failure like a validation-gate failure (report + skip save).
Cache the `DataGraph` shape parse so it isn't re-read per file.

## 9. Smaller improvements

- **Real tokenizer:** swap `prompt_budget.estimate_tokens` to tiktoken
  (`cl100k_base`); the counter is already injectable — just change the default.
- **`--dry-run` flag:** in `ontology.py`, run through validation and print
  `format_validation_failure`-style summary of would-be merges, skip
  `merge_into_graph`/`save_graph`.
- **Parallel extraction:** with per-source provenance, extraction (LLM calls)
  for independent files can run concurrently (`concurrent.futures`), with
  merges applied sequentially in file order to keep resolution deterministic.

---

**If only two:** the repair loop (#1) fixes the most likely runtime failure
mode; provenance (#2) unlocks traceability, idempotency (#3), and safe
iteration on everything else.
