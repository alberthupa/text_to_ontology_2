#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import sys
import time
from pathlib import Path

from context_render import prepare_prompt_context
from graph_management import open_graph, save_graph
from graph_merge import merge_into_graph
from ingest_sources import find_text_files, read_source
from llm import model_name
from prompt_budget import PROMPT_BUDGET, estimate_tokens
from source_parse import parse_source
from task_context import build_task_context


def budget_for(text):
    """The approved prompt budget, with this source's own cost filled in."""
    return dict(PROMPT_BUDGET, source_tokens=estimate_tokens(text))


def report_context(budget):
    """One line about what context this file received, and what did not fit."""
    print(f"  Context: {len(budget['items'])} items, "
          f"{budget['used_tokens']}/{budget['budget_tokens']} tokens, "
          f"{len(budget['dropped_ids'])} items did not fit", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=Path("ontology.ttl"))
    args = parser.parse_args()

    graph = open_graph(args.graph)
    files = find_text_files(args.source, args.graph)
    if not files:
        raise RuntimeError("No text-like files found")

    args.graph.parent.mkdir(parents=True, exist_ok=True)
    for path in files:
        print(f"Reading {path}", flush=True)
        text = read_source(path)
        if not text.strip():
            continue
        # Read only, and rebuilt for every file: the graph has grown since the
        # last one, so last file's context is not this file's context.
        context = build_task_context(text, graph)
        prompt_context = prepare_prompt_context(context, budget_for(text))
        report_context(prompt_context["budget"])
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, prompt_context["text"])
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        counts = merge_into_graph(graph, extraction)
        save_graph(graph, args.graph)
        print(f"  {counts[0]} new, {counts[1]} resolved, "
              f"{counts[2]} relations, {counts[3]} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
