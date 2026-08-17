"""Name the derived views of one source graph as a single group.

Four fields are graphs of statements the source itself makes: `schema`,
`instance`, and `support` partition it, and `skeleton` is the declared
structural core copied out of the schema view. The fifth field, `patterns`,
holds observation records about how the current instance data happens to use
its properties. Those records are evidence, never declared structure, and this
module keeps the two kinds beside each other without mixing them.

Nothing here reinterprets what the existing modules return, and the source
graph is only ever read.
"""

from graph_partition import partition_graph
from graph_patterns import observed_relationships
from graph_skeleton import create_graph_skeleton


def build_ontology_views(source_graph):
    """Return the current schema, instance, support, skeleton, and patterns."""
    schema, instance, support = partition_graph(source_graph)
    return {
        "schema": schema,
        "instance": instance,
        "support": support,
        "skeleton": create_graph_skeleton(schema),
        "patterns": observed_relationships(schema, instance),
    }
