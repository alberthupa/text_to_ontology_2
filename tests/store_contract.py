"""Backend-independent behavior every GraphStore adapter must pass.

Each concrete test class supplies `make_store()` and inherits everything here,
so a future remote adapter proves itself with the same cases.
"""

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDFS

from text_to_ontology.graph_store import Publication, ReadOnlyGraphStore


class Terms:
    """A tiny stable vocabulary shared by every contract case."""

    base = "http://example.com/store-contract/"
    alice = URIRef(base + "alice")
    bob = URIRef(base + "bob")
    carol = URIRef(base + "carol")
    knows = URIRef(base + "knows")
    named = URIRef(base + "graphs/one")
    other = URIRef(base + "graphs/two")
    doomed = URIRef(base + "graphs/doomed")


def pair_graph(subject, object_):
    graph = Graph()
    graph.add((subject, Terms.knows, object_))
    graph.add((subject, RDFS.label, Literal("a name")))
    return graph


class StoreContract:
    """The observable contract, independent of how the store stores."""

    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()

    def test_a_fresh_store_is_empty(self):
        self.assertEqual(len(self.store.get(Terms.named)), 0)
        self.assertEqual(self.store.graph_names(), [])

    def test_put_then_get_round_trips_isomorphically(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.assertTrue(isomorphic(
            self.store.get(Terms.named), pair_graph(Terms.alice, Terms.bob)))

    def test_get_returns_an_isolated_copy(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        borrowed = self.store.get(Terms.named)
        borrowed.add((Terms.carol, Terms.knows, Terms.alice))
        self.assertEqual(len(self.store.get(Terms.named)), 2)

    def test_put_replaces_previous_content_whole(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.put(Terms.named, pair_graph(Terms.bob, Terms.carol))
        self.assertTrue(isomorphic(
            self.store.get(Terms.named), pair_graph(Terms.bob, Terms.carol)))

    def test_delete_removes_the_graph(self):
        self.store.put(Terms.doomed, pair_graph(Terms.alice, Terms.bob))
        self.store.delete(Terms.doomed)
        self.assertEqual(len(self.store.get(Terms.doomed)), 0)
        self.assertNotIn(Terms.doomed, self.store.graph_names())

    def test_graph_names_lists_exactly_the_stored_graphs(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.put(Terms.other, pair_graph(Terms.bob, Terms.carol))
        self.assertEqual(self.store.graph_names(),
                         sorted([Terms.named, Terms.other]))

    def test_query_sees_across_all_named_graphs(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        self.store.put(Terms.other, pair_graph(Terms.bob, Terms.carol))
        rows = list(self.store.query(
            f"SELECT ?s ?o WHERE {{ ?s <{Terms.knows}> ?o }}"))
        pairs = {(str(row.s), str(row.o)) for row in rows}
        self.assertEqual(pairs, {
            (str(Terms.alice), str(Terms.bob)),
            (str(Terms.bob), str(Terms.carol)),
        })

    def test_query_accepts_bound_values(self):
        self.store.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        rows = list(self.store.query(
            "SELECT ?o WHERE { ?s ?p ?o }", p=Terms.knows))
        self.assertEqual({str(row.o) for row in rows}, {str(Terms.bob)})

    def test_update_writes_into_one_named_graph(self):
        self.store.update(
            f"INSERT DATA {{ GRAPH <{Terms.named}> {{ "
            f"<{Terms.alice}> <{Terms.knows}> <{Terms.bob}> }} }}")
        expected = Graph()
        expected.add((Terms.alice, Terms.knows, Terms.bob))
        self.assertTrue(isomorphic(self.store.get(Terms.named), expected))

    def test_publish_applies_every_change_as_one_step(self):
        self.store.put(Terms.doomed, pair_graph(Terms.alice, Terms.bob))
        self.store.publish(Publication(
            graphs={Terms.named: pair_graph(Terms.bob, Terms.carol)},
            deletions=(Terms.doomed,),
        ))
        self.assertEqual(len(self.store.get(Terms.doomed)), 0)
        self.assertNotIn(Terms.doomed, self.store.graph_names())
        self.assertTrue(isomorphic(
            self.store.get(Terms.named), pair_graph(Terms.bob, Terms.carol)))

    def test_publish_without_changes_still_succeeds(self):
        self.assertIsNone(self.store.publish())


class ReadOnlyRules:
    """AC8: the read-only wrapper hides every way of changing anything."""

    def test_read_only_wrapper_offers_no_write_path(self):
        wrapper = ReadOnlyGraphStore(self.make_store())
        for forbidden in ("put", "delete", "update", "publish"):
            self.assertFalse(hasattr(wrapper, forbidden), forbidden)

    def test_read_only_wrapper_still_reads(self):
        inner = self.make_store()
        inner.put(Terms.named, pair_graph(Terms.alice, Terms.bob))
        wrapper = ReadOnlyGraphStore(inner)
        self.assertEqual(len(wrapper.get(Terms.named)), 2)
        rows = list(wrapper.query("SELECT ?s WHERE { ?s ?p ?o }"))
        self.assertEqual({str(row.s) for row in rows}, {str(Terms.alice)})
