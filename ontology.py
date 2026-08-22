#!/usr/bin/env python3
"""Add knowledge from text files to one Turtle graph."""

import argparse
import json
import sys
import time
from pathlib import Path

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from candidate_validation import format_validation_failure, validate_candidates
from context_render import prepare_prompt_context
from graph_management import open_graph, save_graph
from graph_merge import apply_merge_plan
from graph_partition import partition_graph
from graph_skeleton import create_graph_skeleton
from ingest_sources import find_text_files, read_source
from llm import model_name
from merge_policy import build_provenance, plan_graph_merge
from prompt_budget import PROMPT_BUDGET, estimate_tokens
from source_parse import parse_source
from task_context import build_task_context, local_name


def budget_for(text):
    """The approved prompt budget, with this source's own cost filled in."""
    return dict(PROMPT_BUDGET, source_tokens=estimate_tokens(text))


def report_context(budget, verbose):
    """One line about what context this file received, and what did not fit."""
    print(f"  Context: {len(budget['items'])} items, "
          f"{budget['used_tokens']}/{budget['budget_tokens']} tokens, "
          f"{len(budget['dropped_ids'])} items did not fit", flush=True)
    if not verbose:
        return
    for entry in budget["items"]:
        print(f"    kept    {entry['id']} ({entry['section']}, "
              f"priority {entry['priority']})")
    for dropped in budget["dropped_ids"]:
        print(f"    dropped {dropped}")


def report_extraction(extraction):
    """The model's raw response, before anything validates or changes it."""
    print("  Raw model response:", flush=True)
    print(json.dumps(extraction, indent=2, ensure_ascii=False), flush=True)


def report_validation(validation, verbose):
    """One line about the candidate counts and duplicates the validator removed."""
    counts = validation["counts"]
    removed = counts["duplicates_removed"]
    duplicates = (removed["entities"] + removed["relations"]
                  + removed["facts"] + removed["aliases"])
    print(f"  Validated: {counts['normalized']['entities']} entities, "
          f"{counts['normalized']['relations']} relations, "
          f"{counts['normalized']['facts']} facts; "
          f"{duplicates} duplicates removed", flush=True)
    if not verbose:
        return
    for issue in validation["issues"]:
        if issue["severity"] == "warning":
            print(f"    warning {issue['path']} [{issue['code']}]: "
                  f"{issue['message']}")


def report_plan(plan, verbose):
    """One line about what merge policy decided before anything is written."""
    counts = plan["counts"]
    identities = counts["identities"]
    assertions = counts["assertions"]
    summaries = counts["entity_summaries"]
    duplicates = assertions["duplicate"] + summaries["duplicate"]
    review = (assertions["review"] + summaries["review"]
              + summaries["partial_review"])
    print(f"  Planned: {identities['new']} new, {identities['resolved']} "
          f"resolved, {identities['review']} review identities; "
          f"{assertions['accepted']} accepted, {duplicates} corroborated, "
          f"{review} for review; {counts['audit_triples']} audit triples",
          flush=True)
    if not verbose:
        return
    for local_id, decision in sorted(plan["identities"].items()):
        target = decision["uri"] or "(unresolved)"
        print(f"    identity {local_id}: {decision['status']} -> {target}")
    for section in ("entities", "relations", "facts"):
        for item in plan[section]:
            reasons = ",".join(item.get("reason_codes", []))
            suffix = f" ({reasons})" if reasons else ""
            if section == "entities":
                print(f"    entity {item['local_id']}: "
                      f"{item['summary']}{suffix}")
            else:
                print(f"    {section[:-1]} {item['index']}: "
                      f"{item['outcome']}{suffix}")


def skeleton_label(skeleton, term):
    """A readable name: preferred label, label, else the decoded local name."""
    for predicate in (SKOS.prefLabel, RDFS.label):
        found = skeleton.value(term, predicate)
        if found:
            return str(found)
    return local_name(term)


def skeleton_restriction(skeleton, node):
    """One restriction, shown as compact onProperty/constraint text."""
    parts = []
    for _, predicate, target in sorted(skeleton.triples((node, None, None)),
                                       key=lambda triple: str(triple[1])):
        text = f'"{target}"' if isinstance(target, Literal) \
            else skeleton_label(skeleton, target)
        parts.append(f"{local_name(predicate)} {text}")
    return ", ".join(parts)


def report_skeleton(skeleton):
    # Where the skeleton comes from:
    #   partition_graph() in graph_partition.py first splits the graph into
    #   schema / instance / support views;
    #   create_graph_skeleton() in graph_skeleton.py then copies out of the
    #   schema view only the declared structural core: owl:Class and property
    #   declarations, named rdfs:subClassOf / rdfs:domain / rdfs:range axioms,
    #   whole supported restrictions, plus their labels and comments.
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


def report_task_context(context, source_graph):
    """What build_task_context produced for this source, without the text."""
    # The skeleton is the same view the selector matched against, so it is
    # rebuilt here read only (verbose runs only).
    schema, _, _ = partition_graph(source_graph)
    report_skeleton(create_graph_skeleton(schema))
    diagnostics = context["diagnostics"]
    candidates = diagnostics["candidate_counts"]
    selected = diagnostics["selected_counts"]
    limits = diagnostics["limits"]
    print("  Task context:", flush=True)
    # Concepts: extract_source_concepts(text) in source_concepts.py — what the
    # text mentions (headings, capitalized spans, frequent phrases), capped at
    # the limit.
    print(f"    concepts extracted: {len(context['concepts'])} "
          f"(limit {limits['concepts']})", flush=True)
    for concept in context["concepts"]:
        print(f"      {concept['text']} ({concept['kind']}, "
              f"{concept['origin']}, weight {concept['weight']:.2f})")
    # Candidates: everything in the graph the source could possibly match,
    # gathered by candidates() in task_context.py from three index builders:
    #   classes + properties  schema_index() over the skeleton view;
    #   resources             resource_index() over the instance view, merged
    #                         with entity_catalog(graph) ids;
    #   patterns              observed_relationships() in graph_patterns.py.
    print(f"    graph offered: {candidates['classes']} classes, "
          f"{candidates['properties']} properties, "
          f"{candidates['resources']} resources, "
          f"{candidates['patterns']} patterns", flush=True)
    # Selected: the direct matches (name/label/concept/overlap) plus what
    # expansion added for them, each kind cut to its limit.
    print(f"    selected: {selected['matches']} matches -> "
          f"{selected['classes']} classes, {selected['properties']} properties, "
          f"{selected['restrictions']} restrictions, {selected['patterns']} patterns, "
          f"{selected['resources']} resources, {selected['examples']} examples",
          flush=True)
    # The four sections, in the order the renderer assembles them:
    #   schema    declared triples from the skeleton (classes, properties,
    #             restrictions);
    #   patterns  observed class-predicate-range statistics, as evidence;
    #   resources entity cards with their exact identifiers;
    #   examples  one-hop instance assertions around matched resources.
    for section in ("schema", "patterns", "resources", "examples"):
        print(f"    {section}:", flush=True)
        for entry in context[section]:
            print(f"      [{entry['priority']}] {entry['id']} -- "
                  f"{entry['reason']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a text file or directory")
    parser.add_argument("graph", type=Path, nargs="?", default=Path("ontology.ttl"))
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every intermediate artifact, step by step")
    args = parser.parse_args()

    graph = open_graph(args.graph)
    files = find_text_files(args.source, args.graph)
    if not files:
        raise RuntimeError("No text-like files found")

    args.graph.parent.mkdir(parents=True, exist_ok=True)
    for path in files:
        print(f"Reading {path}", flush=True)
        text = read_source(path)
        if not text.strip():
            continue
        # Read only, and rebuilt for every file: the graph has grown since the
        # last one, so last file's context is not this file's context.
        context = build_task_context(text, graph)
        if args.verbose:
            report_task_context(context, graph)
        prompt_context = prepare_prompt_context(context, budget_for(text))
        report_context(prompt_context["budget"], args.verbose)
        if args.verbose:
            print("  Prompt context text:", flush=True)
            print(prompt_context["text"], flush=True)


        model = model_name()
        print(f"  Asking {model} (this can take a minute)...", flush=True)
        started = time.monotonic()
        extraction = parse_source(text, prompt_context["text"])
        print(f"  Model replied in {time.monotonic() - started:.1f} seconds", flush=True)
        if args.verbose:
            report_extraction(extraction)
        validation = validate_candidates(
            extraction, graph, prompt_context["existing_ids"])
        report_validation(validation, args.verbose)
        if not validation["valid"]:
            raise RuntimeError(format_validation_failure(validation))
        # Plan first, read only; materialize the completed plan into a copy;
        # save it; only then does the saved graph feed the next source.
        provenance = build_provenance(path, text, model)
        plan = plan_graph_merge(graph, validation["candidates"], provenance)
        report_plan(plan, args.verbose)
        updated, counts = apply_merge_plan(graph, plan)
        save_graph(updated, args.graph)
        graph = updated
        print(f"  {counts['new_entities']} new, "
              f"{counts['resolved_entities']} resolved, "
              f"{counts['relation_triples']} relations, "
              f"{counts['fact_triples']} facts")
    print(f"Saved {len(graph)} triples to {args.graph}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
