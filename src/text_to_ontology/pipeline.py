"""The readable run loop: source files in, one growing Turtle graph out."""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .candidate_validation import format_validation_failure, validate_candidates
from .context_render import prepare_prompt_context
from .graph_management import LocalTurtleStore, save_graph
from .graph_merge import apply_merge_plan
from .ingest_sources import find_text_files, read_source
from .llm import SYSTEM_PROMPT, OpenRouterExtractor
from .merge_policy import (
    AUTO_ACCEPT_MIN_CONFIDENCE,
    build_provenance,
    plan_graph_merge,
)
from .prompt_budget import PROMPT_BUDGET, estimate_tokens
from .run_report import RunReporter
from .source_parse import make_prompt
from .task_context import build_task_context


@dataclass
class WindowingConfig:
    """How a source document is split into extraction windows.

    Strategy version 1 sends every short document as one whole-text window.
    Real windowing arrives with the documents-and-windowing milestone.
    """

    strategy_version: int = 1


@dataclass
class ContextConfig:
    """How much selected ontology context one prompt may carry."""

    budget: dict = field(default_factory=lambda: dict(PROMPT_BUDGET))


@dataclass
class ExtractionConfig:
    """Which model answers extraction prompts (None: adapter default)."""

    model: str | None = None


@dataclass
class MergeConfig:
    """When a new assertion is confident enough to be accepted."""

    min_auto_accept_confidence: float = AUTO_ACCEPT_MIN_CONFIDENCE


@dataclass
class RunRequest:
    """One complete request: sources in, knowledge into one graph file."""

    source: Path
    graph_path: Path = Path("ontology.ttl")
    windowing: WindowingConfig = field(default_factory=WindowingConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)


@dataclass
class RunResult:
    """What one completed run did."""

    graph_path: Path
    triples: int
    files_total: int
    files_saved: int
    files_blank: int


class Extractor(Protocol):
    """What the pipeline needs from any extraction backend."""

    def model(self) -> str:
        """The model name shown in reports."""

    def extract(self, prompt: str) -> dict:
        """Send one prompt and return its parsed JSON answer."""


class Reporter(Protocol):
    """What the pipeline reports while it runs; see RunReporter."""

    def source_started(self, path, index, total, graph_size): ...
    def blank_source(self): ...
    def context_selection(self, context, source_graph): ...
    def prompt_context(self, prompt_context): ...
    def asking_model(self, model): ...
    def llm_input(self, system_prompt, user_prompt): ...
    def model_replied(self, extraction, elapsed): ...
    def validation(self, validation): ...
    def merge_plan(self, plan, candidates, graph): ...
    def saved(self, graph_path, before_size, updated, counts): ...
    def finished(self, graph, graph_path): ...
    def failed(self, error): ...


def budget_for(text, budget):
    """The configured prompt budget, with this source's own cost filled in."""
    return dict(budget, source_tokens=estimate_tokens(text))


def run_text_to_graph(request, graph_store=None, extractor=None, reporter=None):
    """Add the knowledge of every source file to one graph file.

    The public entry point of the application. Give it a request plus three
    adapters - where graphs live, who answers prompts, who hears about it -
    and it returns what happened.
    """
    graph_store = graph_store or LocalTurtleStore()
    extractor = extractor or OpenRouterExtractor(model=request.extraction.model)
    reporter = reporter or RunReporter()

    graph = graph_store.load(request.graph_path)
    files = find_text_files(request.source, request.graph_path)
    if not files:
        raise RuntimeError("No text-like files found")

    blank_files = 0
    for index, path in enumerate(files, start=1):
        reporter.source_started(path, index, len(files), len(graph))
        text = read_source(path)
        if not text.strip():
            reporter.blank_source()
            blank_files += 1
            continue

        # Choose potentially useful items before budgeting. Each gets a priority.
        context = build_task_context(text, graph)
        reporter.context_selection(context, graph)

        # Prepare the budgeted context text that will be placed in the prompt.
        prompt_context = prepare_prompt_context(
            context, budget_for(text, request.context.budget))
        reporter.prompt_context(prompt_context)

        model = extractor.model()
        prompt = make_prompt(text, prompt_context["text"])
        reporter.asking_model(model)
        reporter.llm_input(SYSTEM_PROMPT, prompt)
        started = time.monotonic()

        # Send the prompt to the LLM and parse its JSON response.
        extraction = extractor.extract(prompt)
        reporter.model_replied(extraction, time.monotonic() - started)

        # Is this LLM package structurally valid and safe enough for merge policy?
        validation = validate_candidates(
            extraction, graph, prompt_context["existing_ids"])
        reporter.validation(validation)
        if not validation["valid"]:
            raise RuntimeError(format_validation_failure(validation))

        # Record where this extraction came from and which model/policy produced it.
        provenance = build_provenance(path, text, model)

        # Decide what to accept, corroborate, or hold for review without changing
        # the graph.
        plan = plan_graph_merge(
            graph, validation["candidates"], provenance,
            min_new_confidence=request.merge.min_auto_accept_confidence)

        # Show the merge decisions before anything is written.
        reporter.merge_plan(plan, validation["candidates"], graph)

        # Apply the completed plan to a copy of the graph.
        before_size = len(graph)
        updated, counts = apply_merge_plan(graph, plan)
        save_graph(updated, request.graph_path)
        graph = updated
        reporter.saved(request.graph_path, before_size, updated, counts)
    reporter.finished(graph, request.graph_path)

    return RunResult(
        graph_path=request.graph_path,
        triples=len(graph),
        files_total=len(files),
        files_saved=len(files) - blank_files,
        files_blank=blank_files,
    )

