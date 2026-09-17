"""Milestone 2: stable source documents and complete windowing."""

import ast
import unittest
from pathlib import Path

from text_to_ontology import windowing
from text_to_ontology.prompt_budget import estimate_tokens
from text_to_ontology.windowing import (
    WINDOW_STRATEGY_VERSION,
    WindowingConfig,
    load_source_document,
    make_source_document,
    normalize_text,
    plan_windows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def covered_offsets(windows):
    """Every character position at least one window looks at."""
    seen = set()
    for window in windows:
        seen.update(range(window.start, window.end))
    return seen


class SourceDocumentTest(unittest.TestCase):
    """AC1: content-derived ID, name, normalized text, media type, digest."""

    def test_identity_comes_from_content_not_name(self):
        first = make_source_document("a.txt", "same text\n")
        second = make_source_document("b.md", "same text\r\n")
        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual(first.digest, second.digest)
        self.assertNotEqual(first.name, second.name)

    def test_fields_are_filled_and_shape_is_sane(self):
        document = make_source_document("notes.txt", "hello\r\nworld")
        self.assertTrue(document.document_id.startswith("doc-"))
        self.assertEqual(len(document.digest), 64)
        self.assertEqual(document.text, "hello\nworld")
        self.assertEqual(document.media_type, "text/plain")

    def test_media_type_follows_the_extension(self):
        document = load_source_document(FIXTURES / "long_paragraphs.md")
        self.assertEqual(document.media_type, "text/markdown")
        mystery = make_source_document("mystery.weird", "x", media_type="text/plain")
        self.assertEqual(mystery.media_type, "text/plain")

    def test_load_reads_a_fixture_from_disk(self):
        document = load_source_document(FIXTURES / "unicode.txt")
        self.assertIn("naïve façade", document.text)
        self.assertEqual(document.source_path,
                         (FIXTURES / "unicode.txt").as_posix())


class ShortDocumentTest(unittest.TestCase):
    """AC3: below target size means exactly one whole-text window."""

    def test_one_window_holding_everything(self):
        document = make_source_document("short.txt", "Just one small source.\n")
        windows = plan_windows(document)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual(window.text, document.text)
        self.assertEqual((window.start, window.end), (0, len(document.text)))
        self.assertEqual(window.index, 0)
        self.assertEqual(window.strategy_version, WINDOW_STRATEGY_VERSION)
        self.assertGreater(window.token_estimate, 0)


class ParagraphDocumentTest(unittest.TestCase):
    """AC4/AC5: headings and paragraphs split; overlap present; nothing lost."""

    def setUp(self):
        self.document = load_source_document(FIXTURES / "long_paragraphs.md")
        # A tiny target forces many windows from a small fixture.
        self.config = WindowingConfig(target_tokens=40, overlap_tokens=10)
        self.windows = plan_windows(self.document, self.config)

    def test_long_source_produces_several_windows(self):
        self.assertGreater(len(self.windows), 2)

    def test_window_text_matches_recorded_offsets(self):
        for window in self.windows:
            self.assertEqual(
                self.document.text[window.start:window.end], window.text
            )

    def test_adjacent_windows_overlap(self):
        for previous, following in zip(self.windows, self.windows[1:]):
            self.assertLess(following.start, previous.end,
                            "adjacent windows must share text")

    def test_every_character_is_covered_by_at_least_one_window(self):
        self.assertEqual(
            covered_offsets(self.windows),
            set(range(len(self.document.text))),
        )

    def test_headings_and_paragraphs_boundaries_align(self):
        # Without overlap, consecutive windows touch exactly, and each
        # boundary sits at a line break - never in the middle of a line.
        windows = plan_windows(
            self.document, WindowingConfig(target_tokens=40, overlap_tokens=0)
        )
        text = self.document.text
        for previous, following in zip(windows, windows[1:]):
            self.assertEqual(previous.end, following.start)
            self.assertEqual("\n", text[previous.end - 1])


class OversizedSentenceTest(unittest.TestCase):
    """AC4: one sentence too big for any window is hard-split, not lost."""

    def setUp(self):
        self.document = load_source_document(FIXTURES / "oversized_sentence.txt")
        self.config = WindowingConfig(target_tokens=200, overlap_tokens=20)
        self.windows = plan_windows(self.document, self.config)

    def test_hard_split_produces_many_small_windows(self):
        self.assertGreater(len(self.windows), 3)
        sizes = [window.token_estimate for window in self.windows]
        self.assertLess(max(sizes) * 3, len(self.document.text),
                        "no single window should still hold most of the text")

    def test_coverage_survives_the_hard_split(self):
        self.assertEqual(
            covered_offsets(self.windows),
            set(range(len(self.document.text))),
        )

    def test_tail_reaches_the_final_words(self):
        self.assertTrue(self.windows[-1].text.endswith("final period."))


class LongArticleTest(unittest.TestCase):
    """The real long sample: coverage and a marker in the final characters."""

    def test_tail_marker_of_the_uploaded_sample_is_never_lost(self):
        document = load_source_document(FIXTURES / "long_article.md")
        config = WindowingConfig(target_tokens=600, overlap_tokens=60)
        windows = plan_windows(document, config)
        self.assertGreater(len(windows), 4)
        self.assertEqual(
            covered_offsets(windows), set(range(len(document.text)))
        )
        self.assertTrue(
            windows[-1].text.rstrip().endswith("bolder builders themselves.")
        )

    def test_default_config_covers_the_whole_sample(self):
        document = load_source_document(FIXTURES / "long_article.md")
        windows = plan_windows(document)
        self.assertEqual(
            covered_offsets(windows), set(range(len(document.text)))
        )
        joined = "".join(window.text for window in windows)
        self.assertIn("The Widget Launch", joined)
        self.assertIn("Key Points", joined)


class DeterminismTest(unittest.TestCase):
    """AC6/T6: same inputs give the same IDs and boundaries; changed inputs don't."""

    def setUp(self):
        self.document = load_source_document(FIXTURES / "long_paragraphs.md")
        self.config = WindowingConfig(target_tokens=40, overlap_tokens=10)

    def test_same_document_and_config_give_identical_windows(self):
        first = plan_windows(self.document, self.config)
        second = plan_windows(self.document, self.config)
        self.assertEqual([(w.window_id, w.start, w.end) for w in first],
                         [(w.window_id, w.start, w.end) for w in second])

    def test_window_ids_change_when_strategy_inputs_change(self):
        base = plan_windows(self.document, self.config)
        newer = plan_windows(self.document, WindowingConfig(
            target_tokens=40, overlap_tokens=10, strategy_version=99))
        bigger = plan_windows(self.document, WindowingConfig(
            target_tokens=41, overlap_tokens=10))
        self.assertNotEqual([w.window_id for w in base], [w.window_id for w in newer])
        self.assertNotEqual([w.window_id for w in base], [w.window_id for w in bigger])

    def test_window_ids_include_the_tokenizer_name(self):
        def same_count_but_named(text):  # same numbers, different name
            return estimate_tokens(text)

        named = plan_windows(self.document, WindowingConfig(
            target_tokens=40, overlap_tokens=10, count_tokens=same_count_but_named))
        base = plan_windows(self.document, self.config)
        self.assertEqual([(w.start, w.end) for w in base],
                         [(w.start, w.end) for w in named])
        self.assertNotEqual([w.window_id for w in base], [w.window_id for w in named])


class TokenCountingTest(unittest.TestCase):
    """AC7: the counter is injected; the algorithm does not care which one."""

    def test_a_pricier_counter_makes_smaller_windows(self):
        document = load_source_document(FIXTURES / "long_paragraphs.md")
        plain = plan_windows(document, WindowingConfig(target_tokens=40))
        double = plan_windows(document, WindowingConfig(
            target_tokens=40, count_tokens=lambda text: 2 * estimate_tokens(text)))
        self.assertGreater(len(double), len(plain))


class BlankDocumentTest(unittest.TestCase):
    """AC8: blank documents skip cleanly with zero windows."""

    def test_empty_and_whitespace_only_documents_are_skipped(self):
        for raw in ("", "\n", "   \n\t\r\n"):
            document = make_source_document("blank.txt", raw)
            self.assertEqual(plan_windows(document), [])


class CrlfDocumentTest(unittest.TestCase):
    """Line endings normalize before hashing, so twins produce equal windows."""

    def test_crlf_and_lf_twins_share_ids_and_windows(self):
        raw = (FIXTURES / "crlf.txt").read_bytes().decode("utf-8")
        crlf = make_source_document("crlf.txt", raw)
        lf = make_source_document("crlf.txt", normalize_text(raw))
        self.assertNotEqual(raw, normalize_text(raw))
        self.assertEqual(crlf.document_id, lf.document_id)
        self.assertEqual([w.text for w in plan_windows(crlf)],
                         [w.text for w in plan_windows(lf)])

    def test_no_carriage_return_survives_normalization(self):
        document = load_source_document(FIXTURES / "crlf.txt")
        self.assertNotIn("\r", document.text)


class UnicodeDocumentTest(unittest.TestCase):
    """Multi-byte text survives segmentation with full coverage."""

    def test_unicode_content_is_covered_and_intact(self):
        document = load_source_document(FIXTURES / "unicode.txt")
        windows = plan_windows(document, WindowingConfig(target_tokens=30))
        self.assertEqual(
            covered_offsets(windows), set(range(len(document.text)))
        )
        everything = "".join(window.text for window in windows)
        for marker in ("Émile", "🌍🚀", "naïve façade", "⟦END⟧"):
            self.assertIn(marker, everything)


class ImportBoundaryTest(unittest.TestCase):
    """AC9: this module stays free of RDFLib and any LLM adapter."""

    ALLOWED_ROOTS = {"hashlib", "re", "dataclasses", "pathlib",
                     "text_to_ontology"}

    def reimported_module_roots(self):
        tree = ast.parse(Path(windowing.__file__).read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                # A relative import belongs to this package by definition.
                roots.add(node.module.split(".")[0] if not node.level
                          else "text_to_ontology")
        return roots

    def test_only_plain_standard_library_and_own_package_imports(self):
        roots = self.reimported_module_roots()
        self.assertLessEqual(roots, self.ALLOWED_ROOTS)

    def test_rdflib_is_nowhere_in_the_module(self):
        source = Path(windowing.__file__).read_text(encoding="utf-8")
        self.assertNotIn("rdflib", source)
        self.assertNotIn("llm", source)


if __name__ == "__main__":
    unittest.main()
