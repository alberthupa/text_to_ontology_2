#!/usr/bin/env python3
"""Print the read-only views of an existing Turtle graph, or write them as HTML.

This is the side chain made visible: graph_partition splits the graph into
schema / instance / support, graph_skeleton copies the declared structural
core out of the schema, and graph_patterns reports what the instance data
actually does. Nothing here writes to the graph.

With -html the same views become one self-contained page that also explains
how each of them is derived, and lets you search, filter, and sort what is in
them. Those page controls only change what is displayed.
"""

import argparse
import sys
from pathlib import Path

from rdflib import BNode, RDF, RDFS, OWL, URIRef
from rdflib.namespace import SKOS

from .graph_management import open_graph
from .ontology_views import build_ontology_views
from .run_report import skeleton_label, skeleton_restriction
from .task_context import local_name
from .view_html import write_report


def label(term):
    """A readable name for any term: its decoded local name."""
    return local_name(URIRef(term)) if isinstance(term, str) else local_name(term)


def report_partitions(views):
    """Explain the partitioning rules, then show the three view sizes."""
    print("\n1. Partitions: three ways of looking at the same graph")
    print("  How they are made:")
    print("    Every RDF statement is inspected and placed in exactly one view.")
    print("    schema   = explicit class/property definitions and ontology rules")
    print("    instance = named things and their types, relations, facts, and names")
    print("    support  = ontology headers, SHACL shapes, merge audit data, and")
    print("               anything that cannot be classified safely")
    print("    Nothing is inferred or discarded; uncertain statements go to support.")
    print("  Controls:")
    print("    There are no partition controls in this viewer. The result follows the")
    print("    explicit RDF/OWL/SHACL declarations in the graph. Developers can change")
    print("    the recognized types and predicates in graph_partition.py.")
    print("  Result (lossless and non-overlapping):")
    for name in ("schema", "instance", "support"):
        print(f"    {name}: {len(views[name])} triples")


def report_skeleton_help():
    """Explain how the structural skeleton is copied from the schema view."""
    print("\n2. Skeleton: the small, explicitly declared structure")
    print("  How it is made:")
    print("    It starts with the schema partition and copies declared classes,")
    print("    object/datatype properties, subclass links, domains, ranges, and their")
    print("    names or descriptions. A supported OWL restriction is copied only when")
    print("    it is complete; unsupported or incomplete restrictions are left out.")
    print("    It never invents a class, parent, domain, or range.")
    print("  Controls:")
    print("    There are no skeleton controls in this viewer. What appears is controlled")
    print("    mainly by what is explicitly declared in the graph. Developers can change")
    print("    the allowed declarations, axioms, annotations, and restriction forms in")
    print("    graph_skeleton.py.")


def report_skeleton(skeleton):
    """Print the declared structural core that create_graph_skeleton copied."""
    print(f"  Graph skeleton ({len(skeleton)} triples), the declared core:",
          flush=True)
    subjects = {subject for subject, _, _ in skeleton}
    for subject in sorted(subjects, key=str):
        # Blank nodes are restrictions; they are shown inline under their
        # class, not as their own entries.
        if isinstance(subject, BNode):
            continue
        types = set(skeleton.objects(subject, RDF.type))
        if OWL.ObjectProperty in types:
            kind = "object property"
        elif OWL.DatatypeProperty in types:
            kind = "datatype property"
        elif types & {OWL.Class, RDFS.Class}:
            kind = "class"
        else:
            kind = "resource"  # no declaration, only axioms name it
        print(f"    {kind} {skeleton_label(skeleton, subject)}", flush=True)
        for comment in skeleton.objects(subject, RDFS.comment):
            print(f"      comment: {comment}")
        for definition in skeleton.objects(subject, SKOS.definition):
            print(f"      definition: {definition}")
        for parent in skeleton.objects(subject, RDFS.subClassOf):
            if isinstance(parent, BNode):
                print(f"      restricted by: "
                      f"{skeleton_restriction(skeleton, parent)}")
            else:
                print(f"      subClassOf: {skeleton_label(skeleton, parent)}")
        for predicate, title in ((RDFS.domain, "domain"),
                                 (RDFS.range, "range")):
            for target in skeleton.objects(subject, predicate):
                print(f"      {title}: {skeleton_label(skeleton, target)}")


def report_patterns(patterns):
    """Explain pattern discovery, then print every observed pattern."""
    print("\n3. Patterns: repeated shapes observed in the instance data")
    print("  How they are made:")
    print("    Data statements are grouped as subject class -> property -> value type.")
    print("    The subject uses its most specific explicitly stated class. A value type")
    print("    is another entity's class, a literal datatype such as string/date, or")
    print("    'unknown' when the target has no usable class.")
    print("    occurrences = total matching values")
    print("    subjects    = distinct subjects that have at least one matching value")
    print("    population  = all current instances of the subject class")
    print("    coverage    = subjects divided by population")
    print("    cardinality = values per participating subject; entities with no value")
    print("                  affect coverage, not the cardinality numbers")
    print("    These are observations about current data, not ontology rules.")
    print("  Controls:")
    print("    There are no pattern filters or thresholds in this viewer, and rare")
    print("    patterns are kept. Modeling/name predicates and onto:kind are ignored.")
    print("    Developers can change those exclusions in graph_patterns.py.")
    print(f"  Observed patterns ({len(patterns)}):")
    for record in patterns:
        subject = label(record["subject_class"])
        predicate = label(record["predicate"])
        target = (f"literal ({label(record['range'])})"
                  if record["range_kind"] == "datatype"
                  else label(record["range"] or "unknown"))
        population = record["class_population"]
        population = population if population is not None else "-"
        coverage = record["coverage"]
        coverage = f"{coverage:.0%}" if coverage is not None else "-"
        print(f"    {subject} --{predicate}--> {target}")
        print(f"      occurrences {record['occurrences']}, "
              f"subjects {record['distinct_subjects']}, "
              f"population {population}, coverage {coverage}")
        print(f"      cardinality min {record['cardinality_min']}, "
              f"median {record['cardinality_median']:g}, "
              f"max {record['cardinality_max']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path, nargs="?",
                        default=Path("ontology.ttl"))
    parser.add_argument("-html", "--html", type=Path, nargs="?",
                        const=Path("ontology_views.html"), metavar="FILE",
                        help="write an explained HTML page instead of printing; "
                             "the default file is ontology_views.html")
    args = parser.parse_args()

    graph = open_graph(args.graph)
    views = build_ontology_views(graph)
    if args.html is not None:
        write_report(args.graph, graph, views, args.html)
        print(f"Wrote {args.html} from {args.graph} ({len(graph)} triples)")
        return

    print(f"Views of {args.graph}:")
    print("  An RDF triple is one subject-predicate-object statement.")
    print("  All views below are generated in memory and do not change the graph file.")
    print("  Viewer control: pass a different graph path, or -html to write the")
    print("  same views as an explained HTML page; there are no filter options.")
    report_partitions(views)
    report_skeleton_help()
    report_skeleton(views["skeleton"])
    report_patterns(views["patterns"])


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
