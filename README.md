# Dead simple text to ontology

This is a deliberately small experiment, not a framework. Give it one text file
or a directory of text-like files. It asks an LLM to extract entities,
relations, and literal facts, then saves them in one Turtle (`.ttl`) graph.

Every source file is one document with a stable content-derived ID. A long
document is split into reproducible overlapping windows, and each window's
answer is admitted into that document's own *source staging graph* before
anything canonical happens: a later window sees what earlier windows already
extracted (clearly marked `(this document)` in its prompt), repeated names are
reconciled inside the document instead of duplicated, and anything ambiguous or
conflicting is held for review rather than silently merged. The final ontology
is only touched after a document's last window was admitted. Identity against
the whole existing graph is still decided explicitly at that point: an exact
identifier or a unique exact name/alias match resolves to the existing entity,
an ambiguous or close-spelling match is held for review, and only confident,
unambiguous records create new entities.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

`pyproject.toml` is the single dependency declaration (`rdflib` is the only
runtime dependency); there is no `requirements.txt`. Python 3.12+ is required.
The tests need the same editable install:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Configure OpenRouter

Create a `.env` file in the directory you run the program from:

```text
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL=openrouter/pareto-code:nitro
```

`OPENROUTER_MODEL` is optional; its default is the speed-optimized Pareto router
`openrouter/pareto-code:nitro`. You can also use exported shell variables:

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="openrouter/pareto-code:nitro"
```

## Use

After installing, use one of three equivalent commands (the console script,
the module entry point, or the legacy root wrapper):

```bash
text-to-ontology notes.txt ontology.ttl
python3 -m text_to_ontology notes.txt ontology.ttl
python ontology.py notes.txt ontology.ttl
```

Add another file to that same graph:

```bash
text-to-ontology more_notes.md ontology.ttl
```

Or recursively read all supported text-like files in a directory:

```bash
text-to-ontology documents/ ontology.ttl
```

If the second argument is omitted, the output is `ontology.ttl`:

```bash
text-to-ontology documents/
```

Save a detailed report as a timestamped Markdown file under `reports/runs/`:

```bash
text-to-ontology documents/ ontology.ttl --report
```

`--report` writes to the file only, so a successful run stays silent in the
terminal. The report includes the exact system and user messages sent to the
extraction LLM. Generated reports are ignored by Git because
they may be large and may contain source-derived information.

That is the whole workflow. Open `ontology.ttl` in a text editor to see or edit
the RDF/RDFS/OWL/SHACL/SKOS graph directly.

## Call it from Python

The public API is one function. The CLI is a thin adapter over it:

```python
from pathlib import Path

from text_to_ontology.api import RunRequest, run_text_to_graph
from text_to_ontology.graph_management import LocalTurtleStore
from text_to_ontology.llm import OpenRouterExtractor
from text_to_ontology.run_report import RunReporter

result = run_text_to_graph(
    RunRequest(source=Path("notes.txt"), graph_path=Path("ontology.ttl")),
    graph_store=LocalTurtleStore(),
    extractor=OpenRouterExtractor(),
    reporter=RunReporter(verbose=False),
)
print(result.triples, "triples in", result.graph_path)
```

`RunRequest` carries the source, the graph path, and the configuration:
`WindowingConfig` (window target/overlap size in tokens), `ContextConfig`,
`ExtractionConfig`, `MergeConfig`, and `ProcessingConfig`
(`retain_staging_on_failure` exports a failed document's staging graphs to a
sidecar TriG file next to the output graph for diagnosis; by default they are
discarded).
When the model's answer is messy — unparseable JSON or a contract violation —
it is sent back to the model for self-repair up to
`ExtractionConfig(repair_attempts=...)` times (default 2; 0 disables repair)
before the window is rejected. Every answer, repaired or not, must pass the
same validation gate.
Any adapter can be replaced — pass an object with `model()` and
`extract(prompt)` as the extractor (a fake in tests), or anything with
`load(path)` and `save(graph, path)` as the graph store. The core pipeline
never parses arguments, reads environment variables, or exits the process.

## Look at the graph

The viewer derives five read-only views of an existing graph and explains each
one: the schema / instance / support partitions, the declared skeleton copied
out of the schema, and the usage patterns observed in the instance data.

```bash
python view_ontology.py                            # print the report for ontology.ttl
python view_ontology.py other.ttl                  # a different graph
python view_ontology.py -html                      # write ontology_views.html
python view_ontology.py other.ttl -html out.html   # a different graph, a chosen file
```

The HTML page is one standalone file with no external assets. Besides the same
numbers the terminal prints, it walks through how each view is derived, browses
every statement, every declared class and property, every observed pattern,
every entity, and the whole provenance trail, and ends with a glossary. Its
search boxes, filters, and sliders only change what is displayed — what a view
contains is decided in the code before the page is generated, and there are no
filter options on the command line for the same reason.

For each document the run prints one line about its staging graph and windows,
for example `Document doc-13ed72f8: 6 window(s); staging graph ...`, plus one
`Window k/n admitted ...` line per window showing how the source graph grew.
The numbers behind the prompt budget live in `PROMPT_BUDGET` in
`prompt_budget.py`; `context_tokens` is the ceiling
on how much ontology context one prompt may carry, and lowering it makes the
prompt smaller by dropping the least relevant items first.

Each non-empty window's answer is validated before it may change anything. The
run prints a `Validated:` line, then plans the merge and prints a `Planned:`
line before anything is written. Every record the model returns must carry a
`confidence` from 0.0 to 1.0 — the model's confidence that the source text
directly supports that complete record. New assertions below `0.80` confidence
are not merged; they are retained as review records instead. Exact duplicates
of existing statements are kept as corroboration evidence, not re-added, and
disagreements with explicit functional constraints go to review rather than
overwriting anything: existing canonical statements are never replaced
automatically.

Every valid extraction leaves provenance in the graph: where the source came
from (path and content digest), which model extracted it, and per-record
normalized content, confidence, decision, and reason codes. These audit records
live in the support partition of the graph — they never appear as entities, in
prompts, or in usage statistics. A validation error still leaves the graph and
file unchanged for that source, and exits with a short list of the offending
paths and codes. Saves are atomic: a failed write never damages the previous
graph file.

## Files

All importable code lives in the `text_to_ontology` package under `src/`.
The root scripts `ontology.py` and `view_ontology.py` are thin compatibility
wrappers that call the packaged modules, so both old workflows keep working.

The pipeline that runs when you invoke the program:

- `src/text_to_ontology/api.py` — the documented public API and its exports
- `src/text_to_ontology/pipeline.py` — the run loop, the request/result
  dataclasses, and the extractor/reporter contracts
- `src/text_to_ontology/cli.py` — the command line: argument parsing, adapters,
  exit codes (also reachable as `python3 -m text_to_ontology`)
- `src/text_to_ontology/run_report.py` — normal and verbose run reporting to
  the terminal, a file, or any supplied text stream
- `src/text_to_ontology/ingest_sources.py` — finding and reading source files
- `src/text_to_ontology/source_parse.py` — building the prompt and parsing the
  LLM's answer
- `src/text_to_ontology/candidate_validation.py` — validating and normalizing a
  response before merge
- `src/text_to_ontology/merge_policy.py` — read-only merge planning: identity
  decisions, acceptance, corroboration, conflict review, and provenance
- `src/text_to_ontology/entity_lookup.py` — deciding whether an entity is
  already in the graph
- `src/text_to_ontology/candidate_graph.py` — turning one validated response
  into an inspectable RDF candidate graph with PROV-O/DQV confidence
- `src/text_to_ontology/source_staging.py` — one provisional source graph per
  document: stable staging-graph names, source-local admission planning, the
  marked layered prompt context, and diagnostic retention on failure
- `src/text_to_ontology/windowing.py` — stable documents and reproducible
  overlapping text windows
- `src/text_to_ontology/graph_merge.py` — materializing a completed plan (and
  the legacy direct merger) into the graph
- `src/text_to_ontology/graph_management.py` — opening, seeding, naming, and
  atomically saving the graph
- `src/text_to_ontology/llm.py` — the tiny OpenRouter client

Choosing what the LLM gets to see. All read-only: none of these writes to the
graph, and each one can be read, tested, or replaced on its own:

- `src/text_to_ontology/source_concepts.py` — what one text mentions, before
  any ontology is opened. Deliberately simple for now, and free of RDF so it
  can later be replaced by NLP, NER, embeddings, or a small model without
  changing anything else
- `src/text_to_ontology/task_context.py` — align the text with the graph and
  select the relevant classes, properties, observed usage, resources, and
  example assertions
- `src/text_to_ontology/context_render.py` — turn that selection into compact
  lines an LLM can read, keeping declared structure and observed usage visibly
  apart
- `src/text_to_ontology/prompt_budget.py` — estimate tokens and keep only the
  complete items that fit. The token counter is swappable for a real tokenizer
  later

Read-only tools that derive smaller views of an existing graph:

- `src/text_to_ontology/graph_partition.py` — split a graph into schema,
  instance, and support views
- `src/text_to_ontology/graph_skeleton.py` — copy the explicit class and
  property core out of a schema view
- `src/text_to_ontology/graph_patterns.py` — report which
  class-property-range patterns the instance data actually contains, with
  evidence
- `src/text_to_ontology/ontology_views.py` — hand back all of the above as one
  group of views
- `src/text_to_ontology/view_ontology.py` — the viewer's command line: print
  those views, or write them as an explained HTML page
- `src/text_to_ontology/view_report.py` — turn the views into plain data, with
  no HTML anywhere in it
- `src/text_to_ontology/view_html.py` — render that data as one self-contained
  page, explanations included

And the rest:

- `pyproject.toml` — package metadata and the one dependency (`rdflib`)
- `tests/fixtures/miniature_repository.ttl` — the frozen miniature graph the
  exact partition/skeleton/pattern tests run against
- `ontology.ttl` — your graph, created when you first run the program

The accepted directory file extensions are listed near the top of
`ingest_sources.py`. A directly supplied file is always read, regardless of
extension.

## Read more
TTL Graph Generalization techniques
What about wiki?
