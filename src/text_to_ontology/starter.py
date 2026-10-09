"""Create the starter ontology: from a short paste, or from an RDF file.

Two ways in, one result. Either you describe the world in a few sentences and
the model proposes the classes, relations, and facts, or you hand over an
RDF/Turtle/TriG document and it is parsed instead. Both are checked and written
as the dataset's schema, shapes, and data. After that, ingestion is data-only:
it may add individuals and statements, but never a class or a relationship, and
it uses the starter's own IRIs (see `vocabulary.py`).

The whole starter is written in one atomic publication, so re-running it
replaces the previous starter instead of growing it.
"""

import argparse
import sys
from pathlib import Path

from rdflib import Dataset, Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, XSD

from . import prompts
from .document_publication import split_legacy_graph
from .graph_management import FACT, ONTO, RELATION, seed_graph
from .graph_merge import class_uri, label, slug
from .graph_partition import partition_graph
from .graph_store import GraphNames, Publication, RdflibGraphStore
from .llm import OpenRouterExtractor
from .repair import extract_validated
from .source_validation import embedded_shape_graph
from .vocabulary import read_vocabulary

DEFAULT_GRAPH = Path("ontology.trig")
MIN_CLASSES = 2
MAX_CLASSES = 20
MAX_ASSERTIONS = 40

# The short XSD names a fact range may use.
XSD_TYPES = {
    "string": XSD.string, "text": XSD.string, "integer": XSD.integer,
    "int": XSD.integer, "decimal": XSD.decimal, "float": XSD.float,
    "double": XSD.double, "boolean": XSD.boolean, "date": XSD.date,
    "datetime": XSD.dateTime, "time": XSD.time, "anyuri": XSD.anyURI,
}
XSD_NAMES = "string, integer, decimal, float, boolean, date, datetime, anyURI"

STARTER_SHAPE = '"classes", "relations", "facts"'

# The default starter template lives in prompts.py, where a user can edit it.
STARTER_PROMPT = prompts.DEFAULT_PROMPTS["starter"]


def starter_prompt(text, library=None):
    """The one prompt that turns pasted information into a starter proposal."""
    return prompts.render(
        "starter",
        {"text": text.strip(), "min_classes": MIN_CLASSES,
         "max_classes": MAX_CLASSES, "xsd_names": XSD_NAMES},
        library=library)


def format_starter_failure(result):
    """A concise, deterministic error message for a rejected proposal."""
    errors = [issue for issue in result["issues"] if issue["severity"] == "error"]
    lines = [f"{len(errors)} starter ontology error(s):"]
    lines += [f"- {issue['path']}: {issue['message']}" for issue in errors]
    return "\n".join(lines)


def validate_starter(data):
    """Check one proposed starter ontology; never touch a graph.

    Returns the same shape as `candidate_validation.validate_candidates`, so
    the shared repair loop can use it unchanged.
    """
    issues = []

    def fail(code, path, message):
        issues.append({"code": code, "severity": "error", "path": path,
                       "related_paths": [], "message": message})

    if not isinstance(data, dict):
        fail("starter.not_mapping", "$", "the answer is not a JSON object")
        return _starter_result(False, None, issues)

    for section in ("classes", "relations", "facts"):
        if section not in data:
            fail("starter.missing_section", section,
                 f"missing required section '{section}'")
        elif not isinstance(data[section], list):
            fail("starter.section_not_list", section,
                 f"section '{section}' must be a list")
    for key in data:
        if key not in ("classes", "relations", "facts"):
            fail("starter.unknown_section", key,
                 f"unknown top-level field '{key}'")
    if issues:
        return _starter_result(False, None, issues)

    classes = _normalize(data["classes"], "classes", issues, "class",
                         is_class=True)
    relations = _normalize(data["relations"], "relations", issues, "relation")
    facts = _normalize(data["facts"], "facts", issues, "fact")
    class_names = {slug(item["name"]) for item in classes}

    for section, records in (("relations", relations), ("facts", facts)):
        for index, item in enumerate(records):
            _check_class_field(item, "domain", class_names, section, index,
                               issues, required=True)
            if section == "relations":
                _check_class_field(item, "range", class_names, section, index,
                                   issues, required=True)
            else:
                _check_literal_range(item, section, index, issues)

    _check_unique(classes, "classes", "class", issues)
    _check_unique(relations, "relations", "relation", issues)
    _check_unique(facts, "facts", "fact", issues)

    if not MIN_CLASSES <= len(classes) <= MAX_CLASSES:
        fail("starter.class_count", "classes",
             f"expected {MIN_CLASSES} to {MAX_CLASSES} classes, "
             f"got {len(classes)}")
    if len(relations) + len(facts) > MAX_ASSERTIONS:
        fail("starter.assertion_count", "relations",
             f"expected at most {MAX_ASSERTIONS} relations and facts, "
             f"got {len(relations) + len(facts)}")

    valid = not any(issue["severity"] == "error" for issue in issues)
    proposal = {"classes": classes, "relations": relations, "facts": facts}
    return _starter_result(valid, proposal, issues)


def _starter_result(valid, candidates, issues):
    issues = sorted(issues, key=lambda item: item["path"])
    return {
        "valid": valid,
        "candidates": candidates if valid else None,
        "issues": issues,
        "counts": {
            "errors": sum(1 for issue in issues
                          if issue["severity"] == "error"),
            "warnings": 0,
        },
    }


def _usable_name(name):
    """A name ingestion can find again: no camelCase, no stray characters."""
    return bool(name) and slug(name) != "unnamed" \
        and slug(label(name)) == slug(name)


def _normalize(raw, section, issues, word, is_class=False):
    """Normalize one proposed section, reporting every broken record."""
    records = []
    for index, record in enumerate(raw):
        path = f"{section}[{index}]"
        if not isinstance(record, dict):
            issues.append({"code": f"starter.{word}_not_mapping",
                           "severity": "error", "path": path,
                           "related_paths": [],
                           "message": f"{word} is not a JSON object"})
            continue
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append({"code": f"starter.{word}_name", "severity": "error",
                           "path": path + ".name", "related_paths": [],
                           "message": f"{word} needs a non-empty name"})
            continue
        name = name.strip()
        if not _usable_name(name):
            style = "Title Case words" if is_class \
                else "lowercase words separated by hyphens"
            issues.append({
                "code": f"starter.{word}_name_not_usable", "severity": "error",
                "path": path + ".name", "related_paths": [],
                "message": f"name {name!r} must be plain {style}, "
                           f"without camelCase"})
            continue
        description = record.get("description") or ""
        if not isinstance(description, str):
            issues.append({"code": f"starter.{word}_description",
                           "severity": "error",
                           "path": path + ".description", "related_paths": [],
                           "message": "description must be a string"})
            description = ""
        item = {"name": name, "description": description.strip()}
        if not is_class:
            for field in ("domain", "range"):
                value = record.get(field)
                item[field] = value.strip() if isinstance(value, str) else ""
        records.append(item)
    return records


def _check_class_field(item, field, class_names, section, index, issues,
                       required):
    value = item.get(field, "")
    path = f"{section}[{index}].{field}"
    if not value:
        if required:
            issues.append({"code": f"starter.{section}_{field}_missing",
                           "severity": "error", "path": path,
                           "related_paths": [],
                           "message": f"{section[:-1]} needs a {field} class name"})
        return
    if slug(value) not in class_names:
        issues.append({
            "code": f"starter.{section}_{field}_unknown", "severity": "error",
            "path": path, "related_paths": [],
            "message": f"{field} {value!r} is not one of the proposed classes: "
                       + ", ".join(sorted(class_names))})


def _check_literal_range(item, section, index, issues):
    value = item.get("range", "")
    if value and value.lower() not in XSD_TYPES:
        issues.append({
            "code": "starter.fact_range_unknown", "severity": "error",
            "path": f"{section}[{index}].range", "related_paths": [],
            "message": f"range {value!r} is not a known literal type: "
                       + XSD_NAMES})


def _check_unique(records, section, word, issues):
    seen = set()
    for index, item in enumerate(records):
        key = slug(item["name"])
        if key in seen:
            issues.append({"code": f"starter.duplicate_{word}",
                           "severity": "error",
                           "path": f"{section}[{index}].name",
                           "related_paths": [],
                           "message": f"{item['name']!r} appears more than once"})
        seen.add(key)


def propose_starter(text, extractor, repair_attempts=2, library=None):
    """Ask the model for a starter ontology and validate it (with repair)."""
    outcome = extract_validated(
        extractor, starter_prompt(text, library=library), validate_starter,
        max_repair_attempts=repair_attempts, shape=STARTER_SHAPE)
    if not outcome.ok:
        raise RuntimeError(outcome.raw_problem
                           or format_starter_failure(outcome.validation))
    return outcome.validation["candidates"]


# Importing an RDF file instead of asking the model. The suffix is a hint; when
# it is missing or wrong the formats are tried in this order.
RDF_SUFFIXES = {
    ".ttl": "turtle", ".turtle": "turtle", ".trig": "trig", ".nt": "nt",
    ".n3": "n3", ".nq": "nquads", ".rdf": "xml", ".owl": "xml",
    ".jsonld": "json-ld", ".json": "json-ld",
}
RDF_FORMATS = ("turtle", "trig", "nt", "nquads", "xml", "json-ld", "n3")
RDF_SIGNS = ("@prefix", "@base", "prefix ", "select ", "<rdf:", "a owl:",
             "a rdfs:", "owl:ontology", "sh:nodeshape")


def looks_like_rdf(name, text):
    """True when a dropped file is an RDF document rather than prose.

    The suffix is trusted when it is a known RDF one; otherwise the first
    non-comment line has to look like Turtle, TriG, N-Triples, or RDF/XML.
    """
    if Path(name).suffix.lower() in RDF_SUFFIXES:
        return True
    head = " ".join(line for line in str(text).splitlines()[:20]
                    if not line.strip().startswith("#")).lower()
    if not head.strip():
        return False
    if head.lstrip().startswith(("<?xml", "<rdf:rdf")) and "rdf" in head:
        return True
    return any(sign in head for sign in RDF_SIGNS)


def parse_rdf(text, name=""):
    """Parse one RDF document; returns (format, dataset or graph).

    A TriG or N-Quads document keeps its named graphs; everything else becomes
    one graph.
    """
    hint = RDF_SUFFIXES.get(Path(name).suffix.lower())
    formats = ([hint] if hint else []) + [item for item in RDF_FORMATS
                                          if item != hint]
    failures = []
    for rdf_format in formats:
        try:
            if rdf_format in ("trig", "nquads"):
                dataset = Dataset()
                dataset.parse(data=text, format=rdf_format)
                if len(dataset):
                    return rdf_format, dataset
            else:
                graph = Graph()
                graph.parse(data=text, format=rdf_format)
                if len(graph):
                    return rdf_format, graph
            failures.append(f"{rdf_format}: parsed but empty")
        except Exception as error:                       # noqa: BLE001
            failures.append(f"{rdf_format}: {str(error).splitlines()[0]}")
    raise ValueError("this does not parse as RDF. Tried "
                     + "; ".join(failures[:4]))


def import_publication(text, name="", names=None):
    """One publication that makes a parsed RDF document the starter dataset.

    When the document already carries this project's named graphs, they are
    imported role for role, so an exported dataset can be edited and dropped
    back in. Otherwise the document is partitioned: classes and properties
    become the schema, SHACL shapes the shapes graph, individuals and
    statements the data graph, and the rest is kept as support.
    """
    names = names or GraphNames()
    rdf_format, parsed = parse_rdf(text, name)
    triples = list(_triples(parsed))
    roles = _roles_from_parsed(parsed, names)
    schema = roles[names.schema_graphs[0]]
    vocabulary = read_vocabulary(schema)
    if vocabulary.is_empty:
        raise ValueError(
            "the RDF document declares no classes or properties, so it cannot "
            f"be the starter vocabulary (it holds {len(triples)} triples); "
            "it needs owl:Class or owl:ObjectProperty declarations")
    summary = {
        "format": rdf_format,
        "triples": len(triples),
        "schema": len(schema),
        "shapes": len(roles[names.shape_graphs[0]]),
        "data": len(roles[names.target_graph]),
        "support": len(roles[names.provenance_graph]),
        "classes": vocabulary.class_names,
        "relations": vocabulary.relation_names,
        "facts": vocabulary.fact_names,
    }
    return Publication(graphs=roles), summary


def _roles_from_parsed(parsed, names):
    """Put a parsed document into the five role graphs."""
    role_names = {
        str(names.schema_graphs[0]): names.schema_graphs[0],
        str(names.shape_graphs[0]): names.shape_graphs[0],
        str(names.target_graph): names.target_graph,
        str(names.provenance_graph): names.provenance_graph,
        str(names.review_graph): names.review_graph,
    }
    roles = {name: Graph() for name in
             (names.schema_graphs[0], names.shape_graphs[0],
              names.target_graph, names.provenance_graph, names.review_graph)}
    if isinstance(parsed, Dataset):
        known = False
        foreign = Graph()
        for context in list(parsed.contexts()):
            graph = Graph()
            for subject, predicate, object_ in parsed.triples(
                    (None, None, None, context.identifier)):
                graph.add((subject, predicate, object_))
            if not len(graph):
                continue
            role = role_names.get(str(context.identifier))
            if role is None:
                for triple in graph:
                    foreign.add(triple)
            else:
                known = True
                for triple in graph:
                    roles[role].add(triple)
        if known:
            # One of our own datasets: a named graph we do not own is data,
            # not bookkeeping.
            for triple in foreign:
                roles[names.target_graph].add(triple)
            return roles
        # Not one of our datasets: partition the whole file below, once.
    union = Graph()
    for triple in _triples(parsed):
        union.add(triple)
    schema, instance, support = partition_graph(union)
    shapes = embedded_shape_graph(union)
    for triple in schema:
        roles[names.schema_graphs[0]].add(triple)
    for triple in shapes:
        roles[names.shape_graphs[0]].add(triple)
    for triple in instance:
        roles[names.target_graph].add(triple)
    for triple in support:
        if triple not in shapes:
            roles[names.provenance_graph].add(triple)
    return roles


def _triples(parsed):
    """Every (subject, predicate, object) of a graph or a dataset."""
    if isinstance(parsed, Dataset):
        return [(subject, predicate, object_) for subject, predicate, object_,
                _graph in parsed.quads((None, None, None, None))]
    return list(parsed)


def import_starter(text, name="", graph_path=DEFAULT_GRAPH, names=None):
    """Import an RDF document as the starter ontology, in one publication."""
    names = names or GraphNames()
    publication, summary = import_publication(text, name, names)
    store = RdflibGraphStore(path=graph_path)
    store.publish(publication)
    return summary


def starter_publication(proposal, names=None):
    """The one publication that installs a starter ontology, nothing else."""
    names = names or GraphNames()
    roles = split_legacy_graph(seed_graph(), names)
    schema = roles[names.schema_graphs[0]]

    class_uris = {}
    for item in proposal["classes"]:
        uri = class_uri(item["name"])
        class_uris[slug(item["name"])] = uri
        schema.add((uri, RDF.type, OWL.Class))
        schema.add((uri, RDFS.label, Literal(item["name"])))
        schema.add((uri, RDFS.subClassOf, ONTO.Entity))
        if item["description"]:
            schema.add((uri, RDFS.comment, Literal(item["description"])))

    for item in proposal["relations"]:
        uri = RELATION[slug(item["name"])]
        schema.add((uri, RDF.type, OWL.ObjectProperty))
        schema.add((uri, RDFS.label, Literal(label(item["name"]))))
        if item["description"]:
            schema.add((uri, RDFS.comment, Literal(item["description"])))
        if item["domain"]:
            schema.add((uri, RDFS.domain, class_uris[slug(item["domain"])]))
        if item["range"]:
            schema.add((uri, RDFS.range, class_uris[slug(item["range"])]))

    for item in proposal["facts"]:
        uri = FACT[slug(item["name"])]
        schema.add((uri, RDF.type, OWL.DatatypeProperty))
        schema.add((uri, RDFS.label, Literal(label(item["name"]))))
        if item["description"]:
            schema.add((uri, RDFS.comment, Literal(item["description"])))
        if item["domain"]:
            schema.add((uri, RDFS.domain, class_uris[slug(item["domain"])]))
        if item["range"]:
            schema.add((uri, RDFS.range, XSD_TYPES[item["range"].lower()]))

    graphs = {
        names.schema_graphs[0]: schema,
        names.shape_graphs[0]: roles[names.shape_graphs[0]],
        names.target_graph: roles[names.target_graph],
        names.provenance_graph: roles[names.provenance_graph],
        names.review_graph: roles[names.review_graph],
    }
    # Any further configured role starts empty, so an old dataset is replaced.
    for name in (*names.schema_graphs[1:], *names.shape_graphs[1:],
                 *names.data_graphs):
        graphs.setdefault(name, Graph())
    return Publication(graphs=graphs)


def create_starter(text, graph_path=DEFAULT_GRAPH, extractor=None, names=None):
    """Turn pasted information into a written starter ontology."""
    names = names or GraphNames()
    extractor = extractor or OpenRouterExtractor()
    proposal = propose_starter(text, extractor)
    store = RdflibGraphStore(path=graph_path)
    store.publish(starter_publication(proposal, names))
    return proposal


def proposal_summary(proposal):
    """A short plain-text summary of a starter proposal."""
    lines = [f"{len(proposal['classes'])} classes, "
             f"{len(proposal['relations'])} relations, "
             f"{len(proposal['facts'])} facts"]
    for item in proposal["classes"]:
        lines.append(f"  class    {item['name']}")
    for item in proposal["relations"]:
        lines.append(f"  relation {item['name']}: "
                     f"{item['domain']} -> {item['range']}")
    for item in proposal["facts"]:
        lines.append(f"  fact     {item['name']}: "
                     f"{item['domain']} -> {item['range'] or 'literal'}")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Create the starter ontology from a short description.")
    parser.add_argument("info", type=Path, nargs="?",
                        help="a text file with the initial information, or - "
                             "to read it from standard input")
    parser.add_argument("graph", type=Path, nargs="?", default=DEFAULT_GRAPH,
                        help="the TriG dataset to write (default ontology.trig)")
    parser.add_argument("--model", default=None,
                        help="the OpenRouter model to use")
    return parser


def import_summary(summary):
    """A short plain-text summary of one imported RDF starter."""
    lines = [f"{summary['format']}: {summary['triples']} triples -> "
             f"schema {summary['schema']}, shapes {summary['shapes']}, "
             f"data {summary['data']}, support {summary['support']}",
             f"classes: {', '.join(summary['classes']) or 'none'}",
             f"relations: {', '.join(summary['relations']) or 'none'}",
             f"facts: {', '.join(summary['facts']) or 'none'}"]
    return "\n".join(lines)


def main(argv=None):
    """Read a description and let the model propose the starter.

    An existing RDF ontology is not imported here: `python ttl_to_trig.py`
    turns it into a dataset.
    """
    args = build_parser().parse_args(argv)
    if args.info is None or str(args.info) == "-":
        text = sys.stdin.read()
    else:
        text = args.info.read_text(encoding="utf-8")
    if not text.strip():
        print("Error: no initial information given", file=sys.stderr)
        raise SystemExit(1)
    try:
        proposal = create_starter(
            text, graph_path=args.graph,
            extractor=OpenRouterExtractor(model=args.model))
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(proposal_summary(proposal))
    print(f"Starter ontology written to {args.graph}")


if __name__ == "__main__":
    main()
