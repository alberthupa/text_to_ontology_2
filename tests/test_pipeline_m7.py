"""M7: one document-level plan and one atomic named-graph publication."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import PROV, RDF, RDFS, SH, SKOS

from text_to_ontology import pipeline
from text_to_ontology import graph_store as graph_store_module
from text_to_ontology.api import (
    ExtractionConfig,
    RunRequest,
    WindowingConfig,
    run_text_to_graph,
)
from text_to_ontology.candidate_graph import DQV
from text_to_ontology.document_publication import PublicationValidationError
from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.run_report import RunReporter
from text_to_ontology.windowing import make_source_document, plan_windows


class FakeExtractor:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def model(self):
        return "test-model"

    def extract(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        return response() if callable(response) else response


class CountingStore(RdflibGraphStore):
    def __init__(self, path=None):
        super().__init__(path)
        self.publish_calls = 0
        self.fail_publication = False

    def publish(self, publication=None):
        self.publish_calls += 1
        if self.fail_publication:
            raise OSError("injected publication failure")
        return super().publish(publication)


def entity(local_id, name, kind="Company", confidence=0.9,
           existing_id=None):
    return {"id": local_id, "name": name, "kind": kind,
            "description": "", "aliases": [],
            "existing_id": existing_id, "confidence": confidence}


def package(names):
    return {"entities": [entity(f"e{number}", name)
                         for number, name in enumerate(names, 1)],
            "relations": [], "facts": []}


def relation_package(confidence=0.9):
    return {
        "entities": [entity("e1", "Acme Corp"),
                     entity("e2", "Ada Lovelace", kind="Person")],
        "relations": [{"subject": "e1", "predicate": "employs",
                       "object": "e2", "confidence": confidence}],
        "facts": [],
    }


def run(request, extractor, store):
    return run_text_to_graph(
        request, graph_store=store, extractor=extractor,
        reporter=RunReporter(stream=io.StringIO()))


def snapshot(store):
    return {name: set(store.get(name)) for name in store.graph_names()}


class PublicationCountTest(unittest.TestCase):
    def test_generic_kinds_reuse_root_across_repeated_ingestion(self):
        for kind in ("Entity", "entity", "ENTITY", None, "", "   "):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "notes.txt"
                source.write_text("A thing exists.", encoding="utf-8")
                response = package(["A thing"])
                if kind is None:
                    del response["entities"][0]["kind"]
                else:
                    response["entities"][0]["kind"] = kind
                store = CountingStore()
                request = RunRequest(source=source,
                                     graph_path=root / "dataset.trig")
                run(request, FakeExtractor(response), store)
                source.write_text("A thing still exists.", encoding="utf-8")
                run(request, FakeExtractor(response), store)
                self.assertEqual(store.publish_calls, 2)
                target = store.get(GraphNames().target_graph)
                self.assertEqual(set(target.subjects(RDF.type, ONTO.Entity)),
                                 {ENTITY["a-thing"]})
                for triples in snapshot(store).values():
                    self.assertFalse(any(CLASS["entity"] in t for t in triples))
                    self.assertNotIn(
                        (ONTO.Entity, RDFS.subClassOf, ONTO.Entity), triples)

    def test_default_api_store_persists_the_named_dataset(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            path = root / "dataset.trig"
            result = run_text_to_graph(
                RunRequest(source=source, graph_path=path),
                extractor=FakeExtractor(package(["Acme Corp"])),
                reporter=RunReporter(stream=io.StringIO()))
            reopened = RdflibGraphStore(path)
        self.assertEqual(result.files_saved, 1)
        self.assertIn(names.target_graph, reopened.graph_names())
        self.assertIn(names.provenance_graph, reopened.graph_names())

    def test_one_successful_document_calls_publication_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            store = CountingStore()
            result = run(RunRequest(source=source,
                                    graph_path=root / "dataset.trig"),
                         FakeExtractor(package(["Acme Corp"])), store)
        self.assertEqual(store.publish_calls, 1)
        self.assertEqual(len(result.documents), 1)
        self.assertIsNotNone(result.documents[0].publication_plan)

    def test_two_files_publish_in_order_and_second_reads_first(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text(
                "Acme Corp and Beta Corp exist.", encoding="utf-8")
            store = CountingStore()
            extractor = FakeExtractor(
                package(["Acme Corp"]), package(["Beta Corp"]))
            result = run(RunRequest(source=root,
                                    graph_path=root / "dataset.trig"),
                         extractor, store)
        self.assertEqual(store.publish_calls, 2)
        self.assertEqual(len(result.documents), 2)
        self.assertNotIn("entity/acme-corp", extractor.prompts[0])
        self.assertIn("entity/acme-corp", extractor.prompts[1])


class OneDocumentPlanTest(unittest.TestCase):
    def test_final_identity_resolution_runs_once_after_many_windows(self):
        text = "\n\n".join(
            "Acme Corp grows and hires people. " * 8 for _ in range(4))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text(text, encoding="utf-8")
            windowing = WindowingConfig(target_tokens=50, overlap_tokens=0)
            count = len(plan_windows(
                make_source_document(source.name, text), windowing))
            extractor = FakeExtractor(*[package(["Acme Corp"])
                                        for _ in range(count)])
            store = CountingStore()
            with mock.patch.object(
                    pipeline, "plan_graph_merge",
                    wraps=pipeline.plan_graph_merge) as planner:
                result = run(RunRequest(
                    source=source, graph_path=root / "dataset.trig",
                    windowing=windowing,
                    extraction=ExtractionConfig(repair_attempts=0)),
                    extractor, store)

        self.assertGreater(count, 1)
        self.assertEqual(planner.call_count, 1)
        mapping = result.documents[0].publication_plan.document_merge[
            "identity_mapping"]
        self.assertEqual(len(mapping), 1)
        decision = next(iter(mapping.values()))
        self.assertEqual(decision["status"], "new")
        self.assertIn("reason_codes", decision)

    def test_identity_search_includes_every_configured_data_graph(self):
        other_data = URIRef("urn:graphs:other-data")
        names = GraphNames(data_graphs=[other_data])
        existing = URIRef("urn:entities:acme")
        graph = Graph()
        graph.add((existing, RDF.type, ONTO.Entity))
        graph.add((existing, ONTO.kind, Literal("Company")))
        graph.add((existing, SKOS.prefLabel, Literal("Acme Corp")))
        store = CountingStore()
        store.put(other_data, graph)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            result = run(RunRequest(
                source=source, graph_path=root / "dataset.trig",
                graph_names=names),
                FakeExtractor(package(["Acme Corp"])), store)
        decision = next(iter(result.documents[0].publication_plan
                             .document_merge["identity_mapping"].values()))
        self.assertEqual(decision["status"], "existing")
        self.assertEqual(decision["uri"], existing)


class DryRunTest(unittest.TestCase):
    def test_dry_run_returns_the_same_graph_replacements_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            dry_path = root / "dry.trig"
            dry_store = CountingStore(path=dry_path)
            dry = run(RunRequest(source=source, graph_path=dry_path,
                                 dry_run=True),
                      FakeExtractor(package(["Acme Corp"])), dry_store)

            real_path = root / "real.trig"
            real_store = CountingStore(path=real_path)
            real = run(RunRequest(source=source, graph_path=real_path),
                       FakeExtractor(package(["Acme Corp"])), real_store)

        self.assertTrue(dry.dry_run)
        self.assertEqual(dry.files_saved, 0)
        self.assertEqual(dry_store.publish_calls, 0)
        self.assertFalse(dry_path.exists())
        self.assertEqual(real_store.publish_calls, 1)
        dry_graphs = dry.documents[0].publication_plan.publication.graphs
        for name in (GraphNames().target_graph, GraphNames().provenance_graph,
                     GraphNames().review_graph):
            self.assertTrue(isomorphic(dry_graphs[name], real_store.get(name)))
        self.assertEqual(
            dry.documents[0].publication_plan.document_merge["identity_mapping"],
            real.documents[0].publication_plan.document_merge["identity_mapping"])


class ProposedValidationTest(unittest.TestCase):
    def test_post_merge_non_conformance_prevents_publication(self):
        names = GraphNames()
        store = CountingStore()
        acme = URIRef("http://example.org/text-ontology/entity/acme-corp")
        target = Graph()
        target.add((acme, RDF.type, ONTO.Entity))
        target.add((acme, ONTO.kind, Literal("Company")))
        target.add((acme, SKOS.prefLabel, Literal("Acme Corp")))
        target.add((acme, FACT["status"], Literal("old")))
        shapes = Graph()
        shape = URIRef("urn:shape:one-status")
        rule = URIRef("urn:shape:one-status-rule")
        shapes.add((shape, RDF.type, SH.NodeShape))
        shapes.add((shape, SH.targetClass, ONTO.Entity))
        shapes.add((shape, SH.property, rule))
        shapes.add((rule, SH.path, FACT["status"]))
        shapes.add((rule, SH.maxCount, Literal(1)))
        store.put(names.target_graph, target)
        store.put(names.shape_graphs[0], shapes)
        store.publish()
        store.publish_calls = 0
        before = snapshot(store)

        response = {
            "entities": [entity("e1", "Acme Corp")],
            "relations": [],
            "facts": [{"subject": "e1", "predicate": "status",
                       "value": "new", "confidence": 0.9}],
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp has new status.", encoding="utf-8")
            with self.assertRaises(PublicationValidationError) as caught:
                run(RunRequest(source=source,
                               graph_path=root / "dataset.trig"),
                    FakeExtractor(response), store)

        self.assertFalse(caught.exception.validation.conforms)
        self.assertEqual(store.publish_calls, 0)
        self.assertEqual(snapshot(store), before)


class EvidenceTest(unittest.TestCase):
    def test_duplicate_assertion_keeps_two_independent_confidences(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "01.txt").write_text(
                "Acme Corp employs Ada Lovelace.", encoding="utf-8")
            (root / "02.txt").write_text(
                "Ada Lovelace works at Acme Corp.", encoding="utf-8")
            store = CountingStore()
            result = run(RunRequest(source=root,
                                    graph_path=root / "dataset.trig"),
                         FakeExtractor(relation_package(0.9),
                                       relation_package(0.7)), store)

        target = store.get(names.target_graph)
        acme = URIRef("http://example.org/text-ontology/entity/acme-corp")
        ada = URIRef("http://example.org/text-ontology/entity/ada-lovelace")
        assertion = (acme, RELATION["employs"], ada)
        self.assertIn(assertion, target)
        self.assertEqual(len(list(target.triples(assertion))), 1)

        provenance = store.get(names.provenance_graph)
        statements = {
            statement for statement in provenance.subjects(RDF.type, RDF.Statement)
            if provenance.value(statement, RDF.subject) == acme
            and provenance.value(statement, RDF.predicate) == RELATION["employs"]
            and provenance.value(statement, RDF.object) == ada
        }
        records = {record for statement in statements
                   for record in provenance.subjects(PROV.hadMember, statement)}
        measurements = {measurement for record in records
                        for measurement in provenance.subjects(
                            DQV.computedOn, record)}
        values = {str(provenance.value(item, DQV.value))
                  for item in measurements}
        self.assertEqual(values, {"0.9", "0.7"})
        self.assertEqual(
            result.documents[1].publication_plan.document_merge["merge_plan"]
            ["relations"][0]["outcome"], "duplicate")

    def test_exact_rerun_is_idempotent_for_all_final_graphs(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp employs Ada Lovelace.", encoding="utf-8")
            store = CountingStore()
            request = RunRequest(source=source,
                                 graph_path=root / "dataset.trig")
            run(request, FakeExtractor(relation_package()), store)
            first = {name: set(store.get(name)) for name in (
                names.target_graph, names.provenance_graph, names.review_graph)}
            run(request, FakeExtractor(relation_package()), store)
            second = {name: set(store.get(name)) for name in first}
        self.assertEqual(second, first)


class ReviewGraphTest(unittest.TestCase):
    def test_withheld_identity_is_written_only_as_review_information(self):
        names = GraphNames()
        response = {"entities": [entity(
            "e1", "Uncertain Thing", kind="Concept", confidence=0.5)],
            "relations": [], "facts": []}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("An uncertain thing may exist.", encoding="utf-8")
            store = CountingStore()
            result = run(RunRequest(source=source,
                                    graph_path=root / "dataset.trig"),
                         FakeExtractor(response), store)
        self.assertEqual(len(set(store.get(names.target_graph).subjects(
            RDF.type, ONTO.Entity))), 0)
        self.assertGreater(len(store.get(names.review_graph)), 0)
        decision = next(iter(result.documents[0].publication_plan
                             .document_merge["identity_mapping"].values()))
        self.assertEqual(decision["status"], "review")


class AtomicFailureTest(unittest.TestCase):
    def test_injected_planning_failure_leaves_every_graph_unchanged(self):
        store = CountingStore()
        before = snapshot(store)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with mock.patch.object(
                    pipeline, "plan_graph_merge",
                    side_effect=RuntimeError("injected planning failure")):
                with self.assertRaisesRegex(RuntimeError, "planning failure"):
                    run(RunRequest(source=source,
                                   graph_path=root / "dataset.trig"),
                        FakeExtractor(package(["Acme Corp"])), store)
        self.assertEqual(store.publish_calls, 0)
        self.assertEqual(snapshot(store), before)

    def test_injected_serialization_failure_keeps_file_and_memory(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "dataset.trig"
            store = CountingStore(path)
            existing = Graph()
            existing.add((URIRef("urn:existing"), RDFS.label, Literal("kept")))
            store.put(names.target_graph, existing)
            store.publish()
            store.publish_calls = 0
            before_file = path.read_bytes()
            before_memory = snapshot(store)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with mock.patch.object(
                    graph_store_module, "_atomic_write",
                    side_effect=OSError("injected serialization failure")):
                with self.assertRaisesRegex(OSError, "serialization failure"):
                    run(RunRequest(source=source, graph_path=path),
                        FakeExtractor(package(["Acme Corp"])), store)
            self.assertEqual(path.read_bytes(), before_file)
            self.assertEqual(snapshot(store), before_memory)

    def test_injected_publication_failure_leaves_every_graph_unchanged(self):
        names = GraphNames()
        store = CountingStore()
        existing = Graph()
        existing.add((URIRef("urn:existing"), RDFS.label, Literal("kept")))
        store.put(names.target_graph, existing)
        before = snapshot(store)
        store.fail_publication = True
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with self.assertRaisesRegex(OSError, "publication failure"):
                run(RunRequest(source=source,
                               graph_path=root / "dataset.trig"),
                    FakeExtractor(package(["Acme Corp"])), store)
        self.assertEqual(snapshot(store), before)
        self.assertIn((URIRef("urn:existing"), RDFS.label, Literal("kept")),
                      store.get(names.target_graph))


if __name__ == "__main__":
    unittest.main()
