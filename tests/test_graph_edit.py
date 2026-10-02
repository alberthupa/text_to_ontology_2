"""Editing the graph: patch parsing, checks, preview, apply, and evidence."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, PROV, RDF, RDFS, SH, SKOS

from text_to_ontology import graph_edit
from text_to_ontology.graph_edit import (
    Patch, fenced_turtle, parse_patch, preview, provenance_for, publication,
    statement_uri,
)
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.operations import call
from text_to_ontology.publication_sources import materialize_sources
from text_to_ontology.workspace import Workspace

EX = Namespace("http://example.org/lib#")
PREFIXES = """@prefix ex: <http://example.org/lib#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
"""


def library_graph():
    graph = Graph()
    graph.add((EX.Tool, RDF.type, OWL.Class))
    graph.add((EX.Tool, RDFS.label, Literal("Tool")))
    graph.add((EX.serial, RDF.type, OWL.DatatypeProperty))
    graph.add((EX.serial, RDFS.label, Literal("serial")))
    graph.add((EX.drill, RDF.type, EX.Tool))
    graph.add((EX.drill, RDFS.label, Literal("Drill")))
    graph.add((EX.drill, EX.serial, Literal("1234")))
    return graph


def shape_graph():
    graph = Graph()
    node = EX.ToolShape
    graph.add((node, RDF.type, SH.NodeShape))
    graph.add((node, SH.targetClass, EX.Tool))
    rule = EX.toolRule
    graph.add((node, SH.property, rule))
    graph.add((rule, SH.path, RDFS.label))
    graph.add((rule, SH.minCount, Literal(1)))
    return graph


class ParsePatchTest(unittest.TestCase):
    def test_additions_and_removals_are_separated(self):
        added, removed, errors = parse_patch(PREFIXES + """
# a comment
ex:saw a ex:Tool ;
    skos:prefLabel "Saw" .
- ex:drill skos:prefLabel "Drill" .
""")
        self.assertEqual(errors, ())
        self.assertEqual(len(added), 2)
        self.assertEqual(removed,
                         ((EX.drill, SKOS.prefLabel, Literal("Drill")),))

    def test_prefixes_are_shared_with_removals(self):
        _added, removed, errors = parse_patch(
            PREFIXES + "- ex:drill ex:serial \"1234\" .\n")
        self.assertEqual(errors, ())
        self.assertEqual(removed, ((EX.drill, EX.serial, Literal("1234")),))

    def test_a_removal_without_a_full_stop_is_still_read(self):
        _added, removed, errors = parse_patch(PREFIXES + "- ex:drill skos:prefLabel \"Drill\"\n")
        self.assertEqual(errors, ())
        self.assertEqual(len(removed), 1)

    def test_comments_and_blank_lines_are_ignored(self):
        added, removed, errors = parse_patch("# nothing here\n\n")
        self.assertEqual((added, removed, errors), ((), (), ()))

    def test_a_broken_addition_is_reported(self):
        _added, _removed, errors = parse_patch(PREFIXES + "ex:saw a ex:Tool\n")
        self.assertTrue(errors)
        self.assertIn("does not parse", errors[0])

    def test_a_broken_removal_is_reported(self):
        _added, _removed, errors = parse_patch(PREFIXES + "- ex:saw a\n")
        self.assertTrue(errors)
        self.assertIn("removal", errors[0])


class FencedTurtleTest(unittest.TestCase):
    def test_one_block_is_found(self):
        blocks = fenced_turtle('Sure:\n```turtle\nex:saw a ex:Tool .\n```\nDone.')
        self.assertEqual(blocks, ["ex:saw a ex:Tool ."])

    def test_several_blocks_and_other_languages(self):
        text = "```turtle\nex:a ex:b ex:c .\n```\nand\n```trig\nex:d ex:e ex:f .\n```\n```json\n{}\n```"
        blocks = fenced_turtle(text)
        self.assertEqual(len(blocks), 2)
        self.assertIn("ex:a", blocks[0])
        self.assertIn("ex:d", blocks[1])

    def test_no_block_is_no_block(self):
        self.assertEqual(fenced_turtle("just prose"), [])
        self.assertEqual(fenced_turtle("```\n\n```"), [])


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.graph = library_graph()

    def good(self):
        return PREFIXES + 'ex:saw a ex:Tool ; skos:prefLabel "Saw" .\n'

    def test_a_good_patch_is_ok_with_a_stable_id(self):
        patch = preview(self.graph, self.good())
        self.assertIsInstance(patch, Patch)
        self.assertTrue(patch.ok, patch.errors)
        self.assertEqual(patch.counts()["added"], 2)
        self.assertEqual(patch.patch_id, preview(self.graph, self.good()).patch_id)
        self.assertNotEqual(patch.patch_id,
                            preview(self.graph, self.good(),
                                    allow_new_vocabulary=True).patch_id)

    def test_the_sample_shows_both_sides(self):
        patch = preview(self.graph, PREFIXES + """
ex:saw a ex:Tool .
- ex:drill ex:serial "1234" .
""")
        sample = patch.sample()
        self.assertTrue(any("saw" in line for line in sample["added"]))
        self.assertTrue(any("1234" in line for line in sample["removed"]))

    def test_a_new_class_is_refused_while_the_vocabulary_is_frozen(self):
        patch = preview(self.graph, PREFIXES + "ex:Brand a owl:Class .\n")
        self.assertFalse(patch.ok)
        self.assertIn("allow new classes", patch.errors[0])

    def test_a_new_class_is_allowed_with_the_toggle(self):
        patch = preview(self.graph, PREFIXES + "ex:Brand a owl:Class .\n",
                        allow_new_vocabulary=True)
        self.assertTrue(patch.ok, patch.errors)
        self.assertEqual(patch.counts()["added"], 1)

    def test_an_undeclared_property_is_refused_while_frozen(self):
        patch = preview(self.graph,
                        PREFIXES + "ex:drill ex:made-by ex:bosch .\n")
        self.assertFalse(patch.ok)
        self.assertIn("made-by", patch.errors[0])

    def test_an_undeclared_property_is_a_warning_when_open(self):
        patch = preview(self.graph,
                        PREFIXES + "ex:drill ex:made-by ex:bosch .\n",
                        allow_new_vocabulary=True)
        self.assertTrue(patch.ok, patch.errors)
        self.assertTrue(any("nothing declares" in line for line in patch.warnings))

    def test_a_statement_using_a_declared_property_is_fine(self):
        patch = preview(self.graph, PREFIXES + 'ex:drill ex:serial "5678" .\n')
        self.assertTrue(patch.ok, patch.errors)

    def test_a_removal_of_something_absent_is_a_warning(self):
        patch = preview(self.graph, PREFIXES + '- ex:saw skos:prefLabel "Saw" .\n')
        self.assertTrue(patch.ok, patch.errors)
        self.assertTrue(any("not in the graph" in line for line in patch.warnings))

    def test_an_iri_cannot_become_both_a_class_and_a_property(self):
        patch = preview(self.graph, PREFIXES + "ex:Thing a owl:Class .\n"
                        "ex:Thing a owl:ObjectProperty .\n",
                        allow_new_vocabulary=True)
        self.assertFalse(patch.ok)
        self.assertIn("both a class and a property", patch.errors[-1])

    def test_shacl_violations_are_warnings_not_errors(self):
        patch = preview(self.graph, PREFIXES + "ex:hammer a ex:Tool .\n",
                        shapes=(shape_graph(),))
        self.assertTrue(patch.ok, patch.errors)
        self.assertTrue(any("SHACL violation" in line for line in patch.warnings))

    def test_a_parse_error_is_an_error_with_its_id(self):
        patch = preview(self.graph, PREFIXES + "ex:saw a\n")
        self.assertFalse(patch.ok)
        self.assertTrue(patch.patch_id)


class ProvenanceTest(unittest.TestCase):
    def test_the_statement_iri_matches_the_publishing_convention(self):
        triple = (EX.drill, EX.serial, Literal("1234"))
        self.assertEqual(statement_uri(triple),
                         materialize_statement_uri(triple))

    def test_one_activity_and_one_record_per_triple(self):
        patch = preview(library_graph(),
                        PREFIXES + 'ex:saw a ex:Tool .\n'
                        '- ex:drill ex:serial "1234" .\n')
        edit_iri, evidence = provenance_for(patch)
        self.assertIn((edit_iri, RDF.type, PROV.Activity), evidence)
        self.assertIn((edit_iri, RDFS.label, Literal("manual edit")), evidence)
        self.assertEqual(len(list(evidence.subjects(RDF.type, RDF.Statement))), 2)
        self.assertTrue(any(evidence.triples(
            (None, PROV.wasGeneratedBy, edit_iri))))
        self.assertTrue(any(evidence.triples(
            (None, PROV.wasInvalidatedBy, edit_iri))))

    def test_the_edit_id_is_deterministic(self):
        patch = preview(library_graph(), PREFIXES + "ex:saw a ex:Tool .\n")
        first = provenance_for(patch)[0]
        second = provenance_for(preview(library_graph(),
                                        PREFIXES + "ex:saw a ex:Tool .\n"))[0]
        self.assertEqual(first, second)


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.names = GraphNames()
        self.store = RdflibGraphStore()
        self.store.put(self.names.target_graph, library_graph())

    def test_applying_reaches_exactly_the_previewed_state(self):
        patch = preview(self.store.get(self.names.target_graph),
                        PREFIXES + 'ex:saw a ex:Tool .\n'
                        '- ex:drill ex:serial "1234" .\n')
        self.assertTrue(patch.ok, patch.errors)
        bundle, evidence = publication(self.store, self.names, patch)
        target = bundle.graphs[self.names.target_graph]
        self.assertIn((EX.saw, RDF.type, EX.Tool), target)
        self.assertNotIn((EX.drill, EX.serial, Literal("1234")), target)
        self.assertIn((EX.drill, RDF.type, EX.Tool), target)
        self.assertTrue(len(evidence))

    def test_the_shape_and_schema_graphs_are_left_alone(self):
        self.store.put(self.names.schema_graphs[0], Graph())
        patch = preview(self.store.get(self.names.target_graph),
                        PREFIXES + "ex:saw a ex:Tool .\n")
        bundle, _evidence = publication(self.store, self.names, patch)
        self.assertNotIn(self.names.schema_graphs[0], bundle.graphs)
        self.assertNotIn(self.names.shape_graphs[0], bundle.graphs)


class EditWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.workspace = Workspace(graph_path=self.base / "ontology.trig",
                                   sources_dir=self.base / "inbox",
                                   extractor=_NoModel())
        self.names = self.workspace.names
        self.workspace.store.put(self.names.target_graph, library_graph())

    def test_the_current_data_graph_is_readable_and_parseable(self):
        answer = call(self.workspace, "edit.current", {})
        self.assertTrue(answer["ok"])
        self.assertIn("Drill", answer["turtle"])
        self.assertIn("bytes", answer)
        parsed = Graph()
        parsed.parse(data=answer["turtle"], format="turtle")
        self.assertIn((EX.drill, RDF.type, EX.Tool), parsed)

    def test_preview_then_apply_writes_and_records(self):
        text = PREFIXES + 'ex:saw a ex:Tool ; skos:prefLabel "Saw" .\n'
        shown = call(self.workspace, "edit.preview", {"text": text})
        self.assertTrue(shown["ok"], shown)
        self.assertTrue(shown["patch_id"])
        applied = call(self.workspace, "edit.apply",
                       {"patch_id": shown["patch_id"]})
        self.assertTrue(applied["ok"], applied)
        self.assertIn("log", applied)
        target = self.workspace.store.get(self.names.target_graph)
        self.assertIn((EX.saw, RDF.type, EX.Tool), target)
        provenance = self.workspace.store.get(self.names.provenance_graph)
        self.assertTrue(list(provenance.subjects(RDF.type, PROV.Activity)))

    def test_apply_needs_a_preview(self):
        refused = call(self.workspace, "edit.apply", {"patch_id": "deadbeef"})
        self.assertFalse(refused["ok"])
        self.assertIn("Preview again", refused["error"])

    def test_a_refused_patch_is_never_stored(self):
        shown = call(self.workspace, "edit.preview",
                     {"text": PREFIXES + "ex:Brand a owl:Class .\n"})
        self.assertFalse(shown["ok"])
        self.assertFalse(shown["patch_id"] in self.workspace.edits)

    def test_the_vocabulary_toggle_travels_with_the_preview(self):
        text = PREFIXES + "ex:Brand a owl:Class .\n"
        shown = call(self.workspace, "edit.preview",
                     {"text": text, "allow_new_vocabulary": True})
        self.assertTrue(shown["ok"], shown)
        applied = call(self.workspace, "edit.apply",
                       {"patch_id": shown["patch_id"]})
        self.assertTrue(applied["ok"], applied)

    def test_an_empty_patch_is_reported(self):
        shown = call(self.workspace, "edit.preview", {"text": "   "})
        self.assertFalse(shown["ok"])
        self.assertIn("empty", shown["error"])
        # and the workspace refuses it as well, not only the operation
        self.assertFalse(self.workspace.edit_preview("  ")["ok"])

    def test_previewing_twice_keeps_one_id_and_the_latest_wins(self):
        text = PREFIXES + "ex:saw a ex:Tool .\n"
        first = call(self.workspace, "edit.preview", {"text": text})
        second = call(self.workspace, "edit.preview", {"text": text})
        self.assertEqual(first["patch_id"], second["patch_id"])
        self.assertEqual(len(self.workspace.edits), 1)


def materialize_statement_uri(triple):
    """The same IRI the publishing path builds, cross-checked here."""
    import hashlib
    from text_to_ontology.graph_management import ONTO
    key = " ".join(term.n3() for term in triple)
    return ONTO["statement/" + hashlib.sha256(key.encode("utf-8")).hexdigest()]


class _NoModel:
    def model(self):
        return "no-model"

    def extract(self, prompt):
        raise AssertionError("an edit must never ask a model")


if __name__ == "__main__":
    unittest.main()
