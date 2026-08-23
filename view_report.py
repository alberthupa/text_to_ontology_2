"""Turn the read-only ontology views into plain data, ready for rendering.

Nothing here knows about HTML and nothing here writes to the graph. Every
number is read out of the views that `ontology_views.build_ontology_views`
already produced, so the page can never disagree with the terminal report.
"""

import json
from datetime import datetime

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS

from graph_management import ONTO
from graph_patterns import eligible, usable_classes
from run_report import skeleton_label, skeleton_restriction
from task_context import local_name


# Types that say a resource exists rather than what it is. Shown apart from
# the real classes on an instance card.
METATYPES = {OWL.NamedIndividual, SKOS.Concept, OWL.Thing, RDFS.Resource}

# The audit vocabulary written by merge_policy.py, read back here.
EVENT_FIELDS = (
    ("sourcePath", ONTO.sourcePath),
    ("sourceSha256", ONTO.sourceSha256),
    ("modelName", ONTO.modelName),
    ("mergePolicyVersion", ONTO.mergePolicyVersion),
    ("candidatePackageSha256", ONTO.candidatePackageSha256),
)


def prefix_table(graph):
    """Bound prefixes, longest namespace first so the tightest one wins."""
    pairs = [(prefix, str(namespace)) for prefix, namespace in graph.namespaces()]
    return sorted(pairs, key=lambda pair: -len(pair[1]))


def shorten(term, prefixes):
    """`onto:Entity` when a bound prefix covers the URI, else the full URI."""
    text = str(term)
    for prefix, namespace in prefixes:
        if text.startswith(namespace) and len(text) > len(namespace):
            return f"{prefix}:{text[len(namespace):]}"
    return text


def describe(term, prefixes):
    """One term as `(kind, display text, extra note)`."""
    if isinstance(term, Literal):
        note = term.language or (local_name(term.datatype) if term.datatype
                                 else "plain string")
        return "literal", str(term), note
    if isinstance(term, BNode):
        return "blank", f"_:{term}", "blank node"
    return "uri", shorten(term, prefixes), "resource"


def triple_rows(views, prefixes):
    """Every source triple once, tagged with the view it was placed in."""
    rows = []
    for view in ("schema", "instance", "support"):
        for subject, predicate, target in views[view]:
            subject_kind, subject_text, _ = describe(subject, prefixes)
            _, predicate_text, _ = describe(predicate, prefixes)
            target_kind, target_text, target_note = describe(target, prefixes)
            rows.append([view, subject_text, subject_kind, predicate_text,
                         target_text, target_kind, target_note])
    rows.sort(key=lambda row: (row[0], row[1], row[3]))
    return rows


def named(graph, term, prefixes):
    """A term as both a readable label and the prefixed URI it really is."""
    return {"label": skeleton_label(graph, term), "short": shorten(term, prefixes)}


def class_entries(skeleton, prefixes):
    """Declared classes with their parents, restrictions, and descriptions."""
    entries = []
    classes = {subject for subject in skeleton.subjects(RDF.type, OWL.Class)
               if isinstance(subject, URIRef)}
    classes |= {subject for subject in skeleton.subjects(RDF.type, RDFS.Class)
                if isinstance(subject, URIRef)}
    for class_ in sorted(classes, key=str):
        parents, restrictions = [], []
        for parent in skeleton.objects(class_, RDFS.subClassOf):
            if isinstance(parent, BNode):
                restrictions.append(skeleton_restriction(skeleton, parent))
            elif parent != class_:
                parents.append(named(skeleton, parent, prefixes))
        entries.append({
            "uri": str(class_),
            "label": skeleton_label(skeleton, class_),
            "short": shorten(class_, prefixes),
            "parents": sorted(parents, key=lambda item: item["label"]),
            "restrictions": sorted(restrictions),
            "comment": describing_text(skeleton, class_),
        })
    return entries


def describing_text(graph, resource):
    """The first comment or definition stated for a resource, if any."""
    for predicate in (RDFS.comment, SKOS.definition):
        found = graph.value(resource, predicate)
        if found:
            return str(found)
    return ""


def property_entries(skeleton, prefixes):
    """Declared properties with the kind, domain, and range actually stated."""
    entries = []
    for kind, type_ in (("object", OWL.ObjectProperty),
                        ("datatype", OWL.DatatypeProperty)):
        for prop in sorted(skeleton.subjects(RDF.type, type_), key=str):
            entries.append({
                "uri": str(prop),
                "label": skeleton_label(skeleton, prop),
                "short": shorten(prop, prefixes),
                "kind": kind,
                "domain": [named(skeleton, target, prefixes) for target
                           in skeleton.objects(prop, RDFS.domain)],
                "range": [named(skeleton, target, prefixes) for target
                          in skeleton.objects(prop, RDFS.range)],
                "comment": describing_text(skeleton, prop),
            })
    entries.sort(key=lambda entry: (entry["kind"], entry["label"].lower()))
    return entries


def skeleton_section(views, prefixes):
    """The declared core, plus how much of the schema view it kept."""
    skeleton = views["skeleton"]
    restrictions = {node for node in skeleton.subjects(RDF.type, OWL.Restriction)}
    return {
        "triples": len(skeleton),
        "schema_triples": len(views["schema"]),
        "restrictions": len(restrictions),
        "classes": class_entries(skeleton, prefixes),
        "properties": property_entries(skeleton, prefixes),
    }


def pattern_rows(patterns, prefixes):
    """Observation records with readable names beside their raw numbers."""
    rows = []
    for record in patterns:
        target = record["range"]
        rows.append({
            "subject": local_name(record["subject_class"] or "unclassified"),
            "subject_uri": str(record["subject_class"] or ""),
            "predicate": local_name(record["predicate"]),
            "predicate_uri": shorten(record["predicate"], prefixes),
            "target": local_name(target) if target is not None else "unknown",
            "target_kind": record["range_kind"],
            "occurrences": record["occurrences"],
            "subjects": record["distinct_subjects"],
            "population": record["class_population"],
            "coverage": record["coverage"],
            "min": record["cardinality_min"],
            "median": record["cardinality_median"],
            "max": record["cardinality_max"],
        })
    return rows


def instance_cards(schema, instance, prefixes):
    """One card per named individual: its classes, names, relations, facts."""
    cache, cards = {}, []
    subjects = {subject for subject in instance.subjects(RDF.type, None)
                if isinstance(subject, URIRef)}
    for subject in sorted(subjects, key=str):
        specific = set(usable_classes(schema, instance, subject, cache))
        stated = {type_ for type_ in instance.objects(subject, RDF.type)
                  if isinstance(type_, URIRef)}
        relations, facts = [], []
        for predicate, target in instance.predicate_objects(subject):
            if not eligible(predicate):
                continue
            entry = {"predicate": local_name(predicate),
                     "value": str(target) if isinstance(target, Literal)
                     else local_name(target)}
            (facts if isinstance(target, Literal) else relations).append(entry)
        cards.append({
            "uri": str(subject),
            "short": shorten(subject, prefixes),
            "label": str(instance.value(subject, SKOS.prefLabel)
                         or instance.value(subject, RDFS.label)
                         or local_name(subject)),
            "kind": str(instance.value(subject, ONTO.kind) or ""),
            "classes": sorted(({"label": local_name(type_),
                                "short": shorten(type_, prefixes)}
                               for type_ in specific),
                              key=lambda item: item["short"]),
            "metatypes": sorted(shorten(type_, prefixes)
                                for type_ in stated & METATYPES),
            "other_types": sorted(shorten(type_, prefixes) for type_
                                  in stated - specific - METATYPES),
            "aliases": sorted(str(name) for name
                              in instance.objects(subject, SKOS.altLabel)),
            "comment": describing_text(instance, subject),
            "relations": sorted(relations, key=lambda item: item["predicate"]),
            "facts": sorted(facts, key=lambda item: item["predicate"]),
        })
    cards.sort(key=lambda card: card["label"].lower())
    return cards


def shape_entries(support):
    """SHACL node shapes, flattened into one readable rule line each."""
    entries = []
    for shape in sorted(support.subjects(RDF.type, SH.NodeShape), key=str):
        rules = []
        for node in support.objects(shape, SH.property):
            parts = [f"{local_name(predicate)} {local_name(target)}"
                     if isinstance(target, URIRef) else
                     f"{local_name(predicate)} {target}"
                     for predicate, target in support.predicate_objects(node)]
            rules.append(", ".join(sorted(parts)))
        entries.append({
            "label": local_name(shape),
            "targets": sorted(local_name(target) for target
                              in support.objects(shape, SH.targetClass)),
            "rules": sorted(rules),
        })
    return entries


def event_entries(support):
    """One record per extraction run kept in the graph."""
    entries = []
    for event in sorted(support.subjects(RDF.type, ONTO.ExtractionEvent), key=str):
        entry = {"uri": str(event), "id": local_name(event)[:12]}
        for name, predicate in EVENT_FIELDS:
            entry[name] = str(support.value(event, predicate) or "")
        entries.append(entry)
    return entries


def candidate_entries(support):
    """Every extracted record with the decision the merge policy made on it."""
    entries = []
    for node in sorted(support.subjects(RDF.type, ONTO.MergeCandidate), key=str):
        event = support.value(node, ONTO.wasExtractedIn)
        confidence = support.value(node, ONTO.extractionConfidence)
        resolved = support.value(node, ONTO.resolvedEntity)
        statement = [support.value(node, part) for part
                     in (RDF.subject, RDF.predicate, RDF.object)]
        entries.append({
            "section": str(support.value(node, ONTO.candidateSection) or ""),
            "index": int(support.value(node, ONTO.candidateIndex) or 0),
            "decision": str(support.value(node, ONTO.mergeDecision) or ""),
            "confidence": float(confidence) if confidence is not None else None,
            "reasons": sorted(str(reason) for reason
                              in support.objects(node, ONTO.decisionReason)),
            "resolved": local_name(resolved) if resolved else "",
            "event": local_name(event)[:12] if event else "",
            "statement": " ".join(local_name(part) for part in statement
                                  if part is not None),
            "candidate": readable_json(support.value(node, ONTO.normalizedCandidate)),
        })
    entries.sort(key=lambda entry: (entry["event"], entry["section"], entry["index"]))
    return entries


def readable_json(value):
    """A stored JSON literal as compact readable text, or the literal itself."""
    if value is None:
        return ""
    try:
        return json.dumps(json.loads(str(value)), ensure_ascii=False,
                          sort_keys=True)
    except ValueError:
        return str(value)


def header_rows(support, prefixes):
    """What the ontology header itself states, if the graph has one."""
    rows = []
    for subject in support.subjects(RDF.type, OWL.Ontology):
        for predicate, target in support.predicate_objects(subject):
            rows.append([shorten(subject, prefixes), shorten(predicate, prefixes),
                         describe(target, prefixes)[1]])
    return sorted(rows)


def build_report(path, graph, views):
    """Everything the page shows, as plain lists and dictionaries."""
    prefixes = prefix_table(graph)
    counts = {name: len(views[name]) for name
              in ("schema", "instance", "support", "skeleton")}
    counts["patterns"] = len(views["patterns"])
    support = views["support"]
    return {
        "graph": {
            "path": str(path),
            "triples": len(graph),
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "counts": counts,
            "partitioned": counts["schema"] + counts["instance"] + counts["support"],
            "prefixes": [pair for pair in sorted(prefixes)
                         if any(pair[1] in str(term) for term in
                                (ONTO, RDF, RDFS, OWL, SH, SKOS))
                         or pair[1].startswith(str(ONTO))],
        },
        "triples": triple_rows(views, prefixes),
        "skeleton": skeleton_section(views, prefixes),
        "patterns": pattern_rows(views["patterns"], prefixes),
        "instances": instance_cards(views["schema"], views["instance"], prefixes),
        "support": {
            "events": event_entries(support),
            "candidates": candidate_entries(support),
            "shapes": shape_entries(support),
            "header": header_rows(support, prefixes),
        },
    }
