"""How well connected is the graph? A few plain numbers, read only.

Every change to ingestion should be judged by the same numbers:

    isolated entities     linked to no other entity at all;
    root-only entities    typed only as the root class `Entity`;
    endpoint violations   statements whose subject or object has the wrong
                          class for the property's declared domain or range;
    missing links         expected links (SHACL warning shapes) an entity lacks;
    duplicate suspects    two entities whose names are the same words, maybe
                          inflected ("Polpharma" / "Polpharmy");
    uncovered sources     files in a source folder that no document came from;
    gold links            how many links you know to be true are in the graph,
                          and how many links of that kind are right.

One function per number, so each can be tested on its own. No model call,
nothing written.

    text-to-ontology-health ontology.trig
    text-to-ontology-health ontology.trig --sources notes/ --gold eval/gold.local.json
"""

import argparse
import json
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .entity_lookup import identity_key
from .graph_management import ONTO
from .graph_store import GraphNames, RdflibGraphStore
from .ingest_sources import find_text_files, read_source
from .link_check import expected_links
from .source_concepts import same_name_stem
from .vocabulary import read_vocabulary
from .windowing import make_source_document

NAME_PREDICATES = (SKOS.prefLabel, SKOS.altLabel, RDFS.label)
DOCUMENT = ONTO["document/"]


# ---------- small helpers ----------

def entities(data):
    """Every entity of the data graph."""
    return sorted(set(data.subjects(RDF.type, ONTO.Entity)), key=str)


def names_of(graph, entity):
    """All names of an entity, preferred label first."""
    preferred = graph.value(entity, SKOS.prefLabel)
    found = sorted({str(name) for predicate in NAME_PREDICATES
                    for name in graph.objects(entity, predicate)})
    if preferred is not None:
        found = [str(preferred)] + [name for name in found
                                    if name != str(preferred)]
    return found or [str(entity)]


def declared_classes(data, entity, vocabulary):
    """The declared classes of an entity other than the root class."""
    return sorted(str(type_) for type_ in data.objects(entity, RDF.type)
                  if str(type_) in vocabulary.classes
                  and type_ != ONTO.Entity)


def _is_entity(data, term):
    return isinstance(term, URIRef) and (term, RDF.type, ONTO.Entity) in data


# ---------- the numbers ----------

def isolated_entities(data):
    """Entities with no link to any other entity, in either direction."""
    linked = set()
    for subject, predicate, object_ in data:
        if predicate != RDF.type and _is_entity(data, subject) \
                and _is_entity(data, object_) and subject != object_:
            linked.update((subject, object_))
    return [entity for entity in entities(data) if entity not in linked]


def root_only_entities(data, vocabulary):
    """Entities whose only class is the root class."""
    return [entity for entity in entities(data)
            if not declared_classes(data, entity, vocabulary)]


def endpoint_violations(data, vocabulary):
    """Statements whose subject or object breaks the declared domain/range."""
    def fits(term, wanted):
        return any(vocabulary.is_a(class_iri, wanted)
                   for class_iri in data.objects(term, RDF.type))

    found = []
    for prop in sorted(list(vocabulary.relations) + list(vocabulary.facts)):
        domain = vocabulary.domain_of(prop)
        target = vocabulary.range_of(prop)
        for subject, object_ in data.subject_objects(URIRef(prop)):
            problems = []
            if domain is not None and not fits(subject, domain):
                problems.append("domain")
            if target is not None and isinstance(object_, URIRef) \
                    and not fits(object_, target):
                problems.append("range")
            if problems:
                found.append({
                    "predicate": vocabulary.label_of(prop),
                    "subject": names_of(data, subject)[0],
                    "object": (str(object_) if isinstance(object_, Literal)
                               else names_of(data, object_)[0]),
                    "problems": problems,
                })
    return found


def missing_links(data, vocabulary, expected):
    """Entities that lack an expected link."""
    found = []
    for link in expected:
        for entity in entities(data):
            if not any(vocabulary.is_a(class_iri, link["class"])
                       for class_iri in data.objects(entity, RDF.type)):
                continue
            if data.value(entity, URIRef(link["relation"])) is None:
                found.append({"entity": names_of(data, entity)[0],
                              "relation": vocabulary.label_of(link["relation"])})
    return found


def duplicate_suspects(data, vocabulary):
    """Pairs of entities that may be one thing under two names.

    Two entities are compared when they share a declared class, or when one
    of them has no declared class at all (the "Polpharmy" typed only as
    Entity next to the client "Polpharma").
    """
    cards = [(entity, set(declared_classes(data, entity, vocabulary)),
              names_of(data, entity)) for entity in entities(data)]
    found = []
    for index, (first, first_classes, first_names) in enumerate(cards):
        for second, second_classes, second_names in cards[index + 1:]:
            comparable = (first_classes & second_classes
                          or not first_classes or not second_classes)
            if not comparable:
                continue
            if any(same_name_stem(left, right)
                   for left in first_names for right in second_names):
                found.append({"first": first_names[0],
                              "second": second_names[0],
                              "first_id": str(first),
                              "second_id": str(second)})
    return found


def uncovered_sources(provenance, folder):
    """Source files under `folder` whose content no ingested document has."""
    missing = []
    for path in find_text_files(Path(folder), Path("/nonexistent-graph")):
        text = read_source(path)
        if not text.strip():
            continue
        document = make_source_document(path.name, text)
        if (URIRef(f"{DOCUMENT}{document.document_id}"), None, None) \
                not in provenance:
            missing.append(path.relative_to(folder).as_posix())
    return missing


def _matching(data, name):
    key = identity_key(name)
    return {entity for entity in entities(data)
            if key in {identity_key(found) for found in names_of(data, entity)}}


def gold_scores(data, vocabulary, gold_links):
    """Recall and precision of known true links.

    Recall: how many gold links are in the graph (matched by any name or
    alias). Precision: of the graph's links from a gold subject with a gold
    predicate, how many point at a gold object.
    """
    found, missing = 0, []
    gold_objects = {}  # (subject entity, predicate) -> the right objects
    for link in gold_links:
        predicate = URIRef(vocabulary.relation_iri(link["predicate"]))
        subjects = _matching(data, link["subject"])
        objects = _matching(data, link["object"])
        if any((subject, predicate, object_) in data
               for subject in subjects for object_ in objects):
            found += 1
        else:
            missing.append(f"{link['subject']} --{link['predicate']}--> "
                           f"{link['object']}")
        for subject in subjects:
            gold_objects.setdefault((subject, predicate), set()).update(objects)
    checked = correct = 0
    for (subject, predicate), objects in gold_objects.items():
        for object_ in data.objects(subject, predicate):
            checked += 1
            if object_ in objects:
                correct += 1
    return {
        "gold": len(gold_links),
        "found": found,
        "recall": found / len(gold_links) if gold_links else None,
        "checked": checked,
        "correct": correct,
        "precision": correct / checked if checked else None,
        "missing": missing,
    }


# ---------- the report ----------

def _role(store, names):
    graph = Graph()
    for name in names:
        for triple in store.get(name):
            graph.add(triple)
    return graph


def health_report(graph_path, sources=None, gold_path=None):
    """Every number for one dataset, as plain data."""
    store = RdflibGraphStore(path=Path(graph_path))
    names = GraphNames()
    schema = _role(store, names.schema_graphs)
    data = _role(store, [names.target_graph, *names.data_graphs])
    provenance = _role(store, [names.provenance_graph])
    vocabulary = read_vocabulary(schema)
    expected = expected_links(_role(store, names.shape_graphs))
    all_entities = entities(data)
    report = {
        "entities": len(all_entities),
        "isolated": len(isolated_entities(data)),
        "root_only": len(root_only_entities(data, vocabulary)),
        "endpoint_violations": endpoint_violations(data, vocabulary),
        "expected_links": [
            f"{vocabulary.label_of(link['class'])} --"
            f"{vocabulary.label_of(link['relation'])}-->" for link in expected],
        "missing_links": missing_links(data, vocabulary, expected),
        "duplicate_suspects": duplicate_suspects(data, vocabulary),
    }
    if sources is not None:
        report["uncovered_sources"] = uncovered_sources(provenance, sources)
    if gold_path is not None:
        gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
        report["gold"] = gold_scores(data, vocabulary, gold["links"])
    return report


def _share(part, whole):
    return f"{part}/{whole} ({round(100 * part / whole)}%)" if whole else "0"


def format_report(report, limit=20):
    """The report as short text: numbers first, then examples."""
    lines = [
        f"Entities: {report['entities']}",
        f"Isolated (no link to another entity): "
        f"{_share(report['isolated'], report['entities'])}",
        f"Typed only as Entity: {_share(report['root_only'], report['entities'])}",
        f"Endpoint violations: {len(report['endpoint_violations'])}",
    ]
    by_predicate = {}
    for item in report["endpoint_violations"]:
        by_predicate[item["predicate"]] = by_predicate.get(item["predicate"], 0) + 1
    for predicate, count in sorted(by_predicate.items(),
                                   key=lambda pair: (-pair[1], pair[0])):
        lines.append(f"  {predicate}: {count}")
    lines.append("Expected links: " + (", ".join(report["expected_links"])
                                       or "none declared"))
    lines.append(f"Missing expected links: {len(report['missing_links'])}")
    for item in report["missing_links"][:limit]:
        lines.append(f"  {item['entity']} has no {item['relation']!r}")
    lines.append(f"Duplicate suspects: {len(report['duplicate_suspects'])}")
    for item in report["duplicate_suspects"][:limit]:
        lines.append(f"  {item['first']!r} / {item['second']!r}")
    if "uncovered_sources" in report:
        lines.append(f"Source files never ingested: "
                     f"{len(report['uncovered_sources'])}")
        for path in report["uncovered_sources"][:limit]:
            lines.append(f"  {path}")
    if "gold" in report:
        gold = report["gold"]
        recall = ("-" if gold["recall"] is None
                  else f"{round(100 * gold['recall'])}%")
        precision = ("-" if gold["precision"] is None
                     else f"{round(100 * gold['precision'])}%")
        lines.append(f"Gold links found: {gold['found']}/{gold['gold']} "
                     f"(recall {recall}); precision {precision} "
                     f"({gold['correct']}/{gold['checked']})")
        for item in gold["missing"][:limit]:
            lines.append(f"  missing: {item}")
    return "\n".join(lines)


def main(argv=None):
    """`text-to-ontology-health`: print the health numbers of one dataset."""
    parser = argparse.ArgumentParser(
        description="How well connected is the graph? Read only.")
    parser.add_argument("graph", type=Path, help="the TriG dataset")
    parser.add_argument("--sources", type=Path,
                        help="a source folder: list files never ingested")
    parser.add_argument("--gold", type=Path,
                        help='a JSON file {"links": [{"subject", "predicate", '
                             '"object"}]} of links known to be true')
    parser.add_argument("--json", action="store_true",
                        help="print the full report as JSON")
    args = parser.parse_args(argv)
    report = health_report(args.graph, args.sources, args.gold)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))
