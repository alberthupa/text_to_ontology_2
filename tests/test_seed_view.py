"""The seed view keeps only what the seed ontology covers."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from connectivity_fixtures import schema_graph, starter_store
from text_to_ontology.graph_management import CLASS, ONTO, RELATION, SRC
from text_to_ontology.graph_store import GraphNames, Publication
from text_to_ontology.operations import call
from text_to_ontology.seed_view import seed_graphs, seed_view
from text_to_ontology.workspace import Workspace

E = "http://example.org/text-ontology/entity/"
VAF, FARMEXA = URIRef(E + "vaf"), URIRef(E + "farmexa")
UNDECLARED = URIRef("http://example.org/text-ontology/relation/likes")


def roles():
    names = GraphNames()
    data = Graph()
    for entity, name, kind in ((VAF, "VAF", "Project"),
                               (FARMEXA, "Farmexa", "Client")):
        data.add((entity, RDF.type, ONTO.Entity))
        data.add((entity, RDF.type, CLASS[kind.lower()]))
        data.add((entity, RDF.type, OWL.NamedIndividual))
        data.add((entity, RDF.type, SKOS.Concept))
        data.add((entity, ONTO.kind, Literal(kind)))
        data.add((entity, SKOS.prefLabel, Literal(name)))
    data.add((VAF, RELATION["has-client"], FARMEXA))
    data.add((VAF, UNDECLARED, FARMEXA))
    # Source links live in the data graph, but are not part of what was said.
    data.add((VAF, SRC.fromFile, SRC["file/1"]))
    data.add((SRC["file/1"], RDFS.label, Literal("notes.md")))
    data.add((SRC["statement/1"], RDF.subject, VAF))
    provenance, review, shapes = Graph(), Graph(), Graph()
    provenance.add((VAF, ONTO.sourceFile, URIRef("http://x/file")))
    review.add((URIRef("http://x/review"), RDFS.label, Literal("held")))
    shapes.add((URIRef("http://x/shape"), RDF.type, URIRef(
        "http://www.w3.org/ns/shacl#NodeShape")))
    return names, {
        names.schema_graphs[0]: schema_graph(),
        names.shape_graphs[0]: shapes,
        names.target_graph: data,
        names.provenance_graph: provenance,
        names.review_graph: review,
    }


class SeedViewTest(unittest.TestCase):
    def setUp(self):
        self.names, self.roles = roles()
        self.view = seed_view(self.roles, self.names)

    def test_the_schema_is_kept_whole(self):
        for triple in self.roles[self.names.schema_graphs[0]]:
            self.assertIn(triple, self.view)

    def test_declared_statements_names_and_kinds_are_kept(self):
        for triple in ((VAF, RELATION["has-client"], FARMEXA),
                       (VAF, RDF.type, CLASS["project"]),
                       (VAF, RDF.type, ONTO.Entity),
                       (VAF, SKOS.prefLabel, Literal("VAF")),
                       (VAF, ONTO.kind, Literal("Project"))):
            self.assertIn(triple, self.view)

    def test_bookkeeping_and_undeclared_statements_are_dropped(self):
        for triple in ((VAF, RDF.type, OWL.NamedIndividual),
                       (VAF, RDF.type, SKOS.Concept),
                       (VAF, UNDECLARED, FARMEXA)):
            self.assertNotIn(triple, self.view)

    def test_source_links_are_left_out(self):
        for triple in ((VAF, SRC.fromFile, SRC["file/1"]),
                       (SRC["file/1"], RDFS.label, Literal("notes.md")),
                       (SRC["statement/1"], RDF.subject, VAF)):
            self.assertNotIn(triple, self.view)

    def test_provenance_review_and_shapes_are_left_out(self):
        self.assertNotIn((VAF, ONTO.sourceFile, URIRef("http://x/file")),
                         self.view)
        self.assertEqual(list(self.view.subjects(RDFS.label, Literal("held"))),
                         [])
        graphs = seed_graphs(self.roles, self.names)
        self.assertEqual(set(graphs), {self.names.schema_graphs[0],
                                       self.names.target_graph})

    def test_a_declaration_made_in_a_data_graph_counts(self):
        # Without the data-only lock, a run declares new vocabulary in data.
        self.roles[self.names.target_graph].add(
            (UNDECLARED, RDF.type, OWL.ObjectProperty))
        view = seed_view(self.roles, self.names)
        self.assertIn((VAF, UNDECLARED, FARMEXA), view)
        self.assertIn((UNDECLARED, RDF.type, OWL.ObjectProperty), view)


class DatasetViewTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        self.names, graphs = roles()
        store = starter_store(base / "ontology.trig")
        store.publish(Publication(graphs={
            name: graph for name, graph in graphs.items()
            if name != self.names.schema_graphs[0]}))
        self.workspace = Workspace(graph_path=base / "ontology.trig",
                                   sources_dir=base / "inbox")

    def graph_names(self, view):
        answer = call(self.workspace, "dataset", {"view": view})
        self.assertTrue(answer["ok"], answer)
        dataset = Dataset()
        dataset.parse(data=answer["trig"], format="trig")
        return {str(graph.identifier) for graph in dataset.graphs()
                if len(graph)}

    def test_the_seed_view_is_the_default_and_has_no_support_graphs(self):
        default = call(self.workspace, "dataset", {})
        self.assertEqual(default["view"], "seed")
        self.assertEqual(self.graph_names("seed"),
                         {str(self.names.schema_graphs[0]),
                          str(self.names.target_graph)})

    def test_everything_shows_every_named_graph(self):
        self.assertTrue({str(self.names.provenance_graph),
                         str(self.names.review_graph),
                         str(self.names.shape_graphs[0])}
                        <= self.graph_names("all"))

    def test_an_unknown_view_is_a_clear_error(self):
        answer = call(self.workspace, "dataset", {"view": "bogus"})
        self.assertFalse(answer["ok"])

    def test_the_chat_reads_the_seed_view(self):
        graph = self.workspace.seed_graph()
        self.assertNotIn((VAF, ONTO.sourceFile, URIRef("http://x/file")), graph)
        self.assertIn((VAF, RELATION["has-client"], FARMEXA), graph)


if __name__ == "__main__":
    unittest.main()
