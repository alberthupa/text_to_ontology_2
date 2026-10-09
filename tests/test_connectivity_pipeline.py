"""Data-only ingestion keeps documents connected: schema, context, links."""

import io
import tempfile
import unittest
from pathlib import Path

from rdflib.namespace import SKOS

from connectivity_fixtures import (
    ScriptedExtractor,
    answer,
    entity,
    relation,
    starter_store,
)
from text_to_ontology.graph_management import RELATION
from text_to_ontology.graph_store import GraphNames
from text_to_ontology.link_check import add_expected_link
from text_to_ontology.pipeline import (
    ExtractionConfig,
    MergeConfig,
    RunRequest,
    WindowingConfig,
    run_text_to_graph,
)
from text_to_ontology.prompts import PromptLibrary
from text_to_ontology.run_report import RunReporter

TITLE = "# Comparison of Copilot with VAF for the request of Farmexa"
BODY = ("The assistant answers questions of doctors. "
        "It is built on LangGraph and runs in the cloud. " * 6)


def is_link_check(prompt):
    return prompt.startswith("Which client")


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.graph = self.base / "ontology.trig"
        self.sources = self.base / "inbox"
        self.store = starter_store(self.graph)
        self.names = GraphNames()

    def write(self, relative, text):
        path = self.sources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_with(self, path, respond, link_check=True, windowing=None,
                 prompts=None):
        extractor = ScriptedExtractor(respond)
        result = run_text_to_graph(
            RunRequest(source=path, graph_path=self.graph,
                       source_root=self.sources,
                       windowing=windowing or WindowingConfig(),
                       merge=MergeConfig(require_declared_vocabulary=True),
                       extraction=ExtractionConfig(link_check=link_check),
                       prompts=prompts),
            graph_store=self.store, extractor=extractor,
            reporter=RunReporter(stream=io.StringIO()))
        return result, extractor

    def data(self):
        return self.store.get(self.names.target_graph)

    def entity_named(self, name):
        data = self.data()
        for subject in data.subjects(SKOS.prefLabel, None):
            if str(data.value(subject, SKOS.prefLabel)) == name:
                return subject
        return None


class CoreSchemaTest(Base):
    def test_a_window_that_matches_nothing_still_sees_the_whole_schema(self):
        path = self.write("note.md", "Zupełnie inny tekst po polsku.")
        _, extractor = self.run_with(path, lambda prompt, n: answer())
        prompt = extractor.prompts[0]
        self.assertIn("CORE SCHEMA", prompt)
        self.assertIn("Project --has client--> Client", prompt)
        self.assertIn("Project --uses technology--> Technology", prompt)
        self.assertIn("Project . project summary = string", prompt)
        self.assertNotIn("RELEVANT DECLARED ONTOLOGY", prompt)

    def test_the_run_records_the_schema_digest(self):
        path = self.write("note.md", "Nothing much.")
        result, _ = self.run_with(path, lambda prompt, n: answer())
        configuration = result.documents[0].publication_plan \
            .document_merge["configuration"]
        self.assertEqual(len(configuration["schema_sha256"]), 12)

    def test_an_old_prompt_override_still_works(self):
        library = PromptLibrary(self.base / "prompts.local.json")
        self.assertIsNone(library.set("extraction_user",
                                      "${context}HANDEDITED ${text}"))
        path = self.write("note.md", "Nothing much.")
        _, extractor = self.run_with(path, lambda prompt, n: answer(),
                                     prompts=library)
        self.assertIn("HANDEDITED", extractor.prompts[0])
        self.assertIn("CORE SCHEMA", extractor.prompts[0])


class DocumentContextTest(Base):
    def test_every_window_carries_path_title_and_earlier_anchors(self):
        path = self.write("Farmexa/VAF/notes.md", TITLE + "\n\n" + BODY)

        def respond(prompt, number):
            if number == 1:
                return answer([entity("e1", "VAF", "Project")])
            return answer()

        result, extractor = self.run_with(
            path, respond, link_check=False,
            windowing=WindowingConfig(target_tokens=60, overlap_tokens=0))
        windows = [prompt for prompt in extractor.prompts]
        self.assertGreater(len(windows), 2)
        for prompt in windows:
            self.assertIn("Path: Farmexa/VAF/notes.md", prompt)
            self.assertIn("Title: Comparison of Copilot with VAF", prompt)
        self.assertNotIn("DOCUMENT ANCHORS", windows[0])
        later = windows[-1]
        self.assertIn("DOCUMENT ANCHORS", later)
        anchors = later.split("DOCUMENT ANCHORS", 1)[1]
        self.assertIn("- name: VAF", anchors)


class ProvisionalIdTest(Base):
    def test_earlier_window_entities_show_no_temporary_iri(self):
        path = self.write("note.md", TITLE + "\n\n" + BODY)

        def respond(prompt, number):
            if number == 1:
                return answer([entity("e1", "VAF", "Project")])
            return answer()

        _, extractor = self.run_with(
            path, respond, link_check=False,
            windowing=WindowingConfig(target_tokens=60, overlap_tokens=0))
        for prompt in extractor.prompts:
            self.assertNotIn("/provisional/", prompt)

    def test_a_copied_temporary_iri_is_cleared_not_fatal(self):
        path = self.write("note.md", TITLE + "\n\n" + BODY)

        def respond(prompt, number):
            if number == 1:
                return answer([entity("e1", "VAF", "Project")])
            return answer(
                [entity("e1", "VAF", "Project", existing_id=(
                    "http://example.org/text-ontology/provisional/"
                    "doc-0000000000000000/vaf")),
                 entity("e2", "Kafka", "Technology")],
                [relation("e1", "uses technology", "e2")])

        self.run_with(path, respond, link_check=False,
                      windowing=WindowingConfig(target_tokens=60,
                                                overlap_tokens=0))
        project, kafka = self.entity_named("VAF"), self.entity_named("Kafka")
        self.assertIn((project, RELATION["uses-technology"], kafka),
                      self.data())


class EndpointTest(Base):
    def test_a_wrong_link_is_repaired_first(self):
        path = self.write("note.md", "VAF uses LangGraph.")
        wrong = answer([entity("e1", "VAF", "Project"),
                        entity("e2", "LangGraph", "Technology")],
                       [relation("e1", "has client", "e2")])
        right = answer([entity("e1", "VAF", "Project"),
                        entity("e2", "LangGraph", "Technology")],
                       [relation("e1", "uses technology", "e2")])
        _, extractor = self.run_with(
            path, lambda prompt, n: wrong if n == 1 else right)
        self.assertIn("goes Project --has client--> Client", extractor.prompts[1])
        project = self.entity_named("VAF")
        self.assertIsNotNone(
            self.data().value(project, RELATION["uses-technology"]))

    def test_a_link_still_wrong_after_repair_is_dropped_alone(self):
        path = self.write("note.md", "VAF uses LangGraph.")
        wrong = answer([entity("e1", "VAF", "Project"),
                        entity("e2", "LangGraph", "Technology")],
                       [relation("e1", "has client", "e2")])
        self.run_with(path, lambda prompt, n: wrong)
        data = self.data()
        self.assertIsNotNone(self.entity_named("VAF"))
        self.assertIsNotNone(self.entity_named("LangGraph"))
        self.assertEqual(list(data.subject_objects(RELATION["has-client"])), [])


class LinkCheckTest(Base):
    def setUp(self):
        super().setUp()
        add_expected_link(self.store, "Project", "has client",
                          "Which client is this project delivered for?")

    def extraction(self, prompt, number):
        """Windows find the project and the client, never the link."""
        if is_link_check(prompt):
            return self.link_answer
        return answer([entity("e1", "VAF", "Project"),
                       entity("e2", "Farmexa", "Client")])

    def test_a_missing_link_is_filled_from_quoted_evidence(self):
        self.link_answer = {"links": [{
            "object": "c1", "confidence": 0.9,
            "evidence": "VAF for the request of Farmexa"}]}
        path = self.write("note.md", TITLE + "\n\n" + BODY)
        result, extractor = self.run_with(path, self.extraction)
        self.assertTrue(any(is_link_check(prompt)
                            for prompt in extractor.prompts))
        project, client = self.entity_named("VAF"), self.entity_named("Farmexa")
        self.assertIn((project, RELATION["has-client"], client), self.data())
        summary = result.documents[0].link_check
        self.assertEqual(summary["gaps"], 1)
        self.assertEqual(len(summary["filled"]), 1)
        provenance = self.store.get(self.names.provenance_graph)
        self.assertTrue(any("link-" in str(term) for triple in provenance
                            for term in triple))

    def test_evidence_not_in_the_text_adds_nothing(self):
        self.link_answer = {"links": [{
            "object": "c1", "confidence": 0.9,
            "evidence": "Farmexa ordered this project in 2024"}]}
        path = self.write("note.md", TITLE + "\n\n" + BODY)
        result, _ = self.run_with(path, self.extraction)
        self.assertEqual(list(self.data().subject_objects(
            RELATION["has-client"])), [])
        summary = result.documents[0].link_check
        self.assertEqual(summary["not_established"], ["VAF --has client--> ?"])
        self.assertTrue(any("unsupported_evidence" in note
                            for note in summary["dropped"]))

    def test_an_empty_answer_is_not_established(self):
        self.link_answer = {"links": []}
        path = self.write("note.md", TITLE + "\n\n" + BODY)
        result, _ = self.run_with(path, self.extraction)
        self.assertEqual(len(result.documents[0].link_check["not_established"]), 1)

    def test_no_gap_means_no_extra_call(self):
        path = self.write("note.md", "VAF is delivered for Farmexa.")

        def respond(prompt, number):
            return answer([entity("e1", "VAF", "Project"),
                           entity("e2", "Farmexa", "Client")],
                          [relation("e1", "has client", "e2")])

        _, extractor = self.run_with(path, respond)
        self.assertFalse(any(is_link_check(prompt)
                             for prompt in extractor.prompts))

    def test_the_link_check_can_be_switched_off(self):
        self.link_answer = {"links": []}
        path = self.write("note.md", TITLE)
        _, extractor = self.run_with(path, self.extraction, link_check=False)
        self.assertFalse(any(is_link_check(prompt)
                             for prompt in extractor.prompts))

    def test_a_client_already_in_the_graph_is_a_candidate_with_its_id(self):
        first = self.write("a/first.md", "Farmexa is a client.")
        self.run_with(first, lambda prompt, n: answer(
            [entity("e1", "Farmexa", "Client")]))
        client = self.entity_named("Farmexa")
        self.link_answer = {"links": [{
            "object": "c1", "confidence": 0.9,
            "evidence": "VAF for the request of Farmexa"}]}
        second = self.write("b/second.md", TITLE)
        self.run_with(second, lambda prompt, n: self.link_answer
                      if is_link_check(prompt)
                      else answer([entity("e1", "VAF", "Project")]))
        project = self.entity_named("VAF")
        self.assertIn((project, RELATION["has-client"], client), self.data())


class SameFolderTest(Base):
    def test_a_later_file_sees_projects_from_its_folder(self):
        first = self.write("Farmexa/VAF/description.md", "VAF is a project.")
        self.run_with(first, lambda prompt, n: answer(
            [entity("e1", "VAF", "Project")]))
        project = self.entity_named("VAF")
        second = self.write("Farmexa/VAF/backlog.md", "Refresh data weekly.")
        other = self.write("Elsewhere/x/backlog.md", "Refresh data weekly.!")
        _, extractor = self.run_with(second, lambda prompt, n: answer())
        self.assertIn("SAME FOLDER", extractor.prompts[0])
        self.assertIn(f"id: {project}", extractor.prompts[0])
        _, extractor = self.run_with(other, lambda prompt, n: answer())
        self.assertNotIn("SAME FOLDER", extractor.prompts[0])

    def test_a_same_folder_id_may_be_used_as_existing_id(self):
        first = self.write("Farmexa/VAF/description.md", "VAF is a project.")
        self.run_with(first, lambda prompt, n: answer(
            [entity("e1", "VAF", "Project")]))
        project = self.entity_named("VAF")
        second = self.write("Farmexa/VAF/backlog.md", "The assistant uses Kafka.")
        self.run_with(second, lambda prompt, n: answer(
            [entity("e1", "The assistant", "Project", existing_id=str(project)),
             entity("e2", "Kafka", "Technology")],
            [relation("e1", "uses technology", "e2")]))
        kafka = self.entity_named("Kafka")
        self.assertIn((project, RELATION["uses-technology"], kafka), self.data())


if __name__ == "__main__":
    unittest.main()
