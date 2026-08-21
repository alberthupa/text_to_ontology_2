"""Validate and normalize one candidate package before it may touch the graph.

The LLM response is an untrusted proposal, not input that may immediately mutate
the canonical RDF graph. This module understands the supported response
structure, normalizes it deterministically and conservatively, and returns
either a normalized, deduplicated candidate package or a deterministic failure
with path-addressed diagnostics.

Normalization makes representation stable without guessing semantics: dates are
not parsed, numbers are not coerced, and fields are never truncated. The module
reads the graph to check explicit identities and generated-URI compatibility,
but never writes to it and never performs identity search.
"""

import math
import re
import unicodedata

from rdflib.namespace import OWL, RDF, RDFS, SKOS

from entity_lookup import entity_catalog, identity_key
from graph_management import CLASS, FACT, ONTO, RELATION
from graph_merge import label, slug


LOCAL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

TOP_LEVEL_FIELDS = ("entities", "relations", "facts")
ENTITY_FIELDS = ("id", "name", "kind", "description", "aliases", "existing_id",
                 "confidence")
RELATION_FIELDS = ("subject", "predicate", "object", "confidence")
FACT_FIELDS = ("subject", "predicate", "value", "confidence")
_SINGULAR = {"entities": "entity", "relations": "relation", "facts": "fact"}

CLASS_TYPES = {OWL.Class, RDFS.Class}
PROPERTY_TYPES = {OWL.ObjectProperty, OWL.DatatypeProperty}
ENTITY_ROLE_TYPES = {OWL.NamedIndividual, SKOS.Concept, ONTO.Entity}

SECTION_RANK = {"entities": 0, "relations": 1, "facts": 2}
FIELD_RANK = {
    "id": 0, "name": 1, "kind": 2, "description": 3, "aliases": 4,
    "existing_id": 5, "confidence": 6,
    "subject": 0, "predicate": 1, "object": 2, "value": 2,
}


def _is_control(character):
    """A disallowed control character: C0 controls or DEL/C1, no allowed whitespace."""
    code = ord(character)
    return code < 0x20 or 0x7F <= code < 0xA0


def normalize_text(value):
    """NFKC, line endings folded to LF, controls removed, edges trimmed.

    Internal whitespace (spaces, tabs, newlines) is preserved so descriptions
    and fact strings keep their meaning.
    """
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character if character in "\n\t" or not _is_control(character) else " "
        for character in text)
    return text.strip()


def normalize_oneline(value):
    """NFKC and control removal, then all whitespace collapsed to one space."""
    return " ".join(normalize_text(value).split())


def normalize_id(value):
    """A local identifier: NFKC, trimmed. Grammar is checked separately."""
    return unicodedata.normalize("NFKC", str(value)).strip()


def normalize_existing_id(value):
    """An existing id must match the rendered id exactly; only trim it."""
    return str(value).strip()


def _norm(state, func, raw):
    """Normalize one value and remember whether normalization changed it."""
    normalized = func(raw)
    if normalized != raw:
        state["normalized_fields"] += 1
    return normalized


def looks_like_uri(value):
    """Whether a predicate string names a URI rather than a property name."""
    return "://" in value or SCHEME.match(value) is not None


def value_type(value):
    """The JSON scalar type of a fact value, or None when unsupported."""
    if value is None:
        return None
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float" if math.isfinite(value) else None
    if type(value) is str:
        return "str"
    return None


def normalize_confidence(value):
    """One stable float in [0, 1]; raises ValueError for anything else.

    Integers and floats both become float, so 1 and 0.80 normalize to the same
    representation as 1.0 and 0.8. Booleans and non-finite numbers are rejected.
    """
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("confidence must be finite")
    if not 0.0 <= number <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0 inclusive")
    return number


def _confidence(record, state, base, index, section):
    """Read the required confidence field; None means the record has an error."""
    code = _SINGULAR[section]
    if "confidence" not in record:
        _note(state, f"{code}.missing_confidence", "error",
              f"{base}.confidence", [],
              f"{_SINGULAR[section]} has no confidence",
              section, index, "confidence")
        return None
    try:
        return _norm(state, normalize_confidence, record["confidence"])
    except ValueError as failure:
        _note(state, f"{code}.invalid_confidence", "error",
              f"{base}.confidence", [], str(failure),
              section, index, "confidence")
        return None


def _note(state, code, severity, path, related_paths, message,
          section="", index=0, field=""):
    """Record one issue. Ordering is decided later from the issue's path."""
    state["issues"].append({
        "code": code, "severity": severity, "path": path,
        "related_paths": related_paths, "message": message,
    })


def _normalize_entities(raw, state, allowed, catalog_by_id):
    """Pass 2: normalize every entity record and build the local-ID index."""
    entities = []
    id_to_path = {}
    id_to_index = {}
    id_signature = {}
    id_to_record = {}
    existing_id_owner = {}
    valid_ids = set()

    for index, record in enumerate(raw):
        base = f"entities[{index}]"
        if not isinstance(record, dict):
            _note(state, "entity.not_mapping", "error", base, [],
                  "entity record is not a JSON object", "entities", index)
            continue

        problems = []

        def error(code, field, message):
            _note(state, code, "error", f"{base}.{field}", [], message,
                  "entities", index, field)
            problems.append(code)

        for field in record:
            if field not in ENTITY_FIELDS:
                _note(state, "entity.unknown_field", "error",
                      f"{base}.{field}", [],
                      f"unknown entity field '{field}'",
                      "entities", index, field)

        if "id" not in record:
            error("entity.missing_id", "id", "entity record has no id")
            local_id = None
        elif not isinstance(record["id"], str):
            error("entity.invalid_id", "id", "entity id must be a string")
            local_id = None
        else:
            local_id = _norm(state, normalize_id, record["id"])
            if not local_id or not LOCAL_ID.match(local_id):
                error("entity.invalid_id", "id",
                      f"entity id {local_id!r} is not a valid local identifier")
                local_id = None

        raw_name = record.get("name")
        if "name" not in record:
            error("entity.missing_name", "name", "entity record has no name")
            name = ""
        elif not isinstance(raw_name, str):
            error("entity.invalid_name", "name", "entity name must be a string")
            name = ""
        else:
            name = _norm(state, normalize_oneline, raw_name)
            if not name:
                error("entity.empty_name", "name", "entity name is empty")

        raw_kind = record.get("kind")
        if raw_kind is None:
            kind = "Entity"
            original_kind = ""
            _note(state, "entity.kind_defaulted", "warning", f"{base}.kind", [],
                  "missing kind defaulted to 'Entity'",
                  "entities", index, "kind")
        elif not isinstance(raw_kind, str):
            error("entity.invalid_kind", "kind", "entity kind must be a string")
            kind = "Entity"
            original_kind = ""
        else:
            kind = _norm(state, normalize_oneline, raw_kind)
            original_kind = kind
            if not kind:
                kind = "Entity"
                _note(state, "entity.kind_defaulted", "warning",
                      f"{base}.kind", [],
                      "empty kind defaulted to 'Entity'",
                      "entities", index, "kind")

        raw_description = record.get("description")
        if raw_description is None:
            description = ""
        elif isinstance(raw_description, str):
            description = _norm(state, normalize_text, raw_description)
        else:
            error("entity.invalid_description", "description",
                  "entity description must be a string or null")
            description = ""

        aliases = []
        raw_aliases = record.get("aliases")
        if raw_aliases is not None and not isinstance(raw_aliases, list):
            error("entity.invalid_aliases", "aliases",
                  "entity aliases must be a list")
        elif raw_aliases is not None:
            seen_aliases = set()
            for alias_index, raw_alias in enumerate(raw_aliases):
                alias_path = f"{base}.aliases[{alias_index}]"
                if not isinstance(raw_alias, str):
                    _note(state, "entity.invalid_aliases", "error", alias_path,
                          [], "alias must be a string",
                          "entities", index, "aliases")
                    continue
                alias = _norm(state, normalize_oneline, raw_alias)
                if not alias:
                    _note(state, "entity.alias_duplicate", "warning",
                          alias_path, [], "empty alias removed",
                          "entities", index, "aliases")
                    state["duplicates_removed"]["aliases"] += 1
                elif alias == name:
                    _note(state, "entity.alias_duplicate", "warning",
                          alias_path, [f"{base}.name"],
                          "alias equals the preferred name and was removed",
                          "entities", index, "aliases")
                    state["duplicates_removed"]["aliases"] += 1
                elif alias in seen_aliases:
                    _note(state, "entity.alias_duplicate", "warning",
                          alias_path, [],
                          f"duplicate alias {alias!r} removed",
                          "entities", index, "aliases")
                    state["duplicates_removed"]["aliases"] += 1
                else:
                    seen_aliases.add(alias)
                    aliases.append(alias)

        raw_existing = record.get("existing_id")
        if raw_existing is None:
            existing_id = None
        elif isinstance(raw_existing, str):
            existing_id = _norm(state, normalize_existing_id, raw_existing) or None
        else:
            error("entity.invalid_existing_id", "existing_id",
                  "existing_id must be a string or null")
            existing_id = None

        if existing_id is not None:
            if existing_id not in allowed:
                error("entity.existing_id_not_allowed", "existing_id",
                      f"existing_id {existing_id!r} was not shown in the final prompt")
            elif existing_id not in catalog_by_id:
                error("entity.existing_id_not_allowed", "existing_id",
                      f"existing_id {existing_id!r} is no longer in the graph")
            else:
                current_kind = catalog_by_id[existing_id]["kind"]
                if original_kind and current_kind and \
                        identity_key(original_kind) != identity_key(current_kind):
                    _note(state, "entity.existing_id_kind_mismatch", "error",
                          f"{base}.existing_id", [f"{base}.kind"],
                          f"kind {original_kind!r} does not match the existing "
                          f"kind {current_kind!r}",
                          "entities", index, "existing_id")
                    problems.append("entity.existing_id_kind_mismatch")
                owner = existing_id_owner.get(existing_id)
                if owner is not None:
                    _note(state, "entity.duplicate_existing_id", "error",
                          f"{base}.existing_id", [owner],
                          f"existing_id {existing_id!r} is also claimed by "
                          f"another entity",
                          "entities", index, "existing_id")
                    problems.append("entity.duplicate_existing_id")
                else:
                    existing_id_owner[existing_id] = f"{base}.id"

        confidence = _confidence(record, state, base, index, "entities")

        normalized = {
            "id": local_id,
            "name": name,
            "kind": kind,
            "description": description,
            "aliases": aliases,
            "existing_id": existing_id,
            "confidence": confidence,
            "_path": base,
        }

        if local_id is not None:
            signature = (name, kind, description, tuple(aliases), existing_id)
            prior = id_to_index.get(local_id)
            if prior is not None:
                if id_signature[local_id] == signature:
                    _note(state, "entity.duplicate_record", "warning", base,
                          [f"entities[{prior}]"],
                          f"duplicate entity record for id {local_id!r} removed",
                          "entities", index)
                    state["duplicates_removed"]["entities"] += 1
                    if confidence is not None and \
                            confidence < id_to_record[local_id]["confidence"]:
                        # Differing confidence does not make a record distinct;
                        # keep the lower value conservatively.
                        kept_path = id_to_record[local_id]["_path"]
                        _note(state, "entity.duplicate_confidence", "warning",
                              base + ".confidence", [kept_path + ".confidence"],
                              f"duplicate entity record for id {local_id!r} "
                              f"lowered the kept confidence to {confidence}",
                              "entities", index, "confidence")
                        id_to_record[local_id]["confidence"] = confidence
                    continue
                _note(state, "entity.duplicate_id", "error", f"{base}.id",
                      [f"entities[{prior}].id"],
                      f"duplicate local id {local_id!r} names different entities",
                      "entities", index, "id")
                problems.append("entity.duplicate_id")
            else:
                id_to_index[local_id] = index
                id_signature[local_id] = signature
                id_to_record[local_id] = normalized

        if local_id is not None:
            id_to_path.setdefault(local_id, base)
        entities.append(normalized)
        if not problems and local_id is not None and name:
            # Only a record that is free of errors and carries a usable id and
            # name is a valid reference target for relations and facts.
            valid_ids.add(local_id)

    return entities, id_to_path, valid_ids


def _normalize_records(raw, section, state):
    """Pass 3: normalize relation and fact records in original order."""
    normalizer = _normalize_relation if section == "relations" else _normalize_fact
    records = []
    for index, record in enumerate(raw):
        normalized = normalizer(record, state, f"{section}[{index}]", index)
        if normalized is not None:
            records.append(normalized)
    return records


def _ref(record, field, state, base, index, section, problems):
    code = _SINGULAR[section]
    if field not in record:
        _note(state, f"{code}.missing_{field}", "error",
              f"{base}.{field}", [], f"{section[:-1]} has no {field}",
              section, index, field)
        problems.append(True)
        return None
    value = record[field]
    if not isinstance(value, str):
        _note(state, f"{code}.invalid_{field}", "error",
              f"{base}.{field}", [], f"{section[:-1]} {field} must be a string",
              section, index, field)
        problems.append(True)
        return None
    value = _norm(state, normalize_oneline, value)
    if not value:
        _note(state, f"{code}.invalid_{field}", "error",
              f"{base}.{field}", [], f"{section[:-1]} {field} is empty",
              section, index, field)
        problems.append(True)
        return None
    return value


def _normalize_relation(record, state, base, index):
    if not isinstance(record, dict):
        _note(state, "relation.not_mapping", "error", base, [],
              "relation record is not a JSON object", "relations", index)
        return None
    problems = []
    for field in record:
        if field not in RELATION_FIELDS:
            _note(state, "relation.unknown_field", "error", f"{base}.{field}",
                  [], f"unknown relation field '{field}'", "relations", index, field)

    subject = _ref(record, "subject", state, base, index, "relations", problems)
    object_ = _ref(record, "object", state, base, index, "relations", problems)

    name = None
    if "predicate" not in record:
        _note(state, "relation.missing_predicate", "error",
              f"{base}.predicate", [], "relation has no predicate",
              "relations", index, "predicate")
        problems.append(True)
    elif not isinstance(record["predicate"], str):
        _note(state, "relation.invalid_predicate", "error",
              f"{base}.predicate", [], "relation predicate must be a string",
              "relations", index, "predicate")
        problems.append(True)
    else:
        name = _norm(state, normalize_oneline, record["predicate"])
        if not name:
            _note(state, "relation.empty_predicate", "error",
                  f"{base}.predicate", [], "relation predicate is empty",
                  "relations", index, "predicate")
            problems.append(True)
        elif looks_like_uri(name):
            _note(state, "relation.uri_predicate", "error",
                  f"{base}.predicate", [],
                  f"relation predicate {name!r} names a URI, not a property",
                  "relations", index, "predicate")
            problems.append(True)
        elif slug(name) == "unnamed":
            _note(state, "relation.unnamed_predicate", "error",
                  f"{base}.predicate", [],
                  f"relation predicate {name!r} has no usable local name",
                  "relations", index, "predicate")
            problems.append(True)

    if problems:
        return None
    confidence = _confidence(record, state, base, index, "relations")
    if confidence is None:
        return None
    return {"subject": subject, "predicate": name, "object": object_,
            "confidence": confidence,
            "_slug": slug(name), "_label": label(name), "_base": base}


def _normalize_fact(record, state, base, index):
    if not isinstance(record, dict):
        _note(state, "fact.not_mapping", "error", base, [],
              "fact record is not a JSON object", "facts", index)
        return None
    problems = []
    for field in record:
        if field not in FACT_FIELDS:
            _note(state, "fact.unknown_field", "error", f"{base}.{field}", [],
                  f"unknown fact field '{field}'", "facts", index, field)

    subject = _ref(record, "subject", state, base, index, "facts", problems)

    name = None
    if "predicate" not in record:
        _note(state, "fact.missing_predicate", "error", f"{base}.predicate", [],
              "fact has no predicate", "facts", index, "predicate")
        problems.append(True)
    elif not isinstance(record["predicate"], str):
        _note(state, "fact.invalid_predicate", "error", f"{base}.predicate", [],
              "fact predicate must be a string", "facts", index, "predicate")
        problems.append(True)
    else:
        name = _norm(state, normalize_oneline, record["predicate"])
        if not name:
            _note(state, "fact.empty_predicate", "error", f"{base}.predicate",
                  [], "fact predicate is empty", "facts", index, "predicate")
            problems.append(True)
        elif looks_like_uri(name):
            _note(state, "fact.uri_predicate", "error", f"{base}.predicate", [],
                  f"fact predicate {name!r} names a URI, not a property",
                  "facts", index, "predicate")
            problems.append(True)
        elif slug(name) == "unnamed":
            _note(state, "fact.unnamed_predicate", "error", f"{base}.predicate",
                  [], f"fact predicate {name!r} has no usable local name",
                  "facts", index, "predicate")
            problems.append(True)

    if "value" not in record:
        _note(state, "fact.missing_value", "error", f"{base}.value", [],
              "fact has no value", "facts", index, "value")
        problems.append(True)
        value = None
    else:
        value = record["value"]
        kind = value_type(value)
        if kind is None:
            _note(state, "fact.invalid_value", "error", f"{base}.value", [],
                  "fact value must be a string, Boolean, integer, or finite number",
                  "facts", index, "value")
            problems.append(True)
        elif kind == "str":
            value = _norm(state, normalize_text, value)

    if problems:
        return None
    confidence = _confidence(record, state, base, index, "facts")
    if confidence is None:
        return None
    return {"subject": subject, "predicate": name, "value": value,
            "confidence": confidence,
            "_value_type": value_type(record["value"]),
            "_slug": slug(name), "_label": label(name), "_base": base}


def _check_references(record, section, state, id_to_path, valid_ids):
    """Pass 4: every reference must name a valid candidate entity."""
    code = _SINGULAR[section]
    fields = ("subject", "object") if section == "relations" else ("subject",)
    for field in fields:
        ref = record[field]
        path = f"{record['_base']}.{field}"
        if ref not in id_to_path:
            _note(state, f"{code}.unknown_{field}", "error", path, [],
                  f"{code} {field} {ref!r} does not name a valid candidate entity",
                  section, 0, field)
        elif ref not in valid_ids:
            _note(state, f"{code}.unknown_{field}", "error", path,
                  [id_to_path[ref]],
                  f"{code} {field} {ref!r} names an invalid candidate entity",
                  section, 0, field)


def _label_collisions(records, section, state):
    """Pass 6 part 1: distinct labels mapping to one generated URI collide."""
    code = _SINGULAR[section]
    by_slug = {}
    for record in records:
        by_slug.setdefault(record["_slug"], {})
        by_slug[record["_slug"]].setdefault(record["_label"], record)
    for _, labels_found in by_slug.items():
        if len(labels_found) > 1:
            ordered = sorted(labels_found.values(),
                             key=lambda item: item["_base"])
            _note(state, f"{code}.label_collision", "error",
                  ordered[0]["_base"] + ".predicate",
                  [item["_base"] + ".predicate" for item in ordered[1:]],
                  f"distinct {code} predicates "
                  f"{sorted(labels_found)!r} collide on one generated URI",
                  section)


def _dedupe(records, section, state):
    """Pass 5: keep the first record for each exact normalized duplicate key."""
    code = _SINGULAR[section]
    seen = {}
    kept = []
    for record in records:
        if section == "relations":
            key = (record["subject"], record["_slug"], record["object"])
        else:
            key = (record["subject"], record["_slug"],
                   record["_value_type"], record["value"])
        if key in seen:
            _note(state, f"{code}.duplicate", "warning",
                  record["_base"] + ".predicate", [seen[key]["_base"] + ".predicate"],
                  f"duplicate {code} removed", section)
            state["duplicates_removed"][section] += 1
            first = seen[key]
            if record["confidence"] < first["confidence"]:
                # Differing confidence does not make an assertion distinct;
                # keep the lower value conservatively.
                _note(state, f"{code}.duplicate_confidence", "warning",
                      record["_base"] + ".confidence",
                      [first["_base"] + ".confidence"],
                      f"duplicate {code} lowered the kept confidence to "
                      f"{record['confidence']}", section)
                first["confidence"] = record["confidence"]
            continue
        seen[key] = record
        kept.append(record)
    return kept


def _check_graph_compatibility(entities, relations, facts, graph, state):
    """Pass 6 part 2: reject provable role/type conflicts, read only."""

    def types_at(uri):
        return set(graph.objects(uri, RDF.type))

    seen_kinds = set()
    for entity in entities:
        kind = entity["kind"]
        uri = CLASS[slug(kind)]
        if uri in seen_kinds:
            continue
        seen_kinds.add(uri)
        types = types_at(uri)
        if types & PROPERTY_TYPES:
            _note(state, "kind.role_collision", "error", entity["_path"] + ".kind",
                  [], f"kind {kind!r} URI is already used as a property",
                  "entities")
        if types & ENTITY_ROLE_TYPES:
            _note(state, "kind.role_collision", "error", entity["_path"] + ".kind",
                  [], f"kind {kind!r} URI is already used as an entity",
                  "entities")
        if any(True for _ in graph.triples((None, uri, None))):
            _note(state, "kind.role_collision", "error", entity["_path"] + ".kind",
                  [], f"kind {kind!r} URI is already used as a predicate",
                  "entities")

    for section, records, namespace in (("relations", relations, RELATION),
                                        ("facts", facts, FACT)):
        code = _SINGULAR[section]
        opposite = OWL.DatatypeProperty if section == "relations" \
            else OWL.ObjectProperty
        opposite_word = "datatype" if section == "relations" else "object"
        for record in records:
            uri = namespace[record["_slug"]]
            types = types_at(uri)
            if opposite in types:
                _note(state, f"{code}.type_collision", "error",
                      record["_base"] + ".predicate", [],
                      f"{code} predicate {record['predicate']!r} is already "
                      f"typed as a {opposite_word} property", section)
            if types & (CLASS_TYPES | ENTITY_ROLE_TYPES):
                _note(state, f"{code}.role_collision", "error",
                      record["_base"] + ".predicate", [],
                      f"{code} predicate {record['predicate']!r} URI is already "
                      f"used as a class or entity", section)


def validate_candidates(data, graph, allowed_existing_ids=()):
    """Validate and normalize a candidate package; never write to the graph."""
    state = {
        "issues": [],
        "normalized_fields": 0,
        "duplicates_removed": {"entities": 0, "relations": 0, "facts": 0,
                               "aliases": 0},
    }

    allowed = {str(identity) for identity in allowed_existing_ids}
    catalog_by_id = {item["id"]: item for item in entity_catalog(graph)}

    counts = {
        "input": {"entities": 0, "relations": 0, "facts": 0},
        "normalized": {"entities": 0, "relations": 0, "facts": 0},
        "duplicates_removed": state["duplicates_removed"],
        "normalized_fields": 0,
        "errors": 0,
        "warnings": 0,
    }

    # Pass 1: the container.
    if not isinstance(data, dict):
        _note(state, "structure.not_mapping", "error", "$", [],
              "candidate response is not a JSON object", "entities")
        return _finalize(False, None, state, counts)

    for section in TOP_LEVEL_FIELDS:
        if section not in data:
            _note(state, "structure.missing_section", "error", section, [],
                  f"missing required section '{section}'", section)
    for key in data:
        if key not in TOP_LEVEL_FIELDS:
            _note(state, "structure.unknown_section", "error", key, [],
                  f"unknown top-level field '{key}'", "entities")
    for section in TOP_LEVEL_FIELDS:
        if section in data and not isinstance(data[section], list):
            _note(state, "structure.section_not_list", "error", section, [],
                  f"section '{section}' must be a list", section)

    if state["issues"]:
        for section in TOP_LEVEL_FIELDS:
            value = data.get(section)
            if isinstance(value, list):
                counts["input"][section] = len(value)
        return _finalize(False, None, state, counts)

    raw_entities = data["entities"]
    raw_relations = data["relations"]
    raw_facts = data["facts"]
    counts["input"] = {
        "entities": len(raw_entities),
        "relations": len(raw_relations),
        "facts": len(raw_facts),
    }

    # Pass 2: entities.
    entities, id_to_path, valid_ids = _normalize_entities(
        raw_entities, state, allowed, catalog_by_id)

    # Pass 3: relations and facts.
    relations = _normalize_records(raw_relations, "relations", state)
    facts = _normalize_records(raw_facts, "facts", state)

    # Pass 4: references.
    for record in relations:
        _check_references(record, "relations", state, id_to_path, valid_ids)
    for record in facts:
        _check_references(record, "facts", state, id_to_path, valid_ids)

    # Pass 6 part 1: label collisions within a section.
    _label_collisions(relations, "relations", state)
    _label_collisions(facts, "facts", state)

    # Pass 5: deduplicate exact assertions.
    relations = _dedupe(relations, "relations", state)
    facts = _dedupe(facts, "facts", state)

    # Pass 6 part 2: generated-URI compatibility against the graph.
    _check_graph_compatibility(entities, relations, facts, graph, state)

    # Graph-exact assertions are deliberately NOT removed here: merge policy
    # plans their corroboration and provenance, so they stay in normalized
    # output for planning.

    has_errors = any(issue["severity"] == "error" for issue in state["issues"])
    candidates = {
        "entities": [{key: value for key, value in entity.items()
                      if key in ENTITY_FIELDS} for entity in entities],
        "relations": [{key: value for key, value in record.items()
                       if key in RELATION_FIELDS} for record in relations],
        "facts": [{key: value for key, value in record.items()
                   if key in FACT_FIELDS} for record in facts],
    }
    counts["normalized"] = {
        "entities": len(candidates["entities"]),
        "relations": len(candidates["relations"]),
        "facts": len(candidates["facts"]),
    }
    return _finalize(not has_errors, candidates, state, counts)


def _finalize(valid, candidates, state, counts):
    issues = sorted(state["issues"], key=_issue_sort_key)
    counts["errors"] = sum(1 for issue in issues if issue["severity"] == "error")
    counts["warnings"] = sum(1 for issue in issues if issue["severity"] == "warning")
    counts["normalized_fields"] = state["normalized_fields"]
    counts["duplicates_removed"] = dict(state["duplicates_removed"])
    return {
        "valid": valid,
        "candidates": candidates if valid else None,
        "issues": issues,
        "counts": counts,
    }


_PATH = re.compile(r"^(entities|relations|facts)(?:\[(\d+)\])?(?:\.(\w+))?")


def _issue_sort_key(issue):
    path = issue["path"]
    if path == "$":
        return (-1, -1, -1, issue["code"], issue["message"])
    match = _PATH.match(path)
    if not match:
        return (99, 0, 99, issue["code"], issue["message"])
    section = match.group(1)
    index = int(match.group(2)) if match.group(2) is not None else 0
    field = match.group(3) or ""
    return (SECTION_RANK.get(section, 99), index,
            FIELD_RANK.get(field, 99), issue["code"], issue["message"])


def format_validation_failure(result):
    """A concise, deterministic error message for the CLI."""
    errors = [issue for issue in result["issues"] if issue["severity"] == "error"]
    lines = [f"{len(errors)} validation error(s):"]
    for issue in errors:
        lines.append(f"- {issue['path']} [{issue['code']}]: {issue['message']}")
    return "\n".join(lines)