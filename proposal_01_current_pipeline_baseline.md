# Proposal 01: Describe the Current Pipeline

## Purpose

Before changing how ontology context is selected or how graphs are merged, create
a small, trustworthy description of what the program does today. This gives us a
baseline against which later changes can be evaluated.

This step is observational. It should not change the program.

## Current flow

For each input file, the program currently:

1. Opens the existing Turtle graph, or creates a minimal new graph.
2. Builds an entity catalog from all resources typed as `onto:Entity`.
3. Collects the labels of existing object and datatype properties.
4. Sends the source text, complete entity catalog, and property names to the LLM.
5. Receives candidate entities, relations, and literal facts as JSON.
6. Resolves entities using the LLM's selected identifier and conservative local
   name-and-kind matching.
7. Adds the extracted statements directly to the in-memory graph.
8. Serializes the graph after processing each file.

## Important characteristics

- The entity catalog grows with the instance data and is included in every LLM
  request.
- Classes and properties are created as extraction results are ingested.
- The LLM result is written directly into the graph; there is no separate
  candidate or validation stage.
- Existing RDF triples naturally prevent exact duplicate triples, but broader
  identity conflicts and contradictory assertions are not handled explicitly.
- The graph does not record which source or extraction produced a statement.
- Processing a directory is sequential, so additions from one file become
  context for the next file.

## Proposed baseline exercise

Use a tiny, fixed set of documents to observe the present behavior:

1. A document that introduces only new entities and relationships.
2. A document that refers to one of those entities by the same name.
3. A document that refers to it by an alias or close spelling.
4. A document that may refer to a different entity with a similar name.

For each run, record:

- input file and order;
- graph triple count before and after;
- number of existing entities included in the prompt;
- new and resolved entity counts;
- relation and fact counts;
- any duplicate entity, incorrect resolution, or conflicting assertion;
- approximate prompt size as the graph grows.

The baseline can initially be a short Markdown table created from one manual run.
There is no need to build a benchmark framework yet.

## Deliverable

A concise baseline note containing:

- the fixed input documents;
- the observations listed above;
- one saved output graph for inspection;
- a short list of concrete limitations observed during the run.

This gives the next step a precise starting point: we can change ontology context
selection and compare the result with known current behavior.

## Out of scope

This step does not:

- split the TBox and ABox;
- extract a semantic skeleton;
- introduce OWL module extraction;
- add SHACL validation;
- change entity resolution or graph merging;
- reorganize the Python files.

Those decisions should follow only after the current behavior is visible in a
small reproducible example.

## Completion criterion

Point 1 is complete when another person can read the baseline note and understand
what enters the LLM context, what the LLM returns, how that output enters the
graph, and which observed behavior a later change must preserve or improve.
