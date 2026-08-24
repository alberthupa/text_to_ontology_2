"""Say what one source text mentions, before any ontology is opened.

Version one is deliberately modest and dependency-free: Unicode-aware
normalization, bounded runs of capitalized words, bounded short phrases, plain
repetition counting, and explicit weights for headings and early position. It
claims no semantic type. A capitalized span is a mention candidate, never a
Person or an Organization, and no record ever names an ontology resource.

The stop-word set and the heading test below are version-one English
heuristics, not language-independent analysis. A later classical, statistical,
or small-model implementation should replace the body of this module while
keeping the record it returns unchanged:

    {"text", "normalized", "kind", "weight", "origin", "position"}

`normalize()` and `text_phrases()` are shared with task context so that source
matching uses exactly the same word boundaries as source extraction.
"""

import re
import unicodedata


# One word is one run of word characters. Splitting on every other character
# lets "supply-chain" meet the label "supply chain", and lets a label meet
# "Forum's" without the possessive attached.
WORD = re.compile(r"\w+", re.UNICODE)

# A version-one English heuristic. A word here is never a concept on its own,
# and never begins or ends a phrase, but it may sit inside one.
STOP_WORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have
he her him his how i if in into is it its me my no nor not of on or our out
she should so than that the their them then there these they this those to
too was we were what when where which who will with would you your
""".split())

# Every limit this module obeys, in one place.
MAX_CHARACTERS = 200_000
MAX_TOKENS = 5_000
MAX_CONCEPTS = 40
MAX_PHRASE_TOKENS = 3
MAX_MENTION_TOKENS = 4
MAX_MATCH_TOKENS = 6
MIN_TOKEN_CHARACTERS = 2
HEADING_CHARACTERS = 80
EARLY_CHARACTERS = 400

# Every weight this module applies, in one place.
KIND_WEIGHT = {"mention": 3.0, "phrase": 2.0, "keyword": 1.0}
HEADING_BONUS = 2.0
REPEAT_WEIGHT = 0.5
MAX_REPEAT_BONUS = 3.0
EARLY_BONUS = 1.0


def normalize(text):
    """The matching form of any text: NFKC, case folded, words single spaced."""
    folded = unicodedata.normalize("NFKC", str(text)).casefold()
    return " ".join(WORD.findall(folded))


def is_heading(line):
    """A markdown heading, or a short title-like line that is not a sentence."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    return (len(stripped) <= HEADING_CHARACTERS
            and not stripped.endswith((".", "!", "?", ";", ",")))


def tokenize(text):
    """One record per word: its surface, its matching form, and where it sits."""
    tokens, offset = [], 0
    for line in text.split("\n"):
        heading = is_heading(line)
        for match in WORD.finditer(line):
            tokens.append({
                "surface": match.group(),
                "normalized": normalize(match.group()),
                "start": offset + match.start(),
                "end": offset + match.end(),
                "heading": heading,
            })
            if len(tokens) == MAX_TOKENS:
                return tokens
        offset += len(line) + 1
    return tokens


def adjacent(text, first, second):
    """Whether exactly one space separates two words, so they read as one run."""
    return text[first["end"]:second["start"]] == " "


def runs(text, tokens, longest):
    """Every run of two to `longest` words that reads as one uninterrupted span."""
    for index, first in enumerate(tokens):
        run = [first]
        for token in tokens[index + 1:index + longest]:
            if not adjacent(text, run[-1], token):
                break
            run.append(token)
            yield list(run)


def mention_spans(text, tokens):
    """Maximal bounded runs of capitalized words, as mention candidates."""
    run = []
    for token in tokens:
        capitalized = token["surface"][:1].isupper()
        continues = run and adjacent(text, run[-1], token) and len(run) < MAX_MENTION_TOKENS
        if capitalized and (not run or continues):
            run.append(token)
            continue
        if run:
            yield run
        run = [token] if capitalized else []
    if run:
        yield run


def signal(kind, run):
    """One reason to believe a form matters, at one place in the source."""
    return {
        "kind": kind,
        "text": " ".join(token["surface"] for token in run),
        "normalized": " ".join(token["normalized"] for token in run),
        "position": run[0]["start"],
        "heading": any(token["heading"] for token in run),
    }


def signals(text, tokens):
    """Every keyword, phrase, and mention this text offers, with duplicates."""
    for token in tokens:
        if (token["normalized"] not in STOP_WORDS
                and len(token["normalized"]) >= MIN_TOKEN_CHARACTERS):
            yield signal("keyword", [token])
    for run in runs(text, tokens, MAX_PHRASE_TOKENS):
        if run[0]["normalized"] in STOP_WORDS or run[-1]["normalized"] in STOP_WORDS:
            continue
        yield signal("phrase", run)
    for run in mention_spans(text, tokens):
        if len(run) == 1 and run[0]["normalized"] in STOP_WORDS:
            continue
        yield signal("mention", run)


def concept(records):
    """One record per form: strongest reason, earliest place, summed weight."""
    strongest = max(records, key=lambda record: KIND_WEIGHT[record["kind"]])
    earliest = min(records, key=lambda record: record["position"])
    heading = any(record["heading"] for record in records)
    occurrences = len({record["position"] for record in records})
    weight = (
        KIND_WEIGHT[strongest["kind"]]
        + min(REPEAT_WEIGHT * (occurrences - 1), MAX_REPEAT_BONUS)
        + (HEADING_BONUS if heading else 0.0)
        + (EARLY_BONUS if earliest["position"] < EARLY_CHARACTERS else 0.0)
    )
    return {
        "text": earliest["text"],
        "normalized": earliest["normalized"],
        "kind": strongest["kind"],
        "weight": round(weight, 3),
        "origin": ("heading" if heading else
                   "capitalized-span" if strongest["kind"] == "mention" else
                   "frequency"),
        "position": earliest["position"],
    }


def extract_source_concepts(text):
    """Return the deterministic concept records this one text supports."""
    text = str(text)[:MAX_CHARACTERS]
    if not text.strip():
        return []
    grouped = {}
    for record in signals(text, tokenize(text)):
        grouped.setdefault(record["normalized"], []).append(record)
    concepts = [concept(records) for records in grouped.values()]
    concepts.sort(key=lambda item: (
        -item["weight"], item["position"], item["normalized"]))
    return concepts[:MAX_CONCEPTS]


def text_phrases(text, longest=MAX_MATCH_TOKENS):
    """Every word run this text contains, mapped to where it first appears.

    Task context matches names against this index rather than against the raw
    string, so a name only ever matches whole words: the label "art" cannot
    match inside "particle", and "Berlin, Paris" is not the phrase
    "Berlin Paris".
    """
    text = str(text)[:MAX_CHARACTERS]
    tokens = tokenize(text)
    found = {}
    for token in tokens:
        found.setdefault(token["normalized"], token["start"])
    for run in runs(text, tokens, longest):
        found.setdefault(
            " ".join(token["normalized"] for token in run), run[0]["start"])
    return found
