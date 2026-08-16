#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import sys
import time
from pathlib import Path

from graph_management import open_graph, save_graph
from graph_merge import merge_into_graph
from ingest_sources import find_text_files, read_source
from llm import model_name
from source_parse import parse_source


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
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, graph)
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
