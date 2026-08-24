"""Unit tests for source-local staging across one document's windows."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from text_to_ontology.graph_management import ONTO
from text_to_ontology.merge_policy import build_provenance
from text_to_ontology.source_staging import (
    final_graphs_snapshot,
    layered_context_text,
    plan_window_admission,
    provisional_allocator,
    source_staging_graph_name,
    window_activity_id,
    window_candidate_graph_name,
)


def entity_record(local_id, name, kind="Company", confidence=0.9,
                  existing_id=None):
    return {"id": local_id, "name": name, "kind": kind,
            "description": "", "aliases": [],
            "existing_id": existing_id, "confidence": confidence}


def package(*entities):
    return {"entities": list(entities), "relations": [], "facts": []}


class NamingTest(unittest.TestCase):
    def test_the_staging_name_is_stable_and_document_scoped(self):
        self.assertEqual(
            str(source_staging_graph_name("doc-abc")),
            "http://example.org/text-ontology/staging/doc-abc")

    def test_the_candidate_name_pairs_document_and_window(self):
        self.assertEqual(
            str(window_candidate_graph_name("doc-abc", "win-123")),
            "http://example.org/text-ontology/staging/doc-abc/win-123")

    def test_two_documents_never_share_a_staging_graph(self):
        self.assertNotEqual(source_staging_graph_name("doc-1"),
                            source_staging_graph_name("doc-2"))

    def test_activity_ids_are_deterministic_and_content_sensitive(self):
        first = window_activity_id("doc-1", "win-1", "model", package(
            entity_record("e1", "Acme Corp")))
        self.assertEqual(first, window_activity_id(
            "doc-1", "win-1", "model", package(entity_record("e1", "Acme Corp"))))
        self.assertNotEqual(first, window_activity_id(
            "doc-1", "win-2", "model", package(entity_record("e1", "Acme Corp"))))


class ProvisionalAllocatorTest(unittest.TestCase):
    def test_allocations_are_deterministic_and_provisional(self):
        self.assertEqual(
            str(provisional_allocator("doc-1")("Acme Corp")),
            "http://example.org/text-ontology/provisional/doc-1/acme-corp")

    def test_the_same_allocator_never_repeats_a_uri(self):
        allocate = provisional_allocator("doc-1")
        self.assertNotEqual(str(allocate("Nova")), str(allocate("Nova")))

    def test_different_documents_may_allocate_the_same_slug(self):
        self.assertEqual(
            str(provisional_allocator("doc-1")("Nova")),
            str(provisional_allocator("doc-2")("Nova")).replace("doc-2",
                                                                "doc-1"))


class AdmissionTest(unittest.TestCase):
    """M5-AC3: admission sees only this document's earlier windows."""

    def setUp(self):
        self.provenance = build_provenance(Path("notes.txt"), "text", "model")

    def test_an_existing_id_hint_cannot_resolve_to_a_canonical_individual(self):
        canonical = Graph()
        canonical.add((ONTO.Entity, RDF.type, ONTO.Entity))
        # The hint names a canonical entity URI; the source graph is empty,
        # so nothing canonical can be resolved here.
        plan = plan_window_admission(
            Graph(),
            package(entity_record("e1", "Acme Corp",
                                  existing_id=str(URIRef(
                                      "http://example.org/text-ontology/entity/acme-corp")))),
            self.provenance, "doc-1")
        decision = plan["identities"]["e1"]
        self.assertEqual(decision["status"], "new")
        self.assertIn("/provisional/doc-1/", str(decision["uri"]))

    def test_new_entities_receive_deterministic_provisional_uris(self):
        plan = plan_window_admission(
            Graph(), package(entity_record("e1", "Acme Corp")),
            self.provenance, "doc-1")
        self.assertEqual(
            plan["identities"]["e1"]["uri"],
            URIRef("http://example.org/text-ontology/provisional/"
                   "doc-1/acme-corp"))

    def test_a_repeated_exact_name_from_an_earlier_window_resolves(self):
        """M5-AC6: unambiguous local identity evidence creates no duplicate."""
        first = plan_window_admission(
            Graph(), package(entity_record("e1", "Acme Corp")),
            self.provenance, "doc-1")
        from text_to_ontology.graph_merge import apply_merge_plan
        source_graph, _counts = apply_merge_plan(Graph(), first)

        second = plan_window_admission(
            source_graph, package(entity_record("e9", "Acme Corp")),
            self.provenance, "doc-1")
        decision = second["identities"]["e9"]
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(decision["method"], "exact_name")

    def test_a_local_name_collision_is_retained_not_silently_resolved(self):
        """M5-AC7: local identity trouble survives for reconciliation."""
        from text_to_ontology.graph_merge import apply_merge_plan
        first = plan_window_admission(
            Graph(),
            package(entity_record("e1", "Acme Corp", kind="Company"),
                    entity_record("e2", "Acme Corp", kind="Product")),
            self.provenance, "doc-1")
        source_graph, _counts = apply_merge_plan(Graph(), first)
        # Only the unambiguous company is staged; the colliding product
        # record is retained as review evidence, never dropped or merged.
        staged = set(source_graph.subjects(RDF.type, ONTO.Entity))
        self.assertEqual(len(staged), 1)
        self.assertEqual(first["identities"]["e2"]["status"], "review")
        self.assertEqual(first["identities"]["e2"]["reason_codes"],
                         ["identity.kind_collision"])

        # A later window mentioning the colliding name is held again.
        second = plan_window_admission(
            source_graph,
            package(entity_record("e3", "Acme Corp", kind="Product")),
            self.provenance, "doc-1")
        decision = second["identities"]["e3"]
        self.assertEqual(decision["status"], "review")
        self.assertEqual(decision["reason_codes"],
                         ["identity.kind_collision"])
        source_graph, _counts = apply_merge_plan(source_graph, second)
        self.assertEqual(set(source_graph.subjects(RDF.type, ONTO.Entity)),
                         staged)

    def test_planning_leaves_the_source_graph_unchanged(self):
        source_graph = Graph()
        before = final_graphs_snapshot(source_graph)
        plan_window_admission(
            source_graph, package(entity_record("e1", "Acme Corp")),
            self.provenance, "doc-1")
        self.assertEqual(final_graphs_snapshot(source_graph), before)


class SnapshotTest(unittest.TestCase):
    def test_the_snapshot_is_order_independent_and_detects_change(self):
        graph = Graph()
        graph.add((ONTO.Entity, RDF.type, ONTO.Entity))
        reordered = Graph()
        for triple in reversed(list(graph)):
            reordered.add(triple)
        self.assertEqual(final_graphs_snapshot(graph),
                         final_graphs_snapshot(reordered))
        changed = Graph()
        for triple in graph:
            changed.add(triple)
        changed.add((ONTO.Entity, SKOS.prefLabel, Literal("Entity")))
        self.assertNotEqual(final_graphs_snapshot(graph),
                            final_graphs_snapshot(changed))


class LayeredContextTest(unittest.TestCase):
    """M5-T5: source-local context is visible but clearly marked."""

    def canonical_package(self):
        concepts = []
        return {
            "concepts": concepts, "schema": [], "patterns": [],
            "resources": [{
                "id": "resource|canonical", "kind": "resource", "priority": 1,
                "reason": "test", "value": {
                    "uri": URIRef("http://example.org/text-ontology/entity/x"),
                    "names": ["Canonical X"], "preferred": "Canonical X",
                    "types": [], "kind": "", "description": "",
                    "native": True, "id": str(URIRef(
                        "http://example.org/text-ontology/entity/x")),
                },
            }],
            "examples": [], "labels": {},
            "diagnostics": {"limits": {}},
        }

    def source_package(self):
        return {
            "concepts": [], "schema": [], "patterns": [],
            "resources": [{
                "id": "resource|provisional", "kind": "resource", "priority": 1,
                "reason": "test", "value": {
                    "uri": URIRef("http://example.org/text-ontology/"
                                  "provisional/doc-1/acme-corp"),
                    "names": ["Staged Acme"], "preferred": "Staged Acme",
                    "types": [], "kind": "", "description": "",
                    "native": True, "id": "http://example.org/text-ontology/"
                                          "provisional/doc-1/acme-corp",
                },
            }],
            "examples": [], "labels": {},
            "diagnostics": {"limits": {}},
        }

    def budget(self):
        return {"context_tokens": 10_000}

    def test_source_items_are_marked_as_this_document(self):
        result = layered_context_text(
            self.canonical_package(), self.source_package(), self.budget(),
            count_tokens=lambda text: len(text))
        self.assertIn("(this document) - name: Staged Acme", result["text"])
        self.assertIn("- name: Canonical X", result["text"])
        self.assertNotIn("(this document) - name: Canonical X",
                         result["text"])

    def test_only_canonical_resources_become_existing_ids(self):
        result = layered_context_text(
            self.canonical_package(), self.source_package(), self.budget(),
            count_tokens=lambda text: len(text))
        self.assertEqual(result["existing_ids"], [
            "http://example.org/text-ontology/entity/x"])

    def test_without_a_source_package_it_behaves_like_single_context(self):
        alone = layered_context_text(
            self.canonical_package(), None, self.budget(),
            count_tokens=lambda text: len(text))
        self.assertNotIn("(this document)", alone["text"])
        self.assertIn("- name: Canonical X", alone["text"])


if __name__ == "__main__":
    unittest.main()
