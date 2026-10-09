"""Source-local staging: one document, one provisional graph.

While a document's windows are processed, nothing canonical may change.
Each window's validated extraction is planned against the *source staging
graph* - the graph built from this document's earlier windows only - and
admitted assertions enter that staging graph under deterministic provisional
IRIs. Canonical identity resolution against the final ontology happens later,
at publication; the staging layer never decides it.

The pieces:

    source_staging_graph_name      stable named-graph name for one document;
    window_candidate_graph_name    stable name for one window's candidate RDF;
    window_activity_id             deterministic PROV activity identifier;
    plan_window_admission          read-only source-local admission plan;
    final_graphs_snapshot          triple-level snapshot for immutability checks;
    layered_context_text           canonical plus marked source-local context;
    retain_staging                 diagnostic export of a failed document.

Admission reuses the merge policy unchanged, with two differences: new
entities receive provisional IRIs under the document's own namespace instead
of canonical entity/ slugs, and an existing_id hint from the prompt context
cannot match anything because canonical resources are not in the staging
graph. Ambiguous identities and conflicts stay in review, ready for document
reconciliation.
"""

import hashlib

from rdflib import Graph, URIRef

from .candidate_graph import CANDIDATE_BASE, PROVISIONAL
from .context_render import (
    allowance,
    assemble_context,
    assembly_overhead,
    render_context_items,
)
from .merge_policy import (
    AUTO_ACCEPT_MIN_CONFIDENCE,
    canonical_json,
    plan_graph_merge,
)
from .graph_merge import slug
from .prompt_budget import fit_context_items

STAGING_NAMESPACE = CANDIDATE_BASE + "staging/"


def source_staging_graph_name(document_id):
    """One stable graph name per source document, derived from its digest ID."""
    return URIRef(f"{STAGING_NAMESPACE}{document_id}")


def window_candidate_graph_name(document_id, window_id):
    """One stable graph name per window candidate graph."""
    return URIRef(f"{STAGING_NAMESPACE}{document_id}/{window_id}")


def window_activity_id(document_id, window_id, model, candidates):
    """A deterministic PROV activity identifier for one window extraction."""
    payload = "|".join(
        [document_id, window_id, model, canonical_json(candidates)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def provisional_allocator(document_id):
    """Allocate deterministic provisional IRIs for one document's new entities.

    Same rules as the canonical allocator - slug first, -2, -3, ... on
    collision - but always inside this document's provisional namespace, so a
    staged entity can never claim a canonical identity.
    """
    reserved = set()

    def allocate(name):
        stem = slug(name)
        number = 1
        while True:
            suffix = "" if number == 1 else f"-{number}"
            iri = str(PROVISIONAL[f"{document_id}/{stem}{suffix}"])
            if iri not in reserved:
                reserved.add(iri)
                return URIRef(iri)
            number += 1

    return allocate


def plan_window_admission(source_graph, candidates, provenance, document_id,
                          min_new_confidence=AUTO_ACCEPT_MIN_CONFIDENCE):
    """Plan one window against the source staging graph only.

    Read only. Identity decisions see earlier windows of this same document,
    never canonical individuals; new URIs are provisional.
    """
    return plan_graph_merge(
        source_graph, candidates, provenance,
        min_new_confidence=min_new_confidence,
        allocate_uri=provisional_allocator(document_id),
    )


def final_graphs_snapshot(graph):
    """An order-independent snapshot of every final-ontology triple."""
    return tuple(sorted(graph))


def layered_context_text(canonical_package, source_package, budget_config,
                         count_tokens):
    """Render and budget canonical plus source-local context as one block.

    Source-local items keep their sections but are marked "(this document)"
    on every line, so the model can tell earlier-window knowledge from
    established ontology knowledge. One shared budget covers both; items are
    dropped whole, least relevant first, exactly as in single-package mode.
    Only canonical resources can become reusable existing_id values.
    """
    rendered = render_context_items(canonical_package)
    if source_package is not None:
        rendered += _marked_source_items(source_package)
    overhead = assembly_overhead(rendered, count_tokens)
    budget = max(0, allowance(budget_config) - overhead)
    result = fit_context_items(rendered, budget, count_tokens)
    result["budget_tokens"] = allowance(budget_config)
    kept = {entry["id"] for entry in result["items"]}
    existing_ids = sorted({
        entry["value"]["id"]
        for entry in canonical_package.get("resources", [])
        if entry["id"] in kept and entry["value"].get("native")
        and entry["value"].get("id")
    })
    return {"text": assemble_context(result["items"]), "budget": result,
            "existing_ids": existing_ids}


def _marked_source_items(source_package):
    package = dict(source_package)
    # A provisional resource is never a resolvable existing_id, so its IRI is
    # not shown at all: a model copies what it sees. Earlier-window entities
    # are reused by exact name and kind instead.
    package["resources"] = [
        {**entry, "value": {**entry["value"], "native": False,
                            "hide_uri": True}}
        for entry in source_package.get("resources", [])
    ]
    marked = []
    for entry in render_context_items(package):
        marked.append({
            **entry,
            "id": f"this-document|{entry['id']}",
            "dependencies": [f"this-document|{dependency}"
                             for dependency in entry["dependencies"]],
            "text": "\n".join(
                f"(this document) {line}"
                for line in entry["text"].splitlines()),
        })
    return marked


def retain_staging(store, document_id, graph_path):
    """Export one document's staging graphs next to the output graph.

    Used only when retention is configured and a window failed: the sidecar
    file keeps the source staging graph and every window candidate graph for
    diagnosis. Nothing canonical is touched.
    """
    from .graph_store import RdflibGraphStore

    prefix = str(source_staging_graph_name(document_id))
    sidecar_path = (graph_path.parent /
                    f"{graph_path.name}.staging/{document_id}.trig")
    export = RdflibGraphStore()
    for name in store.graph_names():
        if str(name).startswith(prefix):
            export.put(name, store.get(name))
    export.path = sidecar_path
    export.publish()
    return sidecar_path
