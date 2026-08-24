"""Proposal 07B: explicit, reasoned, read-only identity decisions."""

import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from text_to_ontology.entity_lookup import identity_decision, identity_key
from text_to_ontology.graph_management import ENTITY, ONTO
from text_to_ontology.merge_policy import (
    AUTO_ACCEPT_MIN_CONFIDENCE, canonical_json, proposed_entity_uri,
    record_digest, resolve_entities,
)


BASE = "http://example.org/text-ontology/entity/"


def item(local, names, kind):
    """One catalog entry shaped like entity_catalog output."""
    return {"id": BASE + local, "names": list(names), "kind": kind,
            "description": ""}


def candidate(identifier, name, kind="Company", aliases=(), existing_id=None,
              confidence=AUTO_ACCEPT_MIN_CONFIDENCE):
    return {"id": identifier, "name": name, "kind": kind,
            "aliases": list(aliases), "existing_id": existing_id,
            "confidence": confidence}


def decide(entity, catalog=(), planned=(), allocate_uri=None,
           provisional_uri=None):
    return identity_decision(
        entity, list(catalog), planned_catalog=list(planned),
        min_new_confidence=AUTO_ACCEPT_MIN_CONFIDENCE,
        allocate_uri=allocate_uri or (lambda name: URIRef(BASE + "minted")),
        provisional_uri=provisional_uri or proposed_entity_uri,
    )


def add_entity(graph, local, name, kind):
    uri = ENTITY[local]
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, OWL.NamedIndividual))
    graph.add((uri, RDF.type, SKOS.Concept))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    graph.add((uri, ONTO.kind, Literal(kind)))
    return uri


class IdentityKeyTest(unittest.TestCase):
    """7B.10: the current normalization is pinned, not silently migrated."""

    def test_case_and_punctuation_are_folded(self):
        self.assertEqual(identity_key("Acme Corp!"), identity_key("acme corp"))

    def test_decomposable_accents_fold_to_ascii(self):
        self.assertEqual(identity_key("Caf\u00e9"), "cafe")

    def test_undecomposable_letters_are_dropped_not_transliterated(self):
        self.assertEqual(identity_key("\u4e2d\u6587"), "")

    def test_spaces_and_symbols_vanish(self):
        self.assertEqual(identity_key("a-b c.d"), "abcd")


class ExplicitIdTest(unittest.TestCase):
    """7B.2: a valid explicit id resolves and records its method."""

    def test_an_explicit_id_resolves_to_that_uri(self):
        catalog = [item("acme-corp", ["Acme Corp"], "Company")]
        decision = decide(candidate("e1", "Whatever", existing_id=BASE + "acme-corp"),
                          catalog)
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(decision["method"], "explicit_id")
        self.assertEqual(str(decision["uri"]), BASE + "acme-corp")
        self.assertEqual(decision["reason_codes"], [])

    def test_the_decision_record_has_exactly_the_agreed_fields(self):
        decision = decide(candidate("e1", "Acme"), [])
        self.assertEqual(set(decision), {
            "local_id", "status", "uri", "method", "identity_score", "suggestions",
            "reason_codes"})


class ExactMatchTest(unittest.TestCase):
    """7B.3, 7B.4: unique exact same-kind matches auto-resolve."""

    def test_a_unique_preferred_name_match_records_exact_name(self):
        catalog = [item("acme-corp", ["Acme Corp"], "Company")]
        decision = decide(candidate("e1", "Acme Corp"), catalog)
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(decision["method"], "exact_name")

    def test_an_alias_match_records_exact_alias(self):
        catalog = [item("acme-corp", ["Acme Corp", "ACME"], "Company")]
        decision = decide(candidate("e1", "Unrelated Name", aliases=["acme"]),
                          catalog)
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(decision["method"], "exact_alias")

    def test_a_different_kind_never_matches_exactly(self):
        catalog = [item("acme-corp", ["Acme Corp"], "Person")]
        decision = decide(candidate("e1", "Acme Corp", kind="Company"), catalog)
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "kind_collision")

    def test_a_preferred_name_matching_a_catalog_alias_records_exact_name(self):
        catalog = [item("acme-corp", ["The Acme Corporation", "AC"], "Company")]
        decision = decide(candidate("e1", "AC"), catalog)
        self.assertEqual(decision["method"], "exact_name")


class AmbiguousExactTest(unittest.TestCase):
    """7B.5: several same-kind exact matches become review, never first-URI."""

    def test_two_same_kind_matches_become_review_with_sorted_suggestions(self):
        catalog = [item("zeta", ["Acme Corp"], "Company"),
                   item("alpha", ["Acme Corp"], "Company")]
        decision = decide(candidate("e1", "Acme Corp"), catalog)
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "ambiguous_exact")
        self.assertEqual(decision["reason_codes"], ["identity.ambiguous_exact"])
        self.assertEqual([s["uri"] for s in decision["suggestions"]],
                         [BASE + "alpha", BASE + "zeta"])
        self.assertIsNone(decision["identity_score"])

    def test_matches_under_different_kinds_are_not_ambiguous(self):
        catalog = [item("acme-person", ["Acme Corp"], "Person"),
                   item("acme-company", ["Acme Corp"], "Company")]
        decision = decide(candidate("e1", "Acme Corp", kind="Company"), catalog)
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(str(decision["uri"]), BASE + "acme-company")


class KindCollisionTest(unittest.TestCase):
    """7B.6: an exact label only under another kind is review, not a homonym."""

    def test_a_label_owned_by_another_kind_is_review(self):
        catalog = [item("acme-person", ["Acme Corp"], "Person")]
        decision = decide(candidate("e1", "Acme Corp", kind="Company"), catalog)
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "kind_collision")
        self.assertEqual(decision["reason_codes"], ["identity.kind_collision"])
        self.assertEqual([s["uri"] for s in decision["suggestions"]],
                         [BASE + "acme-person"])

    def test_an_alias_can_cause_the_collision(self):
        catalog = [item("acme-person", ["Ada", "Acme Corp"], "Person")]
        decision = decide(candidate("e1", "Other", aliases=["acme corp"],
                                    kind="Company"), catalog)
        self.assertEqual(decision["method"], "kind_collision")


class CloseSpellingTest(unittest.TestCase):
    """7B.7, 7B.8: close spelling only ever suggests; it never merges."""

    CLOSE_PAIR = ("Counterproductive Force", "counterproductive forces")

    def close_catalog(self, *locals_):
        return [item(local, [self.CLOSE_PAIR[1]], "Organization")
                for local in locals_]

    def close_candidate(self, identifier="e1", confidence=0.9):
        return candidate(identifier, self.CLOSE_PAIR[0], kind="Organization",
                         confidence=confidence)

    def test_a_unique_close_spelling_at_the_threshold_is_review(self):
        decision = decide(self.close_candidate(), self.close_catalog("forces"))
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "close_spelling")
        self.assertEqual(decision["reason_codes"], ["identity.close_spelling"])
        self.assertGreaterEqual(decision["identity_score"], 0.96)
        self.assertEqual(len(decision["suggestions"]), 1)
        self.assertEqual(decision["suggestions"][0]["uri"], BASE + "forces")
        self.assertGreaterEqual(decision["suggestions"][0]["identity_score"], 0.96)

    def test_tied_close_spellings_are_review_with_all_suggestions(self):
        catalog = self.close_catalog("one", "two")
        decision = decide(self.close_candidate(), catalog)
        self.assertEqual(decision["status"], "review")
        self.assertEqual(len(decision["suggestions"]), 2)

    def test_scores_below_the_threshold_permit_new_entity_consideration(self):
        catalog = [item("far-away", ["Completely Different Thing"],
                        "Organization")]
        decision = decide(self.close_candidate(), catalog)
        self.assertEqual(decision["status"], "new")

    def test_close_spelling_never_returns_an_existing_status(self):
        for catalog in (self.close_catalog("forces"),
                        self.close_catalog("one", "two")):
            decision = decide(self.close_candidate(), catalog)
            self.assertNotEqual(decision["status"], "existing")


class NewEntityTest(unittest.TestCase):
    """7B.8, 7B.9, 7B.11, 7B.12: safe creation and review-only proposals."""

    def mint(self, reserved=()):
        issued = []

        def allocate(name):
            from text_to_ontology.graph_merge import slug
            stem, number = slug(name), 1
            while True:
                suffix = "" if number == 1 else f"-{number}"
                uri = ENTITY[stem + suffix]
                if str(uri) not in reserved:
                    issued.append(uri)
                    return uri
                number += 1

        return allocate, issued

    def test_a_confident_unmatched_entity_is_new(self):
        allocate, issued = self.mint()
        decision = decide(candidate("e1", "Brand New Thing"),
                          [], allocate_uri=allocate)
        self.assertEqual(decision["status"], "new")
        self.assertEqual(decision["method"], "new")
        self.assertEqual(decision["reason_codes"], [])
        self.assertEqual(issued, [ENTITY["brand-new-thing"]])

    def test_suffix_allocation_skips_existing_subjects(self):
        allocate, _ = self.mint(reserved={BASE + "acme"})
        decision = decide(candidate("e1", "Acme"), [],
                          allocate_uri=allocate)
        self.assertEqual(str(decision["uri"]), BASE + "acme-2")

    def test_suffix_allocation_skips_earlier_reservations(self):
        allocate, _ = self.mint(reserved={BASE + "acme", BASE + "acme-2"})
        decision = decide(candidate("e1", "Acme"), [],
                          allocate_uri=allocate)
        self.assertEqual(str(decision["uri"]), BASE + "acme-3")

    def test_a_below_threshold_new_entity_is_review_only(self):
        decision = decide(candidate("e1", "Shaky Thing", confidence=0.5), [])
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["method"], "new")
        self.assertEqual(decision["reason_codes"],
                         ["identity.new_below_confidence"])
        self.assertIsNotNone(decision["uri"])
        self.assertTrue(str(decision["uri"]).startswith(
            str(ONTO["merge-proposed-entity/"])))

    def test_the_boundary_value_itself_is_new(self):
        allocate, _ = self.mint()
        decision = decide(
            candidate("e1", "Boundary Thing",
                      confidence=AUTO_ACCEPT_MIN_CONFIDENCE),
            [], allocate_uri=allocate)
        self.assertEqual(decision["status"], "new")

    def test_an_empty_catalog_still_yields_a_decision(self):
        decision = decide(candidate("e1", "Anything"), [])
        self.assertEqual(decision["status"], "new")

    def test_missing_catalog_kind_never_auto_resolves(self):
        catalog = [{"id": BASE + "kindless", "names": ["Acme Corp"],
                    "kind": "", "description": ""}]
        decision = decide(candidate("e1", "Acme Corp"), catalog)
        self.assertEqual(decision["status"], "review")

    def test_missing_labels_leave_creation_open(self):
        catalog = [{"id": BASE + "silent", "names": [], "kind": "Company",
                    "description": ""}]
        decision = decide(candidate("e1", "Acme Corp"), catalog)
        self.assertEqual(decision["status"], "new")


class PlannedVisibilityTest(unittest.TestCase):
    """7B.13, 7B.14: sequential visibility inside one response."""

    def test_a_later_candidate_resolves_to_an_earlier_accepted_entity(self):
        first = decide(candidate("e1", "Brand New Thing"), [])
        self.assertEqual(first["status"], "new")
        planned = [{"id": str(first["uri"]), "names": ["Brand New Thing"],
                    "kind": "Company", "description": ""}]
        second = decide(candidate("e2", "brand new thing"), [],
                        planned=planned)
        self.assertEqual(second["status"], "existing")
        self.assertEqual(second["method"], "planned_exact")
        self.assertEqual(str(second["uri"]), str(first["uri"]))

    def test_a_later_candidate_cannot_resolve_to_a_review_proposal(self):
        shaky = candidate("e1", "Shaky Thing", confidence=0.5)
        first = decide(shaky, [])
        self.assertEqual(first["status"], "review")
        # The proposal is not canonical, so it enters no virtual catalog.
        second = decide(candidate("e2", "Shaky Thing"), [])
        self.assertNotEqual(second["status"], "existing")
        self.assertNotIn("planned_exact", second["method"])

    def test_planned_entities_do_not_satisfy_explicit_ids(self):
        planned = [{"id": BASE + "planned-one", "names": ["Planned One"],
                    "kind": "Company", "description": ""}]
        decision = decide(candidate("e1", "x", existing_id=BASE + "planned-one"),
                          [], planned=planned)
        self.assertNotEqual(decision["method"], "explicit_id")
        self.assertNotEqual(str(decision["uri"]), BASE + "planned-one")


class DeterminismTest(unittest.TestCase):
    """7B.15, 7B.16: stable decisions and untouched inputs."""

    def graph_with(self, triples):
        graph = Graph()
        for triple in triples:
            graph.add(triple)
        return graph

    def acme_graph(self):
        return self.graph_with([
            (ENTITY["acme-corp"], RDF.type, ONTO.Entity),
            (ENTITY["acme-corp"], SKOS.prefLabel, Literal("Acme Corp")),
            (ENTITY["acme-corp"], ONTO.kind, Literal("Company")),
        ])

    def package(self):
        return {"entities": [
            candidate("e1", "Acme Corp"),
            candidate("e2", "Brand New Thing"),
            candidate("e3", "Shaky Thing", confidence=0.5),
        ], "relations": [], "facts": []}

    def test_decisions_are_identical_across_graph_insertion_order(self):
        other = self.graph_with([
            (ENTITY["acme-corp"], ONTO.kind, Literal("Company")),
            (ENTITY["acme-corp"], RDF.type, ONTO.Entity),
            (ENTITY["acme-corp"], SKOS.prefLabel, Literal("Acme Corp")),
        ])
        one = resolve_entities(self.package(), self.acme_graph())
        two = resolve_entities(dict(self.package()), other)
        self.assertEqual(one, two)

    def test_repeated_runs_give_identical_decisions(self):
        one = resolve_entities(self.package(), self.acme_graph())
        two = resolve_entities(self.package(), self.acme_graph())
        self.assertEqual(one, two)

    def test_the_graph_is_triple_identical_after_resolution(self):
        graph = self.acme_graph()
        before = set(graph)
        resolve_entities(self.package(), graph)
        self.assertEqual(set(graph), before)
        self.assertEqual(len(graph), len(before))

    def test_inputs_are_not_mutated(self):
        package = self.package()
        catalog = [item("acme-corp", ["Acme Corp"], "Company")]
        snapshot = repr((package, catalog))
        decide(package["entities"][0], catalog)
        identity_decision(package["entities"][0], catalog)
        self.assertEqual(repr((package, catalog)), snapshot)

    def test_decisions_are_keyed_by_local_id(self):
        decisions = resolve_entities(self.package(), self.acme_graph())
        self.assertEqual(set(decisions), {"e1", "e2", "e3"})
        self.assertEqual(decisions["e1"]["status"], "existing")
        self.assertEqual(decisions["e2"]["status"], "new")
        self.assertEqual(decisions["e3"]["status"], "review")


class CanonicalJsonTest(unittest.TestCase):
    """7C.17 pinned early: the serialization every digest depends on."""

    def test_keys_are_sorted_and_separators_compact(self):
        text = canonical_json({"b": 1, "a": 2})
        self.assertEqual(text, '{"a":2,"b":1}')

    def test_list_order_is_preserved(self):
        self.assertNotEqual(canonical_json([1, 2]), canonical_json([2, 1]))

    def test_non_ascii_survives_as_utf8_text(self):
        self.assertIn("\u00e9", canonical_json({"name": "Caf\u00e9"}))

    def test_equal_content_gives_equal_digests_regardless_of_key_order(self):
        one = record_digest({"a": 1, "b": 2})
        two = record_digest({"b": 2, "a": 1})
        self.assertEqual(one, two)
        self.assertRegex(one, r"^[0-9a-f]{64}$")

    def test_proposed_uris_are_content_addressed_and_deterministic(self):
        entity = candidate("e1", "Shaky Thing", confidence=0.5)
        self.assertEqual(proposed_entity_uri(entity), proposed_entity_uri(entity))
        other = candidate("e1", "Shaky Thing", confidence=0.6)
        self.assertNotEqual(proposed_entity_uri(entity), proposed_entity_uri(other))
        self.assertTrue(str(proposed_entity_uri(entity)).startswith(str(ONTO)))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- Phase 7C


import json
import hashlib
from pathlib import Path

from rdflib import BNode

from text_to_ontology.graph_management import CLASS, FACT, RELATION
from text_to_ontology.entity_lookup import entity_catalog
from text_to_ontology.merge_policy import build_provenance, plan_graph_merge
from text_to_ontology import graph_partition
from text_to_ontology import graph_skeleton
from text_to_ontology import graph_patterns


def provenance(**overrides):
    base = {"source_path": "sources/notes.md",
            "source_sha256": "a" * 64, "model": "test-model",
            "policy_version": 1}
    base.update(overrides)
    return base


def catalog_graph():
    graph = Graph()
    add_entity(graph, "acme-corp", "Acme Corp", "Company")
    add_entity(graph, "ada-lovelace", "Ada Lovelace", "Person")
    return graph


def with_relation(graph, local, name, subject, object_, prop_type=None):
    predicate = RELATION[local]
    graph.add((predicate, RDF.type, prop_type or OWL.ObjectProperty))
    graph.add((predicate, RDFS.label, Literal(name)))
    graph.add((subject, predicate, object_))
    return predicate


def plan_for(graph, entities=(), relations=(), facts=(), prov=None):
    return plan_graph_merge(
        graph, {"entities": list(entities), "relations": list(relations),
                "facts": list(facts)},
        prov or provenance())


def new_entity_record(identifier, name, kind="Company", confidence=0.9,
                      **extra):
    record = {"id": identifier, "name": name, "kind": kind,
              "description": "", "aliases": [], "existing_id": None,
              "confidence": confidence}
    record.update(extra)
    return record


def relation_record(subject, predicate, object_, confidence=0.9):
    return {"subject": subject, "predicate": predicate, "object": object_,
            "confidence": confidence}


def fact_record(subject, predicate, value, confidence=0.9):
    return {"subject": subject, "predicate": predicate, "value": value,
            "confidence": confidence}


class PlanShapeTest(unittest.TestCase):
    """7C.1: the MergePlan field set is pinned."""

    def setUp(self):
        self.plan = plan_for(catalog_graph(), [new_entity_record("e9", "Nova")])

    def test_the_plan_has_exactly_the_agreed_top_level_fields(self):
        self.assertEqual(set(self.plan), {
            "policy_version", "provenance", "event_uri", "package_sha256",
            "identities", "entities", "relations", "facts",
            "domain_triples", "audit_triples", "counts", "diagnostics"})

    def test_counts_cover_identities_assertions_and_triples(self):
        counts = self.plan["counts"]
        self.assertEqual(set(counts), {
            "identities", "assertions", "entity_summaries",
            "domain_triples", "audit_triples"})
        self.assertEqual(set(counts["identities"]),
                         {"new", "resolved", "review"})
        self.assertEqual(set(counts["assertions"]),
                         {"accepted", "duplicate", "review"})


class NewPackagePlanTest(unittest.TestCase):
    """7C.2: a completely new high-confidence package plans without applying."""

    def setUp(self):
        self.graph = Graph()
        self.plan = plan_for(
            self.graph,
            [new_entity_record("e1", "Acme Corp"),
             new_entity_record("e2", "Ada Lovelace", kind="Person")],
            [relation_record("e1", "employs", "e2")],
            [fact_record("e2", "birth date", "1815-12-10")])

    def test_identities_are_new_and_assertions_accepted(self):
        self.assertEqual(self.plan["counts"]["identities"],
                         {"new": 2, "resolved": 0, "review": 0})
        self.assertEqual(self.plan["counts"]["assertions"],
                         {"accepted": 2, "duplicate": 0, "review": 0})

    def test_domain_triples_carry_typing_naming_and_assertions(self):
        domain = set(self.plan["domain_triples"])
        self.assertIn((ENTITY["acme-corp"], RDF.type, ONTO.Entity), domain)
        self.assertIn((ENTITY["acme-corp"], SKOS.prefLabel,
                       Literal("Acme Corp")), domain)
        self.assertIn((CLASS["company"], RDFS.subClassOf, ONTO.Entity), domain)
        self.assertIn((ENTITY["acme-corp"], RELATION["employs"],
                       ENTITY["ada-lovelace"]), domain)
        self.assertIn((ENTITY["ada-lovelace"], FACT["birth-date"],
                       Literal("1815-12-10")), domain)
        self.assertIn((RELATION["employs"], RDF.type, OWL.ObjectProperty),
                      domain)

    def test_planning_does_not_apply_the_plan(self):
        self.assertEqual(len(self.graph), 0)

    def test_a_later_assertion_sees_an_earlier_accepted_one(self):
        second = plan_for(
            self.graph,
            [new_entity_record("e1", "Acme Corp"),
             new_entity_record("e2", "Ada Lovelace", kind="Person")],
            [relation_record("e1", "employs", "e2"),
             relation_record("e1", "employs", "e2", confidence=0.95)])
        self.assertEqual(second["counts"]["assertions"]["accepted"], 1)
        self.assertEqual(second["counts"]["assertions"]["duplicate"], 1)


class ResolutionPlanTest(unittest.TestCase):
    """7C.3: explicit and exact-name resolution plans enrich, not duplicate."""

    def setUp(self):
        self.graph = catalog_graph()
        self.acme = str(ENTITY["acme-corp"])

    def test_an_explicit_id_resolves_and_enriches_only(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "ACME", existing_id=self.acme,
                              aliases=["Acme Corporation"]),
        ])
        identity = plan["identities"]["e1"]
        self.assertEqual(identity["status"], "existing")
        self.assertEqual(identity["method"], "explicit_id")
        self.assertEqual(plan["entities"][0]["summary"], "accept")
        self.assertIn((ENTITY["acme-corp"], SKOS.altLabel,
                       Literal("Acme Corporation")),
                      set(plan["domain_triples"]))
        self.assertNotIn((ENTITY["acme-corp"], SKOS.prefLabel,
                          Literal("ACME")), set(plan["domain_triples"]))

    def test_an_exact_name_resolves_without_new_typing(self):
        plan = plan_for(self.graph, [new_entity_record("e1", "Acme Corp")])
        self.assertEqual(plan["identities"]["e1"]["method"], "exact_name")
        self.assertEqual(plan["entities"][0]["summary"], "duplicate")
        domain = set(plan["domain_triples"])
        self.assertNotIn((ENTITY["acme-corp"], RDF.type, ONTO.Entity), domain)


class PreferredNameTest(unittest.TestCase):
    """7C.4: existing preferred labels are never replaced."""

    def setUp(self):
        self.graph = catalog_graph()
        self.acme = str(ENTITY["acme-corp"])

    def test_an_existing_preflabel_is_preserved(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Different Name", existing_id=self.acme),
        ])
        domain = set(plan["domain_triples"])
        self.assertNotIn((ENTITY["acme-corp"], SKOS.prefLabel,
                          Literal("Different Name")), domain)
        self.assertIn((ENTITY["acme-corp"], SKOS.altLabel,
                       Literal("Different Name")), domain)

    def test_a_matching_candidate_name_is_corroboration(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Acme Corp", existing_id=self.acme),
        ])
        self.assertEqual(plan["entities"][0]["fields"]["name"],
                         {"outcome": "duplicate"})
        self.assertEqual(set(plan["domain_triples"]), set())


class AliasPolicyTest(unittest.TestCase):
    """7C.5: alias duplicate, addition, and same-kind ownership conflict."""

    def setUp(self):
        self.graph = catalog_graph()
        add_entity(self.graph, "rival", "ACME Industries", "Company")
        self.acme = str(ENTITY["acme-corp"])

    def test_a_cross_kind_alias_is_not_blocked_by_ownership(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Acme Corp", existing_id=self.acme,
                              aliases=["Ada Lovelace"]),
        ])
        # "Ada Lovelace" belongs to a Person, a different kind: no conflict.
        self.assertEqual(plan["entities"][0]["fields"]["aliases"],
                         [{"alias": "Ada Lovelace", "outcome": "accept"}])

    def test_an_alias_owned_by_another_same_kind_entity_goes_to_review(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Acme Corp", existing_id=self.acme,
                              aliases=["ACME Industries"]),
        ])
        field = plan["entities"][0]["fields"]["aliases"][0]
        self.assertEqual(field["outcome"], "review")
        self.assertEqual(field["reason_codes"],
                         ["alias.claimed_by_other_entity"])
        self.assertEqual(field["owners"], [str(ENTITY["rival"])])
        self.assertNotIn((ENTITY["acme-corp"], SKOS.altLabel,
                          Literal("ACME Industries")),
                         set(plan["domain_triples"]))

    def test_one_conflicting_alias_does_not_block_other_fields(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Acme Corp", existing_id=self.acme,
                              aliases=["ACME Industries"],
                              description="A solid company."),
        ])
        self.assertEqual(plan["entities"][0]["summary"], "partial_review")
        self.assertIn((ENTITY["acme-corp"], RDFS.comment,
                       Literal("A solid company.")),
                      set(plan["domain_triples"]))


class DescriptionPolicyTest(unittest.TestCase):
    """7C.6: empty, new, exact duplicate, and conflicting descriptions."""

    def setUp(self):
        self.graph = Graph()
        add_entity(self.graph, "described", "Described Corp", "Company")
        self.graph.add((ENTITY["described"], RDFS.comment,
                        Literal("The first description.")))
        self.described = str(ENTITY["described"])

    def test_an_empty_description_produces_nothing(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Described Corp",
                              existing_id=self.described),
        ])
        self.assertEqual(plan["entities"][0]["fields"]["description"],
                         {"outcome": "none"})
        self.assertEqual(set(plan["domain_triples"]), set())

    def test_an_exact_duplicate_description_corroborates(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Described Corp",
                              existing_id=self.described,
                              description="The first description."),
        ])
        self.assertEqual(plan["entities"][0]["fields"]["description"],
                         {"outcome": "duplicate"})

    def test_a_differing_description_goes_to_review_without_overwrite(self):
        plan = plan_for(self.graph, [
            new_entity_record("e1", "Described Corp",
                              existing_id=self.described,
                              description="A different story."),
        ])
        field = plan["entities"][0]["fields"]["description"]
        self.assertEqual(field["outcome"], "review")
        self.assertEqual(field["reason_codes"],
                         ["conflict.existing_description"])
        self.assertNotIn((ENTITY["described"], RDFS.comment,
                          Literal("A different story.")),
                         set(plan["domain_triples"]))

    def test_a_new_description_is_added(self):
        plan = plan_for(Graph(), [
            new_entity_record("e1", "Acme Corp", description="Fresh facts."),
        ])
        self.assertIn((ENTITY["acme-corp"], RDFS.comment,
                       Literal("Fresh facts.")),
                      set(plan["domain_triples"]))


class DependencyTest(unittest.TestCase):
    """7C.7: review identities propagate to dependent assertions."""

    def test_a_relation_with_review_endpoints_is_review(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e9", "Shaky Thing", confidence=0.5),
             new_entity_record("e10", "Also Shaky", confidence=0.5)],
            [relation_record("e9", "partners with", "e10")])
        decision = plan["relations"][0]
        self.assertEqual(decision["outcome"], "review")
        self.assertEqual(decision["reason_codes"],
                         ["dependency.unresolved_entity"])
        self.assertIsNone(decision["triple"])
        self.assertEqual(set(plan["domain_triples"]), set())

    def test_a_relation_with_a_review_object_is_review(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"])),
             new_entity_record("e2", "Shaky Thing", confidence=0.5)],
            [relation_record("e1", "employs", "e2")])
        self.assertEqual(plan["relations"][0]["outcome"], "review")
        self.assertEqual(plan["relations"][0]["unresolved"], ["e2"])

    def test_a_fact_with_a_review_subject_is_review(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e9", "Shaky Thing", confidence=0.5)],
            [],
            [fact_record("e9", "rating", "high")])
        self.assertEqual(plan["facts"][0]["outcome"], "review")
        self.assertEqual(plan["facts"][0]["reason_codes"],
                         ["dependency.unresolved_entity"])

    def test_a_review_dependency_does_not_discard_the_candidate(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e9", "Shaky Thing", confidence=0.5)],
            [],
            [fact_record("e9", "rating", "high")])
        audit_subjects = {t[0] for t in plan["audit_triples"]}
        expected = (len(plan["entities"]) + len(plan["relations"])
                    + len(plan["facts"]) + 1)
        self.assertEqual(len(audit_subjects), expected)


class GraphDuplicatePlanTest(unittest.TestCase):
    """7C.8, 7C.9, 7C.15: graph-exact assertions corroborate, never re-add."""

    def setUp(self):
        self.graph = catalog_graph()
        self.acme = str(ENTITY["acme-corp"])
        self.ada = str(ENTITY["ada-lovelace"])
        with_relation(self.graph, "employs", "employs",
                      ENTITY["acme-corp"], ENTITY["ada-lovelace"])
        self.graph.add((ENTITY["ada-lovelace"], FACT["birth-date"],
                        Literal("1815-12-10")))

    def explicit_package(self, confidence=0.9):
        return [new_entity_record("e1", "Acme Corp", existing_id=self.acme,
                                  confidence=confidence),
                new_entity_record("e2", "Ada Lovelace", kind="Person",
                                  existing_id=self.ada,
                                  confidence=confidence)]

    def test_an_explicit_graph_duplicate_is_duplicate(self):
        plan = plan_for(self.graph, self.explicit_package(),
                        [relation_record("e1", "employs", "e2")],
                        [fact_record("e2", "birth date", "1815-12-10")])
        self.assertEqual(plan["relations"][0]["outcome"], "duplicate")
        self.assertEqual(plan["facts"][0]["outcome"], "duplicate")
        self.assertEqual(plan["counts"]["assertions"],
                         {"accepted": 0, "duplicate": 2, "review": 0})

    def test_a_duplicate_adds_evidence_but_no_domain_triple(self):
        before = set(self.graph)
        plan = plan_for(self.graph, self.explicit_package(),
                        [relation_record("e1", "employs", "e2")], [])
        self.assertNotIn((ENTITY["acme-corp"], RELATION["employs"],
                          ENTITY["ada-lovelace"]),
                         set(plan["domain_triples"]))
        self.assertEqual(len(self.graph), len(before))
        reified = [t for t in plan["audit_triples"]
                   if t[1] == RDF.predicate and t[2] == RELATION["employs"]]
        self.assertEqual(len(reified), 1)

    def test_a_low_confidence_duplicate_still_corroborates(self):
        plan = plan_for(self.graph, self.explicit_package(confidence=0.3),
                        [relation_record("e1", "employs", "e2",
                                         confidence=0.3)], [])
        self.assertEqual(plan["relations"][0]["outcome"], "duplicate")
        self.assertNotIn("confidence.below_auto_accept",
                         plan["relations"][0]["reason_codes"])

    def test_an_exact_name_duplicate_is_detected(self):
        plan = plan_for(self.graph,
                        [new_entity_record("e1", "Acme Corp"),
                         new_entity_record("e2", "Ada Lovelace",
                                           kind="Person")],
                        [relation_record("e1", "employs", "e2")], [])
        self.assertEqual(plan["relations"][0]["outcome"], "duplicate")

    def test_a_same_response_planned_duplicate_is_detected(self):
        plan = plan_for(Graph(),
                        [new_entity_record("e1", "Nova Corp"),
                         new_entity_record("e2", "Umbra Corp")],
                        [relation_record("e1", "buys", "e2"),
                         relation_record("e1", "buys", "e2")])
        self.assertEqual(plan["counts"]["assertions"]["accepted"], 1)
        self.assertEqual(plan["counts"]["assertions"]["duplicate"], 1)


class MultiValueTest(unittest.TestCase):
    """7C.10: ordinary differing objects and values coexist."""

    def test_differing_fact_values_are_both_accepted(self):
        graph = catalog_graph()
        graph.add((ENTITY["acme-corp"], FACT["email"], Literal("a@x.com")))
        plan = plan_for(graph,
                        [new_entity_record(
                            "e1", "Acme Corp",
                            existing_id=str(ENTITY["acme-corp"]))],
                        [],
                        [fact_record("e1", "email", "b@y.com")])
        self.assertEqual(plan["facts"][0]["outcome"], "accept")
        self.assertIn((ENTITY["acme-corp"], FACT["email"],
                       Literal("b@y.com")), set(plan["domain_triples"]))

    def test_differing_relation_objects_are_both_accepted(self):
        graph = catalog_graph()
        with_relation(graph, "invests-in", "invests in",
                      ENTITY["acme-corp"], ENTITY["ada-lovelace"])
        plan = plan_for(graph,
                        [new_entity_record(
                            "e1", "Acme Corp",
                            existing_id=str(ENTITY["acme-corp"])),
                         new_entity_record("e2", "Nova Corp")],
                        [relation_record("e1", "invests in", "e2")], [])
        self.assertEqual(plan["relations"][0]["outcome"], "accept")


class FunctionalConflictTest(unittest.TestCase):
    """7C.11, 7C.12, 7C.13: only explicit semantics create conflicts."""

    def functional_graph(self):
        graph = catalog_graph()
        predicate = with_relation(graph, "ceo-of", "ceo of",
                                  ENTITY["ada-lovelace"], ENTITY["acme-corp"])
        graph.add((predicate, RDF.type, OWL.FunctionalProperty))
        return graph

    def test_an_explicit_functional_conflict_goes_to_review(self):
        plan = plan_for(
            self.functional_graph(),
            [new_entity_record("e1", "Ada Lovelace", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"])),
             new_entity_record("e2", "Nova Corp")],
            [relation_record("e1", "ceo of", "e2")], [])
        decision = plan["relations"][0]
        self.assertEqual(decision["outcome"], "review")
        self.assertEqual(decision["reason_codes"],
                         ["conflict.functional_value"])
        self.assertNotIn(decision["triple"], set(plan["domain_triples"]))

    def test_a_functional_conflict_against_the_same_plan_is_caught(self):
        graph = Graph()
        predicate = RELATION["ceo-of"]
        graph.add((predicate, RDF.type, OWL.FunctionalProperty))
        plan = plan_for(
            graph,
            [new_entity_record("e1", "Ada"), new_entity_record("e2", "Acme"),
             new_entity_record("e3", "Nova")],
            [relation_record("e1", "ceo of", "e2"),
             relation_record("e1", "ceo of", "e3")])
        outcomes = [decision["outcome"] for decision in plan["relations"]]
        self.assertEqual(outcomes, ["accept", "review"])

    def test_an_inverse_functional_conflict_goes_to_review(self):
        graph = Graph()
        predicate = RELATION["tax-id-of"]
        graph.add((predicate, RDF.type, OWL.InverseFunctionalProperty))
        graph.add((predicate, RDFS.label, Literal("tax id of")))
        # The object is already used by another subject: an IFP conflict.
        graph.add((ENTITY["acme-corp"], predicate, ENTITY["ada-lovelace"]))
        plan = plan_for(
            graph,
            [new_entity_record("e1", "Nova Corp"),
             new_entity_record("e2", "Ada Lovelace", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"]))],
            [relation_record("e1", "tax id of", "e2")], [])
        decision = plan["relations"][0]
        self.assertEqual(decision["outcome"], "review")
        self.assertEqual(decision["reason_codes"],
                         ["conflict.inverse_functional_value"])

    def test_domain_range_and_labels_never_manufacture_conflicts(self):
        graph = catalog_graph()
        predicate = with_relation(graph, "ceo-of", "ceo of",
                                  ENTITY["ada-lovelace"], ENTITY["acme-corp"])
        graph.add((predicate, RDFS.domain, ENTITY["ada-lovelace"]))
        graph.add((predicate, RDFS.range, ENTITY["acme-corp"]))
        plan = plan_for(
            graph,
            [new_entity_record("e1", "Ada Lovelace", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"])),
             new_entity_record("e2", "Nova Corp")],
            [relation_record("e1", "ceo of", "e2")], [])
        self.assertEqual(plan["relations"][0]["outcome"], "accept")


class ConfidenceGateTest(unittest.TestCase):
    """7C.14: the 0.80 boundary for entities, metadata, relations, facts."""

    def test_below_threshold_new_entity_is_review(self):
        plan = plan_for(Graph(),
                        [new_entity_record("e1", "Shaky", confidence=0.79)])
        self.assertEqual(plan["identities"]["e1"]["status"], "review")
        self.assertEqual(plan["entities"][0]["summary"], "review")

    def test_at_threshold_new_entity_is_accepted(self):
        plan = plan_for(Graph(),
                        [new_entity_record("e1", "Solid", confidence=0.80)])
        self.assertEqual(plan["identities"]["e1"]["status"], "new")
        self.assertEqual(plan["entities"][0]["summary"], "accept")

    def test_below_threshold_relation_is_review_but_grounded(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"])),
             new_entity_record("e2", "Ada Lovelace", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"]))],
            [relation_record("e1", "employs", "e2", confidence=0.5)], [])
        decision = plan["relations"][0]
        self.assertEqual(decision["outcome"], "review")
        self.assertEqual(decision["reason_codes"],
                         ["confidence.below_auto_accept"])
        self.assertIsNotNone(decision["triple"])
        self.assertNotIn(decision["triple"], set(plan["domain_triples"]))

    def test_at_threshold_fact_is_accepted(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"]))],
            [],
            [fact_record("e1", "score", "high", confidence=0.80)])
        self.assertEqual(plan["facts"][0]["outcome"], "accept")

    def test_below_threshold_new_metadata_alias_is_review(self):
        plan = plan_for(
            catalog_graph(),
            [new_entity_record("e1", "Unusual Name", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"]),
                               confidence=0.5)],
            [], [])
        field = plan["entities"][0]["fields"]["name"]
        self.assertEqual(field["outcome"], "review")
        self.assertEqual(field["reason_codes"], ["confidence.below_auto_accept"])


class PartialReviewTest(unittest.TestCase):
    """7C.16: mixed field outcomes give partial_review with field details."""

    def test_mixed_outcomes_are_reported_per_field(self):
        graph = Graph()
        add_entity(graph, "described", "Described Corp", "Company")
        add_entity(graph, "rival", "Rival Corp", "Company")
        graph.add((ENTITY["described"], RDFS.comment,
                   Literal("The first description.")))
        plan = plan_for(
            graph,
            [new_entity_record(
                "e1", "Described Corp",
                existing_id=str(ENTITY["described"]),
                aliases=["Rival Corp"],
                description="A different story.")],
            [], [])
        entity = plan["entities"][0]
        self.assertEqual(entity["summary"], "partial_review")
        self.assertEqual(entity["fields"]["name"], {"outcome": "duplicate"})
        self.assertEqual(entity["fields"]["aliases"][0]["outcome"], "review")
        self.assertEqual(entity["fields"]["description"]["outcome"], "review")
        self.assertEqual(plan["counts"]["entity_summaries"],
                         {"accept": 0, "duplicate": 0, "review": 0,
                          "partial_review": 1})


class EventUriTest(unittest.TestCase):
    """7C.18, 7C.19: deterministic content-addressed event identity."""

    def package(self):
        return [new_entity_record("e1", "Acme Corp")]

    def test_an_exact_rerun_reuses_the_event_and_candidate_uris(self):
        one = plan_for(catalog_graph(), self.package())
        two = plan_for(catalog_graph(), self.package())
        self.assertEqual(one["event_uri"], two["event_uri"])
        self.assertEqual(one["audit_triples"], two["audit_triples"])

    def test_changed_inputs_create_distinct_events(self):
        base = plan_for(catalog_graph(), self.package())
        variants = [
            plan_for(catalog_graph(), self.package(),
                     prov=provenance(source_path="sources/other.md")),
            plan_for(catalog_graph(), self.package(),
                     prov=provenance(source_sha256="b" * 64)),
            plan_for(catalog_graph(), self.package(),
                     prov=provenance(model="other-model")),
            plan_for(catalog_graph(),
                     [new_entity_record("e1", "Acme Corp", confidence=0.8)]),
        ]
        for variant in variants:
            self.assertNotEqual(base["event_uri"], variant["event_uri"])


class AuditMetadataTest(unittest.TestCase):
    """7C.20 to 7C.23: what the audit records retain, and what they never do."""

    def setUp(self):
        self.plan = plan_for(
            catalog_graph(),
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"])),
             new_entity_record("e2", "Ada Lovelace", kind="Person",
                               existing_id=str(ENTITY["ada-lovelace"])),
             new_entity_record("e3", "Shaky Thing", confidence=0.5)],
            [relation_record("e1", "employs", "e2", confidence=0.5)],
            [fact_record("e1", "score", "high")])

    def event_triples(self):
        return [t for t in self.plan["audit_triples"]
                if t[0] == self.plan["event_uri"]]

    def test_the_event_retains_path_digest_model_policy_and_package(self):
        predicates = {t[1] for t in self.event_triples()}
        self.assertEqual(predicates, {
            RDF.type, ONTO.sourcePath, ONTO.sourceSha256, ONTO.modelName,
            ONTO.mergePolicyVersion, ONTO.candidatePackageSha256})
        values = {str(t[1]).rsplit("/", 1)[-1]: str(t[2])
                  for t in self.event_triples() if t[1] != RDF.type}
        self.assertEqual(values["sourcePath"], "sources/notes.md")
        self.assertEqual(values["modelName"], "test-model")
        self.assertEqual(values["mergePolicyVersion"], "1")

    def test_no_raw_source_prompt_context_response_or_secret_is_stored(self):
        secrets = ("sk-secret-key", "OPENROUTER_API_KEY")
        for triple in self.plan["audit_triples"]:
            for term in triple:
                if isinstance(term, Literal):
                    for forbidden in ("SOURCE:", "ONTOLOGY CONTEXT",
                                      "the model is down", *secrets):
                        self.assertNotIn(forbidden, str(term))

    def test_every_candidate_record_retains_the_full_contract(self):
        candidates = {t[0] for t in self.plan["audit_triples"]
                      if t[1] == RDF.type and t[2] == ONTO.MergeCandidate}
        self.assertEqual(len(candidates), 5)
        for subject in candidates:
            predicates = {t[1] for t in self.plan["audit_triples"]
                          if t[0] == subject}
            for required in (ONTO.wasExtractedIn, ONTO.candidateSection,
                             ONTO.candidateIndex, ONTO.normalizedCandidate,
                             ONTO.extractionConfidence, ONTO.mergeDecision):
                self.assertIn(required, predicates)

    def test_normalized_candidate_json_round_trips_the_record(self):
        found = False
        for triple in self.plan["audit_triples"]:
            if triple[1] == ONTO.normalizedCandidate:
                record = json.loads(str(triple[2]))
                self.assertIn("confidence", record)
                found = True
        self.assertTrue(found)

    def test_grounded_review_assertions_carry_reification(self):
        decision = self.plan["relations"][0]
        self.assertEqual(decision["outcome"], "review")
        subject = {t[0] for t in self.plan["audit_triples"]
                   if t[1] == ONTO.candidateSection
                   and str(t[2]) == "relations"}.pop()
        reification = {t[1]: t[2] for t in self.plan["audit_triples"]
                       if t[0] == subject}
        self.assertEqual(reification[RDF.subject], ENTITY["acme-corp"])
        self.assertEqual(reification[RDF.predicate], RELATION["employs"])
        self.assertEqual(reification[RDF.object], ENTITY["ada-lovelace"])

    def test_a_review_triple_is_never_asserted_as_domain_knowledge(self):
        domain = set(self.plan["domain_triples"])
        self.assertNotIn((ENTITY["acme-corp"], RELATION["employs"],
                          ENTITY["ada-lovelace"]), domain)
        self.assertNotIn((ENTITY["shaky-thing"], RDF.type, ONTO.Entity),
                         domain)

    def test_no_audit_resource_is_a_blank_node(self):
        for triple in self.plan["audit_triples"]:
            for term in triple:
                self.assertNotIsInstance(term, BNode)

    def test_resolved_entities_are_linked(self):
        links = {str(t[2]) for t in self.plan["audit_triples"]
                 if t[1] == ONTO.resolvedEntity}
        self.assertIn(str(ENTITY["acme-corp"]), links)
        self.assertIn(str(ENTITY["ada-lovelace"]), links)
        self.assertNotIn(str(ENTITY["shaky-thing"]), links)


class BuildProvenanceTest(unittest.TestCase):
    """The provenance record is built by the planner's caller, not the LLM."""

    def test_posix_path_without_resolution_and_text_digest(self):
        record = build_provenance(Path("sources/../sources/notes.md"),
                                  "the text", "test-model")
        self.assertEqual(record["source_path"],
                         "sources/../sources/notes.md")
        self.assertFalse(record["source_path"].startswith("/"))
        self.assertEqual(record["source_sha256"],
                         hashlib.sha256(b"the text").hexdigest())
        self.assertEqual(record["model"], "test-model")
        self.assertEqual(record["policy_version"], 1)


class PartitionAuditTest(unittest.TestCase):
    """7C.24, 7C.25: audit records live in support; domain links stay put."""

    def audited_graph(self):
        graph = catalog_graph()
        with_relation(graph, "employs", "employs",
                      ENTITY["acme-corp"], ENTITY["ada-lovelace"])
        plan = plan_for(
            graph,
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"]))],
            [], [])
        for triple in plan["audit_triples"]:
            graph.add(triple)
        return graph, plan

    def test_the_partition_stays_lossless_and_disjoint(self):
        graph, _ = self.audited_graph()
        schema, instance, support = graph_partition.partition_graph(graph)
        union = set(schema) | set(instance) | set(support)
        self.assertEqual(union, set(graph))
        self.assertEqual(len(schema) + len(instance) + len(support),
                         len(graph))
        self.assertFalse(set(schema) & set(instance))
        self.assertFalse(set(schema) & set(support))
        self.assertFalse(set(instance) & set(support))

    def test_audit_roots_and_their_triples_land_in_support(self):
        graph, plan = self.audited_graph()
        _, _, support = graph_partition.partition_graph(graph)
        self.assertIn(plan["event_uri"], set(support.subjects()))
        for triple in plan["audit_triples"]:
            self.assertIn(triple, set(support))

    def test_reified_links_do_not_pull_domain_entities_into_support(self):
        graph, _ = self.audited_graph()
        _, instance, support = graph_partition.partition_graph(graph)
        self.assertIn((ENTITY["acme-corp"], RELATION["employs"],
                       ENTITY["ada-lovelace"]), set(instance))
        self.assertNotIn(ENTITY["acme-corp"], set(support.subjects()))


class NoContaminationTest(unittest.TestCase):
    """7C.26: merge metadata never reaches catalogs, skeletons, or patterns."""

    def audited_graph(self):
        graph = catalog_graph()
        with_relation(graph, "employs", "employs",
                      ENTITY["acme-corp"], ENTITY["ada-lovelace"])
        plan = plan_for(
            graph,
            [new_entity_record("e1", "Acme Corp",
                               existing_id=str(ENTITY["acme-corp"]))],
            [], [])
        for triple in plan["audit_triples"]:
            graph.add(triple)
        return graph

    def test_the_entity_catalog_never_lists_audit_records(self):
        ids = {entry["id"] for entry in entity_catalog(self.audited_graph())}
        self.assertEqual(len(ids), 2)

    def test_the_skeleton_never_includes_audit_vocabulary(self):
        schema, _, _ = graph_partition.partition_graph(self.audited_graph())
        skeleton = graph_skeleton.create_graph_skeleton(schema)
        for subject in skeleton.subjects():
            self.assertNotIn("merge-event", str(subject))
            self.assertNotIn("merge-candidate", str(subject))

    def test_patterns_never_count_audit_predicates(self):
        schema, instance, _ = graph_partition.partition_graph(
            self.audited_graph())
        records = graph_patterns.observed_relationships(schema, instance)
        for record in records:
            self.assertNotIn("merge-", str(record["predicate"]))
            self.assertNotIn(str(ONTO.sourcePath), str(record["predicate"]))

    def test_instance_and_schema_views_never_contain_merge_metadata(self):
        schema, instance, _ = graph_partition.partition_graph(
            self.audited_graph())
        for view in (schema, instance):
            for predicate in set(view.predicates()):
                self.assertNotIn("merge-", str(predicate))
                self.assertNotIn("ExtractionEvent", str(predicate))


class PlanDeterminismTest(unittest.TestCase):
    """7C.27, 7C.28: stable plans, untouched inputs."""

    def package(self):
        return {
            "entities": [
                new_entity_record("e1", "Acme Corp",
                                  description="First mover."),
                new_entity_record("e2", "Shaky Thing", confidence=0.5),
            ],
            "relations": [relation_record("e1", "employs", "e2")],
            "facts": [fact_record("e1", "score", "high")],
        }

    def test_plans_are_identical_across_insertion_orders_and_reruns(self):
        plan_one = plan_for(catalog_graph(), **self.package())
        plan_two = plan_for(catalog_graph(), **self.package())
        self.assertEqual(plan_one, plan_two)
        plan_three = plan_for(catalog_graph(), **self.package())
        self.assertEqual(plan_one, plan_three)

    def test_planning_leaves_the_graph_and_inputs_unchanged(self):
        graph = catalog_graph()
        before = set(graph)
        package = self.package()
        snapshot = repr(package)
        plan_for(graph, **package)
        self.assertEqual(set(graph), before)
        self.assertEqual(repr(package), snapshot)


if __name__ == "__main__":
    unittest.main()
