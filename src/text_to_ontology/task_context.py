"""Choose the small part of the current graph that one source text needs.

Selection is deterministic, bounded, and read only. It answers three questions
in one package and keeps their answers apart, because they do not mean the same
thing:

    schema     what the ontology declares about the matched classes, properties,
               and restrictions, copied from the skeleton exactly as stated;
    patterns   what the current instance data happens to do, as evidence;
    resources  which existing resources and assertions the source may be
               talking about, with their exact identifiers.

Nothing is inferred. A selected observation never becomes a declared axiom, a
generic resource is never promised the project's `existing_id` resolution, and
no score, view, or diagnostic is written back into any graph.

Relevance is tiered rather than weighted: a name occurring in the source beats a
label, which beats a concept, which beats a description overlap, which beats
anything reached by expansion. Empirical frequency never promotes a pattern the
source has no reason to see. Ties fall back to stable strings, so the same text
and graph always give the same package.
"""

from urllib.parse import unquote

from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from .entity_lookup import entity_catalog
from .graph_patterns import STRUCTURAL, eligible
from .ontology_views import build_ontology_views
from .source_concepts import extract_source_concepts, normalize, text_phrases


NAME_PREDICATES = (RDFS.label, SKOS.prefLabel, SKOS.altLabel)
TEXT_PREDICATES = (RDFS.comment, SKOS.definition)
CLASS_TYPES = {OWL.Class, RDFS.Class}
PROPERTY_TYPES = {OWL.ObjectProperty, OWL.DatatypeProperty}

# Types that say a resource exists rather than what it is.
METATYPES = {OWL.NamedIndividual, SKOS.Concept, OWL.Thing, RDFS.Resource}

# Why an item is here, in decreasing order of task relevance. The number is the
# item's priority: the renderer and the prompt budget keep this order.
DIRECT_NAME = 1       # a resource name or alias occurs in the source
DIRECT_LABEL = 2      # a class, property, or predicate label occurs in it
CONCEPT = 3           # an extracted concept equals a name or local name
OVERLAP = 4           # the source shares content words with a description
DEPENDENCY = 5        # structure a directly matched item needs to be understood
CONNECTED = 6         # an observation about a directly matched class or property
NEIGHBOR = 7          # a one-hop assertion or the resource at its far end
INDIRECT = 8          # an observation reached only through a matched resource

DEFAULT_LIMITS = {
    "concepts": 40,
    "direct_matches": 40,
    "classes": 12,
    "properties": 16,
    "restrictions": 8,
    "patterns": 20,
    "resources": 15,
    "examples": 12,
    "hierarchy_hops": 1,
    "instance_hops": 1,
    # Names longer than this many words cannot be matched in the source.
    "match_tokens": 8,
    # How many content words a description must share to count as relevant.
    "overlap_tokens": 2,
}


def structural(term):
    """Whether a term names modeling vocabulary rather than the domain."""
    return str(term).startswith(STRUCTURAL)


def datatype_term(term):
    """Whether a term names a datatype, which is never a class to expand."""
    return str(term).startswith(str(XSD)) or term == RDF.langString


def local_name(uri):
    """The readable tail of a URI: decoded, with separators read as spaces."""
    text = unquote(str(uri)).rstrip("/#")
    for separator in ("#", "/", ":"):
        text = text.rsplit(separator, 1)[-1]
    spaced = "".join(
        f" {character}" if index and character.isupper() and text[index - 1].islower()
        else character
        for index, character in enumerate(text)
    )
    return " ".join(spaced.replace("_", " ").replace("-", " ").split())


def sort_key(triple):
    return tuple(str(term) for term in triple)


def name_index(views):
    """Every naming statement in every view, as uri -> sorted names."""
    found = {}
    for view in ("schema", "instance", "support"):
        for subject, predicate, value in views[view]:
            if predicate in NAME_PREDICATES and isinstance(subject, URIRef):
                if isinstance(value, Literal):
                    found.setdefault(subject, set()).add(str(value))
    return {uri: sorted(names) for uri, names in found.items()}


def text_index(views):
    """Every description and definition, as uri -> sorted texts."""
    found = {}
    for view in ("schema", "instance", "support"):
        for subject, predicate, value in views[view]:
            if predicate in TEXT_PREDICATES and isinstance(subject, URIRef):
                if isinstance(value, Literal):
                    found.setdefault(subject, set()).add(str(value))
    return {uri: sorted(texts) for uri, texts in found.items()}


def names_for(names, uri):
    """The names of a resource, falling back to its decoded local name."""
    return names.get(uri) or [local_name(uri)]


def schema_index(skeleton):
    """The skeleton's classes and properties, including the ones only named."""
    classes, properties = {}, {}
    for subject, _, type_ in skeleton.triples((None, RDF.type, None)):
        if not isinstance(subject, URIRef):
            continue
        if type_ in CLASS_TYPES:
            classes.setdefault(subject, None)
        elif type_ in PROPERTY_TYPES:
            properties.setdefault(
                subject, "object" if type_ == OWL.ObjectProperty else "datatype")
    for subject, _, target in skeleton.triples((None, RDFS.subClassOf, None)):
        for term in (subject, target):
            if isinstance(term, URIRef):
                classes.setdefault(term, None)
    for predicate in (RDFS.domain, RDFS.range):
        for subject, _, target in skeleton.triples((None, predicate, None)):
            if isinstance(subject, URIRef):
                properties.setdefault(subject, None)
            if isinstance(target, URIRef) and not datatype_term(target):
                classes.setdefault(target, None)
    return classes, properties


def preferred_name(instance, uri, names):
    """The name to show first: a preferred label, then a label, then any name."""
    for predicate in (SKOS.prefLabel, RDFS.label):
        found = sorted(str(value) for value in instance.objects(uri, predicate))
        if found:
            return found[0]
    return names[0] if names else local_name(uri)


def resource_index(views, names, texts, native_entities):
    """Every current individual as one card, native or generic."""
    cards = {}
    for subject, _, type_ in views["instance"].triples((None, RDF.type, None)):
        if not isinstance(subject, URIRef):
            continue
        card = cards.setdefault(subject, {
            "uri": subject, "id": None, "names": names_for(names, subject),
            "preferred": preferred_name(
                views["instance"], subject, names_for(names, subject)),
            "kind": "", "description": next(iter(texts.get(subject, [])), ""),
            "types": [], "native": False,
        })
        if isinstance(type_, URIRef) and type_ not in METATYPES:
            card["types"].append(type_)
    for entry in native_entities:
        uri = URIRef(entry["id"])
        card = cards.get(uri)
        if card is None:
            continue
        # The catalog owns project identity: keep its id, names, and kind exact.
        card.update({
            "id": entry["id"],
            "native": True,
            "kind": entry["kind"],
            "description": entry["description"] or card["description"],
            "names": sorted(set(card["names"]) | set(entry["names"])),
        })
    for card in cards.values():
        card["types"] = sorted(set(card["types"]), key=str)
    return cards


def pattern_key(record):
    """A pattern's identifier, built from what it observes, not from its place."""
    return (f"pattern|{record['subject_class']}|{record['predicate']}"
            f"|{record['range_kind']}|{record['range']}")


def build_indexes(views, native_entities):
    """Everything one selection needs to look up, built once and read only."""
    names, texts = name_index(views), text_index(views)
    classes, properties = schema_index(views["skeleton"])
    return {
        "names": names,
        "texts": texts,
        "classes": classes,
        "properties": properties,
        "resources": resource_index(views, names, texts, native_entities),
        "patterns": views["patterns"],
    }


def candidates(indexes):
    """Everything a source can match, with the names and texts to match on."""
    found = []
    for uri in indexes["resources"]:
        card = indexes["resources"][uri]
        found.append({"key": f"resource|{uri}", "kind": "resource", "uri": uri,
                      "names": card["names"],
                      "texts": indexes["texts"].get(uri, [])})
    for kind, group in (("class", "classes"), ("property", "properties")):
        for uri in indexes[group]:
            found.append({"key": f"{kind}|{uri}", "kind": kind, "uri": uri,
                          "names": names_for(indexes["names"], uri),
                          "texts": indexes["texts"].get(uri, [])})
    for record in indexes["patterns"]:
        predicate = record["predicate"]
        found.append({"key": pattern_key(record), "kind": "pattern",
                      "uri": predicate, "record": record,
                      "names": names_for(indexes["names"], predicate),
                      "texts": []})
    return found


def content_words(text):
    """The normalized words of a description, without one-letter noise."""
    return {word for word in normalize(text).split() if len(word) > 1}


def match(candidate, query, tier, reason, position):
    """One reason to believe the source is talking about one candidate."""
    return {
        "query": query,
        "normalized": normalize(query),
        "target": str(candidate["uri"]) if candidate["kind"] != "pattern"
        else candidate["key"],
        "target_kind": candidate["kind"],
        "tier": tier,
        "reason": reason,
        "position": position,
    }


def name_match(candidate, phrases, concepts):
    """The strongest name-based reason this candidate is relevant, if any."""
    best = None
    for name in candidate["names"]:
        form = normalize(name)
        if not form:
            continue
        position = phrases.get(form)
        if position is not None:
            tier = DIRECT_NAME if candidate["kind"] == "resource" else DIRECT_LABEL
            reason = ("source name match" if candidate["kind"] == "resource"
                      else "source label match")
            found = match(candidate, name, tier, reason, position)
        elif form in concepts:
            found = match(candidate, name, CONCEPT, "concept match", concepts[form])
        else:
            continue
        if best is None or found["tier"] < best["tier"]:
            best = found
    return best


def overlap_match(candidate, words, limits):
    """A weaker reason: the source shares content words with a description."""
    for text in candidate["texts"]:
        shared = words & content_words(text)
        if len(shared) >= limits["overlap_tokens"]:
            return match(candidate, " ".join(sorted(shared)), OVERLAP,
                         "description overlap", None)
    return None


def direct_matches(text, concepts, indexes, limits):
    """Every candidate the source itself gives a reason to include."""
    found = candidates(indexes)
    longest = max(
        [2] + [len(normalize(name).split())
               for candidate in found for name in candidate["names"]])
    phrases = text_phrases(text, min(longest, limits["match_tokens"]))
    forms = {concept["normalized"]: concept["position"] for concept in concepts}
    words = {word for form in forms for word in form.split() if len(word) > 1}

    matches = []
    for candidate in found:
        best = name_match(candidate, phrases, forms)
        if best is None:
            best = overlap_match(candidate, words, limits)
        if best is not None:
            matches.append(best)
    matches.sort(key=lambda record: (
        record["tier"], record["target_kind"], record["target"]))
    return matches[:limits["direct_matches"]]


def item(identifier, kind, value, priority, reason, direct):
    return {"id": identifier, "kind": kind, "value": value,
            "priority": priority, "reason": reason, "direct": direct}


def add(selected, new):
    """Keep one item per identity, remembering the strongest reason for it."""
    current = selected.get(new["id"])
    if current is None or new["priority"] < current["priority"]:
        selected[new["id"]] = new


def described(skeleton, uri):
    """The naming and describing statements a skeleton keeps for a resource."""
    triples = []
    for predicate in NAME_PREDICATES + TEXT_PREDICATES:
        triples += skeleton.triples((uri, predicate, None))
    return triples


def class_item(views, uri, priority, reason, direct):
    """A class with its declaration, its naming, and its named parents."""
    skeleton = views["skeleton"]
    triples = list(skeleton.triples((uri, RDF.type, None)))
    triples += described(skeleton, uri)
    triples += [triple for triple in skeleton.triples((uri, RDFS.subClassOf, None))
                if isinstance(triple[2], URIRef)]
    return item(f"class|{uri}", "class",
                {"uri": uri, "triples": sorted(set(triples), key=sort_key)},
                priority, reason, direct)


def property_item(views, indexes, uri, priority, reason, direct):
    """A property with its declaration, naming, and declared domain and range."""
    skeleton = views["skeleton"]
    triples = list(skeleton.triples((uri, RDF.type, None)))
    triples += described(skeleton, uri)
    for predicate in (RDFS.domain, RDFS.range):
        triples += skeleton.triples((uri, predicate, None))
    return item(f"property|{uri}", "property",
                {"uri": uri, "kind": indexes["properties"].get(uri),
                 "triples": sorted(set(triples), key=sort_key)},
                priority, reason, direct)


def restriction_items(views, uri, priority, reason):
    """Every supported restriction on a class, each copied whole."""
    skeleton = views["skeleton"]
    for _, _, node in skeleton.triples((uri, RDFS.subClassOf, None)):
        if not isinstance(node, BNode):
            continue
        parts = sorted(skeleton.triples((node, None, None)), key=sort_key)
        if not parts:
            continue
        identity = "|".join(f"{predicate}={target}" for _, predicate, target in parts)
        yield item(f"restriction|{uri}|{identity}", "restriction",
                   {"class": uri, "triples": [(uri, RDFS.subClassOf, node)] + parts},
                   priority, reason, False)


def pattern_item(record, priority, reason, direct):
    return item(pattern_key(record), "pattern", dict(record), priority, reason,
                direct)


def resource_item(indexes, uri, priority, reason, direct):
    card = indexes["resources"][uri]
    return item(f"resource|{uri}", "resource", dict(card), priority, reason, direct)


def example_item(triple, priority, reason):
    subject, predicate, target = triple
    return item(f"example|{subject}|{predicate}|{target}", "example",
                {"subject": subject, "predicate": predicate, "object": target},
                priority, reason, False)


def seed(selected, views, indexes, matches):
    """Turn every direct match into the item it stands for."""
    records = {pattern_key(record): record for record in indexes["patterns"]}
    for found in matches:
        target, tier, reason = found["target"], found["tier"], found["reason"]
        if found["target_kind"] == "class":
            add(selected, class_item(views, URIRef(target), tier, reason, True))
        elif found["target_kind"] == "property":
            add(selected, property_item(
                views, indexes, URIRef(target), tier, reason, True))
        elif found["target_kind"] == "resource":
            add(selected, resource_item(
                indexes, URIRef(target), tier, reason, True))
        else:
            add(selected, pattern_item(records[target], tier, reason, True))


def relatives(skeleton, uri, hops, upward):
    """Named classes within `hops` subclass steps, without revisiting any."""
    found, frontier, visited = [], [uri], {uri}
    for _ in range(hops):
        next_frontier = []
        for node in frontier:
            targets = (skeleton.objects(node, RDFS.subClassOf) if upward
                       else skeleton.subjects(RDFS.subClassOf, node))
            for target in targets:
                if isinstance(target, URIRef) and target not in visited:
                    visited.add(target)
                    next_frontier.append(target)
                    found.append(target)
        frontier = next_frontier
    return found


def connected_patterns(indexes, uri):
    """Observations whose subject class or class-valued range is this class."""
    for record in indexes["patterns"]:
        if record["subject_class"] == uri:
            yield record
        elif record["range_kind"] == "class" and record["range"] == uri:
            yield record


def endpoint_classes(views, uri):
    """The named, non-datatype classes a property's declarations point at."""
    for predicate in (RDFS.domain, RDFS.range):
        for _, _, target in views["skeleton"].triples((uri, predicate, None)):
            if isinstance(target, URIRef) and not datatype_term(target):
                yield target


def expand_property(selected, views, indexes, uri, priority):
    """The endpoints a property needs, and the observations about it."""
    for endpoint in endpoint_classes(views, uri):
        add(selected, class_item(
            views, endpoint, DEPENDENCY, "endpoint declaration", False))
    for record in indexes["patterns"]:
        if record["predicate"] == uri:
            add(selected, pattern_item(record, priority, "connected pattern", False))


def expand_class(selected, views, indexes, uri, limits):
    """One hierarchy hop, the properties declared over a class, and its rules."""
    skeleton = views["skeleton"]
    for parent in relatives(skeleton, uri, limits["hierarchy_hops"], True):
        add(selected, class_item(views, parent, DEPENDENCY, "parent class", False))
    for child in relatives(skeleton, uri, limits["hierarchy_hops"], False):
        add(selected, class_item(views, child, DEPENDENCY, "child class", False))
    for predicate, reason in ((RDFS.domain, "declared domain"),
                              (RDFS.range, "declared range")):
        for property_uri, _, _ in skeleton.triples((None, predicate, uri)):
            if not isinstance(property_uri, URIRef):
                continue
            add(selected, property_item(
                views, indexes, property_uri, DEPENDENCY, reason, False))
            expand_property(selected, views, indexes, property_uri, CONNECTED)
    for restriction in restriction_items(
            views, uri, DEPENDENCY, "restriction on class"):
        add(selected, restriction)
        for _, predicate, target in restriction["value"]["triples"]:
            if predicate == OWL.onProperty and isinstance(target, URIRef):
                add(selected, property_item(
                    views, indexes, target, DEPENDENCY, "restriction property", False))
    for record in connected_patterns(indexes, uri):
        add(selected, pattern_item(record, CONNECTED, "connected pattern", False))


def relevant_predicates(selected):
    """The predicates the package has a reason for beyond the resource itself.

    An observation reached only through a matched resource does not count. It
    exists because that resource has neighbors, so trusting it here would let
    one hub pull its whole neighborhood in through its own patterns.
    """
    found = set()
    for entry in selected.values():
        if entry["priority"] >= INDIRECT:
            continue
        if entry["kind"] == "property":
            found.add(entry["value"]["uri"])
        elif entry["kind"] == "pattern":
            found.add(entry["value"]["predicate"])
    return found


def assertions(views, uri):
    """The one-hop instance statements a resource takes part in."""
    for triple in views["instance"].triples((uri, None, None)):
        yield triple, triple[2]
    for triple in views["instance"].triples((None, None, uri)):
        yield triple, triple[0]


def expand_resource(selected, views, indexes, uri, limits, direct_resources):
    """A resource's own classes, and only the assertions already made relevant."""
    for type_ in indexes["resources"][uri]["types"]:
        add(selected, class_item(views, type_, DEPENDENCY, "type of resource", False))
        for record in connected_patterns(indexes, type_):
            add(selected, pattern_item(record, INDIRECT, "indirect pattern", False))
    if limits["instance_hops"] < 1:
        return
    predicates = relevant_predicates(selected)
    for triple, other in assertions(views, uri):
        if not eligible(triple[1]):
            continue
        # A hub must not drag its whole neighborhood in: an assertion needs a
        # predicate that already matters, or a far end that already does.
        if triple[1] not in predicates and other not in direct_resources:
            continue
        add(selected, example_item(triple, NEIGHBOR, "instance assertion"))
        if isinstance(other, URIRef) and other in indexes["resources"]:
            add(selected, resource_item(
                indexes, other, NEIGHBOR, "assertion endpoint", False))


def expand(selected, views, indexes, limits):
    """Add the minimal adjacent material the direct seeds need to be read."""
    direct = [entry for entry in selected.values() if entry["direct"]]
    for entry in sorted(direct, key=lambda entry: entry["id"]):
        if entry["kind"] == "class":
            expand_class(selected, views, indexes, entry["value"]["uri"], limits)
        elif entry["kind"] == "property":
            expand_property(
                selected, views, indexes, entry["value"]["uri"], CONNECTED)
    resources = {entry["value"]["uri"] for entry in direct
                 if entry["kind"] == "resource"}
    for uri in sorted(resources, key=str):
        expand_resource(selected, views, indexes, uri, limits, resources)


def ordered(selected, kind, cap):
    """The items of one kind, most relevant first, cut to the agreed cap."""
    items = [entry for entry in selected.values() if entry["kind"] == kind]
    items.sort(key=lambda entry: (entry["priority"], entry["id"]))
    return items[:cap]


def item_uris(entry):
    """The domain resources one item mentions and therefore needs names for."""
    kind, value = entry["kind"], entry["value"]
    if kind in ("class", "property"):
        found = [value["uri"]]
        found += [term for triple in value["triples"] for term in triple]
    elif kind == "restriction":
        found = [term for triple in value["triples"] for term in triple]
    elif kind == "pattern":
        found = [value["subject_class"], value["predicate"], value["range"]]
    elif kind == "resource":
        found = [value["uri"], *value["types"]]
    else:
        found = [value["subject"], value["predicate"], value["object"]]
    return [term for term in found
            if isinstance(term, URIRef) and not structural(term)]


def label_export(items, names):
    """The names the renderer will need, for exactly the items that survived."""
    found = {}
    for entry in items:
        for uri in item_uris(entry):
            found[str(uri)] = names_for(names, uri)
    return dict(sorted(found.items()))


def select_task_context(text, concepts, ontology_views, native_entities=None,
                        limits=None):
    """Return the context package this one source justifies, and why."""
    limits = dict(DEFAULT_LIMITS, **(limits or {}))
    concepts = list(concepts)[:limits["concepts"]]
    indexes = build_indexes(ontology_views, native_entities or [])
    matches = direct_matches(text, concepts, indexes, limits)

    selected = {}
    seed(selected, ontology_views, indexes, matches)
    expand(selected, ontology_views, indexes, limits)

    classes = ordered(selected, "class", limits["classes"])
    properties = ordered(selected, "property", limits["properties"])
    restrictions = ordered(selected, "restriction", limits["restrictions"])
    schema = sorted(classes + properties + restrictions,
                    key=lambda entry: (entry["priority"], entry["id"]))
    patterns = ordered(selected, "pattern", limits["patterns"])
    resources = ordered(selected, "resource", limits["resources"])
    examples = ordered(selected, "example", limits["examples"])
    return {
        "concepts": concepts,
        "schema": schema,
        "patterns": patterns,
        "resources": resources,
        "examples": examples,
        "labels": label_export(
            schema + patterns + resources + examples, indexes["names"]),
        "diagnostics": {
            "matches": matches,
            "candidate_counts": {
                "classes": len(indexes["classes"]),
                "properties": len(indexes["properties"]),
                "resources": len(indexes["resources"]),
                "patterns": len(indexes["patterns"]),
            },
            "selected_counts": {
                "classes": len(classes),
                "properties": len(properties),
                "restrictions": len(restrictions),
                "patterns": len(patterns),
                "resources": len(resources),
                "examples": len(examples),
                "matches": len(matches),
            },
            "limits": limits,
        },
    }


def build_task_context(text, source_graph, limits=None):
    """Read the current graph and select the context for one source text."""
    return select_task_context(
        text, extract_source_concepts(text), build_ontology_views(source_graph),
        entity_catalog(source_graph), limits)
