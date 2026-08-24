"""The public Python API: run the whole application from one function.

Minimal example:

    from pathlib import Path

    from text_to_ontology.api import RunRequest, run_text_to_graph
    from text_to_ontology.llm import OpenRouterExtractor
    from text_to_ontology.run_report import RunReporter

    result = run_text_to_graph(
        RunRequest(source=Path("notes.txt"), graph_path=Path("ontology.trig")),
        extractor=OpenRouterExtractor(),
        reporter=RunReporter(),
    )
    print(result.triples, "triples in", result.graph_path)

The CLI is a thin adapter over this module; it adds only argument parsing,
environment configuration, and exit codes.
"""

from .graph_management import GraphStore, LocalTurtleStore
from .graph_store import GraphNames, RdflibGraphStore
from .document_publication import (
    DocumentPublicationPlan,
    PublicationValidationError,
)
from .llm import OpenRouterExtractor
from .source_reconciliation import SourceGraphArtifact
from .source_validation import SourceValidationError, SourceValidationResult
from .pipeline import (
    ContextConfig,
    DocumentResult,
    ExtractionConfig,
    Extractor,
    MergeConfig,
    ProcessingConfig,
    Reporter,
    RunRequest,
    RunResult,
    ValidationConfig,
    WindowingConfig,
    run_text_to_graph,
)

__all__ = [
    "ContextConfig",
    "DocumentResult",
    "ExtractionConfig",
    "Extractor",
    "GraphStore",
    "GraphNames",
    "LocalTurtleStore",
    "MergeConfig",
    "OpenRouterExtractor",
    "DocumentPublicationPlan",
    "PublicationValidationError",
    "RdflibGraphStore",
    "ProcessingConfig",
    "Reporter",
    "RunRequest",
    "RunResult",
    "SourceGraphArtifact",
    "SourceValidationError",
    "SourceValidationResult",
    "ValidationConfig",
    "WindowingConfig",
    "run_text_to_graph",
]
