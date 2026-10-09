"""Turn a plain RDF file into a studio dataset (TriG with named graphs).

The application keeps its knowledge in named graphs: the schema (classes and
relationships), the data (individuals and their statements), provenance, and
so on. An ontology from elsewhere is one plain file: Turtle, RDF/XML, or a
.trig file with everything in the default graph. This script sorts it into
those named graphs, keeping the file's own IRIs, so ingestion then uses its
classes and relationships.

    python ttl_to_trig.py my_ontology.ttl ontology.trig
    python ttl_to_trig.py my_ontology.ttl ontology.trig --force   # replace
    python ttl_to_trig.py glossary.ttl ontology.trig --concepts-as-classes

Many business vocabularies are SKOS glossaries: their terms ("Client",
"Contract") are skos:Concept, not classes, so nothing could be typed with
them. --concepts-as-classes also declares every skos:Concept an owl:Class
(OWL 2 allows one IRI to be both), turns skos:broader into rdfs:subClassOf,
and gives each class an rdfs:label (from skos:prefLabel) and a short
rdfs:comment (from dct:description, else skos:definition). Every SKOS triple
is kept as it was.

It writes only to the output you name, and never replaces an existing file
unless you pass --force. A file that declares no classes or properties is
refused, and nothing is written.
"""

import argparse
import sys
from pathlib import Path

from rdflib import Dataset, Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.starter import import_publication, import_summary, parse_rdf

DCT = Namespace("http://purl.org/dc/terms/")


def concepts_as_classes(graph):
    """Declare every skos:Concept a class too; returns how many there were."""
    concepts = sorted(set(graph.subjects(RDF.type, SKOS.Concept)), key=str)
    for concept in concepts:
        graph.add((concept, RDF.type, OWL.Class))
        for broader in graph.objects(concept, SKOS.broader):
            graph.add((concept, RDFS.subClassOf, broader))
        if graph.value(concept, RDFS.label) is None:
            for name in graph.objects(concept, SKOS.prefLabel):
                graph.add((concept, RDFS.label, name))
        if graph.value(concept, RDFS.comment) is None:
            meaning = (graph.value(concept, DCT.description)
                       or graph.value(concept, SKOS.definition))
            if meaning is not None:
                graph.add((concept, RDFS.comment, meaning))
    return len(concepts)


def with_concepts_as_classes(text, name):
    """The source as Turtle text, with its SKOS concepts declared classes."""
    _format, parsed = parse_rdf(text, name)
    graph = Graph()
    for prefix, namespace in parsed.namespaces():
        graph.bind(prefix, namespace)
    # A TriG source may spread its triples over several graphs: take them all.
    triples = (parsed.quads((None, None, None, None))
               if isinstance(parsed, Dataset) else parsed)
    for triple in triples:
        graph.add(triple[:3])
    count = concepts_as_classes(graph)
    return graph.serialize(format="turtle"), count


def build_parser():
    parser = argparse.ArgumentParser(
        description="Turn a plain RDF file into a studio dataset.")
    parser.add_argument("source", type=Path,
                        help="the RDF file: .ttl, .trig, .nt, .rdf, .owl, ...")
    parser.add_argument("output", type=Path,
                        help="the TriG dataset to write, e.g. ontology.trig")
    parser.add_argument("--force", action="store_true",
                        help="replace the output file if it already exists")
    parser.add_argument("--concepts-as-classes", action="store_true",
                        help="also declare every skos:Concept an owl:Class, "
                             "so ingestion can type things with it")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.source.resolve() == args.output.resolve():
        print("Error: the output must be a different file than the source",
              file=sys.stderr)
        return 1
    if args.output.exists() and not args.force:
        print(f"Error: {args.output} already exists; pass --force to "
              f"replace it", file=sys.stderr)
        return 1
    try:
        text = args.source.read_text(encoding="utf-8")
        name = args.source.name
        if args.concepts_as_classes:
            text, count = with_concepts_as_classes(text, name)
            name = args.source.stem + ".ttl"
            print(f"{count} SKOS concepts declared as classes")
        # Everything is checked in memory first: a refused file never costs
        # the existing output.
        publication, summary = import_publication(text, name, GraphNames())
        if args.output.exists():
            args.output.unlink()
        RdflibGraphStore(path=args.output).publish(publication)
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(import_summary(summary))
    print(f"{args.source} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
