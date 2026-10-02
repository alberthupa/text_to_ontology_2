"""The starter ontology: proposal checking and the written dataset."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, XSD

from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
from text_to_ontology.graph_store import GraphNames, Publication, RdflibGraphStore
from text_to_ontology.starter import (
    create_starter,
    proposal_summary,
    propose_starter,
    starter_publication,
    validate_starter,
)
from text_to_ontology.vocabulary import read_vocabulary


GOOD = {
    "classes": [
        {"name": "Person", "description": "a human being"},
        {"name": "Organization", "description": "a company"},
    ],
    "relations": [
        {"name": "works-for", "description": "is employed by",
         "domain": "Person", "range": "Organization"},
    ],
    "facts": [
        {"name": "founded-in", "description": "year founded",
         "domain": "Organization", "range": "integer"},
    ],
}


class FakeExtractor:
    """Answers from a fixed list, then keeps repeating the last answer."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def model(self):
        return "fake-model"

    def extract(self, prompt):
        self.prompts.append(prompt)
        return self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]


class ValidateStarterTest(unittest.TestCase):
    def test_a_good_proposal_is_normalized(self):
        result = validate_starter(GOOD)
        self.assertTrue(result["valid"], result["issues"])
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual([item["name"] for item in result["candidates"]["classes"]],
                         ["Person", "Organization"])
        self.assertEqual(result["candidates"]["relations"][0]["range"],
                         "Organization")

    def test_missing_and_unknown_sections_are_reported(self):
        result = validate_starter({"classes": [], "extra": []})
        self.assertFalse(result["valid"])
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("starter.missing_section", codes)
        self.assertIn("starter.unknown_section", codes)

    def test_camel_case_names_are_rejected(self):
        result = validate_starter({
            "classes": [{"name": "businessUnit"}, {"name": "Person"}],
            "relations": [{"name": "hasPart", "domain": "Person",
                           "range": "Person"}],
            "facts": []})
        self.assertFalse(result["valid"])
        unusable = [issue for issue in result["issues"]
                    if issue["code"].endswith("name_not_usable")]
        self.assertEqual(len(unusable), 2)

    def test_an_unknown_domain_or_range_is_rejected(self):
        result = validate_starter({
            "classes": [{"name": "Person"}, {"name": "Organization"}],
            "relations": [{"name": "works-for", "domain": "Team",
                           "range": "Organization"}],
            "facts": [{"name": "born-on", "domain": "Person",
                       "range": "month"}]})
        self.assertFalse(result["valid"])
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("starter.relations_domain_unknown", codes)
        self.assertIn("starter.fact_range_unknown", codes)

    def test_too_few_classes_or_duplicates_are_rejected(self):
        result = validate_starter({
            "classes": [{"name": "Person"}],
            "relations": [{"name": "knows", "domain": "Person",
                           "range": "Person"}],
            "facts": []})
        self.assertFalse(result["valid"])
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("starter.class_count", codes)

        duplicate = dict(GOOD)
        duplicate["classes"] = [{"name": "Person"}, {"name": "person"}]
        result = validate_starter(duplicate)
        self.assertIn("starter.duplicate_class",
                      {issue["code"] for issue in result["issues"]})

    def test_a_relation_needs_a_domain_and_a_range(self):
        result = validate_starter({
            "classes": [{"name": "Person"}, {"name": "Organization"}],
            "relations": [{"name": "works-for"}], "facts": []})
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("starter.relations_domain_missing", codes)
        self.assertIn("starter.relations_range_missing", codes)


class ProposeStarterTest(unittest.TestCase):
    def test_a_messy_answer_is_repaired_by_the_model(self):
        extractor = FakeExtractor(
            {"classes": [{"name": "businessUnit"}], "relations": [], "facts": []},
            GOOD)
        proposal = propose_starter("a company with people", extractor)
        self.assertEqual(len(proposal["classes"]), 2)
        self.assertEqual(len(extractor.prompts), 2)
        self.assertIn("corrected", extractor.prompts[1])
        self.assertIn('"classes", "relations", "facts"', extractor.prompts[1])

    def test_a_hopeless_answer_is_reported(self):
        extractor = FakeExtractor({"classes": [], "relations": [], "facts": []})
        with self.assertRaises(RuntimeError) as caught:
            propose_starter("nothing useful", extractor, repair_attempts=1)
        self.assertIn("starter ontology error", str(caught.exception))


class StarterPublicationTest(unittest.TestCase):
    def proposal(self):
        return validate_starter(GOOD)["candidates"]

    def test_the_five_roles_are_written_and_the_data_graph_is_empty(self):
        names = GraphNames()
        publication = starter_publication(self.proposal(), names)
        self.assertEqual(set(publication.graphs), {
            names.schema_graphs[0], names.shape_graphs[0], names.target_graph,
            names.provenance_graph, names.review_graph})
        self.assertEqual(len(publication.graphs[names.target_graph]), 0)
        self.assertEqual(len(publication.graphs[names.review_graph]), 0)

    def test_the_schema_carries_classes_relations_facts_and_ranges(self):
        names = GraphNames()
        schema = starter_publication(self.proposal(), names) \
            .graphs[names.schema_graphs[0]]
        self.assertIn((CLASS["person"], RDF.type, OWL.Class), schema)
        self.assertIn((CLASS["person"], RDFS.subClassOf, ONTO.Entity), schema)
        self.assertIn((RELATION["works-for"], RDF.type, OWL.ObjectProperty),
                      schema)
        self.assertIn((RELATION["works-for"], RDFS.domain, CLASS["person"]),
                      schema)
        self.assertIn((RELATION["works-for"], RDFS.range, CLASS["organization"]),
                      schema)
        self.assertIn((FACT["founded-in"], RDF.type, OWL.DatatypeProperty),
                      schema)
        self.assertIn((FACT["founded-in"], RDFS.range, XSD.integer), schema)

    def test_the_ontology_header_and_entity_root_survive(self):
        names = GraphNames()
        publication = starter_publication(self.proposal(), names)
        schema = publication.graphs[names.schema_graphs[0]]
        shapes = publication.graphs[names.shape_graphs[0]]
        provenance = publication.graphs[names.provenance_graph]
        self.assertIn((ONTO.Entity, RDF.type, OWL.Class), schema)
        self.assertIn((ONTO.ontology, RDF.type, OWL.Ontology), provenance)
        self.assertTrue(len(shapes) > 0)

    def test_the_summary_names_every_kind(self):
        text = proposal_summary(self.proposal())
        self.assertIn("2 classes, 1 relations, 1 facts", text)
        self.assertIn("works-for: Person -> Organization", text)
        self.assertIn("founded-in: Organization -> integer", text)


class CreateStarterTest(unittest.TestCase):
    def test_writing_a_starter_replaces_an_old_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.trig"
            store = RdflibGraphStore(path=path)
            store.publish(starter_publication(
                validate_starter(GOOD)["candidates"]))
            store.publish(Publication(
                graphs={GraphNames().target_graph: _data_graph()}))

            proposal = create_starter("people and companies",
                                      graph_path=path,
                                      extractor=FakeExtractor(GOOD))
            self.assertEqual(len(proposal["classes"]), 2)

            reopened = RdflibGraphStore(path=path)
            self.assertEqual(len(reopened.get(GraphNames().target_graph)), 0)
            vocabulary = read_vocabulary(
                reopened.get(GraphNames().schema_graphs[0]))
            self.assertEqual(vocabulary.class_names,
                             ["Entity", "Organization", "Person"])


def _data_graph():
    graph = Graph()
    graph.add((ENTITY["leftover"], RDF.type, ONTO.Entity))
    graph.add((ENTITY["leftover"], RDFS.label, Literal("Leftover")))
    return graph


if __name__ == "__main__":
    unittest.main()
