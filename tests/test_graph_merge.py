"""Baseline: merging parsed knowledge into the canonical graph."""

import unittest

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
from graph_merge import label, merge_into_graph, new_entity_uri, slug


def new_graph():
    return Graph()


class SlugTest(unittest.TestCase):
    def test_names_become_uri_safe_identifiers(self):
        self.assertEqual(slug("Acme Corp."), "acme-corp")
        self.assertEqual(slug("!!!"), "unnamed")

    def test_letters_without_an_ascii_decomposition_are_dropped(self):
        # Observed current behavior, matching identity_key(): "l" has no NFKD
        # decomposition and disappears instead of folding to "l".
        self.assertEqual(slug("Zażółć Gęślą"), "zazoc-gesla")


class LabelTest(unittest.TestCase):
    def test_code_like_names_become_readable(self):
        self.assertEqual(label("worksFor"), "works For")
        self.assertEqual(label("birth_date"), "birth date")
        self.assertEqual(label("supply-chain"), "supply chain")


class NewEntityUriTest(unittest.TestCase):
    def test_a_used_subject_uri_gets_a_numeric_suffix(self):
        graph = new_graph()
        self.assertEqual(new_entity_uri(graph, "Acme Corp"), ENTITY["acme-corp"])
        graph.add((ENTITY["acme-corp"], RDF.type, ONTO.Entity))
        self.assertEqual(new_entity_uri(graph, "Acme Corp"), ENTITY["acme-corp-2"])
        graph.add((ENTITY["acme-corp-2"], RDF.type, ONTO.Entity))
        self.assertEqual(new_entity_uri(graph, "Acme Corp"), ENTITY["acme-corp-3"])


class NewEntityTest(unittest.TestCase):
    """Case 14: an unmatched candidate becomes a fully typed new entity."""

    def setUp(self):
        self.graph = new_graph()
        self.counts = merge_into_graph(self.graph, {"entities": [{
            "id": "e1", "name": "Acme Corp", "kind": "Company",
            "description": "A maker of things.", "aliases": ["ACME"],
            "existing_id": None,
        }]})
        self.uri = ENTITY["acme-corp"]

    def test_counts_report_one_new_entity(self):
        self.assertEqual(self.counts, (1, 0, 0, 0))

    def test_all_current_types_are_added(self):
        types = set(self.graph.objects(self.uri, RDF.type))
        self.assertEqual(types, {
            ONTO.Entity, OWL.NamedIndividual, SKOS.Concept, CLASS["company"],
        })

    def test_labels_description_and_kind_are_added(self):
        self.assertEqual(
            self.graph.value(self.uri, SKOS.prefLabel), Literal("Acme Corp")
        )
        self.assertEqual(
            self.graph.value(self.uri, RDFS.label), Literal("Acme Corp")
        )
        self.assertEqual(self.graph.value(self.uri, ONTO.kind), Literal("Company"))
        self.assertEqual(
            set(self.graph.objects(self.uri, SKOS.altLabel)), {Literal("ACME")}
        )
        self.assertEqual(
            self.graph.value(self.uri, RDFS.comment),
            Literal("A maker of things."),
        )

    def test_the_domain_class_is_declared(self):
        kind_uri = CLASS["company"]
        self.assertIn((kind_uri, RDF.type, OWL.Class), self.graph)
        self.assertIn((kind_uri, RDFS.subClassOf, ONTO.Entity), self.graph)
        self.assertIn((kind_uri, RDFS.label, Literal("Company")), self.graph)

    def test_a_missing_kind_becomes_entity(self):
        graph = new_graph()
        merge_into_graph(graph, {"entities": [
            {"id": "e1", "name": "Nameless Thing", "kind": ""},
        ]})
        uri = ENTITY["nameless-thing"]
        self.assertEqual(graph.value(uri, ONTO.kind), Literal("Entity"))
        self.assertIn((uri, RDF.type, CLASS["entity"]), graph)


class EnrichExistingTest(unittest.TestCase):
    """Cases 15, 16, 17: adding to an entity that already exists."""

    def setUp(self):
        self.graph = new_graph()
        merge_into_graph(self.graph, {"entities": [{
            "id": "e1", "name": "Acme Corp", "kind": "Company",
            "description": "The first description.",
        }]})
        self.uri = ENTITY["acme-corp"]

    def test_resolved_entity_gains_aliases_relations_and_facts(self):
        counts = merge_into_graph(self.graph, {
            "entities": [
                {"id": "a", "name": "Acme Corp", "kind": "Company",
                 "aliases": ["ACME", "Acme Incorporated"]},
                {"id": "b", "name": "Ada Lovelace", "kind": "Person"},
            ],
            "relations": [{"subject": "b", "predicate": "works for", "object": "a"}],
            "facts": [{"subject": "b", "predicate": "birth date",
                       "value": "1815-12-10"}],
        })
        self.assertEqual(counts, (1, 1, 1, 1))
        self.assertEqual(
            set(self.graph.objects(self.uri, SKOS.altLabel)),
            {Literal("ACME"), Literal("Acme Incorporated")},
        )
        person = ENTITY["ada-lovelace"]
        self.assertIn((person, RELATION["works-for"], self.uri), self.graph)
        self.assertIn(
            (person, FACT["birth-date"], Literal("1815-12-10")), self.graph
        )

    def test_property_declarations_and_labels_are_added(self):
        merge_into_graph(self.graph, {
            "entities": [{"id": "b", "name": "Ada Lovelace", "kind": "Person"}],
            "relations": [{"subject": "b", "predicate": "worksFor",
                           "object": "b"}],
            "facts": [{"subject": "b", "predicate": "birth_date",
                       "value": "1815-12-10"}],
        })
        self.assertIn(
            (RELATION["worksfor"], RDF.type, OWL.ObjectProperty), self.graph
        )
        self.assertIn(
            (RELATION["worksfor"], RDFS.label, Literal("works For")), self.graph
        )
        self.assertIn(
            (FACT["birth-date"], RDF.type, OWL.DatatypeProperty), self.graph
        )
        self.assertIn(
            (FACT["birth-date"], RDFS.label, Literal("birth date")), self.graph
        )

    def test_a_missing_description_is_filled_in(self):
        graph = new_graph()
        merge_into_graph(graph, {"entities": [
            {"id": "e1", "name": "Beta Corp", "kind": "Company"},
        ]})
        merge_into_graph(graph, {"entities": [
            {"id": "e1", "name": "Beta Corp", "kind": "Company",
             "description": "Added later."},
        ]})
        self.assertEqual(
            graph.value(ENTITY["beta-corp"], RDFS.comment),
            Literal("Added later."),
        )

    def test_an_existing_description_is_not_overwritten(self):
        merge_into_graph(self.graph, {"entities": [
            {"id": "e1", "name": "Acme Corp", "kind": "Company",
             "description": "A competing description."},
        ]})
        self.assertEqual(
            set(self.graph.objects(self.uri, RDFS.comment)),
            {Literal("The first description.")},
        )

    def test_a_later_different_preferred_name_becomes_an_alternate_label(self):
        merge_into_graph(self.graph, {"entities": [
            {"id": "e1", "name": "ACME", "kind": "Company",
             "existing_id": str(self.uri)},
        ]})
        self.assertEqual(
            self.graph.value(self.uri, SKOS.prefLabel), Literal("Acme Corp")
        )
        self.assertEqual(
            set(self.graph.objects(self.uri, SKOS.altLabel)), {Literal("ACME")}
        )
        self.assertEqual(
            set(self.graph.objects(self.uri, RDFS.label)), {Literal("Acme Corp")}
        )


class SkipTest(unittest.TestCase):
    """Case 18: invalid records and endpoints are skipped."""

    def test_entities_without_an_id_or_name_are_skipped(self):
        graph = new_graph()
        counts = merge_into_graph(graph, {"entities": [
            {"id": "", "name": "No Local Id", "kind": "Company"},
            {"id": "e2", "name": "", "kind": "Company"},
            {"id": "e3", "kind": "Company"},
            {"name": "No Id Key", "kind": "Company"},
        ]})
        self.assertEqual(counts, (0, 0, 0, 0))
        self.assertEqual(len(graph), 0)

    def test_relations_and_facts_with_unknown_endpoints_are_skipped(self):
        graph = new_graph()
        counts = merge_into_graph(graph, {
            "entities": [{"id": "e1", "name": "Acme Corp", "kind": "Company"}],
            "relations": [
                {"subject": "e1", "predicate": "works for", "object": "ghost"},
                {"subject": "ghost", "predicate": "works for", "object": "e1"},
                {"subject": "e1", "predicate": "", "object": "e1"},
            ],
            "facts": [
                {"subject": "ghost", "predicate": "birth date", "value": "x"},
                {"subject": "e1", "predicate": "birth date", "value": None},
                {"subject": "e1", "predicate": "", "value": "x"},
            ],
        })
        self.assertEqual(counts, (1, 0, 0, 0))
        self.assertEqual(list(graph.subjects(RDF.type, OWL.ObjectProperty)), [])
        self.assertEqual(list(graph.subjects(RDF.type, OWL.DatatypeProperty)), [])

    def test_a_self_relation_between_valid_endpoints_is_kept(self):
        graph = new_graph()
        counts = merge_into_graph(graph, {
            "entities": [{"id": "e1", "name": "Acme Corp", "kind": "Company"}],
            "relations": [{"subject": "e1", "predicate": "owns", "object": "e1"}],
        })
        self.assertEqual(counts, (1, 0, 1, 0))


class DuplicateTest(unittest.TestCase):
    """Case 19: repeated relations and facts are not counted twice."""

    def test_second_identical_merge_adds_no_new_relations_or_facts(self):
        graph = new_graph()
        data = {
            "entities": [
                {"id": "e1", "name": "Ada Lovelace", "kind": "Person"},
                {"id": "e2", "name": "Acme Corp", "kind": "Company"},
            ],
            "relations": [
                {"subject": "e1", "predicate": "works for", "object": "e2"}
            ],
            "facts": [
                {"subject": "e1", "predicate": "birth date", "value": "1815-12-10"}
            ],
        }
        first = merge_into_graph(graph, data)
        size = len(graph)
        second = merge_into_graph(graph, data)

        self.assertEqual(first, (2, 0, 1, 1))
        self.assertEqual(second, (0, 2, 0, 0))
        self.assertEqual(len(graph), size)


class SequentialVisibilityTest(unittest.TestCase):
    """Case 20: a later entity can resolve to one added earlier in the same response."""

    def test_the_second_candidate_resolves_to_the_first(self):
        graph = new_graph()
        counts = merge_into_graph(graph, {"entities": [
            {"id": "e1", "name": "Helio Grid", "kind": "Company"},
            {"id": "e2", "name": "helio grid", "kind": "company",
             "aliases": ["Helio"]},
        ]})
        self.assertEqual(counts, (1, 1, 0, 0))
        self.assertEqual(
            list(graph.subjects(RDF.type, ONTO.Entity)), [ENTITY["helio-grid"]]
        )
        # The resolved candidate's differing preferred name also becomes an alias.
        self.assertEqual(
            set(graph.objects(ENTITY["helio-grid"], SKOS.altLabel)),
            {Literal("Helio"), Literal("helio grid")},
        )

    def test_both_local_ids_point_at_the_shared_entity(self):
        graph = new_graph()
        counts = merge_into_graph(graph, {
            "entities": [
                {"id": "e1", "name": "Helio Grid", "kind": "Company"},
                {"id": "e2", "name": "helio grid", "kind": "company"},
                {"id": "e3", "name": "Ada Lovelace", "kind": "Person"},
            ],
            "relations": [
                {"subject": "e3", "predicate": "works for", "object": "e2"}
            ],
        })
        self.assertEqual(counts, (2, 1, 1, 0))
        self.assertIn(
            (ENTITY["ada-lovelace"], RELATION["works-for"], ENTITY["helio-grid"]),
            graph,
        )


class CountOrderTest(unittest.TestCase):
    """Case 22: the four counts keep their meaning and order."""

    def test_counts_are_new_resolved_relations_facts(self):
        graph = new_graph()
        merge_into_graph(graph, {"entities": [
            {"id": "e1", "name": "Acme Corp", "kind": "Company"},
        ]})
        counts = merge_into_graph(graph, {
            "entities": [
                {"id": "e1", "name": "Acme Corp", "kind": "Company"},
                {"id": "e2", "name": "Ada Lovelace", "kind": "Person"},
                {"id": "e3", "name": "Grace Hopper", "kind": "Person"},
            ],
            "relations": [
                {"subject": "e2", "predicate": "works for", "object": "e1"},
                {"subject": "e3", "predicate": "works for", "object": "e1"},
            ],
            "facts": [
                {"subject": "e2", "predicate": "birth date", "value": "1815-12-10"},
            ],
        })
        self.assertEqual(counts, (2, 1, 2, 1))


if __name__ == "__main__":
    unittest.main()
