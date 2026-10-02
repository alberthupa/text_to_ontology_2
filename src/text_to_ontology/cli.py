"""The command line: parse arguments, build adapters, call the public API."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .api import RunRequest, run_text_to_graph
from .graph_management import LocalTurtleStore
from .llm import OpenRouterExtractor
from .pipeline import MergeConfig
from .run_report import RunReporter, default_report_path

DEFAULT_GRAPH = Path("ontology.trig")


def build_parser():
    """The one command line this program accepts."""
    parser = argparse.ArgumentParser(
        description="Add knowledge from text files to one RDF dataset.")
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=DEFAULT_GRAPH,
                        help="the TriG dataset to create or extend; .ttl keeps "
                             "legacy Turtle compatibility")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every intermediate artifact, step by step")
    parser.add_argument("--report", action="store_true",
                        help="save a verbose Markdown report; stay silent on success")
    parser.add_argument("--dry-run", action="store_true",
                        help="return and report the exact plan without publishing")
    parser.add_argument("--data-only", action="store_true",
                        help="use only the classes and relationships the starter "
                             "ontology already declares; never add new ones")
    return parser


def main(argv=None):
    """Run the CLI and translate failures into an exit code."""
    args = build_parser().parse_args(argv)
    started_at = datetime.now().astimezone()
    report_stream = None
    report_path = None

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
        compatibility_store = (LocalTurtleStore()
                               if args.graph.suffix.lower() == ".ttl" else None)
        run_text_to_graph(
            RunRequest(source=args.source, graph_path=args.graph,
                       merge=MergeConfig(
                           require_declared_vocabulary=args.data_only),
                       dry_run=args.dry_run),
            graph_store=compatibility_store,
            extractor=OpenRouterExtractor(),
            reporter=reporter,
        )
    except (RuntimeError, OSError) as error:
        reporter.failed(error)
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        if report_stream is not None:
            report_stream.close()
