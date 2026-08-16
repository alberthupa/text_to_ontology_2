#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from entity_lookup import entity_catalog, identify_entity
from graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, open_graph, save_graph
from ingest_sources import find_text_files, read_source
from llm import model_name
from source_parse import parse_source


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


def add_knowledge(graph, data):
    local_ids = {}
    new_count = resolved_count = 0

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=Path("ontology.ttl"))
    args = parser.parse_args()

    graph = open_graph(args.graph)
    files = find_text_files(args.source, args.graph)
    if not files:
        raise RuntimeError("No text-like files found")

    args.graph.parent.mkdir(parents=True, exist_ok=True)
    for path in files:
        print(f"Reading {path}", flush=True)
        text = read_source(path)
        if not text.strip():
            continue
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, graph)
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        counts = add_knowledge(graph, extraction)
        save_graph(graph, args.graph)
        print(f"  {counts[0]} new, {counts[1]} resolved, "
              f"{counts[2]} relations, {counts[3]} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
