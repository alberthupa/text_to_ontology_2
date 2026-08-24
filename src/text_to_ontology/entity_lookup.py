"""Decide whether one parsed entity is already in the graph."""

import re
import unicodedata
from difflib import SequenceMatcher

from rdflib import URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .graph_management import ONTO


CLOSE_SPELLING_THRESHOLD = 0.96


def identity_key(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def entity_catalog(graph):
    """The small identity index sent to the LLM and used locally."""
    result = []
    for uri in sorted(set(graph.subjects(RDF.type, ONTO.Entity)), key=str):
        names = {
            str(name)
            for predicate in (SKOS.prefLabel, SKOS.altLabel)
            for name in graph.objects(uri, predicate)
        }
        result.append({
            "id": str(uri),
            "names": sorted(names),
            "kind": str(graph.value(uri, ONTO.kind) or ""),
            "description": str(graph.value(uri, RDFS.comment) or ""),
        })
    return result


def identify_entity(entity, catalog):
    """Combine the LLM's contextual decision with conservative local matching."""
    by_id = {item["id"]: item for item in catalog}
    if entity.get("existing_id") in by_id:
        return URIRef(entity["existing_id"])

    new_names = [entity["name"], *(entity.get("aliases") or [])]
    new_kind = identity_key(entity.get("kind", ""))
    exact = {
        item["id"]
        for item in catalog
        if new_kind and new_kind == identity_key(item["kind"])
        if {identity_key(name) for name in new_names}
        & {identity_key(name) for name in item["names"]}
    }
    if len(exact) == 1:
        return URIRef(exact.pop())

    # Catch only a unique, extremely close spelling variant of the same kind.
    close = []
    for item in catalog:
        if not new_kind or identity_key(item["kind"]) != new_kind:
            continue
        identity_score = max(
            (SequenceMatcher(None, identity_key(entity["name"]), identity_key(name)).ratio()
             for name in item["names"]),
            default=0,
        )
        if identity_score >= 0.96:
            close.append((identity_score, item["id"]))
    close.sort(reverse=True)
    if close and (len(close) == 1 or close[0][0] > close[1][0]):
        return URIRef(close[0][1])
    return None


def _keys(values):
    """Normalized comparison keys for a name collection."""
    return {identity_key(value) for value in values if value}


def identity_decision(entity, catalog, planned_catalog=(), *,
                      min_new_confidence=0.80, allocate_uri=None,
                      provisional_uri=None):
    """One deterministic, reasoned identity decision for a candidate entity.

    Read only: neither the catalogs nor the candidate record are modified.
    The planner's virtual state enters through `planned_catalog` (entities
    accepted earlier in the same response) and through the `allocate_uri` and
    `provisional_uri` callables, which see the planner's URI reservations.

    The result has exactly these fields: local_id, status (existing, new, or
    review), uri, method, identity_score, suggestions, reason_codes. A close spelling
    never resolves automatically; it only produces review evidence.
    """
    local_id = entity.get("id")
    kind = identity_key(entity.get("kind") or "")
    name_keys = _keys([entity.get("name"), *(entity.get("aliases") or [])])

    def decision(status, uri, method, identity_score=None, suggestions=(), reasons=()):
        return {
            "local_id": local_id,
            "status": status,
            "uri": uri,
            "method": method,
            "identity_score": identity_score,
            "suggestions": sorted(suggestions, key=lambda item: item["uri"]),
            "reason_codes": sorted(set(reasons)),
        }

    if entity.get("existing_id") in {item["id"] for item in catalog}:
        return decision("existing", URIRef(entity["existing_id"]), "explicit_id")

    pool = [(item, False) for item in catalog]
    pool += [(item, True) for item in planned_catalog]

    exact = []
    for item, planned in pool:
        item_kind = identity_key(item["kind"])
        if not kind or not item_kind or item_kind != kind:
            continue
        if name_keys & _keys(item["names"]):
            exact.append((item, planned))
    if len(exact) == 1:
        item, planned = exact[0]
        if planned:
            method = "planned_exact"
        elif identity_key(entity.get("name")) in _keys(item["names"]):
            method = "exact_name"
        else:
            method = "exact_alias"
        return decision("existing", URIRef(item["id"]), method)
    if len(exact) > 1:
        suggestions = [{"uri": item["id"], "method": "exact", "identity_score": None}
                       for item, _ in exact]
        return decision("review", None, "ambiguous_exact",
                        suggestions=suggestions,
                        reasons=("identity.ambiguous_exact",))

    collisions = [
        item for item, _ in pool
        if identity_key(item["kind"]) != kind
        and name_keys & _keys(item["names"])
    ]
    if collisions:
        suggestions = [{"uri": item["id"], "method": "kind_collision",
                        "identity_score": None} for item in collisions]
        return decision("review", None, "kind_collision",
                        suggestions=suggestions,
                        reasons=("identity.kind_collision",))

    preferred = identity_key(entity.get("name"))
    close = []
    if preferred:
        for item, _ in pool:
            item_kind = identity_key(item["kind"])
            if not kind or not item_kind or item_kind != kind:
                continue
            identity_score = max(
                (SequenceMatcher(None, preferred, key).ratio()
                 for key in _keys(item["names"])),
                default=0,
            )
            if identity_score >= CLOSE_SPELLING_THRESHOLD:
                close.append({"uri": item["id"], "method": "close_spelling",
                              "identity_score": identity_score})
    if close:
        top = max(item["identity_score"] for item in close)
        return decision("review", None, "close_spelling",
                        identity_score=top,
                        suggestions=close,
                        reasons=("identity.close_spelling",))

    confidence = entity.get("confidence")
    if confidence is not None and confidence >= min_new_confidence \
            and allocate_uri is not None:
        return decision("new", allocate_uri(entity["name"]), "new")
    return decision(
        "review",
        provisional_uri(entity) if provisional_uri is not None else None,
        "new",
        reasons=("identity.new_below_confidence",),
    )
