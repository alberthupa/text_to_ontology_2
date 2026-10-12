"""Split one source graph into current schema, instance, and support views.

The source graph is only ever read. Every source triple lands in exactly one of
the three derived graphs, so nothing is silently dropped and nothing is copied
twice. A statement that cannot be classified confidently goes to the
support/remainder view rather than being guessed into schema or instance.
"""

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS


# Declaring a resource with one of these types makes it a schema resource.
SCHEMA_TYPES = {
    OWL.Class, RDFS.Class, RDFS.Datatype, RDF.Property, OWL.ObjectProperty,
    OWL.DatatypeProperty, OWL.AnnotationProperty,
}

# Run tracing (trace:) and source links (src:) are support metadata. The
# namespaces are restated here because this module deliberately depends on
# rdflib only; graph_management.TRACE and SRC are the same strings.
TRACE_NAMESPACE = "http://example.org/text-ontology/trace/"
SOURCE_NAMESPACE = "http://example.org/text-ontology/source/"

# Merge-audit roots (Proposal 07): extraction events and merge candidates.
AUDIT_TYPES = {
    URIRef(TRACE_NAMESPACE + "ExtractionEvent"),
    URIRef(TRACE_NAMESPACE + "MergeCandidate"),
}

# Declaring a resource with one of these types makes it supporting material.
SUPPORT_TYPES = {OWL.Ontology, SH.NodeShape, SH.PropertyShape}

# Statements that relate two schema resources to each other.
SCHEMA_AXIOMS = {
    RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
    OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith,
    OWL.inverseOf,
}

# Naming statements, which take the role of whatever they describe.
ANNOTATIONS = {
    RDFS.label, RDFS.comment, SKOS.prefLabel, SKOS.altLabel, SKOS.definition,
}

# Restriction parts whose object is itself a schema resource.
RESTRICTION_TARGETS = {
    OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass,
    OWL.onDataRange,
}


def owned_nodes(graph, root):
    """`root` plus every blank node reachable from it through objects."""
    owned, pending = {root}, [root]
    while pending:
        for _, _, target in graph.triples((pending.pop(), None, None)):
            if isinstance(target, BNode) and target not in owned:
                owned.add(target)
                pending.append(target)
    return owned


def support_roles(graph):
    """Ontology metadata, SHACL shapes, merge audit records, and what they own."""
    nodes = set()
    for type_ in SUPPORT_TYPES | AUDIT_TYPES:
        for root in graph.subjects(RDF.type, type_):
            nodes |= owned_nodes(graph, root)
    return nodes


def restriction_roles(graph):
    """Blank nodes recognizable as OWL restrictions, with what they own."""
    nodes = set()
    for node in graph.subjects(RDF.type, OWL.Restriction):
        if (node, OWL.onProperty, None) in graph:
            nodes |= owned_nodes(graph, node)
    return nodes


def schema_roles(graph, restrictions):
    """Resources declared as, or named by, explicit schema structure."""
    nodes = set()
    for type_ in SCHEMA_TYPES:
        nodes |= set(graph.subjects(RDF.type, type_))
    for axiom in SCHEMA_AXIOMS:
        for subject, _, target in graph.triples((None, axiom, None)):
            nodes |= {subject, target}
    for node in restrictions:
        for _, part, target in graph.triples((node, None, None)):
            if part in RESTRICTION_TARGETS:
                nodes.add(target)
    return {node for node in nodes if not isinstance(node, (BNode, Literal))}


def instance_roles(graph, schema):
    """Resources given an individual's type: a metatype or a known class."""
    nodes = set()
    for subject, _, type_ in graph.triples((None, RDF.type, None)):
        if type_ in SCHEMA_TYPES or type_ in SUPPORT_TYPES:
            continue
        if type_ in (OWL.NamedIndividual, SKOS.Concept) or type_ in schema:
            nodes.add(subject)
    return nodes


def partition_graph(source_graph):
    """Return the current schema, instance, and support/remainder views."""
    support_nodes = support_roles(source_graph)
    restrictions = restriction_roles(source_graph)
    schema_nodes = schema_roles(source_graph, restrictions)
    instance_nodes = instance_roles(source_graph, schema_nodes)

    # Blank nodes belonging to no recognized structure. A statement touching
    # one is kept whole in the remainder; half an expression misleads.
    opaque = {
        node for node in source_graph.all_nodes()
        if isinstance(node, BNode) and node not in support_nodes
        and node not in restrictions
    }

    schema_graph, instance_graph, support_graph = (Graph(), Graph(), Graph())
    for prefix, namespace in source_graph.namespaces():
        for view in (schema_graph, instance_graph, support_graph):
            view.bind(prefix, namespace)

    for triple in source_graph:
        view = choose_view(
            triple, support_nodes, restrictions, schema_nodes, instance_nodes,
            opaque,
        )
        {"schema": schema_graph, "instance": instance_graph}.get(
            view, support_graph).add(triple)
    return schema_graph, instance_graph, support_graph


def choose_view(triple, support_nodes, restrictions, schema_nodes,
                instance_nodes, opaque):
    """Name the view one triple belongs to, in decreasing order of certainty."""
    subject, predicate, target = triple

    # Source links and tracing predicates. A trace: *subject* is not enough:
    # a staging graph's provisional entities (trace:provisional/...) are
    # still the instances a later window must see.
    if str(predicate).startswith((TRACE_NAMESPACE, SOURCE_NAMESPACE)) \
            or str(subject).startswith(SOURCE_NAMESPACE):
        return "support"
    if subject in support_nodes or target in support_nodes:
        return "support"
    if subject in opaque or target in opaque:
        return "support"
    if predicate == RDF.type:
        if target in SCHEMA_TYPES or target == OWL.Restriction:
            return "schema"
        return "instance" if subject in instance_nodes else "support"
    if subject in restrictions:
        return "schema"
    if predicate in SCHEMA_AXIOMS:
        return "schema" if subject in schema_nodes else "support"
    if predicate in ANNOTATIONS:
        # A resource may be both. Naming statements follow its schema role.
        if subject in schema_nodes:
            return "schema"
        return "instance" if subject in instance_nodes else "support"
    return "instance" if subject in instance_nodes else "support"
