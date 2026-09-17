"""Source summaries survive publication, duplication, and rejected claims."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import OWL, PROV, RDF, RDFS

from text_to_ontology.api import RunRequest
from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
from text_to_ontology.graph_partition import partition_graph
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from tests.test_pipeline_m7 import CountingStore, FakeExtractor, entity, run


def response(confidence=0.9):
    return {
        "entities": [entity("a", "Alice", "Person"),
                     entity("b", "Acme", "Company")],
        "relations": [{"subject": "a", "predicate": "works for",
                       "object": "b", "confidence": confidence}],
        "facts": [{"subject": "a", "predicate": "age", "value": 30,
                   "confidence": confidence}],
    }


def canonical_statements(graph, triple):
    return {s for s in graph.subjects(RDF.subject, triple[0])
            if str(s).startswith(str(ONTO) + "statement/")
            and (s, RDF.predicate, triple[1]) in graph
            and (s, RDF.object, triple[2]) in graph}


class SourcePublicationTest(unittest.TestCase):
    def test_sources_accumulate_on_resources_and_exact_statements_after_reload(self):
        names = GraphNames()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "out.trig"
            store = CountingStore(path)
            for number, confidence in ((1, 0.9), (2, 0.7)):
                source = root / f"{number}.txt"
                source.write_text(f"Source {number}: Alice works for Acme.")
                run(RunRequest(source=source, graph_path=path),
                    FakeExtractor(response(confidence)), store)
            graph = RdflibGraphStore(path).get(names.provenance_graph)
        documents = set(graph.objects(ENTITY.alice, ONTO.sourceDocument))
        self.assertEqual(len(documents), 2)
        self.assertEqual({str(v) for d in documents
                          for v in graph.objects(d, RDFS.label)},
                         {"1.txt", "2.txt"})
        for resource in (ENTITY.acme, CLASS.person, CLASS.company,
                         RELATION["works-for"], FACT.age):
            self.assertEqual(set(graph.objects(resource, ONTO.sourceDocument)),
                             documents)
            self.assertEqual(len(set(graph.objects(resource, ONTO.sourceFile))), 2)
        for triple in ((ENTITY.alice, RELATION["works-for"], ENTITY.acme),
                       (ENTITY.alice, FACT.age, Literal(30)),
                       (CLASS.person, RDF.type, OWL.Class)):
            statements = canonical_statements(graph, triple)
            self.assertEqual(len(statements), 1)
            statement = next(iter(statements))
            self.assertEqual(set(graph.objects(statement, PROV.wasDerivedFrom)),
                             documents)
            self.assertEqual(len(set(graph.objects(statement, ONTO.sourceFile))), 2)
        self.assertFalse(list(graph.objects(ONTO.Entity, ONTO.sourceDocument)))
        self.assertFalse(canonical_statements(graph, (ONTO.Entity, RDF.type, OWL.Class)))

    def test_same_content_and_filename_in_different_folders_keeps_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CountingStore()
            paths = [root / part / "notes.txt" for part in ("a", "b")]
            for path in paths:
                path.parent.mkdir()
                path.write_text("Alice works for Acme.")
                run(RunRequest(source=path, graph_path=root / "out.trig"),
                    FakeExtractor(response()), store)
            graph = store.get(GraphNames().provenance_graph)
            files = set(graph.objects(ENTITY.alice, ONTO.sourceFile))
            self.assertEqual(len(files), 2)
            self.assertEqual({str(graph.value(f, ONTO.sourcePath)) for f in files},
                             {p.as_posix() for p in paths})
        documents = set(graph.objects(ENTITY.alice, ONTO.sourceDocument))
        self.assertEqual(len(documents), 1)
        self.assertEqual(set(graph.objects(next(iter(documents)), ONTO.sourceFile)), files)
        for file in files:
            self.assertEqual(graph.value(file, RDFS.label), Literal("notes.txt"))

    def test_rejected_claims_have_evidence_but_do_not_support_canonical_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CountingStore()
            for number in (1, 2):
                source = root / f"{number}.txt"
                source.write_text(f"Source {number} about Alice.")
                package = response()
                if number == 2:
                    package["relations"][0]["confidence"] = 0.2
                    package["relations"][0]["predicate"] = "might join"
                    package["facts"][0].update(value=99, confidence=0.2)
                    package["entities"].append(entity("c", "Uncertain", "Risk", 0.2))
                run(RunRequest(source=source, graph_path=root / "out.trig"),
                    FakeExtractor(package), store)
        graph = store.get(GraphNames().provenance_graph)
        self.assertEqual(len(set(graph.objects(ENTITY.alice, ONTO.sourceDocument))), 2)
        self.assertEqual(len(set(graph.objects(FACT.age, ONTO.sourceDocument))), 1)
        self.assertFalse(list(graph.objects(RELATION["might-join"], ONTO.sourceDocument)))
        self.assertFalse(list(graph.objects(CLASS.risk, ONTO.sourceDocument)))
        self.assertFalse(canonical_statements(graph, (ENTITY.alice, FACT.age, Literal(99))))
        review = store.get(GraphNames().review_graph)
        statements = list(review.subjects(RDF.type, RDF.Statement))
        self.assertTrue(statements)
        for statement in statements:
            self.assertTrue(list(review.objects(statement, PROV.wasDerivedFrom)))
            self.assertTrue(list(review.objects(statement, ONTO.sourceFile)))

    def test_source_links_stay_in_support_when_graphs_are_combined(self):
        from rdflib import Graph
        graph = Graph()
        graph.add((ENTITY.alice, RDF.type, ONTO.Entity))
        graph.add((ONTO.Entity, RDF.type, OWL.Class))
        link = (ENTITY.alice, ONTO.sourceDocument, ONTO["document/test"])
        graph.add(link)
        schema, instance, support = partition_graph(graph)
        self.assertIn(link, support)
        self.assertNotIn(link, instance)
        self.assertNotIn(link, schema)

    def test_changed_file_keeps_versions_without_supporting_old_or_rejected_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            store = CountingStore()
            for number, description in ((1, "First description"),
                                        (2, "Conflicting description")):
                source.write_text(f"Version {number} about Alice.")
                package = response()
                package["entities"][0]["description"] = description
                if number == 2:
                    package["facts"] = []
                run(RunRequest(source=source, graph_path=root / "out.trig"),
                    FakeExtractor(package), store)
        graph = store.get(GraphNames().provenance_graph)
        self.assertEqual(len(set(graph.objects(ENTITY.alice, ONTO.sourceDocument))), 2)
        files = set(graph.objects(ENTITY.alice, ONTO.sourceFile))
        self.assertEqual(len(files), 2)
        self.assertEqual(len({graph.value(f, ONTO.sourcePath) for f in files}), 1)
        for triple in ((ENTITY.alice, FACT.age, Literal(30)),
                       (ENTITY.alice, RDFS.comment, Literal("First description"))):
            statement = next(iter(canonical_statements(graph, triple)))
            self.assertEqual(len(set(graph.objects(statement, PROV.wasDerivedFrom))), 1)
        self.assertFalse(canonical_statements(
            graph, (ENTITY.alice, RDFS.comment, Literal("Conflicting description"))))
