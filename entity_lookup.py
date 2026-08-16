"""Decide whether one parsed entity is already in the graph."""

import re
import unicodedata
from difflib import SequenceMatcher

from rdflib import URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from graph_management import ONTO


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
        score = max(
            (SequenceMatcher(None, identity_key(entity["name"]), identity_key(name)).ratio()
             for name in item["names"]),
            default=0,
        )
        if score >= 0.96:
            close.append((score, item["id"]))
    close.sort(reverse=True)
    if close and (len(close) == 1 or close[0][0] > close[1][0]):
        return URIRef(close[0][1])
    return None
