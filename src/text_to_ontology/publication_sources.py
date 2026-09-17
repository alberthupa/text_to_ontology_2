"""Materialize document/file links for published statements and resources."""

import hashlib

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS

from .entity_lookup import identity_key
from .graph_management import ONTO
from .graph_merge import class_triples, class_uri, label


def source_records(graph, document):
    """Keep content identity separate from the files carrying that content."""
    document_uri = ONTO[f"document/{document.document_id}"]
    path = document.source_path or document.name
    key = f"{document.document_id}\n{path}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    file_uri = ONTO[f"source-file/{digest}"]
    graph.add((document_uri, RDF.type, PROV.Entity))
    graph.add((document_uri, RDFS.label, Literal(document.name)))
    graph.add((document_uri, ONTO.sourceFile, file_uri))
    graph.add((file_uri, RDF.type, PROV.Entity))
    graph.add((file_uri, RDFS.label, Literal(document.name)))
    graph.add((file_uri, ONTO.sourcePath, Literal(path)))
    return document_uri, file_uri


def link_statement_sources(graph, document_uri, file_uri):
    """Attach sources to extraction/review evidence, including withheld claims."""
    for statement in list(graph.subjects(RDF.type, RDF.Statement)):
        # The root class is supplied by the app, not defined by source text.
        if graph.value(statement, RDF.subject) == ONTO.Entity:
            continue
        graph.add((statement, PROV.wasDerivedFrom, document_uri))
        graph.add((statement, ONTO.sourceFile, file_uri))


def materialize_sources(graph, document, document_merge, canonical):
    """Accumulate sources only for accepted or corroborated canonical triples."""
    document_uri, file_uri = source_records(graph, document)
    link_statement_sources(graph, document_uri, file_uri)
    for triple in supported_triples(document_merge, canonical):
        if triple[0] == ONTO.Entity:
            continue
        key = " ".join(term.n3() for term in triple)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        statement = ONTO[f"statement/{digest}"]
        graph.add((statement, RDF.type, RDF.Statement))
        graph.add((statement, RDF.type, PROV.Entity))
        for predicate, value in zip(
                (RDF.subject, RDF.predicate, RDF.object), triple):
            graph.add((statement, predicate, value))
        graph.add((statement, PROV.wasDerivedFrom, document_uri))
        graph.add((statement, ONTO.sourceFile, file_uri))

        for resource in triple:
            if not isinstance(resource, URIRef) or resource == ONTO.Entity:
                continue
            # Only domain individuals, classes, and properties get summaries.
            # RDF/OWL/SKOS vocabulary and application bookkeeping do not.
            if not any((resource, RDF.type, kind) in canonical for kind in (
                    ONTO.Entity, OWL.NamedIndividual, OWL.Class, RDFS.Class,
                    RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty)):
                continue
            graph.add((resource, ONTO.sourceDocument, document_uri))
            graph.add((resource, ONTO.sourceFile, file_uri))


def supported_triples(document_merge, canonical):
    """Include duplicate support without assigning sources to unrelated facts."""
    plan = document_merge["merge_plan"]
    triples = set(plan["domain_triples"])
    for section in ("relations", "facts"):
        for item in plan[section]:
            if item["outcome"] not in ("accept", "duplicate"):
                continue
            triple = item["triple"]
            triples.add(triple)
            record = document_merge["candidates"][section][item["index"]]
            prop_type = (OWL.ObjectProperty if section == "relations"
                         else OWL.DatatypeProperty)
            triples.add((triple[1], RDF.type, prop_type))
            triples.add((triple[1], RDFS.label,
                         Literal(label(record["predicate"]))))

    for item in plan["entities"]:
        if item["identity"]["status"] == "review":
            continue
        record = document_merge["candidates"]["entities"][item["index"]]
        uri = item["resolved_uri"]
        kind = label(record["kind"] or "Entity")
        triples.update(class_triples(kind))
        for type_ in (ONTO.Entity, OWL.NamedIndividual, SKOS.Concept,
                      class_uri(kind)):
            triples.add((uri, RDF.type, type_))
        triples.add((uri, ONTO.kind, Literal(kind)))
        fields = item["fields"]
        names = []
        if fields["name"]["outcome"] in ("accept", "duplicate"):
            names.append(record["name"])
        names.extend(field["alias"] for field in fields["aliases"]
                     if field["outcome"] in ("accept", "duplicate"))
        keys = {identity_key(name) for name in names}
        for predicate in (RDFS.label, SKOS.prefLabel, SKOS.altLabel):
            for value in canonical.objects(uri, predicate):
                if identity_key(value) in keys:
                    triples.add((uri, predicate, value))
        if fields["description"]["outcome"] in ("accept", "duplicate"):
            triples.add((uri, RDFS.comment, Literal(record["description"])))
    return {triple for triple in triples if triple in canonical}
