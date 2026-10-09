"""A small fictional starter for the connectivity tests: no real names."""

from rdflib import Graph

from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.starter import starter_publication, validate_starter
from text_to_ontology.vocabulary import read_vocabulary

PROPOSAL = validate_starter({
    "classes": [
        {"name": "Project", "description": "paid delivery work for a client"},
        {"name": "Client", "description": "customer organization"},
        {"name": "Technology", "description": "a technology"},
    ],
    "relations": [
        {"name": "has-client", "description": "project is delivered for this client",
         "domain": "Project", "range": "Client"},
        {"name": "uses-technology", "description": "technology the project uses",
         "domain": "Project", "range": "Technology"},
    ],
    "facts": [
        {"name": "project-summary", "description": "short summary",
         "domain": "Project", "range": "string"},
    ],
})["candidates"]


def schema_graph():
    names = GraphNames()
    return starter_publication(PROPOSAL, names).graphs[names.schema_graphs[0]]


def vocabulary():
    return read_vocabulary(schema_graph())


def starter_store(path=None):
    store = RdflibGraphStore(path=path)
    store.publish(starter_publication(PROPOSAL))
    return store


def entity(local_id, name, kind, confidence=0.9, **extra):
    return {"id": local_id, "name": name, "kind": kind,
            "confidence": confidence, **extra}


def relation(subject, predicate, object_, confidence=0.9):
    return {"subject": subject, "predicate": predicate, "object": object_,
            "confidence": confidence}


def answer(entities=(), relations=(), facts=()):
    return {"entities": list(entities), "relations": list(relations),
            "facts": list(facts)}


class ScriptedExtractor:
    """Answers each prompt with `respond(prompt, number)`; keeps every prompt."""

    def __init__(self, respond):
        self.respond = respond
        self.prompts = []

    def model(self):
        return "fake-model"

    def extract(self, prompt):
        self.prompts.append(prompt)
        return self.respond(prompt, len(self.prompts))


def union(store, names=None):
    names = names or GraphNames()
    graph = Graph()
    for name in store.graph_names():
        for triple in store.get(name):
            graph.add(triple)
    return graph
