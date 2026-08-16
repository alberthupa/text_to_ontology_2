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

## Planning

- [`ontology_context_and_merge_plan.md`](ontology_context_and_merge_plan.md) —
  the overall incremental plan
- [`proposal_01_current_pipeline_baseline.md`](proposal_01_current_pipeline_baseline.md)
  — the proposal for the first step
- [`next_steps.md`](next_steps.md) — the original working notes

## Files

- `ontology.py` — text extraction and RDF graph logic
- `llm.py` — the tiny OpenRouter client
- `requirements.txt` — the one dependency (`rdflib`)
- `ontology.ttl` — your graph, created when you first run the program
- `sources/` — source documents used by the experiment

The accepted directory file extensions are listed near the top of
`ontology.py`. A directly supplied file is always read, regardless of extension.
