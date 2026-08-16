# Ontology Context and Graph Merge Plan

## Goal

Make ontology extraction practical for graphs that are too large to place in an
LLM prompt, while preserving meaning and keeping the program deliberately small.

The work has two separate concerns:

1. Select a small, relevant ontology context for each extraction task.
2. Safely integrate extracted knowledge into the canonical graph.

These concerns should remain separate. Context selection determines what the LLM
sees; merging determines what is accepted into the graph.

## Intended processing flow

```text
input text
  -> select relevant ontology context
  -> ask the LLM for candidate knowledge
  -> validate and normalize the candidates
  -> resolve identities and conflicts
  -> merge accepted statements
  -> regenerate summaries and views
```

LLM output should eventually be treated as a proposal rather than as a graph that
is appended without an intermediate decision.

## High-level approach

### 1. Understand the current behavior

First establish a small, reproducible baseline of the current end-to-end
pipeline. Record what enters the prompt, what the LLM returns, how entity
resolution behaves, and how the graph changes.

This step is described in
[`proposal_01_current_pipeline_baseline.md`](proposal_01_current_pipeline_baseline.md).

### 2. Separate schema from instance data

Distinguish the ontology schema, or TBox, from instance data, or ABox. This does
not require separate persistent graph files at first. Read the current source
graph without changing it and derive three temporary views:

- a current schema graph containing TBox statements;
- a current instance graph containing ABox statements;
- a support or remainder graph containing ontology metadata, SHACL structures,
  and statements that cannot safely be assigned to either of the first two.

The remainder is an accounting mechanism, not a review queue. The three views
should be disjoint, their union should equal the source graph, and none of their
construction should mutate or overwrite that graph.

### 3. Extract a semantic skeleton

Build a compact schema view containing only the most useful structural elements:

- `owl:Class`;
- `rdfs:subClassOf`;
- `owl:ObjectProperty` and `owl:DatatypeProperty`;
- `rdfs:domain` and `rdfs:range`;
- labels and definitions;
- a small, explicitly supported set of OWL restrictions.

The skeleton is a general structural artifact used by later context selection.
It is not automatically placed into every LLM prompt: even a schema-only graph
may eventually be too large, and relevance to the current task is not decided
in this step.

### 4. Learn structure from actual data

Declared domains and ranges may be missing or incomplete. Inspect instance data
to derive commonly observed patterns such as:

```text
Product -> belongsToBrand -> Brand
Product -> soldInMarket -> Market
```

Record useful evidence such as occurrence count, distinct subjects, class
coverage, and typical cardinality. Frequency should not be the only measure of
importance. Keep these observations distinct from declared schema: an observed
pattern must not silently become an asserted `rdfs:domain` or `rdfs:range`.

Like the schema split and skeleton, the empirical relationship map is a derived
artifact. Producing it does not change the current source graph and does not yet
change prompt construction.

Steps 2 through 4 are specified in
[`proposal_02_schema_skeleton_and_patterns.md`](proposal_02_schema_skeleton_and_patterns.md).

### 5. Select context for a task

For each document or task, identify relevant concepts and construct a small
context package containing:

- relevant classes and properties;
- definitions and aliases;
- nearby class hierarchy;
- common empirical relationships;
- important constraints;
- a few representative examples when useful.

This is the first step that determines what graph context will be placed in the
prompt. The global entity catalog must not be sent. Instead, select a bounded
package from the general skeleton, empirical relationship map, and current
instance graph. A package may contain a tiny always-present core plus
task-relevant schema and instance subgraphs, but the contents of that core
should be decided only after the derived artifacts from steps 2 through 4 have
been inspected.

Start with simple concept selection and bounded traversal. Add formal
locality-based OWL module extraction later only if the simpler approach fails to
preserve needed logical meaning.

Context size can initially be controlled without adding a model tokenizer. Use
a configurable character budget with conservative token estimation, reserve
space for the fixed prompt, source text, and model output, and add ranked context
items only while they fit. Optional caps on classes, properties, patterns, and
entities provide additional safeguards. This is an estimate rather than an
exact token guarantee; exact enforcement requires the target model's tokenizer.

### 6. Validate extracted candidates

Before changing the canonical graph, check candidate output for:

- valid structure and supported predicates;
- normalized identifiers, names, and literals;
- duplicate statements;
- incompatible types or contradictory assertions;
- missing or invalid relation endpoints.

SHACL can later express stable operational constraints, but it does not need to
be the first implementation.

### 7. Define graph merge policy

Graph merging is primarily an identity and conflict-resolution problem. The
policy should determine:

- whether a mention refers to an existing entity;
- when a new entity should be created;
- how aliases and close spellings are handled;
- what happens when sources disagree;
- which assertions require review;
- how source provenance and extraction confidence are retained.

Exact duplicate RDF triples are already naturally collapsed by the graph. That
alone does not resolve semantic duplicates or conflicting claims.

### 8. Publish purpose-specific views

Avoid maintaining one universal simplified Turtle file. Generate related views
from one canonical graph:

- **Ontology map**: important classes and the class hierarchy.
- **Relationship map**: dominant class-property-class patterns with usage data.
- **Domain modules**: focused fragments for areas such as Product, Customer,
  Process, KPI, or Policy.
- **Agent view**: only the concepts, policies, tools, definitions, and
  relationships needed for a particular task.
- **SHACL shapes**: operational expectations used for validation.

SPARQL `CONSTRUCT` queries are a suitable way to generate graph views once their
contents are understood.

## Importance and selection

Selection should combine several signals rather than relying on graph centrality
alone. A general form is:

```text
importance = business weight x query usage x data coverage x connectivity
```

The exact calculation can remain simple at first. Generic nodes such as
`Organization`, `Thing`, or `Identifier` may be structurally central without
being useful for a specific task.

## Code organization

Keep one clear orchestration function in the main file. Introduce separate
modules only when a responsibility is understood and can be self-contained, for
example:

- graph loading and saving;
- schema and instance classification;
- semantic-skeleton extraction;
- usage-statistics calculation;
- task-context selection;
- candidate validation;
- merge policy;
- view generation.

Refactor one responsibility at a time while preserving working behavior. Avoid
building a framework, deep class hierarchy, or generic plugin system before it
is needed.

## Recommended order

1. Characterize the existing end-to-end behavior.
2. Derive current schema, instance, and support/remainder views without changing
   the source graph.
3. Generate the general semantic skeleton.
4. Add empirical relationship statistics from instance data.
5. Add task-specific, budgeted context selection.
6. Replace global entity and property context with only the selected context
   package in the LLM prompt.
7. Introduce validation and provenance before merging.
8. Define explicit identity and conflict-resolution policies.
9. Add SHACL and purpose-specific exported views.
10. Consider formal OWL locality modules if the simpler mechanism is
    insufficient.

Only one point should be developed at a time. The next point should begin after
the previous one has a clear result and its assumptions have been reviewed.

## First practical outcome

After the baseline is understood, the next architectural outcome is a set of
read-only derived artifacts: a schema/instance/support partition, a general
semantic skeleton, and an empirical relationship map. Task-specific context
selection then uses those artifacts to replace global entity and property
context with a bounded relevant package. LLM results should subsequently move
toward being reviewed candidates rather than immediately accepted graph data.
