"""The CLI: argument parsing, exit codes, and one function behind both entries."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from text_to_ontology import __main__, cli, graph_management, llm


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


@contextlib.contextmanager
def run_cli(argv, responses):
    """Run cli.main() with a patched LLM boundary; report code and output."""
    prompts = []

    def fake_extract(prompt, system=None):
        prompts.append(prompt)
        response = responses.pop(0) if responses else {}
        return response() if callable(response) else response

    out, err = io.StringIO(), io.StringIO()
    # Pin the provider: a developer's .env may choose another one.
    environment = dict(os.environ, LLM_PROVIDER="openrouter",
                       OPENROUTER_MODEL="test-model")
    with mock.patch.object(llm, "ask_llm", fake_extract), \
            mock.patch.dict(os.environ, environment), \
            contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            cli.main(argv)
            code = 0
        except SystemExit as exit_call:
            code = exit_call.code
    yield code, out.getvalue(), err.getvalue()


class CliSuccessTest(unittest.TestCase):
    def test_a_successful_run_exits_zero_and_saves_the_graph(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            with run_cli([str(source), str(graph_path)],
                         [entity_response("Acme Corp")]) as (code, out, _):
                pass

            graph = graph_management.open_graph(graph_path)

        self.assertEqual(code, 0)
        self.assertIn(f"Reading {source}", out)
        self.assertIn("Asking test-model (this can take a minute)...", out)
        self.assertIn(f"Saved {len(graph)} triples to {graph_path}", out)


class CliFailureTest(unittest.TestCase):
    def test_a_validation_failure_exits_one_with_an_error_line(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            with run_cli([str(source), str(graph_path)], [{}]) as (
                    code, out, err):
                pass

        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("validation error(s)", err)
        self.assertFalse(graph_path.exists())

    def test_a_missing_source_exits_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with run_cli([str(root / "absent.txt"), str(root / "graph.ttl")],
                         []) as (code, _, err):
                pass
        self.assertEqual(code, 1)
        self.assertIn("Source does not exist", err)

    def test_a_directory_without_text_files_exits_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "image.png").write_text("x", encoding="utf-8")
            with run_cli([str(root), str(root / "graph.ttl")], []) as (
                    code, _, err):
                pass
        self.assertEqual(code, 1)
        self.assertIn("No text-like files found", err)


class CliReportTest(unittest.TestCase):
    def test_report_flag_writes_the_file_and_stays_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = Path.cwd()
            os.chdir(root)
            try:
                source = root / "notes.txt"
                source.write_text("Acme Corp exists.", encoding="utf-8")
                graph_path = root / "graph.ttl"
                with run_cli([str(source), str(graph_path), "--report"],
                             [entity_response("Acme Corp")]) as (code, out, _):
                    pass
                reports = list((root / "reports" / "runs").glob("*.md"))
                saved_report = reports[0].read_text(encoding="utf-8")
            finally:
                os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(len(reports), 1)
        self.assertIn("# Ontology extraction report", saved_report)
        self.assertIn("## [5] Main LLM call and extraction", saved_report)
        self.assertIn("Acme Corp exists.", saved_report)


class CliDryRunTest(unittest.TestCase):
    def test_dry_run_reports_the_plan_and_writes_no_graph(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"
            with run_cli([str(source), str(graph_path), "--dry-run"],
                         [entity_response("Acme Corp")]) as (code, out, _):
                pass
        self.assertEqual(code, 0)
        self.assertFalse(graph_path.exists())
        self.assertIn("Dry run complete", out)
        self.assertIn("nothing written", out)


class CliVerboseTest(unittest.TestCase):
    def test_verbose_output_shows_every_numbered_section(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.txt"
            source.write_text("Acme Corp exists.", encoding="utf-8")
            graph_path = root / "graph.ttl"

            with run_cli(["-v", str(source), str(graph_path)],
                         [entity_response("Acme Corp")]) as (code, out, _):
                pass

        self.assertEqual(code, 0)
        for section in ("[2-3] Context selection inputs", "[4] Prompt context",
                        "[5] Main LLM call and extraction", "[6] Validation: PASS",
                        "[7] Merge plan", "[8] Apply and save"):
            self.assertIn(section, out)
        self.assertIn(f"Saved atomically to {graph_path}", out)


class OneCliFunctionTest(unittest.TestCase):
    """AC7: `python3 -m text_to_ontology` and the console command share main."""

    def test_the_module_entry_is_the_cli_function(self):
        self.assertIs(__main__.main, cli.main)

    def test_python_dash_m_prints_usage_without_network_access(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-m", "text_to_ontology", "--help"],
                cwd=folder, capture_output=True, text=True,
                env=dict(os.environ, OPENROUTER_API_KEY=""))
        self.assertEqual(result.returncode, 0)
        self.assertIn("source", result.stdout)

    def test_the_installed_console_command_prints_the_same_usage(self):
        executable = shutil.which("text-to-ontology")
        if not executable:
            self.skipTest("console script not installed; run `pip install -e .`")
        with tempfile.TemporaryDirectory() as folder:
            installed = subprocess.run(
                [executable, "--help"], cwd=folder,
                capture_output=True, text=True)
            module = subprocess.run(
                [sys.executable, "-m", "text_to_ontology", "--help"],
                cwd=folder, capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0)
        self.assertEqual(module.returncode, 0)
        # argparse prints the invoked program name in the usage line.
        self.assertEqual(
            installed.stdout.split("options:")[-1],
            module.stdout.split("options:")[-1])


if __name__ == "__main__":
    unittest.main()
