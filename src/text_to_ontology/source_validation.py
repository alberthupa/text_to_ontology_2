"""Validate one complete source graph with configured SHACL shapes."""

from dataclasses import dataclass

from rdflib import BNode, Graph
from rdflib.namespace import RDF, SH


@dataclass
class SourceValidationResult:
    """The standard SHACL result plus a small plain summary."""

    conforms: bool
    report_graph: Graph
    report_text: str
    shape_graphs_checked: int


class SourceValidationError(RuntimeError):
    """A non-conformant source graph, kept inspectable by the caller."""

    def __init__(self, result, source_artifact, reconciliation_report,
                 sidecar_path=None):
        super().__init__("complete source graph does not conform to SHACL shapes")
        self.validation = result
        self.source_artifact = source_artifact
        self.reconciliation_report = reconciliation_report
        self.sidecar_path = sidecar_path


def embedded_shape_graph(graph):
    """Copy SHACL shapes embedded in a legacy combined graph.

    Shape-owned blank nodes are followed recursively. Domain resources named
    by targets and paths are referenced, not copied as source data.
    """
    result = Graph()
    pending = list(graph.subjects(RDF.type, SH.NodeShape))
    pending += list(graph.subjects(RDF.type, SH.PropertyShape))
    seen = set()
    while pending:
        subject = pending.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for triple in graph.triples((subject, None, None)):
            result.add(triple)
            if isinstance(triple[2], BNode):
                pending.append(triple[2])
    return result


def combine_shape_graphs(shape_graphs):
    """Combine every configured shape graph into one isolated graph."""
    combined = Graph()
    count = 0
    for shape_graph in shape_graphs:
        count += 1
        blank_nodes = {
            term for triple in shape_graph for term in triple
            if isinstance(term, BNode)
        }
        replacements = {
            node: BNode(f"shape-{count}-{number}")
            for number, node in enumerate(sorted(blank_nodes, key=str))
        }
        for triple in shape_graph:
            combined.add(tuple(replacements.get(term, term) for term in triple))
    return combined, count


def validate_source_graph(source_graph, shape_graphs):
    """Run pySHACL over a copy of the source graph and all supplied shapes."""
    from pyshacl import validate

    data = Graph()
    for triple in source_graph:
        data.add(triple)
    shapes, count = combine_shape_graphs(shape_graphs)
    conforms, report_graph, report_text = validate(
        data_graph=data,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        # A warning (an expected link that is missing) is reported, never
        # blocking; only violations make a graph non-conformant.
        allow_warnings=True,
        meta_shacl=False,
        advanced=False,
    )
    return SourceValidationResult(
        conforms=bool(conforms),
        report_graph=report_graph,
        report_text=str(report_text),
        shape_graphs_checked=count,
    )
