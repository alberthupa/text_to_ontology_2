# Dead simple text to ontology

This is a deliberately small experiment, not a framework. Give it one text file
or a directory of text-like files. It asks an LLM to extract entities,
relations, and literal facts, then saves them in one Turtle (`.ttl`) graph.

Running it again with the same graph adds knowledge to that graph. Existing
labels, aliases, types, and descriptions are shown to the LLM so it can resolve
entities. Exact-name and very conservative spelling matching provide a local
fallback.

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

## Files

The pipeline that runs when you invoke the program:

- `ontology.py` — the command line and the run loop
- `ingest_sources.py` — finding and reading source files
- `source_parse.py` — building the prompt and parsing the LLM's answer
- `entity_lookup.py` — deciding whether an entity is already in the graph
- `graph_merge.py` — writing one parsed result into the graph
- `graph_management.py` — opening, seeding, naming, and saving the graph
- `llm.py` — the tiny OpenRouter client

Read-only tools that derive smaller views of an existing graph. Nothing in the
pipeline calls them yet, and none of them takes part in prompt construction:

- `graph_partition.py` — split a graph into schema, instance, and support views
- `graph_skeleton.py` — copy the explicit class and property core out of a
  schema view
- `graph_patterns.py` — report which class-property-range patterns the instance
  data actually contains, with evidence

And the rest:

- `requirements.txt` — the one dependency (`rdflib`)
- `ontology.ttl` — your graph, created when you first run the program

The accepted directory file extensions are listed near the top of
`ingest_sources.py`. A directly supplied file is always read, regardless of
extension.

## Read more
TTL Graph Generalization techniques
What about wiki?