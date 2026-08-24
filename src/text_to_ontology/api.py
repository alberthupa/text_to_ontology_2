"""The public Python API: run the whole application from one function.

Minimal example:

    from pathlib import Path

    from text_to_ontology.api import RunRequest, run_text_to_graph
    from text_to_ontology.graph_management import LocalTurtleStore
    from text_to_ontology.llm import OpenRouterExtractor
    from text_to_ontology.run_report import RunReporter

    result = run_text_to_graph(
        RunRequest(source=Path("notes.txt"), graph_path=Path("ontology.ttl")),
        graph_store=LocalTurtleStore(),
        extractor=OpenRouterExtractor(),
        reporter=RunReporter(),
    )
    print(result.triples, "triples in", result.graph_path)

The CLI is a thin adapter over this module; it adds only argument parsing,
environment configuration, and exit codes.
"""

from .graph_management import GraphStore, LocalTurtleStore
from .llm import OpenRouterExtractor
from .pipeline import (
    ContextConfig,
    ExtractionConfig,
    Extractor,
    MergeConfig,
    ProcessingConfig,
    Reporter,
    RunRequest,
    RunResult,
    WindowingConfig,
    run_text_to_graph,
)

__all__ = [
    "ContextConfig",
    "ExtractionConfig",
    "Extractor",
    "GraphStore",
    "LocalTurtleStore",
    "MergeConfig",
    "OpenRouterExtractor",
    "ProcessingConfig",
    "Reporter",
    "RunRequest",
    "RunResult",
    "WindowingConfig",
    "run_text_to_graph",
]
