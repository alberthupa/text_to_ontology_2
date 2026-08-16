"""Turn one ingested source text into candidate entities, relations, and facts."""

import json

from rdflib.namespace import OWL, RDF, RDFS

from entity_lookup import entity_catalog
from llm import ask_llm


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


def parse_source(text, graph):
    """Ask the model what this one source says, against the current graph."""
    return ask_llm(make_prompt(text, graph))
