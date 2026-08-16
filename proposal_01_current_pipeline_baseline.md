# Proposal 01: Baseline and Behavior-Preserving Modularization

## Status

This document is the implementation handoff for Proposal 1. It describes exactly
how to characterize the current program and reorganize it into small,
process-oriented modules without changing its observable behavior.

Work must proceed one small step at a time. The user must be shown the result of
each step before the next architectural or behavioral decision is made.

## Goal

Proposal 1 has two ordered outcomes:

1. Establish a small, reproducible description of how the program behaves now.
2. Move the existing behavior into modules whose names describe their roles in
   the processing pipeline.

The refactor is preparation for later work. It is not the implementation of the
semantic skeleton, graph-module extraction, semantic entity search, threshold
policy, or human review.

## Guiding rules

The implementing agent must follow these rules throughout the work:

1. Preserve current behavior unless this document explicitly says otherwise.
2. Do not silently fix questionable behavior during the refactor.
3. Do not introduce a framework, plugin system, dependency-injection system,
   abstract base classes, or generic service layer.
4. Do not create generic modules such as `utils.py`, `helpers.py`, `common.py`,
   or `models.py`.
5. Give every module one role in the processing pipeline.
6. Keep `ontology.py` as the executable entry point with `main()` as the visible
   orchestration function.
7. Prefer small functions and explicit arguments over classes unless a class is
   clearly necessary.
8. Do not create empty modules for future functionality.
9. Use the standard library and the existing `rdflib` dependency. Do not add a
   dependency merely to perform this refactor.
10. Inspect `git status` before editing or staging. Preserve unrelated user work
    and stage files explicitly.
11. After every move, run the relevant tests before moving another
    responsibility.
12. If preserving behavior conflicts with a proposed module boundary, stop and
    explain the conflict instead of making an implicit design decision.

## Approved decisions

The following decisions have already been discussed and approved:

- Module names should describe what happens in the process.
- Source discovery and reading belong in `ingest_sources.py`.
- Parsing ingested text belongs in `source_parse.py`.
- Identifying whether parsed entities already exist belongs in
  `entity_lookup.py`.
- Applying new or additional knowledge belongs in `graph_merge.py`.
- Graph creation, opening, initialization, binding, and saving belong in
  `graph_management.py`.
- LLM transport remains in `llm.py`.
- `ontology.py` retains the CLI and main orchestration function.
- The first modularization preserves the current entity-resolution behavior.
- Entity resolution will become more sophisticated later. The intended future
  progression is semantic lookup, then LLM-assisted lookup, then human decision,
  controlled by confidence thresholds.
- Threshold values and the exact future review workflow are not decided in this
  proposal.
- The semantic skeleton will later belong in `graph_skeleton.py`.
- Focused module extraction will later belong in
  `graph_module_extract.py`.
- Future-only modules must be documented now but not created until their
  functionality is implemented.

## Current program

The current executable code is split between two files:

- `ontology.py` contains graph lifecycle, source ingestion, prompt construction,
  entity lookup, graph mutation, and CLI orchestration.
- `llm.py` contains environment loading, model selection, the HTTP request, and
  JSON response decoding.

The current `ontology.py` responsibilities are:

| Current item | Current responsibility |
|---|---|
| Namespace constants | Define the ontology, entity, class, relation, and fact namespaces |
| `TEXT_FILES` | Define extensions accepted during directory traversal |
| `bind()` | Bind RDF prefixes |
| `open_graph()` | Load an existing graph or initialize a new one |
| `slug()` | Convert a name into a URI-safe local identifier |
| `label()` | Turn code-like property or class names into readable labels |
| `identity_key()` | Normalize names for entity comparison |
| `entity_catalog()` | Read current entity identifiers, names, kinds, and descriptions |
| `make_prompt()` | Build the source-parsing prompt |
| `resolve()` | Resolve one parsed entity to an existing graph URI |
| `new_entity_uri()` | Allocate a unique URI for a new entity |
| `add_knowledge()` | Add entities, relations, and facts to the graph |
| `find_text_files()` | Discover accepted source files |
| `main()` | Parse CLI arguments and orchestrate the run |

## Current end-to-end behavior

For each run, the program currently performs the following sequence:

1. Parse the source path and optional graph path from the command line.
2. Open the Turtle graph if it exists.
3. Otherwise, create a graph containing the base ontology declarations and the
   minimal SHACL preferred-label shape.
4. Resolve the source path into one directly supplied file or a sorted recursive
   list of supported files.
5. Exclude the output graph from directory ingestion.
6. Read each file as UTF-8 and replace invalid characters.
7. Skip parsing when the source text is empty or whitespace-only.
8. Build a prompt containing the source text, the full current entity catalog,
   and the labels of all current object and datatype properties.
9. Ask the configured LLM to return entities, relations, and literal facts.
10. Process returned entities in their returned order.
11. For each returned entity, try to identify an existing graph entity.
12. Create a new entity when lookup returns no existing URI.
13. Immediately add each processed entity to the graph before processing the
    next returned entity.
14. Add relations and literal facts whose local endpoints are valid.
15. Serialize the complete graph after every processed source file.

The ordering in steps 10 through 13 matters. A later entity in the same LLM
response can see an entity that was added earlier in that response. The first
refactor must not accidentally replace this with an all-at-once lookup phase.

## Current entity lookup behavior

The current lookup behavior must be captured and preserved exactly during this
proposal.

### Catalog membership

Only graph subjects with this triple are included in the catalog:

```text
?entity rdf:type onto:Entity
```

A resource that is only an `owl:NamedIndividual`, `skos:Concept`, or instance of
a domain class is not included unless it is also explicitly an `onto:Entity`.

### Catalog fields

For each catalog entity, the program includes:

- URI as `id`;
- all `skos:prefLabel` and `skos:altLabel` values as `names`;
- the first `onto:kind` value as `kind`;
- the first `rdfs:comment` value as `description`.

### Match order

For each parsed entity, the current algorithm uses this order:

1. Accept the LLM-returned `existing_id` when it is an exact identifier present
   in the current entity catalog.
2. Otherwise compare the parsed preferred name and parsed aliases with catalog
   names after normalization.
3. An exact normalized name or alias match is accepted only when the normalized
   parsed kind equals the normalized catalog kind and exactly one catalog entity
   matches.
4. Otherwise attempt close spelling comparison of the parsed preferred name
   against catalog names, again requiring the same normalized kind.
5. Accept a close match only when its similarity is at least `0.96` and it is
   uniquely better than the next candidate.
6. Return no match otherwise.

Do not reorder, broaden, narrow, or reinterpret these rules in Proposal 1.

### Existing SKOS support

The current local lookup already searches both `skos:prefLabel` and
`skos:altLabel`. Preserve this. Do not claim that alias lookup is a new feature
of the modularization.

### Current LLM authority

Today, a valid `existing_id` selected by the LLM is accepted before local name
matching. Preserve that behavior for now, even though the future pipeline will
be different.

## Current graph merge behavior

The current merge behavior must also remain unchanged:

- A parsed entity without a valid local `id` or `name` is skipped.
- A new URI is generated from the preferred name and receives a numeric suffix
  if that URI is already used as a subject.
- Every processed entity is typed as `onto:Entity`, `owl:NamedIndividual`,
  `skos:Concept`, and its generated domain class.
- A generated domain class is typed as `owl:Class`, is a subclass of
  `onto:Entity`, and receives an `rdfs:label`.
- A missing kind becomes the label `Entity`.
- The first preferred name becomes both `skos:prefLabel` and `rdfs:label`.
- A different later preferred name becomes `skos:altLabel`.
- Parsed aliases are added as `skos:altLabel` values.
- A parsed description is added only when the entity has no existing
  `rdfs:comment`; existing descriptions are not overwritten.
- An object-property URI is generated from the parsed relation name.
- A datatype-property URI is generated from the parsed fact name.
- Property labels are created from their parsed names.
- A relation is added only when both endpoints refer to returned entity-local
  identifiers that were successfully processed.
- A fact is added only when its subject refers to a successfully processed
  entity-local identifier and its value is not `None`.
- Exact duplicate triples remain a single RDF triple.
- Relation and fact counts report only newly added relation or fact triples.
- The return value remains the four counts: new entities, resolved entities,
  new relations, and new facts.

Proposal 1 must not add conflict resolution, provenance, replacement rules,
validation stages, or human review.

## Target module organization

### Process overview

The current source-to-graph path should become:

```text
ontology.py
  -> ingest_sources.py
  -> source_parse.py
  -> entity_lookup.py
  -> graph_merge.py
  -> graph_management.py
```

This diagram describes responsibility, not necessarily one call per module. In
particular, `graph_merge.py` must call entity lookup once per entity during the
current behavior-preserving implementation so that sequential visibility is not
lost.

### `ontology.py`

Purpose: expose the CLI and make the processing sequence visible in one place.

It should contain:

- `main()`;
- command-line argument definition;
- user-facing progress and summary printing;
- timing of the LLM operation;
- top-level conversion of expected runtime and OS errors into the existing CLI
  error format.

It should call other modules to do actual work.

It should not contain:

- RDF namespace definitions;
- RDF triple construction;
- source-extension rules;
- recursive file discovery;
- prompt text;
- entity matching logic;
- URI slugging;
- graph merge rules;
- HTTP request construction.

The user-facing command must remain:

```text
python ontology.py SOURCE [GRAPH]
```

The default graph path must remain `ontology.ttl`.

### `ingest_sources.py`

Purpose: locate and read source material before semantic parsing.

Move here:

- `TEXT_FILES`;
- `find_text_files()`;
- UTF-8 source reading with `errors="replace"`.

The module must preserve:

- direct files being accepted regardless of extension;
- directories being searched recursively;
- directory results being sorted;
- only configured text-like extensions being accepted from directories;
- the output graph being excluded;
- the existing missing-source error;
- the existing no-text-files error;
- empty or whitespace-only sources not being sent to the LLM.

The initial implementation may keep separate small functions for file discovery
and file reading. Do not invent document classes, reader registries, or format
plugins in Proposal 1.

Future expansion may add formats, chunking, source metadata, document IDs,
provenance, or OCR inside this stage. None of those features belongs in Proposal
1.

### `source_parse.py`

Purpose: turn one ingested source text into candidate entities, relations, and
literal characteristics.

Move here:

- `make_prompt()`;
- collection of current object-property and datatype-property labels for the
  prompt;
- the call that sends the completed parsing prompt through `llm.py`.

The primary entry point should be named `parse_source()`.

During Proposal 1, `parse_source()` may still receive the graph because the
current prompt is built from the full current catalog and property set. Do not
introduce the semantic skeleton or a new context-selection abstraction yet.

The parser output must preserve the current JSON-shaped data:

- `entities`;
- `relations`;
- `facts`.

Here, facts are characteristics with literal values. Do not rename the returned
field in Proposal 1 because that would change the LLM contract.

This module may ask the LLM to suggest `existing_id`, as it does now, but it must
not modify the graph. The authoritative current decision remains inside
`entity_lookup.py`.

The exact prompt wording and JSON schema should remain unchanged during the move.

### `entity_lookup.py`

Purpose: identify whether one parsed entity already exists in the current graph.

Move here:

- `identity_key()`;
- `entity_catalog()`;
- `resolve()`, renamed to `identify_entity()` if tests confirm identical
  behavior.

The primary current operation should be a single-entity lookup because
`graph_merge.py` must preserve sequential processing. Its conceptual contract is:

```text
parsed entity + current graph -> existing URI or no match
```

`identify_entity()` should build or receive the current catalog in a way that
preserves the present lookup result. Avoid caching the catalog across merges in
Proposal 1 because the graph changes after each processed entity.

This module must not:

- create a new URI;
- add or remove triples;
- decide which facts or relations should be accepted;
- call a human-review interface;
- add semantic search;
- invent threshold values.

The module boundary is the provision for future lookup complexity. The future
implementation is expected to evolve toward:

```text
semantic candidate lookup
  -> confidence threshold decision
  -> LLM-assisted lookup for uncertain candidates
  -> second confidence threshold decision
  -> human decision for unresolved or ambiguous candidates
```

That future pipeline will require richer results than `URIRef` or `None`, such as
candidate URIs, scores, decision source, and review status. Do not introduce that
result model in Proposal 1 because the scoring semantics and human workflow have
not been decided. Keeping all identity decisions behind `entity_lookup.py` is
the deliberately simple compatibility boundary for now.

### `graph_merge.py`

Purpose: merge parsed source knowledge into the current canonical graph.

Move here:

- `slug()`;
- `label()`;
- `new_entity_uri()`;
- `add_knowledge()`, renamed to `merge_into_graph()` if tests confirm identical
  behavior.

The primary entry point should be `merge_into_graph()`.

It must support both source roles:

1. Introducing new entities and relationships.
2. Adding types, aliases, descriptions, relations, or literal characteristics
   to existing entities.

For Proposal 1, it must call `entity_lookup.identify_entity()` while processing
each returned entity and immediately merge that entity before continuing to the
next one. This preserves the current within-response visibility behavior.

It must not independently implement a second lookup algorithm. All identity
matching rules belong in `entity_lookup.py`.

It must not:

- read source files;
- build prompts;
- call the LLM;
- open or save graph files;
- implement provenance or conflicts;
- extract graph skeletons or graph modules.

### `graph_management.py`

Purpose: manage the lifecycle and basic vocabulary of the canonical RDF graph.

Move here:

- `BASE`;
- `ONTO`;
- `ENTITY`;
- `CLASS`;
- `RELATION`;
- `FACT`;
- `bind()`;
- `open_graph()`.

Add one small `save_graph()` function that performs the existing Turtle
serialization. This centralizes graph persistence without changing its format or
save timing.

This module must preserve the new-graph seed exactly:

- the `owl:Ontology` declaration;
- the base `onto:Entity` class and label;
- the SHACL node shape targeting `onto:Entity`;
- the property shape requiring at least one `skos:prefLabel`.

It must not:

- merge parsed knowledge;
- look up entity identity;
- select ontology context;
- build skeletons;
- extract focused modules.

The name `graph_management.py` is intentionally limited to graph lifecycle and
basic graph vocabulary in Proposal 1. It must not become a catch-all module.

### `llm.py`

Purpose: communicate with the configured LLM.

Keep here:

- `.env` loading;
- model selection;
- HTTP request construction;
- HTTP error conversion;
- extraction of JSON from the returned message.

Parsing prompts belong in `source_parse.py`, not `llm.py`.

No behavior change is required in `llm.py` for Proposal 1.

## Future modules represented by the architecture

These modules are part of the agreed direction but must not be created as empty
files during Proposal 1.

### `graph_skeleton.py`

Future purpose: derive a compact graph containing the ontology map and
relationship map.

Expected primary entry point:

```text
create_graph_skeleton(source_graph) -> derived_graph
```

The ontology-map portion is expected to contain important classes, class
hierarchy, object properties, datatype properties, domains, ranges, labels,
definitions, and selected OWL restrictions.

The relationship-map portion is expected to contain observed
class-property-class patterns and later their usage statistics.

The function must create a derived view and must not mutate the canonical graph.
If ontology-map and relationship-map logic later become independently complex,
they may be split only after that complexity exists and is reviewed.

### `graph_module_extract.py`

Future purpose: extract a focused graph module around an already selected set of
concepts.

Expected primary entry point:

```text
extract_graph_module(source_graph, selected_concepts) -> derived_graph
```

This module will not decide which concepts are relevant. Concept selection is a
separate future behavior whose mechanism has not been chosen.

The function must return a derived view and must not mutate the canonical graph.

## Dependency direction

Keep imports simple and one-directional:

```text
ontology.py
  -> ingest_sources.py
  -> source_parse.py
  -> graph_merge.py
  -> graph_management.py
  -> llm.py

source_parse.py
  -> entity_lookup.py (for the current entity catalog)
  -> llm.py

graph_merge.py
  -> entity_lookup.py
  -> graph_management.py

entity_lookup.py
  -> graph_management.py (for the project namespace)

ingest_sources.py
  -> standard library only

graph_management.py
  -> rdflib only

llm.py
  -> standard library only
```

Avoid circular imports. If a proposed move creates a circular import, stop and
reconsider responsibility placement rather than adding delayed imports or a
generic shared module.

## Exact function movement map

The implementing agent should use this as the default movement plan:

| Existing item | Destination |
|---|---|
| `BASE`, `ONTO`, `ENTITY`, `CLASS`, `RELATION`, `FACT` | `graph_management.py` |
| `bind()` | `graph_management.py` |
| `open_graph()` | `graph_management.py` |
| serialization call | `graph_management.save_graph()` |
| `TEXT_FILES` | `ingest_sources.py` |
| `find_text_files()` | `ingest_sources.py` |
| source `read_text()` operation | `ingest_sources.py` |
| `identity_key()` | `entity_lookup.py` |
| `entity_catalog()` | `entity_lookup.py` |
| `resolve()` | `entity_lookup.identify_entity()` |
| `make_prompt()` | `source_parse.py` |
| existing-property label collection | `source_parse.py` |
| LLM call for one source | `source_parse.parse_source()` |
| `slug()` | `graph_merge.py` |
| `label()` | `graph_merge.py` |
| `new_entity_uri()` | `graph_merge.py` |
| `add_knowledge()` | `graph_merge.merge_into_graph()` |
| CLI arguments, timing, printing, loop, error handling | remain in `ontology.py` |

Function renaming and movement should happen together only when tests protect the
behavior. Do not retain compatibility aliases unless a repository search shows
an actual caller that needs them.

## Baseline before moving code

### Purpose

The baseline must make it possible to distinguish a harmless code move from an
accidental behavior change.

### Test approach

Use Python's standard-library `unittest` and `unittest.mock`. Do not add `pytest`
or another test dependency in Proposal 1.

Tests must not call OpenRouter or require an API key. Patch the LLM boundary with
a fixed response when an orchestration test needs parsed data.

Use temporary directories for generated source and Turtle files. Do not overwrite
the repository's `ontology.ttl` during tests.

Compare RDF graphs by triples or RDF graph isomorphism. Do not compare serialized
Turtle text byte-for-byte because prefix order, triple order, and blank-node IDs
are not stable semantic properties.

### Minimum baseline cases

The tests or baseline fixtures must cover at least these cases:

1. Opening a missing path creates the exact base ontology and SHACL structure.
2. Opening an existing Turtle file preserves its triples.
3. A directly supplied file is accepted even when its extension is not listed.
4. Directory ingestion is recursive, sorted, restricted to configured
   extensions, and excludes the output graph.
5. Empty input text is not sent to the LLM.
6. The prompt contains the source text, all catalog entities, and all labeled
   object and datatype properties.
7. Catalog names include both `skos:prefLabel` and `skos:altLabel`.
8. A valid LLM `existing_id` resolves to the catalog URI.
9. An exact normalized preferred-name match with the same kind resolves.
10. An exact normalized alias match with the same kind resolves.
11. A name match with a different or missing kind does not resolve through local
    exact matching.
12. A unique close spelling at or above `0.96` with the same kind resolves.
13. An ambiguous close match does not resolve.
14. An unmatched candidate creates a new entity with all current types and
    labels.
15. A candidate resolved to an existing entity can add aliases, a missing
    description, relations, and literal facts.
16. An existing description is not overwritten.
17. A later different preferred name is added as an alternate label.
18. Invalid entity records and invalid relation or fact endpoints are skipped as
    they are today.
19. Exact duplicate relation and fact triples are not counted as new on the
    second merge.
20. Two matching candidates in one parsed response preserve current sequential
    visibility: the first may create an entity and the later one may resolve to
    it.
21. Processing multiple files remains sequential, and the graph saved after one
    file becomes context for the next.
22. The four reported merge counts retain their current meaning and order.

### Manual baseline note

Create a concise `proposal_01_baseline_results.md` only after the baseline has
actually been run. Do not pre-fill results.

It should record:

- test or fixture inputs;
- graph triple counts before and after;
- entity-catalog size;
- prompt character count;
- new and resolved entity counts;
- new relation and fact counts;
- observed duplicate, ambiguity, or conflict behavior;
- commands used for verification.

One optional live LLM observation may be recorded if the user explicitly asks
for it and credentials are available. It must not be required for deterministic
tests.

## Implementation sequence

Do not move all functions at once. Complete these stages in order.

### Stage 0: Repository safety check

1. Confirm the branch is the Proposal 1 branch.
2. Run `git status --short`.
3. Identify unrelated modified or untracked files.
4. Do not edit, stage, delete, move, or commit unrelated files.
5. Read `ontology.py`, `llm.py`, `README.md`, and this proposal before acting.
6. Search the repository for imports and callers of every function that will be
   moved.

Stop and ask the user if unrelated work overlaps a file required by the current
stage.

### Stage 1: Capture current behavior

1. Add the minimal deterministic baseline tests described above while functions
   still live in `ontology.py`.
2. Keep test fixtures tiny and purpose-specific.
3. Patch LLM calls; do not use the network.
4. Run the tests against the untouched implementation.
5. If a proposed expectation differs from actual current behavior, record the
   actual behavior and ask the user whether it should be preserved. Do not treat
   the refactor as permission to fix it.
6. Produce the baseline-results note from actual observations.
7. Show the user the results before moving production functions.

### Stage 2: Extract graph management

1. Create `graph_management.py`.
2. Move namespaces, prefix binding, and graph opening/initialization without
   rewriting their bodies unnecessarily.
3. Add the small `save_graph()` wrapper around the existing Turtle serialization.
4. Update imports in `ontology.py`.
5. Run graph initialization, load, save, and full baseline tests.
6. Confirm that new and existing graphs are semantically identical to baseline
   results.
7. Show the user the diff and results before proceeding.

### Stage 3: Extract source ingestion

1. Create `ingest_sources.py`.
2. Move extension configuration and file discovery.
3. Move source reading into a plainly named small function in this module.
4. Keep printing and orchestration in `ontology.py`.
5. Preserve direct-file, recursive-directory, sorting, graph exclusion,
   encoding, and empty-source behavior.
6. Run ingestion and full baseline tests.
7. Show the user the diff and results before proceeding.

### Stage 4: Extract entity lookup

1. Create `entity_lookup.py`.
2. Move name normalization and catalog construction.
3. Move `resolve()` and rename it to `identify_entity()` only with tests in
   place.
4. Preserve the exact catalog membership, fields, match order, kind requirement,
   similarity threshold, and ambiguity behavior.
5. Do not cache the catalog across graph mutations.
6. Do not add semantic lookup, confidence objects, thresholds, or human review.
7. Run all identity and full baseline tests.
8. Show the user the diff and results before proceeding.

### Stage 5: Extract source parsing

1. Create `source_parse.py`.
2. Move the prompt unchanged.
3. Move property-label collection.
4. Add `parse_source()` as the small entry point that builds the prompt and uses
   `llm.ask_llm()`.
5. Continue using `entity_lookup.entity_catalog()` for the existing prompt
   context.
6. Keep model/timing progress messages in `ontology.py` unless moving them can be
   shown not to blur module responsibility.
7. Run prompt and full baseline tests.
8. Show the user the diff and results before proceeding.

### Stage 6: Extract graph merge

1. Create `graph_merge.py`.
2. Move slugging, display-label conversion, and new-URI allocation.
3. Move `add_knowledge()` and rename it to `merge_into_graph()` with tests in
   place.
4. Call `entity_lookup.identify_entity()` for each entity while iterating.
5. Merge each entity immediately before looking up the next entity.
6. Preserve all triples, skip rules, non-overwrite rules, and counts.
7. Do not add a candidate graph, validation layer, provenance layer, or conflict
   policy.
8. Run merge and full baseline tests.
9. Show the user the diff and results before proceeding.

### Stage 7: Simplify the orchestrator

1. Remove moved definitions and now-unused imports from `ontology.py`.
2. Keep `main()` readable from top to bottom as the pipeline description.
3. Ensure `main()` opens the graph, gets sources, parses each non-empty source,
   merges parsed results, saves after each file, and reports final counts.
4. Preserve CLI arguments, defaults, messages, error handling, and exit behavior.
5. Avoid wrapping the flow in an application class or controller object.
6. Run the complete baseline suite and CLI help command.
7. Show the user the final orchestrator before documentation cleanup.

### Stage 8: Documentation and final verification

1. Update the README file list and workflow description to match the real files.
2. Complete `proposal_01_baseline_results.md` using actual final verification
   results.
3. Confirm that no future-only empty modules were created.
4. Run the full deterministic tests.
5. Run Python syntax or compilation checks for all modules.
6. Run `git diff --check`.
7. Inspect `git status --short` and confirm unrelated user files remain
   untouched.
8. Compare the final behavior with the baseline rather than merely confirming
   that the program runs.

## Verification after every stage

At every stage, the implementing agent must report:

- files added or changed;
- functions moved or renamed;
- whether any executable behavior changed;
- exact test command;
- test result;
- any observed discrepancy;
- unrelated worktree files intentionally left untouched.

The minimum recurring checks are:

```text
python -m unittest discover -s tests
python ontology.py --help
git diff --check
git status --short
```

If the environment uses a virtual environment, use its Python executable without
changing project dependencies.

## Git and commit discipline

The agent must keep changes reviewable:

1. Never use `git add -A` or `git add .` when unrelated work is present.
2. Stage explicit files only.
3. Do not commit a stage until its relevant tests pass and the user has reviewed
   any decision or discrepancy raised by that stage.
4. Keep baseline tests separate from mechanical module moves when practical.
5. Use commit messages that state the process responsibility, for example:
   - `test: capture current ontology pipeline behavior`
   - `refactor: extract graph management`
   - `refactor: extract source ingestion`
   - `refactor: extract entity lookup`
   - `refactor: extract source parsing`
   - `refactor: extract graph merge`
   - `docs: record proposal 1 baseline results`
6. Do not squash or rewrite user-reviewed commits unless the user explicitly
   asks.

## Decision and review gates

The implementing agent must stop for user input when:

- a test reveals behavior not described here;
- preserving current behavior would require an awkward or circular dependency;
- a function appears to belong in more than one approved module;
- a rename would affect an external caller;
- a new dependency appears necessary;
- a module needs a generic shared abstraction;
- lookup behavior would change, even if the change appears to be an improvement;
- source parsing output or prompt wording would change;
- CLI output, save timing, or error behavior would change;
- unrelated user changes overlap required files;
- threshold values, semantic search, LLM adjudication, or human review would need
  to be designed.

When stopping, the agent should explain the observed evidence, give the smallest
set of alternatives, recommend one, and wait for the user's decision.

## Explicitly out of scope

Proposal 1 does not:

- split the TBox and ABox;
- create the semantic skeleton;
- create the ontology map or empirical relationship map;
- extract locality-based or other focused ontology modules;
- select relevant concepts for module extraction;
- reduce the entity context sent to the LLM;
- add semantic or embedding-based entity lookup;
- add lookup confidence thresholds;
- add a new LLM identity-adjudication step;
- add a human-review queue or interface;
- change the authority of the current LLM-provided `existing_id`;
- add provenance;
- introduce conflict resolution;
- introduce a candidate graph or validation stage;
- change SHACL rules;
- change the RDF vocabulary or URI scheme;
- change the prompt schema;
- change the CLI;
- add future-facing empty files.

## Completion criteria

Proposal 1 is complete only when all of the following are true:

- Current behavior is represented by deterministic baseline tests.
- Actual baseline observations are recorded.
- `ontology.py` contains the CLI and a readable `main()` orchestration flow.
- Source ingestion lives in `ingest_sources.py`.
- Source parsing lives in `source_parse.py`.
- Entity identification lives in `entity_lookup.py`.
- Graph mutation for parsed knowledge lives in `graph_merge.py`.
- Graph lifecycle and namespace management live in `graph_management.py`.
- LLM transport remains in `llm.py`.
- Current entity matching, including SKOS aliases and the `0.96` spelling rule,
  behaves as it did before the refactor.
- New entities and enrichment of existing entities behave as before.
- Within-response sequential visibility is preserved.
- CLI behavior and save timing are preserved.
- No semantic skeleton, focused graph-module extraction, semantic search,
  thresholds, or human-review behavior has been implemented prematurely.
- Tests pass without network access.
- Documentation matches the resulting code.
- Unrelated user work remains untouched.

At that point the code will have explicit process boundaries, and later work can
change one behavior at a time without reopening the entire pipeline.
