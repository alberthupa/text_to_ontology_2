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

from dataclasses import dataclass, field

from rdflib import BNode, Dataset, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .graph_management import BASE
from .prompt_budget import estimate_tokens
from .task_context import build_task_context

# One scope is meant to be read by a person and by a model, so it stays small.
MAX_TRIPLES = 300
MAX_TOKENS = 2500
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
        """Compact, labelled lines, capped by whole triples."""
        budget = budget or MAX_TOKENS
        lines, used, dropped = [], 0, 0
        for triple in self.triples:
            line = describe(triple, graph)
            cost = estimate_tokens(line)
            if used + cost > budget:
                dropped += 1
                continue
            lines.append(line)
            used += cost
        return {"text": "\n".join(lines), "triples": len(lines),
                "dropped": dropped + self.dropped, "tokens": used}

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
    nodes, focus_source = _focus(matched, carry_over, graph, limits["focus"])
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
        },
    )


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


def describe(triple, graph=None):
    """One readable line for one triple: qnames plus labels where there are any."""
    subject, predicate, object_ = triple
    return " ".join((_term(subject, graph), _term(predicate, graph),
                     _term(object_, graph)))


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
    if graph is None:
        return str(uri)
    try:
        return graph.namespace_manager.normalizeUri(uri)
    except Exception:                                        # noqa: BLE001
        return str(uri)


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
