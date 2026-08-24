"""Plan how validated candidates may change the graph - without changing it.

Merge policy is an identity and conflict-resolution problem, kept separate from
both context selection (what the model sees) and validation (what is admissible).
The planner reads the current graph and the validated candidates and returns a
complete plain-record merge plan; a separate materializer applies it. Planning
never calls graph.add(), never serializes, and never mutates its inputs.

Policy version 1 is additive: existing canonical assertions are never replaced,
close spellings never merge automatically, and confidence below
AUTO_ACCEPT_MIN_CONFIDENCE blocks new domain assertions but not corroboration.
"""

import hashlib
import json
from decimal import Decimal

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from .entity_lookup import entity_catalog, identity_decision, identity_key
from .graph_management import CLASS, ENTITY, FACT, ONTO, RELATION
from .graph_merge import label, slug


MERGE_POLICY_VERSION = 1
AUTO_ACCEPT_MIN_CONFIDENCE = 0.80

RDF_JSON = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#JSON")

FUNCTIONAL = OWL.FunctionalProperty
INVERSE_FUNCTIONAL = OWL.InverseFunctionalProperty


def canonical_json(value):
    """UTF-8 canonical JSON: sorted keys, compact separators, list order kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def record_digest(record):
    """The lowercase SHA-256 hex digest of a record's canonical JSON."""
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def proposed_entity_uri(entity):
    """The deterministic review-only identity of a proposed (unaccepted) entity.

    A proposed URI is audit metadata, never typed as onto:Entity and never
    visible through entity_catalog().
    """
    return ONTO["merge-proposed-entity/" + record_digest(entity)]


def build_provenance(source_path, source_text, model):
    """The provenance context of one valid extraction, read only."""
    return {
        "source_path": source_path.as_posix(),
        "source_sha256": hashlib.sha256(
            source_text.encode("utf-8")).hexdigest(),
        "model": model,
        "policy_version": MERGE_POLICY_VERSION,
    }


def _triple_sort(triple):
    return (str(triple[0]), str(triple[1]), str(triple[2]))


def _decimal_confidence(value):
    """One stable xsd:decimal literal for a normalized float confidence."""
    return Literal(Decimal(str(value)))


class _Planner:
    """One planning pass over one graph and one candidate package."""

    def __init__(self, graph, candidates, provenance,
                 min_new_confidence=AUTO_ACCEPT_MIN_CONFIDENCE,
                 allocate_uri=None, provisional_uri=None):
        self.min_new_confidence = min_new_confidence
        self.graph = graph
        self.candidates = {
            section: [dict(record)
                      for record in candidates.get(section, [])]
            for section in ("entities", "relations", "facts")
        }
        self.provenance = dict(provenance)
        # None keeps resolve_entities' canonical defaults.
        self.identities = resolve_entities(
            self.candidates, graph, min_new_confidence=min_new_confidence,
            allocate_uri=allocate_uri, provisional_uri=provisional_uri)
        self.catalog = entity_catalog(graph)
        self.planned = self._planned_entries()
        # Virtual state: triples accepted earlier in this same plan.
        self.accepted = set()
        self.accepted_property_types = {}

    def _planned_entries(self):
        entries = []
        for record in self.candidates["entities"]:
            decision = self.identities.get(str(record.get("id")))
            if decision is not None and decision["status"] == "new":
                entries.append({
                    "id": str(decision["uri"]),
                    "names": [record["name"], *(record.get("aliases") or [])],
                    "kind": record["kind"],
                })
        return entries

    # ---------- shared lookups over real + virtual state ----------

    def entry_for(self, uri):
        for entry in self.catalog + self.planned:
            if entry["id"] == str(uri):
                return entry
        return None

    def own_label_keys(self, uri):
        entry = self.entry_for(uri)
        return {identity_key(name) for name in entry["names"]} if entry else set()

    def same_kind_owners(self, name, kind, exclude_uri):
        wanted = (identity_key(kind), identity_key(name))
        if not wanted[0] or not wanted[1]:
            return []
        owners = set()
        for entry in self.catalog + self.planned:
            if entry["id"] == str(exclude_uri):
                continue
            if identity_key(entry["kind"]) != wanted[0]:
                continue
            if wanted[1] in {identity_key(n) for n in entry["names"]}:
                owners.add(entry["id"])
        return sorted(owners)

    def property_types(self, predicate):
        types = set(self.graph.objects(predicate, RDF.type))
        declared = self.accepted_property_types.get(str(predicate))
        if declared is not None:
            types.add(declared)
        return types

    def objects_of(self, subject, predicate):
        found = set(self.graph.objects(subject, predicate))
        found |= {triple[2] for triple in self.accepted
                  if triple[0] == subject and triple[1] == predicate}
        return found

    def subjects_of(self, predicate, object_):
        found = set(self.graph.subjects(predicate, object_))
        found |= {triple[0] for triple in self.accepted
                  if triple[1] == predicate and triple[2] == object_}
        return found

    # ---------- event identity ----------

    def package_digest(self):
        return hashlib.sha256(
            canonical_json(self.candidates).encode("utf-8")).hexdigest()

    def event_uri(self):
        seed = canonical_json({
            "policy_version": MERGE_POLICY_VERSION,
            "source_path": self.provenance["source_path"],
            "source_sha256": self.provenance["source_sha256"],
            "model": self.provenance["model"],
            "window_id": self.provenance.get("window_id"),
            "package_sha256": self.package_digest(),
        })
        return ONTO["merge-event/" + hashlib.sha256(
            seed.encode("utf-8")).hexdigest()]

    def candidate_uri(self, event_sha, section, index, record):
        return ONTO["merge-candidate/" + event_sha + "/"
                    + f"{section}-{index}-{record_digest(record)}"]

    # ---------- entity field policy ----------

    def plan_entity(self, index, record):
        decision = self.identities[str(record["id"])]
        resolved = URIRef(decision["uri"]) if decision["uri"] else None
        if decision["status"] == "review":
            return {
                "local_id": record["id"], "index": index,
                "resolved_uri": None, "summary": "review",
                "identity": decision, "fields": {},
            }, set()

        if decision["status"] == "new":
            fields, triples = self._plan_new_entity(record, resolved)
        else:
            fields, triples = self._plan_existing_entity(record, resolved)

        outcomes = [field["outcome"] for field in fields.values()
                    if isinstance(field, dict)]
        flat = [field for field in fields.values() if isinstance(field, list)]
        outcomes += [item["outcome"] for group in flat for item in group]
        if any(outcome == "review" for outcome in outcomes):
            summary = "partial_review"
        elif any(outcome == "accept" for outcome in outcomes):
            summary = "accept"
        else:
            summary = "duplicate"
        return {
            "local_id": record["id"], "index": index,
            "resolved_uri": resolved, "summary": summary,
            "identity": decision, "fields": fields,
        }, triples

    def _plan_new_entity(self, record, uri):
        kind = label(record["kind"] or "Entity")
        kind_uri = CLASS[slug(kind)]
        triples = {
            (kind_uri, RDF.type, OWL.Class),
            (kind_uri, RDFS.subClassOf, ONTO.Entity),
            (kind_uri, RDFS.label, Literal(kind)),
            (uri, RDF.type, ONTO.Entity),
            (uri, RDF.type, OWL.NamedIndividual),
            (uri, RDF.type, SKOS.Concept),
            (uri, RDF.type, kind_uri),
            (uri, ONTO.kind, Literal(kind)),
            (uri, SKOS.prefLabel, Literal(record["name"])),
            (uri, RDFS.label, Literal(record["name"])),
        }
        fields = {"kind": {"outcome": "accept"},
                  "name": {"outcome": "accept"}}
        alias_fields = []
        for alias in record.get("aliases") or []:
            field = self._plan_alias(uri, record, alias)
            alias_fields.append(field)
            if field["outcome"] == "accept":
                triples.add((uri, SKOS.altLabel, Literal(alias)))
        fields["aliases"] = alias_fields
        description = record.get("description") or ""
        if description:
            fields["description"] = {"outcome": "accept"}
            triples.add((uri, RDFS.comment, Literal(description)))
        else:
            fields["description"] = {"outcome": "none"}
        return fields, triples

    def _plan_existing_entity(self, record, uri):
        fields = {"kind": {"outcome": "duplicate"}}
        triples = set()

        own_keys = self.own_label_keys(uri)
        if identity_key(record["name"]) in own_keys:
            fields["name"] = {"outcome": "duplicate"}
        else:
            fields["name"] = self._proposed_label(uri, record, record["name"])
            if fields["name"]["outcome"] == "accept":
                triples.add((uri, SKOS.altLabel, Literal(record["name"])))

        alias_fields = []
        for alias in record.get("aliases") or []:
            if identity_key(alias) in own_keys:
                alias_fields.append({"alias": alias, "outcome": "duplicate"})
            else:
                field = self._proposed_label(uri, record, alias,
                                             alias_name=alias)
                alias_fields.append(field)
                if field["outcome"] == "accept":
                    triples.add((uri, SKOS.altLabel, Literal(alias)))
        fields["aliases"] = alias_fields

        description = record.get("description") or ""
        if not description:
            fields["description"] = {"outcome": "none"}
        else:
            existing = self.graph.value(uri, RDFS.comment)
            if existing is not None and str(existing) == description:
                fields["description"] = {"outcome": "duplicate"}
            elif existing is not None:
                fields["description"] = {
                    "outcome": "review",
                    "reason_codes": ["conflict.existing_description"],
                }
            elif record["confidence"] >= self.min_new_confidence:
                fields["description"] = {"outcome": "accept"}
                triples.add((uri, RDFS.comment, Literal(description)))
            else:
                fields["description"] = {
                    "outcome": "review",
                    "reason_codes": ["confidence.below_auto_accept"],
                }
        return fields, triples

    def _proposed_label(self, uri, record, name_text, alias_name=None):
        """A candidate name/alias the entity does not carry yet."""
        owners = self.same_kind_owners(name_text, record["kind"], uri)
        if owners:
            return {
                **({"alias": alias_name} if alias_name else {}),
                "outcome": "review",
                "reason_codes": ["alias.claimed_by_other_entity"],
                "owners": owners,
            }
        if record["confidence"] >= self.min_new_confidence:
            return {
                **({"alias": alias_name} if alias_name else {}),
                "outcome": "accept",
            }
        return {
            **({"alias": alias_name} if alias_name else {}),
            "outcome": "review",
            "reason_codes": ["confidence.below_auto_accept"],
        }

    def _plan_alias(self, uri, record, alias):
        return self._proposed_label(uri, record, alias, alias_name=alias)

    # ---------- relation and fact policy ----------

    def plan_assertions(self, section, records):
        plans = []
        for index, record in enumerate(records):
            plans.append(self._plan_assertion(section, index, record))
        return plans

    def _plan_assertion(self, section, index, record):
        if section == "relations":
            endpoints = {
                record["subject"]: self.identities[record["subject"]],
                record["object"]: self.identities[record["object"]],
            }
            predicate = RELATION[slug(record["predicate"])]
            prop_type = OWL.ObjectProperty
        else:
            endpoints = {record["subject"]: self.identities[record["subject"]]}
            predicate = FACT[slug(record["predicate"])]
            prop_type = OWL.DatatypeProperty

        base = {
            "section": section, "index": index,
            "confidence": record["confidence"],
        }
        unresolved = sorted(local for local, decision in endpoints.items()
                            if decision["status"] == "review")
        if unresolved:
            return {
                **base,
                "outcome": "review",
                "reason_codes": ["dependency.unresolved_entity"],
                "unresolved": unresolved,
                "triple": None, "conflicts": [],
            }

        subject = URIRef(endpoints[record["subject"]]["uri"])
        if section == "relations":
            object_ = URIRef(endpoints[record["object"]]["uri"])
        else:
            object_ = Literal(record["value"])
        triple = (subject, predicate, object_)

        if triple in self.graph or triple in self.accepted:
            return {**base, "outcome": "duplicate",
                    "reason_codes": ["assertion.exact_duplicate"],
                    "triple": triple, "conflicts": []}

        types = self.property_types(predicate)
        conflicts = set()
        if FUNCTIONAL in types:
            conflicts = {(subject, predicate, other)
                         for other in self.objects_of(subject, predicate)
                         if other != object_}
            reason = "conflict.functional_value"
        elif prop_type is OWL.ObjectProperty \
                and INVERSE_FUNCTIONAL in types:
            conflicts = {(other, predicate, object_)
                         for other in self.subjects_of(predicate, object_)
                         if other != subject}
            reason = "conflict.inverse_functional_value"
        if conflicts:
            return {**base, "outcome": "review", "reason_codes": [reason],
                    "triple": triple,
                    "conflicts": sorted(conflicts, key=_triple_sort)}

        if record["confidence"] < self.min_new_confidence:
            return {**base, "outcome": "review",
                    "reason_codes": ["confidence.below_auto_accept"],
                    "triple": triple, "conflicts": []}

        declarations = {
            (predicate, RDF.type, prop_type),
            (predicate, RDFS.label, Literal(label(record["predicate"]))),
        }
        self.accepted.add(triple)
        self.accepted |= declarations
        self.accepted_property_types[str(predicate)] = prop_type
        return {**base, "outcome": "accept", "reason_codes": [],
                "triple": triple, "conflicts": [],
                "declarations": sorted(declarations, key=_triple_sort)}

    # ---------- audit triples ----------

    def event_audit_triples(self, event_uri):
        return {
            (event_uri, RDF.type, ONTO.ExtractionEvent),
            (event_uri, ONTO.sourcePath,
             Literal(self.provenance["source_path"])),
            (event_uri, ONTO.sourceSha256,
             Literal(self.provenance["source_sha256"])),
            (event_uri, ONTO.modelName, Literal(self.provenance["model"])),
            (event_uri, ONTO.mergePolicyVersion,
             Literal(MERGE_POLICY_VERSION)),
            (event_uri, ONTO.candidatePackageSha256,
             Literal(self.package_digest())),
        }

    def candidate_audit_triples(self, candidate_uri, section, index, record,
                                outcome, reasons, resolved=None, triple=None,
                                fields=None, proposed=None):
        triples = {
            (candidate_uri, RDF.type, ONTO.MergeCandidate),
            (candidate_uri, ONTO.wasExtractedIn, self.event),
            (candidate_uri, ONTO.candidateSection, Literal(section)),
            (candidate_uri, ONTO.candidateIndex, Literal(index)),
            (candidate_uri, ONTO.normalizedCandidate,
             Literal(canonical_json(record), datatype=RDF_JSON)),
            (candidate_uri, ONTO.extractionConfidence,
             _decimal_confidence(record["confidence"])),
            (candidate_uri, ONTO.mergeDecision, Literal(outcome)),
        }
        for code in sorted(set(reasons)):
            triples.add((candidate_uri, ONTO.decisionReason, Literal(code)))
        if resolved is not None:
            triples.add((candidate_uri, ONTO.resolvedEntity, resolved))
        if proposed is not None:
            # The review-only provisional identity, so a later review tool can
            # reference it without re-running the model.
            triples.add((candidate_uri, ONTO.proposedEntity, proposed))
        if triple is not None:
            triples.add((candidate_uri, RDF.subject, triple[0]))
            triples.add((candidate_uri, RDF.predicate, triple[1]))
            triples.add((candidate_uri, RDF.object, triple[2]))
        if fields is not None:
            triples.add((candidate_uri, ONTO.fieldDecisions,
                         Literal(canonical_json(fields), datatype=RDF_JSON)))
        return triples

    # ---------- the whole plan ----------

    def build(self):
        self.event = self.event_uri()
        event_sha = str(self.event).rsplit("/", 1)[1]
        domain = set()
        audit = self.event_audit_triples(self.event)
        entity_plans = []

        for index, record in enumerate(self.candidates["entities"]):
            planned, triples = self.plan_entity(index, record)
            entity_plans.append(planned)
            domain |= triples

            reasons = sorted({
                code
                for field in planned["fields"].values()
                if isinstance(field, dict)
                for code in field.get("reason_codes", [])
            } | {
                code
                for group in planned["fields"].values()
                if isinstance(group, list)
                for item in group
                for code in item.get("reason_codes", [])
            } | set(planned["identity"]["reason_codes"]))
            audit |= self.candidate_audit_triples(
                self.candidate_uri(event_sha, "entities", index, record),
                "entities", index, record, planned["summary"], reasons,
                resolved=URIRef(planned["identity"]["uri"])
                if planned["identity"]["status"] != "review" else None,
                fields=planned["fields"],
                proposed=URIRef(planned["identity"]["uri"])
                if planned["identity"]["status"] == "review"
                and planned["identity"]["uri"] is not None else None,
            )

        assertion_plans = {}
        for section in ("relations", "facts"):
            plans = self.plan_assertions(section, self.candidates[section])
            assertion_plans[section] = plans
            for plan in plans:
                if plan["outcome"] == "accept":
                    domain.add(plan["triple"])
                    domain |= set(plan["declarations"])
                if plan["triple"] is not None:
                    audit |= self.candidate_audit_triples(
                        self.candidate_uri(event_sha, section, plan["index"],
                                           self.candidates[section][plan["index"]]),
                        section, plan["index"],
                        self.candidates[section][plan["index"]],
                        plan["outcome"], plan["reason_codes"],
                        triple=plan["triple"],
                    )
                else:
                    audit |= self.candidate_audit_triples(
                        self.candidate_uri(event_sha, section, plan["index"],
                                           self.candidates[section][plan["index"]]),
                        section, plan["index"],
                        self.candidates[section][plan["index"]],
                        plan["outcome"], plan["reason_codes"],
                    )

        identity_counts = {"new": 0, "resolved": 0, "review": 0}
        for decision in self.identities.values():
            identity_counts[
                "resolved" if decision["status"] == "existing" else decision["status"]
            ] += 1
        assertion_counts = {"accepted": 0, "duplicate": 0, "review": 0}
        for plans in assertion_plans.values():
            for plan in plans:
                assertion_counts[
                    "accepted" if plan["outcome"] == "accept"
                    else plan["outcome"]] += 1
        entity_counts = {"accept": 0, "duplicate": 0, "review": 0,
                         "partial_review": 0}
        for plan in entity_plans:
            entity_counts[plan["summary"]] += 1

        diagnostics = []
        for local_id, decision in sorted(self.identities.items()):
            if decision["status"] == "review":
                diagnostics.append(
                    f"identity {local_id}: review "
                    f"{','.join(decision['reason_codes'])}")
        for section, plans in sorted(assertion_plans.items()):
            for plan in plans:
                if plan["outcome"] == "review":
                    diagnostics.append(
                        f"{section}[{plan['index']}]: review "
                        f"{','.join(plan['reason_codes'])}")
        diagnostics.sort()

        return {
            "policy_version": MERGE_POLICY_VERSION,
            "provenance": self.provenance,
            "event_uri": self.event,
            "package_sha256": self.package_digest(),
            "identities": self.identities,
            "entities": entity_plans,
            "relations": assertion_plans["relations"],
            "facts": assertion_plans["facts"],
            "domain_triples": sorted(domain, key=_triple_sort),
            "audit_triples": sorted(audit, key=_triple_sort),
            "counts": {
                "identities": identity_counts,
                "assertions": assertion_counts,
                "entity_summaries": entity_counts,
                "domain_triples": len(domain),
                "audit_triples": len(audit),
            },
            "diagnostics": diagnostics,
        }


def resolve_entities(candidates, graph,
                     min_new_confidence=AUTO_ACCEPT_MIN_CONFIDENCE,
                     allocate_uri=None, provisional_uri=None):
    """One identity decision per candidate entity, in normalized order.

    Read only. Earlier accepted new entities become visible to later candidates
    through a virtual catalog; every allocated URI is reserved so two new
    entities cannot claim one URI before materialization. The `allocate_uri`
    and `provisional_uri` callables decide which URIs new or proposed entities
    receive; the defaults allocate canonical entity/ slugs.
    """
    catalog = entity_catalog(graph)
    reserved = {str(subject) for subject in graph.subjects()}
    planned = []
    decisions = {}

    if allocate_uri is None:
        def allocate(name):
            """The next free slug URI, reserving it for this plan."""
            stem, number = slug(name), 1
            while True:
                suffix = "" if number == 1 else f"-{number}"
                uri = ENTITY[stem + suffix]
                if str(uri) not in reserved:
                    reserved.add(str(uri))
                    return uri
                number += 1
    else:
        def allocate(name):
            uri = allocate_uri(name)
            reserved.add(str(uri))
            return uri

    for entity in candidates.get("entities", []):
        local_id = entity.get("id")
        if not local_id or not entity.get("name"):
            continue
        decision = identity_decision(
            entity, catalog, planned_catalog=planned,
            min_new_confidence=min_new_confidence,
            allocate_uri=allocate,
            provisional_uri=(provisional_uri if provisional_uri is not None
                             else proposed_entity_uri),
        )
        decisions[str(local_id)] = decision
        if decision["status"] == "new":
            planned.append({
                "id": str(decision["uri"]),
                "names": [entity["name"], *(entity.get("aliases") or [])],
                "kind": entity["kind"],
                "description": entity.get("description", ""),
            })
    return decisions


def plan_graph_merge(graph, candidates, provenance,
                     min_new_confidence=AUTO_ACCEPT_MIN_CONFIDENCE,
                     allocate_uri=None, provisional_uri=None):
    """Build the complete read-only merge plan for one valid candidate package."""
    return _Planner(graph, candidates, provenance,
                    min_new_confidence=min_new_confidence,
                    allocate_uri=allocate_uri,
                    provisional_uri=provisional_uri).build()
