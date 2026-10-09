"""The whole starter schema, as one short block every extraction prompt carries.

Word matching picks the *data* a window may need, but the schema is small and
always needed: without it the model guesses relationships by name and joins
the wrong classes. So in data-only ingestion the complete schema - every
class, relationship, and fact, with direction and meaning - is rendered once
per run and placed at the top of every window's context, paid from its own
token budget.

The schema is already marked as the seed by living in its own named graph;
`schema_digest` names the exact schema a run used.

Nothing here writes to a graph.
"""

import hashlib

from rdflib import Graph, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, RDF, RDFS

from .context_render import clean, field
from .graph_management import ONTO

# What to do with a thing no class fits, with and without the root class.
WITH_ROOT = ('Use "Entity" only when no class fits; an Entity cannot be the\n'
             '  subject or object of a relationship or a fact.')
WITHOUT_ROOT = "Leave out anything no class fits."

HEADING = "CORE SCHEMA — the only classes and relationships you may use"

RULES = """Rules for this schema:
- "kind" must be one of the classes above, the most specific one the source
  supports. ${fallback}
- Use a relationship only from its subject class to its object class, as shown.
- "name" is the base (dictionary) form of a name, e.g. "Warszawa", not
  "Warszawy" or "Warszawie". Put other forms you saw in "aliases"."""


def _label(graph, iri):
    found = graph.value(iri, RDFS.label)
    if found is not None:
        return clean(found)
    return clean(str(iri).rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1])


def _meaning(graph, iri):
    comment = graph.value(iri, RDFS.comment)
    return f": {field(comment)}" if comment is not None else ""


def _named(graph, rdf_type):
    return [subject for subject in graph.subjects(RDF.type, rdf_type)
            if isinstance(subject, URIRef)]


def render_core_schema(graph):
    """Every declared class, relationship, and fact as one block of text.

    Deterministic: the same schema always gives the same text, whatever the
    triple order. The root class comes last, with the rule that limits it.
    """
    classes = set(_named(graph, OWL.Class)) | set(_named(graph, RDFS.Class))
    by_label = lambda iri: (_label(graph, iri).lower(), str(iri))
    lines = [HEADING, "Classes:"]
    for iri in sorted(classes - {ONTO.Entity}, key=by_label):
        lines.append(f"- {_label(graph, iri)}{_meaning(graph, iri)}")
    if ONTO.Entity in classes:
        lines.append("- Entity: only for things that fit no class above")

    relations = sorted(_named(graph, OWL.ObjectProperty), key=by_label)
    if relations:
        lines.append("Relationships (subject --name--> object):")
    for iri in relations:
        domain = graph.value(iri, RDFS.domain)
        target = graph.value(iri, RDFS.range)
        lines.append(
            f"- {_label(graph, domain) if domain is not None else 'anything'}"
            f" --{_label(graph, iri)}--> "
            f"{_label(graph, target) if target is not None else 'anything'}"
            f"{_meaning(graph, iri)}")

    facts = sorted(_named(graph, OWL.DatatypeProperty), key=by_label)
    if facts:
        lines.append("Facts (subject . name = value):")
    for iri in facts:
        domain = graph.value(iri, RDFS.domain)
        target = graph.value(iri, RDFS.range)
        lines.append(
            f"- {_label(graph, domain) if domain is not None else 'anything'}"
            f" . {_label(graph, iri)} = "
            f"{_label(graph, target) if target is not None else 'value'}"
            f"{_meaning(graph, iri)}")
    fallback = WITH_ROOT if ONTO.Entity in classes else WITHOUT_ROOT
    return "\n".join(lines + ["", RULES.replace("${fallback}", fallback)])


def schema_digest(schema_graphs):
    """A short stable hash of the schema graphs, for run reports."""
    combined = Graph()
    for graph in schema_graphs:
        for triple in graph:
            combined.add(triple)
    # Canonical blank-node names, so restrictions hash the same every time.
    lines = sorted(" ".join(term.n3() for term in triple)
                   for triple in to_canonical_graph(combined))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:12]
