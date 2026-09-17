"""Merge one parsed source result into the canonical graph."""

import re
import unicodedata

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from .entity_lookup import entity_catalog, identify_entity
from .graph_management import CLASS, ENTITY, FACT, ONTO, RELATION


def slug(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unnamed"


def label(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return re.sub(r"[_-]+", " ", text).strip()


def class_uri(kind):
    """Reuse the built-in Entity class for generic or missing kinds."""
    name = slug((kind or "Entity").strip() or "Entity")
    return ONTO.Entity if name == "entity" else CLASS[name]


def class_triples(kind):
    """Declare a kind without creating a duplicate root or self-subclass."""
    uri = class_uri(kind)
    name = "Entity" if uri == ONTO.Entity else kind
    triples = [(uri, RDF.type, OWL.Class),
               (uri, RDFS.label, Literal(name))]
    if uri != ONTO.Entity:
        triples.append((uri, RDFS.subClassOf, ONTO.Entity))
    return triples


def new_entity_uri(graph, name):
    stem, number = slug(name), 1
    while True:
        suffix = "" if number == 1 else f"-{number}"
        uri = ENTITY[stem + suffix]
        if (uri, None, None) not in graph:
            return uri
        number += 1


def merge_into_graph(graph, data):
    local_ids = {}
    new_count = resolved_count = 0

    # Each entity is merged before the next one is identified, so a later
    # entity in the same response can resolve to one added just above.
    for entity in data.get("entities", []):
        if not entity.get("id") or not entity.get("name"):
            continue
        uri = identify_entity(entity, entity_catalog(graph))
        if uri is None:
            uri = new_entity_uri(graph, entity["name"])
            new_count += 1
        else:
            resolved_count += 1
        local_ids[str(entity["id"])] = uri

        kind = label(entity.get("kind") or "Entity")
        kind_uri = class_uri(kind)
        for triple in class_triples(kind):
            graph.add(triple)
        graph.add((uri, RDF.type, ONTO.Entity))
        graph.add((uri, RDF.type, OWL.NamedIndividual))
        graph.add((uri, RDF.type, SKOS.Concept))
        graph.add((uri, RDF.type, kind_uri))
        graph.add((uri, ONTO.kind, Literal(kind)))

        if graph.value(uri, SKOS.prefLabel) is None:
            graph.add((uri, SKOS.prefLabel, Literal(entity["name"])))
            graph.add((uri, RDFS.label, Literal(entity["name"])))
        elif str(graph.value(uri, SKOS.prefLabel)) != entity["name"]:
            graph.add((uri, SKOS.altLabel, Literal(entity["name"])))
        for alias in entity.get("aliases") or []:
            graph.add((uri, SKOS.altLabel, Literal(alias)))
        if entity.get("description") and graph.value(uri, RDFS.comment) is None:
            graph.add((uri, RDFS.comment, Literal(entity["description"])))

    relation_count = 0
    for relation in data.get("relations", []):
        subject = local_ids.get(str(relation.get("subject")))
        object_ = local_ids.get(str(relation.get("object")))
        name = relation.get("predicate")
        if subject and object_ and name:
            predicate = RELATION[slug(name)]
            graph.add((predicate, RDF.type, OWL.ObjectProperty))
            graph.add((predicate, RDFS.label, Literal(label(name))))
            old = (subject, predicate, object_) in graph
            graph.add((subject, predicate, object_))
            relation_count += not old

    fact_count = 0
    for fact in data.get("facts", []):
        subject = local_ids.get(str(fact.get("subject")))
        name = fact.get("predicate")
        if subject and name and fact.get("value") is not None:
            predicate = FACT[slug(name)]
            value = Literal(fact["value"])
            graph.add((predicate, RDF.type, OWL.DatatypeProperty))
            graph.add((predicate, RDFS.label, Literal(label(name))))
            old = (subject, predicate, value) in graph
            graph.add((subject, predicate, value))
            fact_count += not old

    return new_count, resolved_count, relation_count, fact_count


def apply_merge_plan(source_graph, plan):
    """Apply an already-complete merge plan to a copy of the current graph.

    Every identity, acceptance, and conflict decision was made during
    read-only planning; this function only copies namespace bindings, asserts
    the plan's decided domain and audit triples, and reports. The input graph
    is left triple-identical, including when anything here fails.
    """
    graph = Graph()
    for prefix, namespace in source_graph.namespaces():
        graph.bind(prefix, namespace)
    for triple in source_graph:
        graph.add(triple)

    assertion_plans = plan["relations"] + plan["facts"]
    accepted_assertions = sum(1 for item in assertion_plans
                              if item["outcome"] == "accept")
    declaration_triples = sum(len(item.get("declarations", ()))
                              for item in assertion_plans)
    relation_triples = sum(1 for item in plan["relations"]
                           if item["outcome"] == "accept")
    fact_triples = sum(1 for item in plan["facts"]
                       if item["outcome"] == "accept")
    summaries = plan["counts"]["entity_summaries"]

    result = {
        "new_entities": plan["counts"]["identities"]["new"],
        "resolved_entities": plan["counts"]["identities"]["resolved"],
        "relation_triples": relation_triples,
        "fact_triples": fact_triples,
        "metadata_triples": (len(plan["domain_triples"])
                             - accepted_assertions - declaration_triples),
        "duplicates": (plan["counts"]["assertions"]["duplicate"]
                       + summaries["duplicate"]),
        "review": (plan["counts"]["assertions"]["review"]
                   + summaries["review"] + summaries["partial_review"]),
        "audit_triples": sum(1 for triple in plan["audit_triples"]
                             if triple not in source_graph),
    }

    for triple in plan["domain_triples"]:
        graph.add(triple)
    for triple in plan["audit_triples"]:
        graph.add(triple)
    return graph, result
