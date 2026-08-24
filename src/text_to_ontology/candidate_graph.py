"""Turn one validated extraction package into an RDF candidate graph.

The input is the already-validated, normalized candidate package from
candidate_validation - raw LLM answers can never reach this module. The
output is one inspectable RDF graph that keeps assertion and evidence apart:

  - every record becomes a `prov:Collection`; its supported statements are
    identified by RDF 1.1 reification (`rdf:Statement` members);
  - the asserted triples themselves are also present, so reification alone
    is never treated as assertion;
  - each record carries its extraction confidence as a `dqv:QualityMeasurement`
    against the project-owned `dqv:Metric` instance, typed xsd:decimal [0,1];
  - PROV-O links document, window, extraction activity, extractor agent,
    records, and measurements.

Provisional IRIs are deterministic functions of document ID and the record's
own identifiers, so the same response always produces the same graph, and the
same real thing named twice gets one IRI.
"""

import re
from datetime import date
from decimal import Decimal

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD

# DQV is not bundled with rdflib's namespace module; it is a W3C vocabulary.
DQV = Namespace("http://www.w3.org/ns/dqv#")

from .graph_management import CLASS, FACT, ONTO, RELATION, bind
from .graph_merge import slug

# Bumped whenever the mapping rules change meaningfully.
CANDIDATE_MAPPING_VERSION = 1

CANDIDATE_BASE = "http://example.org/text-ontology/"
PROVISIONAL = Namespace(CANDIDATE_BASE + "provisional/")
EXTRACTION_CONFIDENCE_METRIC = URIRef(CANDIDATE_BASE + "metric/extraction-confidence")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def literal_value(value):
    """A conservative XSD-typed literal; ambiguity stays a plain string."""
    if type(value) is bool:
        return Literal(value)
    if type(value) is int:
        return Literal(value)
    if type(value) is float:
        return Literal(Decimal(str(value)))
    text = str(value)
    # Only real calendar dates become xsd:date; leading-zero strings and
    # impossible dates (2026-13-45) remain plain literals.
    if ISO_DATE.match(text):
        try:
            return Literal(date.fromisoformat(text))
        except ValueError:
            return Literal(text)
    return Literal(text)


def provisional_entity_iri(document_id, local_id):
    """The stable provisional IRI for one unresolved individual."""
    return PROVISIONAL[f"{document_id}/{local_id}"]


def build_candidate_graph(candidates, document_id, window_id, activity_id,
                          extractor_model, entity_iris=None,
                          assertion_triples=None):
    """One validated package in, one candidate graph out. Deterministic."""
    graph = Graph()
    bind(graph)
    graph.bind("prov", PROV)
    graph.bind("dqv", DQV)

    _declare_metric(graph)
    _declare_provenance_chain(graph, document_id, window_id, activity_id,
                              extractor_model)

    entity_iris = entity_iris or {}
    assertion_triples = assertion_triples or {}
    entities = {
        record["id"]: entity_iris.get(
            record["id"], provisional_entity_iri(document_id, record["id"]))
        for record in candidates["entities"]
    }
    for index, record in enumerate(candidates["entities"]):
        record_iri = _record_iri(document_id, window_id, "entity", index)
        _emit_record(graph, record_iri, activity_id, record["confidence"],
                     _entity_triples(record, entities[record["id"]]))
    for index, record in enumerate(candidates["relations"]):
        record_iri = _record_iri(document_id, window_id, "relation", index)
        triple = assertion_triples.get(("relations", index), (
            entities[record["subject"]],
            RELATION[slug(record["predicate"])],
            entities[record["object"]],
        ))
        _emit_record(graph, record_iri, activity_id, record["confidence"],
                     [triple])
    for index, record in enumerate(candidates["facts"]):
        record_iri = _record_iri(document_id, window_id, "fact", index)
        triple = assertion_triples.get(("facts", index), (
            entities[record["subject"]],
            FACT[slug(record["predicate"])],
            literal_value(record["value"]),
        ))
        _emit_record(graph, record_iri, activity_id, record["confidence"],
                     [triple])
    return graph


def _record_iri(document_id, window_id, section, index):
    return URIRef(
        f"{CANDIDATE_BASE}candidate/{document_id}/{window_id}/{section}/{index}")


def _declare_metric(graph):
    graph.add((EXTRACTION_CONFIDENCE_METRIC, RDF.type, DQV.Metric))
    graph.add((EXTRACTION_CONFIDENCE_METRIC, RDFS.label,
               Literal("extraction confidence")))


def _declare_provenance_chain(graph, document_id, window_id, activity_id,
                              extractor_model):
    document = URIRef(f"{CANDIDATE_BASE}document/{document_id}")
    window = URIRef(f"{CANDIDATE_BASE}window/{window_id}")
    activity = URIRef(f"{CANDIDATE_BASE}activity/{activity_id}")
    agent = URIRef(f"{CANDIDATE_BASE}agent/{slug(extractor_model)}")

    graph.add((document, RDF.type, PROV.Entity))
    graph.add((window, RDF.type, PROV.Entity))
    graph.add((window, PROV.wasDerivedFrom, document))
    graph.add((activity, RDF.type, PROV.Activity))
    graph.add((activity, PROV.used, window))
    graph.add((agent, RDF.type, PROV.SoftwareAgent))
    graph.add((agent, RDFS.label, Literal(extractor_model)))
    graph.add((activity, PROV.wasAssociatedWith, agent))


def _entity_triples(record, iri):
    """One entity record as RDF: types instead of kind strings, SKOS names."""
    kind_uri = CLASS[slug(record["kind"])]
    triples = [
        (kind_uri, RDF.type, OWL.Class),
        (kind_uri, RDFS.subClassOf, ONTO.Entity),
        (kind_uri, RDFS.label, Literal(record["kind"])),
        (iri, RDF.type, kind_uri),
        (iri, RDFS.label, Literal(record["name"])),
    ]
    if record.get("description"):
        triples.append((iri, SKOS.definition, Literal(record["description"])))
    for alias in record.get("aliases") or []:
        triples.append((iri, SKOS.altLabel, Literal(alias)))
    return triples


def _emit_record(graph, record_iri, activity_id, confidence, triples):
    """Assert the triples, then attach them to the record as reified members."""
    activity = URIRef(f"{CANDIDATE_BASE}activity/{activity_id}")
    graph.add((record_iri, RDF.type, PROV.Collection))
    graph.add((record_iri, PROV.wasGeneratedBy, activity))

    measurement = URIRef(str(record_iri) + "/confidence")
    graph.add((measurement, RDF.type, DQV.QualityMeasurement))
    graph.add((measurement, DQV.computedOn, record_iri))
    graph.add((measurement, DQV.isMeasurementOf, EXTRACTION_CONFIDENCE_METRIC))
    graph.add((measurement, DQV.value,
               Literal(Decimal(str(confidence)), datatype=XSD.decimal)))
    graph.add((measurement, PROV.wasGeneratedBy, activity))

    for number, triple in enumerate(triples):
        graph.add(triple)
        statement = URIRef(f"{record_iri}/statement/{number}")
        graph.add((statement, RDF.type, RDF.Statement))
        graph.add((statement, RDF.subject, triple[0]))
        graph.add((statement, RDF.predicate, triple[1]))
        graph.add((statement, RDF.object, triple[2]))
        graph.add((record_iri, PROV.hadMember, statement))
