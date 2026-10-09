"""Expected links, and one targeted question for each one a document is missing.

Each window is extracted on its own, so a link that only becomes clear across
windows - the client named in the title, the project described four windows
later - is easily missed. After the last window of a document, this module
looks for *expected links* the document's entities still lack, and asks the
model about each one with only the passages that could answer it.

An expected link is a standard SHACL shape in the shapes graph:

    onto:expected/project-has-client a sh:NodeShape ;
        sh:targetClass class:project ;
        sh:property onto:expected/project-has-client/property .
    onto:expected/project-has-client/property
        sh:path relation:has-client ;
        sh:minCount 1 ;
        sh:severity sh:Warning ;
        sh:message "Which client is this project delivered for?" .

A warning never blocks a document. The answer is accepted only when its
evidence is quoted word for word from the passages; otherwise the gap is
reported as "not established" and nothing is added. Accepted answers become
one more "window" of the document, so staging, reconciliation, provenance,
and publication treat them like any other extraction.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SH, SKOS

from . import prompts
from .candidate_validation import validate_candidates
from .context_render import clean, field
from .document_context import render_document_header
from .entity_lookup import identity_key
from .graph_management import ONTO, RELATION
from .graph_merge import slug
from .graph_store import GraphNames, Publication, RdflibGraphStore
from .llm import InvalidResponseError
from .prompt_budget import estimate_tokens
from .source_concepts import normalize
from .vocabulary import read_vocabulary
from .windowing import TextWindow

EXPECTED = ONTO["expected/"]
MAX_LINK_CHECKS = 5
MAX_CANDIDATES = 20
PASSAGE_TOKENS = 2_500
MIN_EVIDENCE_CHARACTERS = 8


# ---------- expected links in the shapes graph ----------

def expected_link_shape(class_iri, relation_iri, question):
    """The SHACL warning shape for one expected link, as a small graph."""
    name = (f"{str(class_iri).rstrip('/').rsplit('/', 1)[-1]}-"
            f"{str(relation_iri).rstrip('/').rsplit('/', 1)[-1]}")
    shape = URIRef(f"{EXPECTED}{name}")
    rule = URIRef(f"{shape}/property")
    graph = Graph()
    graph.add((shape, RDF.type, SH.NodeShape))
    graph.add((shape, SH.targetClass, URIRef(class_iri)))
    graph.add((shape, SH.property, rule))
    graph.add((rule, SH.path, URIRef(relation_iri)))
    graph.add((rule, SH.minCount, Literal(1)))
    graph.add((rule, SH.severity, SH.Warning))
    graph.add((rule, SH.message, Literal(question)))
    return graph


def expected_links(shapes_graph):
    """Every expected link the shapes declare: minCount 1, severity Warning."""
    found = []
    for shape, class_iri in shapes_graph.subject_objects(SH.targetClass):
        for rule in shapes_graph.objects(shape, SH.property):
            if shapes_graph.value(rule, SH.severity) != SH.Warning:
                continue
            minimum = shapes_graph.value(rule, SH.minCount)
            path = shapes_graph.value(rule, SH.path)
            if minimum is None or int(minimum) < 1 or \
                    not isinstance(path, URIRef):
                continue
            message = shapes_graph.value(rule, SH.message)
            found.append({"class": str(class_iri), "relation": str(path),
                          "question": str(message) if message else ""})
    return sorted(found, key=lambda item: (item["class"], item["relation"]))


def add_expected_link(store, class_name, relation_name, question="",
                      names=None):
    """Declare one expected link by its readable names; returns the shape graph.

    The class and relationship must be declared by the starter, and the
    relationship must start at that class (or one of its parents).
    """
    names = names or GraphNames()
    schema = Graph()
    for name in names.schema_graphs:
        for triple in store.get(name):
            schema.add(triple)
    vocabulary = read_vocabulary(schema)
    if not vocabulary.declares_class(class_name):
        raise ValueError(f"{class_name!r} is not a declared class; use one of: "
                         + ", ".join(vocabulary.class_names))
    if not vocabulary.declares_relation(relation_name):
        raise ValueError(f"{relation_name!r} is not a declared relationship; "
                         "use one of: " + ", ".join(vocabulary.relation_names))
    class_iri = vocabulary.class_iri(class_name)
    relation_iri = vocabulary.relation_iri(relation_name)
    domain = vocabulary.domain_of(relation_iri)
    if domain is not None and not vocabulary.is_a(class_iri, domain):
        raise ValueError(f"{relation_name!r} starts at "
                         f"{vocabulary.label_of(domain)}, not at {class_name}")
    question = question or (f"Which {vocabulary.label_of(vocabulary.range_of(relation_iri) or '')}"
                            f" does this {class_name} have for "
                            f"{relation_name!r}?")
    shapes_name = names.shape_graphs[0]
    shapes = store.get(shapes_name)
    for triple in expected_link_shape(class_iri, relation_iri, question):
        shapes.add(triple)
    store.publish(Publication(graphs={shapes_name: shapes}))
    return shapes


# ---------- finding gaps ----------

def _kind_class(graph, entity, vocabulary):
    kind = graph.value(entity, ONTO.kind)
    return vocabulary.class_iri(str(kind)) if kind is not None else None


def _names(graph, entity):
    preferred = graph.value(entity, SKOS.prefLabel)
    others = sorted({str(name) for name in graph.objects(entity, SKOS.altLabel)})
    preferred = str(preferred) if preferred is not None else (
        others[0] if others else str(entity))
    return [preferred] + [name for name in others if name != preferred]


def _has_link(graph, entity, relation_iri, vocabulary):
    """Whether the entity already has the relationship, under either IRI form.

    Staging graphs name a relationship by the generated IRI; the canonical
    graph by the declared one. For a generated starter both are the same.
    """
    label = vocabulary.label_of(relation_iri)
    for predicate in (URIRef(relation_iri), RELATION[slug(label)]):
        if graph.value(entity, predicate) is not None:
            return True
    return False


def _canonical_twins(canonical, entity, source_graph):
    """Canonical entities with the same kind and a shared name."""
    kind = identity_key(source_graph.value(entity, ONTO.kind) or "")
    keys = {identity_key(name) for name in _names(source_graph, entity)}
    for other in canonical.subjects(RDF.type, ONTO.Entity):
        if identity_key(canonical.value(other, ONTO.kind) or "") != kind:
            continue
        if keys & {identity_key(name) for name in _names(canonical, other)}:
            yield other


def _degree(graph, entity):
    return (sum(1 for _ in graph.triples((entity, None, None)))
            + sum(1 for _ in graph.triples((None, None, entity))))


def find_gaps(source_graph, canonical, expected, vocabulary,
              limit=MAX_LINK_CHECKS):
    """Expected links this document's entities lack, most talked about first.

    A gap the canonical graph already fills (the same entity got its client
    from an earlier document) is not a gap.
    """
    gaps = []
    for entity in set(source_graph.subjects(RDF.type, ONTO.Entity)):
        class_iri = _kind_class(source_graph, entity, vocabulary)
        if class_iri is None:
            continue
        for link in expected:
            if not vocabulary.is_a(class_iri, link["class"]):
                continue
            if _has_link(source_graph, entity, link["relation"], vocabulary):
                continue
            if any(_has_link(canonical, twin, link["relation"], vocabulary)
                   for twin in _canonical_twins(canonical, entity,
                                                source_graph)):
                continue
            gaps.append({"entity": entity, **link})
    gaps.sort(key=lambda gap: (-_degree(source_graph, gap["entity"]),
                               _names(source_graph, gap["entity"])[0],
                               gap["relation"]))
    return gaps[:limit]


# ---------- what the model sees for one gap ----------

def _mentions(text, names):
    padded = f" {normalize(text)} "
    return any(f" {normalize(name)} " in padded for name in names
               if normalize(name))


def select_passages(windows, names, cap=PASSAGE_TOKENS,
                    count_tokens=estimate_tokens):
    """The first window plus every window that names one of `names`.

    Windows stay in document order and whole; the first window always comes
    first because it carries the title. Stops before the cap is exceeded.
    """
    chosen, used = [], 0
    for window in windows:
        if window.index != 0 and not _mentions(window.text, names):
            continue
        cost = count_tokens(window.text)
        if chosen and used + cost > cap:
            break
        chosen.append(window)
        used += cost
    return "\n...\n".join(window.text.strip() for window in chosen)


def object_candidates(source_graph, canonical, range_iri, vocabulary,
                      passages, limit=MAX_CANDIDATES):
    """Entities of the range class: this document's first, then the graph's.

    Entities the passages name come before the rest. Each candidate gets a
    short key (c1, c2, ...) for the model to answer with.
    """
    found = []
    for graph, canonical_entity in ((source_graph, False), (canonical, True)):
        for entity in sorted(set(graph.subjects(RDF.type, ONTO.Entity)), key=str):
            class_iri = _kind_class(graph, entity, vocabulary)
            if class_iri is None or (range_iri is not None and
                                     not vocabulary.is_a(class_iri, range_iri)):
                continue
            names = _names(graph, entity)
            found.append({
                "names": names,
                "kind": str(graph.value(entity, ONTO.kind)),
                "existing_id": str(entity) if canonical_entity else None,
                "named": _mentions(passages, names),
            })
    found.sort(key=lambda item: (not item["named"], item["existing_id"] is not None,
                                 item["names"][0].lower()))
    unique, seen = [], set()
    for item in found:
        key = (identity_key(item["kind"]), identity_key(item["names"][0]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    for number, item in enumerate(unique[:limit], start=1):
        item["key"] = f"c{number}"
    return unique[:limit]


def _render_entity(names, kind, key=None, existing_id=None):
    line = f"- {key + ': ' if key else ''}{clean(names[0])} (kind: {clean(kind)})"
    if len(names) > 1:
        line += f"; also called {', '.join(clean(name) for name in names[1:])}"
    if existing_id:
        line += "; already in the graph"
    return line


def link_check_prompt(gap, source_graph, vocabulary, candidates, passages,
                      library=None):
    """The rendered `link_check_user` prompt for one gap."""
    entity = gap["entity"]
    relation = gap["relation"]
    relation_line = (
        f"{vocabulary.label_of(vocabulary.domain_of(relation) or '')} "
        f"--{vocabulary.label_of(relation)}--> "
        f"{vocabulary.label_of(vocabulary.range_of(relation) or '')}")
    return prompts.render("link_check_user", {
        "question": field(gap["question"] or relation_line),
        "relation": clean(relation_line),
        "subject": _render_entity(_names(source_graph, entity),
                                  str(source_graph.value(entity, ONTO.kind))),
        "candidates": "\n".join(
            _render_entity(item["names"], item["kind"], item["key"],
                           item["existing_id"]) for item in candidates)
        or "(none)",
        "passages": passages,
    }, library=library)


# ---------- the answer ----------

def _folded(text):
    return " ".join(str(text).casefold().split())


def read_answer(answer, gap, source_graph, vocabulary, candidates, passages):
    """Turn a link-check answer into an ordinary extraction package.

    Returns (candidates dict or None, dropped notes). A link survives only
    when it names a listed candidate, has a confidence, and quotes its
    evidence word for word from the passages.
    """
    dropped = []
    links = answer.get("links") if isinstance(answer, dict) else None
    if not isinstance(links, list):
        return None, ["answer has no 'links' list"]
    by_key = {item["key"]: item for item in candidates}
    folded_passages = _folded(passages)
    entity = gap["entity"]
    subject_names = _names(source_graph, entity)
    package = {"entities": [], "relations": [], "facts": []}
    for link in links:
        if not isinstance(link, dict) or link.get("object") not in by_key:
            dropped.append(f"unknown candidate in {link!r}")
            continue
        confidence = link.get("confidence")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            dropped.append(f"no valid confidence in {link!r}")
            continue
        evidence = str(link.get("evidence") or "")
        if len(evidence.strip()) < MIN_EVIDENCE_CHARACTERS or \
                _folded(evidence) not in folded_passages:
            dropped.append(f"link_check.unsupported_evidence: {evidence!r}")
            continue
        target = by_key[link["object"]]
        if not package["entities"]:
            package["entities"].append({
                "id": "s", "name": subject_names[0],
                "kind": str(source_graph.value(entity, ONTO.kind)),
                "aliases": subject_names[1:], "existing_id": None,
                "confidence": confidence})
        package["entities"].append({
            "id": link["object"], "name": target["names"][0],
            "kind": target["kind"], "aliases": target["names"][1:],
            "existing_id": target["existing_id"], "confidence": confidence})
        package["relations"].append({
            "subject": "s", "predicate": vocabulary.label_of(gap["relation"]),
            "object": link["object"], "confidence": confidence})
    if not package["relations"]:
        return None, dropped
    return package, dropped


def link_window(document, gap, passages, index):
    """A synthetic window carrying one gap's passages, with a stable id."""
    digest = hashlib.sha256(
        f"{document.document_id}|{gap['entity']}|{gap['relation']}"
        .encode("utf-8")).hexdigest()[:16]
    return TextWindow(
        window_id=f"link-{digest}", document_id=document.document_id,
        index=index, text=passages, start=0, end=0,
        token_estimate=estimate_tokens(passages), strategy_version=0)


def check_document_links(document, display_path, windows, source_graph,
                         canonical, expected, vocabulary, extractor,
                         reporter=None, library=None,
                         limit=MAX_LINK_CHECKS):
    """Ask about every gap; return the accepted packages and a summary.

    Each accepted package is (synthetic window, validated candidates) ready
    for the same admission as an ordinary window.
    """
    summary = {"gaps": 0, "filled": [], "not_established": [], "dropped": []}
    packages = []
    if not expected:
        return packages, summary
    gaps = find_gaps(source_graph, canonical, expected, vocabulary, limit)
    summary["gaps"] = len(gaps)
    system_prompt = prompts.render("extraction_system", library=library)
    for number, gap in enumerate(gaps):
        label = (f"{_names(source_graph, gap['entity'])[0]} "
                 f"--{vocabulary.label_of(gap['relation'])}--> ?")
        header = render_document_header(
            display_path, document.text, windows[0], len(windows))
        probe = "\n".join(window.text for window in windows)
        candidates = object_candidates(
            source_graph, canonical, vocabulary.range_of(gap["relation"]),
            vocabulary, probe)
        names = _names(source_graph, gap["entity"]) + [
            name for item in candidates for name in item["names"]]
        passages = header + "\n\n" + select_passages(windows, names)
        prompt = link_check_prompt(gap, source_graph, vocabulary, candidates,
                                   passages, library=library)
        if reporter is not None:
            reporter.llm_input(system_prompt, prompt)
        try:
            answer = extractor.extract(prompt)
        except InvalidResponseError as failure:
            summary["dropped"].append(f"{label}: {failure}")
            summary["not_established"].append(label)
            continue
        package, dropped = read_answer(answer, gap, source_graph, vocabulary,
                                       candidates, passages)
        summary["dropped"] += [f"{label}: {note}" for note in dropped]
        if package is None:
            summary["not_established"].append(label)
            continue
        validation = validate_candidates(
            package, canonical,
            [item["existing_id"] for item in candidates if item["existing_id"]],
            vocabulary=vocabulary)
        if not validation["valid"]:
            summary["dropped"] += [f"{label}: {issue['message']}"
                                   for issue in validation["issues"]
                                   if issue["severity"] == "error"]
            summary["not_established"].append(label)
            continue
        window = link_window(document, gap, passages, len(windows) + number)
        packages.append((window, validation["candidates"]))
        summary["filled"].append(
            label.replace("?", ", ".join(
                record["name"] for record in validation["candidates"]["entities"]
                if record["id"] != "s")))
    return packages, summary


# ---------- the command line ----------

def main(argv=None):
    """`text-to-ontology-expect`: declare or list expected links."""
    parser = argparse.ArgumentParser(
        description="Declare a link every entity of a class should have. "
                    "After each document, a missing one is looked for once.")
    parser.add_argument("graph", type=Path, help="the TriG dataset")
    parser.add_argument("class_name", nargs="?", help='e.g. "Project"')
    parser.add_argument("relation_name", nargs="?", help='e.g. "has client"')
    parser.add_argument("question", nargs="?", default="",
                        help="the question to ask, e.g. \"Which client is "
                             "this project delivered for?\"")
    parser.add_argument("--list", action="store_true",
                        help="show the expected links and exit")
    args = parser.parse_args(argv)
    store = RdflibGraphStore(path=args.graph)
    names = GraphNames()
    if args.list or not args.class_name:
        shapes = Graph()
        for name in names.shape_graphs:
            for triple in store.get(name):
                shapes.add(triple)
        for link in expected_links(shapes):
            print(f"{link['class']} --{link['relation']}--> "
                  f"(at least one)  {link['question']}")
        return
    if not args.relation_name:
        parser.error("give a class and a relationship, or --list")
    try:
        add_expected_link(store, args.class_name, args.relation_name,
                          args.question, names)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"Expected: every {args.class_name} has at least one "
          f"{args.relation_name!r}.")
