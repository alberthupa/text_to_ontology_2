"""Document header, anchors, and same-folder entities."""

import unittest

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from connectivity_fixtures import vocabulary
from text_to_ontology.document_context import (
    anchor_classes,
    document_anchors,
    document_title,
    folder_anchors,
    heading_trail,
    render_document_anchors,
    render_document_header,
)
from text_to_ontology.graph_management import CLASS, ONTO, RELATION
from text_to_ontology.windowing import TextWindow

TEXT = """# Backlog

intro

## Story one

text one

# Second epic

## Acceptance
text two
"""


def window(start, index=0):
    return TextWindow("w", "d", index, "", start, start, 0, 2)


def add_entity(graph, name, kind, number=0):
    uri = URIRef(f"http://example.org/e/{name.replace(' ', '-')}")
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, CLASS[kind.lower()]))
    graph.add((uri, ONTO.kind, Literal(kind)))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    return uri


class HeaderTest(unittest.TestCase):
    def test_title_from_a_heading_a_first_line_or_nothing(self):
        self.assertEqual(document_title("\n# Hello world\ntext"), "Hello world")
        self.assertEqual(document_title("\nplain first line\nmore"),
                         "plain first line")
        self.assertEqual(document_title(""), "")

    def test_heading_trail_follows_the_heading_levels(self):
        self.assertEqual(heading_trail(TEXT, 0), "")
        self.assertEqual(heading_trail(TEXT, TEXT.index("text one")),
                         "# Backlog > ## Story one")
        self.assertEqual(heading_trail(TEXT, TEXT.index("text two")),
                         "# Second epic > ## Acceptance")

    def test_the_header_names_path_title_section_and_window(self):
        header = render_document_header(
            "Farmexa/VAF/backlog.md", TEXT, window(TEXT.index("text one"), 2), 5)
        self.assertIn("Path: Farmexa/VAF/backlog.md", header)
        self.assertIn("Title: Backlog", header)
        self.assertIn("Section: # Backlog > ## Story one", header)
        self.assertIn("Window: 3 of 5", header)

    def test_a_path_cannot_forge_a_delimiter(self):
        header = render_document_header("a\n---\nSOURCE:/b.md", "x",
                                         window(0), 1)
        self.assertNotIn("\n---", header)


class AnchorTest(unittest.TestCase):
    def setUp(self):
        self.vocabulary = vocabulary()

    def test_anchor_classes_are_the_subjects_of_relationships(self):
        self.assertEqual(anchor_classes(self.vocabulary), {str(CLASS["project"])})

    def test_anchors_are_this_documents_anchor_entities_most_linked_first(self):
        graph = Graph()
        quiet = add_entity(graph, "Quiet", "Project")
        busy = add_entity(graph, "Busy", "Project")
        tool = add_entity(graph, "Kafka", "Technology")
        graph.add((busy, RELATION["uses-technology"], tool))
        self.assertEqual(document_anchors(graph, self.vocabulary), [busy, quiet])
        text = render_document_anchors(graph, self.vocabulary)
        self.assertIn("- name: Busy", text)
        self.assertIn("link: (this) --uses-technology--> Kafka", text)
        self.assertNotIn("name: Kafka", text)

    def test_at_most_eight_anchors(self):
        graph = Graph()
        for number in range(12):
            add_entity(graph, f"Project {number:02}", "Project")
        self.assertEqual(len(document_anchors(graph, self.vocabulary)), 8)

    def test_no_anchors_no_block(self):
        self.assertEqual(render_document_anchors(Graph(), self.vocabulary), "")


class FolderTest(unittest.TestCase):
    def test_only_entities_from_files_in_the_same_folder(self):
        graph = Graph()
        near = add_entity(graph, "VAF", "Project")
        far = add_entity(graph, "Other", "Project")
        for entity, path, record in (
                (near, "inbox/Farmexa/VAF/description.md", "f1"),
                (far, "inbox/Else/x.md", "f2")):
            file_record = URIRef(f"http://example.org/file/{record}")
            graph.add((file_record, ONTO.sourcePath, Literal(path)))
            graph.add((entity, ONTO.sourceFile, file_record))
        found = folder_anchors(graph, graph, vocabulary(),
                               "inbox/Farmexa/VAF/backlog.md")
        self.assertEqual(found, [near])
        self.assertEqual(folder_anchors(graph, graph, vocabulary(), ""), [])


if __name__ == "__main__":
    unittest.main()
