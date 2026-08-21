#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import sys
import time
from pathlib import Path

from candidate_validation import format_validation_failure, validate_candidates
from context_render import prepare_prompt_context
from graph_management import open_graph, save_graph
from graph_merge import apply_merge_plan
from ingest_sources import find_text_files, read_source
from llm import model_name
from merge_policy import build_provenance, plan_graph_merge
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


def report_validation(validation):
    """One line about the candidate counts and duplicates the validator removed."""
    counts = validation["counts"]
    removed = counts["duplicates_removed"]
    duplicates = (removed["entities"] + removed["relations"]
                  + removed["facts"] + removed["aliases"])
    print(f"  Validated: {counts['normalized']['entities']} entities, "
          f"{counts['normalized']['relations']} relations, "
          f"{counts['normalized']['facts']} facts; "
          f"{duplicates} duplicates removed", flush=True)


def report_plan(plan):
    """One line about what merge policy decided before anything is written."""
    counts = plan["counts"]
    identities = counts["identities"]
    assertions = counts["assertions"]
    summaries = counts["entity_summaries"]
    duplicates = assertions["duplicate"] + summaries["duplicate"]
    review = (assertions["review"] + summaries["review"]
              + summaries["partial_review"])
    print(f"  Planned: {identities['new']} new, {identities['resolved']} "
          f"resolved, {identities['review']} review identities; "
          f"{assertions['accepted']} accepted, {duplicates} corroborated, "
          f"{review} for review; {counts['audit_triples']} audit triples",
          flush=True)


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
        validation = validate_candidates(
            extraction, graph, prompt_context["existing_ids"])
        report_validation(validation)
        if not validation["valid"]:
            raise RuntimeError(format_validation_failure(validation))
        # Plan first, read only; materialize the completed plan into a copy;
        # save it; only then does the saved graph feed the next source.
        provenance = build_provenance(path, text, model)
        plan = plan_graph_merge(graph, validation["candidates"], provenance)
        report_plan(plan)
        updated, counts = apply_merge_plan(graph, plan)
        save_graph(updated, args.graph)
        graph = updated
        print(f"  {counts['new_entities']} new, "
              f"{counts['resolved_entities']} resolved, "
              f"{counts['relation_triples']} relations, "
              f"{counts['fact_triples']} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
