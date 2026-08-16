"""Merge one parsed source result into the canonical graph."""

import re
import unicodedata

from rdflib import Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from entity_lookup import entity_catalog, identify_entity
from graph_management import CLASS, ENTITY, FACT, ONTO, RELATION


def slug(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unnamed"


def label(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return re.sub(r"[_-]+", " ", text).strip()


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
        kind_uri = CLASS[slug(kind)]
        graph.add((kind_uri, RDF.type, OWL.Class))
        graph.add((kind_uri, RDFS.subClassOf, ONTO.Entity))
        graph.add((kind_uri, RDFS.label, Literal(kind)))
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
