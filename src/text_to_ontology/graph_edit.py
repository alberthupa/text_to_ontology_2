"""Change the graph by hand, or from a proposal: parse, check, preview, apply.

An edit is a small patch, written the way a person writes Turtle:

    # additions are plain Turtle
    entity:new-thing a class:Tool ;
        skos:prefLabel "New thing" .

    # removals are the same statement on a line that starts with "-"
    - entity:old-thing skos:prefLabel "Old thing" .

Nothing is applied by parsing alone. `preview` parses and checks the patch and
returns a diff plus a stable `patch_id`; `apply` takes that id and writes the
exact triples that were previewed, so what a person saw is what lands. The
patch is checked for:

  * a removal that is not in the graph (a warning: the target state is still
    reached),
  * new classes or properties, which need `allow_new_vocabulary` (the same
    data-only rule ingestion follows; off by default),
  * statements that use a class or property nothing declares (an error while
    the vocabulary is frozen, a warning when it is not),
  * an IRI used as both a class and a property,
  * SHACL violations in the proposed data graph (warnings: a hand edit is the
    author's call, but they should see what the shapes say).

Every applied edit leaves deterministic PROV evidence: one `prov:Activity` per
patch and one `rdf:Statement` per added or removed triple.
"""

import hashlib
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS

from .candidate_graph import CANDIDATE_BASE
from .graph_management import ONTO, bind
from .graph_store import GraphNames, Publication
from .source_validation import validate_source_graph
from .starter import parse_rdf
from .vocabulary import read_vocabulary

EDIT_BASE = CANDIDATE_BASE + "edit/"
REMOVAL = "-"
PREVIEW_LIMIT = 40
VOCABULARY_TYPES = (OWL.Class, RDFS.Class, OWL.ObjectProperty,
                    OWL.DatatypeProperty)
SYSTEM_NAMESPACES = ("http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                     "http://www.w3.org/2000/01/rdf-schema#",
                     "http://www.w3.org/2002/07/owl#",
                     "http://www.w3.org/2004/02/skos/core#",
                     "http://www.w3.org/ns/shacl#",
                     "http://www.w3.org/ns/prov#")


@dataclass(frozen=True)
class Patch:
    """One checked patch: exactly the triples a preview promised."""

    text: str
    added: tuple = ()
    removed: tuple = ()
    errors: tuple = ()
    warnings: tuple = ()
    source: str = "hand"
    allow_new_vocabulary: bool = False
    patch_id: str = ""

    @property
    def ok(self):
        return not self.errors

    def counts(self):
        present = [triple for triple in self.removed]
        return {"added": len(self.added), "removed": len(present),
                "errors": len(self.errors), "warnings": len(self.warnings)}

    def sample(self, limit=PREVIEW_LIMIT):
        """A few lines of each side, for a preview a person can read."""
        return {
            "added": [_line(triple) for triple in self.added[:limit]],
            "removed": [_line(triple) for triple in self.removed[:limit]],
            "more_added": max(0, len(self.added) - limit),
            "more_removed": max(0, len(self.removed) - limit),
        }

    def summary(self):
        return {"ok": self.ok, "patch_id": self.patch_id,
                "counts": self.counts(), "errors": list(self.errors),
                "warnings": list(self.warnings), "sample": self.sample(),
                "source": self.source,
                "allow_new_vocabulary": self.allow_new_vocabulary}


# ---------- parsing ----------

def parse_patch(text):
    """Split a patch into the triples to add and the triples to remove.

    Prefix declarations are shared: they are written once at the top of the
    patch and prepended to every removal line, so a removal reads like the
    statement it deletes.
    """
    lines = str(text or "").splitlines()
    prefixes = [line for line in lines if _is_prefix(line)]
    added_lines, removal_lines = [], []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or _is_prefix(raw):
            continue
        if stripped.startswith(REMOVAL) and stripped[1:2].isspace():
            removal_lines.append(stripped[2:].strip())
        else:
            added_lines.append(raw)
    added, errors = _parse_added(prefixes, added_lines)
    removed, removal_errors = _parse_removals(prefixes, removal_lines)
    return added, removed, tuple(errors + removal_errors)


def _is_prefix(line):
    stripped = line.strip().lower()
    return stripped.startswith(("@prefix", "@base", "prefix ", "base "))


def _parse_added(prefixes, added_lines):
    if not added_lines:
        return (), ()
    return _parse_turtle("\n".join(prefixes + added_lines))


def _parse_turtle(text):
    try:
        _format, parsed = parse_rdf(text, "patch.ttl")
    except ValueError as error:
        return (), (str(error),)
    return tuple(_as_triples(parsed)), ()


def _parse_removals(prefixes, lines):
    removed, errors = [], []
    for line in lines:
        statement = line if line.endswith(".") else line + " ."
        triples, problems = _parse_turtle("\n".join(prefixes + [statement]))
        if problems:
            errors.append(f"cannot read the removal {line!r}: {problems[0]}")
        elif len(triples) != 1:
            errors.append(f"a removal line names exactly one triple: {line!r}")
        else:
            removed.append(triples[0])
    return tuple(removed), tuple(errors)


def _line(triple):
    """One triple as a readable line, for a diff a person reads."""
    return " ".join(term.n3() for term in triple)


def _as_triples(parsed):
    if hasattr(parsed, "quads"):
        return [(s, p, o) for s, p, o, _g in
                parsed.quads((None, None, None, None))]
    return list(parsed)


def fenced_turtle(text):
    """Every ```turtle fenced block of an answer, in order."""
    blocks, current = [], None
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if current is None and stripped.startswith("```"):
            if stripped[3:].strip().lower() in ("", "turtle", "ttl", "trig"):
                current = []
            continue
        if current is not None:
            if stripped.startswith("```"):
                blocks.append("\n".join(current).strip())
                current = None
            else:
                current.append(line)
    if current is not None and any(line.strip() for line in current):
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


# ---------- checking ----------

def check_patch(graph, added, removed, allow_new_vocabulary=False, shapes=()):
    """Everything wrong or worth knowing about one patch, read only."""
    errors, warnings = [], []
    vocabulary = read_vocabulary(graph)

    missing = [triple for triple in removed if triple not in graph]
    if missing:
        warnings.append(
            f"{len(missing)} removal(s) are not in the graph, so they change "
            f"nothing (for example {_line(missing[0])})")

    declarations = {triple[0] for triple in added
                    if triple[1] == RDF.type and triple[2] in VOCABULARY_TYPES}
    known = set(declarations)
    if not allow_new_vocabulary:
        fresh = sorted(str(iri) for iri in declarations
                       if str(iri) not in set(vocabulary.classes)
                       and str(iri) not in set(vocabulary.relations)
                       and str(iri) not in set(vocabulary.facts))
        if fresh:
            errors.append(
                "the patch declares new classes or properties "
                f"({', '.join(fresh[:5])}); tick 'allow new classes and "
                "relations' if that is what you want")

    known_classes = set(vocabulary.classes) | {str(iri) for iri in declarations}
    known_properties = (set(vocabulary.relations) | set(vocabulary.facts)
                        | {str(iri) for iri in declarations})
    undeclared_classes, undeclared_properties = set(), set()
    for _s, predicate, object_ in added:
        if predicate == RDF.type and isinstance(object_, URIRef) \
                and not _system(object_):
            if str(object_) not in known_classes:
                undeclared_classes.add(str(object_))
        if isinstance(predicate, URIRef) and not _system(predicate) \
                and predicate != RDF.type:
            if str(predicate) not in known_properties:
                undeclared_properties.add(str(predicate))
    message = _undeclared_message(undeclared_classes, undeclared_properties)
    if message:
        if allow_new_vocabulary:
            warnings.append(message + " (allowed: the vocabulary is open)")
        else:
            errors.append(message + "; declare them in the patch and tick "
                                  "'allow new classes and relations'")

    collisions = _role_collisions(graph, added)
    if collisions:
        errors.append("these IRIs would be both a class and a property: "
                      + ", ".join(sorted(collisions)[:5]))

    proposed = _proposed_data(graph, added, removed)
    if shapes:
        report = validate_source_graph(proposed, tuple(shapes))
        if not report.conforms:
            results = list(report.report_graph.subjects(RDF.type,
                                                        _sh_validation_result()))
            warnings.append(
                f"the shapes report {len(results)} SHACL violation(s); the "
                f"edit is still allowed because you are the author")
    return tuple(errors), tuple(warnings), proposed


def _undeclared_message(classes, properties):
    parts = []
    if classes:
        parts.append("class(es) " + ", ".join(sorted(classes)[:5]))
    if properties:
        parts.append("property/properties " + ", ".join(sorted(properties)[:5]))
    if not parts:
        return ""
    return ("the patch uses " + " and ".join(parts)
            + " that nothing declares")


def _role_collisions(graph, added):
    """IRIs the patch would turn into both a class and a property."""
    classes = {str(iri) for iri in _subjects_of_type(graph, added, OWL.Class)}
    classes |= {str(iri) for iri in _subjects_of_type(graph, added, RDFS.Class)}
    properties = {str(iri) for iri in _subjects_of_type(graph, added,
                                                        OWL.ObjectProperty)}
    properties |= {str(iri) for iri in _subjects_of_type(graph, added,
                                                         OWL.DatatypeProperty)}
    return classes & properties


def _subjects_of_type(graph, added, type_):
    found = set(graph.subjects(RDF.type, type_))
    found |= {triple[0] for triple in added
              if triple[1] == RDF.type and triple[2] == type_}
    return found


def _system(iri):
    return str(iri).startswith(SYSTEM_NAMESPACES)


def _sh_validation_result():
    from rdflib.namespace import SH
    return SH.ValidationResult


def _proposed_data(graph, added, removed):
    """The data graph this patch would leave behind, without writing it."""
    proposed = Graph()
    bind(proposed)
    for triple in graph:
        proposed.add(triple)
    for triple in removed:
        proposed.remove(triple)
    for triple in added:
        proposed.add(triple)
    return proposed


# ---------- preview and apply ----------

def preview(graph, text, source="hand", allow_new_vocabulary=False, shapes=()):
    """Parse and check one patch; returns a `Patch` with its stable id."""
    added, removed, parse_errors = parse_patch(text)
    if parse_errors:
        return Patch(text=str(text), added=added, removed=removed,
                     errors=tuple(parse_errors), source=source,
                     allow_new_vocabulary=allow_new_vocabulary,
                     patch_id=_patch_id(text, allow_new_vocabulary, source))
    errors, warnings, _proposed = check_patch(
        graph, added, removed, allow_new_vocabulary=allow_new_vocabulary,
        shapes=shapes)
    return Patch(text=str(text), added=added, removed=removed, errors=errors,
                 warnings=warnings, source=source,
                 allow_new_vocabulary=allow_new_vocabulary,
                 patch_id=_patch_id(text, allow_new_vocabulary, source))


def _patch_id(text, allow_new_vocabulary, source):
    seed = f"{allow_new_vocabulary}|{source}|{text}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def statement_uri(triple):
    """The stable statement IRI for one triple, as publishing uses it."""
    key = " ".join(term.n3() for term in triple)
    return ONTO["statement/" + hashlib.sha256(key.encode("utf-8")).hexdigest()]


def provenance_for(patch, edit_iri=None):
    """The PROV evidence one applied patch leaves behind."""
    edit_iri = edit_iri or URIRef(EDIT_BASE + patch.patch_id)
    evidence = Graph()
    bind(evidence)
    evidence.add((edit_iri, RDF.type, PROV.Activity))
    evidence.add((edit_iri, RDFS.label, Literal("manual edit")))
    evidence.add((edit_iri, ONTO.editSource, Literal(patch.source)))
    evidence.add((edit_iri, ONTO.editAdded, Literal(len(patch.added))))
    evidence.add((edit_iri, ONTO.editRemoved, Literal(len(patch.removed))))
    for relationship, triples in ((PROV.wasGeneratedBy, patch.added),
                                  (PROV.wasInvalidatedBy, patch.removed)):
        for triple in triples:
            statement = statement_uri(triple)
            evidence.add((statement, RDF.type, RDF.Statement))
            evidence.add((statement, RDF.type, PROV.Entity))
            for predicate, value in zip((RDF.subject, RDF.predicate,
                                         RDF.object), triple):
                evidence.add((statement, predicate, value))
            evidence.add((statement, relationship, edit_iri))
    return edit_iri, evidence


def publication(store, names, patch):
    """The one atomic publication that applies a checked patch."""
    target = store.get(names.target_graph)
    provenance = store.get(names.provenance_graph)
    for triple in patch.removed:
        target.remove(triple)
    for triple in patch.added:
        target.add(triple)
    _edit_iri, evidence = provenance_for(patch)
    for triple in evidence:
        provenance.add(triple)
    return Publication(graphs={names.target_graph: target,
                               names.provenance_graph: provenance}), evidence


def data_turtle(graph, limit=None):
    """The editable part of the graph as Turtle, with its prefixes."""
    copy = Graph()
    bind(copy)
    for prefix, namespace in graph.namespaces():
        copy.bind(prefix, namespace)
    for triple in graph:
        copy.add(triple)
    text = copy.serialize(format="turtle")
    return text
