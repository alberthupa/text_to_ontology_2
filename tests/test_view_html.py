"""The HTML view: plain data first, then one standalone page, both read only."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from text_to_ontology.ontology_views import build_ontology_views
from text_to_ontology.view_html import render_page, write_report
from text_to_ontology.view_report import build_report, shorten


def sample_graph():
    """A graph with all three partitions filled: schema, instances, support."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.person, RDFS.label, Literal("Person")))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.domain, CLASS.person))
    graph.add((RELATION.knows, RDFS.range, CLASS.person))
    graph.add((FACT.born, RDF.type, OWL.DatatypeProperty))
    graph.add((FACT.born, RDFS.range, XSD.gYear))
    graph.add((ENTITY.ada, RDF.type, ONTO.Entity))
    graph.add((ENTITY.ada, RDF.type, CLASS.person))
    graph.add((ENTITY.ada, SKOS.prefLabel, Literal("Ada")))
    graph.add((ENTITY.grace, RDF.type, CLASS.person))
    graph.add((ENTITY.grace, SKOS.prefLabel, Literal("Grace")))
    graph.add((ENTITY.ada, RELATION.knows, ENTITY.grace))
    graph.add((ENTITY.ada, FACT.born, Literal("1815")))
    graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
    graph.add((ONTO.EntityShape, SH.targetClass, ONTO.Entity))
    return graph


def report_for(graph):
    return build_report(Path("sample.ttl"), graph, build_ontology_views(graph))


class ReportTest(unittest.TestCase):
    """The page can only ever show what the views already decided."""

    def test_the_counts_repeat_the_views(self):
        graph = sample_graph()
        views = build_ontology_views(graph)
        counts = build_report(Path("sample.ttl"), graph, views)["graph"]["counts"]
        for name in ("schema", "instance", "support", "skeleton"):
            self.assertEqual(counts[name], len(views[name]))
        self.assertEqual(counts["patterns"], len(views["patterns"]))

    def test_every_triple_is_listed_exactly_once(self):
        graph = sample_graph()
        report = report_for(graph)
        self.assertEqual(len(report["triples"]), len(graph))
        self.assertEqual(report["graph"]["partitioned"], len(graph))

    def test_an_empty_graph_still_builds_a_report(self):
        report = report_for(Graph())
        self.assertEqual(report["triples"], [])
        self.assertEqual(report["instances"], [])
        self.assertEqual(report["patterns"], [])

    def test_declared_structure_is_reported_without_invention(self):
        skeleton = report_for(sample_graph())["skeleton"]
        person = next(item for item in skeleton["classes"]
                      if item["short"] == "class:person")
        self.assertEqual([parent["short"] for parent in person["parents"]],
                         ["onto:Entity"])
        born = next(item for item in skeleton["properties"]
                    if item["short"] == "fact:born")
        self.assertEqual(born["kind"], "datatype")
        self.assertEqual(born["domain"], [])

    def test_an_instance_card_separates_its_relations_from_its_facts(self):
        cards = report_for(sample_graph())["instances"]
        ada = next(card for card in cards if card["short"] == "entity:ada")
        self.assertEqual([item["value"] for item in ada["relations"]], ["grace"])
        self.assertEqual([item["value"] for item in ada["facts"]], ["1815"])
        self.assertIn({"label": "person", "short": "class:person"}, ada["classes"])

    def test_a_uri_shortens_only_under_its_tightest_prefix(self):
        prefixes = report_for(sample_graph())["graph"]["prefixes"]
        pairs = sorted(((prefix, uri) for prefix, uri in prefixes),
                       key=lambda pair: -len(pair[1]))
        self.assertEqual(shorten(ENTITY.ada, pairs), "entity:ada")
        self.assertEqual(shorten(ONTO.Entity, pairs), "onto:Entity")


class PageTest(unittest.TestCase):
    """One file, no network, and the data it renders survives the round trip."""

    def setUp(self):
        self.page = render_page(report_for(sample_graph()))

    def test_the_page_is_one_complete_document(self):
        self.assertTrue(self.page.startswith("<!DOCTYPE html>"))
        self.assertIn("<title>", self.page)
        self.assertTrue(self.page.rstrip().endswith("</html>"))

    def test_the_page_loads_nothing_from_outside_itself(self):
        for attribute in ("src=", "@import"):
            self.assertNotIn(attribute, self.page)
        self.assertNotIn('<link', self.page)

    def test_the_embedded_data_is_valid_json(self):
        found = re.search(r"const DATA = (.*);</script>", self.page)
        self.assertIsNotNone(found)
        data = json.loads(found.group(1).replace("<\\/", "</"))
        self.assertEqual(len(data["triples"]), len(sample_graph()))

    def test_a_closing_script_tag_in_the_data_cannot_end_the_script(self):
        graph = sample_graph()
        graph.add((ENTITY.ada, RDFS.comment, Literal("</script><b>hi")))
        page = render_page(report_for(graph))
        self.assertNotIn("</script><b>hi", page)

    def test_every_section_of_the_page_is_present(self):
        for anchor in ("read", "pipeline", "partitions", "skeleton", "patterns",
                       "instances", "support", "controls", "glossary"):
            self.assertIn(f'id="{anchor}"', self.page)


class WriteTest(unittest.TestCase):
    """Writing the page never touches the graph it was built from."""

    def test_writing_leaves_the_graph_file_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.ttl"
            sample_graph().serialize(source, format="turtle")
            before = source.read_bytes()
            graph = Graph()
            graph.parse(source, format="turtle")
            destination = Path(folder) / "page.html"
            write_report(source, graph, build_ontology_views(graph), destination)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(destination.read_text(encoding="utf-8")
                            .startswith("<!DOCTYPE html>"))


if __name__ == "__main__":
    unittest.main()
