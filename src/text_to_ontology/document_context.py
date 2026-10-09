"""What a window must know about its document, even when it does not say it.

A long note is cut into windows. Its title is only in the first window, and a
later window may talk about "the assistant" without ever naming it. Three
small blocks keep that context in every prompt of data-only ingestion:

    document header     path, title, enclosing headings, window k of n;
    document anchors    the projects, clients, ... this document has
                        already introduced (earlier windows);
    same folder         the projects, clients, ... already published from
                        other files of the same folder, with their ids.

"Anchor classes" are derived from the schema: every class that is the
subject of at least one relationship. Nothing is configured.

The header is a hint for reading, not evidence: a statement still has to be
supported by the text. Nothing here writes to a graph.
"""

from pathlib import PurePosixPath

from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .context_render import clean, field
from .graph_management import ONTO

MAX_TITLE_CHARACTERS = 200
MAX_ANCHORS = 8
MAX_FOLDER_ANCHORS = 5
MAX_LINKS_PER_ANCHOR = 5

HEADER_HEADING = "DOCUMENT CONTEXT — where this text comes from (a hint, not evidence)"
ANCHOR_HEADING = (
    "DOCUMENT ANCHORS (this document) — what earlier parts of this document "
    "are about.\nIf this part refers to one of them without naming it (\"the "
    "assistant\", \"the client\"), reuse its exact name and kind.")
FOLDER_HEADING = (
    "SAME FOLDER — already in the graph from other files in this folder.\n"
    "If this text is about one of them, set existing_id to its id.")


# ---------- the document header ----------

def _heading(line):
    """(level, text) for a Markdown heading line, else None."""
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    text = stripped[level:].strip()
    return (level, text) if text else None


def document_title(text):
    """The first Markdown heading, else the first non-empty line."""
    first_line = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        found = _heading(line)
        if found is not None:
            return clean(found[1])[:MAX_TITLE_CHARACTERS]
        if not first_line:
            first_line = line
    return clean(first_line)[:MAX_TITLE_CHARACTERS]


def heading_trail(text, start):
    """The headings in force where a window starts: '# A > ## B'."""
    trail = []
    for line in text[:start].splitlines():
        found = _heading(line)
        if found is None:
            continue
        level, heading = found
        trail = [item for item in trail if item[0] < level]
        trail.append((level, heading))
    return " > ".join(f"{'#' * level} {clean(heading)}"
                      for level, heading in trail)


def render_document_header(display_path, document_text, window, total):
    """The few lines that tell a window where its text comes from."""
    lines = [HEADER_HEADING, f"Path: {clean(display_path)}"]
    title = document_title(document_text)
    if title:
        lines.append(f"Title: {title}")
    trail = heading_trail(document_text, window.start)
    if trail:
        lines.append(f"Section: {field(trail)}")
    lines.append(f"Window: {window.index + 1} of {total}")
    return "\n".join(lines)


# ---------- anchors ----------

def anchor_classes(vocabulary):
    """Every declared class that is the subject of at least one relationship."""
    return {vocabulary.domains[iri] for iri in vocabulary.relations
            if iri in vocabulary.domains}


def is_anchor(graph, entity, vocabulary, anchors):
    """Whether an entity's kind is (a subclass of) an anchor class."""
    kind = graph.value(entity, ONTO.kind)
    if kind is None:
        return False
    class_iri = vocabulary.class_iri(str(kind))
    return any(vocabulary.is_a(class_iri, anchor) for anchor in anchors)


def _names(graph, entity):
    names = sorted({str(value) for predicate in (SKOS.prefLabel, SKOS.altLabel)
                    for value in graph.objects(entity, predicate)})
    preferred = graph.value(entity, SKOS.prefLabel)
    preferred = str(preferred) if preferred is not None else (
        names[0] if names else str(entity))
    return preferred, [name for name in names if name != preferred]


def _links(graph, entity):
    """The entity's links to other entities, as readable arrows."""
    found = []
    for predicate, other in graph.predicate_objects(entity):
        if (other, RDF.type, ONTO.Entity) in graph:
            found.append((predicate, other, False))
    for other, predicate in graph.subject_predicates(entity):
        if (other, RDF.type, ONTO.Entity) in graph:
            found.append((predicate, other, True))
    lines = []
    for predicate, other, incoming in sorted(found, key=lambda item: (
            str(item[0]), str(item[1]))):
        name = graph.value(predicate, RDFS.label) or str(predicate).rsplit(
            "/", 1)[-1]
        other_name = _names(graph, other)[0]
        lines.append(f"{other_name} --{name}--> (this)" if incoming
                     else f"(this) --{name}--> {other_name}")
    return lines[:MAX_LINKS_PER_ANCHOR]


def _card(graph, entity, with_id):
    preferred, aliases = _names(graph, entity)
    lines = [f"- name: {clean(preferred)}"]
    if with_id:
        lines.append(f"  id: {entity}")
    lines.append(f"  kind: {clean(graph.value(entity, ONTO.kind) or '')}")
    if aliases:
        lines.append(f"  aliases: {', '.join(clean(name) for name in aliases)}")
    for link in _links(graph, entity):
        lines.append(f"  link: {clean(link)}")
    return "\n".join(lines)


def _degree(graph, entity):
    return (sum(1 for _ in graph.triples((entity, None, None)))
            + sum(1 for _ in graph.triples((None, None, entity))))


def document_anchors(source_graph, vocabulary, limit=MAX_ANCHORS):
    """This document's anchor entities so far, most talked about first."""
    anchors = anchor_classes(vocabulary)
    found = [entity for entity in set(source_graph.subjects(RDF.type, ONTO.Entity))
             if is_anchor(source_graph, entity, vocabulary, anchors)]
    found.sort(key=lambda entity: (-_degree(source_graph, entity),
                                   _names(source_graph, entity)[0], str(entity)))
    return found[:limit]


def render_document_anchors(source_graph, vocabulary):
    """The anchor block, or '' when the document has none yet."""
    entities = document_anchors(source_graph, vocabulary)
    if not entities:
        return ""
    return "\n".join([ANCHOR_HEADING] + [
        _card(source_graph, entity, with_id=False) for entity in entities])


# ---------- the same folder ----------

def _folder(path):
    return PurePosixPath(str(path)).parent


def folder_anchors(graph, provenance, vocabulary, source_path,
                   limit=MAX_FOLDER_ANCHORS):
    """Canonical anchor entities published from other files in this folder.

    `graph` is the seed view (entities, kinds, names); `provenance` holds the
    links every published entity carries (`onto:sourceFile` to a file record
    with `onto:sourcePath`).
    """
    if not source_path:
        return []
    folder = _folder(source_path)
    files = {record for record, path
             in provenance.subject_objects(ONTO.sourcePath)
             if isinstance(path, Literal) and _folder(path) == folder
             and str(path) != str(source_path)}
    if not files:
        return []
    anchors = anchor_classes(vocabulary)
    counts = {}
    for entity, record in provenance.subject_objects(ONTO.sourceFile):
        if record in files and isinstance(entity, URIRef) \
                and (entity, RDF.type, ONTO.Entity) in graph \
                and is_anchor(graph, entity, vocabulary, anchors):
            counts[entity] = counts.get(entity, 0) + 1
    ordered = sorted(counts, key=lambda entity: (
        -counts[entity], _names(graph, entity)[0], str(entity)))
    return ordered[:limit]


def render_folder_anchors(graph, entities):
    """The same-folder block, or '' when there is nothing to show."""
    if not entities:
        return ""
    return "\n".join([FOLDER_HEADING] + [
        _card(graph, entity, with_id=True) for entity in entities])
