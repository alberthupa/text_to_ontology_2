"""Proposal 5B: choosing the small part of one graph that a source needs."""

import unittest

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from text_to_ontology.entity_lookup import entity_catalog
from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from text_to_ontology.ontology_views import build_ontology_views
from text_to_ontology.source_concepts import extract_source_concepts
from text_to_ontology.task_context import (
    DEFAULT_LIMITS, build_task_context, select_task_context,
)


EX = Namespace("http://example.com/other/")
PARTICIPATES = RELATION["participates-in"]
SCHEDULED = FACT["scheduled-date"]
LAUNCH = ENTITY["widget-launch"]

PACKAGE_FIELDS = {
    "concepts", "schema", "patterns", "resources", "examples", "labels",
    "diagnostics",
}
ITEM_FIELDS = {"id", "kind", "value", "priority", "reason", "direct"}
DIAGNOSTIC_FIELDS = {"matches", "candidate_counts", "selected_counts", "limits"}
MATCH_FIELDS = {
    "query", "normalized", "target", "target_kind", "tier", "reason", "position",
}


def declared_graph():
    """A schema-rich graph: labels, hierarchy, declared domains and ranges."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    for uri, label in (
        (ONTO.Entity, "Entity"), (CLASS.event, "Event"),
        (CLASS.place, "Place"), (CLASS.action, "Action"),
        (CLASS.person, "Person"), (CLASS.product, "Product"),
    ):
        graph.add((uri, RDF.type, OWL.Class))
        graph.add((uri, RDFS.label, Literal(label)))
    graph.add((CLASS.event, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.place, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.action, RDFS.subClassOf, CLASS.event))
    graph.add((CLASS.event, RDFS.comment, Literal("Something that happens at a time and place")))
    graph.add((CLASS.product, SKOS.definition,
               Literal("A thing made to be sold, such as a tool or a toy")))
    graph.add((PARTICIPATES, RDF.type, OWL.ObjectProperty))
    graph.add((PARTICIPATES, RDFS.label, Literal("participates in")))
    graph.add((PARTICIPATES, RDFS.domain, CLASS.event))
    graph.add((PARTICIPATES, RDFS.range, CLASS.place))
    graph.add((SCHEDULED, RDF.type, OWL.DatatypeProperty))
    graph.add((SCHEDULED, RDFS.label, Literal("scheduled date")))
    graph.add((SCHEDULED, RDFS.range, XSD.date))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.label, Literal("knows")))
    graph.add((FACT.born, RDF.type, OWL.DatatypeProperty))
    graph.add((FACT.born, RDFS.label, Literal("born")))

    entity(graph, LAUNCH, CLASS.event, "temporary Widget unveiling",
           alias="Widget unveiling", kind="Event")
    entity(graph, ENTITY.springfield, CLASS.place, "Springfield")
    entity(graph, ENTITY.riverton, CLASS.place, "Riverton")
    graph.add((LAUNCH, PARTICIPATES, ENTITY.springfield))
    graph.add((LAUNCH, SCHEDULED, Literal("2026-01-05", datatype=XSD.date)))
    return graph


def entity(graph, uri, class_, name, alias=None, kind=""):
    """One project-native entity, written the way the merge step writes one."""
    graph.add((uri, RDF.type, ONTO.Entity))
    graph.add((uri, RDF.type, OWL.NamedIndividual))
    graph.add((uri, RDF.type, class_))
    graph.add((uri, SKOS.prefLabel, Literal(name)))
    if alias:
        graph.add((uri, SKOS.altLabel, Literal(alias)))
    if kind:
        graph.add((uri, ONTO.kind, Literal(kind)))
    return uri


def sparse_graph():
    """Declared classes, no declared domain or range, foreign individuals."""
    graph = Graph()
    graph.bind("ex", EX)
    graph.add((EX.Widget, RDF.type, OWL.Class))
    graph.add((EX.Widget, RDFS.label, Literal("Widget")))
    graph.add((EX.Factory, RDF.type, OWL.Class))
    graph.add((EX.Factory, RDFS.label, Literal("Factory")))
    graph.add((EX.widget1, RDF.type, EX.Widget))
    graph.add((EX.widget1, RDFS.label, Literal("green widget")))
    graph.add((EX.factory1, RDF.type, EX.Factory))
    graph.add((EX.factory1, RDFS.label, Literal("Berlin factory")))
    graph.add((EX.widget1, EX["made-in"], EX.factory1))
    graph.add((EX.widget1, EX.weight, Literal(3)))
    graph.add((EX.widget1, EX["shipped-to"], EX.nowhere))
    return graph


def restricted_graph():
    """The schema-rich graph plus one supported restriction on Event."""
    graph = declared_graph()
    node = BNode()
    graph.add((CLASS.event, RDFS.subClassOf, node))
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, PARTICIPATES))
    graph.add((node, OWL.someValuesFrom, CLASS.place))
    return graph


def cyclic_graph():
    """Two classes that are declared subclasses of each other."""
    graph = Graph()
    bind(graph)
    graph.add((CLASS.event, RDF.type, OWL.Class))
    graph.add((CLASS.event, RDFS.label, Literal("Event")))
    graph.add((CLASS.action, RDF.type, OWL.Class))
    graph.add((CLASS.action, RDFS.label, Literal("Action")))
    graph.add((CLASS.event, RDFS.subClassOf, CLASS.action))
    graph.add((CLASS.action, RDFS.subClassOf, CLASS.event))
    return graph


def ids(items):
    return [item["id"] for item in items]


def kinds(items, kind):
    return [item for item in items if item["kind"] == kind]


def find(items, identifier):
    """The one item with this id, or a readable failure."""
    found = [item for item in items if item["id"] == identifier]
    assert len(found) == 1, (identifier, ids(items))
    return found[0]


def selected(package, kind):
    """Every selected item of one kind, from whichever section holds it."""
    everything = (package["schema"] + package["patterns"]
                  + package["resources"] + package["examples"])
    return kinds(everything, kind)


def pattern_id(subject_class, predicate, range_kind, range_):
    return f"pattern|{subject_class}|{predicate}|{range_kind}|{range_}"


class PackageShapeTest(unittest.TestCase):
    """Case 1: the package and its items keep the agreed plain-record shape."""

    def package(self):
        return build_task_context(
            "The temporary Widget unveiling participates in "
            "Springfield. Event applies to that Place.", declared_graph())

    def test_the_package_has_exactly_the_agreed_fields(self):
        self.assertEqual(set(self.package()), PACKAGE_FIELDS)

    def test_every_item_has_exactly_the_agreed_fields(self):
        package = self.package()
        for section in ("schema", "patterns", "resources", "examples"):
            for item in package[section]:
                self.assertEqual(set(item), ITEM_FIELDS, item["id"])
                self.assertIsInstance(item["id"], str)
                self.assertIsInstance(item["priority"], int)
                self.assertIsInstance(item["reason"], str)
                self.assertIsInstance(item["direct"], bool)

    def test_each_section_only_holds_the_kinds_it_promises(self):
        package = self.package()
        self.assertEqual(
            {item["kind"] for item in package["schema"]}
            - {"class", "property", "restriction"}, set())
        self.assertEqual({item["kind"] for item in package["patterns"]}, {"pattern"})
        self.assertEqual({item["kind"] for item in package["resources"]}, {"resource"})
        self.assertEqual({item["kind"] for item in package["examples"]}, {"example"})

    def test_diagnostics_explain_what_was_considered_and_kept(self):
        diagnostics = self.package()["diagnostics"]
        self.assertEqual(set(diagnostics), DIAGNOSTIC_FIELDS)
        for match in diagnostics["matches"]:
            self.assertEqual(set(match), MATCH_FIELDS)
        self.assertGreater(diagnostics["candidate_counts"]["classes"], 0)
        self.assertGreater(diagnostics["selected_counts"]["classes"], 0)
        self.assertEqual(diagnostics["limits"]["hierarchy_hops"],
                         DEFAULT_LIMITS["hierarchy_hops"])

    def test_the_concepts_that_drove_selection_travel_with_the_package(self):
        package = self.package()
        self.assertGreater(len(package["concepts"]), 0)
        self.assertEqual(
            package["concepts"],
            extract_source_concepts(
                "The temporary Widget unveiling participates in "
                "Springfield. Event applies to that Place.")[:DEFAULT_LIMITS["concepts"]])

    def test_the_selector_runs_without_the_composition_helper(self):
        views = build_ontology_views(declared_graph())
        package = select_task_context(
            "Event applies here.", extract_source_concepts("Event applies here."),
            views)
        self.assertEqual(set(package), PACKAGE_FIELDS)
        self.assertIn(f"class|{CLASS.event}", ids(package["schema"]))


class LabelMatchTest(unittest.TestCase):
    """Cases 2 and 3: names decide what is relevant, at word boundaries."""

    def test_an_rdfs_label_in_the_source_selects_its_class(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        item = find(package["schema"], f"class|{CLASS.event}")
        self.assertTrue(item["direct"])
        self.assertEqual(item["reason"], "source label match")

    def test_a_skos_preferred_label_in_the_source_selects_its_resource(self):
        package = build_task_context(
            "Officials discussed the temporary Widget unveiling.",
            declared_graph())
        item = find(package["resources"], f"resource|{LAUNCH}")
        self.assertTrue(item["direct"])
        self.assertEqual(item["reason"], "source name match")

    def test_a_skos_alternative_label_in_the_source_selects_its_resource(self):
        package = build_task_context(
            "The Widget unveiling expires in June.", declared_graph())
        self.assertIn(f"resource|{LAUNCH}", ids(package["resources"]))

    def test_an_unlabeled_resource_falls_back_to_its_uri_local_name(self):
        graph = Graph()
        graph.add((EX["water-pump"], RDF.type, OWL.Class))
        package = build_task_context("The water pump broke down.", graph)
        self.assertIn(f"class|{EX['water-pump']}", ids(package["schema"]))

    def test_a_short_label_does_not_match_inside_a_longer_word(self):
        graph = Graph()
        graph.add((EX.Art, RDF.type, OWL.Class))
        graph.add((EX.Art, RDFS.label, Literal("art")))
        package = build_task_context("The particle accelerator started.", graph)
        self.assertEqual(package["schema"], [])

    def test_a_comma_separated_pair_is_not_one_name(self):
        graph = Graph()
        graph.add((EX.Pair, RDF.type, OWL.Class))
        graph.add((EX.Pair, RDFS.label, Literal("Berlin Paris")))
        package = build_task_context("Berlin, Paris and Rome.", graph)
        self.assertEqual(package["schema"], [])

    def test_a_concept_matches_a_label_that_the_phrase_index_missed(self):
        graph = Graph()
        graph.add((EX.Widget, RDF.type, OWL.Class))
        graph.add((EX.Widget, RDFS.label, Literal("widget")))
        package = build_task_context("# Widgets\nA widget arrived.", graph)
        item = find(package["schema"], f"class|{EX.Widget}")
        self.assertTrue(item["direct"])


class PriorityTest(unittest.TestCase):
    """Case 4: task relevance is tiered, and the tiers are honest."""

    def test_an_exact_name_match_outranks_a_description_overlap(self):
        package = build_task_context(
            "An Event covers a tool made to be sold.", declared_graph())
        event = find(package["schema"], f"class|{CLASS.event}")
        product = find(package["schema"], f"class|{CLASS.product}")
        self.assertLess(event["priority"], product["priority"])
        self.assertEqual(product["reason"], "description overlap")

    def test_a_resource_name_outranks_a_class_label(self):
        package = build_task_context(
            "The Widget unveiling is an Event.", declared_graph())
        resource = find(package["resources"], f"resource|{LAUNCH}")
        class_ = find(package["schema"], f"class|{CLASS.event}")
        self.assertLess(resource["priority"], class_["priority"])

    def test_a_direct_match_outranks_everything_reached_from_it(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        direct = [item for item in package["schema"] if item["direct"]]
        expanded = [item for item in package["schema"] if not item["direct"]]
        self.assertGreater(len(direct), 0)
        self.assertGreater(len(expanded), 0)
        self.assertLess(max(item["priority"] for item in direct),
                        min(item["priority"] for item in expanded))

    def test_frequency_cannot_promote_an_unrelated_pattern(self):
        graph = declared_graph()
        for index in range(50):
            person = entity(graph, ENTITY[f"person{index}"], CLASS.person,
                            f"Person {index}")
            graph.add((person, FACT.born, Literal("1900")))
        package = build_task_context(
            "The temporary Widget unveiling was signed.", graph)
        unrelated = pattern_id(CLASS.person, FACT.born, "datatype", XSD.string)
        self.assertNotIn(unrelated, ids(package["patterns"]))
        self.assertGreater(len(package["patterns"]), 0)


class DeclaredStructureTest(unittest.TestCase):
    """Cases 5 to 8: declared structure is followed, never invented."""

    def test_an_object_property_named_in_the_source_is_selected(self):
        package = build_task_context(
            "The measure participates in that country.", declared_graph())
        item = find(package["schema"], f"property|{PARTICIPATES}")
        self.assertTrue(item["direct"])

    def test_a_datatype_property_named_in_the_source_is_selected(self):
        package = build_task_context(
            "The scheduled date was recorded.", declared_graph())
        item = find(package["schema"], f"property|{SCHEDULED}")
        self.assertTrue(item["direct"])

    def test_a_selected_property_carries_its_declared_domain_and_range(self):
        package = build_task_context(
            "The measure participates in that country.", declared_graph())
        triples = find(package["schema"], f"property|{PARTICIPATES}")["value"]["triples"]
        self.assertIn((PARTICIPATES, RDFS.domain, CLASS.event), triples)
        self.assertIn((PARTICIPATES, RDFS.range, CLASS.place), triples)
        self.assertIn(f"class|{CLASS.event}", ids(package["schema"]))
        self.assertIn(f"class|{CLASS.place}", ids(package["schema"]))

    def test_a_selected_class_pulls_in_the_properties_declared_over_it(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        item = find(package["schema"], f"property|{PARTICIPATES}")
        self.assertEqual(item["reason"], "declared domain")
        self.assertFalse(item["direct"])

    def test_a_graph_without_domains_or_ranges_still_selects(self):
        package = build_task_context("A green widget arrived.", sparse_graph())
        self.assertIn(f"resource|{EX.widget1}", ids(package["resources"]))
        self.assertIn(f"class|{EX.Widget}", ids(package["schema"]))
        for item in package["schema"]:
            for triple in item["value"].get("triples", []):
                self.assertNotIn(triple[1], (RDFS.domain, RDFS.range))

    def test_one_hierarchy_hop_reaches_the_parent_and_the_child(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        parent = find(package["schema"], f"class|{ONTO.Entity}")
        child = find(package["schema"], f"class|{CLASS.action}")
        self.assertEqual(parent["reason"], "parent class")
        self.assertEqual(child["reason"], "child class")

    def test_the_second_hierarchy_hop_is_not_taken(self):
        graph = declared_graph()
        graph.add((CLASS.meeting, RDF.type, OWL.Class))
        graph.add((CLASS.meeting, RDFS.label, Literal("Meeting")))
        graph.add((CLASS.meeting, RDFS.subClassOf, CLASS.action))
        package = build_task_context("An Event was adopted.", graph)
        self.assertNotIn(f"class|{CLASS.meeting}", ids(package["schema"]))

    def test_a_hierarchy_cycle_terminates_without_duplicates(self):
        package = build_task_context("An Event was adopted.", cyclic_graph())
        self.assertEqual(len(ids(package["schema"])), len(set(ids(package["schema"]))))
        self.assertIn(f"class|{CLASS.action}", ids(package["schema"]))


class RestrictionTest(unittest.TestCase):
    """Case 9: a restriction arrives whole, exactly as the skeleton kept it."""

    def restriction(self):
        package = build_task_context("An Event was adopted.", restricted_graph())
        found = kinds(package["schema"], "restriction")
        self.assertEqual(len(found), 1)
        return package, found[0]

    def test_the_complete_bundle_is_selected(self):
        _, item = self.restriction()
        triples = item["value"]["triples"]
        self.assertEqual(len(triples), 4)
        predicates = {predicate for _, predicate, _ in triples}
        self.assertEqual(
            predicates,
            {RDFS.subClassOf, RDF.type, OWL.onProperty, OWL.someValuesFrom})

    def test_the_bundle_is_copied_from_the_skeleton_unchanged(self):
        graph = restricted_graph()
        package = build_task_context("An Event was adopted.", graph)
        item = kinds(package["schema"], "restriction")[0]
        skeleton = build_ontology_views(graph)["skeleton"]
        for triple in item["value"]["triples"]:
            self.assertIn(triple, skeleton)

    def test_the_restricted_property_comes_with_the_bundle(self):
        package, _ = self.restriction()
        self.assertIn(f"property|{PARTICIPATES}", ids(package["schema"]))

    def test_the_item_id_does_not_depend_on_the_blank_node_identifier(self):
        first, _ = self.restriction()
        second, _ = self.restriction()
        self.assertEqual(ids(kinds(first["schema"], "restriction")),
                         ids(kinds(second["schema"], "restriction")))

    def test_an_unsupported_restriction_never_reaches_the_package(self):
        graph = declared_graph()
        node = BNode()
        graph.add((CLASS.event, RDFS.subClassOf, node))
        graph.add((node, RDF.type, OWL.Restriction))
        graph.add((node, OWL.onProperty, PARTICIPATES))
        graph.add((node, OWL.qualifiedCardinality, Literal(1)))
        graph.add((node, OWL.onClass, CLASS.place))
        package = build_task_context("An Event was adopted.", graph)
        self.assertEqual(kinds(package["schema"], "restriction"), [])


class PatternTest(unittest.TestCase):
    """Cases 10 to 13: observed usage is selected as evidence, not as a rule."""

    def test_a_predicate_named_in_the_source_selects_its_pattern(self):
        package = build_task_context(
            "The measure participates in that country.", declared_graph())
        item = find(package["patterns"],
                    pattern_id(CLASS.event, PARTICIPATES, "class", CLASS.place))
        self.assertTrue(item["direct"])
        self.assertEqual(item["value"]["occurrences"], 1)

    def test_a_selected_subject_class_pulls_in_its_patterns(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        item = find(package["patterns"],
                    pattern_id(CLASS.event, PARTICIPATES, "class", CLASS.place))
        self.assertFalse(item["direct"])
        self.assertEqual(item["reason"], "connected pattern")

    def test_a_class_valued_range_also_connects_a_pattern(self):
        package = build_task_context("A Place was affected.", declared_graph())
        self.assertIn(pattern_id(CLASS.event, PARTICIPATES, "class", CLASS.place),
                      ids(package["patterns"]))

    def test_a_datatype_valued_pattern_keeps_its_datatype(self):
        package = build_task_context("The scheduled date was recorded.",
                                     declared_graph())
        item = find(package["patterns"],
                    pattern_id(CLASS.event, SCHEDULED, "datatype", XSD.date))
        self.assertEqual(item["value"]["range_kind"], "datatype")
        self.assertEqual(item["value"]["range"], XSD.date)

    def test_an_unknown_range_stays_unknown(self):
        package = build_task_context("A green widget arrived.", sparse_graph())
        item = find(package["patterns"],
                    pattern_id(EX.Widget, EX["shipped-to"], "unknown", None))
        self.assertEqual(item["value"]["range_kind"], "unknown")
        self.assertIsNone(item["value"]["range"])

    def test_the_pattern_record_is_the_observation_itself(self):
        package = build_task_context("An Event was adopted.", declared_graph())
        views = build_ontology_views(declared_graph())
        for item in package["patterns"]:
            self.assertIn(item["value"], views["patterns"])

    def test_a_declared_shape_and_a_conflicting_observation_both_survive(self):
        graph = declared_graph()
        bob = entity(graph, ENTITY["bob"], CLASS.person, "Bob")
        graph.add((bob, PARTICIPATES, ENTITY.springfield))
        package = build_task_context(
            "The measure participates in that country.", graph)
        declared = find(package["schema"], f"property|{PARTICIPATES}")["value"]["triples"]
        self.assertIn((PARTICIPATES, RDFS.domain, CLASS.event), declared)
        observed = {item["value"]["subject_class"] for item in package["patterns"]
                    if item["value"]["predicate"] == PARTICIPATES}
        self.assertIn(CLASS.person, observed)
        self.assertIn(CLASS.event, observed)


class ResourceTest(unittest.TestCase):
    """Cases 14 to 16: identities are kept exact, and are not all sent."""

    def test_a_project_native_entity_keeps_its_exact_id_and_aliases(self):
        package = build_task_context(
            "Officials discussed the temporary Widget unveiling.",
            declared_graph())
        card = find(package["resources"], f"resource|{LAUNCH}")["value"]
        self.assertTrue(card["native"])
        self.assertEqual(card["id"], str(LAUNCH))
        self.assertIn("Widget unveiling", card["names"])
        self.assertEqual(card["kind"], "Event")
        catalog = {item["id"]: item for item in entity_catalog(declared_graph())}
        self.assertEqual(sorted(card["names"]), catalog[str(LAUNCH)]["names"])

    def test_a_card_names_the_label_to_show_first(self):
        package = build_task_context(
            "Officials discussed the Widget unveiling.", declared_graph())
        card = find(package["resources"], f"resource|{LAUNCH}")["value"]
        self.assertEqual(card["preferred"],
                         "temporary Widget unveiling")
        self.assertIn(card["preferred"], card["names"])

    def test_a_generic_individual_needs_no_project_entity_type(self):
        package = build_task_context("A green widget arrived.", sparse_graph())
        card = find(package["resources"], f"resource|{EX.widget1}")["value"]
        self.assertFalse(card["native"])
        self.assertIsNone(card["id"])
        self.assertIn(EX.Widget, card["types"])

    def test_a_selected_resource_seeds_its_own_type_class(self):
        package = build_task_context(
            "Officials discussed the Widget unveiling.", declared_graph())
        item = find(package["schema"], f"class|{CLASS.event}")
        self.assertEqual(item["reason"], "type of resource")

    def test_an_unmentioned_resource_stays_out(self):
        package = build_task_context(
            "Officials discussed the Widget unveiling.", declared_graph())
        self.assertNotIn(f"resource|{ENTITY.riverton}", ids(package["resources"]))


class ExampleTest(unittest.TestCase):
    """Cases 17 and 18: assertions illustrate, and a hub is not unpacked."""

    def test_an_assertion_with_a_relevant_predicate_becomes_an_example(self):
        package = build_task_context(
            "The temporary Widget unveiling participates in "
            "Springfield.", declared_graph())
        item = find(package["examples"], f"example|{LAUNCH}|{PARTICIPATES}|{ENTITY.springfield}")
        self.assertEqual(item["value"]["subject"], LAUNCH)
        self.assertEqual(item["value"]["object"], ENTITY.springfield)
        self.assertEqual(item["reason"], "instance assertion")

    def test_a_literal_assertion_can_also_be_an_example(self):
        package = build_task_context(
            "The Widget unveiling has an scheduled date.", declared_graph())
        objects = {item["value"]["object"] for item in package["examples"]}
        self.assertIn(Literal("2026-01-05", datatype=XSD.date), objects)

    def test_the_far_endpoint_of_an_example_becomes_a_resource(self):
        package = build_task_context(
            "The temporary Widget unveiling participates in "
            "Springfield.", declared_graph())
        item = find(package["resources"], f"resource|{ENTITY.springfield}")
        self.assertIn(item["reason"], ("source name match", "assertion endpoint"))

    def test_the_neighbors_of_a_hub_are_not_all_unpacked(self):
        graph = declared_graph()
        for index in range(20):
            other = entity(graph, ENTITY[f"other{index}"], CLASS.place,
                           f"Venue {index}")
            graph.add((LAUNCH, RELATION.knows, other))
        package = build_task_context(
            "Officials discussed the Widget unveiling.", graph)
        places = [item for item in package["resources"]
                  if str(ENTITY.other) in item["id"]]
        self.assertEqual(places, [])
        self.assertLessEqual(len(package["examples"]), DEFAULT_LIMITS["examples"])


class EmptySelectionTest(unittest.TestCase):
    """Case 19: no match means no context, never an arbitrary sample."""

    def test_an_unrelated_source_selects_nothing(self):
        package = build_task_context(
            "Nothing here corresponds. Quiet afternoon.", declared_graph())
        self.assertEqual(package["schema"], [])
        self.assertEqual(package["patterns"], [])
        self.assertEqual(package["resources"], [])
        self.assertEqual(package["examples"], [])
        self.assertGreater(len(package["concepts"]), 0)
        self.assertEqual(package["diagnostics"]["matches"], [])

    def test_an_empty_graph_yields_an_empty_package(self):
        package = build_task_context("An Event was adopted.", Graph())
        self.assertEqual(package["schema"], [])
        self.assertEqual(package["diagnostics"]["candidate_counts"]["classes"], 0)

    def test_an_empty_source_yields_an_empty_package(self):
        package = build_task_context("   ", declared_graph())
        self.assertEqual(package["concepts"], [])
        self.assertEqual(package["resources"], [])


class CapTest(unittest.TestCase):
    """Case 20: every category cap holds on its own."""

    def source(self):
        return ("An Event was adopted. The temporary Widget unveiling participates in Springfield. The scheduled date was recorded. "
                "A Place and a Person and an Action and an Entity.")

    def test_each_cap_limits_only_its_own_category(self):
        for name, section, kind in (
            ("classes", "schema", "class"),
            ("properties", "schema", "property"),
            ("patterns", "patterns", "pattern"),
            ("resources", "resources", "resource"),
            ("examples", "examples", "example"),
        ):
            package = build_task_context(
                self.source(), declared_graph(), limits={name: 1})
            self.assertLessEqual(len(kinds(package[section], kind)), 1, name)

    def test_a_cap_of_zero_empties_only_that_category(self):
        package = build_task_context(
            self.source(), declared_graph(), limits={"patterns": 0})
        self.assertEqual(package["patterns"], [])
        self.assertGreater(len(package["schema"]), 0)

    def test_the_concept_cap_reaches_the_package(self):
        package = build_task_context(
            self.source(), declared_graph(), limits={"concepts": 3})
        self.assertEqual(len(package["concepts"]), 3)

    def test_the_effective_limits_are_reported(self):
        package = build_task_context(
            self.source(), declared_graph(), limits={"classes": 2})
        self.assertEqual(package["diagnostics"]["limits"]["classes"], 2)
        self.assertEqual(package["diagnostics"]["limits"]["patterns"],
                         DEFAULT_LIMITS["patterns"])

    def test_selected_counts_agree_with_what_was_returned(self):
        package = build_task_context(self.source(), declared_graph())
        counts = package["diagnostics"]["selected_counts"]
        self.assertEqual(counts["classes"], len(kinds(package["schema"], "class")))
        self.assertEqual(counts["patterns"], len(package["patterns"]))
        self.assertEqual(counts["resources"], len(package["resources"]))


class DeterminismTest(unittest.TestCase):
    """Case 21: the same source and graph always give the same package."""

    def test_repeated_runs_agree_item_for_item(self):
        text, graph = "An Event participates in Springfield.", declared_graph()
        first, second = (build_task_context(text, graph) for _ in range(2))
        for section in ("schema", "patterns", "resources", "examples"):
            self.assertEqual(ids(first[section]), ids(second[section]))
        self.assertEqual(first["diagnostics"]["matches"],
                         second["diagnostics"]["matches"])

    def test_items_are_ordered_by_priority_then_identifier(self):
        package = build_task_context(
            "An Event participates in Springfield.", declared_graph())
        for section in ("schema", "patterns", "resources", "examples"):
            keys = [(item["priority"], item["id"]) for item in package[section]]
            self.assertEqual(keys, sorted(keys))

    def test_two_graphs_built_the_same_way_select_the_same_items(self):
        text = "An Event participates in Springfield."
        self.assertEqual(ids(build_task_context(text, declared_graph())["schema"]),
                         ids(build_task_context(text, declared_graph())["schema"]))


class ImmutabilityTest(unittest.TestCase):
    """Case 22: selection reads the graph and writes nothing anywhere."""

    def test_the_source_graph_is_unchanged(self):
        graph = declared_graph()
        before = set(graph)
        build_task_context("An Event participates in Springfield.", graph)
        self.assertEqual(set(graph), before)

    def test_the_derived_views_are_unchanged(self):
        views = build_ontology_views(declared_graph())
        before = {name: set(views[name]) for name in
                  ("schema", "instance", "support", "skeleton")}
        patterns = list(views["patterns"])
        text = "An Event participates in Springfield."
        select_task_context(text, extract_source_concepts(text), views)
        for name, triples in before.items():
            self.assertEqual(set(views[name]), triples, name)
        self.assertEqual(views["patterns"], patterns)

    def test_no_selected_item_shares_mutable_state_with_a_pattern_record(self):
        views = build_ontology_views(declared_graph())
        text = "The measure participates in that country."
        package = select_task_context(text, extract_source_concepts(text), views)
        for item in package["patterns"]:
            item["value"]["occurrences"] = -1
        self.assertNotIn(-1, [record["occurrences"] for record in views["patterns"]])


class LabelExportTest(unittest.TestCase):
    """Case 23: the package carries the names its rendering will need."""

    def test_every_named_uri_in_a_selected_item_has_a_label_entry(self):
        package = build_task_context(
            "An Event participates in Springfield.", declared_graph())
        self.assertEqual(package["labels"][str(CLASS.event)], ["Event"])
        self.assertEqual(package["labels"][str(PARTICIPATES)], ["participates in"])

    def test_an_unlabeled_uri_falls_back_to_its_decoded_local_name(self):
        package = build_task_context("A green widget arrived.", sparse_graph())
        self.assertEqual(package["labels"][str(EX["shipped-to"])], ["shipped to"])

    def test_no_label_entry_exists_for_an_unselected_resource(self):
        package = build_task_context(
            "Officials discussed the Widget unveiling.", declared_graph())
        self.assertNotIn(str(ENTITY.riverton), package["labels"])


if __name__ == "__main__":
    unittest.main()
