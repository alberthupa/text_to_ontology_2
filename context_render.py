"""Translate a selected context package into lines an LLM can read.

This is semantic translation, not RDF serialization. Each supported item kind has
its own wording, and the four sections stay visibly apart because they carry
different authority:

    declared    what the ontology states;
    observed    what the current data happens to do, marked as evidence;
    resources   which resources exist, and which identifiers may be reused;
    examples    what a current assertion looks like.

Three rules the wording must never break. A datatype property points at a
literal value, never at an apparent entity. An unknown observed range stays
unknown. A restriction is translated only in the forms the skeleton supports; any
other form is shown as compact RDF rather than given invented meaning.

Text that came out of the graph is flattened and defused before it reaches the
prompt, so a label or description cannot forge a heading, a fence, or a source
delimiter. Long fields are cut at their own boundary with a visible marker; the
assembled context is never sliced.
"""

from rdflib import BNode, Literal
from rdflib.namespace import OWL, RDF, RDFS

from prompt_budget import context_allowance, estimate_tokens, fit_context_items
from task_context import TEXT_PREDICATES, datatype_term


SECTIONS = ("declared", "observed", "resources", "examples")

HEADINGS = {
    "declared": "RELEVANT DECLARED ONTOLOGY",
    "observed": "OBSERVED USAGE — EVIDENCE, NOT AN ONTOLOGY RULE",
    "resources": "RELEVANT EXISTING RESOURCES",
    "examples": "REPRESENTATIVE CURRENT ASSERTIONS",
}

SECTION_OF_KIND = {
    "class": "declared", "property": "declared", "restriction": "declared",
    "pattern": "observed", "resource": "resources", "example": "examples",
}

PROPERTY_TAGS = {"object": "object property", "datatype": "datatype property"}

# The restriction forms graph_skeleton.py supports, and nothing else.
CONSTRAINT_WORDS = {
    OWL.someValuesFrom: 'at least one "{name}" value is a {value}',
    OWL.allValuesFrom: 'every "{name}" value is a {value}',
    OWL.hasValue: '"{name}" always includes {value}',
    OWL.cardinality: 'exactly {value} "{name}" values',
    OWL.minCardinality: 'at least {value} "{name}" values',
    OWL.maxCardinality: 'at most {value} "{name}" values',
}
COUNTING_CONSTRAINTS = {OWL.cardinality, OWL.minCardinality, OWL.maxCardinality}

# Runs of these forge headings, fences, and source delimiters.
DELIMITERS = ("-", "=", "`", "#", "_", "*", "~")

MAX_FIELD_CHARACTERS = 240
TRUNCATION_MARKER = " ...[truncated]"
GENERIC_NOTE = "existing resource; not usable as existing_id"
NO_CLASS = "(no declared class)"


def clean(value):
    """One safe prompt fragment: no newlines, no controls, no forged delimiters."""
    flattened = "".join(
        " " if character in "\n\r\t" or ord(character) < 32 or ord(character) == 127
        else character
        for character in str(value)
    )
    for character in DELIMITERS:
        run = character * 3
        while run in flattened:
            flattened = flattened.replace(run, character)
    return " ".join(flattened.split())


def field(value):
    """A description, cut at a word boundary when too long, and marked as cut."""
    text = clean(value)
    if len(text) <= MAX_FIELD_CHARACTERS:
        return text
    cut = text[:MAX_FIELD_CHARACTERS].rsplit(" ", 1)[0]
    return (cut or text[:MAX_FIELD_CHARACTERS]) + TRUNCATION_MARKER


def qualified(manager, term):
    """A term as prompt text: owl: shorthand, then a prefix, then the full URI."""
    if str(term).startswith(str(OWL)):
        return "owl:" + str(term)[len(str(OWL)):]
    if manager is not None:
        return manager.normalizeUri(term)
    return str(term)


def display(names, manager, term):
    """A label if the package carries one, then a prefixed URI, then the URI."""
    if isinstance(term, Literal):
        return f'"{clean(term)}"'
    found = names.get(str(term))
    if found:
        return clean(found[0])
    if manager is not None:
        return manager.normalizeUri(term)
    return str(term)


def naming(context_package):
    """The package's labels, with each selected resource's preferred name first."""
    found = {key: list(value) for key, value in context_package["labels"].items()}
    for entry in context_package["resources"]:
        card = entry["value"]
        preferred = card.get("preferred") or (
            card["names"][0] if card["names"] else None)
        if preferred:
            found[str(card["uri"])] = [preferred] + [
                name for name in card["names"] if name != preferred]
    return found


def description_line(triples):
    """The first description a bundle states, as its own labeled line."""
    found = sorted({str(target) for _, predicate, target in triples
                    if predicate in TEXT_PREDICATES})
    return f"\n  description: {field(found[0])}" if found else ""


def render_class(entry, names, manager):
    """A class, and only the parents it actually declares."""
    value = entry["value"]
    parents = sorted({display(names, manager, target)
                      for _, predicate, target in value["triples"]
                      if predicate == RDFS.subClassOf and not isinstance(target, BNode)})
    line = f"- [class] {display(names, manager, value['uri'])}"
    if parents:
        line += " is a kind of " + ", ".join(parents)
    return line + "." + description_line(value["triples"]), []


def render_property(entry, names, manager):
    """A property, visibly an object or a datatype property, with what it states."""
    value = entry["value"]
    tag = PROPERTY_TAGS.get(value.get("kind"), "property")
    clauses = []
    for predicate, word in ((RDFS.domain, "domain"), (RDFS.range, "range")):
        for target in sorted((target for _, found, target in value["triples"]
                              if found == predicate), key=str):
            shown = display(names, manager, target)
            if word == "range" and (value.get("kind") == "datatype"
                                    or datatype_term(target)):
                shown = f"{shown} (literal value)"
            clauses.append(f"{word} {shown}")
    line = f"- [{tag}] {display(names, manager, value['uri'])}"
    if clauses:
        line += ": " + "; ".join(clauses)
    return line + "." + description_line(value["triples"]), []


def render_restriction(entry, names, manager):
    """A supported restriction in words; any other form as compact RDF."""
    value = entry["value"]
    parts = {predicate: target for subject, predicate, target in value["triples"]
             if isinstance(subject, BNode)}
    property_uri = parts.get(OWL.onProperty)
    constraint = next((predicate for predicate in parts
                       if predicate not in (RDF.type, OWL.onProperty)), None)
    class_name = display(names, manager, value["class"])
    dependencies = [f"property|{property_uri}"] if property_uri is not None else []
    if property_uri is None or constraint not in CONSTRAINT_WORDS:
        shown = " ; ".join(
            f"{qualified(manager, predicate)} {display(names, manager, target)}"
            for predicate, target in sorted(parts.items(), key=lambda pair: str(pair[0]))
            if predicate != RDF.type)
        return (f"- [rule] {class_name} rdfs:subClassOf [ {shown} ].", dependencies)
    target = parts[constraint]
    shown = (clean(target) if constraint in COUNTING_CONSTRAINTS
             else display(names, manager, target))
    said = CONSTRAINT_WORDS[constraint].format(
        name=display(names, manager, property_uri), value=shown)
    return f"- [rule] {class_name}: {said}.", dependencies


def render_pattern(entry, names, manager):
    """One observation as an arrow plus its evidence, never as a rule."""
    record = entry["value"]
    subject = (NO_CLASS if record["subject_class"] is None
               else display(names, manager, record["subject_class"]))
    if record["range_kind"] == "class":
        target = display(names, manager, record["range"])
    elif record["range_kind"] == "datatype":
        target = f"literal value ({display(names, manager, record['range'])})"
    else:
        target = "unknown"
    subjects = str(record["distinct_subjects"])
    if record["class_population"]:
        subjects += f"/{record['class_population']}"
    evidence = [f"occurrences={record['occurrences']}", f"subjects={subjects}"]
    if record["coverage"] is not None:
        evidence.append(f"coverage={round(record['coverage'] * 100)}%")
    evidence.append("cardinality={}/{}/{}".format(
        record["cardinality_min"], record["cardinality_median"],
        record["cardinality_max"]))
    predicate = display(names, manager, record["predicate"])
    return (f"- {subject} --{predicate}--> {target}\n  " + "; ".join(evidence), [])


def render_resource(entry, names, manager):
    """One identity card: exact for a native entity, honest for anything else."""
    card = entry["value"]
    everything = [clean(name) for name in card["names"]]
    preferred = clean(card.get("preferred") or "") or (
        everything[0] if everything else display(names, manager, card["uri"]))
    lines = [f"- name: {preferred}"]
    if card["native"] and card["id"]:
        lines.append(f"  id: {card['id']}")
    else:
        # Gate 6: a generic resource is context, not a resolvable identity.
        lines.append(f"  uri: {card['uri']} ({GENERIC_NOTE})")
    types = [display(names, manager, type_) for type_ in card["types"]]
    if types:
        lines.append(f"  type: {', '.join(types)}")
    if card["kind"] and clean(card["kind"]) not in types:
        lines.append(f"  kind: {clean(card['kind'])}")
    aliases = [name for name in everything if name != preferred]
    if aliases:
        lines.append(f"  aliases: {', '.join(aliases)}")
    if card["description"]:
        lines.append(f"  description: {field(card['description'])}")
    return "\n".join(lines), []


def render_example(entry, names, manager):
    """One current assertion, in the same arrow shape as observed usage."""
    value = entry["value"]
    return ("- {} --{}--> {}".format(
        display(names, manager, value["subject"]),
        display(names, manager, value["predicate"]),
        display(names, manager, value["object"])),
        [f"resource|{value['subject']}"])


RENDERERS = {
    "class": render_class, "property": render_property,
    "restriction": render_restriction, "pattern": render_pattern,
    "resource": render_resource, "example": render_example,
}


def render_context_items(context_package, namespace_manager=None):
    """Translate every selected item into one complete, standalone text block."""
    names = naming(context_package)
    sections = ("schema", "patterns", "resources", "examples")
    known = {entry["id"] for section in sections
             for entry in context_package[section]}
    rendered = []
    for section in sections:
        for entry in context_package[section]:
            text, dependencies = RENDERERS[entry["kind"]](
                entry, names, namespace_manager)
            rendered.append({
                "id": entry["id"],
                "section": SECTION_OF_KIND[entry["kind"]],
                "priority": entry["priority"],
                "text": text,
                "dependencies": [name for name in dependencies
                                 if name in known and name != entry["id"]],
            })
    rendered.sort(key=lambda entry: (
        SECTIONS.index(entry["section"]), entry["priority"], entry["id"]))
    return rendered


def assemble_context(rendered_items):
    """Join selected items into one block: fixed section order, nothing empty."""
    blocks = []
    for section in SECTIONS:
        entries = sorted(
            (entry for entry in rendered_items if entry["section"] == section),
            key=lambda entry: (entry["priority"], entry["id"]))
        if entries:
            blocks.append("\n".join(
                [HEADINGS[section]] + [entry["text"] for entry in entries]))
    return "\n\n".join(blocks)


def assembly_overhead(rendered_items, count_tokens):
    """What the headings and line breaks cost, priced with the same counter.

    Charged for every section the candidates could fill rather than for the
    sections that survive, so the assembled text can never overrun the
    allowance. Being a few tokens pessimistic is the safe direction.
    """
    sections = {entry["section"] for entry in rendered_items}
    headings = sum(count_tokens(HEADINGS[section]) for section in SECTIONS
                   if section in sections)
    return headings + count_tokens("\n" * (len(rendered_items) + 2 * len(sections) + 1))


def allowance(budget_config):
    """The context allowance: a stated ceiling, prompt arithmetic, or both.

    With both, the smaller wins. `context_tokens` is a deliberate ceiling on how
    much context to send; the arithmetic is what the prompt can afford once the
    instructions, this source, the output reserve, and the safety margin are
    paid for. A long source must be able to shrink the context below the
    ceiling, so neither number may override the other.

    No number is invented here. A configuration that states neither, or states
    incomplete arithmetic, raises rather than falling back to a default.
    """
    limits = []
    if "context_tokens" in budget_config:
        limits.append(max(0, int(budget_config["context_tokens"])))
    if "total_limit" in budget_config:
        limits.append(context_allowance(
            budget_config["total_limit"], budget_config["fixed_prompt_tokens"],
            budget_config["source_tokens"], budget_config["output_reserve"],
            budget_config["safety_margin"]))
    if not limits:
        raise KeyError("budget_config needs context_tokens or total_limit")
    return min(limits)


def prepare_prompt_context(context_package, budget_config,
                           count_tokens=estimate_tokens):
    """Render, fit, and assemble one context block, with budget diagnostics."""
    rendered = render_context_items(context_package)
    budget = allowance(budget_config)
    overhead = assembly_overhead(rendered, count_tokens)
    result = fit_context_items(
        rendered, max(0, budget - overhead), count_tokens)
    # Report the allowance the caller asked about, not the internal remainder.
    result["budget_tokens"] = budget
    kept = {entry["id"] for entry in result["items"]}
    existing_ids = sorted({
        entry["value"]["id"]
        for entry in context_package.get("resources", [])
        if entry["id"] in kept and entry["value"].get("native")
        and entry["value"].get("id")
    })
    return {"text": assemble_context(result["items"]), "budget": result,
            "existing_ids": existing_ids}
