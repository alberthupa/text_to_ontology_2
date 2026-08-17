"""Baseline: the end-to-end run, with the LLM boundary patched."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdflib import Literal
from rdflib.namespace import RDF, SKOS

import ontology
import source_parse
import graph_management
from graph_management import ENTITY, ONTO
from prompt_budget import estimate_tokens


class FakeLLM:
    """Answers each prompt from a queue and records what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []
        self.observed = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0) if self.responses else {}
        if callable(response):
            return response()
        return response


def entity_response(*names):
    return {
        "entities": [
            {"id": f"e{number}", "name": name, "kind": "Company",
             "description": f"{name} description", "aliases": [],
             "existing_id": None}
            for number, name in enumerate(names, start=1)
        ],
        "relations": [],
        "facts": [],
    }


@contextlib.contextmanager
def run_main(argv, fake_llm):
    """Run main() with a patched LLM and captured output."""
    output = io.StringIO()
    with mock.patch.object(source_parse, "ask_llm", fake_llm), \
            mock.patch.object(ontology, "model_name", lambda: "test-model"), \
            mock.patch.object(sys, "argv", ["ontology.py", *argv]), \
            contextlib.redirect_stdout(output):
        ontology.main()
    yield output.getvalue()


class EmptySourceTest(unittest.TestCase):
    """Case 5: empty or whitespace-only text is never sent to the LLM."""

    def test_blank_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a_empty.txt").write_text("", encoding="utf-8")
            (root / "b_blank.txt").write_text("   \n\t\n", encoding="utf-8")
            (root / "c_real.txt").write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            fake = FakeLLM(entity_response("Acme Corp"))
            with run_main([str(root), str(graph_path)], fake):
                pass

        self.assertEqual(len(fake.prompts), 1)
        self.assertIn("Acme Corp exists.", fake.prompts[0])


class SequentialFilesTest(unittest.TestCase):
    """Case 21: each file is processed in order against the growing graph."""

    def test_the_second_file_sees_the_first_file_result_on_disk_and_in_context(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text("Acme Corp hires Ada.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            saved_between_files = {}

            def second_response():
                saved_between_files["text"] = graph_path.read_text(encoding="utf-8")
                return entity_response("Ada Lovelace")

            fake = FakeLLM(entity_response("Acme Corp"), second_response)
            with run_main([str(root), str(graph_path)], fake):
                pass

            graph = graph_management.open_graph(graph_path)

        self.assertEqual(len(fake.prompts), 2)
        self.assertIn("Acme Corp exists.", fake.prompts[0])
        self.assertIn("Acme Corp hires Ada.", fake.prompts[1])
        # The first file's entity is context for the second file's prompt.
        self.assertNotIn(str(ENTITY["acme-corp"]), fake.prompts[0])
        self.assertIn(str(ENTITY["acme-corp"]), fake.prompts[1])
        # And the graph was already saved before the second file was parsed.
        self.assertIn("acme-corp", saved_between_files["text"])
        self.assertEqual(
            set(graph.subjects(RDF.type, ONTO.Entity)),
            {ENTITY["acme-corp"], ENTITY["ada-lovelace"]},
        )


class SavingTest(unittest.TestCase):
    def test_the_graph_directory_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "made" / "up" / "graph.ttl"

            fake = FakeLLM(entity_response("Acme Corp"))
            with run_main([str(source), str(graph_path)], fake):
                pass

            self.assertTrue(graph_path.exists())

    def test_the_default_graph_path_is_ontology_ttl(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            previous = Path.cwd()
            os.chdir(root)
            try:
                fake = FakeLLM(entity_response("Acme Corp"))
                with run_main([str(source)], fake):
                    pass
            finally:
                os.chdir(previous)

            self.assertTrue((root / "ontology.ttl").exists())


class ReportingTest(unittest.TestCase):
    def test_progress_and_summary_lines_are_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            fake = FakeLLM(entity_response("Acme Corp", "Beta Corp"))
            with run_main([str(source), str(graph_path)], fake) as printed:
                pass

        self.assertIn(f"Reading {source}", printed)
        self.assertIn("Asking test-model", printed)
        self.assertIn("2 new, 0 resolved, 0 relations, 0 facts", printed)
        self.assertIn(f"triples to {graph_path}", printed)


class ErrorTest(unittest.TestCase):
    def test_a_directory_without_text_files_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "image.png").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError) as caught:
                with run_main([str(root), str(root / "graph.ttl")], FakeLLM()):
                    pass
        self.assertIn("No text-like files found", str(caught.exception))

    def test_a_missing_source_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(RuntimeError) as caught:
                with run_main(
                    [str(root / "absent.txt"), str(root / "graph.ttl")], FakeLLM()
                ):
                    pass
        self.assertIn("Source does not exist", str(caught.exception))


def run_once(root, name, text, graph_path, fake):
    """Process one new source file against a graph, and return the fake."""
    source = root / name
    source.write_text(text, encoding="utf-8")
    with run_main([str(source), str(graph_path)], fake):
        pass
    return fake


class SelectedContextTest(unittest.TestCase):
    """Proposal 5D: the prompt carries selected context, not the whole graph."""

    def build(self, root, graph_path):
        """A graph holding two unrelated entities from two earlier files."""
        run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                 FakeLLM(entity_response("Acme Corp")))
        run_once(root, "02.txt", "Beta Corp exists.", graph_path,
                 FakeLLM(entity_response("Beta Corp")))

    def test_a_mentioned_entity_is_sent_and_an_unmentioned_one_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                            graph_path, FakeLLM(entity_response("Ada Lovelace")))
        prompt = fake.prompts[0]
        self.assertIn(str(ENTITY["acme-corp"]), prompt)
        self.assertNotIn(str(ENTITY["beta-corp"]), prompt)

    def test_the_old_global_catalog_block_is_no_longer_sent(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                            graph_path, FakeLLM(entity_response("Ada Lovelace")))
        self.assertNotIn("EXISTING ENTITIES:", fake.prompts[0])
        self.assertIn("ONTOLOGY CONTEXT", fake.prompts[0])

    def test_the_context_is_rebuilt_from_the_graph_for_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text("Acme Corp hires Ada.", encoding="utf-8")
            fake = FakeLLM(entity_response("Acme Corp"),
                           entity_response("Ada Lovelace"))
            with run_main([str(root), str(graph_path)], fake):
                pass
        # Nothing existed for the first file; the first file's result is context
        # for the second.
        self.assertNotIn("ONTOLOGY CONTEXT", fake.prompts[0])
        self.assertIn(str(ENTITY["acme-corp"]), fake.prompts[1])

    def test_a_zero_allowance_still_produces_a_valid_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            with mock.patch.dict(ontology.PROMPT_BUDGET, {"context_tokens": 0}):
                fake = run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                                graph_path, FakeLLM(entity_response("Ada")))
        prompt = fake.prompts[0]
        self.assertNotIn("ONTOLOGY CONTEXT", prompt)
        self.assertIn("Acme Corp hires Ada Lovelace.", prompt)
        self.assertIn('"entities"', prompt)
        self.assertIn("Return JSON only.", prompt)

    def test_the_context_budget_is_reported_for_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            source = root / "03.txt"
            source.write_text("Acme Corp hires Ada Lovelace.", encoding="utf-8")
            with run_main([str(source), str(graph_path)],
                          FakeLLM(entity_response("Ada"))) as printed:
                pass
        self.assertIn("Context:", printed)
        self.assertIn(f"/{ontology.PROMPT_BUDGET['context_tokens']} tokens", printed)

    def test_the_prompt_stays_smaller_than_the_configured_allowance(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                            graph_path, FakeLLM(entity_response("Ada")))
        context = fake.prompts[0].split("ONTOLOGY CONTEXT")[1].split(
            "Entity resolution is important.")[0]
        self.assertLessEqual(estimate_tokens(context),
                             ontology.PROMPT_BUDGET["context_tokens"])


class MergeIdentityTest(unittest.TestCase):
    """Proposal 5D: merge-time lookup still sees the whole graph."""

    def test_an_entity_absent_from_the_prompt_still_resolves_at_merge_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeLLM(entity_response("Acme Corp")))
            source = root / "02.txt"
            source.write_text("Nothing familiar appears here.", encoding="utf-8")
            fake = FakeLLM(entity_response("Acme Corp"))
            with run_main([str(source), str(graph_path)], fake) as printed:
                pass
            graph = graph_management.open_graph(graph_path)

        self.assertNotIn(str(ENTITY["acme-corp"]), fake.prompts[0])
        self.assertIn("0 new, 1 resolved", printed)
        self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)),
                         {ENTITY["acme-corp"]})


class FailureTest(unittest.TestCase):
    """Proposal 5D: a failed call writes nothing, least of all diagnostics."""

    def test_a_failed_call_leaves_the_saved_graph_untouched(self):
        def explode():
            raise RuntimeError("the model is down")

        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeLLM(entity_response("Acme Corp")))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Acme Corp hires Ada.", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                with run_main([str(source), str(graph_path)], FakeLLM(explode)):
                    pass
            self.assertEqual(graph_path.read_bytes(), before)
            graph = graph_management.open_graph(graph_path)
            self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)),
                             {ENTITY["acme-corp"]})


class RepositoryGraphTest(unittest.TestCase):
    """The canonical graph is never touched by running the pipeline elsewhere."""

    def test_the_repository_graph_is_untouched_by_a_temporary_run(self):
        canonical = Path(__file__).resolve().parent.parent / "ontology.ttl"
        before = canonical.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeLLM(entity_response("Acme Corp")))
        self.assertEqual(canonical.read_bytes(), before)


class ExistingGraphContextTest(unittest.TestCase):
    """A second run against a saved graph resolves into the existing entity."""

    def test_a_rerun_resolves_rather_than_duplicating(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            with run_main([str(source), str(graph_path)],
                          FakeLLM(entity_response("Acme Corp"))):
                pass
            with run_main([str(source), str(graph_path)],
                          FakeLLM(entity_response("acme corp"))) as printed:
                pass

            graph = graph_management.open_graph(graph_path)

        self.assertIn("0 new, 1 resolved", printed)
        self.assertEqual(
            set(graph.subjects(RDF.type, ONTO.Entity)), {ENTITY["acme-corp"]}
        )
        self.assertEqual(
            set(graph.objects(ENTITY["acme-corp"], SKOS.altLabel)),
            {Literal("acme corp")},
        )


if __name__ == "__main__":
    unittest.main()
