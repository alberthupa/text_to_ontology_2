#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from candidate_validation import format_validation_failure, validate_candidates
from context_render import prepare_prompt_context
from graph_management import open_graph, save_graph
from graph_merge import apply_merge_plan
from ingest_sources import find_text_files, read_source
from llm import SYSTEM_PROMPT, model_name
from merge_policy import build_provenance, plan_graph_merge
from prompt_budget import PROMPT_BUDGET, estimate_tokens
from run_report import RunReporter, default_report_path
from source_parse import make_prompt, parse_prompt
from task_context import build_task_context


def budget_for(text):
    """The approved prompt budget, with this source's own cost filled in."""
    return dict(PROMPT_BUDGET, source_tokens=estimate_tokens(text))


def run_pipeline(source, graph_path, reporter):
    """Process every source file using one reporter and one growing graph."""
    graph = open_graph(graph_path)
    files = find_text_files(source, graph_path)
    if not files:
        raise RuntimeError("No text-like files found")

    graph_path.parent.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(files, start=1):
        reporter.source_started(path, index, len(files), len(graph))
        text = read_source(path)
        if not text.strip():
            reporter.blank_source()
            continue

        # Choose potentially useful items before budgeting. Each gets a priority.
        context = build_task_context(text, graph)
        reporter.context_selection(context, graph)

        # Prepare the budgeted context text that will be placed in the prompt.
        prompt_context = prepare_prompt_context(context, budget_for(text))
        reporter.prompt_context(prompt_context)

        model = model_name()
        prompt = make_prompt(text, prompt_context["text"])
        reporter.asking_model(model)
        reporter.llm_input(SYSTEM_PROMPT, prompt)
        started = time.monotonic()

        # Send the prompt to the LLM and parse its JSON response.
        extraction = parse_prompt(prompt)
        reporter.model_replied(extraction, time.monotonic() - started)

        # Is this LLM package structurally valid and safe enough to give to merge policy?
        validation = validate_candidates(
            extraction, graph, prompt_context["existing_ids"])
        reporter.validation(validation)
        if not validation["valid"]:
            raise RuntimeError(format_validation_failure(validation))

        # Record where this extraction came from and which model/policy produced it.
        provenance = build_provenance(path, text, model)

        # Decide what to accept, corroborate, or hold for review without changing the graph.
        plan = plan_graph_merge(graph, validation["candidates"], provenance)

        # Show the merge decisions before anything is written.
        reporter.merge_plan(plan, validation["candidates"], graph)

        # Apply the completed plan to a copy of the graph.
        before_size = len(graph)
        updated, counts = apply_merge_plan(graph, plan)
        save_graph(updated, graph_path)
        graph = updated
        reporter.saved(graph_path, before_size, updated, counts)
    reporter.finished(graph, graph_path)


def main(reporter=None):
    """Run the CLI, optionally writing through a supplied reporter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=Path("ontology.ttl"))
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every intermediate artifact, step by step")
    parser.add_argument("--report", action="store_true",
                        help="save a verbose Markdown report; stay silent on success")
    args = parser.parse_args()
    started_at = datetime.now().astimezone()
    report_stream = None
    report_path = None

    if reporter is None:
        if args.report:
            report_path = default_report_path(args.source, started_at)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_stream = report_path.open("w", encoding="utf-8")
            reporter = RunReporter(
                verbose=True,
                stream=report_stream,
                markdown_streams=[report_stream],
            )
        else:
            reporter = RunReporter(verbose=args.verbose)

    reporter.run_started(args.source, args.graph, started_at, report_path)
    try:
        run_pipeline(args.source, args.graph, reporter)
    except (RuntimeError, OSError) as error:
        reporter.failed(error)
        raise
    finally:
        if report_stream is not None:
            report_stream.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
