"""Importing an RDF/Turtle/TriG file as the starter ontology."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from text_to_ontology.graph_management import CLASS, ENTITY
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.operations import call
from text_to_ontology.prompts import PromptLibrary
from text_to_ontology.starter import (
    RDF_SUFFIXES, import_publication, import_starter, import_summary,
    looks_like_rdf, parse_rdf,
)
from text_to_ontology.vocabulary import read_vocabulary
from text_to_ontology.workspace import Workspace


EX = Namespace("http://example.org/bikes#")
LIB = Namespace("http://example.org/lib#")

TURTLE = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/bikes#> .
ex: a owl:Ontology ; rdfs:label "Bike shop" .
ex:Bike a owl:Class ; rdfs:label "Bike" .
ex:Brand a owl:Class ; rdfs:label "Brand" .
ex:made-by a owl:ObjectProperty ; rdfs:label "made by" ;
    rdfs:domain ex:Bike ; rdfs:range ex:Brand .
ex:model-name a owl:DatatypeProperty ; rdfs:label "model name" .
ex:krossBrand a ex:Brand ; rdfs:label "Kross" .
ex:kross a ex:Bike ; rdfs:label "Kross Level" ; ex:made-by ex:krossBrand .
"""

TRIG_ROLES = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/lib#> .
<http://example.org/text-ontology/graphs/schema> {
  ex:Tool a owl:Class ; rdfs:label "Tool" .
  ex:borrowed-by a owl:ObjectProperty ; rdfs:label "borrowed by" .
}
<http://example.org/text-ontology/graphs/data> {
  ex:drill a ex:Tool ; rdfs:label "Drill" .
}
<http://example.org/other/graph> {
  ex:extra a ex:Tool ; rdfs:label "Extra" .
}
"""


class LooksLikeRdfTest(unittest.TestCase):
    def test_a_known_suffix_is_rdf(self):
        for suffix in RDF_SUFFIXES:
            self.assertTrue(looks_like_rdf("thing" + suffix, "whatever"), suffix)

    def test_content_is_sniffed_when_the_suffix_says_nothing(self):
        self.assertTrue(looks_like_rdf("notes.txt", TURTLE))
        self.assertTrue(looks_like_rdf("notes.txt", "PREFIX owl: <x>\nSELECT * {}"))
        self.assertTrue(looks_like_rdf(
            "notes.txt", '<?xml version="1.0"?><rdf:RDF xmlns:rdf="x"/>'))

    def test_prose_is_not_rdf(self):
        self.assertFalse(looks_like_rdf("notes.txt", "We roast coffee."))
        self.assertFalse(looks_like_rdf("notes.md", ""))
        self.assertFalse(looks_like_rdf("notes.md", "# a heading\n\nsome text"))


class ParseRdfTest(unittest.TestCase):
    def test_a_suffix_is_used_as_a_hint(self):
        rdf_format, parsed = parse_rdf(TURTLE, "bikes.ttl")
        self.assertEqual(rdf_format, "turtle")
        self.assertEqual(len(list(parsed)), 17)

    def test_a_missing_suffix_is_discovered(self):
        rdf_format, _parsed = parse_rdf(TURTLE, "bikes")
        self.assertEqual(rdf_format, "turtle")

    def test_trig_keeps_its_named_graphs(self):
        rdf_format, parsed = parse_rdf(TRIG_ROLES, "roles.trig")
        self.assertEqual(rdf_format, "trig")
        self.assertTrue(hasattr(parsed, "contexts"))

    def test_nonsense_is_a_clear_error(self):
        with self.assertRaises(ValueError) as caught:
            parse_rdf("this is prose, not RDF", "notes.txt")
        self.assertIn("does not parse as RDF", str(caught.exception))
        self.assertIn("turtle", str(caught.exception))


class ImportPublicationTest(unittest.TestCase):
    def names(self):
        return GraphNames()

    def test_a_plain_ontology_is_partitioned_into_roles(self):
        publication, summary = import_publication(TURTLE, "bikes.ttl")
        names = self.names()
        self.assertEqual(summary["format"], "turtle")
        self.assertEqual(summary["classes"], ["Bike", "Brand"])
        self.assertEqual(summary["relations"], ["made by"])
        self.assertEqual(summary["facts"], ["model name"])
        schema = publication.graphs[names.schema_graphs[0]]
        data = publication.graphs[names.target_graph]
        # an imported ontology keeps its own IRIs; that is the point
        self.assertIn((EX.Bike, RDF.type, OWL.Class), schema)
        self.assertIn((EX["made-by"], RDFS.range, EX.Brand), schema)
        self.assertIn((EX["model-name"], RDF.type, OWL.DatatypeProperty), schema)
        # the individuals are data, and the ontology header is kept as support
        self.assertIn((EX.kross, RDF.type, EX.Bike), data)
        self.assertEqual(len(publication.graphs[names.review_graph]), 0)
        self.assertGreaterEqual(
            len(publication.graphs[names.provenance_graph]), 1)

    def test_our_own_named_graphs_are_imported_role_for_role(self):
        publication, summary = import_publication(TRIG_ROLES, "roles.trig")
        names = self.names()
        self.assertEqual(summary["format"], "trig")
        self.assertEqual(summary["classes"], ["Tool"])
        self.assertEqual(summary["relations"], ["borrowed by"])
        schema = publication.graphs[names.schema_graphs[0]]
        data = publication.graphs[names.target_graph]
        self.assertIn((LIB.Tool, RDF.type, OWL.Class), schema)
        self.assertIn((LIB.drill, RDF.type, LIB.Tool), data)
        # a named graph we do not own is kept as data, not dropped
        self.assertEqual(len(data), 4)

    def test_a_document_without_vocabulary_is_refused(self):
        only_individuals = """@prefix ex: <http://example.org/> .
ex:thing ex:note "just data" .
"""
        with self.assertRaises(ValueError) as caught:
            import_publication(only_individuals, "data.ttl")
        self.assertIn("no classes or properties", str(caught.exception))
        self.assertIn("1 triples", str(caught.exception))

    def test_the_summary_reads_well(self):
        _publication, summary = import_publication(TURTLE, "bikes.ttl")
        text = import_summary(summary)
        self.assertIn("turtle: 17 triples", text)
        self.assertIn("classes: Bike, Brand", text)
        self.assertIn("relations: made by", text)
        self.assertIn("facts: model name", text)


class ImportStarterFileTest(unittest.TestCase):
    def test_importing_writes_a_dataset_that_reads_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.trig"
            summary = import_starter(TURTLE, "bikes.ttl", graph_path=path)
            self.assertEqual(summary["classes"], ["Bike", "Brand"])
            reopened = RdflibGraphStore(path=path)
            vocabulary = read_vocabulary(
                reopened.get(GraphNames().schema_graphs[0]))
            self.assertEqual(vocabulary.class_names, ["Bike", "Brand"])
            self.assertEqual(vocabulary.relation_names, ["made by"])

    def test_a_bad_file_leaves_the_old_dataset_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.trig"
            import_starter(TURTLE, "bikes.ttl", graph_path=path)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                import_starter("not rdf at all", "notes.txt", graph_path=path)
            self.assertEqual(path.read_bytes(), before)


class ImportOperationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.workspace = Workspace(
            graph_path=self.base / "ontology.trig",
            sources_dir=self.base / "inbox",
            extractor=_NoModel("this must never be called"))

    def test_the_operation_answers_with_a_summary_and_a_status(self):
        answer = call(self.workspace, "starter.import",
                      {"name": "bikes.ttl", "text": TURTLE})
        self.assertTrue(answer["ok"], answer)
        self.assertIn("Imported bikes.ttl", answer["log"])
        self.assertEqual(answer["summary"]["classes"], ["Bike", "Brand"])
        self.assertTrue(answer["status"]["ready"])
        self.assertEqual(self.workspace.extractor.calls, 0)

    def test_an_empty_or_broken_file_is_reported(self):
        empty = call(self.workspace, "starter.import", {"name": "x.ttl", "text": ""})
        self.assertFalse(empty["ok"])
        self.assertIn("no RDF file content", empty["error"])
        broken = call(self.workspace, "starter.import",
                      {"name": "x.ttl", "text": "prose, not RDF"})
        self.assertFalse(broken["ok"])
        self.assertIn("does not parse as RDF", broken["error"])

    def test_importing_replaces_the_previous_dataset(self):
        call(self.workspace, "starter.import", {"name": "bikes.ttl", "text": TURTLE})
        other = TURTLE.replace("Bike", "Bicycle").replace("Kross", "Romet")
        answer = call(self.workspace, "starter.import",
                      {"name": "bikes2.ttl", "text": other})
        self.assertTrue(answer["ok"], answer)
        names = GraphNames()
        schema = self.workspace.store.get(names.schema_graphs[0])
        self.assertIn((EX.Bicycle, RDF.type, OWL.Class), schema)
        self.assertNotIn((EX.Bike, RDF.type, OWL.Class), schema)

    def test_an_imported_vocabulary_locks_ingestion(self):
        call(self.workspace, "starter.import", {"name": "bikes.ttl", "text": TURTLE})
        listed = call(self.workspace, "status", {})
        self.assertIn("Bike", listed["classes"])
        # the data-only gate reads this same vocabulary
        self.assertEqual(read_vocabulary(
            self.workspace.canonical_graph()).relation_names, ["made by"])


class LooksLikeRdfTest(unittest.TestCase):
    def test_a_known_suffix_is_rdf(self):
        for suffix in RDF_SUFFIXES:
            self.assertTrue(looks_like_rdf("thing" + suffix, "whatever"), suffix)

    def test_content_is_sniffed_when_the_suffix_says_nothing(self):
        self.assertTrue(looks_like_rdf("notes.txt", TURTLE))
        self.assertTrue(looks_like_rdf("notes.txt", "PREFIX owl: <x>\nSELECT * {}"))
        self.assertTrue(looks_like_rdf(
            "notes.txt", '<?xml version="1.0"?><rdf:RDF xmlns:rdf="x"/>'))

    def test_prose_is_not_rdf(self):
        self.assertFalse(looks_like_rdf("notes.txt", "We roast coffee."))
        self.assertFalse(looks_like_rdf("notes.md", ""))
        self.assertFalse(looks_like_rdf("notes.md", "# a heading\n\nsome text"))


class ParseRdfTest(unittest.TestCase):
    def test_a_suffix_is_used_as_a_hint(self):
        rdf_format, parsed = parse_rdf(TURTLE, "bikes.ttl")
        self.assertEqual(rdf_format, "turtle")
        self.assertEqual(len(list(parsed)), 17)

    def test_a_missing_suffix_is_discovered(self):
        rdf_format, _parsed = parse_rdf(TURTLE, "bikes")
        self.assertEqual(rdf_format, "turtle")

    def test_trig_keeps_its_named_graphs(self):
        rdf_format, parsed = parse_rdf(TRIG_ROLES, "roles.trig")
        self.assertEqual(rdf_format, "trig")
        self.assertTrue(hasattr(parsed, "contexts"))

    def test_nonsense_is_a_clear_error(self):
        with self.assertRaises(ValueError) as caught:
            parse_rdf("this is prose, not RDF", "notes.txt")
        self.assertIn("does not parse as RDF", str(caught.exception))
        self.assertIn("turtle", str(caught.exception))


class ImportPublicationTest(unittest.TestCase):
    def names(self):
        return GraphNames()

    def test_a_plain_ontology_is_partitioned_into_roles(self):
        publication, summary = import_publication(TURTLE, "bikes.ttl")
        names = self.names()
        self.assertEqual(summary["format"], "turtle")
        self.assertEqual(summary["classes"], ["Bike", "Brand"])
        self.assertEqual(summary["relations"], ["made by"])
        self.assertEqual(summary["facts"], ["model name"])
        schema = publication.graphs[names.schema_graphs[0]]
        data = publication.graphs[names.target_graph]
        # an imported ontology keeps its own IRIs; that is the point
        self.assertIn((EX.Bike, RDF.type, OWL.Class), schema)
        self.assertIn((EX["made-by"], RDFS.range, EX.Brand), schema)
        self.assertIn((EX["model-name"], RDF.type, OWL.DatatypeProperty), schema)
        # the individuals are data, and the ontology header is kept as support
        self.assertIn((EX.kross, RDF.type, EX.Bike), data)
        self.assertEqual(len(publication.graphs[names.review_graph]), 0)
        self.assertGreaterEqual(
            len(publication.graphs[names.provenance_graph]), 1)

    def test_our_own_named_graphs_are_imported_role_for_role(self):
        publication, summary = import_publication(TRIG_ROLES, "roles.trig")
        names = self.names()
        self.assertEqual(summary["format"], "trig")
        self.assertEqual(summary["classes"], ["Tool"])
        self.assertEqual(summary["relations"], ["borrowed by"])
        schema = publication.graphs[names.schema_graphs[0]]
        data = publication.graphs[names.target_graph]
        self.assertIn((LIB.Tool, RDF.type, OWL.Class), schema)
        self.assertIn((LIB.drill, RDF.type, LIB.Tool), data)
        # a named graph we do not own is kept as data, not dropped
        self.assertEqual(len(data), 4)

    def test_a_document_without_vocabulary_is_refused(self):
        only_individuals = """@prefix ex: <http://example.org/> .
ex:thing ex:note "just data" .
"""
        with self.assertRaises(ValueError) as caught:
            import_publication(only_individuals, "data.ttl")
        self.assertIn("no classes or properties", str(caught.exception))
        self.assertIn("1 triples", str(caught.exception))

    def test_the_summary_reads_well(self):
        _publication, summary = import_publication(TURTLE, "bikes.ttl")
        text = import_summary(summary)
        self.assertIn("turtle: 17 triples", text)
        self.assertIn("classes: Bike, Brand", text)
        self.assertIn("relations: made by", text)
        self.assertIn("facts: model name", text)


class ImportStarterFileTest(unittest.TestCase):
    def test_importing_writes_a_dataset_that_reads_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.trig"
            summary = import_starter(TURTLE, "bikes.ttl", graph_path=path)
            self.assertEqual(summary["classes"], ["Bike", "Brand"])
            reopened = RdflibGraphStore(path=path)
            vocabulary = read_vocabulary(
                reopened.get(GraphNames().schema_graphs[0]))
            self.assertEqual(vocabulary.class_names, ["Bike", "Brand"])
            self.assertEqual(vocabulary.relation_names, ["made by"])

    def test_a_bad_file_leaves_the_old_dataset_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.trig"
            import_starter(TURTLE, "bikes.ttl", graph_path=path)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                import_starter("not rdf at all", "notes.txt", graph_path=path)
            self.assertEqual(path.read_bytes(), before)


class ImportOperationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.workspace = Workspace(
            graph_path=self.base / "ontology.trig",
            sources_dir=self.base / "inbox",
            extractor=_NoModel("this must never be called"))

    def test_the_operation_answers_with_a_summary_and_a_status(self):
        answer = call(self.workspace, "starter.import",
                      {"name": "bikes.ttl", "text": TURTLE})
        self.assertTrue(answer["ok"], answer)
        self.assertIn("Imported bikes.ttl", answer["log"])
        self.assertEqual(answer["summary"]["classes"], ["Bike", "Brand"])
        self.assertTrue(answer["status"]["ready"])
        self.assertEqual(self.workspace.extractor.calls, 0)

    def test_an_empty_or_broken_file_is_reported(self):
        empty = call(self.workspace, "starter.import", {"name": "x.ttl", "text": ""})
        self.assertFalse(empty["ok"])
        self.assertIn("no RDF file content", empty["error"])
        broken = call(self.workspace, "starter.import",
                      {"name": "x.ttl", "text": "prose, not RDF"})
        self.assertFalse(broken["ok"])
        self.assertIn("does not parse as RDF", broken["error"])

    def test_importing_replaces_the_previous_dataset(self):
        call(self.workspace, "starter.import", {"name": "bikes.ttl", "text": TURTLE})
        other = TURTLE.replace("Bike", "Bicycle").replace("Kross", "Romet")
        answer = call(self.workspace, "starter.import",
                      {"name": "bikes2.ttl", "text": other})
        self.assertTrue(answer["ok"], answer)
        names = GraphNames()
        schema = self.workspace.store.get(names.schema_graphs[0])
        self.assertIn((EX.Bicycle, RDF.type, OWL.Class), schema)
        self.assertNotIn((EX.Bike, RDF.type, OWL.Class), schema)

    def test_an_imported_vocabulary_locks_ingestion(self):
        call(self.workspace, "starter.import", {"name": "bikes.ttl", "text": TURTLE})
        listed = call(self.workspace, "status", {})
        self.assertIn("Bike", listed["classes"])
        # the data-only gate reads this same vocabulary
        self.assertEqual(read_vocabulary(
            self.workspace.canonical_graph()).relation_names, ["made by"])


class ImportThenIngestTest(unittest.TestCase):
    """An imported vocabulary is usable: ingestion follows its IRIs."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.graph = self.base / "ontology.trig"
        self.source = self.base / "note.txt"
        self.source.write_text("Kross Level was made by Kross.",
                               encoding="utf-8")
        self.extractor = _ScriptedExtractor({
            "entities": [{"id": "e1", "name": "Kross Level", "kind": "Bike",
                          "confidence": 0.9},
                         {"id": "e2", "name": "Kross", "kind": "Brand",
                          "confidence": 0.9}],
            "relations": [{"subject": "e1", "predicate": "made by",
                           "object": "e2", "confidence": 0.9}],
            "facts": [],
        })
        self.workspace = Workspace(
            graph_path=self.graph, sources_dir=self.base / "inbox",
            extractor=self.extractor)

    def test_data_only_ingestion_uses_the_imported_iris(self):
        from text_to_ontology.pipeline import MergeConfig, RunRequest, \
            run_text_to_graph
        from text_to_ontology.run_report import RunReporter

        imported = call(self.workspace, "starter.import",
                        {"name": "bikes.ttl", "text": TURTLE})
        self.assertTrue(imported["ok"], imported)
        names = GraphNames()
        schema_before = set(self.workspace.store.get(names.schema_graphs[0]))

        run_text_to_graph(
            RunRequest(source=self.source, graph_path=self.graph,
                       merge=MergeConfig(require_declared_vocabulary=True),
                       prompts=PromptLibrary(self.base / "prompts.local.json")),
            graph_store=self.workspace.store, extractor=self.extractor,
            reporter=RunReporter())

        data = self.workspace.store.get(names.target_graph)
        # individuals stay in the project's entity namespace; the imported
        # vocabulary supplies the class and the predicate
        self.assertIn((ENTITY["kross-level"], RDF.type, EX.Bike), data)
        self.assertIn((ENTITY["kross-level"], EX["made-by"], ENTITY["kross"]),
                      data)
        # the imported schema is untouched: no class:* twins appeared
        self.assertEqual(set(self.workspace.store.get(names.schema_graphs[0])),
                         schema_before)
        self.assertFalse(any(str(subject).startswith(str(CLASS))
                             for subject in data.subjects(RDF.type, OWL.Class)))


class _ScriptedExtractor:
    def __init__(self, answer):
        self.answer = answer

    def model(self):
        return "scripted"

    def extract(self, prompt):
        return self.answer


class _NoModel:
    """An extractor that fails loudly if an import ever asks a model."""

    def __init__(self, message):
        self.message = message
        self.calls = 0

    def model(self):
        return "no-model"

    def extract(self, prompt):
        self.calls += 1
        raise AssertionError(self.message)


if __name__ == "__main__":
    unittest.main()
