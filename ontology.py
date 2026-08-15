#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS

from llm import ask_llm, model_name


# Change this when you want permanent URIs of your own.
BASE = "http://example.org/text-ontology/"
ONTO = Namespace(BASE)
ENTITY = Namespace(BASE + "entity/")
CLASS = Namespace(BASE + "class/")
RELATION = Namespace(BASE + "relation/")
FACT = Namespace(BASE + "fact/")

TEXT_FILES = {
    ".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".html", ".log",
}


def bind(graph):
    for prefix, namespace in {
        "onto": ONTO, "entity": ENTITY, "class": CLASS, "relation": RELATION,
        "fact": FACT, "owl": OWL, "rdf": RDF, "rdfs": RDFS, "sh": SH,
        "skos": SKOS,
    }.items():
        graph.bind(prefix, namespace)


def open_graph(path):
    graph = Graph()
    bind(graph)
    if path.exists():
        graph.parse(path, format="turtle")
        return graph

    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))

    # A tiny SHACL shape: every entity must have a preferred label.
    rule = BNode()
    graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
    graph.add((ONTO.EntityShape, SH.targetClass, ONTO.Entity))
    graph.add((ONTO.EntityShape, SH.property, rule))
    graph.add((rule, SH.path, SKOS.prefLabel))
    graph.add((rule, SH.minCount, Literal(1)))
    return graph


def slug(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unnamed"


def label(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return re.sub(r"[_-]+", " ", text).strip()


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


def make_prompt(text, graph):
    entities = json.dumps(entity_catalog(graph), ensure_ascii=False)
    properties = sorted({
        str(name)
        for property_type in (OWL.ObjectProperty, OWL.DatatypeProperty)
        for uri in graph.subjects(RDF.type, property_type)
        for name in graph.objects(uri, RDFS.label)
    })
    return f"""
Extract only knowledge stated or clearly implied by SOURCE.

EXISTING ENTITIES:
{entities}

EXISTING PROPERTY NAMES (reuse them when they mean the same thing):
{json.dumps(properties, ensure_ascii=False)}

Entity resolution is important. Set existing_id to an existing entity's exact id
only when it is the same real thing in this context. Use its names, kind, and
description. A similar name alone is not enough. Otherwise use null. Include one
entity record per real thing mentioned in this source.

Return this exact JSON shape:
{{
  "entities": [
    {{"id": "e1", "name": "preferred name", "kind": "Person",
      "description": "short source-grounded description",
      "aliases": ["other source name"], "existing_id": null}}
  ],
  "relations": [
    {{"subject": "e1", "predicate": "works for", "object": "e2"}}
  ],
  "facts": [
    {{"subject": "e1", "predicate": "birth date", "value": "1950-01-01"}}
  ]
}}

Relation endpoints and fact subjects must use ids from entities. Use empty lists
when needed. Return JSON only.

SOURCE:
---
{text}
---
""".strip()


def resolve(entity, catalog):
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
        uri = resolve(entity, entity_catalog(graph))
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


def find_text_files(source, graph_path):
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise RuntimeError(f"Source does not exist: {source}")
    graph_path = graph_path.resolve()
    return sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.resolve() != graph_path
        and path.suffix.lower() in TEXT_FILES
    )


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
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = ask_llm(make_prompt(text, graph))
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        counts = add_knowledge(graph, extraction)
        graph.serialize(args.graph, format="turtle")
        print(f"  {counts[0]} new, {counts[1]} resolved, "
              f"{counts[2]} relations, {counts[3]} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
