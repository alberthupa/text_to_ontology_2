"""Summarize how the current instance data actually uses its properties.

These are observations, not axioms. A record says "seven locations exist and two
of them carry this property once each", never "every location must". Nothing
here is written back into the graph, and no pattern is dropped for being rare:
Proposal 2 has no notion of importance to drop it by.
"""

from collections import Counter
from statistics import median

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

from graph_management import ONTO


# Types that say a resource exists rather than what it is.
METATYPES = {OWL.NamedIndividual, SKOS.Concept, OWL.Thing, RDFS.Resource}

# Predicates from these vocabularies carry structure or naming, not relations.
STRUCTURAL = tuple(str(namespace) for namespace in (RDF, RDFS, OWL, SH, SKOS))

# Project identity metadata, which repeats the type in a literal.
EXCLUDED = {ONTO.kind}


def eligible(predicate):
    """Whether a predicate describes the domain rather than the modeling."""
    return predicate not in EXCLUDED and not str(predicate).startswith(STRUCTURAL)


def ancestors(schema_graph, class_):
    """Every superclass reachable through explicit rdfs:subClassOf."""
    found, pending = set(), [class_]
    while pending:
        for parent in schema_graph.objects(pending.pop(), RDFS.subClassOf):
            if isinstance(parent, URIRef) and parent not in found:
                found.add(parent)
                pending.append(parent)
    return found


def usable_classes(schema_graph, instance_graph, resource, cache):
    """The most specific explicit domain classes of one resource.

    Decision gate 3: metatypes are ignored, only stated subclass links are
    followed, and a resource with two incomparable classes keeps both.
    """
    if resource in cache:
        return cache[resource]
    types = {
        type_ for type_ in instance_graph.objects(resource, RDF.type)
        if isinstance(type_, URIRef) and type_ not in METATYPES
    }
    specific = {
        type_ for type_ in types
        if not any(type_ in ancestors(schema_graph, other)
                   for other in types if other != type_)
    }
    # A subclass cycle leaves nothing specific; report the stated types instead.
    cache[resource] = tuple(sorted(specific or types, key=str))
    return cache[resource]


def subject_classes(schema_graph, instance_graph, resource, cache):
    """The classes to report a subject under, or `None` when it has none."""
    return usable_classes(schema_graph, instance_graph, resource, cache) or (None,)


def object_ranges(schema_graph, instance_graph, target, cache):
    """The `(kind, range)` pairs one object position contributes."""
    if isinstance(target, Literal):
        datatype = target.datatype
        if datatype is None:
            datatype = RDF.langString if target.language else XSD.string
        return (("datatype", datatype),)
    classes = usable_classes(schema_graph, instance_graph, target, cache)
    if not classes:
        return (("unknown", None),)
    return tuple(("class", class_) for class_ in classes)


def class_populations(schema_graph, instance_graph, cache):
    """How many distinct current individuals each class has."""
    population = Counter()
    for resource in set(instance_graph.subjects(RDF.type, None)):
        for class_ in usable_classes(schema_graph, instance_graph, resource, cache):
            population[class_] += 1
    return population


def observed_relationships(schema_graph, instance_graph):
    """Return the class-property-range patterns the instance data shows."""
    cache = {}
    population = class_populations(schema_graph, instance_graph, cache)

    values_per_subject = {}
    for subject, predicate, target in instance_graph:
        if not eligible(predicate):
            continue
        for class_ in subject_classes(schema_graph, instance_graph, subject, cache):
            for kind, range_ in object_ranges(
                    schema_graph, instance_graph, target, cache):
                key = (class_, predicate, kind, range_)
                values_per_subject.setdefault(key, Counter())[subject] += 1

    records = [
        pattern_record(key, counts, population)
        for key, counts in values_per_subject.items()
    ]
    records.sort(key=lambda record: (
        str(record["subject_class"]), str(record["predicate"]),
        record["range_kind"], str(record["range"]),
    ))
    return records


def pattern_record(key, counts, population):
    """One pattern with its evidence, per decision gates 4 and 5."""
    class_, predicate, kind, range_ = key
    values = sorted(counts.values())
    size = population.get(class_) if class_ is not None else None
    return {
        "subject_class": class_,
        "predicate": predicate,
        "range_kind": kind,
        "range": range_,
        "occurrences": sum(values),
        "distinct_subjects": len(values),
        "class_population": size,
        "coverage": len(values) / size if size else None,
        # Gate 4: summarized over participating subjects only. Class members
        # with no value are reported by coverage instead.
        "cardinality_min": min(values),
        "cardinality_median": float(median(values)),
        "cardinality_max": max(values),
    }
