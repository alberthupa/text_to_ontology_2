"""Compile and atomically publish one document-level merge plan."""

import hashlib
from dataclasses import dataclass

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS

from .candidate_graph import provisional_entity_iri
from .graph_management import TRACE, seed_graph
from .graph_partition import partition_graph
from .publication_sources import (
    document_uri, link_statement_sources, source_attribution, trace_sources,
)
from .graph_store import GraphNames, Publication, RdflibGraphStore
from .source_validation import embedded_shape_graph, validate_source_graph


@dataclass
class DocumentPublicationPlan:
    """The exact graph replacements and validation for one document."""

    document_id: str
    document_merge: dict
    proposed_validation: object
    publication: Publication
    counts: dict


class PublicationValidationError(RuntimeError):
    """The proposed post-merge canonical data failed SHACL validation."""

    def __init__(self, plan):
        super().__init__(
            "proposed post-merge data does not conform to SHACL shapes")
        self.plan = plan
        self.validation = plan.proposed_validation


class LegacyTurtleDatasetStore:
    """Explicit compatibility adapter: named roles persisted as one Turtle union."""

    def __init__(self, legacy_store, path, names, save_graph):
        self.path = path
        self.names = names
        self.save_graph = save_graph
        self.memory = RdflibGraphStore()
        combined = legacy_store.load(path)
        for name, graph in split_legacy_graph(combined, names).items():
            if len(graph):
                self.memory.put(name, graph)
        self.publish_calls = 0

    def get(self, name):
        return self.memory.get(name)

    def graph_names(self):
        return self.memory.graph_names()

    def query(self, sparql, **bindings):
        return self.memory.query(sparql, **bindings)

    def publish(self, publication=None):
        prospective = RdflibGraphStore()
        for name in self.memory.graph_names():
            prospective.put(name, self.memory.get(name))
        if publication is not None:
            prospective.publish(publication)
        combined = union_graphs(
            prospective.get(name) for name in prospective.graph_names())
        self.save_graph(combined, self.path)
        self.memory = prospective
        self.publish_calls += 1


def split_legacy_graph(graph, names):
    """Place a compatibility Turtle graph into explicit in-memory roles."""
    schema, data, support = partition_graph(graph)
    shapes = embedded_shape_graph(graph)
    provenance = copy_graph(support)
    for triple in shapes:
        provenance.remove(triple)
    return {
        names.schema_graphs[0]: schema,
        names.shape_graphs[0]: shapes,
        names.target_graph: data,
        names.provenance_graph: provenance,
        names.review_graph: Graph(),
    }


def initial_role_graphs(store, names):
    """Read all final roles; a wholly fresh store gets the virtual seed."""
    roles = _read_roles(store, names)
    if any(len(graph) for graph in roles.values()):
        return roles
    return split_legacy_graph(seed_graph(), names)


def _read_roles(store, names):
    graph_names = [
        *names.schema_graphs, *names.shape_graphs, *names.data_graphs,
        names.target_graph, names.provenance_graph, names.review_graph,
    ]
    return {name: store.get(name) for name in graph_names}


def canonical_graph(roles, names):
    """The full identity/conflict scope: schema plus every canonical data graph."""
    return union_graphs(
        roles[name] for name in [
            *names.schema_graphs, *names.data_graphs, names.target_graph])


def shape_graphs(roles, names):
    return tuple(roles[name] for name in names.shape_graphs)


def compile_document_publication(document, document_merge, candidate_graphs,
                                 packages, admission_plans, roles, names,
                                 validation_shapes=None, trace=False):
    """Build proposed target/provenance/review replacements without writing.

    The data graph gets the accepted triples plus their `src:` source links.
    The provenance graph always gets the document record; the full candidate
    evidence (every window answer, PROV/DQV) only when `trace` is on.
    """
    merge_plan = document_merge["merge_plan"]
    target = copy_graph(roles[names.target_graph])
    for triple in merge_plan["domain_triples"]:
        target.add(triple)

    proposed_roles = dict(roles)
    proposed_roles[names.target_graph] = target
    proposed_data = canonical_graph(proposed_roles, names)
    for triple in source_attribution(document, document_merge, proposed_data):
        target.add(triple)
    evidence = trace_sources(document, document_merge, proposed_data)
    if trace:
        for triple in remap_candidate_evidence(
                document, document_merge, candidate_graphs, packages,
                admission_plans):
            evidence.add(triple)
        link_statement_sources(evidence, document)
    proposed_data = canonical_graph(proposed_roles, names)
    provenance = copy_graph(roles[names.provenance_graph])
    for triple in evidence:
        provenance.add(triple)

    review = copy_graph(roles[names.review_graph])
    for triple in build_review_graph(document, document_merge):
        review.add(triple)

    validation = validate_source_graph(
        proposed_data,
        (tuple(validation_shapes) if validation_shapes is not None
         else shape_graphs(roles, names)))
    publication = Publication(graphs={
        names.target_graph: target,
        names.provenance_graph: provenance,
        names.review_graph: review,
        **{name: roles[name] for name in names.schema_graphs},
        **{name: roles[name] for name in names.shape_graphs},
        **{name: roles[name] for name in names.data_graphs},
    })
    return DocumentPublicationPlan(
        document_id=document.document_id,
        document_merge=document_merge,
        proposed_validation=validation,
        publication=publication,
        counts=_publication_counts(merge_plan, evidence, review),
    )


def publish_document(store, plan):
    """The only final write: one atomic store publication call."""
    store.publish(plan.publication)


def remap_candidate_evidence(document, document_merge, candidate_graphs,
                             packages, admission_plans):
    """Keep every PROV/DQV occurrence while remapping its reified statements."""
    result = Graph()
    candidates_by_window = {
        window.window_id: candidates
        for window, _model, candidates in packages
    }
    admissions_by_window = {
        item["window_id"]: item["plan"] for item in admission_plans
    }
    graph_by_window = {
        str(name).rsplit("/", 1)[-1]: graph
        for name, graph in candidate_graphs.items()
    }
    for window_id in sorted(graph_by_window):
        candidate = graph_by_window[window_id]
        term_mapping = _window_term_mapping(
            document, window_id, candidates_by_window[window_id],
            admissions_by_window[window_id], document_merge)
        _copy_evidence(candidate, result, term_mapping)
    return result


def _window_term_mapping(document, window_id, candidates, admission,
                         document_merge):
    mapping = {}
    source_keys = document_merge["source_keys_by_window"][window_id]
    for record in candidates["entities"]:
        local_id = record["id"]
        local_decision = admission["identities"][local_id]
        if local_decision["status"] != "review" and local_decision.get("uri"):
            candidate_term = URIRef(local_decision["uri"])
        else:
            candidate_term = provisional_entity_iri(
                document.document_id, local_id)
        final_decision = document_merge["identity_mapping"][
            source_keys[local_id]]
        final_term = final_decision.get("uri") or source_keys[local_id]
        mapping[candidate_term] = URIRef(final_term)
    return mapping


def _copy_evidence(source, target, term_mapping):
    statements = set(source.subjects(RDF.type, RDF.Statement))
    asserted = set()
    for statement in statements:
        triple = tuple(source.value(statement, predicate) for predicate in (
            RDF.subject, RDF.predicate, RDF.object))
        if None not in triple:
            asserted.add(triple)

    for subject, predicate, object_ in source:
        if (subject, predicate, object_) in asserted:
            continue
        mapped_subject = term_mapping.get(subject, subject)
        mapped_object = term_mapping.get(object_, object_)
        target.add((mapped_subject, predicate, mapped_object))


def build_review_graph(document, document_merge):
    """Represent withheld candidates with standard RDF/PROV in the review graph."""
    graph = Graph()
    document_ = document_uri(document)
    merge_plan = document_merge["merge_plan"]
    candidates = document_merge["candidates"]

    for local_id, decision in sorted(merge_plan["identities"].items()):
        if decision["status"] != "review":
            continue
        record = next(item for item in candidates["entities"]
                      if item["id"] == local_id)
        resource = _review_uri(document.document_id, "entity", local_id)
        graph.add((resource, RDF.type, PROV.Collection))
        graph.add((resource, RDFS.label, Literal(record["name"])))
        graph.add((resource, PROV.wasDerivedFrom, document_))

    for section in ("relations", "facts"):
        for item in merge_plan[section]:
            if item["outcome"] != "review":
                continue
            resource = _review_uri(
                document.document_id, section, str(item["index"]))
            graph.add((resource, RDF.type, PROV.Collection))
            graph.add((resource, PROV.wasDerivedFrom, document_))
            if item.get("triple") is None:
                continue
            statement = URIRef(str(resource) + "/statement")
            graph.add((statement, RDF.type, RDF.Statement))
            graph.add((statement, RDF.subject, item["triple"][0]))
            graph.add((statement, RDF.predicate, item["triple"][1]))
            graph.add((statement, RDF.object, item["triple"][2]))
            graph.add((resource, PROV.hadMember, statement))
    if len(graph):
        link_statement_sources(graph, document)
    return graph


def _review_uri(document_id, section, value):
    digest = hashlib.sha256(
        f"{document_id}|{section}|{value}".encode("utf-8")).hexdigest()
    return URIRef(f"{TRACE}review/{document_id}/{digest[:20]}")


def _publication_counts(merge_plan, evidence, review):
    identities = merge_plan["counts"]["identities"]
    relations = merge_plan["relations"]
    facts = merge_plan["facts"]
    summaries = merge_plan["counts"]["entity_summaries"]
    assertions = merge_plan["counts"]["assertions"]
    return {
        "new_entities": identities["new"],
        "resolved_entities": identities["resolved"],
        "relation_triples": sum(item["outcome"] == "accept"
                                for item in relations),
        "fact_triples": sum(item["outcome"] == "accept" for item in facts),
        "duplicates": assertions["duplicate"] + summaries["duplicate"],
        "review": (assertions["review"] + summaries["review"]
                   + summaries["partial_review"]),
        "audit_triples": len(evidence),
        "review_triples": len(review),
    }


def copy_graph(graph):
    result = Graph()
    for triple in graph:
        result.add(triple)
    return result


def union_graphs(graphs):
    result = Graph()
    for graph in graphs:
        for triple in graph:
            result.add(triple)
    return result
