# Dead simple text to ontology

This is a deliberately small experiment, not a framework. Give it one text file
or a directory of text-like files. It asks an LLM to extract entities,
relations, and literal facts, then saves them in one Turtle (`.ttl`) graph.

Running it again with the same graph adds knowledge to that graph. For each
source file it picks the part of the current graph that text actually relates to
— relevant classes and properties, how the existing data uses them, and the
existing resources it may be talking about — and shows the LLM only that, inside
a token budget. Exact-name and very conservative spelling matching provide a
local fallback, and that fallback still searches the whole graph, not just what
was sent.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure OpenRouter

Create a `.env` file beside `ontology.py`:

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

Create a seed graph from one file:

```bash
python ontology.py notes.txt ontology.ttl
```

Add another file to that same graph:

```bash
python ontology.py more_notes.md ontology.ttl
```

Or recursively read all supported text-like files in a directory:

```bash
python ontology.py documents/ ontology.ttl
```

If the second argument is omitted, the output is `ontology.ttl`:

```bash
python ontology.py documents/
```

That is the whole workflow. Open `ontology.ttl` in a text editor to see or edit
the RDF/RDFS/OWL/SHACL/SKOS graph directly.

For each file the run prints one line about the context it selected, for example
`Context: 32 items, 1333/1400 tokens, 21 items did not fit`. The numbers behind
it live in `PROMPT_BUDGET` in `prompt_budget.py`; `context_tokens` is the ceiling
on how much ontology context one prompt may carry, and lowering it makes the
prompt smaller by dropping the least relevant items first.

## Files

The pipeline that runs when you invoke the program:

- `ontology.py` — the command line and the run loop
- `ingest_sources.py` — finding and reading source files
- `source_parse.py` — building the prompt and parsing the LLM's answer
- `entity_lookup.py` — deciding whether an entity is already in the graph
- `graph_merge.py` — writing one parsed result into the graph
- `graph_management.py` — opening, seeding, naming, and saving the graph
- `llm.py` — the tiny OpenRouter client

Choosing what the LLM gets to see. All read-only: none of these writes to the
graph, and each one can be read, tested, or replaced on its own:

- `source_concepts.py` — what one text mentions, before any ontology is opened.
  Deliberately simple for now, and free of RDF so it can later be replaced by
  NLP, NER, embeddings, or a small model without changing anything else
- `task_context.py` — align the text with the graph and select the relevant
  classes, properties, observed usage, resources, and example assertions
- `context_render.py` — turn that selection into compact lines an LLM can read,
  keeping declared structure and observed usage visibly apart
- `prompt_budget.py` — estimate tokens and keep only the complete items that fit.
  The token counter is swappable for a real tokenizer later

Read-only tools that derive smaller views of an existing graph:

- `graph_partition.py` — split a graph into schema, instance, and support views
- `graph_skeleton.py` — copy the explicit class and property core out of a
  schema view
- `graph_patterns.py` — report which class-property-range patterns the instance
  data actually contains, with evidence
- `ontology_views.py` — hand back all of the above as one group of views

And the rest:

- `requirements.txt` — the one dependency (`rdflib`)
- `ontology.ttl` — your graph, created when you first run the program

The accepted directory file extensions are listed near the top of
`ingest_sources.py`. A directly supplied file is always read, regardless of
extension.

## Read more
TTL Graph Generalization techniques
What about wiki?