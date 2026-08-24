"""M6: complete-source reconciliation and deterministic artifacts."""

import unittest
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF

from text_to_ontology.candidate_graph import build_candidate_graph
from text_to_ontology.graph_merge import apply_merge_plan
from text_to_ontology.merge_policy import build_provenance
from text_to_ontology.source_reconciliation import (
    build_source_artifact,
    canonical_ntriples,
    reconcile_document,
)
from text_to_ontology.source_staging import (
    plan_window_admission,
    window_candidate_graph_name,
)
from text_to_ontology.windowing import WindowingConfig, make_source_document


def package(local_id="e1"):
    return {
        "entities": [
            {"id": local_id, "name": "Acme Corp", "kind": "Company",
             "description": "", "aliases": ["Acme"],
             "existing_id": None, "confidence": 0.9},
            {"id": "e2", "name": "Beta Corp", "kind": "Company",
             "description": "", "aliases": [],
             "existing_id": None, "confidence": 0.9},
        ],
        "relations": [{"subject": local_id, "predicate": "owns",
                       "object": "e2", "confidence": 0.9}],
        "facts": [],
    }


def admit(source_graph, candidates, window_id):
    provenance = build_provenance(Path("notes.txt"), "window", "model")
    provenance["window_id"] = window_id
    plan = plan_window_admission(
        source_graph, candidates, provenance, "doc-1")
    entity_iris = {
        local_id: decision["uri"]
        for local_id, decision in plan["identities"].items()
        if decision["status"] != "review"
    }
    assertion_triples = {
        (section, item["index"]): item["triple"]
        for section in ("relations", "facts")
        for item in plan[section]
        if item["triple"] is not None
    }
    candidate = build_candidate_graph(
        candidates, "doc-1", window_id, "activity-" + window_id, "model",
        entity_iris=entity_iris, assertion_triples=assertion_triples)
    updated, _counts = apply_merge_plan(source_graph, plan)
    return updated, plan, candidate


class DuplicateSupportTest(unittest.TestCase):
    def test_overlap_duplicate_has_one_assertion_and_two_prov_dqv_supports(self):
        source, first_plan, first_candidate = admit(
            Graph(), package("e1"), "win-1")
        source, second_plan, second_candidate = admit(
            source, package("e9"), "win-2")
        candidates = {
            window_candidate_graph_name("doc-1", "win-1"): first_candidate,
            window_candidate_graph_name("doc-1", "win-2"): second_candidate,
        }
        report = reconcile_document(
            "doc-1", source, candidates,
            [{"window_id": "win-1", "plan": first_plan},
             {"window_id": "win-2", "plan": second_plan}],
        )

        self.assertEqual(report["counts"]["duplicate_assertions"], 1)
        duplicate = report["duplicate_assertions"][0]
        self.assertEqual(duplicate["support_count"], 2)
        self.assertEqual({item["confidence"] for item in duplicate["supports"]},
                         {0.9})
        for candidate in candidates.values():
            self.assertTrue(list(candidate.subjects(RDF.type, PROV.Collection)))

    def test_report_lists_local_entities_and_aliases(self):
        source, plan, candidate = admit(Graph(), package(), "win-1")
        report = reconcile_document(
            "doc-1", source,
            {window_candidate_graph_name("doc-1", "win-1"): candidate},
            [{"window_id": "win-1", "plan": plan}],
        )
        self.assertEqual(report["counts"]["local_entities"], 2)
        self.assertEqual(report["aliases"][0]["alias"], "Acme")

    def test_report_keeps_unresolved_identities_and_conflicts_explicit(self):
        plan = {
            "identities": {
                "e1": {"status": "review",
                       "reason_codes": ["identity.kind_collision"],
                       "suggestions": []},
            },
            "entities": [],
            "relations": [],
            "facts": [{
                "index": 0,
                "outcome": "review",
                "reason_codes": ["conflict.functional_value"],
                "triple": (URIRef("urn:s"), URIRef("urn:p"), Literal("new")),
                "conflicts": [
                    (URIRef("urn:s"), URIRef("urn:p"), Literal("old"))],
            }],
        }
        report = reconcile_document(
            "doc-1", Graph(), {}, [{"window_id": "win-1", "plan": plan}])
        self.assertEqual(report["counts"]["unresolved_identities"], 1)
        self.assertEqual(report["unresolved_identities"][0]["local_id"], "e1")
        self.assertEqual(report["counts"]["conflicts"], 1)
        self.assertEqual(report["conflicts"][0]["reason_codes"],
                         ["conflict.functional_value"])


class ArtifactTest(unittest.TestCase):
    def test_canonical_serialization_is_stable_across_blank_node_ids(self):
        first, second = Graph(), Graph()
        first.add((URIRef("urn:s"), URIRef("urn:p"), BNode("first")))
        second.add((URIRef("urn:s"), URIRef("urn:p"), BNode("second")))
        self.assertEqual(canonical_ntriples(first), canonical_ntriples(second))

    def test_artifact_records_every_version_and_extractor_identity(self):
        document = make_source_document("notes.txt", "Acme exists.")
        graph = Graph()
        graph.add((URIRef("urn:s"), URIRef("urn:p"), Literal("value")))
        artifact = build_source_artifact(
            document, graph, WindowingConfig(strategy_version=7),
            ["model-b", "model-a", "model-a"])
        self.assertEqual(artifact.document_digest, document.digest)
        self.assertEqual(artifact.window_strategy_version, 7)
        self.assertGreaterEqual(artifact.candidate_mapping_version, 1)
        self.assertEqual(artifact.extractor_identities,
                         ("model-a", "model-b"))
        self.assertEqual(len(artifact.graph_digest), 64)
        self.assertIn("urn:s", artifact.ntriples)

        repeated = build_source_artifact(
            document, graph, WindowingConfig(strategy_version=7),
            ["model-a", "model-b"])
        self.assertEqual(repeated.graph_digest, artifact.graph_digest)
        self.assertEqual(repeated.ntriples, artifact.ntriples)


if __name__ == "__main__":
    unittest.main()
