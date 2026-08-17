# Proposal 05: Task-Specific Ontology Context Selection, Rendering, and Budgeting

## General purpose

Build a read-only Phase 5 pipeline that selects a small, relevant semantic view
of the current RDF graph for each source text and places that view in the LLM
extraction prompt.

The selected view must combine three different kinds of information without
confusing their semantics:

1. declared ontology structure selected from the semantic skeleton;
2. observed class-property-range usage selected from empirical patterns;
3. relevant current resources and representative assertions selected from the
   instance graph.

The result must be rendered in compact language that an LLM can understand and
must fit a configurable prompt budget. The complete ontology, complete entity
catalog, complete skeleton, and complete empirical pattern table must not be
sent automatically.

This proposal implements step 5 of
[`ontology_context_and_merge_plan.md`](ontology_context_and_merge_plan.md). It
does not validate or merge extracted candidates; those remain later phases.

## Status and checklist convention

This document is an independent implementation handoff. Phases 5A, 5B, 5C, and 5D
are implemented; each phase's implementation record below holds its actual files,
commands, and measurements.

Master status:

- [x] Phase 5A — compose the existing derived ontology views and define shared
  contracts.
- [x] Phase 5B — extract source concepts and select a task-specific context
  package.
- [x] Phase 5C — render LLM-friendly context and enforce the prompt budget.
- [x] Phase 5D — integrate the bounded context into the active extraction
  pipeline.

Every unchecked item is required unless it is explicitly marked optional. The
implementing agent should change `[ ]` to `[x]` only after the item is
implemented and its stated verification passes. A partially implemented item
must remain unchecked and be described in that phase's implementation record.

Each phase contains an implementation record. Fill it in before declaring the
phase complete:

```text
Implementation record
- Status: not started | in progress | complete | blocked
- Files added:
- Files changed:
- Tests added or changed:
- Commands run:
- Measured results:
- Decisions or deviations:
```

## Intended end-to-end flow

For each non-empty source file, the eventual active pipeline should perform this
flow:

```text
current RDF graph (read only during context construction)
  |
  `-> build ontology views
        |-> schema graph
        |-> instance graph
        |-> support/remainder graph
        |-> semantic skeleton          [declared structure]
        `-> empirical patterns         [observed usage]

source text
  `-> extract source concepts          [source-only signals]

source text + concepts + ontology views
  `-> match resources
      -> create direct seeds
      -> bounded structural expansion
      -> rank semantic candidates
      -> build ContextPackage
      -> render atomic LLM-friendly items
      -> pack complete items into the prompt budget
      -> assemble one prompt-context block
      -> ask the extraction LLM
      -> merge returned candidates using the existing full-graph merge path
```

Context construction must finish before the LLM call and must not mutate the
graph. After extraction, the existing merge and per-file save behavior remains
unchanged. Because the graph changes after each successful file, ontology views
must be refreshed for the next file unless a future cache has an explicit and
tested invalidation policy.

## Phase boundary

Phase 5 answers:

- What concepts or mentions characterize the current source text?
- Which declared classes, properties, hierarchy statements, definitions, and
  supported restrictions are relevant to those concepts?
- Which observed class-property-range patterns are relevant?
- Which existing resources or assertions are useful for identity resolution or
  as representative examples?
- How should selected information be translated into LLM-friendly text?
- Which complete context items fit into the configured prompt budget?
- How does the selected context replace the current global entity and property
  context in the prompt?

Phase 5 does not answer:

- whether returned candidate knowledge is structurally valid;
- whether an extracted claim conflicts with the canonical graph;
- whether a candidate should be accepted, rejected, or reviewed;
- how provenance or extraction confidence should be persisted;
- how identities should be resolved beyond the current merge behavior;
- how long source documents should be chunked;
- whether a locality-based OWL module extractor is needed;
- whether an LLM, embedding model, or external NLP dependency should be added.

There is no Phase 5E in this proposal. LLM quality evaluation is explicitly not
part of the current implementation plan.

## Existing code that must be reused

Before changing code, inspect the current implementations and tests. Phase 5
must build on these public operations rather than duplicating them:

| Existing module | Public operation | Phase 5 use |
|---|---|---|
| `graph_partition.py` | `partition_graph(source_graph)` | Derive current schema, instance, and support views |
| `graph_skeleton.py` | `create_graph_skeleton(schema_graph)` | Produce the declared structural search space |
| `graph_patterns.py` | `observed_relationships(schema_graph, instance_graph)` | Produce observed usage records |
| `entity_lookup.py` | `entity_catalog(graph)` | Reuse current project-native identity cards where applicable |
| `source_parse.py` | `make_prompt(...)`, `parse_source(...)` | Replace global prompt context only in Phase 5D |
| `graph_merge.py` | `merge_into_graph(graph, data)` | Preserve the current full-graph merge path |
| `ontology.py` | `main()` | Keep visible orchestration small and sequential |

Important limitations must be respected:

- `entity_catalog()` contains only resources explicitly typed as
  `onto:Entity`. It is useful for the project's native entities but is not a
  complete generic RDF individual index.
- The graph supplied by the user may contain declared `rdfs:domain` and
  `rdfs:range`, no declared domains or ranges, or a mixture of declared schema
  and empirical usage.
- `graph_skeleton.py` supports an explicit subset of RDF/OWL structure. Phase 5
  consumes that subset; it must not silently expand its semantics.
- `graph_patterns.py` returns observations. Those records must never be turned
  into declared schema statements by context selection or rendering.
- The current extraction JSON contract and local entity-resolution behavior
  remain protected.

## Approved architectural decisions

These decisions are part of the requested design and are not open implementation
questions:

1. Keep `graph_skeleton.py` and `graph_patterns.py` as separate implementation
   modules because declared structure and observed usage have different
   semantics.
2. Add one composition façade, proposed as `ontology_views.py`, so later code
   can consume both results as one group of ontology views.
3. Add a source-only concept extraction module, proposed as
   `source_concepts.py`.
4. Add a task-specific selector, proposed as `task_context.py`.
5. Add an LLM-friendly renderer, proposed as `context_render.py`.
6. Add a prompt-budget module, proposed as `prompt_budget.py`.
7. Start with deterministic lexical source analysis and matching. Do not make a
   second LLM call in this proposal.
8. Preserve a stable source-concept contract so classical NLP, embeddings, NER,
   or a small language model can be introduced later without changing context
   selection's input shape.
9. Do not introduce a provider registry, plugin framework, abstract class
   hierarchy, or dependency-injection framework.
10. The context package may contain an RDF graph plus plain records. It is not
    required to be one RDF graph because empirical patterns are not asserted
    ontology triples.
11. Render declared structure and observed usage in visibly separate prompt
    sections.
12. Apply budget limits to complete semantic items. Never trim context by
    slicing the final string in the middle of a URI, entity card, relation,
    pattern, or OWL restriction.
13. The selected prompt catalog replaces the global prompt catalog only after
    Phases 5A through 5C are complete and verified.
14. Local merge-time entity lookup continues to use the full current graph. A
    resource omitted from the prompt is not removed from local resolution.
15. Context construction is read only. No selected view, score, or diagnostic
    is written into the canonical graph.
16. No new runtime dependency is approved for this proposal. Use the standard
    library and the existing `rdflib` dependency.
17. No LLM evaluation phase is included.

## Target module organization

### `ontology_views.py`

Purpose: compose the existing partition, skeleton, and empirical-pattern
operations behind one read-only entry point.

Recommended public operation:

```text
build_ontology_views(source_graph) -> OntologyViews record
```

Recommended plain-record shape:

```text
{
  "schema": Graph,
  "instance": Graph,
  "support": Graph,
  "skeleton": Graph,
  "patterns": list[dict]
}
```

It should call the existing functions directly:

```text
schema, instance, support = partition_graph(source_graph)
skeleton = create_graph_skeleton(schema)
patterns = observed_relationships(schema, instance)
```

It must not perform task matching, ranking, rendering, budgeting, persistence,
or graph mutation.

### `source_concepts.py`

Purpose: derive deterministic, source-only signals that describe what one text
mentions or emphasizes.

Recommended public operation:

```text
extract_source_concepts(text) -> list[ConceptRecord]
```

Recommended plain-record fields:

```text
{
  "text": original or display form,
  "normalized": normalized matching form,
  "kind": "mention" | "phrase" | "keyword",
  "weight": deterministic numeric priority,
  "origin": "heading" | "capitalized-span" | "frequency" | other explicit origin,
  "position": first source position used for deterministic tie-breaking
}
```

The records must not contain ontology URIs. This module has no RDF dependency
and must not inspect the ontology.

The first implementation should be deliberately modest: normalized source
terms, bounded short phrases, capitalized spans where applicable, and simple
frequency or source-position weighting. It must not claim semantic entity types
or perform opaque language-model inference.

### `task_context.py`

Purpose: align one source with the ontology views, perform bounded expansion,
rank relevant semantic material, and create a structured `ContextPackage`.

Recommended public operations:

```text
select_task_context(text, concepts, ontology_views,
                    native_entities=None, limits=None)
    -> ContextPackage

build_task_context(text, source_graph, limits=None)
    -> ContextPackage
```

`select_task_context()` is the independently testable selector.
`build_task_context()` is the small composition entry point that obtains views
and concepts, obtains the current project-native catalog with
`entity_catalog(source_graph)`, and then delegates to the selector.
`build_task_context()` returns selection results only. It does not render or
budget prompt text.

Recommended `ContextPackage` shape:

```text
{
  "concepts": list[ConceptRecord],
  "schema": list[SemanticItem],
  "patterns": list[SemanticItem],
  "resources": list[SemanticItem],
  "examples": list[SemanticItem],
  "diagnostics": {
    "matches": list[MatchRecord],
    "candidate_counts": dict,
    "selected_counts": dict,
    "limits": dict
  }
}
```

The exact internal representation may be adjusted before Phase 5B production
code, but it must remain a small explicit record rather than a framework. Any
change must be recorded in the phase implementation record and reflected in
tests.

Each semantic item should retain enough metadata to explain and order it:

```text
{
  "id": stable identifier within this package,
  "kind": "class" | "property" | "restriction" | "pattern" |
          "resource" | "example",
  "value": RDF term, triple bundle, or pattern record,
  "priority": deterministic sortable priority,
  "reason": direct label match, alias match, connected pattern, hierarchy hop, etc.,
  "direct": true | false
}
```

### `context_render.py`

Purpose: translate the selected context package into compact, unambiguous,
LLM-friendly atomic items and assemble selected items into one context block.

Recommended public operations:

```text
render_context_items(context_package, namespace_manager=None)
    -> list[RenderedItem]

assemble_context(rendered_items) -> str

prepare_prompt_context(context_package, budget_config,
                       count_tokens=estimate_tokens)
    -> PromptContextResult
```

Recommended rendered-item shape:

```text
{
  "id": stable identifier,
  "section": "declared" | "observed" | "resources" | "examples",
  "priority": deterministic sortable priority,
  "text": complete standalone text block,
  "dependencies": list[stable identifier]
}
```

The renderer must preserve the distinction between:

- declared class/property structure;
- observed patterns and their evidence;
- existing resources and exact identifiers;
- representative assertions.

`prepare_prompt_context()` is the explicit Phase 5C composition operation. It
renders atomic items, asks `prompt_budget.py` to fit them, assembles only the
selected items, and returns both final text and budget diagnostics. It must not
perform relevance selection.

Recommended result shape:

```text
{
  "text": str,
  "budget": BudgetResult
}
```

### `prompt_budget.py`

Purpose: estimate or count tokens, calculate the context allowance, and select
the highest-priority complete rendered items that fit.

Recommended public operations:

```text
estimate_tokens(text, chars_per_token=3) -> int

context_allowance(total_limit, fixed_prompt_tokens, source_tokens,
                  output_reserve, safety_margin) -> int

fit_context_items(rendered_items, token_budget, count_tokens=estimate_tokens)
    -> BudgetResult
```

Recommended budget-result shape:

```text
{
  "items": list[RenderedItem],
  "used_tokens": int,
  "budget_tokens": int,
  "dropped_ids": list[str],
  "item_costs": dict[str, int],
  "estimator": descriptive string
}
```

The token counter must be replaceable by passing a callable. This is the future
extension point for an exact model tokenizer or a small local model's tokenizer.
No tokenizer dependency is added now.

### Existing `source_parse.py`

Purpose after Phase 5D: insert the already selected and budgeted context text
into the extraction prompt and call `ask_llm()`.

The prompt builder must stop discovering global graph context itself. It should
receive source text and task-context text explicitly. The extraction response
shape remains unchanged.

### Existing `ontology.py`

Keep `main()` as visible orchestration. The final code should read as a small
process, conceptually:

```text
text = read_source(path)
context = build_task_context(text, graph, selection_limits)
prompt_context = prepare_prompt_context(context, budget_config)
extraction = parse_source(text, prompt_context["text"])
counts = merge_into_graph(graph, extraction)
save_graph(graph, path)
```

Do not expose partition, skeleton traversal, match scoring, item rendering, or
packing internals in `main()`.

## Shared semantic rules

### Declared and observed information

The prompt must not collapse declared schema and observed usage into one claim.

Examples:

```text
[declared] sold in market: domain Product; range Market
[observed] Product --sold in market--> Market; occurrences=123
```

If declared and observed shapes disagree, include both when both are relevant
and fit. Do not choose a winner, modify either source, or describe the observed
shape as a rule.

### Generic RDF resources

Task context must not assume every useful individual is typed `onto:Entity`.
Generic resource candidates may be discovered from the partitioned instance
graph when they have an individual role, including resources typed as a known
class, `owl:NamedIndividual`, or `skos:Concept` according to the existing
partition policy.

Use available labels and descriptions from the vocabularies already recognized
by the project, including `rdfs:label`, `rdfs:comment`, `skos:prefLabel`,
`skos:altLabel`, and `skos:definition`. Use a compact URI or full URI as a
fallback when no label exists.

For resources returned by `entity_catalog()`, preserve its exact `id`, names,
kind, and description so the extraction LLM can return a valid `existing_id`.
For generic resources outside that catalog, include their URI for context but
do not promise that the current merge-time `existing_id` mechanism can resolve
them without a later entity-resolution change.

### Initial matching priority

Use deterministic priority tiers before considering a complex weighted score:

1. exact source occurrence of an existing resource name or alias;
2. exact source occurrence of a class or property label;
3. exact match between an extracted concept and a label, alias, or URI local
   name;
4. strong normalized token overlap with a definition or description;
5. schema dependencies of directly matched resources;
6. patterns connected to directly matched classes or properties;
7. one-hop neighboring resources or representative examples;
8. weaker indirect material.

Task relevance must outrank raw empirical frequency. Occurrence count,
coverage, and cardinality may break ties between equally relevant patterns, but
must not make an unrelated common pattern outrank a direct task match.

All ties must have deterministic fallbacks, ultimately using stable string
forms such as URI and item ID.

### Initial bounded expansion

Version one uses bounded traversal, not formal OWL locality extraction.

From directly selected classes:

- include the class declaration and supported annotations;
- include directly connected parent and child classes up to one configured
  hierarchy hop;
- include relevant properties whose declared domain or range is the class;
- include the opposite named domain/range endpoint needed to understand such a
  property;
- include complete supported restrictions attached to that class;
- include empirical patterns whose subject class or class-valued range is the
  selected class.

From directly selected properties:

- include the property declaration and annotations;
- include declared domain and range statements where present;
- include named endpoint declarations needed to understand them;
- include matching empirical patterns.

From directly selected resources:

- include identity annotations and explicit types;
- seed the relevant type classes;
- consider one-hop instance assertions only when their predicate is selected,
  their other endpoint is directly selected, or the assertion receives another
  explicit relevance reason;
- do not add all neighbors of a high-degree resource.

Expansion must use visited sets and explicit caps. Cycles must terminate, and
one selected generic superclass must not cause the complete ontology to be
included.

### Prompt representation

The intended human-readable structure is:

```text
RELEVANT DECLARED ONTOLOGY
- [class] Policy is a kind of Entity.
- [object property] waives sanctions on: Policy -> Location.

OBSERVED USAGE — EVIDENCE, NOT AN ONTOLOGY RULE
- Policy --waives sanctions on--> Location
  occurrences=1; subjects=1/1; cardinality=1/1/1

RELEVANT EXISTING RESOURCES
- name: temporary US sanctions waiver on Russian oil
  id: http://example.org/text-ontology/entity/...
  type: Policy
  aliases: US sanctions waiver

REPRESENTATIVE CURRENT ASSERTIONS
- temporary US sanctions waiver --waives sanctions on--> Russia
```

This is illustrative wording, not an instruction to hardcode those resources.
The renderer should favor compact, line-oriented records over Turtle dumps or
large JSON documents.

Do not send source-concept diagnostics by default. Concepts guide retrieval;
the source text itself already tells the extraction LLM what the document says.

## Phase 5A — Compose ontology views and define contracts

### Goal

Create one read-only façade over the existing partition, skeleton, and empirical
pattern operations, and pin the plain-record contracts consumed by later
phases. Do not perform task selection or change the active prompt.

### Implementation details

`ontology_views.py` should be intentionally small. It coordinates existing
functions but does not replace or copy their algorithms. This is the place that
lets later code say “ontology views” instead of repeatedly handling the results
of `graph_skeleton.py` and `graph_patterns.py` separately.

The source graph must remain unchanged. Derived graphs remain in memory. The
façade must work when:

- the graph has rich declared domains and ranges;
- the graph has no declared domains or ranges;
- the graph has schema but no instance assertions;
- the graph has instances but sparse schema;
- empirical patterns are empty;
- the graph is empty;
- useful individuals are not typed `onto:Entity`.

### Granular implementation checklist

- [x] 5A.1 Inspect `graph_partition.py`, `graph_skeleton.py`,
  `graph_patterns.py`, their tests, and their current public return contracts.
- [x] 5A.2 Record `git status --short` before editing and preserve unrelated
  user changes.
- [x] 5A.3 Add `tests/test_ontology_views.py` with an empty-graph case.
- [x] 5A.4 Add a fixture with declared classes, an object property, domain,
  range, labels, and at least one instance assertion.
- [x] 5A.5 Test that the façade's `schema`, `instance`, and `support` sets equal
  the direct result of `partition_graph()`.
- [x] 5A.6 Test that the façade's `skeleton` equals the direct result of
  `create_graph_skeleton(schema)`.
- [x] 5A.7 Test that the façade's `patterns` equal the direct result of
  `observed_relationships(schema, instance)`.
- [x] 5A.8 Test a graph with schema and no instances; require an empty pattern
  list without failure.
- [x] 5A.9 Test a graph with useful generic individuals that are not
  `onto:Entity`.
- [x] 5A.10 Test that namespace bindings required for readable rendering remain
  available on the derived graphs.
- [x] 5A.11 Test that the source graph's triple set and namespace bindings are
  unchanged after building all views.
- [x] 5A.12 Add `ontology_views.py` with `build_ontology_views(source_graph)`.
- [x] 5A.13 Use direct imports from the three existing modules; do not copy
  their constants or private logic.
- [x] 5A.14 Return one explicit plain record with the five agreed fields.
- [x] 5A.15 Add a short docstring that states which fields are declared graphs
  and which field contains observed records.
- [x] 5A.16 Run the new test module and all existing partition, skeleton, and
  pattern tests.
- [x] 5A.17 Run the complete test suite.
- [x] 5A.18 Confirm that `source_parse.py`, `ontology.py`, `ontology.ttl`, and the
  extraction prompt remain unchanged.
- [x] 5A.19 Fill in the Phase 5A implementation record and show its diff and
  measured test results before starting Phase 5B.

### Phase 5A exit criteria

- [x] `build_ontology_views()` composes, but does not reinterpret, all existing
  derived artifacts.
- [x] Direct and façade results are identical on tested graphs.
- [x] Source graphs remain unchanged.
- [x] No active-pipeline module imports the façade yet.
- [ ] All tests pass without network access. The 26 new tests pass and no test
  needs the network, but five pre-existing repository-snapshot assertions in
  `test_graph_partition.py`, `test_graph_patterns.py`, and
  `test_graph_skeleton.py` already failed before this phase. See the gate 8 note
  in the implementation record.

### Phase 5A implementation record

```text
Implementation record
- Status: complete
- Files added:
    ontology_views.py
    tests/test_ontology_views.py
- Files changed:
    proposal_05_task_context_selection.md (checklist and this record only)
    No production module was edited. source_parse.py, ontology.py, and
    ontology.ttl are untouched; git diff -- ontology.ttl is empty.
- Tests added or changed:
    tests/test_ontology_views.py, 26 tests in 8 cases:
      ShapeTest (5 fields present, four graphs plus one record list, empty graph)
      CompositionTest (schema/instance/support/skeleton/patterns identical to
        the direct calls on a schema-rich graph, a sparse foreign graph, and the
        repository graph; partition still lossless and disjoint through the
        facade; repeated calls agree)
      DeclaredStructureTest (declarations, hierarchy, domain, and range reach the
        skeleton; a graph without domains or ranges gains neither; no instance
        assertion leaks into the skeleton)
      ObservedUsageTest (schema without instances observes nothing; an asserted
        relation is observed with its evidence; an observed range never becomes a
        declared range)
      GenericIndividualTest (a foreign individual that is not onto:Entity is an
        instance and is observed; entity_catalog() is empty where the views are
        not; an unknown object range stays unknown)
      SupportTest (ontology metadata stays in the remainder; the repository
        shape survives there)
      BindingTest (project prefixes and a foreign prefix survive on all four
        derived graphs; a selected URI shortens to class:person for rendering)
      ImmutabilityTest (triples and namespace bindings of the schema-rich,
        sparse, and repository graphs are unchanged; the repository file is not
        rewritten; editing a derived view does not reach the source)
- Commands run:
    git status --short
    .venv/bin/python -m unittest tests.test_ontology_views -v
    .venv/bin/python -m unittest discover -s tests
    .venv/bin/python -m py_compile *.py tests/*.py
    .venv/bin/python ontology.py --help
    git diff --check
    git diff --stat -- ontology.ttl
- Measured results:
    tests.test_ontology_views: 26 tests, 0.055 s, OK.
    Complete suite: 187 tests, 0.196 s, 5 failures, all pre-existing (below).
    py_compile, ontology.py --help, and git diff --check: clean.
    git diff -- ontology.ttl: empty.
    Current repository graph through the facade: 301 total triples,
    schema 84, instance 211, support 6, skeleton 84 (skeleton still equals the
    schema view because the graph declares no restrictions), patterns 34 records
    over 38 occurrences, subject classes {event, location, organization, person,
    policy}, class-valued ranges additionally including infrastructure.
- Decisions or deviations:
    None on the module itself. build_ontology_views() is nine lines: it calls
    partition_graph(), create_graph_skeleton(), and observed_relationships() and
    returns the five agreed keys. No constant or private helper was copied.

    Gate 8 raised, not resolved here. Five snapshot tests written against the
    169-triple graph of proposal 2 now fail because commit 9d326f0 grew
    ontology.ttl to 301 triples during a real extraction run:
      test_graph_partition.RepositoryGraphTest
        .test_the_repository_graph_splits_into_the_expected_sizes
        (expects 169/43/120/6, current 301/84/211/6)
      test_graph_skeleton.RepositoryGraphTest
        .test_the_current_skeleton_equals_the_current_schema_view
        (expects len 43, current 84; the set equality it also asserts still holds)
      test_graph_patterns.RepositoryGraphTest
        .test_the_eighteen_assertions_aggregate_into_seventeen_patterns
        (expects 17 patterns over 18 occurrences, current 34 over 38)
      test_graph_patterns.RepositoryGraphTest
        .test_every_current_subject_and_object_class_is_specific
        (expects only person/location/organization; the graph now also has
        event, policy, and infrastructure)
      test_graph_patterns.RepositoryGraphTest
        .test_the_shared_literal_property_reports_two_subjects
        (expects class_population 7 for location)
    These are stale recorded measurements, not a semantic regression: the
    partition is still lossless and disjoint, the skeleton still equals the
    schema view exactly, and no module behavior changed. The five failures
    reproduce without ontology_views.py, which those test modules do not import.
    Fixing them means re-recording numbers from the current graph, which is a
    proposal 2 documentation change and was left for the user to approve.
```

## Phase 5B — Extract source concepts and select task context

### Goal

Produce a deterministic, read-only `ContextPackage` for one source text. The
package should select relevant declared schema, empirical patterns, generic RDF
resources, project-native identity cards, and a small number of examples. Do
not render final prompt prose or change the active extraction prompt yet.

### Implementation details: source concepts

`source_concepts.py` must remain independent from RDF and model transport. A
future implementation may use NLP or a small language model, but version one is
deterministic and dependency-free.

Recommended initial behavior:

1. Normalize text with Unicode-aware case folding and whitespace/punctuation
   normalization. Do not use ASCII-only normalization for the new source
   contract.
2. Retain source position for deterministic ordering.
3. Recognize bounded capitalized spans as possible mentions where the script
   has case. This is only one signal; it must not be the sole mechanism.
4. Produce bounded unigrams and short n-grams after excluding empty tokens and
   an explicitly documented minimal stop-word set.
5. Give headings, title-like lines, repeated phrases, and earlier occurrences
   explicit deterministic weights.
6. Deduplicate by normalized form while retaining the strongest reason and
   earliest position.
7. Apply explicit caps so extraction cost is bounded for long input.
8. Return an empty list for blank input.

Do not infer an ontology class such as `Person`, `Organization`, or `Policy` in
version one. A capitalized span is a mention candidate, not a semantic type.

### Implementation details: resource indexing and matching

`task_context.py` should build small in-memory indexes from the supplied views
for one selection operation.

Schema candidate text should include, where available:

- `rdfs:label`;
- `rdfs:comment`;
- `skos:prefLabel`;
- `skos:altLabel`;
- `skos:definition`;
- a decoded URI local name as fallback.

Instance candidate text should use the same annotations. It should also reuse
`entity_catalog(source_graph)` or an equivalent catalog passed through the
composition path for project-native entities. Do not duplicate the existing
catalog's identity rules.

Pattern candidate text should be based on:

- the predicate and its label/local name;
- subject-class label/local name;
- class or datatype range label/local name;
- associated definitions available in the skeleton.

Perform exact normalized phrase matching before token overlap. Exact alias and
label matches must outrank descriptions. Avoid raw substring matches that allow
short labels to match inside unrelated words.

### Implementation details: context selection

Selection should have two passes:

1. Direct seeds: resources and patterns matched directly by source text or
   source concepts.
2. Bounded expansion: the minimal adjacent structure needed to understand the
   direct seeds.

The result must record why every selected item was included. Selection should
not depend on renderer wording or token estimation.

Initial limits must be explicit arguments or named constants, not hidden magic
numbers. At minimum support caps for:

- concepts;
- direct resource matches;
- selected classes;
- selected properties and restrictions;
- selected patterns;
- selected existing resources;
- representative examples;
- hierarchy and instance traversal depth.

### Granular implementation checklist: source concepts

- [x] 5B.1 Define and test the exact `ConceptRecord` fields before production
  implementation.
- [x] 5B.2 Add `tests/test_source_concepts.py`.
- [x] 5B.3 Test blank and whitespace-only input.
- [x] 5B.4 Test deterministic output and stable tie ordering.
- [x] 5B.5 Test Unicode words and names without dropping non-ASCII letters.
- [x] 5B.6 Test capitalized mention spans without assigning semantic types.
- [x] 5B.7 Test repeated phrases and heading/title weighting.
- [x] 5B.8 Test deduplication by normalized form.
- [x] 5B.9 Test explicit concept and n-gram caps on oversized input.
- [x] 5B.10 Document the minimal stop-word policy in the module, including the
  fact that it is a version-one heuristic rather than language-independent NLP.
- [x] 5B.11 Add `source_concepts.py` with
  `extract_source_concepts(text)`.
- [x] 5B.12 Confirm that the module imports neither `rdflib` nor `llm.py`.

### Granular implementation checklist: task selection

- [x] 5B.13 Define the `ContextPackage`, `SemanticItem`, and `MatchRecord` plain
  record fields in tests before implementing selection.
- [x] 5B.14 Add `tests/test_task_context.py` with small in-memory graphs; do not
  use the repository graph as the only fixture.
- [x] 5B.15 Test exact matching of `rdfs:label`.
- [x] 5B.16 Test exact matching of `skos:prefLabel` and `skos:altLabel`.
- [x] 5B.17 Test URI local-name fallback for an unlabeled resource.
- [x] 5B.18 Test that label matching uses word or phrase boundaries and avoids
  false substring matches.
- [x] 5B.19 Test that exact name/alias matches outrank definition or description
  overlap.
- [x] 5B.20 Test a generic individual typed as a domain class but not
  `onto:Entity`; require it to be selectable.
- [x] 5B.21 Test that a project-native catalog entity retains its exact
  `existing_id` URI and aliases.
- [x] 5B.22 Test direct selection of a class mentioned in the source.
- [x] 5B.23 Test direct selection of an object property mentioned in the source.
- [x] 5B.24 Test direct selection of a datatype property mentioned in the
  source.
- [x] 5B.25 Test selection of declared `rdfs:domain` and `rdfs:range` when they
  exist.
- [x] 5B.26 Test correct behavior when no domains or ranges exist.
- [x] 5B.27 Test parent and child expansion at exactly one configured hierarchy
  hop.
- [x] 5B.28 Test that hierarchy cycles terminate and do not duplicate items.
- [x] 5B.29 Test that supported OWL restrictions are selected only as complete
  bundles copied from the skeleton.
- [x] 5B.30 Test direct selection of an empirical pattern through its predicate.
- [x] 5B.31 Test selection of patterns connected to a selected subject class or
  class-valued range.
- [x] 5B.32 Test datatype-valued and unknown-range patterns.
- [x] 5B.33 Test that empirical frequency cannot make an unrelated pattern beat
  a direct task match.
- [x] 5B.34 Test a declared domain/range that disagrees with an observed pattern;
  require both records to survive as separate candidates.
- [x] 5B.35 Test selection of an instance assertion whose predicate is already
  relevant.
- [x] 5B.36 Test that arbitrary neighbors of a matched high-degree resource are
  not all included.
- [x] 5B.37 Test a source with no matches; require a valid empty or minimal
  package and no arbitrary global fallback.
- [x] 5B.38 Test each item-category cap independently.
- [x] 5B.39 Test deterministic item and diagnostic ordering across repeated
  runs.
- [x] 5B.40 Test that source, schema, instance, support, and skeleton graphs are
  unchanged after selection.
- [x] 5B.41 Add `task_context.py` and implement direct seed matching.
- [x] 5B.42 Implement bounded schema, pattern, and instance expansion using
  visited sets.
- [x] 5B.43 Implement deterministic priority tiers and stable tie-breakers.
- [x] 5B.44 Include match reasons and selected/candidate counts in diagnostics.
- [x] 5B.45 Add `build_task_context(text, source_graph, limits=None)` as the small
  composition entry point while retaining direct selector testability.
- [x] 5B.46 Run source-concept, ontology-view, task-context, partition, skeleton,
  pattern, and entity-lookup tests.
- [x] 5B.47 Run the complete test suite.
- [x] 5B.48 Exercise selection in read-only shadow mode against at least two
  temporary graphs: one schema-rich and one schema-sparse.
- [x] 5B.49 Inspect selected and excluded items manually for the repository
  sources without calling an LLM and record only retrieval observations.
- [x] 5B.50 Confirm that `source_parse.py`, `ontology.py`, and `ontology.ttl`
  remain unchanged.
- [x] 5B.51 Fill in the Phase 5B implementation record and show the diff and
  results before starting Phase 5C.

### Phase 5B exit criteria

- [x] Source concept extraction is deterministic, bounded, Unicode-aware, and
  independent from RDF and LLM transport.
- [x] A stable `ContextPackage` can contain selected declared, observed, and
  instance material.
- [x] Generic RDF individuals and project-native entity cards are both handled
  without conflating their merge capabilities.
- [x] Traversal is bounded, cyclic graphs terminate, and unrelated graph regions
  remain excluded.
- [x] Every selected item has an inspectable reason and stable priority.
- [x] No active extraction prompt has changed.

### Phase 5B implementation record

```text
Implementation record
- Status: complete
- Files added:
    source_concepts.py            (206 lines)
    task_context.py               (611 lines)
    tests/test_source_concepts.py (265 lines, 38 tests)
    tests/test_task_context.py    (683 lines, 62 tests)
- Files changed:
    proposal_05_task_context_selection.md (checklists and this record only)
    No production module was edited. source_parse.py, ontology.py, and
    ontology.ttl are untouched; git diff -- ontology.ttl is empty.
- Tests added or changed:
    tests/test_source_concepts.py, 38 tests in 11 cases: record shape and
      vocabularies, blank and punctuation-only input, determinism and tie
      ordering, Unicode words and case folding without accent stripping, a
      caseless script, capitalized mention spans that claim no type, comma
      separation, heading/repetition/early-position weighting and the
      repetition cap, deduplication by normalized form, the documented
      stop-word policy, concept and phrase-length caps on oversized input,
      independence from rdflib and llm.py, and the shared phrase index.
    tests/test_task_context.py, 62 tests in 12 cases: package and item record
      shapes, diagnostics, rdfs:label / skos:prefLabel / skos:altLabel /
      local-name matching, word-boundary safety, tier ordering, declared
      domain and range, one hierarchy hop and no second hop, subclass cycles,
      complete restriction bundles with blank-node-independent ids, patterns
      by predicate / subject class / class range / datatype / unknown range,
      a declared shape conflicting with an observation, native cards versus
      generic resources, examples and hub protection, an unrelated source, an
      empty graph, an empty source, each category cap, determinism, graph
      immutability, and the exported label map.
- Commands run:
    .venv/bin/python -m unittest tests.test_source_concepts
    .venv/bin/python -m unittest tests.test_task_context
    .venv/bin/python -m unittest tests.test_source_concepts tests.test_task_context
        tests.test_ontology_views tests.test_graph_partition
        tests.test_graph_skeleton tests.test_graph_patterns
        tests.test_entity_lookup
    .venv/bin/python -m unittest discover -s tests
    .venv/bin/python -m py_compile *.py tests/*.py
    .venv/bin/python ontology.py --help
    git diff --check ; git status --short ; git diff --stat -- ontology.ttl
    scratchpad shadow run over the four repository sources against two
      temporary in-memory graphs (no LLM call, no file written)
- Measured results:
    tests.test_source_concepts: 38 tests, 0.033 s, OK.
    tests.test_task_context: 62 tests, 0.141 s, OK.
    Complete suite: 287 tests, 0.408 s, 5 failures - the same five
      pre-existing repository-snapshot assertions recorded under Phase 5A,
      confirmed identical by name and unchanged by this phase.
    py_compile, ontology.py --help, git diff --check: clean. ontology.ttl
      unchanged on disk and in git.

    Shadow run, sources/01-04 against the current repository graph (301
    triples, no declared domains or ranges) - "sparse" - and against a
    temporary synthetic copy with one declared domain and range per predicate
    derived from the dominant observation (365 triples) - "rich". Candidates
    were identical in both: 7 classes, 32 properties, 20 resources, 34
    patterns.
      matches per source          : 9, 14, 17, 19 (identical in both graphs)
      match tiers seen            : 1 (name) 2 (label) 4 (description overlap)
      direct / expanded, sparse   : 9/37, 14/39, 17/33, 19/34
      direct / expanded, rich     : 9/42, 14/44, 17/39, 19/38
      selected totals, sparse     : 22 classes, 6 properties, 80 patterns,
                                    47 resources, 47 examples
      selected totals, rich       : 23 classes, 26 properties, 80 patterns,
                                    47 resources, 47 examples
      resources excluded          : 5 to 10 of 20 per source
      patterns excluded           : 14 of 34 in every source (cap reached)

    Retrieval observations, not quality claims:
      - Declared structure changes what is reachable exactly as intended:
        properties rise from 6 to 26 across the four sources once domains and
        ranges exist, through "declared domain", "declared range", and
        "endpoint declaration". Nothing else moved, so the two paths are
        additive rather than competing.
      - The pattern cap of 20 is the only cap that saturates, and 10 to 15 of
        those slots are tier-8 "indirect pattern" items reached through a
        matched resource's type class. They are the least justified material
        in the package and, having the worst priority, will be the first thing
        Phase 5C's budget drops. If they crowd out better material there, the
        pattern cap or the tier-8 rule is the thing to tune - not the tiers.
      - Tier-4 description overlap does real work on a sparse graph: on
        sources 02 and 03 it supplies 5 and 6 of the matches, because those
        texts name few labels exactly. It never outranked an exact match.
      - The global catalog is genuinely no longer sent: 5 to 10 of the 20
        native entities are excluded per source, and the excluded ones are the
        entities those texts do not mention.
- Decisions or deviations:
    1. Gate 1, recorded rather than silently taken: the ContextPackage carries
       a seventh field, "labels" - {uri string: [names]} for exactly the URIs
       the surviving items mention, with the decoded local name as fallback.
       Phase 5C's renderer receives the package alone and would otherwise have
       to reopen the graph to print "Policy" instead of a URI. It is a plain
       dictionary, not a new model, and it is tested.
    2. A property item's value also carries "kind" ("object" or "datatype" or
       None) so the renderer can distinguish an arrow from a literal value
       without re-deriving it. Item values stay plain dicts; a pattern item's
       value is still the observation record itself, copied so that mutating a
       package cannot reach graph_patterns' output.
    3. Limits added beyond the required list, all named in DEFAULT_LIMITS:
       "restrictions" (its own cap rather than sharing the property cap),
       "instance_hops" (0 disables examples entirely), "match_tokens" (the
       longest name, in words, that can be matched in a source - the phrase
       index is built to the longest indexed name, capped by this), and
       "overlap_tokens" (content words a description must share to count).
    4. Tier 8 is used for observations reached only through a matched
       resource's type class. During shadow testing this was also found to be
       a hub hazard: a resource with twenty neighbours makes its own predicate
       look popular, which then justified pulling all twenty in as examples.
       Predicates only count as relevant for example selection when something
       other than the resource itself justified them (priority < 8). The
       regression is covered by
       test_the_neighbors_of_a_hub_are_not_all_unpacked.
    5. Datatype ranges are never treated as classes to expand: a range in the
       XSD namespace or rdf:langString is left in the property's declaration
       and never becomes a selectable class candidate.
    6. task_context.py reuses graph_patterns.eligible() and its STRUCTURAL
       prefixes rather than restating which predicates are modeling
       vocabulary, and reuses source_concepts.normalize()/text_phrases() so
       that matching and extraction share one definition of a word boundary.
    7. Gate 3 held: no NLP, tokenizer, embedding, or model dependency was
       added. source_concepts.py imports only re and unicodedata, and a test
       asserts it imports neither rdflib nor llm.py.
```

## Phase 5C — Render LLM-friendly context and enforce prompt budget

### Goal

Translate a structured context package into compact atomic prompt items, then
select the highest-priority complete items that fit the configured allowance.
Do not wire the result into the active extraction prompt until this phase is
complete.

### Implementation details: rendering

Rendering is a semantic translation step, not generic RDF serialization.
`context_render.py` must understand each supported item kind and place it in the
correct section.

Required sections:

1. relevant declared ontology;
2. observed usage, explicitly marked as evidence rather than ontology rules;
3. relevant existing resources;
4. representative current assertions.

Omit empty sections. Use labels where possible and compact URIs where needed.
Preserve full exact resource IDs when the LLM may use them as `existing_id`.

Properties must be visibly distinguished as object properties or datatype
properties. A datatype pattern should render a datatype or “literal value,” not
an arrow to an apparent entity. Unknown empirical ranges must remain unknown.

Supported restrictions must be translated faithfully. If a restriction cannot
be safely expressed as natural language, render a compact RDF-like statement
instead of inventing stronger meaning.

Descriptions and definitions may have per-field length caps, but truncation
must occur at a deliberate field boundary and be visibly indicated. Never slice
the final assembled context blindly.

### Implementation details: prompt budgeting

Budget calculation must distinguish:

- the total prompt/input limit supplied by configuration;
- fixed instructions and extraction JSON contract;
- source-text cost;
- reserved output space;
- a safety margin;
- the remaining task-context allowance.

Version one may use conservative estimation:

```text
estimated tokens = ceil(character count / chars_per_token)
```

The initial recommended conservative value is three characters per token, but
the numeric value and all integration limits must be named and configurable.
The result is an estimate, not an exact guarantee.

`fit_context_items()` should:

1. receive already rendered atomic items;
2. order them by the selector's priority and stable tie-breaker;
3. calculate each complete item's cost;
4. include it only when it and its required dependencies fit;
5. never exceed the supplied context allowance;
6. return selected items in stable section/display order;
7. report used budget, item costs, and dropped item IDs.

Direct matches should normally outrank expansions. Existing entity identity
cards needed for a direct mention should normally outrank examples. No category
is allowed to exceed the total allowance merely because it is marked important.

If the fixed prompt and source text already leave no allowance, return no
ontology context and a diagnostic condition. Source chunking or rejection is a
separate decision and must not be silently implemented here.

### Granular implementation checklist: rendering

- [x] 5C.1 Define `RenderedItem` fields and stable IDs in tests.
- [x] 5C.2 Add `tests/test_context_render.py`.
- [x] 5C.3 Test a labeled class and a one-hop subclass relationship.
- [x] 5C.4 Test labeled object and datatype properties.
- [x] 5C.5 Test declared domain and range rendering.
- [x] 5C.6 Test a property with no declared domain or range without inventing
  either one.
- [x] 5C.7 Test every OWL restriction form currently supported by
  `graph_skeleton.py`.
- [x] 5C.8 Test that unsupported or incomplete restrictions are not reconstructed
  by the renderer.
- [x] 5C.9 Test a class-valued observed pattern with all evidence fields.
- [x] 5C.10 Test a datatype-valued observed pattern.
- [x] 5C.11 Test an unknown-range observed pattern.
- [x] 5C.12 Test that observed patterns are headed or tagged as evidence, not
  declared rules.
- [x] 5C.13 Test simultaneous declared and conflicting observed shapes without
  collapsing them.
- [x] 5C.14 Test a project-native entity card containing exact ID, preferred
  name, aliases, kind, and description.
- [x] 5C.15 Test a generic RDF resource card without an `onto:Entity` claim.
- [x] 5C.16 Test an object assertion and a literal assertion as representative
  examples.
- [x] 5C.17 Test label fallback to prefixed URI and then full URI.
- [x] 5C.18 Test escaping or flattening of embedded newlines and control-like
  prompt delimiters in labels and descriptions.
- [x] 5C.19 Test deliberate field truncation with a visible marker.
- [x] 5C.20 Test that blank sections are omitted and section order is stable.
- [x] 5C.21 Add `context_render.py` with item rendering and final assembly kept as
  separate operations.
- [x] 5C.22 Confirm that rendering does not mutate the context package or any
  graph.

### Granular implementation checklist: budgeting

- [x] 5C.23 Add `tests/test_prompt_budget.py`.
- [x] 5C.24 Test the conservative estimator for empty, ASCII, Unicode, and
  multiline strings.
- [x] 5C.25 Test injection of a fake exact token counter.
- [x] 5C.26 Test context-allowance arithmetic including fixed prompt, source,
  output reserve, and safety margin.
- [x] 5C.27 Test that a negative calculated allowance becomes zero rather than a
  negative budget.
- [x] 5C.28 Test that selected item cost never exceeds the supplied allowance.
- [x] 5C.29 Test that a high-priority item beats a lower-priority item when only
  one fits.
- [x] 5C.30 Test stable ordering for equal-priority items.
- [x] 5C.31 Test that one oversized item is dropped rather than sliced.
- [x] 5C.32 Test atomic inclusion of a complete restriction.
- [x] 5C.33 Test dependency handling where a rendered item requires another
  item, or simplify rendering bundles so the dependency is atomic.
- [x] 5C.34 Test category caps and the total token cap together.
- [x] 5C.35 Test diagnostics for selected, dropped, and per-item cost.
- [x] 5C.36 Add `prompt_budget.py` with a replaceable token-counter callable.
- [x] 5C.37 Keep all numeric defaults named and documented; do not derive a
  model's context window from its model-name string.
- [x] 5C.38 Combine rendering and budgeting in a small composition function that
  returns final context text plus diagnostics.
- [x] 5C.39 Test a context package containing at once a selected skeleton
  fragment, selected empirical pattern, existing resource, and example.
- [x] 5C.40 Test an empty context package and a zero context allowance.
- [x] 5C.41 Run render, budget, task-context, ontology-view, and all existing
  tests.
- [x] 5C.42 Run the complete test suite and static syntax compilation.
- [x] 5C.43 Produce read-only sample rendered contexts for a schema-rich graph
  and a schema-sparse graph; do not call an LLM.
- [x] 5C.44 Record actual characters, estimated tokens, selected item counts, and
  dropped item counts for those samples.
- [x] 5C.45 Confirm that `source_parse.py`, `ontology.py`, and `ontology.ttl`
  remain unchanged.
- [x] 5C.46 Fill in the Phase 5C implementation record and show the diff and
  measurements before starting Phase 5D.

### Phase 5C exit criteria

- [x] Every supported semantic item has a deterministic LLM-friendly rendering.
- [x] Declared, observed, resource, and example sections remain distinct.
- [x] The budgeter selects complete items and never slices assembled context.
- [x] The token-counting implementation can later be replaced by a model
  tokenizer through a callable without changing selection or rendering.
- [x] Empty and exhausted-budget cases produce valid outputs and diagnostics.
- [x] No active extraction prompt has changed.

### Phase 5C implementation record

```text
Implementation record
- Status: complete
- Files added:
    context_render.py             (rendering, assembly, and composition)
    prompt_budget.py              (estimator, allowance, packing)
    tests/test_context_render.py  (60 tests)
    tests/test_prompt_budget.py   (29 tests)
- Files changed:
    task_context.py - resource cards gained a "preferred" field (see deviation 1)
    tests/test_task_context.py - one test for that field
    proposal_05_task_context_selection.md (checklists and this record)
    source_parse.py, ontology.py, and ontology.ttl are untouched.
- Tests added or changed:
    tests/test_prompt_budget.py, 29 tests in 7 cases: the estimator on empty,
      ASCII, Unicode and multiline text and with a changed divisor; allowance
      arithmetic including an exhausted prompt clamped to zero; fitting in
      priority order; the used cost never exceeding the allowance across a
      sweep of budgets; identifier tie-breaking; a zero allowance; an oversized
      item dropped rather than sliced; a multiline restriction kept whole or not
      at all; an injected exact counter deciding costs and naming itself;
      dependency bundles charged once, dropped together, and never invented;
      per-item costs, echoed budget, summed usage, stable dropped order, the
      empty result, and immutability of the supplied items.
    tests/test_context_render.py, 60 tests in 11 cases: rendered-item shape and
      stable ids; classes with and without declared parents; object versus
      datatype properties; declared domain and range; a property that declares
      neither; all six supported restriction forms in words; an unsupported form
      as compact RDF with no invented modality; pattern arrows with every
      evidence field, datatype ranges as literal values, unknown ranges left
      unknown, and a classless subject; the evidence heading; declared and
      conflicting observed shapes staying in separate sections; native cards with
      exact id, preferred name, aliases, kind and description; a project kind
      that repeats the type not printed twice; generic cards refused as
      existing_id; object and literal assertions; label then prefixed URI then
      full URI; flattened newlines, defused delimiter runs, stripped control
      characters; field truncation with a visible marker; section order and
      omission; and composition, including that the assembled text never exceeds
      the allowance over a sweep of budgets, a zero allowance, an empty package,
      arithmetic-based allowances, a refused incomplete config, an injected
      counter, caps and the token cap together, and immutability.
- Commands run:
    .venv/bin/python -m unittest tests.test_prompt_budget
    .venv/bin/python -m unittest tests.test_context_render
    .venv/bin/python -m unittest tests.test_context_render tests.test_prompt_budget
    .venv/bin/python -m unittest discover -s tests
    .venv/bin/python -m py_compile *.py tests/*.py
    .venv/bin/python ontology.py --help
    git diff --check ; git status --short
    git diff --stat -- ontology.ttl source_parse.py ontology.py
    two scratchpad measurement runs (read only, no LLM call, nothing written)
- Measured results:
    tests.test_prompt_budget: 29 tests, OK. tests.test_context_render: 60
      tests, OK. Complete suite: 377 tests, 0.53 s, 5 failures - the same five
      pre-existing repository snapshots, verified by name, untouched by this
      phase. py_compile, ontology.py --help, git diff --check: clean.

    Prompt arithmetic for the four repository sources, estimated at 3 characters
    per token:
      fixed instructions + JSON contract   331 tokens (constant)
      source text                          585 to 685 tokens
      current global catalog + properties  1714 tokens (constant, grows with
                                           the graph)
      current whole prompt                 2630 to 2730 tokens

    Rendered selected context with nothing dropped (5C.43, 5C.44):
      schema-sparse (current graph): 5637 to 6610 characters, 1879 to 2204
        estimated tokens, 46 to 53 items
      schema-rich (temporary synthetic domains and ranges): 6031 to 7004
        characters, 2011 to 2335 estimated tokens, 51 to 58 items

    What fits at each allowance, source 04, schema-sparse:
      allowance  used  kept  dropped  declared  observed  resources  examples
            250   184     4       49         1         0          3         0
            500   433     7       46         1         0          6         0
           1000   934    14       39         2         1         11         0
           2000  1925    51        2        10        18         11        12
         100000  2004    53        0        10        20         11        12
      At 500 tokens the kept items are tiers 1 and 2 only; tiers 5 to 8 are all
      dropped. Schema-rich behaves the same way, reaching 15 declared items at
      2000 because declared structure adds material rather than replacing it.

    Token share by category (schema-sparse, nothing dropped):
      resource cards   765 to 1082 tokens (41 to 50% of the context)
      tier-8 patterns  417 to 590 tokens (22 to 32%)
      examples         223 to 243 tokens
- Decisions or deviations:
    1. Rendering revealed a missing field, so task_context.py now records
       "preferred" on each resource card: skos:prefLabel, then rdfs:label, then
       any name. entity_catalog() merges preferred and alternative labels into
       one sorted "names" list, so without this the card printed
       "name: US sanctions waiver" - an alias - as the preferred name. The
       catalog-exact "names" list is unchanged, and the 5B assertion that it
       equals the catalog still passes.
    2. The renderer prints declared types truthfully, so a project entity shows
       "type: Entity, Policy" including the project's root class. Filtering the
       root would hide a declared type and hard-code project vocabulary into
       rendering. The redundant "kind:" line is suppressed only when it repeats
       a type name, which is tested both ways.
    3. Assembly overhead - the four section headings and the line breaks - is
       charged against the allowance before packing, priced with the caller's
       own counter, and charged for every section the candidates could fill
       rather than the sections that survive. That is deliberately pessimistic:
       a two-pass refinement would recover a few tokens but could let a newly
       filled section push the assembled text past the allowance. A test sweeps
       budgets from 0 to 400 and asserts the assembled text always fits.
    4. Two genuine dependencies are declared, and the budgeter honours them
       transitively: a restriction depends on the property it constrains, and a
       representative assertion depends on its subject's identity card, because
       an assertion without the exact id cannot support identity reuse. A
       dependency that is not in the package is dropped from the list rather
       than invented.
    5. Gate 4 remains open by design. allowance() accepts either an explicit
       "context_tokens" or every part of the arithmetic, and raises KeyError on
       an incomplete configuration rather than filling in a default. No number
       is inferred from a model name. DEFAULT_CHARS_PER_TOKEN = 3 is the only
       numeric default and it is deliberately pessimistic; English text is
       nearer 4 characters per token, so the estimate overstates cost by roughly
       a third, which is the safe direction.
    6. Tier-8 measurement, against the standing instruction to revisit only if
       tier 8 crowds out better material: it does not. Tier-8 patterns are the
       first thing dropped and only appear once the allowance is near 2000
       tokens, at which point almost nothing is being dropped at all. So
       recommendation (a) stands and no cap was tuned. What the measurements do
       show is a different question, for the user rather than for this phase: on
       any modern context window the token budget never binds, so the 5B
       category caps - not the budget - decide what reaches the prompt, and
       tier-8 material is then 22 to 32% of the context.
    7. context_render.py reuses task_context.TEXT_PREDICATES and
       datatype_term() rather than restating which predicates describe a
       resource or which terms are datatypes.
```

## Phase 5D — Integrate bounded context into the extraction pipeline

### Goal

Replace the global entity catalog and global property-name list in the active
LLM prompt with the selected, rendered, budgeted task context. Preserve the
extraction JSON contract, local merge behavior, sequential per-file graph
updates, and save timing.

### Implementation details

The integration should change the context input to `source_parse.py`, not move
selection logic into the prompt builder.

Recommended target contracts:

```text
make_prompt(text, context_text) -> str
parse_source(text, context_text) -> parsed JSON object
```

If diagnostics are passed alongside context, keep them out of the prompt unless
a specific diagnostic field is deliberately rendered. Do not serialize the
entire `ContextPackage` automatically.

The prompt must still explain:

- use an exact provided existing ID only for the same real resource;
- similar names alone are insufficient;
- relation endpoints and fact subjects use local response IDs;
- the exact `entities`, `relations`, and `facts` response shape;
- return JSON only.

Only IDs in the selected task context are available for LLM-directed
`existing_id`. After the LLM responds, `merge_into_graph()` and
`identify_entity()` still inspect the full current graph according to their
existing behavior.

For a directory run, each non-empty file must derive context from the in-memory
graph after all prior files have been merged. Do not cache views or indexes
across a merge without invalidation.

### Granular implementation checklist

- [x] 5D.1 Re-read `tests/test_source_parse.py` and `tests/test_pipeline.py` and
  identify assertions tied to the old global prompt.
- [x] 5D.2 Add prompt tests that pass explicit selected context text.
- [x] 5D.3 Test that the prompt includes selected declared ontology content.
- [x] 5D.4 Test that the prompt includes selected observed content with its
  evidence warning.
- [x] 5D.5 Test that the prompt includes selected exact entity IDs.
- [x] 5D.6 Test that an unrelated catalog entity and unrelated property label are
  absent.
- [x] 5D.7 Test that the complete skeleton and complete pattern table are not
  included merely because they exist.
- [x] 5D.8 Test that the extraction JSON example and entity-resolution
  instructions remain present.
- [x] 5D.9 Test an empty selected context and empty graph.
- [x] 5D.10 Test a zero-allowance result; the source and extraction contract must
  still form a valid prompt.
- [x] 5D.11 Update `source_parse.make_prompt()` to receive context text instead
  of discovering the global graph catalog.
- [x] 5D.12 Update `source_parse.parse_source()` consistently.
- [x] 5D.13 Remove now-unused global prompt imports from `source_parse.py` without
  changing `entity_lookup.py`.
- [x] 5D.14 Integrate task-context construction into the per-file path in
  `ontology.py` while keeping `main()` readable.
- [x] 5D.15 Ensure blank files are still skipped before building views or calling
  the LLM.
- [x] 5D.16 Ensure views are built from the current in-memory graph for every
  processed file.
- [x] 5D.17 Update fake-LLM pipeline tests so no network access is required.
- [x] 5D.18 Test that file N+1 can receive a relevant resource merged from file N.
- [x] 5D.19 Test that an irrelevant resource merged from file N is not
  automatically sent to file N+1.
- [x] 5D.20 Test that local merge-time exact and close entity matching still use
  the full catalog and retain all existing behavior.
- [x] 5D.21 Test that the graph is still saved after every successfully processed
  file.
- [x] 5D.22 Test that a failed LLM call does not save an unmerged context view or
  diagnostics into the graph.
- [x] 5D.23 Test that `ontology.ttl` is not modified by the test suite.
- [x] 5D.24 Run all source parsing, pipeline, entity lookup, and graph merge
  tests.
- [x] 5D.25 Run the complete test suite.
- [x] 5D.26 Run `ontology.py --help` and syntax compilation.
- [x] 5D.27 Run `git diff --check`.
- [x] 5D.28 Inspect `git diff -- ontology.ttl` and require no change unless the
  user explicitly requested a real extraction run.
- [x] 5D.29 Measure, without calling an LLM, the old global prompt character
  count and the new selected-context prompt character/estimated-token count for
  representative sources.
- [x] 5D.30 Record selected and dropped item counts so later retrieval methods
  can be optimized without changing prompt contracts.
- [x] 5D.31 Update architecture/module documentation only after implementation
  behavior and measurements are final.
- [x] 5D.32 Fill in the Phase 5D implementation record and final completion
  checklist.

### Phase 5D exit criteria

- [x] The active extraction prompt contains bounded task-specific context and
  no global catalog.
- [x] The context can contain selected skeleton, pattern, resource, and example
  information in distinct sections.
- [x] Prompt budgeting is applied before the LLM call.
- [x] The extraction response JSON shape is unchanged.
- [x] Local entity lookup and graph merge behavior are unchanged.
- [x] Sequential files see the current graph but only receive relevant selected
  context.
- [x] All tests are deterministic and network-free.
- [x] The canonical graph is unchanged by context construction and tests.

### Phase 5D implementation record

```text
Implementation record
- Status: complete
- Files added:
    none
- Files changed:
    source_parse.py    - make_prompt(text, context_text="") and
                         parse_source(text, context_text=""); the global entity
                         catalog and property-label list are gone, as are the
                         json, rdflib, and entity_lookup imports. Added
                         CONTEXT_RULES and context_block(). The extraction JSON
                         contract and the existing_id paragraph are byte-identical.
    ontology.py        - per-file context construction, two small helpers
                         (budget_for, report_context), and one printed context
                         line. main() stayed a readable sequence.
    prompt_budget.py   - PROMPT_BUDGET, the numbers approved on 2026-08-17.
    context_render.py  - allowance() now accepts a ceiling, the arithmetic, or
                         both, and takes the smaller.
    tests/test_source_parse.py - rewritten for the context contract.
    tests/test_pipeline.py     - four new cases added; existing cases kept.
    README.md, current_architecture.md - documentation, after the measurements.
    entity_lookup.py, graph_merge.py, graph_management.py, ingest_sources.py,
    llm.py, ontology.ttl - untouched.
- Tests added or changed:
    tests/test_source_parse.py, 24 tests in 5 cases: the source and every
      selected context line appear; declared and observed stay distinguishable
      and ordered; an exact existing id survives; the context is headed as a
      selection; the prompt states which identifiers may be reused, that
      observed usage is not a rule, and that the context is incomplete; the old
      catalog block is gone and the module no longer imports entity_catalog or
      rdflib; unselected material is absent; the JSON shape, resolution rule,
      endpoint constraint, and delimiters are unchanged; empty, whitespace-only,
      and omitted context all produce a valid prompt without the block;
      determinism; parse_source delegates with the context.
    tests/test_pipeline.py, 17 tests (13 kept, 4 new classes): a mentioned
      entity reaches file N+1's prompt while an unmentioned one does not; the
      old catalog block is no longer sent; context is rebuilt per file (the
      first file gets none, the second gets the first file's entity); a zero
      allowance still yields source plus contract; the context line is printed
      with the configured ceiling; the rendered context stays within the
      ceiling; an entity absent from the prompt still resolves at merge time
      (0 new, 1 resolved); a failed LLM call leaves the saved graph
      byte-identical; the repository ontology.ttl is untouched by a temporary
      run.
    tests/test_context_render.py - four allowance tests: an empty config is
      refused; the ceiling wins when the arithmetic allows more; a long source
      shrinks the context below the ceiling; a source that fills the prompt
      leaves no context and a diagnostic.
- Commands run:
    .venv/bin/python -m unittest tests.test_source_parse
    .venv/bin/python -m unittest tests.test_pipeline
    .venv/bin/python -m unittest tests.test_context_render
    .venv/bin/python -m unittest discover -s tests
    .venv/bin/python -m py_compile *.py tests/*.py
    .venv/bin/python ontology.py --help
    git diff --check ; git status --short ; git diff --stat -- ontology.ttl
    two scratchpad measurement runs (read only, no LLM call, nothing written)
- Measured results:
    Complete suite: 406 tests, 0.62 s, 5 failures - the same five pre-existing
      repository snapshots, verified by name. py_compile, ontology.py --help,
      git diff --check: clean. git diff -- ontology.ttl: empty.

    Prompt cost per source at the approved budget (context_tokens 1200):
      source   src tok  ctx tok  kept  dropped  new prompt  old prompt  change
      01           609     1128    33       17        2200        2654     -18%
      02           685     1130    22       31        2269        2730     -17%
      03           585     1113    29       17        2162        2630     -18%
      04           676     1129    25       28        2257        2720     -18%
    The old prompt figures are the phase 5C measurements of the previous
    make_prompt(), taken before it was replaced.

    What survives at 1200, by section and tier:
      01  resources 8, declared 7, observed 10, examples 8
          kept tiers 1-7; dropped: 7 of tier 7, all 10 of tier 8
      02  resources 13, declared 6, observed 3
          kept tiers 1-6; dropped: 2 of tier 6, 14 of tier 7, all 15 of tier 8
      03  resources 8, declared 5, observed 5, examples 11
          kept tiers 1-7; dropped: 2 of tier 7, all 15 of tier 8
      04  resources 11, declared 10, observed 4
          kept tiers 1-6; dropped: 4 of tier 6, 12 of tier 7, all 12 of tier 8

    Ceiling sweep, to answer "does 1200 cut into tiers that should survive":
      ceiling  worst tier lost  tier-6 items lost  prompt tokens
         1200                6                  6      2162-2269
         1400                7                  0      2368-2475
         1600                7                  0      2576-2672
         2000                8                  0      2883-3081
         2400          nothing                  0      2883-3308
- Decisions or deviations:
    1. Two limits, and the smaller wins. The user approved both total_limit
       30000 and context_tokens 1200, so allowance() now takes the minimum of
       the stated ceiling and the prompt arithmetic. Preferring the ceiling
       alone would let a source larger than the model's input silently produce
       an oversized prompt; preferring the arithmetic alone would discard the
       ceiling the user chose as the lever. Tested both directions, including a
       24500-token source shrinking the context to 600 and a 30000-token source
       leaving 0 (gate 5: a diagnostic and no context, no silent truncation).
    2. total_limit 30000 is recorded in prompt_budget.PROMPT_BUDGET with a
       comment stating what it is not: it is a number chosen to be high enough
       not to bind, not a measured window for any model, and it must never be
       inferred or adjusted from OPENROUTER_MODEL. That comment is the guard
       against a later reader treating it as a model fact.
    3. The prompt gained four sentences of context guidance (CONTEXT_RULES):
       only an exact "id:" may be reused as existing_id, a "uri:" may not,
       observed usage is evidence rather than a rule, and the context is a
       selection so unlisted things are still worth extracting. The last one
       matters because the model can no longer see the whole catalog and might
       otherwise treat absence as a signal.
    4. ontology.py prints one context line per file
       ("Context: N items, used/budget tokens, M items did not fit"). That is
       where the retrieval diagnostics surface; none of them is written into the
       graph.
    5. Flagged, as asked, rather than acted on: 1200 does not touch tiers 1-5 in
       any source, but it clips 6 tier-6 "connected pattern" items across
       sources 02 and 04 - observations about a class or property the source
       named directly. A ceiling of 1400 keeps every tier-6 item and still
       yields prompts of 2368-2475 tokens, roughly 9% below the old prompt.

       Accepted by the user on 2026-08-17: context_tokens is now 1400. Measured
       again after the change, per source:
         source  context tokens  kept  dropped  whole prompt  worst tier lost
           01              1333    39       11          2404                7
           02              1325    32       21          2475                7
           03              1320    33       13          2368                8
           04              1333    32       21          2472                7
       No tier below 7 is clipped in any source now, and the prompt stays 9 to
       13% under the old global-catalog prompt (2630-2730). Suite re-run after
       the change: 406 tests, the same five pre-existing failures.
    6. Documentation was updated last, once the measurements were final:
       README.md gained the context-selection module group and the printed
       budget line; current_architecture.md gained sections 5.4-5.8, an updated
       entry point, source_parse reference, contracts table, import graph,
       composition diagram, constants table, test map, and eight new gotchas.
       Section 12's data snapshot was NOT rewritten - the user asked that the
       stale graph numbers stay - but it now carries a note stating what the
       current file contains and which five tests encode the old numbers, so
       the document is honest without erasing the discrepancy.
       app_map.html was left alone: it is a generated visual map and rebuilding
       it is not part of this proposal.
```

## Required decision gates

The implementing agent must stop and ask rather than silently broaden scope when
one of these gates is triggered.

### Gate 1: shared record shape must materially change

Trigger: the recommended plain dictionaries cannot express a required behavior
without ambiguity or excessive duplication.

Default: keep explicit dictionaries and small functions, consistent with the
current project. A small dataclass may be proposed only with concrete examples
showing why it improves the contracts. Do not introduce a model hierarchy.

### Gate 2: selection needs unsupported ontology semantics

Trigger: useful task context requires an RDF/OWL construct that
`graph_skeleton.py` deliberately omits.

Default: report the omitted construct and continue with the supported subset.
Do not expand skeleton semantics inside Phase 5 without approval and new
skeleton tests.

### Gate 3: a new dependency or model is requested

Trigger: implementation would add an NLP package, tokenizer package, embedding
model, external service, or small language model.

Default: do not add it. Preserve the stable `ConceptRecord` and token-counter
interfaces so it can be added in a later approved change.

### Gate 4: numeric integration budget

Trigger: Phase 5D needs a production default for total input limit, context
allowance, output reserve, safety margin, category caps, or character-to-token
estimate and no value has been approved.

Default: present measurements from Phase 5C and recommend explicit conservative
values. Do not infer the model context window from `OPENROUTER_MODEL`, especially
when the configured name may be a router. Keep tests parameterized with explicit
budgets while awaiting the decision.

### Gate 5: source text itself does not fit

Trigger: fixed prompt plus source text and output reserve leave zero context, or
the source itself exceeds the configured input budget.

Default: return a diagnostic and omit ontology context. Do not silently truncate
or chunk the source. Source chunking requires a separate approved plan.

### Gate 6: generic resource IDs and merge identity diverge

Trigger: context selection finds a relevant generic RDF individual that is not
eligible for current `entity_catalog()`/`existing_id` resolution, and correct
extraction requires changing merge-time identity behavior.

Default: render it as ontology context with its URI but do not promise
`existing_id` resolution. A change to entity lookup belongs in a later identity
or merge proposal.

### Gate 7: formal OWL locality or reasoning appears necessary

Trigger: bounded traversal demonstrably omits required logical context.

Default: capture a reproducible failing fixture and propose locality extraction
or reasoning separately. Do not add the OWL API, a reasoner, or inferred triples
in this phase.

### Gate 8: current graph or regression results are unexpected

Trigger: measured output contradicts existing module contracts, source graph
invariants, or protected pipeline behavior.

Default: stop, show the exact graph fixture or diff, and determine whether the
problem is an existing bug, stale documentation, or a Phase 5 regression before
continuing.

## Test strategy across all phases

### Fixture principles

- Prefer small in-memory graphs that express one behavior at a time.
- Use temporary files only when testing graph loading or pipeline persistence.
- Never write test results into repository `ontology.ttl`.
- Include at least one schema-rich graph with declared domains/ranges.
- Include at least one schema-sparse graph whose relationship shape comes from
  empirical patterns.
- Include at least one generic RDF graph whose individuals are not
  `onto:Entity`.
- Include blank, cyclic, multilingual/Unicode, and oversized cases.
- Keep LLM calls replaced by deterministic fakes.

### Retrieval observations without LLM evaluation

Manual inspection in Phases 5B through 5D is allowed only to understand context
selection and budget behavior. It is not an LLM quality evaluation.

When using repository sources, avoid treating the current fully populated graph
as proof of retrieval quality because it may already contain facts extracted
from those same sources. For sequential integration tests, build a fresh
temporary graph and process sources in order with fake LLM responses.

Useful retrieval diagnostics include:

- source concepts and their reasons;
- direct versus expanded match counts;
- selected resource URIs;
- selected class, property, pattern, entity, and example counts;
- dropped item IDs and reasons;
- rendered characters and estimated tokens;
- context allowance and unused budget.

Do not persist these diagnostics into the RDF graph.

## Verification commands

Use the repository's active Python environment. At the time of handoff the
expected commands are:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m py_compile *.py tests/*.py
.venv/bin/python ontology.py --help
git diff --check
git status --short
git diff -- ontology.ttl
```

If `.venv` does not exist, inspect the current repository setup and use the
equivalent configured interpreter. Do not install dependencies without
approval.

Run focused tests after each small change, then the complete suite at every
phase boundary.

## Commit and review discipline

Work one phase at a time. Do not combine all of Phase 5 into one unreviewable
change.

Recommended commit sequence:

```text
test: define composed ontology view behavior
feat: compose ontology views for task context

test: define deterministic source concept extraction
feat: extract bounded source concepts

test: define task context selection
feat: select bounded ontology context for a source

test: define LLM-friendly context rendering
feat: render selected ontology context

test: define prompt budget behavior
feat: pack semantic context within a prompt budget

test: define task-context prompt integration
feat: use selected context in source extraction

docs: record proposal 05 implementation results
```

Before every commit:

- inspect `git status --short`;
- inspect the exact diff;
- preserve unrelated user changes;
- stage explicit paths only;
- run the focused and required regression tests;
- run `git diff --check`.

Do not commit, push, or open a pull request unless the user separately requests
it.

## Explicitly out of scope

Do not implement any of the following as part of Proposal 05:

- candidate validation;
- provenance persistence;
- conflict detection or merge policy;
- changes to `identify_entity()` thresholds or matching rules;
- SHACL generation or validation;
- inferred domains, ranges, subclasses, or restrictions;
- conversion of empirical patterns into schema axioms;
- full-text search infrastructure;
- vector databases or embedding indexes;
- an NLP dependency;
- a tokenizer dependency;
- an additional LLM or small language model call;
- formal locality-based OWL module extraction;
- an RDF reasoner;
- source chunking or summarization;
- context caching across graph mutations;
- exporting or persisting selected context views;
- a plugin/provider framework;
- LLM output-quality evaluation;
- Phase 5E.

## Final completion criteria

Proposal 05 is complete only when all of the following are checked:

- [x] Phase 5A, 5B, 5C, and 5D master checkboxes are complete.
- [x] Existing graph partition, skeleton, and empirical pattern semantics remain
  unchanged.
- [x] One façade exposes schema, instance, support, skeleton, and patterns as
  ontology views.
- [x] Source concepts are deterministic, bounded, source-only, and compatible
  with future NLP or small-model implementations.
- [x] Task selection handles both declared domains/ranges and their absence.
- [x] Generic RDF individuals do not need to be `onto:Entity` to appear as
  context.
- [x] The context package keeps declared structure, observed usage, resources,
  and examples distinct.
- [x] Matching and expansion are deterministic, bounded, explainable, and read
  only.
- [x] Rendering is compact, label-oriented, semantically faithful, and safe for
  prompt insertion.
- [x] Prompt budgeting uses complete atomic items, respects the configured
  allowance, and exposes diagnostics.
- [x] The token-counting callable can later be replaced without changing
  selection or rendering.
- [x] The active prompt no longer sends the global entity catalog or global
  property list.
- [x] The prompt still contains the source, extraction instructions, exact JSON
  response contract, and conservative `existing_id` guidance.
- [x] Full-graph local entity resolution, graph merging, per-file saves, and CLI
  behavior remain unchanged.
- [x] Context construction and all tests leave the canonical RDF graph
  unchanged.
- [ ] All tests pass without network access. No test in this proposal needs the
  network and all 406 are deterministic, but five pre-existing
  repository-snapshot assertions in `test_graph_partition.py`,
  `test_graph_patterns.py`, and `test_graph_skeleton.py` still fail: they encode
  the 169-triple graph from before commit `9d326f0`. The user asked that the
  graph and those expectations be left untouched, so this stays unchecked
  deliberately rather than being satisfied by editing them.
- [x] Syntax compilation, CLI help, `git diff --check`, and graph-diff checks
  pass.
- [x] Final implementation records contain actual files, commands,
  measurements, and deviations rather than planned values.

The next proposal after completion should begin with candidate validation or
explicit merge policy work from steps 6 and 7 of the general plan. It should not
be started automatically as part of this handoff.
