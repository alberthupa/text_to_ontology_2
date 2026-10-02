"""The relevant part of the graph for one question.

A chat turn must not send the whole dataset to a model, and a reader must be
able to see exactly which part was sent. This module turns one topic text into
a small, deterministic subgraph:

  1. `task_context.build_task_context(text, graph)` selects what the text is
     about (classes, properties, patterns, resources, examples) - the same
     read-only relevance layer extraction uses;
  2. the statements around the selected resources are collected (one hop,
     subject or object), most relevant first;
  3. the declarations and labels of everything the collection mentions are
     added, so the model can read the subgraph without guessing;
  4. the whole thing is capped by whole triples and reported, never sliced.

The result carries three faces: `trig_text()` for the viewer, `view()` as a
declarative directive a frontend applies, and `render_for_model()` as compact
lines for the prompt or the transcript. Nothing here writes to a graph.
"""

import re
from dataclasses import dataclass, field

from rdflib import BNode, Dataset, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from .graph_management import BASE
from .prompt_budget import estimate_tokens
from .task_context import build_task_context

# One scope is meant to be read by a person and by a model, so it stays small.
# The token ceiling is what a model is handed: at 2500 tokens the compact
# renderer fits about 69 triples, which was not enough to list the twelve
# instances of one class in the reference graph. 6000 fits that whole scope.
MAX_TRIPLES = 300
MAX_TOKENS = 6000
MAX_FOCUS = 20
SCOPE_GRAPH = URIRef(BASE + "graphs/scope")
SCOPE_FILE = "scope.trig"
DECLARATION_PREDICATES = (RDF.type, RDFS.label, RDFS.comment, RDFS.domain,
                          RDFS.range, RDFS.subClassOf, SKOS.prefLabel,
                          SKOS.altLabel)
DEFAULT_LIMITS = {"triples": MAX_TRIPLES, "focus": MAX_FOCUS,
                  "tokens": MAX_TOKENS}


@dataclass(frozen=True)
class Scope:
    """One question's subgraph, and how to show or send it."""

    question: str
    nodes: tuple = ()          # the resources the question matched, in order
    triples: tuple = ()        # the subgraph itself, deterministic order
    dropped: int = 0
    focus_source: str = "matched"
    diagnostics: dict = field(default_factory=dict)

    # ---------- for a viewer ----------

    def trig_text(self):
        """The subgraph as one TriG document with a named graph."""
        data = Dataset()
        for prefix, namespace in _prefixes():
            data.bind(prefix, namespace)
        for subject, predicate, object_ in self.triples:
            data.add((subject, predicate, object_, SCOPE_GRAPH))
        return data.serialize(format="trig")

    def view(self, file_name=SCOPE_FILE):
        """The directive a frontend applies to show exactly this subgraph."""
        return {
            "replace": [file_name],
            "files": [{"name": file_name, "trig": self.trig_text()}],
            "mode": "instances",
            "clearFilters": True,
            "hideIsolated": False,
            "focus": str(self.nodes[0]) if self.nodes else None,
        }

    # ---------- for a model or a transcript ----------

    def render_for_model(self, budget=None, graph=None):
        """Compact lines for a model: prefixes and names once, then statements.

        Two things were throwing away most of the budget: every URI written out
        in full, and every subject's label repeated on every line. So the
        renderer first writes a small PREFIXES block and a NAMES block (each
        name once, quoted), and the statements below use short prefixed names.
        The header is charged to the budget first; whole triples are dropped
        when it runs out, and the count is reported.
        """
        budget = budget or MAX_TOKENS
        prefixes = _namespace_map(self.triples, graph)
        header, named, names_dropped = _header(
            self.triples, graph, prefixes)
        used = estimate_tokens(header) if header else 0
        lines, dropped = [], 0
        for triple in self.triples:
            line = statement(triple, prefixes)
            cost = estimate_tokens(line)
            if used + cost > budget:
                dropped += 1
                continue
            lines.append(line)
            used += cost
        body = "\n".join(lines)
        text = f"{header}\n\n{body}" if header else body
        return {"text": text, "triples": len(lines),
                "dropped": dropped + self.dropped, "tokens": used,
                "named": named, "names_dropped": names_dropped,
                "prefixes": len(prefixes)}

    def summary(self):
        """One line a frontend can show next to the answer."""
        return {
            "question": self.question,
            "nodes": [str(node) for node in self.nodes],
            "triples": len(self.triples),
            "dropped": self.dropped,
            "focus_source": self.focus_source,
            "diagnostics": dict(self.diagnostics),
        }


def select(text, graph, carry_over=(), limits=None):
    """The subgraph one question justifies, and why."""
    limits = dict(DEFAULT_LIMITS, **(limits or {}))
    context = build_task_context(text, graph)
    # Context items wrap their card under "value"; the card carries "uri".
    matched = [URIRef(item["value"]["uri"]) for item in context["resources"]
               if (item.get("value") or {}).get("uri")]
    loose = False
    if not matched:
        # The strict layer matches whole words, so "tools" misses a class
        # labelled "Tool". That is worth one bounded fallback.
        matched = loose_matches(text, graph, limits["focus"])
        loose = bool(matched)
    nodes, focus_source = _focus(matched, carry_over, graph, limits["focus"])
    if loose and nodes:
        focus_source = "loose"
    triples, dropped = _collect(graph, nodes, context, limits["triples"])
    return Scope(
        question=text,
        nodes=tuple(nodes),
        triples=tuple(triples),
        dropped=dropped,
        focus_source=focus_source,
        diagnostics={
            "matched": len(matched),
            "carried_over": len([node for node in carry_over]),
            "concepts": len(context["concepts"]),
            "loose": loose,
        },
    )


def loose_matches(text, graph, limit=MAX_FOCUS):
    """Individuals the question names, tolerating a plural or a suffix.

    Used only when the strict selection found nothing: the question's words
    (and their singular forms) are looked up in the labels of what the graph
    names. A word that matches a *class* brings that class's instances, which
    is what a person means by "what tools does the library have".
    """
    words = set()
    for word in re.findall(r"[a-z0-9]+", str(text).lower()):
        if len(word) > 2:
            words |= _word_forms(word)
    if not words:
        return []

    labelled = sorted(_labelled(graph), key=lambda pair: (pair[0], str(pair[1])))
    chosen, seen = [], set()

    def add(uri):
        if isinstance(uri, URIRef) and uri not in seen:
            seen.add(uri)
            chosen.append(uri)

    for label, subject in labelled:
        tokens = set(re.findall(r"[a-z0-9]+", label.lower()))
        if not tokens & words:
            continue
        if (subject, RDF.type, OWL.Class) in graph:
            instances = _instances_of(graph, subject)
            if instances:
                for instance in instances:
                    add(instance)
                    if len(chosen) >= limit:
                        return chosen
            else:
                # A class nobody instantiates yet is still worth showing.
                add(subject)
        else:
            add(subject)
        if len(chosen) >= limit:
            break
    return chosen


def _instances_of(graph, class_uri, depth=1):
    """Direct instances of a class, and of its subclasses, in a stable order."""
    classes, frontier, seen = [class_uri], [class_uri], {class_uri}
    for _hop in range(max(0, depth)):
        below = []
        for parent in frontier:
            for child in graph.subjects(RDFS.subClassOf, parent):
                if isinstance(child, URIRef) and child not in seen:
                    seen.add(child)
                    classes.append(child)
                    below.append(child)
        frontier = below
    found = set()
    for item in classes:
        found |= {instance for instance in graph.subjects(RDF.type, item)
                  if isinstance(instance, URIRef)}
    return sorted(found, key=str)


def _word_forms(word):
    """A word and the singular forms a person would expect it to match."""
    forms = {word}
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        forms.add(word[:-1])
    return forms


def _labelled(graph):
    """(text, subject) for everything the graph gives a name, read only."""
    for _s, predicate, label in graph.triples((None, None, None)):
        if predicate not in (RDFS.label, SKOS.prefLabel, SKOS.altLabel):
            continue
        if isinstance(label, Literal):
            yield str(label), label and _s


def _focus(matched, carry_over, graph, limit):
    """The resources to expand: what matched now, else what was discussed."""
    chosen, seen = [], set()

    def add(uri):
        uri = URIRef(uri)
        if uri in seen or (uri, None, None) not in graph:
            return
        seen.add(uri)
        chosen.append(uri)

    for uri in matched:
        add(uri)
    source = "matched" if chosen else "carried"
    for uri in carry_over:
        add(uri)
    if not chosen:
        source = "empty"
    return chosen[:limit], source


def _collect(graph, nodes, context, limit):
    """Statements around the focus, the declarations they rely on, then the rest.

    Each focus node gets a fair share first, so one well-connected hub cannot
    eat the whole scope before the schema and labels are added; anything left
    over fills the remaining room in the same deterministic order.
    """
    found, seen, deferred = [], set(), []

    def add(triple):
        if triple in seen:
            return False
        seen.add(triple)
        found.append(triple)
        return True

    # A slice of the scope is kept for the schema and labels: one very
    # well-connected node must not push the declarations out.
    reserve = min(60, max(10, limit // 5))
    per_node = max(5, (limit - reserve) // len(nodes)) if nodes else limit
    for node in nodes:
        taken = 0
        for triple in _statements(graph, node):
            if triple in seen:
                continue
            if taken < per_node and add(triple):
                taken += 1
            else:
                deferred.append(triple)

    # The pattern evidence the selection already found is worth keeping.
    for item in context["examples"]:
        value = item.get("value") or {}
        if {"subject", "predicate", "object"} <= set(value):
            add((value["subject"], value["predicate"], value["object"]))

    # Declarations and labels of everything mentioned, so nothing is a mystery.
    mentioned = sorted({term for triple in found for term in triple
                        if isinstance(term, URIRef)
                        and not isinstance(term, BNode)}, key=str)
    for uri in mentioned:
        for predicate in DECLARATION_PREDICATES:
            for object_ in graph.objects(uri, predicate):
                add((uri, predicate, object_))

    for triple in deferred:
        add(triple)

    dropped = max(0, len(found) - limit)
    return found[:limit], dropped


def _statements(graph, node):
    """Every statement of one node, in a stable and useful order.

    Types and labels come first, so a node that names a class always brings
    that class into the scope; then the ordinary statements; then everything
    that points at the node. Without the ranking, one busy predicate can fill a
    node's whole share and the type triple never makes it in.
    """
    def rank(predicate):
        if predicate == RDF.type:
            return 0
        if predicate in (RDFS.label, SKOS.prefLabel, SKOS.altLabel):
            return 1
        return 2

    outward = sorted(graph.predicate_objects(node),
                     key=lambda pair: (rank(pair[0]), str(pair[0]),
                                       str(pair[1])))
    inward = sorted(graph.subject_predicates(node),
                    key=lambda pair: (str(pair[1]), str(pair[0])))
    return ([(node, predicate, object_) for predicate, object_ in outward]
            + [(subject, predicate, node) for subject, predicate in inward])


MAX_NAMES = 60


def _header(triples, graph, prefixes, limit=MAX_NAMES):
    """The PREFIXES and NAMES blocks, charged to the budget before statements.

    The prefixes are what let a model write an edit proposal with real IRIs;
    the names are what keep every statement short.
    """
    blocks = []
    if prefixes:
        blocks.append("PREFIXES\n" + "\n".join(
            f"{prefix} = <{namespace}>"
            for namespace, prefix in sorted(prefixes.items())))
    named, seen = [], set()
    for triple in triples:
        for term in (triple[0], triple[2]):
            if not isinstance(term, URIRef) or term in seen:
                continue
            seen.add(term)
            label = label_of(term, graph)
            if label and label != _qname(term, prefixes):
                named.append(f'{_qname(term, prefixes)} = "{label}"')
    named.sort()
    dropped = max(0, len(named) - limit)
    names = named[:limit]
    if names:
        blocks.append("NAMES\n" + "\n".join(names))
    return "\n\n".join(blocks), len(names), dropped


def _namespace_map(triples, graph=None):
    """{namespace IRI: prefix} for exactly the namespaces these triples use.

    The graph's own prefixes are used where it has them (so an imported
    ontology keeps `lib:`), and a stable `ns1`, `ns2`, ... otherwise, assigned
    in sorted namespace order so the same subgraph always renders the same way.
    """
    known = {}
    if graph is not None:
        try:
            for prefix, namespace in graph.namespaces():
                known.setdefault(str(namespace), prefix or None)
        except Exception:                                    # noqa: BLE001
            pass
    for prefix, namespace in _prefixes():
        known.setdefault(str(namespace), prefix)
    used = {prefix for prefix in known.values() if prefix}
    found = sorted({_namespace_of(term) for triple in triples for term in triple
                    if isinstance(term, URIRef) and _namespace_of(term)})
    # Decide a name for each namespace first, then resolve collisions among
    # those names only: a default binding for a namespace that is not in this
    # subgraph (say an unrelated `geo` for OpenGIS) must not force `ns1`.
    intended = {}
    for namespace in found:
        prefix = known.get(namespace) or ""
        if not prefix or re.fullmatch(r"ns\d+", prefix):
            prefix = _prefix_candidate(namespace) or ""
        intended[namespace] = prefix
    prefixes, chosen = {}, set()
    for index, namespace in enumerate(found, start=1):
        prefix = intended[namespace]
        if not prefix or prefix in chosen:
            prefix = f"ns{index}"
            while prefix in chosen:
                prefix += "x"
        chosen.add(prefix)
        prefixes[namespace] = prefix
    return prefixes


def _prefix_candidate(namespace):
    """A readable prefix from a namespace nobody named: `.../geo#` -> `geo`."""
    stem = str(namespace).rstrip("#/").rpartition("/")[2]
    stem = re.sub(r"[^A-Za-z0-9_-]", "", stem)
    if not stem or not stem[0].isalpha() or stem.lower() in ("http", "https",
                                                             "www"):
        return ""
    return stem.lower()


def _namespace_of(uri):
    """The namespace half of an IRI: up to the last # or /."""
    text = str(uri)
    for separator in ("#", "/"):
        if separator in text:
            head, _, tail = text.rpartition(separator)
            if tail:
                return head + separator
    return ""


def _qname(uri, prefixes):
    """One IRI as prefix:local, or in angle brackets when nothing fits."""
    namespace = _namespace_of(uri)
    prefix = prefixes.get(namespace)
    if prefix:
        return f"{prefix}:{str(uri)[len(namespace):]}"
    return f"<{uri}>"


def statement(triple, prefixes):
    """One short line for one triple: prefixed names, a literal as written."""
    subject, predicate, object_ = triple
    if predicate == RDF.type:
        return f"{_qname(subject, prefixes)} a {_qname(object_, prefixes)}"
    return " ".join((_qname(subject, prefixes), _qname(predicate, prefixes),
                     _literal_text(object_, prefixes)))


def describe(triple, graph=None):
    """One readable line for one triple, for a human rather than a budget."""
    subject, predicate, object_ = triple
    return " ".join((_term(subject, graph), _term(predicate, graph),
                     _term(object_, graph)))


def _literal_text(term, prefixes=None):
    if isinstance(term, Literal):
        text = str(term).replace("\n", " ")
        if term.language:
            return f'"{text}"@{term.language}'
        return f'"{text}"'
    if isinstance(term, BNode):
        return f"_:{term}"
    return _qname(term, prefixes or {})


def _term(term, graph=None):
    if isinstance(term, Literal):
        text = str(term)
        if term.language:
            return f'"{text}"@{term.language}'
        if term.datatype:
            return f'"{text}"^^<{term.datatype}>'
        return f'"{text}"'
    if isinstance(term, BNode):
        return f"_:{term}"
    name = _short(term, graph)
    label = label_of(term, graph) if graph is not None else None
    return f"{name} \"{label}\"" if label and label != name else name


def label_of(uri, graph):
    """The preferred label of one resource, or None."""
    if graph is None:
        return None
    for predicate in (SKOS.prefLabel, RDFS.label):
        value = graph.value(uri, predicate)
        if value is not None:
            return str(value)
    return None


def _short(uri, graph=None):
    """A prefixed name for one IRI, from the graph or from the project's own.

    The graph's own prefixes win; the project namespaces are the fallback, so a
    graph nobody bound (a test fixture, a plain parsed file) still renders
    `class:threat` instead of the whole IRI.
    """
    text = str(uri)
    if graph is not None:
        try:
            short = graph.namespace_manager.normalizeUri(uri)
            if short != text and not short.startswith("<"):
                return short
        except Exception:                                    # noqa: BLE001
            pass
    for prefix, namespace in _prefixes():
        base = str(namespace)
        if text.startswith(base) and len(text) > len(base):
            return f"{prefix}:{text[len(base):]}"
    return f"<{text}>"


def _prefixes():
    """The prefixes a scope document carries, so it reads well."""
    from .graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
    from rdflib.namespace import OWL, SH, XSD
    return (("onto", ONTO), ("entity", ENTITY), ("class", CLASS),
            ("relation", RELATION), ("fact", FACT), ("owl", OWL), ("rdf", RDF),
            ("rdfs", RDFS), ("skos", SKOS), ("sh", SH), ("xsd", XSD))


def parse_trig(text):
    """Read a scope document back; used by tests and by frontends that check."""
    data = Dataset()
    data.parse(data=text, format="trig")
    graph = Graph()
    for subject, predicate, object_, _name in data.quads((None, None, None, None)):
        graph.add((subject, predicate, object_))
    return graph
