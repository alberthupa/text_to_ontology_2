# Initial architecture proposal

## 1. Recommendation in one sentence

Build this as a **modular monolith** with a small application API: text is turned
into stable document windows, each window produces a candidate RDF graph, and
only a dedicated merge module may publish validated triples to a named-graph RDF
dataset.

Do not introduce microservices, a plugin framework, or a general workflow engine
yet. The current program already contains several good module boundaries. The
next step is to make those boundaries explicit and give them small, stable input
and output contracts.

## 2. Main architectural decisions

1. **The durable data model is an RDF dataset, not one Turtle file.**
   Turtle remains a useful human-readable import/export format. The application
   works with named graphs through SPARQL. A local `rdflib.Dataset` can be the
   first backend; Apache Jena Fuseki/TDB2 can replace it without changing domain
   modules.
2. **A graph is passed by reference, not copied into every module.**
   A module receives a graph store plus the names of the graphs it may read or
   write. This works both with an in-process RDFLib dataset and a remote Jena
   server.
3. **Every meaningful intermediate knowledge result is a graph.**
   The LLM may continue returning JSON because that boundary is reliable and
   easy to validate. Immediately after parsing, the JSON is converted into a
   candidate RDF graph. Context, candidates, accepted data, review data, schema,
   shapes, and provenance then move between modules as graphs or graph names.
4. **Only one module writes accepted knowledge.**
   Context selection, extraction, validation, identity resolution, and merge
   planning are read-only. The publisher applies an already completed merge plan
   in one transaction.
5. **Long text is a first-class input case.**
   A source document is split into stable, overlapping windows before context
   selection and extraction. The whole document is never silently truncated.
6. **Declared schema and observed usage remain different.**
   RDFS/OWL axioms come from schema graphs. Patterns inferred from instance data
   are evidence only and must not silently become ontology axioms.
7. **Use standard semantic technologies.**
   Use RDF 1.1 datasets, SPARQL 1.1 Query/Update, the SPARQL Graph Store Protocol,
   RDFS, OWL, SKOS, SHACL, PROV-O, Dublin Core Terms, and established domain
   vocabularies such as FOAF where appropriate. Do not create a custom workflow,
   validation, provenance, or graph-management vocabulary.

Project-owned URIs are still necessary for actual domain classes, properties,
and individuals that have no suitable established vocabulary. That is ordinary
ontology content, not a new semantic-technology mechanism.

## 3. Proposed end-to-end flow

```text
file / directory / future API text
              |
              v
      discover and read sources
              |
              v
     split document into windows
              |
              v
  for each window, in stable order:
      select relevant RDF context with SPARQL
              |
              v
      build prompt and call LLM
              |
              v
      parse JSON into a candidate RDF graph
              |
              v
      validate candidate graph and SHACL shapes
              |
              v
      resolve identities and plan merge (read-only)
              |
              v
      publish accepted triples in one transaction
      route unsafe candidates to review
              |
              v
      next window sees the newly accepted graph
```

The initial implementation should remain sequential. It preserves the useful
current property that later input sees earlier accepted knowledge and keeps
identity decisions deterministic. Parallel LLM extraction can be added later,
but merge publication should remain ordered and single-writer.

## 4. The small application API

The CLI should not contain the pipeline. It should translate command-line
arguments into one request and call an ordinary Python function:

```python
def run_text_to_graph(request, graph_store, extractor, reporter):
    """Run one text-to-graph job and return a RunResult."""
```

The same function can later be called by a web API, a notebook, tests, or another
Python program. No HTTP server is needed now.

Use small named records, preferably plain dataclasses, for non-RDF control data:

```text
RunRequest
  source
  data_graphs
  schema_graphs
  shape_graphs
  target_graph
  windowing
  context
  extraction
  merge

RunResult
  run_id
  processed_documents
  processed_windows
  accepted_triples
  duplicate_triples
  review_items
  errors
```

Configuration should be module-specific and explicit: `WindowingConfig`,
`ContextConfig`, `ExtractionConfig`, and `MergeConfig`. Avoid a large untyped
`params` dictionary and avoid modules reading environment variables directly.
Only the composition root should turn environment variables and CLI arguments
into configuration.

## 5. Common module conventions

Do not force every operation into one generic `Module` base class. That would
hide useful differences. Use normal functions with clear names and follow these
conventions:

- A source-only module receives text or a source record.
- A graph-reading module receives `graph_store`, input graph names, and its own
  configuration.
- A graph-producing module returns an RDF graph or the name of a newly written
  staging graph, plus a small report.
- Read-only modules never call SPARQL Update.
- Only the publisher may update the target data graph.
- A module never imports the pipeline/orchestrator.
- A module never opens a Turtle file or creates its own Jena connection.
- Results are deterministic for the same input graphs, input text, and params,
  except for the external LLM response.
- Errors identify the document, window, module, and reason in plain language.

Suggested public functions are intentionally boring:

```python
find_sources(source, config) -> list[SourceDocument]
read_document(source) -> SourceDocument
split_document(document, config) -> list[TextWindow]

select_context(store, graph_names, window, config) -> ContextBundle
extract_candidates(window, context, extractor, config) -> ExtractionResult
build_candidate_graph(extraction, context, config) -> CandidateBundle
validate_candidate_graph(store, candidate, shape_graphs, config) -> ValidationResult
plan_merge(store, target_graph, candidate, config) -> MergePlan
publish_merge(store, plan) -> MergeResult
```

`ContextBundle` and `CandidateBundle` contain an RDF graph as their main payload.
They may also contain diagnostics that do not belong in RDF, such as token counts
or validation messages.

## 6. RDF dataset layout

Use named graphs and assign their roles in application configuration. Do not
infer their role by scanning and partitioning every triple on every run.

| Graph role | Contents | Mutability |
|---|---|---|
| Schema graphs | Declared RDFS/OWL/SKOS vocabulary and ontology imports | Curated or seed-tool managed |
| Shape graphs | One or more SHACL shape sets | Curated or seed-tool managed |
| Data graphs | Accepted entities and assertions | Updated only by publisher |
| Provenance graph | Standard PROV-O provenance and RDF reification where statement-level provenance is required | Append/update by publisher |
| Candidate graphs | One staging graph per window or document | Temporary or retained for audit |
| Review graphs | Candidate triples withheld from accepted data | Written by publisher, never used as canonical facts |
| Derived graphs/cache | Optional skeleton or observed-pattern products | Rebuildable |

Graph names should be supplied by configuration. The architecture must not
hard-code one schema graph or one shape graph. A run can receive lists such as
`schema_graphs`, `shape_graphs`, and `data_graphs`, plus one explicit
`target_graph`.

The current schema/instance/support partitioner remains useful for importing the
old combined Turtle graph and for the viewer. In the new storage model, graph
placement gives the primary separation and avoids repeatedly classifying the
entire growing dataset.

### Provenance without a custom vocabulary

Use a named candidate/source graph as a `prov:Entity`; model an extraction as a
`prov:Activity`; connect it to its source document or window with
`prov:used`/`prov:wasDerivedFrom`. Use Dublin Core Terms for identifiers and
source metadata when their meanings fit. If individual accepted statements need
provenance, use standard RDF reification plus PROV-O.

There is no broadly accepted RDF property for extraction confidence or merge
status. Keep confidence, validation issues, and policy reasons in the run report
or operational metadata rather than inventing an ontology for them. Candidate
and review graph placement already expresses whether triples were published.

## 7. Graph store boundary and Jena migration

Domain modules should depend on a very small graph-store interface:

```python
class GraphStore:
    def query(self, sparql, bindings=None): ...
    def update(self, sparql, bindings=None): ...
    def get_graph(self, graph_name): ...
    def put_graph(self, graph_name, graph): ...
    def delete_graph(self, graph_name): ...
    def transaction(self): ...
```

This is an application interface, not a replacement for SPARQL. Its first
implementation can wrap `rdflib.Dataset`. A later implementation can call Jena
Fuseki using SPARQL Query, SPARQL Update, and the Graph Store Protocol. TDB2 is
then the database behind Fuseki; application modules do not need to know it
exists.

Turtle should be used for one graph at a time when humans need to read it. Use
TriG or N-Quads when importing/exporting a complete multi-graph dataset.

Important storage rules:

- Do not fetch the entire data graph for context selection or identity lookup.
  Ask focused SPARQL queries.
- Keep one writer initially.
- Plan against a consistent dataset state and publish in a transaction.
- The local backend should retain today's safe behavior: work on a copy and
  replace the persisted file atomically.
- The remote backend should use the database transaction supported by Jena.
- SPARQL queries live next to the module that owns them and have descriptive
  names. Never build them by concatenating untrusted source text.

## 8. Long-document handling

Introduce two simple records:

```text
SourceDocument
  document_id       stable digest of normalized source bytes
  source_name       path, URL, or caller-supplied name
  text
  media_type

TextWindow
  window_id         document_id + strategy version + window index
  document_id
  index
  text
  start_character
  end_character
```

The first windowing strategy should be simple:

1. Split on headings and paragraph boundaries.
2. Pack complete paragraphs up to a target token count.
3. Carry approximately 10% overlap from the previous window.
4. If one paragraph is too large, split it by sentence; use a hard character
   boundary only as the final fallback.
5. Never discard the tail of the document.

The controls belong in `WindowingConfig`:

```text
target_tokens
overlap_tokens
maximum_tokens
minimum_window_tokens
strategy_version
```

Use the real tokenizer for the configured extraction model when possible. Keep
the current character estimator as a fallback. Store offsets and the strategy
version so a window can be reproduced and cited.

Each window gets its own selected graph context. The source budget and ontology
context budget are separate. A longer document creates more windows; it must not
make the ontology context silently disappear as happens when the full source is
charged against one prompt.

Overlap will produce duplicates. That is expected. Exact-triple corroboration,
stable window provenance, and the existing merge policy should absorb it.
Initially merge windows sequentially. Later, candidate graphs from all windows
of one document may be unioned into a document candidate graph and reconciled
before publication.

## 9. Context and skeleton selection

The current separation is good and should remain:

```text
relevance selection decides what matters
budget packing decides what fits
```

Change the context module so it works from explicit input graph lists and
focused SPARQL queries. Its configuration should include:

```text
schema_graphs
shape_graphs
data_graphs
include_declared_schema
include_observed_patterns
hierarchy_hops
instance_hops
maximum_classes
maximum_properties
maximum_resources
maximum_examples
context_token_budget
```

The selected result should be a small context RDF graph. Rendering that graph
for an LLM is a separate adapter and may still produce compact human-readable
lines instead of dumping Turtle.

The skeleton provider should have replaceable strategies with one simple
interface:

```python
select_skeleton(store, schema_graphs, source_concepts, config) -> Graph
```

Start with the current explicit structure only: class/property declarations,
labels, subclass links, domain/range, and complete supported OWL restrictions.
Do no inference. Later strategies may query a precomputed skeleton graph or a
cached schema projection. Selecting a strategy and its parameters must not
change extraction or merge modules.

Observed relationship patterns remain a separate optional input and should be
clearly marked as evidence. They may suggest future RDFS/OWL axioms or SHACL
shapes, but another explicit tool or human decision must create those axioms.

## 10. Candidate graph, validation, identity, and merge

### Candidate graph

Do not ask the LLM to emit Turtle initially. Keep the explicit JSON contract and
validate its syntax. Then map valid records to a staging RDF graph using:

- existing URIs when the model selected an exact URI shown in context;
- stable temporary URIs for unresolved candidate resources;
- RDF types rather than a separate string-valued `kind` field in the graph;
- XSD datatypes for confidently parsed dates, numbers, booleans, and other
  ordinary literals;
- standard labels (`rdfs:label`, `skos:prefLabel`, `skos:altLabel`) where they
  fit their defined meanings.

The candidate graph is never automatically canonical. It is the extracted
subgraph requested in the backlog and is inspectable before merge.

### Validation

Validation has two independent layers:

1. **Response validation:** JSON structure, required fields, references, scalar
   types, confidence bounds, and deterministic normalization.
2. **Graph validation:** RDF role collisions, configured SHACL shapes, and
   compatibility with the target schema/data graphs.

One response-validation failure may enter a bounded repair loop, for example two
attempts. The final failure still rejects the window. SHACL validation must run
before publication. A validation report is not itself an ontology.

### Entity identity

Keep identity resolution as its own read-only module. It should query the whole
configured identity scope, not just prompt context:

1. exact URI explicitly shown to the model;
2. unique exact preferred/alternative label plus compatible RDF type;
3. ambiguous exact match goes to review;
4. close spelling is a review suggestion, not an automatic merge;
5. embeddings or a Jena text index may later provide suggestions, never silent
   identity by themselves.

The current full in-memory entity catalog is acceptable for the local backend.
For Jena, replace it with focused SPARQL lookup and an optional rebuildable text
index. The RDF dataset remains the source of truth; the index is only an
optimization.

### Merge

Preserve the present plan/apply split:

- `plan_merge` is read-only and returns every identity and triple decision.
- `publish_merge` contains no identity logic; it applies the plan transactionally.
- Existing canonical assertions are not overwritten automatically.
- Exact duplicates become additional provenance, not additional triples.
- Explicit OWL functional or inverse-functional conflicts go to review.
- Low-confidence new assertions go to review.
- Dry run stops after planning and returns the same report without updating RDF.

## 11. Suggested package structure

This is a target layout, not a request to move every file immediately:

```text
text_to_ontology/
  api.py                    public run_text_to_graph()
  pipeline.py               readable orchestration only
  config.py                 named configuration records
  source/
    discover.py
    read.py
    window.py
  context/
    concepts.py
    select.py
    skeleton.py
    patterns.py
    render.py
    budget.py
  extraction/
    prompt.py
    candidate_graph.py
    repair.py
  merge/
    validate.py
    identity.py
    plan.py
    publish.py
  store/
    base.py
    rdflib_store.py
    fuseki_store.py
  adapters/
    openrouter.py
  reporting/
    run_report.py
  tools/
    view.py
    seed.py                 later, separate command
```

Keep current file names while introducing these boundaries if moving them would
create noise. Move a file only when it is already being changed for a functional
reason.

### Mapping from the current files

| Current responsibility | Proposed home |
|---|---|
| `ontology.py` CLI and loop | thin CLI plus `api.py` and `pipeline.py` |
| `ingest_sources.py` | `source/discover.py`, `source/read.py`; add `source/window.py` |
| `graph_management.py` | `store/rdflib_store.py`, later `store/fuseki_store.py` |
| context and prompt-budget files | `context/`, keeping their present separation |
| `source_parse.py` and `llm.py` | extraction prompt plus OpenRouter adapter |
| `candidate_validation.py` | response validation plus graph validation |
| `entity_lookup.py` | `merge/identity.py` |
| `merge_policy.py` | `merge/plan.py` |
| `graph_merge.py` | `merge/publish.py` |
| partition/skeleton/pattern files | `context/` and viewer/import compatibility |
| viewer files | `tools/view.py` and its render helpers |

## 12. Separate seed-graph tool

Seed creation should not happen implicitly when the extraction pipeline opens an
empty path. A later `seed` command should be a separate application using the
same graph-store boundary.

Its responsibilities are:

- import one or more RDF schema graphs;
- import one or more SHACL shape graphs;
- optionally build a small starter schema from explicitly supplied material;
- validate syntax and SHACL shapes;
- show a plan/diff;
- write only after explicit confirmation or a non-interactive flag;
- export Turtle/TriG for human inspection.

It should not ingest ordinary documents, call the normal fact-extraction merge,
or automatically promote observed patterns to schema.

## 13. Delivery sequence

### Phase 1 — establish boundaries without changing behavior

- Split CLI parsing from `run_text_to_graph()` orchestration.
- Add the small graph-store interface and an RDFLib implementation around the
  current Turtle behavior.
- Move settings into named configuration records.
- Preserve all current tests and read-only plan/copy/atomic-save guarantees.

### Phase 2 — add long-document and candidate-graph support

- Add stable documents and windows.
- Add per-window provenance and idempotency digests.
- Convert validated extraction JSON into inspectable candidate RDF graphs.
- Run the existing validation/plan/publish flow per window, sequentially.
- Add the bounded repair loop and a real tokenizer.

### Phase 3 — move from one graph to an RDF dataset

- Introduce configured named graphs for schema, shapes, accepted data,
  provenance, candidates, and review.
- Import the current `ontology.ttl` once.
- Make context and identity modules query explicit graph lists.
- Keep Turtle export and add TriG/N-Quads dataset export.

### Phase 4 — add Jena and SHACL enforcement

- Implement the Fuseki graph-store adapter.
- Use focused SPARQL rather than loading full graphs.
- Add transactional publication and SHACL validation before commit.
- Cache only rebuildable derived products, keyed by input graph versions.

### Phase 5 — separate seed tooling and scale optimizations

- Add the seed-graph command.
- Add an optional entity text index for suggestions.
- Add safe source replacement/selective unmerge based on provenance.
- Consider parallel extraction only after deterministic ordered publication and
  idempotency are proven.

## 14. Backlog placement

The items from `ox_recommendations.md` fit as follows:

| Backlog item | Architectural home |
|---|---|
| Repair loop | extraction module, before final response rejection |
| Provenance | provenance named graph using PROV-O and RDF reification |
| Re-run idempotency | source/window digests checked by the pipeline |
| Cached views | rebuildable context/skeleton cache keyed by graph version |
| Stronger identity | independent identity module plus optional text index |
| Chunk long sources | source window module |
| Typed facts | candidate graph mapping with XSD datatypes |
| SHACL enforcement | graph validation before transactional publication |
| Real tokenizer | window and prompt-budget adapter |
| Dry run | stop after merge planning |
| Parallel extraction | later pipeline optimization; ordered merge remains |

## 15. What not to build now

- No microservices. The modules need process boundaries only when operational
  evidence demands them.
- No dynamic plugin registry or generic DAG engine.
- No custom RDF workflow/status/provenance vocabulary.
- No automatic ontology inference in the skeleton selector.
- No automatic promotion of observed patterns into RDFS/OWL/SHACL.
- No direct canonical write from the LLM or candidate parser.
- No requirement that every module load the complete graph into memory.
- No parallel merge writers.
- No repository-wide file move merely to make the tree look architectural.

## 16. Definition of success for the initial architecture

The architecture is working when all of these are true:

- The CLI, a test, and a future API can call the same `run_text_to_graph()`
  function.
- A document larger than one model context window is fully processed as stable
  windows with no lost tail.
- Every extraction has an inspectable candidate RDF graph before merge.
- Context selection, validation, identity, and planning can be tested without
  writing to the canonical graph.
- The publisher is the only accepted-data writer and its update is atomic.
- Multiple schema and SHACL graphs can be selected by configuration.
- Switching from the local RDFLib store to Jena changes an adapter, not domain
  modules.
- Turtle remains available for people, while SPARQL and named graphs are the
  application boundary.
- Only standard RDF/RDFS/OWL/SKOS/SHACL and established vocabularies are used for
  semantic infrastructure.

This keeps the program understandable for a non-advanced developer while giving
it a clean path from the current single-file experiment to a larger RDF-backed
application.
