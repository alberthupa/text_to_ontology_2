# Proposal 02: Read-Only Graph Partition, Semantic Skeleton, and Empirical Patterns

## Status

This document is the implementation handoff for Proposal 2. It covers steps 2,
3, and 4 of
[`ontology_context_and_merge_plan.md`](ontology_context_and_merge_plan.md):

1. separate schema statements from instance data;
2. derive a compact semantic skeleton;
3. learn commonly observed structure from instance data.

Proposal 1 is complete. Its resulting architecture and measured behavior are
recorded in:

- [`proposal_01_current_pipeline_baseline.md`](proposal_01_current_pipeline_baseline.md);
- [`proposal_01_baseline_results.md`](proposal_01_baseline_results.md).

Proposal 2 has not been implemented yet. This handoff defines its intended
scope, stages, tests, and decision gates. The implementing agent must complete
one stage at a time and must not silently resolve a decision gate.

## Goal

Produce small, read-only structural artifacts from the current RDF graph without
changing that graph or the active extraction pipeline.

Given one source graph, Proposal 2 should be able to produce:

```text
source graph (read only)
  |
  |-> current schema graph
  |-> current instance graph
  |-> current support/remainder graph
  |
  |-> general semantic skeleton
  `-> empirical relationship patterns
```

The outputs are preparation for task-specific context selection in step 5 of
the main plan. Proposal 2 does not decide what a particular source document
needs and does not place any of these artifacts into an LLM prompt.

## Phase boundary

The boundary between this proposal and the next context-selection proposal is
strict.

Proposal 2 answers:

- Which current statements describe schema?
- Which current statements describe instances?
- Which statements are supporting material or cannot be classified safely?
- What is the explicit class and property skeleton?
- Which class-property-range patterns are observed in the instance data?
- What evidence describes the use of each observed pattern?

Proposal 2 does not answer:

- Which concepts are relevant to the current source text?
- Which part of the skeleton should be sent to the LLM?
- Which existing individuals are relevant to the current source text?
- How many context items fit into the current prompt budget?
- How should context items be ranked or traversed?

Those are step 5 responsibilities. Only after a bounded task-specific package
exists should `source_parse.py` stop sending the current global entity catalog
and property list and begin sending the selected package.

## Approved decisions

The following decisions are already made and are not implementation gates:

1. The current source graph, including the repository's `ontology.ttl`, must not
   be changed by Proposal 2.
2. Schema, instance, and support/remainder graphs are derived views. They are
   created in memory unless the user later explicitly requests exports.
3. Test fixtures are temporary in-memory graphs or files under temporary test
   directories. They must never be merged into the repository graph.
4. The three partition views must be disjoint, and their union must equal the
   source graph.
5. The support/remainder graph is an accounting mechanism. It is not a human
   review queue and has no runtime workflow.
6. The semantic skeleton is a general derived artifact. It is not automatically
   included in every prompt.
7. Empirical patterns are descriptive evidence. They must not be converted into
   declared `rdfs:domain`, `rdfs:range`, restrictions, or SHACL constraints.
8. Proposal 2 does not change `make_prompt()`, `parse_source()`, the extraction
   JSON shape, entity lookup, graph merge, CLI behavior, or save timing.
9. The eventual prompt must not contain a global entity catalog. Task-specific
   entity context belongs to step 5, not this proposal.
10. No tokenizer is added in Proposal 2. A later context selector may initially
    use conservative character and item budgets.
11. No new dependency should be required. Use the standard library and the
    existing `rdflib` dependency.
12. The implementation should remain procedural and small. Do not introduce a
    framework, service layer, plugin system, class hierarchy, or generic helper
    module.

## Required implementation decisions at a glance

The implementing agent must not treat the recommended defaults below as already
approved. Gates 2 through 5 require an explicit user decision. Gates 1, 6, and 7
apply when their triggering condition occurs.

| Gate | Stage | Decision |
|---|---|---|
| 1 | Partitioning | How to classify triples when schema, instance, and support roles overlap |
| 2 | Skeleton | Exactly which OWL restriction forms the skeleton supports |
| 3 | Patterns | Which class or classes represent multiply typed resources |
| 4 | Patterns | Exact definitions of coverage and cardinality statistics |
| 5 | Patterns | Plain records or a derived RDF representation for empirical results |
| 6 | Any measured stage | How to resolve unexpected results from the current graph |
| 7 | Any stage | Whether to approve a dependency, reasoner, persistence, prompt, or other scope expansion |

The full gates, recommended starting options, and evidence requirements appear
under [Implementation decision gates](#implementation-decision-gates).

## Terminology

### Source graph

The graph supplied to the partitioning and derivation functions. In normal use,
this is the current graph loaded from `ontology.ttl` or another user-supplied
Turtle file.

"Source graph" in this proposal does not grant permission to mutate or save it.
Every Proposal 2 operation treats it as read only.

### Current schema graph

A derived graph containing statements classified as TBox: classes, properties,
hierarchy, domains, ranges, schema annotations, and recognized OWL structural
statements.

"Current" means derived from the source graph as it exists for this operation.
It is not a separately maintained authoritative graph.

### Current instance graph

A derived graph containing ABox statements: individual type assertions,
relations between individuals, literal facts, and instance annotations.

### Current support/remainder graph

A derived graph containing source statements that are neither TBox nor ABox, or
that cannot safely be assigned to either role. For the repository graph, this is
expected to include the ontology declaration and SHACL shape structure.

The remainder makes the partition lossless and exposes classification gaps. It
is not included in the skeleton or empirical relationship calculations unless a
later proposal deliberately gives some of it a role.

### Semantic skeleton

A compact graph copied from the current schema graph. It retains selected
explicit class and property structure and excludes instance data.

### Empirical relationship pattern

A descriptive record such as:

```text
Location -> affects -> Organization
```

accompanied by evidence such as occurrence count, distinct subjects, class
coverage, and per-subject cardinality. It reports what the current ABox does; it
does not assert what every valid instance must do.

## Current program and protected behavior

Proposal 1 produced these responsibility boundaries:

```text
ontology.py             CLI and orchestration
ingest_sources.py       source discovery and reading
source_parse.py         prompt construction and LLM parsing
entity_lookup.py        current identity decision
graph_merge.py          current graph mutation
graph_management.py     graph lifecycle and project namespaces
llm.py                  LLM transport
```

The following behaviors remain protected throughout Proposal 2:

- `ontology.py` remains the executable entry point.
- Parsing does not mutate the graph.
- Graph merge processes entities sequentially.
- The entity catalog is rebuilt for each entity during a merge.
- Existing local identity matching and its `0.96` close-spelling rule remain
  unchanged.
- The extraction JSON contract remains `entities`, `relations`, and `facts`.
- The graph is saved after each processed source file.
- Existing tests must remain deterministic and network-free.

Proposal 2 modules are initially called directly by tests and later by the
step-5 context selector. Do not wire them into `ontology.py` merely to make them
appear active in the current pipeline.

## Proposed module organization

### `graph_partition.py`

Purpose: classify every source triple into one of three current derived views.

Proposed primary entry point:

```text
partition_graph(source_graph)
    -> schema_graph, instance_graph, support_graph
```

Responsibilities:

- discover resources playing schema, instance, and support roles;
- classify source triples using those roles and structural predicates;
- preserve source namespace bindings in all derived graphs;
- ensure every source triple occurs in exactly one result;
- avoid mutating the source graph.

It must not:

- save any graph;
- extract the smaller semantic skeleton;
- calculate usage statistics;
- build prompt text;
- infer new ontology axioms;
- call the LLM.

### `graph_skeleton.py`

Purpose: copy the explicitly supported structural subset from a current schema
graph into a smaller derived graph.

Proposed primary entry point:

```text
create_graph_skeleton(schema_graph) -> skeleton_graph
```

Responsibilities:

- retain approved class and property declarations and axioms;
- retain useful labels and definitions attached to retained schema resources;
- copy only complete supported OWL restriction structures;
- preserve namespace bindings;
- avoid mutating the schema graph.

It must not:

- read from the current instance graph;
- decide relevance to a task;
- calculate empirical patterns;
- serialize prompt context;
- add inferred domains, ranges, or class hierarchy;
- mutate or save the source graph.

### `graph_patterns.py`

Purpose: summarize relationship and literal-property use in the current instance
graph using class information from the current schema graph.

Proposed primary entry point:

```text
observed_relationships(schema_graph, instance_graph) -> list of records
```

Responsibilities:

- identify instance assertions eligible for structural summarization;
- associate subjects and resource objects with usable classes;
- associate literal objects with usable datatypes;
- aggregate statements into class-property-range patterns;
- calculate the approved evidence fields;
- return results in deterministic order;
- avoid mutating either input graph.

It must not:

- alter schema statements;
- turn observations into ontology axioms or SHACL shapes;
- apply task relevance or a prompt budget;
- filter using business importance or query usage that the program does not yet
  have;
- call the LLM.

### Existing modules

No production integration is part of Proposal 2:

- `source_parse.py` remains unchanged;
- `ontology.py` remains unchanged;
- `entity_lookup.py` remains unchanged;
- `graph_merge.py` remains unchanged;
- `graph_management.py` may be imported only for existing project namespaces or
  prefix binding; its lifecycle behavior remains unchanged.

The intended dependency direction is:

```text
graph_partition.py  -> rdflib, optionally graph_management.py vocabulary
graph_skeleton.py   -> rdflib
graph_patterns.py   -> rdflib

future context selector
  -> graph_partition.py
  -> graph_skeleton.py
  -> graph_patterns.py
  -> source_parse.py
```

Avoid dependencies among the three new modules unless actual implementation
shows a small, necessary shared operation. Passing the derived graphs explicitly
is preferable to hiding partitioning inside both downstream modules.

## Proposed classification policy

Partitioning needs at least two passes. A triple cannot always be classified
from its predicate alone because labels and comments inherit the role of their
subject.

### Pass 1: discover resource roles

Start from explicit declarations and structural positions.

Likely schema resources include:

- subjects typed `owl:Class` or `rdfs:Class`;
- subjects typed `owl:ObjectProperty` or `owl:DatatypeProperty`;
- classes occurring as the subject or object of `rdfs:subClassOf`;
- properties occurring as the subject of `rdfs:domain` or `rdfs:range`;
- classes or datatypes occurring as domain or range targets;
- explicitly recognizable OWL restriction nodes and their owned triples,
  referenced properties, and fillers.

Partitioning and skeleton support are separate decisions. A recognizable OWL
restriction can belong to the current schema graph even when Proposal 2 later
decides not to retain that restriction form in the smaller skeleton.

Likely instance resources include:

- subjects explicitly typed `owl:NamedIndividual`;
- subjects explicitly typed `skos:Concept` when they are not schema resources;
- subjects explicitly typed `onto:Entity` or another discovered domain class;
- resources participating as subjects or objects of instance property
  assertions.

Likely support resources include:

- subjects typed `owl:Ontology`;
- subjects typed `sh:NodeShape` or `sh:PropertyShape`;
- blank-node structures owned by SHACL shapes;
- other explicitly recognized support structures.

Role discovery must not add triples to the source or derived graphs.

### Pass 2: assign triples

The intended priority is:

1. Assign recognized ontology metadata, SHACL roots, and their owned blank-node
   structures to the support graph.
2. Assign declarations and structural schema axioms to the schema graph.
3. Assign labels and definitions according to the role of their subject.
4. Assign individual type statements, relations, literal facts, and instance
   annotations to the instance graph.
5. Assign anything not safely classified to the support/remainder graph.

The implementation must verify after assignment that:

```text
schema triples intersect instance triples = empty
schema triples intersect support triples  = empty
instance triples intersect support triples = empty
union of all three triple sets = source triple set
```

An unknown statement belongs in the remainder rather than being guessed into
the schema or instance graph.

## Proposed semantic-skeleton contents

The non-restriction core should retain explicit source statements for:

- `owl:Class` and `rdfs:Class` declarations;
- `rdfs:subClassOf`;
- `owl:ObjectProperty` and `owl:DatatypeProperty` declarations;
- `rdfs:domain` and `rdfs:range`;
- `rdfs:label` and `rdfs:comment` on retained schema resources;
- `skos:prefLabel`, `skos:altLabel`, and `skos:definition` on retained schema
  resources.

The skeleton must copy statements; it must not materialize inferred triples.
For example, a property observed only in instance data does not acquire a
declared domain or range in the skeleton.

If a retained axiom refers to another named schema resource, include that
resource's supported declaration, label, and definition when present. Do not
copy unrelated statements merely because they share a resource.

Blank-node OWL expressions must be handled as complete owned structures. A
partial restriction is more misleading than an omitted unsupported restriction.

## Proposed empirical-pattern semantics

The empirical summarizer should consider instance property assertions while
excluding structural and annotation predicates such as:

- `rdf:type`;
- `rdfs:label` and `rdfs:comment`;
- `skos:prefLabel`, `skos:altLabel`, and `skos:definition`;
- project identity metadata such as `onto:kind`;
- OWL, RDFS, and SHACL structural predicates.

An eligible statement with a resource object contributes to a
class-property-class pattern. An eligible statement with a literal object
contributes to a class-property-datatype pattern.

The evidence required by the main plan is:

- occurrence count;
- number of distinct subjects;
- population of the subject class;
- coverage within the subject class;
- a useful summary of per-subject cardinality.

The result must clearly identify when the subject or object lacks a usable class
instead of inventing a class assertion.

The implementation must not remove low-frequency patterns yet. Frequency alone
is not importance, and Proposal 2 has no business weights or query-usage data.

## Current graph characterization target

The repository graph currently contains 169 triples, including:

- 4 `owl:Class` declarations;
- 3 `rdfs:subClassOf` statements;
- 6 `owl:ObjectProperty` declarations;
- 10 `owl:DatatypeProperty` declarations;
- 12 resources typed `onto:Entity`;
- 18 instance relation or literal-fact assertions;
- one ontology declaration and one SHACL node-shape structure.

Under the proposed initial classification, the expected starting hypothesis is:

```text
current schema graph:             43 triples
current instance graph:          120 triples
current support/remainder graph:   6 triples
total:                           169 triples
```

The expected skeleton is also 43 triples because the current graph has no
declared domains, ranges, or OWL restrictions and its schema is already small.

The 18 instance assertions are expected to aggregate into approximately 17
class-property-range patterns under a most-specific-class policy. These are
hypotheses to verify after the policies below are decided, not numbers to force
by manipulating classification rules.

## Implementation decision gates

The implementing agent must stop at each applicable gate, present evidence and
the smallest reasonable alternatives, recommend one, and wait for user approval
before continuing. A convenient implementation is not itself approval.

### Decision gate 1: ambiguous or overlapping resource roles

**When:** After role discovery tests are written and the current graph has been
classified provisionally, before finalizing `graph_partition.py`.

**Question:** How should a resource that simultaneously plays schema, instance,
or support roles be handled?

Examples include metamodeling, a class also treated as an individual, or a blank
node referenced by both SHACL and OWL structures.

**Recommended starting rule:** Give explicitly recognized support structures
priority, treat explicit schema axioms as schema, and classify individual
assertions separately by triple rather than forcing each resource to have only
one global role. Never duplicate a triple across partitions.

**Evidence to show:** The conflicting triples, their source locations or
normalized form, the result under each alternative, and the effect on the
disjoint-union invariant.

If the current graph has no overlap and synthetic tests establish the intended
rule, report that result; user input is needed only if the policy affects real or
plausibly supported data in a way not settled here.

### Decision gate 2: supported OWL restriction subset

**When:** Before implementing restriction copying in `graph_skeleton.py`.

**Question:** Which restriction forms should Proposal 2 claim to support?

**Recommended starting option:** Support only direct restrictions attached
through `rdfs:subClassOf`, containing `owl:onProperty` and one of:

- `owl:someValuesFrom`;
- `owl:allValuesFrom`;
- `owl:hasValue`;
- unqualified `owl:cardinality`;
- unqualified `owl:minCardinality`;
- unqualified `owl:maxCardinality`.

Alternatives are to start with only value restrictions, or to defer all
restriction support until the source graph contains a real restriction. Do not
add qualified cardinalities, Boolean class expressions, RDF-list expressions,
property chains, imports, or general OWL closure without a new decision.

**Evidence to show:** Small synthetic source graphs for each proposed supported
form, at least one unsupported form, and the exact skeleton triples produced.

### Decision gate 3: class choice for empirical patterns

**When:** Before aggregating the first pattern records.

**Question:** Which class or classes represent a subject or resource object that
has multiple explicit types?

The current generated entities have generic types such as `onto:Entity`,
`owl:NamedIndividual`, and `skos:Concept` in addition to a domain class such as
`class:location`.

**Recommended starting rule:** Ignore metatypes, use the most-specific explicit
domain class according to the explicit `rdfs:subClassOf` hierarchy, and emit
multiple patterns when several incomparable most-specific domain classes remain.
Do not use a general OWL reasoner.

Alternatives include retaining every domain type or choosing one deterministic
type. Choosing one arbitrary type is discouraged because it loses information.

**Evidence to show:** Pattern output for one generic-plus-specific individual,
one individual with two incomparable domain types, and one untyped resource.

### Decision gate 4: cardinality and coverage definitions

**When:** Before naming the public evidence fields returned by
`observed_relationships()`.

**Question:** Which population is used for cardinality summaries, and how is
coverage defined?

**Recommended starting definitions:**

```text
occurrences       = distinct matching RDF triples
distinct_subjects = subjects with at least one matching value
class_population  = distinct current instances of the subject class
coverage          = distinct_subjects / class_population
cardinality       = min, median, and max values among participating subjects
```

Coverage separately represents subjects with zero values. An alternative is to
include zero-valued class members in the cardinality distribution, but that often
makes the median zero and duplicates information already conveyed by coverage.

**Evidence to show:** A fixture with class members having zero, one, and several
values, including the exact calculation under both definitions.

### Decision gate 5: empirical result representation

**When:** Before finalizing the return contract of `graph_patterns.py`.

**Question:** Should empirical patterns initially be plain Python records or a
derived RDF statistics graph?

**Recommended starting option:** Return a deterministically sorted list of plain
dictionaries containing RDF terms and numeric evidence. This avoids inventing a
statistics ontology and prevents observations from looking like declared domain
or range axioms.

A derived RDF representation should be chosen only if a concrete consumer needs
serialization during Proposal 2.

**Evidence to show:** The proposed record fields and one complete example for an
object relation and a literal fact.

### Decision gate 6: unexpected current-graph results

**When:** After running partition, skeleton, or empirical statistics against a
read-only load of `ontology.ttl`.

**Question:** Is a discrepancy caused by a wrong expectation, an implementation
bug, or an uncovered modeling case?

The counts in this document are characterization hypotheses. Do not distort the
implementation merely to produce them.

**Evidence to show:** Expected and actual counts, the precise differing triples
or patterns, and the smallest plausible explanations.

### Decision gate 7: any requested scope expansion

Stop before adding any of the following:

- graph serialization or a new CLI;
- a reasoner or another dependency;
- prompt integration;
- task relevance, traversal, ranking, or budgets;
- inferred schema axioms;
- SHACL generation;
- changes to identity or merge behavior;
- a generic abstraction shared only speculatively by future modules.

Explain why the expansion appears necessary and wait for approval.

## Test strategy

Use standard-library `unittest` and the existing `rdflib` dependency. Tests must
not call the network, require an API key, or write the repository graph.

Each fixture should be constructed as a new `Graph()` inside the test or loaded
from a file in `tempfile.TemporaryDirectory()`. When a test reads
`ontology.ttl`, capture its triple set before the operation and confirm that the
set and working-tree file remain unchanged afterward.

Compare RDF graphs by triple sets or graph isomorphism rather than serialized
Turtle text.

### `tests/test_graph_partition.py`

Cover at least:

1. Explicit class and property declarations enter the schema graph.
2. Subclass, domain, and range axioms enter the schema graph.
3. Labels and definitions follow the role of their subject.
4. Individual domain-class type statements enter the instance graph.
5. Object-property and datatype-property assertions enter the instance graph.
6. Instance labels, aliases, descriptions, and kind metadata remain instance
   statements.
7. The ontology declaration and complete SHACL blank-node structure enter the
   support graph.
8. A recognized OWL restriction structure enters the schema graph even when the
   skeleton does not support copying that restriction form.
9. An unknown statement enters the remainder instead of being guessed.
10. All three outputs retain useful namespace bindings.
11. The outputs are pairwise disjoint and their union equals the source.
12. Source serialization bytes are not compared, but its triple set remains
    unchanged.
13. The repository graph can be partitioned without writing `ontology.ttl`.

Add cases for ambiguous roles once decision gate 1 is resolved.

### `tests/test_graph_skeleton.py`

Cover at least:

1. Approved declarations, hierarchy, domain, range, labels, and definitions are
   retained.
2. Individuals and their annotations are absent.
3. Instance relations and literal values are absent.
4. Ontology metadata and SHACL structures are absent.
5. A supported restriction is copied as a complete structure.
6. An unsupported or incomplete restriction is omitted as a complete structure.
7. Referenced schema resources retain their available supported annotations.
8. No inferred domain, range, type, or hierarchy triple is added.
9. Namespace bindings are retained.
10. The schema input remains unchanged.

The exact restriction cases depend on decision gate 2.

### `tests/test_graph_patterns.py`

Cover at least:

1. Resource-valued assertions produce class-property-class patterns.
2. Literal-valued assertions produce class-property-datatype patterns.
3. Plain strings and explicitly typed literals have the approved range labels.
4. Duplicate RDF triples are naturally counted once.
5. Occurrences and distinct-subject counts differ when one subject has several
   values.
6. Coverage uses the approved subject-class population.
7. Cardinality statistics match the approved definition.
8. Generic project and RDF metatypes do not swamp domain classes.
9. Multiple incomparable types follow the approved policy.
10. Untyped subjects or objects are represented explicitly and not assigned an
    invented class.
11. Labels, comments, aliases, type statements, kind metadata, and schema
    predicates do not become empirical relationship patterns.
12. Low-frequency patterns are retained.
13. Results have deterministic ordering.
14. Neither input graph is changed.

The exact expected records depend on decision gates 3 through 5.

### Existing regression suite

Run the complete Proposal 1 suite after every production stage. Because Proposal
2 is not integrated into the current pipeline, all existing tests and prompt
expectations should remain unchanged.

Any existing test change requires an explanation and user approval. New modules
do not justify casually rewriting the baseline.

## Implementation sequence

### Stage 0: repository and baseline safety

1. Confirm the active branch is `proposal-02/skeleton`.
2. Inspect `git status --short` and preserve unrelated work.
3. Read this handoff, the main plan, Proposal 1 results, and the current graph
   modules before editing.
4. Run the complete existing test suite.
5. Record the current `ontology.ttl` triple set and high-level counts without
   saving it.
6. Confirm that no current code already calls the proposed module or function
   names.
7. Report the baseline before adding files.

Do not continue if the existing suite fails or required files contain
overlapping user changes.

### Stage 1: pin partition behavior with temporary fixtures

1. Add `tests/test_graph_partition.py` using only fresh or temporary graphs.
2. Express the approved straightforward classification cases first.
3. Add disjointness, exhaustiveness, namespace, and immutability assertions.
4. Add a read-only characterization test for the repository graph only if it is
   robust and cannot write the file.
5. Exercise decision gate 1 if ambiguous roles are found or need a policy.
6. Show the expected classifications before adding production code.

### Stage 2: implement graph partitioning

1. Create `graph_partition.py` with the smallest functions needed for role
   discovery and triple assignment.
2. Keep `partition_graph()` as the visible public operation.
3. Do not create persistent files or an object model for graph roles.
4. Run partition tests and the complete Proposal 1 suite.
5. Partition a read-only load of `ontology.ttl` and report counts and remainder
   contents.
6. Exercise decision gate 6 for any unexpected result.
7. Show the diff and results before starting skeleton work.

### Stage 3: decide and pin semantic-skeleton behavior

1. Add `tests/test_graph_skeleton.py` for the non-restriction core.
2. Exercise decision gate 2 and wait for approval of the restriction subset.
3. Add supported and unsupported restriction fixtures matching that decision.
4. Confirm every fixture is temporary and the schema input remains unchanged.
5. Show the expected skeleton triples before adding production code.

### Stage 4: implement the semantic skeleton

1. Create `graph_skeleton.py`.
2. Implement `create_graph_skeleton(schema_graph)` as a pure derived-graph
   operation.
3. Copy explicit supported statements only.
4. Handle supported blank-node restrictions as complete structures.
5. Run skeleton, partition, and complete regression tests.
6. Build a skeleton from the read-only current schema graph and report its
   contents and size.
7. Exercise decision gate 6 for any discrepancy.
8. Show the diff and result before starting empirical statistics.

Do not alter `source_parse.py` or put this skeleton into a prompt.

### Stage 5: decide and pin empirical-pattern semantics

1. Exercise decision gate 3 for class selection.
2. Exercise decision gate 4 for coverage and cardinality definitions.
3. Exercise decision gate 5 for the public result representation.
4. Add `tests/test_graph_patterns.py` only after those decisions are approved.
5. Cover resource, literal, multiple-type, untyped, and zero/one/many-value
   fixtures.
6. Show exact expected records before adding production code.

### Stage 6: implement empirical relationship statistics

1. Create `graph_patterns.py`.
2. Implement `observed_relationships(schema_graph, instance_graph)` with no
   filtering by frequency or invented importance.
3. Return results in deterministic order.
4. Preserve both input graphs.
5. Run pattern, skeleton, partition, and complete regression tests.
6. Calculate current-graph patterns and report the records and evidence fields.
7. Exercise decision gate 6 for unexpected results.
8. Show the diff and result before documentation cleanup.

Do not convert empirical records into RDF schema axioms or prompt text.

### Stage 7: documentation and final verification

1. Update the README module list to describe the actual implemented files and
   state that they are not yet part of prompt construction.
2. Create `proposal_02_schema_skeleton_results.md` from actual measurements; do
   not pre-fill it with planned results.
3. Record final partition counts, skeleton size, remainder contents, empirical
   pattern count, and resolved decision gates.
4. Run the full deterministic suite.
5. Run Python compilation checks for all modules.
6. Run `git diff --check`.
7. Inspect `git status --short`.
8. Confirm by diff and triple comparison that `ontology.ttl` was not changed.
9. Confirm that `source_parse.py`, `entity_lookup.py`, `graph_merge.py`, and the
   current CLI behavior were not changed.

## Verification after every stage

Every stage report should state:

- files added or changed;
- functions added;
- source graph before and after triple counts;
- whether `ontology.ttl` changed;
- exact test command and result;
- current partition, skeleton, or pattern observations;
- which decision gate was reached or resolved;
- any discrepancy;
- unrelated files intentionally left untouched.

Recurring checks should include:

```text
.venv/bin/python -m unittest discover -s tests
.venv/bin/python ontology.py --help
git diff --check
git status --short
git diff -- ontology.ttl
```

Do not run the live LLM. Proposal 2 needs no API key or network access.

## Commit discipline

Keep stages reviewable and preserve the Proposal 1 history.

Suggested commit boundaries, after tests and required review gates pass:

```text
test: define graph partition behavior
feat: derive schema instance and support views
test: define semantic skeleton behavior
feat: derive semantic skeleton
test: define empirical relationship statistics
feat: calculate empirical relationship statistics
docs: record proposal 2 results
```

Do not squash or rewrite reviewed Proposal 1 commits. Stage explicit files and
do not include unrelated work.

## Explicitly out of scope

Proposal 2 does not:

- send the skeleton to the LLM;
- remove or replace the current global prompt catalog yet;
- select concepts relevant to a source document;
- extract task-specific schema or instance subgraphs;
- define an always-present prompt core;
- add context token, character, or item budgets;
- add a tokenizer;
- add graph traversal or relevance ranking;
- perform locality-based OWL module extraction;
- perform general RDFS or OWL reasoning;
- serialize or maintain separate schema and instance files;
- add a CLI for derived artifacts;
- add semantic entity lookup;
- change identity thresholds or authority;
- validate parsed candidates;
- add provenance or conflict resolution;
- change merge behavior;
- generate SHACL shapes;
- generate purpose-specific exported views;
- add a new dependency.

## Completion criteria

Proposal 2 is complete only when:

- temporary tests protect the approved role-classification behavior;
- `partition_graph()` returns disjoint, exhaustive, read-only schema, instance,
  and support/remainder views;
- current-graph partition results are recorded from an actual run;
- the supported OWL restriction subset has been explicitly decided;
- `create_graph_skeleton()` produces only the approved explicit structure;
- unsupported or incomplete restriction structures do not leak partially into
  the skeleton;
- empirical class selection, coverage, cardinality, and output representation
  have been explicitly decided;
- `observed_relationships()` returns deterministic evidence-bearing patterns;
- empirical observations remain separate from declared schema;
- the source and all derived input graphs remain unchanged by downstream
  operations;
- `ontology.ttl` has no diff;
- prompt construction and the current pipeline remain unchanged;
- the complete deterministic regression suite passes without network access;
- actual results and all decision resolutions are documented;
- unrelated user work remains untouched.

At that point step 5 can design task-specific selection against known, measured
artifacts rather than trying to discover graph structure while simultaneously
building an LLM prompt.
