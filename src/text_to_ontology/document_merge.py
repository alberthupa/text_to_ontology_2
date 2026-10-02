"""Build one final merge plan from a complete reconciled document."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .candidate_graph import provisional_entity_iri
from .graph_merge import slug
from .merge_policy import build_provenance, canonical_json, plan_graph_merge


DOCUMENT_MERGE_VERSION = 1


@dataclass
class DocumentCandidateBundle:
    """One deduplicated candidate package plus its source-identity map."""

    candidates: dict
    source_keys_by_window: dict
    local_id_by_source: dict


def build_document_candidates(document_id, packages, admission_plans):
    """Collapse window packages into one document package.

    Safe source-local identities share one record. Identity candidates held by
    local admission remain separate and can be reconsidered against the full
    canonical identity scope. Exact overlap assertions become one planned
    assertion; their independent candidate-graph evidence remains untouched.
    """
    grouped_entities = {}
    source_keys_by_window = {}

    for (window, _model, candidates), admission in zip(
            packages, admission_plans):
        window_sources = {}
        decisions = admission["plan"]["identities"]
        for record in candidates["entities"]:
            local_id = record["id"]
            decision = decisions[local_id]
            if decision["status"] != "review" and decision.get("uri"):
                source_key = str(decision["uri"])
            else:
                source_key = str(provisional_entity_iri(
                    document_id, f"review/{window.window_id}/{local_id}"))
            window_sources[local_id] = source_key
            grouped_entities.setdefault(source_key, []).append(record)
        source_keys_by_window[window.window_id] = window_sources

    local_id_by_source = {
        source_key: "source-" + hashlib.sha256(
            source_key.encode("utf-8")).hexdigest()[:16]
        for source_key in sorted(grouped_entities)
    }
    entities = [
        _combined_entity(local_id_by_source[source_key], records)
        for source_key, records in sorted(grouped_entities.items())
    ]

    assertions = {"relations": {}, "facts": {}}
    for window, _model, candidates in packages:
        sources = source_keys_by_window[window.window_id]
        for record in candidates["relations"]:
            combined = {
                "subject": local_id_by_source[sources[record["subject"]]],
                "predicate": record["predicate"],
                "object": local_id_by_source[sources[record["object"]]],
                "confidence": record["confidence"],
            }
            key = (combined["subject"], slug(combined["predicate"]),
                   combined["object"])
            _keep_strongest(assertions["relations"], key, combined)
        for record in candidates["facts"]:
            combined = {
                "subject": local_id_by_source[sources[record["subject"]]],
                "predicate": record["predicate"],
                "value": record["value"],
                "confidence": record["confidence"],
            }
            key = (combined["subject"], slug(combined["predicate"]),
                   canonical_json(combined["value"]))
            _keep_strongest(assertions["facts"], key, combined)

    return DocumentCandidateBundle(
        candidates={
            "entities": entities,
            "relations": [assertions["relations"][key]
                          for key in sorted(assertions["relations"])],
            "facts": [assertions["facts"][key]
                      for key in sorted(assertions["facts"])],
        },
        source_keys_by_window=source_keys_by_window,
        local_id_by_source=local_id_by_source,
    )


def plan_document_merge(canonical_graph, document, packages, admission_plans,
                        min_new_confidence, planner=plan_graph_merge,
                        vocabulary=None, configuration=None):
    """Resolve the whole reconciled source against canonical knowledge once.

    Anything in `configuration` joins the hashed run configuration, so an
    artifact always names the prompt and policy that produced it.
    """
    bundle = build_document_candidates(
        document.document_id, packages, admission_plans)
    models = sorted({model for _window, model, _candidates in packages})
    configuration = {
        "document_merge_version": DOCUMENT_MERGE_VERSION,
        "min_new_confidence": min_new_confidence,
        **(configuration or {}),
    }
    provenance = build_provenance(
        Path(document.name), document.text, ", ".join(models))
    provenance["document_id"] = document.document_id
    provenance["configuration_sha256"] = hashlib.sha256(
        canonical_json(configuration).encode("utf-8")).hexdigest()
    merge_plan = planner(
        canonical_graph, bundle.candidates, provenance,
        min_new_confidence=min_new_confidence, vocabulary=vocabulary)
    identity_mapping = {
        source_key: merge_plan["identities"][local_id]
        for source_key, local_id in bundle.local_id_by_source.items()
    }
    return {
        "version": DOCUMENT_MERGE_VERSION,
        "document_id": document.document_id,
        "configuration": configuration,
        "candidates": bundle.candidates,
        "source_keys_by_window": bundle.source_keys_by_window,
        "local_id_by_source": bundle.local_id_by_source,
        "identity_mapping": identity_mapping,
        "merge_plan": merge_plan,
    }


def _combined_entity(local_id, records):
    first = records[0]
    aliases = sorted({alias for record in records
                      for alias in record.get("aliases", [])})
    descriptions = [record.get("description", "")
                    for record in records if record.get("description")]
    existing_ids = sorted({record.get("existing_id") for record in records
                           if record.get("existing_id")})
    return {
        "id": local_id,
        "name": first["name"],
        "kind": first["kind"],
        "description": descriptions[0] if descriptions else "",
        "aliases": aliases,
        "existing_id": existing_ids[0] if len(existing_ids) == 1 else None,
        "confidence": max(record["confidence"] for record in records),
    }


def _keep_strongest(records, key, candidate):
    current = records.get(key)
    if current is None or candidate["confidence"] > current["confidence"]:
        records[key] = candidate
