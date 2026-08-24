"""Human-readable reporting for one ontology pipeline run."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS

from .graph_partition import partition_graph
from .graph_skeleton import create_graph_skeleton
from .task_context import local_name


REPORT_DIRECTORY = Path("reports/runs")


def default_report_path(source, started_at=None):
    """A readable, unique Markdown path for one run."""
    started_at = started_at or datetime.now().astimezone()
    source_name = Path(source).stem or "source"
    source_name = re.sub(r"[^A-Za-z0-9_-]+", "-", source_name).strip("-")
    source_name = source_name or "source"
    timestamp = started_at.strftime("%Y-%m-%d_%H-%M-%S_%f")
    return REPORT_DIRECTORY / f"{timestamp}_{source_name}.md"


def skeleton_label(skeleton, term):
    """A readable skeleton name: preferred label, label, or local name."""
    for predicate in (SKOS.prefLabel, RDFS.label):
        found = skeleton.value(term, predicate)
        if found:
            return str(found)
    return local_name(term)


def skeleton_restriction(skeleton, node):
    """One restriction as compact onProperty/constraint text."""
    parts = []
    for _, predicate, target in sorted(
            skeleton.triples((node, None, None)),
            key=lambda triple: str(triple[1])):
        text = f'"{target}"' if isinstance(target, Literal) \
            else skeleton_label(skeleton, target)
        parts.append(f"{local_name(predicate)} {text}")
    return ", ".join(parts)


class RunReporter:
    """Write normal or verbose run reports to one replaceable text stream."""

    def __init__(self, verbose=False, stream=None, extra_streams=(),
                 markdown_streams=()):
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stdout
        self.streams = [self.stream, *extra_streams]
        self.markdown_streams = set(markdown_streams)

    def line(self, text=""):
        for stream in self.streams:
            rendered = f"{text}  " if text and stream in self.markdown_streams \
                else text
            print(rendered, file=stream, flush=True)

    def verbose_line(self, text=""):
        if self.verbose:
            self.line(text)

    def block(self, text, language="text"):
        """Write an exact code block without Markdown hard-break changes."""
        longest = max((len(match.group())
                       for match in re.finditer(r"`+", str(text))), default=0)
        fence = "`" * max(3, longest + 1)
        for stream in self.streams:
            print(f"{fence}{language}", file=stream)
            print(text, file=stream)
            print(fence, file=stream, flush=True)

    def section(self, title):
        self.verbose_line(f"\n## {title}")

    def run_started(self, source, graph_path, started_at, report_path=None):
        if not self.verbose:
            return
        self.line("# Ontology extraction report")
        self.line("")
        self.line(f"- Started: {started_at.isoformat(timespec='seconds')}")
        self.line(f"- Source: {source}")
        self.line(f"- Graph: {graph_path}")
        if report_path is not None:
            self.line(f"- Report: {report_path}")

    def source_started(self, path, index, total, graph_size):
        if self.verbose:
            self.section(f"Source {index}/{total}: {path}")
            self.line(f"  Source {index}/{total}; graph before: {graph_size} triples")
        else:
            self.line(f"Reading {path}")

    def blank_source(self):
        self.verbose_line("  Blank source: skipped")

    def document_staging(self, document_id, staging_name, windows):
        """Announce one document's stable source staging graph."""
        self.line(f"  Document {document_id}: {windows} window(s); "
                  f"staging graph {staging_name}")

    def window_started(self, number, total, window_id):
        if self.verbose:
            self.line(f"  Window {number}/{total}: {window_id}")

    def window_admitted(self, number, total, counts, source_size):
        """Report what one window added to its source graph - not publication."""
        accepted = counts.get("relation_triples", 0) + counts.get(
            "fact_triples", 0)
        summary = (f"  Window {number}/{total} admitted "
                   f"{counts.get('new_entities', 0)} new entities and "
                   f"{accepted} assertions; source graph now "
                   f"{source_size} triples")
        if not self.verbose:
            self.line(summary)
            return
        self.section(f"Source-local admission, window {number}/{total}")
        self.line(summary)
        self.line(f"  Corroborated in source graph: {counts.get('duplicates', 0)}")
        self.line(f"  Held for review in source graph: {counts.get('review', 0)}")

    def reconciliation(self, report):
        """Report the complete document's local identity and assertion state."""
        counts = report["counts"]
        summary = (
            f"  Reconciled source: {counts['local_entities']} local entities, "
            f"{counts['aliases']} aliases, "
            f"{counts['duplicate_assertions']} duplicate assertions, "
            f"{counts['unresolved_identities']} unresolved identities, "
            f"{counts['conflicts']} conflicts")
        self.line(summary)
        if not self.verbose:
            return
        self.section("[6a] Complete-source reconciliation")
        self.line(summary)
        for entity in report["local_entities"]:
            self.line(f"  Entity: {entity['name']} ({entity['uri']})")
            self.line(f"    kind: {entity['kind']}")
            self.line("    aliases: " +
                      (", ".join(entity["aliases"]) or "(none)"))
        for assertion in report["duplicate_assertions"]:
            self.line("  Duplicate assertion: " +
                      " | ".join(assertion["triple"]))
            self.line(f"    independent supports: "
                      f"{assertion['support_count']}")
        for identity in report["unresolved_identities"]:
            self.line(f"  Unresolved {identity['local_id']} in "
                      f"{identity['window_id']}: " +
                      ", ".join(identity["reason_codes"]))
        for conflict in report["conflicts"]:
            self.line(f"  Conflict {conflict['section']}[{conflict['index']}] "
                      f"in {conflict['window_id']}: " +
                      ", ".join(conflict["reason_codes"]))

    def source_validation(self, result):
        """Report the SHACL gate before any final merge plan is built."""
        result_count = len(set(result.report_graph.subjects(
            RDF.type, SH.ValidationResult)))
        status = "PASS" if result.conforms else "FAIL"
        summary = (f"  SHACL source validation: {status}; "
                   f"{result.shape_graphs_checked} shape graph(s), "
                   f"{result_count} result(s)")
        self.line(summary)
        if self.verbose:
            self.section(f"[6b] Complete-source SHACL validation: {status}")
            self.line(summary)
            if not result.conforms:
                self.block(result.report_graph.serialize(format="turtle"),
                           language="turtle")

    def publication_validation(self, result):
        """Report SHACL validation of the proposed post-merge data."""
        result_count = len(set(result.report_graph.subjects(
            RDF.type, SH.ValidationResult)))
        status = "PASS" if result.conforms else "FAIL"
        summary = (f"  Proposed data SHACL validation: {status}; "
                   f"{result.shape_graphs_checked} shape graph(s), "
                   f"{result_count} result(s)")
        self.line(summary)
        if self.verbose:
            self.section(f"[7b] Proposed post-merge SHACL validation: {status}")
            self.line(summary)
            if not result.conforms:
                self.block(result.report_graph.serialize(format="turtle"),
                           language="turtle")

    def dry_run(self, graph_path, before_size, proposed, counts):
        """Report an exact plan that deliberately was not published."""
        self.section("[8] Dry run")
        self.line(f"  Proposed graph: {before_size} -> {len(proposed)} triples")
        self.line(f"  Would publish atomically to {graph_path}")
        self.line("  Final graphs unchanged")

    def staging_failed(self, document_id, retained, sidecar_path):
        """Record whether a failed document's staging graphs were kept."""
        if retained and sidecar_path is not None:
            self.line(f"  Staging graphs of {document_id} retained for "
                      f"diagnosis in {sidecar_path}")
        else:
            self.line(f"  Staging graphs of {document_id} discarded")

    def context_selection(self, context, source_graph):
        """Report the structured context selected before prompt budgeting."""
        if not self.verbose:
            return

        self.section("[2-3] Context selection inputs")
        self.line("  Available graph skeleton (selector input; not sent wholesale):")
        schema, _, _ = partition_graph(source_graph)
        self._skeleton(create_graph_skeleton(schema))

        diagnostics = context["diagnostics"]
        candidates = diagnostics["candidate_counts"]
        selected = diagnostics["selected_counts"]
        limits = diagnostics["limits"]

        self.line(f"  Concepts: {len(context['concepts'])}/{limits['concepts']}")
        for concept in context["concepts"]:
            self.line(f"    {concept['text']} ({concept['kind']}, "
                      f"{concept['origin']}, weight {concept['weight']:.2f})")

        self.line("  Graph candidates: "
                  f"{candidates['classes']} classes, "
                  f"{candidates['properties']} properties, "
                  f"{candidates['resources']} resources, "
                  f"{candidates['patterns']} patterns")
        self.line(f"  Selected: {selected['matches']} matches -> "
                  f"{selected['classes']} classes, "
                  f"{selected['properties']} properties, "
                  f"{selected['restrictions']} restrictions, "
                  f"{selected['patterns']} patterns, "
                  f"{selected['resources']} resources, "
                  f"{selected['examples']} examples")

        for section in ("schema", "patterns", "resources", "examples"):
            self.line(f"  {section.capitalize()}:")
            for entry in context[section]:
                self.line(f"    [{entry['priority']}] {entry['id']} -- "
                          f"{entry['reason']}")

    def prompt_context(self, prompt_context):
        """Always report the budget; show its contents only in verbose mode."""
        budget = prompt_context["budget"]
        summary = (f"  Context: {len(budget['items'])} items, "
                   f"{budget['used_tokens']}/{budget['budget_tokens']} tokens, "
                   f"{len(budget['dropped_ids'])} items did not fit")
        if not self.verbose:
            self.line(summary)
            return

        self.section("[4] Prompt context")
        self.line("  This selected, budgeted context is embedded in the user "
                  "message shown in the next section.")
        self.line(summary)
        for entry in budget["items"]:
            self.line(f"    kept    {entry['id']} ({entry['section']}, "
                      f"priority {entry['priority']})")
        for dropped in budget["dropped_ids"]:
            self.line(f"    dropped {dropped}")
        reusable = prompt_context["existing_ids"]
        self.line(f"  Reusable existing IDs: {len(reusable)}")
        for identity in reusable:
            self.line(f"    {identity}")
        self.line("  Prompt context text:")
        if prompt_context["text"]:
            for line in prompt_context["text"].splitlines():
                self.line(f"    {line}")
        else:
            self.line("    (empty)")

    def asking_model(self, model):
        if self.verbose:
            self.section("[5] Main LLM call and extraction")
            self.line(f"  Model: {model}")
            self.line("  Asking model (this can take a minute)...")
        else:
            self.line(f"  Asking {model} (this can take a minute)...")

    def llm_input(self, system_prompt, user_prompt):
        """Show the exact two messages that are sent to the extraction LLM."""
        if not self.verbose:
            return
        self.line("  Exact request: temperature 0, followed by these messages.")
        self.line("  System message:")
        self.block(system_prompt)
        self.line("  User message (instructions + selected context + source):")
        self.block(user_prompt)

    def model_replied(self, extraction, elapsed):
        self.line(f"  Model replied in {elapsed:.1f} seconds")
        if not self.verbose:
            return

        if not isinstance(extraction, dict):
            self.line(f"  Parsed JSON value: {type(extraction).__name__} (untrusted)")
            self.line(f"    {self._json(extraction)}")
            return

        counts = {
            section: len(extraction.get(section, []))
            if isinstance(extraction.get(section), list) else "invalid"
            for section in ("entities", "relations", "facts")
        }
        self.line("  Parsed JSON (untrusted): "
                  f"{counts['entities']} entities, "
                  f"{counts['relations']} relations, "
                  f"{counts['facts']} facts")
        self._extraction_records(extraction)

    def validation(self, validation):
        """Report the validator's result without making policy decisions."""
        counts = validation["counts"]
        removed = counts["duplicates_removed"]
        duplicate_total = sum(removed.values())
        summary = (f"  Validated: {counts['normalized']['entities']} entities, "
                   f"{counts['normalized']['relations']} relations, "
                   f"{counts['normalized']['facts']} facts; "
                   f"{duplicate_total} duplicates removed")
        if not self.verbose:
            self.line(summary)
            return

        status = "PASS" if validation["valid"] else "FAIL"
        self.section(f"[6] Validation: {status}")
        self.line(summary)
        input_counts = counts["input"]
        self.line("  Input: "
                  f"{input_counts['entities']} entities, "
                  f"{input_counts['relations']} relations, "
                  f"{input_counts['facts']} facts")
        self.line(f"  Normalized fields: {counts['normalized_fields']}")
        self.line("  Removed duplicates: "
                  f"{removed['entities']} entities, "
                  f"{removed['relations']} relations, "
                  f"{removed['facts']} facts, "
                  f"{removed['aliases']} aliases")
        self.line(f"  Issues: {counts['errors']} errors, "
                  f"{counts['warnings']} warnings")
        for issue in validation["issues"]:
            self.line(f"    {issue['severity'].upper()} {issue['path']}")
            self.line(f"      {issue['code']}: {issue['message']}")
            if issue["related_paths"]:
                self.line("      related: " + ", ".join(issue["related_paths"]))
        if not validation["valid"]:
            self.line("  Result: whole extraction rejected; graph unchanged")

    def merge_plan(self, plan, candidates, graph):
        """Report identity, entity-field, and assertion decisions."""
        counts = plan["counts"]
        identities = counts["identities"]
        assertions = counts["assertions"]
        summaries = counts["entity_summaries"]
        duplicates = assertions["duplicate"] + summaries["duplicate"]
        review = (assertions["review"] + summaries["review"]
                  + summaries["partial_review"])
        summary = (f"  Planned: {identities['new']} new, "
                   f"{identities['resolved']} resolved, "
                   f"{identities['review']} review identities; "
                   f"{assertions['accepted']} accepted, "
                   f"{duplicates} corroborated, {review} for review; "
                   f"{counts['audit_triples']} audit triples")
        if not self.verbose:
            self.line(summary)
            return

        self.section(f"[7] Merge plan: policy v{plan['policy_version']}")
        self.line(summary)
        candidate_entities = {
            str(record.get("id")): record
            for record in candidates.get("entities", [])
            if isinstance(record, dict)
        }
        for local_id, decision in sorted(plan["identities"].items()):
            record = candidate_entities.get(local_id, {})
            self.line(f"  Identity {local_id}: {decision['status'].upper()}")
            self.line(f"    name: {record.get('name', '')}")
            self.line(f"    target: {self._term(decision['uri'], graph)}")
            self.line(f"    method: {decision['method']}")
            self.line(f"    confidence: {record.get('confidence', '')}")
            self._reasons(decision.get("reason_codes", []), indent="    ")
            for suggestion in decision.get("suggestions", []):
                score = suggestion.get("identity_score")
                score_text = "" if score is None else f", score {score:.3f}"
                self.line(f"    suggestion: "
                          f"{self._term(suggestion['uri'], graph)} "
                          f"({suggestion['method']}{score_text})")

        for entity in plan["entities"]:
            self.line(f"  Entity {entity['local_id']}: "
                      f"{entity['summary'].upper()}")
            self._entity_fields(entity["fields"])

        for section in ("relations", "facts"):
            records = candidates.get(section, [])
            for item in plan[section]:
                record = records[item["index"]]
                title = section[:-1].capitalize()
                self.line(f"  {title}[{item['index']}]: "
                          f"{item['outcome'].upper()}")
                self.line(f"    {self._assertion_text(section, record, item, graph)}")
                self.line(f"    confidence: {item['confidence']}")
                self._reasons(item.get("reason_codes", []), indent="    ")
                for conflict in item.get("conflicts", []):
                    self.line("    conflicts with: "
                              f"{self._triple(conflict, graph)}")

        self.line("  Planned triples: "
                  f"{counts['domain_triples']} domain, "
                  f"{counts['audit_triples']} audit")

    def saved(self, graph_path, before_size, updated, counts):
        """Report materialization and the successful atomic save."""
        if self.verbose:
            self.section("[8] Apply and save")
            change = len(updated) - before_size
            sign = "+" if change >= 0 else ""
            self.line(f"  Graph: {before_size} -> {len(updated)} triples "
                      f"({sign}{change})")
            self.line(f"  New entities: {counts['new_entities']}")
            self.line(f"  Resolved entities: {counts['resolved_entities']}")
            self.line(f"  Relations added: {counts['relation_triples']}")
            self.line(f"  Facts added: {counts['fact_triples']}")
            self.line(f"  Corroborated records: {counts.get('duplicates', 0)}")
            self.line(f"  Review records saved: {counts.get('review', 0)}")
            self.line(f"  Audit triples added: {counts.get('audit_triples', 0)}")
            self.line(f"  Saved atomically to {graph_path}")
        else:
            self.line(f"  {counts['new_entities']} new, "
                      f"{counts['resolved_entities']} resolved, "
                      f"{counts['relation_triples']} relations, "
                      f"{counts['fact_triples']} facts")

    def finished(self, graph, graph_path):
        self.line(f"Saved {len(graph)} triples to {graph_path}")

    def dry_run_finished(self, graph, graph_path):
        self.line(f"Dry run complete: {len(graph)} proposed triples; "
                  f"nothing written to {graph_path}")

    def failed(self, error):
        if self.verbose:
            self.section("Run failed")
            self.line(f"  Error: {error}")

    def _skeleton(self, skeleton):
        self.line(f"  {len(skeleton)} declared triples")
        subjects = {subject for subject, _, _ in skeleton}
        for subject in sorted(subjects, key=str):
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
                kind = "resource"
            self.line(f"    {kind}: {skeleton_label(skeleton, subject)}")
            for comment in skeleton.objects(subject, RDFS.comment):
                self.line(f"      comment: {comment}")
            for definition in skeleton.objects(subject, SKOS.definition):
                self.line(f"      definition: {definition}")
            for parent in skeleton.objects(subject, RDFS.subClassOf):
                if isinstance(parent, BNode):
                    self.line("      restricted by: "
                              f"{skeleton_restriction(skeleton, parent)}")
                else:
                    self.line("      subClassOf: "
                              f"{skeleton_label(skeleton, parent)}")
            for predicate, title in ((RDFS.domain, "domain"),
                                     (RDFS.range, "range")):
                for target in skeleton.objects(subject, predicate):
                    self.line(f"      {title}: "
                              f"{skeleton_label(skeleton, target)}")

    def _extraction_records(self, extraction):
        for section in ("entities", "relations", "facts"):
            records = extraction.get(section)
            if not isinstance(records, list):
                self.line(f"  {section.capitalize()}: invalid section")
                continue
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    self.line(f"  {section[:-1].capitalize()}[{index}]: "
                              f"{self._json(record)}")
                    continue
                if section == "entities":
                    title = f"Entity {record.get('id', index)}"
                    fields = ("name", "kind", "description", "aliases",
                              "existing_id", "confidence")
                else:
                    title = f"{section[:-1].capitalize()}[{index}]"
                    fields = ("subject", "predicate",
                              "object" if section == "relations" else "value",
                              "confidence")
                self.line(f"  {title}")
                for field in fields:
                    if field in record:
                        self.line(f"    {field}: {self._json(record[field])}")

    def _entity_fields(self, fields):
        for name in ("kind", "name", "aliases", "description"):
            value = fields.get(name)
            if isinstance(value, list):
                if not value:
                    self.line(f"    {name}: none")
                for item in value:
                    alias = item.get("alias", "")
                    suffix = f" {self._json(alias)}" if alias else ""
                    self.line(f"    {name}: {item['outcome'].upper()}{suffix}")
                    self._reasons(item.get("reason_codes", []), indent="      ")
            elif isinstance(value, dict):
                self.line(f"    {name}: {value['outcome'].upper()}")
                self._reasons(value.get("reason_codes", []), indent="      ")

    def _assertion_text(self, section, record, item, graph):
        if item.get("triple") is not None:
            return self._triple(item["triple"], graph)
        subject = record.get("subject", "?")
        predicate = record.get("predicate", "?")
        object_ = record.get("object", "?") if section == "relations" \
            else self._json(record.get("value"))
        return f"[{subject}] -- {predicate} --> [{object_}]"

    def _triple(self, triple, graph):
        subject, predicate, object_ = triple
        return (f"{self._term(subject, graph)} -- "
                f"{self._term(predicate, graph)} --> "
                f"{self._term(object_, graph)}")

    def _term(self, term, graph):
        if term is None:
            return "(unresolved)"
        try:
            return term.n3(namespace_manager=graph.namespace_manager)
        except (AttributeError, TypeError):
            if isinstance(term, str) and "://" in term:
                return URIRef(term).n3(namespace_manager=graph.namespace_manager)
            return str(term)

    def _reasons(self, reasons, indent=""):
        for reason in reasons:
            self.line(f"{indent}reason: {reason}")

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
