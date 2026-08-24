"""Baseline: the end-to-end public API, with a fake extractor and local store."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdflib import Literal
from rdflib.namespace import RDF, SKOS

from text_to_ontology import graph_management, pipeline
from text_to_ontology.api import (
    ContextConfig,
    ExtractionConfig,
    RunRequest,
    run_text_to_graph,
)
from text_to_ontology.graph_management import ENTITY, ONTO, RELATION
from text_to_ontology.prompt_budget import PROMPT_BUDGET, estimate_tokens
from text_to_ontology.run_report import RunReporter


class FakeExtractor:
    """Answers each prompt from a queue and records what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []
        self.observed = []

    def model(self):
        return "test-model"

    def extract(self, prompt):
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
             "existing_id": None, "confidence": 0.9}
            for number, name in enumerate(names, start=1)
        ],
        "relations": [],
        "facts": [],
    }


def no_repair(source, graph_path):
    """A request with model self-repair disabled: first answer is final."""
    return RunRequest(
        source=Path(source), graph_path=Path(graph_path),
        extraction=ExtractionConfig(repair_attempts=0))


def run_api(source, graph_path, fake_extractor, verbose=False, request=None):
    """Run the public API with a fake extractor and captured output."""
    output = io.StringIO()
    reporter = RunReporter(verbose=verbose, stream=output)
    if request is None:
        request = RunRequest(source=Path(source), graph_path=Path(graph_path))
    result = run_text_to_graph(
        request,
        graph_store=graph_management.LocalTurtleStore(),
        extractor=fake_extractor,
        reporter=reporter,
    )
    return result, output.getvalue()


def run_once(root, name, text, graph_path, fake_extractor, **kwargs):
    """Write one new source file, process it against a graph, report back."""
    source = root / name
    source.write_text(text, encoding="utf-8")
    return run_api(source, graph_path, fake_extractor, **kwargs)


class EmptySourceTest(unittest.TestCase):
    """Case 5: empty or whitespace-only text is never sent to the LLM."""

    def test_blank_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a_empty.txt").write_text("", encoding="utf-8")
            (root / "b_blank.txt").write_text("   \n\t\n", encoding="utf-8")
            (root / "c_real.txt").write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            fake = FakeExtractor(entity_response("Acme Corp"))
            result, _ = run_api(root, graph_path, fake)

        self.assertEqual(len(fake.prompts), 1)
        self.assertIn("Acme Corp exists.", fake.prompts[0])
        self.assertEqual((result.files_total, result.files_saved,
                          result.files_blank), (3, 1, 2))


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

            fake = FakeExtractor(entity_response("Acme Corp"), second_response)
            run_api(root, graph_path, fake)
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

            run_api(source, graph_path, FakeExtractor(entity_response("Acme Corp")))

            self.assertTrue(graph_path.exists())

    def test_the_default_graph_path_is_ontology_ttl(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = io.StringIO()
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            previous = Path.cwd()
            os.chdir(root)
            try:
                result = run_text_to_graph(
                    RunRequest(source=source),
                    graph_store=graph_management.LocalTurtleStore(),
                    extractor=FakeExtractor(entity_response("Acme Corp")),
                    reporter=RunReporter(stream=output),
                )
            finally:
                os.chdir(previous)

            self.assertTrue((root / "ontology.ttl").exists())
            self.assertEqual(result.graph_path, Path("ontology.ttl"))


class ReportingTest(unittest.TestCase):
    def test_progress_and_summary_lines_are_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            _, printed = run_api(source, graph_path, FakeExtractor(
                entity_response("Acme Corp", "Beta Corp")))

        self.assertIn(f"Reading {source}", printed)
        self.assertIn("Asking test-model", printed)
        self.assertIn("2 new, 0 resolved, 0 relations, 0 facts", printed)
        self.assertIn(f"triples to {graph_path}", printed)

    def test_verbose_report_uses_the_same_numbered_pipeline_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Alice has an uncertain date.", encoding="utf-8")
            graph_path = root / "graph.ttl"
            response = {
                "entities": [{
                    "id": "e1", "name": "Alice", "kind": "Person",
                    "description": "", "aliases": [],
                    "existing_id": None, "confidence": 0.9,
                }],
                "relations": [],
                "facts": [{
                    "subject": "e1", "predicate": "important date",
                    "value": "unknown", "confidence": 0.5,
                }],
            }

            _, printed = run_api(source, graph_path, FakeExtractor(response),
                                 verbose=True)

        for section in ("[2-3] Context selection inputs", "[4] Prompt context",
                        "[5] Main LLM call and extraction", "[6] Validation: PASS",
                        "[6a] Complete-source reconciliation",
                        "[6b] Complete-source SHACL validation: PASS",
                        "[7] Merge plan", "[8] Apply and save"):
            self.assertIn(section, printed)
        self.assertIn("Identity e1: NEW", printed)
        self.assertIn("Fact[0]: REVIEW", printed)
        self.assertIn("reason: confidence.below_auto_accept", printed)
        self.assertIn(f"Saved atomically to {graph_path}", printed)

    def test_a_run_result_reports_final_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            result, _ = run_api(source, graph_path, FakeExtractor(
                entity_response("Acme Corp")))
            graph = graph_management.open_graph(graph_path)

        self.assertEqual(result.triples, len(graph))
        self.assertEqual(result.files_saved, 1)


class SelectedContextTest(unittest.TestCase):
    """Proposal 5D: the prompt carries selected context, not the whole graph."""

    def build(self, root, graph_path):
        """A graph holding two unrelated entities from two earlier files."""
        run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                 FakeExtractor(entity_response("Acme Corp")))
        run_once(root, "02.txt", "Beta Corp exists.", graph_path,
                 FakeExtractor(entity_response("Beta Corp")))

    def test_a_mentioned_entity_is_sent_and_an_unmentioned_one_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = FakeExtractor(entity_response("Ada Lovelace"))
            run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                     graph_path, fake)
        prompt = fake.prompts[0]
        self.assertIn(str(ENTITY["acme-corp"]), prompt)
        self.assertNotIn(str(ENTITY["beta-corp"]), prompt)

    def test_the_old_global_catalog_block_is_no_longer_sent(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = FakeExtractor(entity_response("Ada Lovelace"))
            run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                     graph_path, fake)
        self.assertNotIn("EXISTING ENTITIES:", fake.prompts[0])
        self.assertIn("ONTOLOGY CONTEXT", fake.prompts[0])

    def test_the_context_is_rebuilt_from_the_graph_for_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text("Acme Corp hires Ada.", encoding="utf-8")
            fake = FakeExtractor(entity_response("Acme Corp"),
                                 entity_response("Ada Lovelace"))
            run_api(root, graph_path, fake)
        # Nothing existed for the first file; the first file's result is context
        # for the second.
        self.assertNotIn("ONTOLOGY CONTEXT", fake.prompts[0])
        self.assertIn(str(ENTITY["acme-corp"]), fake.prompts[1])

    def test_a_zero_allowance_still_produces_a_valid_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            request = RunRequest(
                source=root / "03.txt",
                graph_path=graph_path,
                context=ContextConfig(budget={**PROMPT_BUDGET,
                                              "context_tokens": 0}),
            )
            fake = FakeExtractor(entity_response("Ada"))
            run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                     graph_path, fake, request=request)
        prompt = fake.prompts[0]
        self.assertNotIn("ONTOLOGY CONTEXT", prompt)
        self.assertIn("Acme Corp hires Ada Lovelace.", prompt)
        self.assertIn('"entities"', prompt)
        self.assertIn("Return JSON only.", prompt)

    def test_the_context_budget_is_reported_for_every_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            _, printed = run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                                  graph_path, FakeExtractor(entity_response("Ada")))
        self.assertIn("Context:", printed)
        self.assertIn(f"/{PROMPT_BUDGET['context_tokens']} tokens", printed)

    def test_the_prompt_stays_smaller_than_the_configured_allowance(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            self.build(root, graph_path)
            fake = FakeExtractor(entity_response("Ada"))
            run_once(root, "03.txt", "Acme Corp hires Ada Lovelace.",
                     graph_path, fake)
        context = fake.prompts[0].split("ONTOLOGY CONTEXT")[1].split(
            "Entity resolution is important.")[0]
        self.assertLessEqual(estimate_tokens(context),
                             PROMPT_BUDGET["context_tokens"])


class MergeIdentityTest(unittest.TestCase):
    """Proposal 5D: merge-time lookup still sees the whole graph."""

    def test_an_entity_absent_from_the_prompt_still_resolves_at_merge_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            fake = FakeExtractor(entity_response("Acme Corp"))
            _, printed = run_once(root, "02.txt",
                                  "Nothing familiar appears here.",
                                  graph_path, fake)
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
                     FakeExtractor(entity_response("Acme Corp")))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Acme Corp hires Ada.", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                run_api(source, graph_path, FakeExtractor(explode))
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
                     FakeExtractor(entity_response("Acme Corp")))
        self.assertEqual(canonical.read_bytes(), before)


class ExistingGraphContextTest(unittest.TestCase):
    """A second run against a saved graph resolves into the existing entity."""

    def test_a_rerun_resolves_rather_than_duplicating(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            run_api(source, graph_path, FakeExtractor(entity_response("Acme Corp")))
            _, printed = run_api(source, graph_path, FakeExtractor(
                entity_response("acme corp")))

            graph = graph_management.open_graph(graph_path)

        self.assertIn("0 new, 1 resolved", printed)
        self.assertEqual(
            set(graph.subjects(RDF.type, ONTO.Entity)), {ENTITY["acme-corp"]}
        )
        # Policy 07: a name equal after identity normalization corroborates
        # the existing label instead of adding a near-duplicate altLabel.
        self.assertEqual(
            set(graph.objects(ENTITY["acme-corp"], SKOS.altLabel)),
            set(),
        )


class ValidationGateTest(unittest.TestCase):
    """Proposal 6C: every non-empty response is validated before graph mutation."""

    def test_normalized_candidates_reach_the_merger(self):
        captured = {}

        def fake_apply(graph, plan):
            captured["plan"] = plan
            return graph, {"new_entities": 0, "resolved_entities": 0,
                           "relation_triples": 0, "fact_triples": 0,
                           "metadata_triples": 0, "duplicates": 0,
                           "review": 0, "audit_triples": 0}

        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            fake = FakeExtractor({
                "entities": [{
                    "id": "e1", "name": "  Acme   Corp  ",
                    "kind": "Company", "description": "",
                    "aliases": ["ACME", "ACME"],
                    "existing_id": None,
                    "confidence": 0.9,
                }],
                "relations": [], "facts": [],
            })
            with mock.patch.object(pipeline, "apply_merge_plan", fake_apply):
                run_api(source, graph_path, fake)
        domain = set(captured["plan"]["domain_triples"])
        self.assertIn((ENTITY["acme-corp"], SKOS.prefLabel,
                       Literal("Acme Corp")), domain)
        self.assertIn((ENTITY["acme-corp"], SKOS.altLabel,
                       Literal("ACME")), domain)

    def test_a_successful_run_reports_validation_and_duplicate_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            one = entity_response("Acme Corp")["entities"][0]
            _, printed = run_api(source, graph_path, FakeExtractor({
                "entities": [one, one],
                "relations": [], "facts": [],
            }))
        self.assertIn("Validated: 1 entities", printed)
        self.assertIn("1 duplicates removed", printed)

    def test_a_non_mapping_response_rejects_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with self.assertRaises(RuntimeError) as caught:
                run_api(source, graph_path, FakeExtractor([]))
        self.assertIn("validation error(s)", str(caught.exception))

    def test_an_invalid_endpoint_rejects_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                run_api(source, graph_path, FakeExtractor({
                    "entities": [entity_response("Acme Corp")["entities"][0]],
                    "relations": [{"subject": "e1", "predicate": "employs",
                                   "object": "ghost"}],
                    "facts": [],
                }))
        self.assertFalse(graph_path.exists())

    def test_a_hallucinated_existing_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            ghost = str(ENTITY["not-in-the-prompt"])
            with self.assertRaises(RuntimeError) as caught:
                run_api(source, graph_path, FakeExtractor({
                    "entities": [{
                        "id": "e1", "name": "Acme Corp", "kind": "Company",
                        "existing_id": ghost, "confidence": 0.9,
                    }],
                    "relations": [], "facts": [],
                }), request=no_repair(source, graph_path))
        self.assertIn("existing_id", str(caught.exception))

    def test_a_valid_existing_id_from_the_prompt_resolves(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            source = root / "02.txt"
            source.write_text("Acme Corp is important.", encoding="utf-8")
            existing = str(ENTITY["acme-corp"])
            _, printed = run_api(source, graph_path, FakeExtractor({
                "entities": [{
                    "id": "e1", "name": "Acme Corp", "kind": "Company",
                    "existing_id": existing, "confidence": 0.9,
                }],
                "relations": [], "facts": [],
            }))
        self.assertIn("0 new, 1 resolved", printed)

    def test_no_merge_or_save_after_a_validation_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            with mock.patch.object(pipeline, "plan_graph_merge") as planned, \
                    mock.patch.object(pipeline, "apply_merge_plan") as merged, \
                    mock.patch.object(pipeline, "save_graph") as saved:
                with self.assertRaises(RuntimeError):
                    run_api(source, graph_path, FakeExtractor([]))
            planned.assert_not_called()
            merged.assert_not_called()
            saved.assert_not_called()

    def test_a_rejected_source_leaves_the_saved_graph_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Acme Corp hires Ada.", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                run_api(source, graph_path, FakeExtractor({}))
            self.assertEqual(graph_path.read_bytes(), before)

    def test_prior_files_stay_saved_and_later_files_are_not_processed(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "01.txt").write_text("Acme Corp exists.", encoding="utf-8")
            (root / "02.txt").write_text("This is malformed.", encoding="utf-8")
            (root / "03.txt").write_text("Beta Corp exists.", encoding="utf-8")
            fake = FakeExtractor(entity_response("Acme Corp"), {})
            with self.assertRaises(RuntimeError):
                run_api(root, graph_path, fake,
                        request=no_repair(root, graph_path))
            graph = graph_management.open_graph(graph_path)
        self.assertEqual(len(fake.prompts), 2)
        self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)),
                         {ENTITY["acme-corp"]})

    def test_duplicate_only_warnings_still_allow_a_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            one = entity_response("Acme Corp")["entities"][0]
            _, printed = run_api(source, graph_path, FakeExtractor({
                "entities": [dict(one), dict(one)],
                "relations": [], "facts": [],
            }))
            graph = graph_management.open_graph(graph_path)
        self.assertIn("1 new, 0 resolved", printed)
        self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)),
                         {ENTITY["acme-corp"]})

    def test_blank_files_bypass_validation_merge_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            (root / "a_blank.txt").write_text("   \n\t", encoding="utf-8")
            (root / "b_real.txt").write_text("Acme Corp exists.", encoding="utf-8")
            with mock.patch.object(pipeline, "validate_candidates") as validator, \
                    mock.patch.object(pipeline, "save_graph") as saved:
                validator.return_value = {
                    "valid": True,
                    "candidates": entity_response("Acme Corp"),
                    "issues": [],
                    "counts": {"normalized": {"entities": 1, "relations": 0,
                                              "facts": 0},
                               "duplicates_removed": {"entities": 0,
                                                      "relations": 0,
                                                      "facts": 0,
                                                      "aliases": 0}},
                }
                run_api(root, graph_path, FakeExtractor(entity_response("Acme Corp")))
        # The one real file is validated and published once; the blank file
        # never reaches extraction at all.
        self.assertEqual(validator.call_count, 1)
        self.assertEqual(saved.call_count, 1)


class MergePolicyPipelineTest(unittest.TestCase):
    """Proposal 07D: plan first, materialize second, save atomically."""

    def test_a_mixed_package_reports_accepts_duplicates_and_reviews(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            source = root / "02.txt"
            source.write_text("Acme Corp hires Ada Lovelace.", encoding="utf-8")
            acme = str(ENTITY["acme-corp"])
            response = {
                "entities": [
                    {"id": "e1", "name": "Acme Corp", "kind": "Company",
                     "description": "", "aliases": [],
                     "existing_id": acme, "confidence": 0.9},
                    {"id": "e2", "name": "Ada Lovelace", "kind": "Person",
                     "description": "", "aliases": [],
                     "existing_id": None, "confidence": 0.9},
                    {"id": "e3", "name": "Nova Corp", "kind": "Company",
                     "description": "", "aliases": [],
                     "existing_id": None, "confidence": 0.9},
                    {"id": "e4", "name": "Shaky Thing", "kind": "Company",
                     "description": "", "aliases": [],
                     "existing_id": None, "confidence": 0.5},
                ],
                "relations": [
                    {"subject": "e1", "predicate": "employs", "object": "e2",
                     "confidence": 0.9},
                ],
                "facts": [],
            }
            _, printed = run_api(source, graph_path, FakeExtractor(response))
            graph = graph_management.open_graph(graph_path)

        self.assertIn("1 accepted, 1 corroborated, 1 for review", printed)
        self.assertIn("2 new, 1 resolved", printed)
        self.assertEqual(
            set(graph.subjects(RDF.type, ONTO.Entity)),
            {ENTITY["acme-corp"], ENTITY["ada-lovelace"], ENTITY["nova-corp"]},
        )
        self.assertNotIn((ENTITY["shaky-thing"], RDF.type, ONTO.Entity),
                         set(graph))
        self.assertIn((ENTITY["acme-corp"], RELATION["employs"],
                       ENTITY["ada-lovelace"]), set(graph))

    def test_a_duplicate_corroboration_is_reported_and_not_re_added(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            acme0 = entity_response("Acme Corp")["entities"][0]
            ada0 = entity_response("Ada Lovelace")["entities"][0]
            ada0["id"] = "e2"
            run_once(root, "01.txt", "Acme Corp hires Ada Lovelace.",
                     graph_path,
                     FakeExtractor({
                         "entities": [acme0, ada0],
                         "relations": [{"subject": "e1", "predicate": "employs",
                                        "object": "e2", "confidence": 0.9}],
                         "facts": [],
                     }))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Acme Corp employs Ada Lovelace.", encoding="utf-8")
            acme, ada = str(ENTITY["acme-corp"]), str(ENTITY["ada-lovelace"])
            response = {
                "entities": [
                    {"id": "e1", "name": "Acme Corp", "kind": "Company",
                     "description": "", "aliases": [],
                     "existing_id": acme, "confidence": 0.9},
                    {"id": "e2", "name": "Ada Lovelace", "kind": "Company",
                     "description": "", "aliases": [],
                     "existing_id": ada, "confidence": 0.9},
                ],
                "relations": [{"subject": "e1", "predicate": "employs",
                               "object": "e2", "confidence": 0.9}],
                "facts": [],
            }
            _, printed = run_api(source, graph_path, FakeExtractor(response))
            after = graph_path.read_bytes()

        self.assertIn("0 accepted, 3 corroborated", printed)
        self.assertNotEqual(before, after)  # evidence was retained

    def test_a_review_only_package_is_saved_without_domain_assertions(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("A dubious claim appears here.", encoding="utf-8")
            response = {
                "entities": [{
                    "id": "e1", "name": "Dubious Thing", "kind": "Concept",
                    "description": "", "aliases": [],
                    "existing_id": None, "confidence": 0.5,
                }],
                "relations": [], "facts": [],
            }
            _, printed = run_api(source, graph_path, FakeExtractor(response))
            self.assertTrue(graph_path.exists())
            graph = graph_management.open_graph(graph_path)

        self.assertIn("1 for review", printed)
        self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)), set())
        self.assertTrue(any("merge-candidate" in str(subject)
                            for subject in set(graph.subjects())))

    def test_a_planning_failure_leaves_both_graphs_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Beta Corp exists.", encoding="utf-8")
            with mock.patch.object(pipeline, "plan_graph_merge",
                                   side_effect=RuntimeError("planner broke")):
                with self.assertRaises(RuntimeError):
                    run_api(source, graph_path, FakeExtractor(
                        entity_response("Beta Corp")))
            self.assertEqual(graph_path.read_bytes(), before)

    def test_a_save_failure_leaves_the_old_file_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            run_once(root, "01.txt", "Acme Corp exists.", graph_path,
                     FakeExtractor(entity_response("Acme Corp")))
            before = graph_path.read_bytes()
            source = root / "02.txt"
            source.write_text("Beta Corp exists.", encoding="utf-8")
            with mock.patch.object(pipeline, "save_graph",
                                   side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    run_api(source, graph_path, FakeExtractor(
                        entity_response("Beta Corp")))
            self.assertEqual(graph_path.read_bytes(), before)
            graph = graph_management.open_graph(graph_path)
            self.assertEqual(set(graph.subjects(RDF.type, ONTO.Entity)),
                             {ENTITY["acme-corp"]})
            self.assertFalse(Path(str(graph_path) + ".tmp").exists())

    def test_the_next_file_resolves_an_accepted_entity_but_not_a_proposal(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            # File 1 accepts Ada and leaves Shaky as a review-only proposal.
            (root / "01.txt").write_text("Ada Lovelace and Shaky Thing.",
                                         encoding="utf-8")
            (root / "02.txt").write_text("Ada Lovelace again, Shaky Thing too.",
                                         encoding="utf-8")
            ada = entity_response("Ada Lovelace")["entities"][0]
            shaky = dict(ada, id="e9", name="Shaky Thing", confidence=0.5)
            _, first = run_api(root / "01.txt", graph_path, FakeExtractor(
                {"entities": [ada, shaky], "relations": [], "facts": []}))
            # File 2 repeats both names at full confidence.
            repeated = [dict(ada), dict(ada, id="e9", name="Shaky Thing")]
            _, second = run_api(root / "02.txt", graph_path, FakeExtractor(
                {"entities": repeated, "relations": [], "facts": []}))
            graph = graph_management.open_graph(graph_path)

        self.assertIn("1 new, 0 resolved", first)
        self.assertIn("1 new, 1 resolved", second)
        self.assertEqual(
            set(graph.subjects(RDF.type, ONTO.Entity)),
            {ENTITY["ada-lovelace"], ENTITY["shaky-thing"]},
        )


class MergeConfigTest(unittest.TestCase):
    """The merge configuration reaches the planner without changing defaults."""

    def test_a_lower_threshold_accepts_a_shaky_entity(self):
        with tempfile.TemporaryDirectory() as folder:
            root, graph_path = Path(folder), Path(folder) / "graph.ttl"
            source = root / "notes.txt"
            source.write_text("A dubious claim appears here.", encoding="utf-8")
            request = RunRequest(
                source=source,
                graph_path=graph_path,
                merge=pipeline.MergeConfig(min_auto_accept_confidence=0.4),
            )
            response = {
                "entities": [{
                    "id": "e1", "name": "Dubious Thing", "kind": "Concept",
                    "description": "", "aliases": [],
                    "existing_id": None, "confidence": 0.5,
                }],
                "relations": [], "facts": [],
            }
            _, printed = run_api(source, graph_path, FakeExtractor(response),
                                 request=request)
            graph = graph_management.open_graph(graph_path)

        self.assertIn("1 new, 0 resolved", printed)
        self.assertIn((ENTITY["dubious-thing"], RDF.type, ONTO.Entity), set(graph))


if __name__ == "__main__":
    unittest.main()
