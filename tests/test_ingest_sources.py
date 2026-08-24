"""Baseline: source discovery and reading."""

import tempfile
import unittest
from pathlib import Path

from text_to_ontology.ingest_sources import TEXT_FILES, find_text_files, read_source


class DirectFileTest(unittest.TestCase):
    """Case 3: a directly supplied file is accepted whatever its extension."""

    def test_unlisted_extension_is_accepted_when_named_directly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "notes.weird"
            source.write_text("hello", encoding="utf-8")
            self.assertNotIn(".weird", TEXT_FILES)
            self.assertEqual(
                find_text_files(source, root / "ontology.ttl"), [source]
            )


class DirectoryTest(unittest.TestCase):
    """Case 4: recursive, sorted, extension-limited, graph-excluding."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "nested" / "deeper").mkdir(parents=True)
        for name in (
            "b.txt", "a.md", "nested/c.rst", "nested/deeper/d.json",
            "skip.bin", "nested/skip.pdf",
        ):
            (self.root / name).write_text("x", encoding="utf-8")
        self.graph_path = self.root / "ontology.ttl"
        self.graph_path.write_text("# graph", encoding="utf-8")

    def test_directory_results_are_recursive_sorted_and_filtered(self):
        found = find_text_files(self.root, self.graph_path)
        self.assertEqual(
            [path.relative_to(self.root).as_posix() for path in found],
            ["a.md", "b.txt", "nested/c.rst", "nested/deeper/d.json"],
        )
        self.assertEqual(found, sorted(found))

    def test_output_graph_is_excluded(self):
        graph_path = self.root / "graph.txt"
        graph_path.write_text("# graph", encoding="utf-8")
        found = find_text_files(self.root, graph_path)
        self.assertNotIn(graph_path, found)
        self.assertIn(self.root / "b.txt", found)

    def test_missing_source_raises_the_existing_error(self):
        with self.assertRaises(RuntimeError) as caught:
            find_text_files(self.root / "absent", self.graph_path)
        self.assertIn("Source does not exist", str(caught.exception))

    def test_directory_without_text_files_returns_nothing(self):
        empty = self.root / "empty"
        empty.mkdir()
        (empty / "image.png").write_text("x", encoding="utf-8")
        self.assertEqual(find_text_files(empty, self.graph_path), [])


class ReadSourceTest(unittest.TestCase):
    def test_utf8_is_read_and_invalid_bytes_are_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mixed.txt"
            path.write_bytes("Zażółć".encode("utf-8") + b"\xff")
            text = read_source(path)
        self.assertTrue(text.startswith("Zażółć"))
        self.assertIn("�", text)


if __name__ == "__main__":
    unittest.main()
