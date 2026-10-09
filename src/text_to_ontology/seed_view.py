"""The seed view: only what the seed ontology covers.

A dataset holds much more than the business knowledge: provenance (which
document supports which statement), review material, SHACL shapes, and
bookkeeping types on every entity. All of it is useful for audit, none of it
is needed to *read* the ontology. The seed view is the part that is:

    kept                                       dropped
    the schema graph(s), whole                 provenance and review graphs
    statements whose predicate is declared     shapes
    rdf:type to a declared class               owl:NamedIndividual, skos:Concept
    names and descriptions of entities         statements with undeclared predicates
    onto:kind (entity identity needs it)

"Declared" means declared in the schema or data graphs, so the view also works
for datasets built without the data-only lock.

One view, used everywhere a reader needs the business ontology: the context of
every extraction prompt, the graph chat, and the studio's "Seed ontology"
view. Nothing here writes to a graph.
"""

from rdflib import Graph
from rdflib.namespace import RDF, RDFS, SKOS

from .graph_management import ONTO, bind
from .vocabulary import read_vocabulary

# Names, descriptions, and the kind an entity was given: what a reader and the
# identity matcher need to know which thing a statement is about.
NAMING = {SKOS.prefLabel, SKOS.altLabel, SKOS.definition, RDFS.label,
          RDFS.comment, ONTO.kind}


def _union(graphs):
    result = Graph()
    bind(result)
    for graph in graphs:
        for triple in graph:
            result.add(triple)
    return result


def keep_in_seed(triple, declared_terms, declared_classes,
                 declared_properties):
    """Whether one data statement belongs to the seed view."""
    subject, predicate, object_ = triple
    if str(subject) in declared_terms:
        return True  # a declaration made in a data graph (legacy runs)
    if predicate == RDF.type:
        return str(object_) in declared_classes
    return predicate in NAMING or str(predicate) in declared_properties


def seed_graphs(roles, names):
    """The seed view, still split by named graph: {graph name: Graph}.

    `roles` maps graph names to graphs, as the pipeline and the store hold
    them. Schema graphs are kept whole; every data graph is filtered.
    """
    schema_names = [name for name in names.schema_graphs if name in roles]
    data_names = [name for name in [*names.data_graphs, names.target_graph]
                  if name in roles]
    vocabulary = read_vocabulary(
        _union(roles[name] for name in schema_names + data_names))
    declared_classes = set(vocabulary.classes)
    declared_properties = set(vocabulary.relations) | set(vocabulary.facts)
    declared_terms = declared_classes | declared_properties
    view = {name: roles[name] for name in schema_names}
    for name in data_names:
        kept = Graph()
        for triple in roles[name]:
            if keep_in_seed(triple, declared_terms, declared_classes,
                            declared_properties):
                kept.add(triple)
        view[name] = kept
    return view


def seed_view(roles, names):
    """The seed view as one graph, with the project prefixes bound."""
    return _union(seed_graphs(roles, names).values())


def store_roles(store, names):
    """Every role graph of a named-graph store, as {graph name: Graph}."""
    return {name: store.get(name)
            for name in [*names.schema_graphs, *names.shape_graphs,
                         *names.data_graphs, names.target_graph,
                         names.provenance_graph, names.review_graph]}
