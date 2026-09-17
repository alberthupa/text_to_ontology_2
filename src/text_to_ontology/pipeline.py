"""The readable run loop: source documents, windows, staged graphs, one file."""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from rdflib import Graph

from .candidate_graph import build_candidate_graph
from .candidate_validation import format_validation_failure, validate_candidates
from .graph_management import save_graph
from .graph_merge import apply_merge_plan
from .graph_store import GraphNames, RdflibGraphStore
from .ingest_sources import find_text_files, read_source
from .llm import SYSTEM_PROMPT, OpenRouterExtractor
from .merge_policy import (
    AUTO_ACCEPT_MIN_CONFIDENCE,
    build_provenance,
    plan_graph_merge,
)
from .document_merge import plan_document_merge
from .document_publication import (
    DocumentPublicationPlan,
    LegacyTurtleDatasetStore,
    PublicationValidationError,
    canonical_graph,
    compile_document_publication,
    initial_role_graphs,
    publish_document,
    shape_graphs,
    union_graphs,
)
from .prompt_budget import PROMPT_BUDGET, estimate_tokens
from .repair import extract_validated
from .run_report import RunReporter
from .source_parse import make_prompt
from .source_staging import (
    final_graphs_snapshot,
    layered_context_text,
    plan_window_admission,
    retain_staging,
    source_staging_graph_name,
    window_activity_id,
    window_candidate_graph_name,
)
from .source_reconciliation import (
    SourceGraphArtifact,
    build_source_artifact,
    reconcile_document,
)
from .source_validation import (
    SourceValidationError,
    SourceValidationResult,
    embedded_shape_graph,
    validate_source_graph,
)
from .task_context import build_task_context
from .windowing import (
    DEFAULT_TARGET_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    WINDOW_STRATEGY_VERSION,
    make_source_document,
    plan_windows,
)


@dataclass
class WindowingConfig:
    """How a source document is split into extraction windows.

    A short document stays one whole-text window; a long one is cut on
    headings, paragraphs, and sentences with a token overlap between
    adjacent windows.
    """

    target_tokens: int = DEFAULT_TARGET_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    strategy_version: int = WINDOW_STRATEGY_VERSION
    count_tokens: object = estimate_tokens


@dataclass
class ContextConfig:
    """How much selected ontology context one prompt may carry."""

    budget: dict = field(default_factory=lambda: dict(PROMPT_BUDGET))


@dataclass
class ExtractionConfig:
    """Which model answers extraction prompts, and how often it may retry.

    `repair_attempts` bounds how many times a messy answer is sent back to
    the model for self-repair before the window is rejected.
    """

    model: str | None = None
    repair_attempts: int = 2


@dataclass
class MergeConfig:
    """When a new assertion is confident enough to be accepted."""

    min_auto_accept_confidence: float = AUTO_ACCEPT_MIN_CONFIDENCE


@dataclass
class ProcessingConfig:
    """How source staging graphs behave when a window fails.

    With `retain_staging_on_failure`, the failed document's source staging
    graph and window candidate graphs are exported to a sidecar TriG file
    next to the output graph for diagnosis; otherwise they are discarded.
    """

    retain_staging_on_failure: bool = False


@dataclass
class ValidationConfig:
    """SHACL shape graphs applied to every complete source graph.

    With no explicit graphs, the compatibility Turtle graph's embedded shapes
    are used. Supplying graphs replaces that default and all supplied graphs
    are combined for one validation pass.
    """

    shape_graphs: tuple = ()


@dataclass
class RunRequest:
    """One complete request: sources in, knowledge into one RDF dataset."""

    source: Path
    graph_path: Path = Path("ontology.trig")
    windowing: WindowingConfig = field(default_factory=WindowingConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    graph_names: GraphNames = field(default_factory=GraphNames)
    dry_run: bool = False


@dataclass
class DocumentResult:
    """The reconciled and validated source artifact for one saved document."""

    path: Path
    document_id: str
    source_artifact: SourceGraphArtifact
    reconciliation_report: dict
    source_validation: SourceValidationResult
    publication_plan: DocumentPublicationPlan | None = None
    publication_validation: SourceValidationResult | None = None


@dataclass
class RunResult:
    """What one completed run did."""

    graph_path: Path
    triples: int
    files_total: int
    files_saved: int
    files_blank: int
    windows_processed: int = 0
    documents: tuple[DocumentResult, ...] = ()
    dry_run: bool = False


@dataclass
class _StagedDocument:
    """Internal state kept until reconciliation and validation finish."""

    packages: list
    staging: RdflibGraphStore
    source_graph: Graph
    candidate_graphs: dict
    admission_plans: list


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
    def document_staging(self, document_id, staging_name, windows): ...
    def window_started(self, number, total, window_id): ...
    def context_selection(self, context, source_graph): ...
    def prompt_context(self, prompt_context): ...
    def asking_model(self, model): ...
    def llm_input(self, system_prompt, user_prompt): ...
    def model_replied(self, extraction, elapsed): ...
    def validation(self, validation): ...
    def window_admitted(self, number, total, counts, source_size): ...
    def reconciliation(self, report): ...
    def source_validation(self, result): ...
    def publication_validation(self, result): ...
    def dry_run(self, graph_path, before_size, proposed, counts): ...
    def merge_plan(self, plan, candidates, graph): ...
    def saved(self, graph_path, before_size, updated, counts): ...
    def staging_failed(self, document_id, retained, sidecar_path): ...
    def finished(self, graph, graph_path): ...
    def dry_run_finished(self, graph, graph_path): ...
    def failed(self, error): ...


def budget_for(text, budget):
    """The configured prompt budget, with this source's own cost filled in."""
    return dict(budget, source_tokens=estimate_tokens(text))


def _window_context(window_text, final_graph, source_graph, budget_config):
    """Select and budget what this window's prompt may see.

    Canonical knowledge comes from the final ontology; earlier-window
    knowledge comes from the source staging graph and is clearly marked as
    such in the rendered prompt context. Returns the budgeted prompt context
    and the canonical selection package, for reporting.
    """
    canonical = build_task_context(window_text, final_graph)
    source = (build_task_context(window_text, source_graph)
              if len(source_graph) else None)
    prompt_context = layered_context_text(
        canonical, source, budget_config, count_tokens=estimate_tokens)
    return prompt_context, canonical


def _extract_window(window, request, final_graph, source_graph, extractor,
                    reporter):
    """Ask the model about one window and validate the answer."""
    prompt_context, canonical_context = _window_context(
        window.text, final_graph, source_graph,
        budget_for(window.text, request.context.budget))
    reporter.context_selection(canonical_context, final_graph)
    reporter.prompt_context(prompt_context)

    model = extractor.model()
    prompt = make_prompt(window.text, prompt_context["text"])
    reporter.asking_model(model)
    reporter.llm_input(SYSTEM_PROMPT, prompt)
    started = time.monotonic()

    # Send the prompt; a messy answer is repaired by the model itself,
    # under the same validation gate, at most repair_attempts times.
    outcome = extract_validated(
        extractor, prompt,
        lambda data: validate_candidates(
            data, final_graph, prompt_context["existing_ids"]),
        max_repair_attempts=request.extraction.repair_attempts,
    )
    reporter.model_replied(
        outcome.validation["candidates"] if outcome.validation else {},
        time.monotonic() - started)
    if outcome.validation is not None:
        reporter.validation(outcome.validation)
    if not outcome.ok:
        raise RuntimeError(
            outcome.raw_problem
            or format_validation_failure(outcome.validation))
    return model, outcome.validation["candidates"]


def _admit_window(window, candidates, request, document, staging,
                  source_graph, model, reporter):
    """Build the candidate RDF and admit accepted assertions locally.

    The admission plan sees only the source staging graph: earlier windows of
    this same document, never canonical individuals. The candidate graph is
    kept alongside as evidence under its own stable name.
    """
    provenance = build_provenance(Path(document.name), window.text, model)
    provenance["window_id"] = window.window_id
    plan = plan_window_admission(
        source_graph, candidates, provenance, document.document_id,
        min_new_confidence=request.merge.min_auto_accept_confidence)
    entity_iris = {
        local_id: decision["uri"]
        for local_id, decision in plan["identities"].items()
        if decision["status"] != "review" and decision.get("uri") is not None
    }
    assertion_triples = {
        (section, item["index"]): item["triple"]
        for section in ("relations", "facts")
        for item in plan[section]
        if item.get("triple") is not None
    }
    activity_id = window_activity_id(
        document.document_id, window.window_id, model, candidates)
    candidate = build_candidate_graph(
        candidates, document.document_id, window.window_id, activity_id, model,
        entity_iris=entity_iris, assertion_triples=assertion_triples)
    candidate_name = window_candidate_graph_name(
        document.document_id, window.window_id)
    staging.put(candidate_name, candidate)

    updated, counts = apply_merge_plan(source_graph, plan)
    return updated, counts, plan


def _process_document(document, request, final_graph, extractor, reporter):
    """Run every window of one document through staging.

    Returns the admitted window packages. The final ontology is never written
    to here; a snapshot taken before the first window must still be exact
    after every later one.
    """
    windows = plan_windows(document, request.windowing)
    staging_name = source_staging_graph_name(document.document_id)
    reporter.document_staging(document.document_id, staging_name, len(windows))

    staging = RdflibGraphStore()
    staging.put(staging_name, Graph())
    source_graph = staging.get(staging_name)
    snapshot = final_graphs_snapshot(final_graph)
    packages = []
    admission_plans = []
    try:
        for number, window in enumerate(windows, start=1):
            reporter.window_started(number, len(windows), window.window_id)
            model, candidates = _extract_window(
                window, request, final_graph, source_graph, extractor, reporter)
            source_graph, counts, plan = _admit_window(
                window, candidates, request, document, staging, source_graph,
                model, reporter)
            if final_graphs_snapshot(final_graph) != snapshot:
                raise RuntimeError(
                    "the final ontology changed during window processing")
            staging.put(staging_name, source_graph)
            reporter.window_admitted(number, len(windows), counts,
                                     len(source_graph))
            packages.append((window, model, candidates))
            admission_plans.append({"window_id": window.window_id,
                                    "plan": plan})
    except BaseException:
        retained = request.processing.retain_staging_on_failure
        sidecar = (retain_staging(staging, document.document_id,
                                  request.graph_path) if retained else None)
        reporter.staging_failed(document.document_id, retained, sidecar)
        raise
    candidate_graphs = {
        name: staging.get(name)
        for name in staging.graph_names()
        if name != staging_name
    }
    return _StagedDocument(
        packages=packages,
        staging=staging,
        source_graph=source_graph,
        candidate_graphs=candidate_graphs,
        admission_plans=admission_plans,
    )


def _source_shape_graphs(request, final_graph, roles, names):
    """Configured shapes, named shape roles, or embedded compatibility shapes."""
    if request.validation.shape_graphs:
        return tuple(request.validation.shape_graphs)
    configured = shape_graphs(roles, names)
    if any(len(graph) for graph in configured):
        return configured
    embedded = embedded_shape_graph(final_graph)
    return (embedded,) if len(embedded) else ()


def _final_store(graph_store, request):
    """Use a named store directly, or wrap the explicit Turtle compatibility adapter."""
    if graph_store is None:
        return RdflibGraphStore(path=request.graph_path)
    if all(hasattr(graph_store, method)
           for method in ("get", "graph_names", "publish")):
        return graph_store
    return LegacyTurtleDatasetStore(
        graph_store, request.graph_path, request.graph_names, save_graph)


def run_text_to_graph(request, graph_store=None, extractor=None, reporter=None):
    """Add the knowledge of every source file to one RDF dataset.

    The public entry point of the application. Give it a request plus three
    adapters - where graphs live, who answers prompts, who hears about it -
    and it returns what happened. Each document is processed window by window
    into its own source staging graph first; the final ontology is touched
    only after a document's last window was admitted.
    """
    extractor = extractor or OpenRouterExtractor(model=request.extraction.model)
    reporter = reporter or RunReporter()
    names = request.graph_names
    names.validate()
    store = _final_store(graph_store, request)
    roles = initial_role_graphs(store, names)
    graph = union_graphs(roles.values())
    files = find_text_files(request.source, request.graph_path)
    if not files:
        raise RuntimeError("No text-like files found")

    blank_files = 0
    windows_processed = 0
    documents = []
    for index, path in enumerate(files, start=1):
        reporter.source_started(path, index, len(files), len(graph))
        raw_text = read_source(path)
        if not raw_text.strip():
            reporter.blank_source()
            blank_files += 1
            continue

        document = make_source_document(path.name, raw_text,
                                        source_path=path.as_posix())
        before_size = len(graph)
        before_snapshot = final_graphs_snapshot(graph)
        staged = _process_document(
            document, request, graph, extractor, reporter)
        windows_processed += len(staged.packages)

        reconciliation = reconcile_document(
            document.document_id, staged.source_graph,
            staged.candidate_graphs, staged.admission_plans)
        reporter.reconciliation(reconciliation)
        models = [model for _window, model, _candidates in staged.packages]
        artifact = build_source_artifact(
            document, staged.source_graph, request.windowing, models)
        validation_shapes = _source_shape_graphs(
            request, graph, roles, names)
        validation = validate_source_graph(
            staged.source_graph, validation_shapes)
        reporter.source_validation(validation)
        if not validation.conforms:
            retained = request.processing.retain_staging_on_failure
            sidecar = (retain_staging(
                staged.staging, document.document_id, request.graph_path)
                if retained else None)
            reporter.staging_failed(document.document_id, retained, sidecar)
            raise SourceValidationError(
                validation, artifact, reconciliation, sidecar)
        if final_graphs_snapshot(graph) != before_snapshot:
            raise RuntimeError(
                "the final ontology changed during source reconciliation")

        document_merge = plan_document_merge(
            canonical_graph(roles, names), document, staged.packages,
            staged.admission_plans,
            request.merge.min_auto_accept_confidence,
            planner=plan_graph_merge)
        merge_plan = document_merge["merge_plan"]
        reporter.merge_plan(
            merge_plan, document_merge["candidates"],
            canonical_graph(roles, names))
        publication_plan = compile_document_publication(
            document, document_merge, staged.candidate_graphs,
            staged.packages, staged.admission_plans, roles, names,
            validation_shapes=validation_shapes)
        reporter.publication_validation(
            publication_plan.proposed_validation)
        if not publication_plan.proposed_validation.conforms:
            raise PublicationValidationError(publication_plan)

        proposed_graph = union_graphs(
            publication_plan.publication.graphs.values())
        if request.dry_run:
            reporter.dry_run(
                request.graph_path, before_size, proposed_graph,
                publication_plan.counts)
        else:
            publish_document(store, publication_plan)
            reporter.saved(
                request.graph_path, before_size, proposed_graph,
                publication_plan.counts)
        roles = dict(roles)
        roles.update(publication_plan.publication.graphs)
        graph = union_graphs(roles.values())
        documents.append(DocumentResult(
            path=path,
            document_id=document.document_id,
            source_artifact=artifact,
            reconciliation_report=reconciliation,
            source_validation=validation,
            publication_plan=publication_plan,
            publication_validation=publication_plan.proposed_validation,
        ))
    if request.dry_run:
        reporter.dry_run_finished(graph, request.graph_path)
    else:
        reporter.finished(graph, request.graph_path)

    return RunResult(
        graph_path=request.graph_path,
        triples=len(graph),
        files_total=len(files),
        files_saved=(0 if request.dry_run else len(files) - blank_files),
        files_blank=blank_files,
        windows_processed=windows_processed,
        documents=tuple(documents),
        dry_run=request.dry_run,
    )
