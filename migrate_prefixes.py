"""Move a dataset made before the src:/trace: split to the new prefixes.

Older datasets kept everything under one namespace (onto:): candidates,
windows, documents, review records, and the source links all looked like
business data. Since then:

    src:    (.../source/)  which file said what - kept in the data graph
    trace:  (.../trace/)   how the run got there - provenance and review

This script rewrites one old dataset into a new file:

  - every entity that had `onto:sourceFile` gets `src:fromFile` in the data
    graph, pointing to one `src:file/<hash of path>` node per path;
  - every published relation or fact gets a `src:statement/<hash>` node in
    the data graph, with its `src:fromFile` links;
  - candidates, windows, documents, review records, and merge audit move
    under `trace:`; the old `onto:statement/...` records in provenance are
    dropped (their source links are now in the data graph);
  - the per-window candidate evidence (trace:candidate/, window/, activity/,
    agent/, metric/) is dropped unless you pass --keep-candidates, the same
    as a run without --trace.

    python migrate_prefixes.py ontology_bckp.trig ontology_new.trig
    python migrate_prefixes.py old.trig new.trig --keep-candidates

It never writes to the input file, and refuses to replace an existing output.
"""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rdflib import Graph, Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF, RDFS  # noqa: E402

from text_to_ontology.graph_management import (  # noqa: E402
    BASE, ONTO, SRC, TRACE,
)
from text_to_ontology.graph_store import (  # noqa: E402
    GraphNames, Publication, RdflibGraphStore,
)
from text_to_ontology.publication_sources import statement_uri  # noqa: E402
from text_to_ontology.vocabulary import read_vocabulary  # noqa: E402

# Old IRI families (directly under onto:) that are tracing now.
TRACE_FAMILIES = (
    "candidate/", "window/", "activity/", "agent/", "metric/", "review/",
    "document/", "merge-event/", "merge-candidate/", "merge-proposed-entity/",
    "provisional/", "edit/", "staging/",
)
# Of those, the per-window candidate evidence that only --trace keeps.
CANDIDATE_FAMILIES = ("candidate/", "window/", "activity/", "agent/",
                      "metric/")
# Old onto: predicates and types that are tracing vocabulary now.
TRACE_TERMS = (
    "sourceDocument", "sourceFile", "sourcePath", "ExtractionEvent",
    "MergeCandidate", "sourceSha256", "modelName", "mergePolicyVersion",
    "candidatePackageSha256", "wasExtractedIn", "candidateSection",
    "candidateIndex", "extractionConfidence", "mergeDecision",
    "decisionReason", "normalizedCandidate", "resolvedEntity",
    "proposedEntity", "fieldDecisions", "editSource", "editAdded",
    "editRemoved",
)
OLD_STATEMENT = BASE + "statement/"
OLD_FILE = BASE + "source-file/"


def new_file_uri(path):
    """The same file IRI a new run gives this path."""
    return SRC["file/" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()]


def rename(term, files):
    """The new IRI of one old term (unchanged when it is business data)."""
    if not isinstance(term, URIRef) or not str(term).startswith(BASE):
        return term
    if term in files:
        return files[term]
    local = str(term)[len(BASE):]
    if local.startswith(TRACE_FAMILIES) or local in TRACE_TERMS:
        return TRACE[local]
    return term


def is_candidate_evidence(subject):
    local = str(subject)[len(BASE):] if str(subject).startswith(BASE) else ""
    return local.startswith(CANDIDATE_FAMILIES)


def migrate(store, names, keep_candidates=False):
    """The migrated role graphs, as {graph name: Graph}. Reads only."""
    roles = {name: store.get(name) for name in store.graph_names()}
    data = roles.get(names.target_graph, Graph())
    provenance = roles.get(names.provenance_graph, Graph())
    business = Graph()
    for name in [*names.schema_graphs, *names.data_graphs, names.target_graph]:
        for triple in roles.get(name, ()):
            business.add(triple)
    vocabulary = read_vocabulary(business)
    assertion_predicates = set(vocabulary.relations) | set(vocabulary.facts)

    # One new src:file node per old file record (per path).
    files = {}
    new_data = Graph()
    for record in set(provenance.subjects(ONTO.sourcePath, None)) | set(
            roles.get(names.review_graph, Graph()).subjects(ONTO.sourcePath,
                                                            None)):
        source = (provenance.value(record, ONTO.sourcePath)
                  or roles[names.review_graph].value(record, ONTO.sourcePath))
        label = (provenance.value(record, RDFS.label)
                 or Literal(Path(str(source)).name))
        files[record] = new_file_uri(source)
        new_data.add((files[record], RDF.type, SRC.SourceFile))
        new_data.add((files[record], RDFS.label, label))
        new_data.add((files[record], SRC.path, Literal(str(source))))

    # Entities and published relations/facts name their files.
    for subject, file in provenance.subject_objects(ONTO.sourceFile):
        if file not in files:
            continue
        if (subject, RDF.type, ONTO.Entity) in data:
            new_data.add((subject, SRC.fromFile, files[file]))
        elif str(subject).startswith(OLD_STATEMENT):
            triple = tuple(provenance.value(subject, part)
                           for part in (RDF.subject, RDF.predicate, RDF.object))
            if None not in triple and triple in data \
                    and str(triple[1]) in assertion_predicates:
                node = statement_uri(triple)
                new_data.add((node, RDF.type, RDF.Statement))
                new_data.add((node, RDF.subject, triple[0]))
                new_data.add((node, RDF.predicate, triple[1]))
                new_data.add((node, RDF.object, triple[2]))
                new_data.add((node, SRC.fromFile, files[file]))

    result = {}
    for name, graph in roles.items():
        migrated = Graph()
        for subject, predicate, object_ in graph:
            if name != names.target_graph and (
                    subject in files or str(subject).startswith(OLD_STATEMENT)):
                continue  # file records and canonical statements moved
            if name != names.target_graph and predicate == ONTO.sourceFile \
                    and (subject, RDF.type, ONTO.Entity) in data:
                continue  # entity file links moved to the data graph
            if not keep_candidates and is_candidate_evidence(subject):
                continue
            migrated.add((rename(subject, files), rename(predicate, files),
                          rename(object_, files)))
        result[name] = migrated
    for triple in new_data:
        result.setdefault(names.target_graph, Graph()).add(triple)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Move an old dataset to the src:/trace: prefixes.")
    parser.add_argument("source", type=Path, help="the old .trig dataset")
    parser.add_argument("output", type=Path, help="the new .trig to write")
    parser.add_argument("--keep-candidates", action="store_true",
                        help="keep the per-window candidate evidence")
    args = parser.parse_args(argv)
    if args.output.resolve() == args.source.resolve():
        raise SystemExit("Error: write to a new file, not over the input")
    if args.output.exists():
        raise SystemExit(f"Error: {args.output} already exists")
    names = GraphNames()
    graphs = migrate(RdflibGraphStore(args.source), names,
                     keep_candidates=args.keep_candidates)
    RdflibGraphStore(args.output).publish(Publication(graphs=graphs))
    before = sum(len(RdflibGraphStore(args.source).get(name))
                 for name in graphs)
    after = sum(len(graph) for graph in graphs.values())
    print(f"Wrote {args.output}: {after} triples (was {before})")


if __name__ == "__main__":
    main()
