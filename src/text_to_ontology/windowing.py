"""Split source documents into stable, reproducible text windows.

This module is deliberately source-only: it knows about text, digests, and
offsets - never about RDF, LLMs, or graph files.

The pieces:

    SourceDocument  one input file: stable ID, name, normalized text, digest;
    TextWindow      one reproducible slice with offsets and a token estimate;
    WindowingConfig target/overlap size in tokens plus an injected tokenizer.

Splitting prefers whole headings and paragraphs first. A paragraph too large
for one window falls back to sentences; a single sentence that still cannot
fit is hard-split. Adjacent windows share a configured token overlap, and
window spans tile the normalized text, so no character is lost - not even the
document tail.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .prompt_budget import estimate_tokens

# Bumped whenever the split algorithm or its defaults change in a way that
# would move window boundaries; old IDs then stay explainable.
WINDOW_STRATEGY_VERSION = 2

DEFAULT_TARGET_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100

MEDIA_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rst": "text/x-rst",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
}

_HEADING_PREFIX = re.compile(r"\s*#")
_SENTENCE_ENDINGS = ".!?…"
_CLOSING_QUOTES = "\"')]”’"


@dataclass
class SourceDocument:
    """One source file, normalized and identified by its content."""

    document_id: str
    name: str
    text: str
    media_type: str
    digest: str
    source_path: str = ""


@dataclass
class TextWindow:
    """One slice of one document, reproducible from its recorded inputs."""

    window_id: str
    document_id: str
    index: int
    text: str
    start: int
    end: int
    token_estimate: int
    strategy_version: int


@dataclass
class WindowingConfig:
    """How aggressively a document is cut, and who counts tokens.

    `count_tokens` may be any callable returning an integer for a string;
    the default is the pessimistic character estimator from prompt_budget,
    and a model-aware tokenizer can replace it without touching the algorithm.
    """

    target_tokens: int = DEFAULT_TARGET_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    strategy_version: int = WINDOW_STRATEGY_VERSION
    count_tokens: object = estimate_tokens


def normalize_text(raw_text):
    """The only normalization: every line ending becomes one newline."""
    return raw_text.replace("\r\n", "\n").replace("\r", "\n")


def media_type_for(path):
    return MEDIA_TYPES.get(Path(path).suffix.lower(), "text/plain")


def make_source_document(name, raw_text, media_type="text/plain", source_path=""):
    """Build a document from already-read text; the ID comes from content."""
    text = normalize_text(raw_text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SourceDocument(
        document_id=f"doc-{digest[:16]}",
        name=name,
        text=text,
        media_type=media_type,
        digest=digest,
        source_path=source_path,
    )


def load_source_document(path):
    """Read one file from disk as a SourceDocument."""
    path = Path(path)
    return make_source_document(
        name=path.name,
        raw_text=path.read_text(encoding="utf-8", errors="replace"),
        media_type=media_type_for(path),
        source_path=path.as_posix(),
    )


def plan_windows(document, config=None):
    """Every window of one document, in order.

    A blank (whitespace-only) document produces no windows at all - that
    empty list is the skip result callers should treat as "nothing to do".
    """
    config = config or WindowingConfig()
    if not document.text.strip():
        return []
    units = _units(document.text, config)
    total_tokens = sum(unit["tokens"] for unit in units)
    if total_tokens <= config.target_tokens:
        spans = [(0, len(document.text))]
    else:
        spans = _pack(units, config)
    return [
        TextWindow(
            window_id=_window_id(config, document.document_id, index, start, end),
            document_id=document.document_id,
            index=index,
            text=document.text[start:end],
            start=start,
            end=end,
            token_estimate=config.count_tokens(document.text[start:end]),
            strategy_version=config.strategy_version,
        )
        for index, (start, end) in enumerate(spans)
    ]


def _unit(text, start, end, config):
    return {
        "start": start,
        "end": end,
        "tokens": config.count_tokens(text[start:end]),
    }


def _units(text, config):
    """Atomic slices tiling the whole text: blocks, sentences, hard chunks.

    Every span ends exactly where the next begins, so packing spans into
    windows can never drop or duplicate characters.
    """
    units = []
    for block_start, block_end in _block_spans(text):
        block_tokens = config.count_tokens(text[block_start:block_end])
        if block_tokens <= config.target_tokens:
            units.append(_unit(text, block_start, block_end, config))
            continue
        for sent_start, sent_end in _sentence_spans(text, block_start, block_end):
            sent_tokens = config.count_tokens(text[sent_start:sent_end])
            if sent_tokens <= config.target_tokens:
                units.append(_unit(text, sent_start, sent_end, config))
                continue
            for chunk_start, chunk_end in _hard_chunks(
                text, sent_start, sent_end, sent_tokens, config
            ):
                units.append(_unit(text, chunk_start, chunk_end, config))
    return units


def _block_spans(text):
    """Heading/paragraph spans covering all of text, separators included.

    Blank lines trail the paragraph before them, so consecutive spans touch:
    each starts where the previous ended.
    """
    spans = []
    block_start = None
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if not line.strip():
            if block_start is not None:
                spans.append((block_start, line_end))
                block_start = None
        elif _HEADING_PREFIX.match(line) and line.lstrip().startswith("#"):
            if block_start is not None:
                spans.append((block_start, offset))
                block_start = None
            spans.append((offset, line_end))
        elif block_start is None:
            block_start = offset
        offset = line_end
    if block_start is not None:
        spans.append((block_start, offset))
    # Headings do not absorb their trailing blank line; close any such gap
    # into the preceding span so the spans still cover all of the text.
    for index in range(len(spans) - 1):
        spans[index] = (spans[index][0], max(spans[index][1], spans[index + 1][0]))
    if spans and spans[0][0] > 0:
        spans.insert(0, (0, spans[0][0]))
    return spans or [(0, len(text))]


def _sentence_spans(text, start, end):
    """Sentence spans inside one oversized block, still tiling it.

    This is a plain splitter: sentence-ending punctuation followed by space
    or the end of the block. Abbreviations like "J.D." will split; keeping
    the rule simple keeps windows reproducible.
    """
    spans = []
    sent_start = start
    i = start
    while i < end:
        char = text[i]
        i += 1
        if char in _SENTENCE_ENDINGS:
            while i < end and text[i] in _CLOSING_QUOTES:
                i += 1
            if i >= end or text[i].isspace():
                spans.append((sent_start, i))
                while i < end and text[i].isspace():
                    i += 1
                sent_start = i
    if sent_start < end:
        spans.append((sent_start, end))
    return spans


def _hard_chunks(text, start, end, tokens, config):
    """Cut one un-splittable sentence into equal character chunks."""
    chunk_count = max(1, -(-tokens // max(1, config.target_tokens)))
    size = -(-(end - start) // chunk_count)
    return [
        (slice_start, min(slice_start + size, end))
        for slice_start in range(start, end, size)
    ]


def _pack(units, config):
    """Greedily pack consecutive units into overlapping window spans.

    The last unit(s) of a finished window - up to the overlap budget, always
    at least one - open the next window, which is how adjacent windows share
    their overlap while every unit stays at its original offset.
    """
    spans = []
    current = []
    used = 0
    for unit in units:
        # An empty body must take the next unit even past target: slight
        # overshoot beats a window holding nothing but carried-over overlap.
        if (current and not _holds_only_overlap(current, config)
                and used + unit["tokens"] > config.target_tokens):
            spans.append((current[0]["start"], current[-1]["end"]))
            tail = _tail_units(current, config)
            current = list(tail)
            used = sum(part["tokens"] for part in tail)
        current.append(unit)
        used += unit["tokens"]
    if current:
        spans.append((current[0]["start"], current[-1]["end"]))
    return spans


def _holds_only_overlap(units, config):
    """True when every unit in the window is carried-over overlap."""
    return len(units) <= _tail_count(units, config)


def _tail_count(units, config):
    """How many trailing units fit the overlap budget; zero means none."""
    if config.overlap_tokens <= 0:
        return 0
    total = 0
    count = 0
    for unit in reversed(units):
        total += unit["tokens"]
        count += 1
        if total >= config.overlap_tokens:
            break
    return count


def _tail_units(units, config):
    count = _tail_count(units, config)
    if not count:
        return ()
    return tuple(units[-count:])


def _tokenizer_name(count_tokens):
    return getattr(count_tokens, "__name__", type(count_tokens).__name__)


def _window_id(config, document_id, index, start, end):
    """A short stable ID derived from everything the boundary depends on."""
    payload = "|".join([
        f"v{config.strategy_version}",
        f"target={config.target_tokens}",
        f"overlap={config.overlap_tokens}",
        f"tokenizer={_tokenizer_name(config.count_tokens)}",
        document_id,
        str(index),
        str(start),
        str(end),
    ])
    return "win-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
