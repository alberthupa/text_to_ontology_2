"""Baseline: deciding whether a parsed entity already exists in the graph."""

import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from entity_lookup import entity_catalog, identify_entity, identity_key
from graph_management import ENTITY, ONTO


def add_entity(graph, local, name, kind, aliases=(), description=""):
    """Write one catalog-visible entity the way the merge step writes it."""
    uri = ENTITY[local]
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    graph.add((uri, ONTO.kind, Literal(kind)))
    for alias in aliases:
        graph.add((uri, SKOS.altLabel, Literal(alias)))
    if description:
        graph.add((uri, RDFS.comment, Literal(description)))
    return uri


def parsed(name, kind, aliases=(), existing_id=None):
    return {
        "id": "e1", "name": name, "kind": kind,
        "aliases": list(aliases), "existing_id": existing_id,
    }


class IdentityKeyTest(unittest.TestCase):
    def test_case_accents_and_punctuation_are_removed(self):
        self.assertEqual(identity_key("Acme  Corp."), "acmecorp")
        self.assertEqual(identity_key("acme-corp"), identity_key("Acme Corp"))

    def test_letters_without_an_ascii_decomposition_are_dropped(self):
        # Observed current behavior: NFKD splits accents off "a" and "e", but
        # "l" has no decomposition, so it is lost entirely rather than folded.
        self.assertEqual(identity_key("Zazolc Gesla!"), "zazolcgesla")
        self.assertEqual(identity_key("Zażółć Gęślą!"), "zazocgesla")


class CatalogTest(unittest.TestCase):
    """Case 7: catalog names include prefLabel and altLabel."""

    def test_catalog_fields_and_names(self):
        graph = Graph()
        add_entity(
            graph, "acme-corp", "Acme Corp", "Company",
            aliases=["Acme", "ACME Inc"], description="A maker of things.",
        )
        catalog = entity_catalog(graph)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0], {
            "id": str(ENTITY["acme-corp"]),
            "names": ["ACME Inc", "Acme", "Acme Corp"],
            "kind": "Company",
            "description": "A maker of things.",
        })

    def test_only_explicit_onto_entities_are_listed(self):
        graph = Graph()
        add_entity(graph, "listed", "Listed", "Company")
        other = ENTITY["unlisted"]
        graph.add((other, RDF.type, SKOS.Concept))
        graph.add((other, SKOS.prefLabel, Literal("Unlisted")))
        self.assertEqual(
            [item["id"] for item in entity_catalog(graph)],
            [str(ENTITY["listed"])],
        )

    def test_missing_kind_and_description_become_empty_strings(self):
        graph = Graph()
        uri = ENTITY["bare"]
        graph.add((uri, RDF.type, ONTO.Entity))
        graph.add((uri, SKOS.prefLabel, Literal("Bare")))
        self.assertEqual(entity_catalog(graph)[0]["kind"], "")
        self.assertEqual(entity_catalog(graph)[0]["description"], "")

    def test_catalog_is_sorted_by_uri(self):
        graph = Graph()
        add_entity(graph, "zeta", "Zeta", "Company")
        add_entity(graph, "alpha", "Alpha", "Company")
        ids = [item["id"] for item in entity_catalog(graph)]
        self.assertEqual(ids, sorted(ids))


class ExistingIdTest(unittest.TestCase):
    """Case 8: a valid LLM existing_id resolves to the catalog URI."""

    def setUp(self):
        self.graph = Graph()
        self.uri = add_entity(self.graph, "acme-corp", "Acme Corp", "Company")
        self.catalog = entity_catalog(self.graph)

    def test_valid_existing_id_is_accepted(self):
        entity = parsed("Totally Other Name", "Person", existing_id=str(self.uri))
        self.assertEqual(identify_entity(entity, self.catalog), self.uri)

    def test_existing_id_is_accepted_before_local_name_matching(self):
        other = add_entity(self.graph, "beta-corp", "Beta Corp", "Company")
        catalog = entity_catalog(self.graph)
        entity = parsed("Acme Corp", "Company", existing_id=str(other))
        self.assertEqual(identify_entity(entity, catalog), other)

    def test_unknown_existing_id_falls_through_to_local_matching(self):
        entity = parsed("Acme Corp", "Company", existing_id="http://example.org/nope")
        self.assertEqual(identify_entity(entity, self.catalog), self.uri)

    def test_null_existing_id_is_ignored(self):
        entity = parsed("Nothing Alike", "Company", existing_id=None)
        self.assertIsNone(identify_entity(entity, self.catalog))


class ExactNameTest(unittest.TestCase):
    """Cases 9, 10, 11: normalized name and alias matching needs equal kinds."""

    def setUp(self):
        self.graph = Graph()
        self.uri = add_entity(
            self.graph, "acme-corp", "Acme Corp", "Company", aliases=["ACME"]
        )
        self.catalog = entity_catalog(self.graph)

    def test_normalized_preferred_name_with_same_kind_resolves(self):
        self.assertEqual(
            identify_entity(parsed("acme  corp.", "company"), self.catalog), self.uri
        )

    def test_parsed_alias_matching_a_catalog_name_resolves(self):
        entity = parsed("Unknown Name", "Company", aliases=["Acme Corp"])
        self.assertEqual(identify_entity(entity, self.catalog), self.uri)

    def test_parsed_name_matching_a_catalog_alias_resolves(self):
        self.assertEqual(identify_entity(parsed("acme", "Company"), self.catalog), self.uri)

    def test_different_kind_does_not_resolve(self):
        self.assertIsNone(identify_entity(parsed("Acme Corp", "Person"), self.catalog))

    def test_missing_parsed_kind_does_not_resolve(self):
        self.assertIsNone(identify_entity(parsed("Acme Corp", ""), self.catalog))

    def test_missing_catalog_kind_does_not_resolve(self):
        graph = Graph()
        uri = ENTITY["bare"]
        graph.add((uri, RDF.type, ONTO.Entity))
        graph.add((uri, SKOS.prefLabel, Literal("Acme Corp")))
        self.assertIsNone(
            identify_entity(parsed("Acme Corp", "Company"), entity_catalog(graph))
        )

    def test_two_exact_matches_do_not_resolve(self):
        add_entity(self.graph, "acme-corp-2", "Acme Corp", "Company")
        catalog = entity_catalog(self.graph)
        self.assertIsNone(identify_entity(parsed("Acme Corp", "Company"), catalog))


class CloseSpellingTest(unittest.TestCase):
    """Cases 12, 13: the 0.96 rule and its ambiguity guard."""

    def test_unique_close_spelling_of_the_same_kind_resolves(self):
        graph = Graph()
        uri = add_entity(
            graph, "io", "International Organization", "Organization"
        )
        entity = parsed("International Organizations", "Organization")
        self.assertEqual(identify_entity(entity, entity_catalog(graph)), uri)

    def test_close_spelling_of_a_different_kind_does_not_resolve(self):
        graph = Graph()
        add_entity(graph, "io", "International Organization", "Person")
        entity = parsed("International Organizations", "Organization")
        self.assertIsNone(identify_entity(entity, entity_catalog(graph)))

    def test_below_threshold_does_not_resolve(self):
        graph = Graph()
        add_entity(graph, "acme", "Acme Corporation", "Company")
        self.assertIsNone(
            identify_entity(parsed("Acme Company", "Company"), entity_catalog(graph))
        )

    def test_tied_close_candidates_do_not_resolve(self):
        graph = Graph()
        add_entity(graph, "one", "International Organization", "Organization")
        add_entity(graph, "two", "International Organization", "Organization")
        entity = parsed("International Organizations", "Organization")
        self.assertIsNone(identify_entity(entity, entity_catalog(graph)))

    def test_a_strictly_better_close_candidate_resolves(self):
        graph = Graph()
        best = add_entity(
            graph, "one", "International Organizations", "Organization"
        )
        add_entity(graph, "two", "International Organization", "Organization")
        entity = parsed("International Organizations", "Organization")
        self.assertEqual(identify_entity(entity, entity_catalog(graph)), best)

    def test_close_matching_only_uses_the_parsed_preferred_name(self):
        graph = Graph()
        add_entity(graph, "io", "International Organization", "Organization")
        entity = parsed(
            "Nothing Alike", "Organization", aliases=["International Organizations"]
        )
        self.assertIsNone(identify_entity(entity, entity_catalog(graph)))


class EmptyCatalogTest(unittest.TestCase):
    def test_nothing_resolves_against_an_empty_catalog(self):
        self.assertIsNone(identify_entity(parsed("Acme Corp", "Company"), []))


class ReturnTypeTest(unittest.TestCase):
    def test_a_match_is_returned_as_a_uriref(self):
        graph = Graph()
        add_entity(graph, "acme-corp", "Acme Corp", "Company")
        found = identify_entity(parsed("Acme Corp", "Company"), entity_catalog(graph))
        self.assertIsInstance(found, URIRef)


if __name__ == "__main__":
    unittest.main()
