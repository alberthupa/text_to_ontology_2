"""Which source file said what.

Business side - added to the data graph, prefix `src:`:

    src:file/<hash of path>  a src:SourceFile ;
                             rdfs:label "notes.md" ;
                             src:path "client/project/notes.md" .
    entity:acme              src:fromFile src:file/... .
    src:statement/<hash>     a rdf:Statement ;
                             rdf:subject / rdf:predicate / rdf:object ... ;
                             src:fromFile src:file/... .

One file node per path, so re-ingesting an edited file adds no new node.
Only entities and the relations and facts between them get a source link;
classes and properties are the starter's, not the texts'.

Tracing side - kept in the provenance and review graphs, prefix `trace:`:

    trace:document/<content id>  a prov:Entity ; rdfs:label "notes.md" ;
                                 trace:sourceFile src:file/... .
    <entity or statement>        trace:sourceDocument trace:document/... .

The document is one *version* of a file's content; that is run history.
"""

import hashlib

from rdflib import Graph, Literal
from rdflib.namespace import PROV, RDF, RDFS

from .graph_management import ONTO, SRC, TRACE


# ---------- stable IRIs ----------

def file_uri(document):
    """One node per source path, whatever its content is today."""
    path = document.source_path or document.name
    return SRC["file/" + hashlib.sha256(path.encode("utf-8")).hexdigest()]


def statement_uri(triple):
    """The stable node for one relation or fact triple."""
    key = " ".join(term.n3() for term in triple)
    return SRC["statement/" + hashlib.sha256(key.encode("utf-8")).hexdigest()]


def document_uri(document):
    """One version of a file's content: tracing, not business data."""
    return TRACE[f"document/{document.document_id}"]


# ---------- business side: the data graph ----------

def source_attribution(document, document_merge, canonical):
    """The `src:` triples one published document adds to the data graph.

    Only what was accepted, or corroborated as a duplicate, and is really in
    `canonical` gets a link; withheld claims stay in the review graph.
    """
    graph = Graph()
    source = file_uri(document)
    graph.add((source, RDF.type, SRC.SourceFile))
    graph.add((source, RDFS.label, Literal(document.name)))
    graph.add((source, SRC.path,
               Literal(document.source_path or document.name)))
    for entity in published_entities(document_merge, canonical):
        graph.add((entity, SRC.fromFile, source))
    for triple in published_statements(document_merge, canonical):
        statement = statement_uri(triple)
        graph.add((statement, RDF.type, RDF.Statement))
        graph.add((statement, RDF.subject, triple[0]))
        graph.add((statement, RDF.predicate, triple[1]))
        graph.add((statement, RDF.object, triple[2]))
        graph.add((statement, SRC.fromFile, source))
    return graph


def published_entities(document_merge, canonical):
    """Entities this document named that are in the published graph."""
    found = set()
    for item in document_merge["merge_plan"]["entities"]:
        uri = item.get("resolved_uri")
        if item["identity"]["status"] != "review" and uri is not None \
                and (uri, RDF.type, ONTO.Entity) in canonical:
            found.add(uri)
    return found


def published_statements(document_merge, canonical):
    """Relation and fact triples this document asserted or corroborated."""
    plan = document_merge["merge_plan"]
    return {item["triple"]
            for section in ("relations", "facts")
            for item in plan[section]
            if item["outcome"] in ("accept", "duplicate")
            and item["triple"] in canonical}


def forget_statement(graph, triple):
    """Drop the `src:statement` node of a triple that was removed."""
    graph.remove((statement_uri(triple), None, None))


# ---------- tracing side: provenance and review graphs ----------

def document_record(graph, document):
    """Add the document record and return its IRI."""
    document_ = document_uri(document)
    graph.add((document_, RDF.type, PROV.Entity))
    graph.add((document_, RDFS.label, Literal(document.name)))
    graph.add((document_, TRACE.sourceFile, file_uri(document)))
    return document_


def trace_sources(document, document_merge, canonical):
    """Which document version supported each published entity and statement."""
    graph = Graph()
    document_ = document_record(graph, document)
    for entity in published_entities(document_merge, canonical):
        graph.add((entity, TRACE.sourceDocument, document_))
    for triple in published_statements(document_merge, canonical):
        graph.add((statement_uri(triple), TRACE.sourceDocument, document_))
    return graph


def link_statement_sources(graph, document):
    """Point every reified statement of evidence or review at its sources."""
    document_ = document_record(graph, document)
    source = file_uri(document)
    for statement in list(graph.subjects(RDF.type, RDF.Statement)):
        # The root class is supplied by the app, not defined by source text.
        if graph.value(statement, RDF.subject) == ONTO.Entity:
            continue
        graph.add((statement, TRACE.sourceDocument, document_))
        graph.add((statement, TRACE.sourceFile, source))
