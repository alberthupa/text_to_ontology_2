"""Baseline: merging parsed knowledge into the canonical graph."""

import unittest

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, TRACE
from text_to_ontology.graph_merge import (
    apply_merge_plan, label, merge_into_graph, new_entity_uri, slug,
)
from text_to_ontology.graph_management import bind, open_graph, save_graph


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
        self.assertEqual(label("widget-part"), "widget part")


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
        self.assertIn((uri, RDF.type, ONTO.Entity), graph)
        self.assertFalse(any(CLASS["entity"] in triple for triple in graph))
        self.assertNotIn((ONTO.Entity, RDFS.subClassOf, ONTO.Entity), graph)


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


# ---------------------------------------------------------------- Proposal 07D

import tempfile
from pathlib import Path

from text_to_ontology import merge_policy
from text_to_ontology.graph_management import ONTO as _ONTO
from text_to_ontology.merge_policy import build_provenance, plan_graph_merge


def plan_apply(graph, entities=(), relations=(), facts=()):
    provenance = {"source_path": "s.md", "source_sha256": "0" * 64,
                  "model": "m", "policy_version": 1}
    plan = plan_graph_merge(
        graph, {"entities": list(entities), "relations": list(relations),
                "facts": list(facts)}, provenance)
    return apply_merge_plan(graph, plan)


def plan_entity(identifier, name, kind="Company", confidence=0.9, **extra):
    record = {"id": identifier, "name": name, "kind": kind,
              "description": "", "aliases": [], "existing_id": None,
              "confidence": confidence}
    record.update(extra)
    return record


class MaterializerTest(unittest.TestCase):
    """7D.2 to 7D.10: only decided triples reach the copied graph."""

    def test_only_accept_domain_triples_are_asserted(self):
        source = Graph()
        source.add((ENTITY["ghost"], RDF.type, OWL.Thing))
        updated, result = plan_apply(
            source,
            [plan_entity("e1", "Nova Corp"),
             plan_entity("e2", "Shaky Thing", confidence=0.5)],
            [], [])
        self.assertIn((ENTITY["nova-corp"], RDF.type, ONTO.Entity),
                      set(updated))
        self.assertNotIn((ENTITY["shaky-thing"], RDF.type, ONTO.Entity),
                         set(updated))
        self.assertEqual(result["new_entities"], 1)

    def test_duplicate_domain_triples_are_not_re_added_but_audit_is(self):
        source = Graph()
        source.add((ENTITY["acme-corp"], RDF.type, ONTO.Entity))
        source.add((ENTITY["acme-corp"], SKOS.prefLabel, Literal("Acme Corp")))
        source.add((ENTITY["acme-corp"], ONTO.kind, Literal("Company")))
        updated, result = plan_apply(
            source,
            [plan_entity("e1", "Acme Corp",
                         existing_id=str(ENTITY["acme-corp"]))],
            [], [])
        self.assertEqual(len(updated), len(source) + result["audit_triples"])
        self.assertEqual(result["duplicates"], 1)

    def test_review_records_persist_without_their_proposed_triples(self):
        source = Graph()
        updated, result = plan_apply(
            source,
            [plan_entity("e1", "Shaky Thing", confidence=0.5)], [], [])
        self.assertGreater(result["audit_triples"], 0)
        self.assertNotIn((ENTITY["shaky-thing"], RDF.type, ONTO.Entity),
                         set(updated))
        self.assertEqual(result["review"], 1)
        # The proposal survives as audit metadata under merge-proposed-entity.
        proposals = [o for o in updated.objects(None, TRACE.proposedEntity)]
        self.assertTrue(any("merge-proposed-entity" in str(o)
                            for o in proposals))
        self.assertNotIn((ENTITY["shaky-thing"], RDF.type, ONTO.Entity),
                         set(updated))

    def test_new_entity_boilerplate_matches_the_current_representation(self):
        updated, _ = plan_apply(Graph(),
                                [plan_entity("e1", "Nova Corp",
                                             kind="Widget")], [], [])
        self.assertIn((CLASS["widget"], RDF.type, OWL.Class), set(updated))
        self.assertIn((CLASS["widget"], RDFS.subClassOf, ONTO.Entity),
                      set(updated))
        self.assertIn((ENTITY["nova-corp"], RDF.type, OWL.NamedIndividual),
                      set(updated))
        self.assertIn((ENTITY["nova-corp"], RDF.type, SKOS.Concept),
                      set(updated))

    def test_property_declaration_and_labeling(self):
        updated, _ = plan_apply(
            Graph(),
            [plan_entity("e1", "Nova Corp"), plan_entity("e2", "Umbra")],
            [{"subject": "e1", "predicate": "buys", "object": "e2",
              "confidence": 0.9}], [])
        self.assertIn((RELATION["buys"], RDF.type, OWL.ObjectProperty),
                      set(updated))
        self.assertIn((RELATION["buys"], RDFS.label, Literal("buys")),
                      set(updated))

    def test_existing_property_labels_are_not_multiplied(self):
        source = Graph()
        source.add((RELATION["buys"], RDF.type, OWL.ObjectProperty))
        source.add((RELATION["buys"], RDFS.label, Literal("buys")))
        for local, name in (("acme-corp", "Acme Corp"),
                            ("umbra-corp", "Umbra Corp")):
            source.add((ENTITY[local], RDF.type, ONTO.Entity))
            source.add((ENTITY[local], SKOS.prefLabel, Literal(name)))
            source.add((ENTITY[local], ONTO.kind, Literal("Company")))
        updated, _ = plan_apply(
            source,
            [plan_entity("e1", "Acme Corp",
                         existing_id=str(ENTITY["acme-corp"])),
             plan_entity("e2", "Umbra Corp",
                         existing_id=str(ENTITY["umbra-corp"]))],
            [{"subject": "e1", "predicate": "buys", "object": "e2",
              "confidence": 0.9}], [])
        labels = list(updated.objects(RELATION["buys"], RDFS.label))
        self.assertEqual(labels, [Literal("buys")])

    def test_namespace_bindings_survive_copy_and_round_trip(self):
        source = Graph()
        bind(source)
        source.add((ONTO.ontology, RDF.type, OWL.Ontology))
        updated, _ = plan_apply(
            source, [plan_entity("e1", "Nova Corp")], [], [])
        prefixes = {prefix for prefix, _ in updated.namespaces()}
        self.assertIn("onto", prefixes)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "g.ttl"
            save_graph(updated, path)
            reloaded = open_graph(path)
        self.assertIn("onto", {p for p, _ in reloaded.namespaces()})
        self.assertIn((ENTITY["nova-corp"], RDF.type, ONTO.Entity),
                      set(reloaded))

    def test_the_input_graph_stays_triple_identical(self):
        source = Graph()
        source.add((ENTITY["acme-corp"], RDF.type, ONTO.Entity))
        before = set(source)
        updated, _ = plan_apply(
            source, [plan_entity("e1", "Nova Corp")], [], [])
        self.assertEqual(set(source), before)
        self.assertIsNot(updated, source)
        self.assertIn((ENTITY["nova-corp"], RDF.type, ONTO.Entity),
                      set(updated))

    def test_a_forced_failure_returns_no_partially_mutated_input(self):
        source = Graph()
        source.add((ENTITY["acme-corp"], RDF.type, ONTO.Entity))
        before = set(source)
        provenance = {"source_path": "s.md", "source_sha256": "0" * 64,
                      "model": "m", "policy_version": 1}
        plan = plan_graph_merge(
            source, {"entities": [plan_entity("e1", "Nova Corp")],
                     "relations": [], "facts": []}, provenance)
        plan["domain_triples"] = [(None, None, None)]
        with self.assertRaises(Exception):
            apply_merge_plan(source, plan)
        self.assertEqual(set(source), before)




if __name__ == "__main__":
    unittest.main()
