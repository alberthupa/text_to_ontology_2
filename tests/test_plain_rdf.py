"""A plain RDF file is refused, never silently emptied; ttl_to_trig converts it."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


from text_to_ontology.graph_store import GraphNames, PlainRdfError, RdflibGraphStore
from text_to_ontology.operations import call
from text_to_ontology.pipeline import MergeConfig, RunRequest, run_text_to_graph
from text_to_ontology.run_report import RunReporter
from text_to_ontology.vocabulary import read_vocabulary
from text_to_ontology.workspace import Workspace

PLAIN = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix ex:   <https://example.org/vocab#> .
@prefix a:    <https://example.org/asset/> .

ex:DataAsset a owl:Class ; rdfs:label "Data asset" .
ex:Process a owl:Class ; rdfs:label "Process" .
ex:feeds a owl:ObjectProperty ; rdfs:label "Feeds" ;
    rdfs:domain ex:DataAsset ; rdfs:range ex:Process .
a:sales a ex:DataAsset ; rdfs:label "Sales table" ; ex:feeds a:billing .
a:billing a ex:Process ; rdfs:label "Billing" .
"""

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "ttl_to_trig", ROOT / "ttl_to_trig.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fake:
    def model(self):
        return "fake"

    def extract(self, prompt):
        return {"entities": [], "relations": [], "facts": []}


class Base(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.plain = self.base / "ontology.trig"
        self.plain.write_text(PLAIN, encoding="utf-8")
        self.before = self.plain.read_bytes()
        self.note = self.base / "note.txt"
        self.note.write_text("Sales table feeds billing.", encoding="utf-8")


class GuardTest(Base):
    def test_ingestion_refuses_and_leaves_the_file_alone(self):
        with self.assertRaises(PlainRdfError) as caught:
            run_text_to_graph(
                RunRequest(source=self.note, graph_path=self.plain,
                           merge=MergeConfig(require_declared_vocabulary=True)),
                extractor=Fake(), reporter=RunReporter(stream=io.StringIO()))
        self.assertIn("ttl_to_trig.py", str(caught.exception))
        self.assertEqual(self.plain.read_bytes(), self.before)

    def test_the_studio_says_why_and_refuses_to_change_it(self):
        workspace = Workspace(graph_path=self.plain,
                              sources_dir=self.base / "inbox")
        status = call(workspace, "status", {})
        self.assertIn("plain RDF file", status["error"])
        with self.assertRaises(PlainRdfError):
            call(workspace, "dataset", {})
        with self.assertRaises(PlainRdfError):
            workspace.ingest([("note.txt", "Sales table feeds billing.")],
                             io.StringIO())
        with self.assertRaises(PlainRdfError):
            workspace.edit_preview("<https://x/a> <https://x/b> <https://x/c> .")
        self.assertFalse(workspace.chat_ask("what feeds billing?")["ok"])
        self.assertEqual(self.plain.read_bytes(), self.before)

    def test_a_proper_dataset_has_no_error(self):
        converted = self.base / "converted.trig"
        with redirect_stdout(io.StringIO()):
            load_script().main([str(self.plain), str(converted)])
        workspace = Workspace(graph_path=converted,
                              sources_dir=self.base / "inbox")
        self.assertIsNone(call(workspace, "status", {})["error"])


class ScriptTest(Base):
    def run_script(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = load_script().main([str(arg) for arg in args])
        return code, out.getvalue() + err.getvalue()

    def roles(self, path):
        names = GraphNames()
        store = RdflibGraphStore(path=path)
        return {"schema": store.get(names.schema_graphs[0]),
                "data": store.get(names.target_graph)}

    def test_classes_go_to_schema_and_individuals_to_data(self):
        output = self.base / "out.trig"
        code, text = self.run_script(self.plain, output)
        self.assertEqual(code, 0, text)
        roles = self.roles(output)
        vocabulary = read_vocabulary(roles["schema"])
        self.assertEqual(vocabulary.class_names, ["Data asset", "Process"])
        self.assertEqual(vocabulary.relation_names, ["Feeds"])
        labels = {str(label) for label in roles["data"].objects()}
        self.assertIn("Sales table", labels)
        self.assertNotIn("Data asset", labels)

    def test_a_trig_and_a_ttl_source_split_the_same_way(self):
        ttl = self.base / "same.ttl"
        ttl.write_text(PLAIN, encoding="utf-8")
        self.run_script(self.plain, self.base / "from_trig.trig")
        self.run_script(ttl, self.base / "from_ttl.trig")
        from_trig = self.roles(self.base / "from_trig.trig")
        from_ttl = self.roles(self.base / "from_ttl.trig")
        self.assertEqual(set(from_trig["data"]), set(from_ttl["data"]))
        self.assertEqual(set(from_trig["schema"]), set(from_ttl["schema"]))

    def test_an_existing_output_needs_force(self):
        output = self.base / "out.trig"
        output.write_text("keep me", encoding="utf-8")
        code, text = self.run_script(self.plain, output)
        self.assertEqual(code, 1)
        self.assertIn("--force", text)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep me")
        code, _ = self.run_script(self.plain, output, "--force")
        self.assertEqual(code, 0)
        self.assertTrue(len(self.roles(output)["schema"]))

    def test_a_refused_source_never_costs_the_existing_output(self):
        output = self.base / "out.trig"
        output.write_text("keep me", encoding="utf-8")
        empty = self.base / "no_vocabulary.ttl"
        empty.write_text("<https://x/a> <https://x/b> <https://x/c> .",
                         encoding="utf-8")
        code, text = self.run_script(empty, output, "--force")
        self.assertEqual(code, 1)
        self.assertIn("declares no classes", text)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_the_source_is_never_the_output(self):
        code, _ = self.run_script(self.plain, self.plain, "--force")
        self.assertEqual(code, 1)
        self.assertEqual(self.plain.read_bytes(), self.before)


GLOSSARY = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix ex:   <https://example.org/vocab#> .
@prefix g:    <https://example.org/glossary/> .

ex:Domain a owl:Class ; rdfs:label "Domain" .
g:contract a skos:Concept ; skos:prefLabel "Contract"@en ;
    dct:description "A commercial agreement."@en .
g:nda a skos:Concept ; skos:prefLabel "Non-Disclosure Agreement"@en ;
    skos:definition "Keeps things secret."@en ; skos:broader g:contract .
"""


class ConceptsAsClassesTest(Base):
    def convert(self, *extra):
        source = self.base / "glossary.ttl"
        source.write_text(GLOSSARY, encoding="utf-8")
        output = self.base / "glossary.trig"
        with redirect_stdout(io.StringIO()):
            code = load_script().main([str(source), str(output), *extra])
        self.assertEqual(code, 0)
        store = RdflibGraphStore(path=output)
        return store.get(GraphNames().schema_graphs[0])

    def test_without_the_option_concepts_are_not_classes(self):
        self.assertEqual(read_vocabulary(self.convert()).class_names,
                         ["Domain"])

    def test_concepts_become_named_described_classes_with_hierarchy(self):
        from rdflib import Literal, URIRef
        from rdflib.namespace import RDFS
        schema = self.convert("--concepts-as-classes")
        vocabulary = read_vocabulary(schema)
        self.assertEqual(vocabulary.class_names,
                         ["Contract", "Domain", "Non-Disclosure Agreement"])
        nda = URIRef("https://example.org/glossary/nda")
        contract = URIRef("https://example.org/glossary/contract")
        self.assertIn((nda, RDFS.subClassOf, contract), schema)
        self.assertTrue(vocabulary.is_a(nda, contract))
        self.assertEqual(schema.value(contract, RDFS.comment),
                         Literal("A commercial agreement.", lang="en"))
        self.assertEqual(schema.value(nda, RDFS.comment),
                         Literal("Keeps things secret.", lang="en"))

    def test_a_concept_class_can_be_an_extracted_kind(self):
        from text_to_ontology.candidate_validation import validate_candidates
        schema = self.convert("--concepts-as-classes")
        result = validate_candidates(
            {"entities": [{"id": "e1", "name": "MSA 2026", "kind": "Contract",
                           "confidence": 0.9}], "relations": [], "facts": []},
            schema, (), vocabulary=read_vocabulary(schema))
        self.assertTrue(result["valid"], result["issues"])

    def test_without_a_root_class_the_rule_says_leave_it_out(self):
        from text_to_ontology.schema_context import render_core_schema
        text = render_core_schema(self.convert("--concepts-as-classes"))
        self.assertIn("Leave out anything no class fits.", text)
        self.assertNotIn('Use "Entity"', text)


if __name__ == "__main__":
    unittest.main()
