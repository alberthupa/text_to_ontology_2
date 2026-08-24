"""Reconcile and describe one complete document staging graph."""

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from rdflib import Graph
from rdflib.compare import to_canonical_graph
from rdflib.namespace import PROV, RDF, RDFS, SKOS

from .candidate_graph import CANDIDATE_MAPPING_VERSION, DQV
from .graph_management import FACT, ONTO, RELATION


@dataclass
class SourceGraphArtifact:
    """An inspectable deterministic export and the metadata needed to reuse it."""

    document_id: str
    document_digest: str
    graph_digest: str
    window_strategy_version: int
    candidate_mapping_version: int
    extractor_identities: tuple[str, ...]
    ntriples: str


def canonical_ntriples(graph):
    """Stable N-Triples after RDF blank-node canonicalization."""
    canonical = to_canonical_graph(graph)
    lines = canonical.serialize(format="nt").splitlines()
    return "\n".join(sorted(line for line in lines if line.strip())) + "\n"


def build_source_artifact(document, source_graph, windowing, models):
    """Create the deterministic source export and its association metadata."""
    serialized = canonical_ntriples(source_graph)
    return SourceGraphArtifact(
        document_id=document.document_id,
        document_digest=document.digest,
        graph_digest=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        window_strategy_version=windowing.strategy_version,
        candidate_mapping_version=CANDIDATE_MAPPING_VERSION,
        extractor_identities=tuple(sorted(set(models))),
        ntriples=serialized,
    )


def reconcile_document(document_id, source_graph, candidate_graphs,
                       admission_plans):
    """Return a plain, deterministic report for one complete source graph.

    Admission already resolved safe local identities incrementally. This pass
    makes the result explicit and verifies which independent candidate records
    support each admitted relation or fact.
    """
    local_entities = []
    aliases = []
    for entity in sorted(set(source_graph.subjects(RDF.type, ONTO.Entity)),
                         key=str):
        names = sorted({str(value)
                        for value in source_graph.objects(entity, SKOS.prefLabel)})
        kinds = sorted({str(value)
                        for value in source_graph.objects(entity, ONTO.kind)})
        entity_aliases = sorted({str(value)
                                 for value in source_graph.objects(
                                     entity, SKOS.altLabel)})
        local_entities.append({
            "uri": str(entity),
            "name": names[0] if names else "",
            "kind": kinds[0] if kinds else "",
            "aliases": entity_aliases,
        })
        aliases.extend({"entity": str(entity), "alias": alias}
                       for alias in entity_aliases)

    support_map = _assertion_supports(source_graph, candidate_graphs)
    duplicate_assertions = []
    for triple, supports in sorted(support_map.items(), key=lambda item: _key(item[0])):
        if len(supports) > 1:
            duplicate_assertions.append({
                "triple": tuple(str(term) for term in triple),
                "support_count": len(supports),
                "supports": supports,
            })

    unresolved = []
    conflicts = []
    for item in admission_plans:
        window_id, plan = item["window_id"], item["plan"]
        for local_id, decision in sorted(plan["identities"].items()):
            if decision["status"] == "review":
                unresolved.append({
                    "window_id": window_id,
                    "local_id": local_id,
                    "reason_codes": list(decision.get("reason_codes", [])),
                    "suggestions": list(decision.get("suggestions", [])),
                })
        conflicts.extend(_plan_conflicts(window_id, plan))

    aliases.sort(key=lambda item: (item["entity"], item["alias"]))
    unresolved.sort(key=lambda item: (item["window_id"], item["local_id"]))
    conflicts.sort(key=lambda item: (
        item["window_id"], item["section"], item["index"]))
    return {
        "document_id": document_id,
        "local_entities": local_entities,
        "aliases": aliases,
        "duplicate_assertions": duplicate_assertions,
        "unresolved_identities": unresolved,
        "conflicts": conflicts,
        "counts": {
            "local_entities": len(local_entities),
            "aliases": len(aliases),
            "duplicate_assertions": len(duplicate_assertions),
            "unresolved_identities": len(unresolved),
            "conflicts": len(conflicts),
        },
    }


def _assertion_supports(source_graph, candidate_graphs):
    supports = {}
    for graph_name, candidate in sorted(candidate_graphs.items(),
                                        key=lambda item: str(item[0])):
        for record in sorted(candidate.subjects(RDF.type, PROV.Collection), key=str):
            measurement = candidate.value(None, DQV.computedOn, record)
            confidence = candidate.value(measurement, DQV.value)
            for statement in candidate.objects(record, PROV.hadMember):
                triple = tuple(candidate.value(statement, predicate)
                               for predicate in (
                                   RDF.subject, RDF.predicate, RDF.object))
                if None in triple or triple not in source_graph:
                    continue
                predicate = str(triple[1])
                if not (predicate.startswith(str(RELATION))
                        or predicate.startswith(str(FACT))):
                    continue
                supports.setdefault(triple, []).append({
                    "candidate_graph": str(graph_name),
                    "record": str(record),
                    "confidence": float(Decimal(str(confidence))),
                })
    for records in supports.values():
        records.sort(key=lambda item: (item["candidate_graph"], item["record"]))
    return supports


def _plan_conflicts(window_id, plan):
    found = []
    for entity in plan["entities"]:
        for field_name, field in entity["fields"].items():
            fields = field if isinstance(field, list) else [field]
            for field_item in fields:
                reasons = list(field_item.get("reason_codes", []))
                if any(reason.startswith(("conflict.", "alias."))
                       for reason in reasons):
                    found.append({
                        "window_id": window_id,
                        "section": "entities",
                        "index": entity["index"],
                        "field": field_name,
                        "reason_codes": reasons,
                        "triple": None,
                        "conflicts_with": [],
                    })
    for section in ("relations", "facts"):
        for item in plan[section]:
            reasons = list(item.get("reason_codes", []))
            if any(reason.startswith("conflict.") for reason in reasons):
                found.append({
                    "window_id": window_id,
                    "section": section,
                    "index": item["index"],
                    "reason_codes": reasons,
                    "triple": (tuple(str(term) for term in item["triple"])
                               if item.get("triple") else None),
                    "conflicts_with": [tuple(str(term) for term in triple)
                                       for triple in item.get("conflicts", [])],
                })
    return found


def _key(triple):
    return tuple(str(term) for term in triple)
