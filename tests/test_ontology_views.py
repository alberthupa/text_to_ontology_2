"""Proposal 5A: naming the derived views of one graph without changing them."""

import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

from text_to_ontology.entity_lookup import entity_catalog
from text_to_ontology.graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from text_to_ontology.graph_partition import partition_graph
from text_to_ontology.graph_patterns import observed_relationships
from text_to_ontology.graph_skeleton import create_graph_skeleton
from text_to_ontology.ontology_views import build_ontology_views


REPOSITORY = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPOSITORY / "ontology.ttl"
EX = Namespace("http://example.com/other/")

FIELDS = {"schema", "instance", "support", "skeleton", "patterns"}


def declared_graph():
    """A schema-rich graph: declarations, hierarchy, domain, range, an instance."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.person, RDFS.label, Literal("Person")))
    graph.add((CLASS.organization, RDF.type, OWL.Class))
    graph.add((CLASS.organization, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.organization, RDFS.label, Literal("Organization")))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.domain, CLASS.person))
    graph.add((RELATION.knows, RDFS.range, CLASS.organization))
    graph.add((RELATION.knows, RDFS.label, Literal("knows")))
    graph.add((FACT.born, RDF.type, OWL.DatatypeProperty))
    graph.add((FACT.born, RDFS.range, XSD.gYear))
    graph.add((FACT.born, RDFS.label, Literal("born")))
    graph.add((ENTITY.ada, RDF.type, ONTO.Entity))
    graph.add((ENTITY.ada, RDF.type, OWL.NamedIndividual))
    graph.add((ENTITY.ada, RDF.type, CLASS.person))
    graph.add((ENTITY.ada, SKOS.prefLabel, Literal("Ada")))
    graph.add((ENTITY.acme, RDF.type, ONTO.Entity))
    graph.add((ENTITY.acme, RDF.type, CLASS.organization))
    graph.add((ENTITY.acme, SKOS.prefLabel, Literal("Acme")))
    graph.add((ENTITY.ada, RELATION.knows, ENTITY.acme))
    graph.add((ENTITY.ada, FACT.born, Literal("1815")))
    return graph


def sparse_graph():
    """Individuals of a foreign vocabulary, with no domain, range, or onto:Entity."""
    graph = Graph()
    graph.bind("ex", EX)
    graph.add((EX.Widget, RDF.type, OWL.Class))
    graph.add((EX.Widget, RDFS.label, Literal("Widget")))
    graph.add((EX.widget1, RDF.type, EX.Widget))
    graph.add((EX.widget1, RDFS.label, Literal("First widget")))
    graph.add((EX.widget2, RDF.type, OWL.NamedIndividual))
    graph.add((EX.widget1, EX.madeIn, EX.berlin))
    graph.add((EX.widget1, EX.weight, Literal(3)))
    return graph


def schema_only_graph():
    """Declared structure with nothing asserted about any individual."""
    graph = Graph()
    bind(graph)
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.label, Literal("Person")))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.domain, CLASS.person))
    return graph


def repository_graph():
    graph = Graph()
    graph.parse(GRAPH_PATH, format="turtle")
    return graph


class ShapeTest(unittest.TestCase):
    """Case 1: one record with the five agreed fields, whatever the input."""

    def test_the_five_fields_are_always_present(self):
        for source in (Graph(), declared_graph(), sparse_graph()):
            views = build_ontology_views(source)
            self.assertEqual(set(views), FIELDS)

    def test_four_fields_are_graphs_and_patterns_is_a_list(self):
        views = build_ontology_views(declared_graph())
        for field in ("schema", "instance", "support", "skeleton"):
            self.assertIsInstance(views[field], Graph)
        self.assertIsInstance(views["patterns"], list)

    def test_an_empty_graph_yields_empty_views_and_no_patterns(self):
        views = build_ontology_views(Graph())
        for field in ("schema", "instance", "support", "skeleton"):
            self.assertEqual(len(views[field]), 0)
        self.assertEqual(views["patterns"], [])


class CompositionTest(unittest.TestCase):
    """Case 2: every field equals what the existing module returns directly."""

    def check(self, source):
        views = build_ontology_views(source)
        schema, instance, support = partition_graph(source)
        self.assertEqual(set(views["schema"]), set(schema))
        self.assertEqual(set(views["instance"]), set(instance))
        self.assertEqual(set(views["support"]), set(support))
        self.assertEqual(
            set(views["skeleton"]), set(create_graph_skeleton(schema)))
        self.assertEqual(
            views["patterns"], observed_relationships(schema, instance))

    def test_the_schema_rich_graph_composes_identically(self):
        self.check(declared_graph())

    def test_the_sparse_graph_composes_identically(self):
        self.check(sparse_graph())

    def test_the_repository_graph_composes_identically(self):
        self.check(repository_graph())

    def test_the_partition_stays_lossless_through_the_facade(self):
        source = declared_graph()
        views = build_ontology_views(source)
        parts = [set(views[field]) for field in ("schema", "instance", "support")]
        self.assertEqual(parts[0] | parts[1] | parts[2], set(source))
        self.assertEqual(parts[0] & parts[1], set())
        self.assertEqual(parts[0] & parts[2], set())
        self.assertEqual(parts[1] & parts[2], set())

    def test_repeated_calls_agree(self):
        source = declared_graph()
        first, second = build_ontology_views(source), build_ontology_views(source)
        self.assertEqual(first["patterns"], second["patterns"])
        for field in ("schema", "instance", "support", "skeleton"):
            self.assertEqual(set(first[field]), set(second[field]))


class DeclaredStructureTest(unittest.TestCase):
    """Case 3: the declared skeleton carries what the source actually states."""

    def test_declarations_hierarchy_domain_and_range_reach_the_skeleton(self):
        skeleton = build_ontology_views(declared_graph())["skeleton"]
        for triple in (
            (CLASS.person, RDF.type, OWL.Class),
            (CLASS.person, RDFS.subClassOf, ONTO.Entity),
            (RELATION.knows, RDF.type, OWL.ObjectProperty),
            (RELATION.knows, RDFS.domain, CLASS.person),
            (RELATION.knows, RDFS.range, CLASS.organization),
            (FACT.born, RDFS.range, XSD.gYear),
        ):
            self.assertIn(triple, skeleton)

    def test_a_graph_without_domains_or_ranges_gains_neither(self):
        skeleton = build_ontology_views(sparse_graph())["skeleton"]
        self.assertEqual(len(list(skeleton.triples((None, RDFS.domain, None)))), 0)
        self.assertEqual(len(list(skeleton.triples((None, RDFS.range, None)))), 0)

    def test_no_instance_assertion_reaches_the_skeleton(self):
        skeleton = build_ontology_views(declared_graph())["skeleton"]
        self.assertNotIn((ENTITY.ada, RELATION.knows, ENTITY.acme), skeleton)
        self.assertNotIn((ENTITY.ada, FACT.born, Literal("1815")), skeleton)


class ObservedUsageTest(unittest.TestCase):
    """Case 4: patterns are observations, and absence of data is not failure."""

    def test_schema_without_instances_observes_nothing(self):
        views = build_ontology_views(schema_only_graph())
        self.assertEqual(views["patterns"], [])
        self.assertEqual(len(views["skeleton"]), 4)

    def test_the_asserted_relation_is_observed_with_its_evidence(self):
        patterns = build_ontology_views(declared_graph())["patterns"]
        record = [p for p in patterns if p["predicate"] == RELATION.knows]
        self.assertEqual(len(record), 1)
        self.assertEqual(record[0]["subject_class"], CLASS.person)
        self.assertEqual(record[0]["range"], CLASS.organization)
        self.assertEqual(record[0]["range_kind"], "class")
        self.assertEqual(record[0]["occurrences"], 1)

    def test_an_observed_range_never_becomes_a_declared_range(self):
        views = build_ontology_views(sparse_graph())
        observed = {p["predicate"]: p["range"] for p in views["patterns"]}
        self.assertEqual(observed[EX.weight], XSD.integer)
        self.assertNotIn((EX.weight, RDFS.range, XSD.integer), views["skeleton"])
        self.assertEqual(len(list(views["skeleton"].triples((None, RDFS.range, None)))), 0)


class GenericIndividualTest(unittest.TestCase):
    """Case 5: a useful individual does not have to be an onto:Entity."""

    def test_a_foreign_individual_is_an_instance_and_is_observed(self):
        views = build_ontology_views(sparse_graph())
        self.assertIn((EX.widget1, RDF.type, EX.Widget), views["instance"])
        self.assertIn((EX.widget1, EX.madeIn, EX.berlin), views["instance"])
        classes = {p["subject_class"] for p in views["patterns"]}
        self.assertIn(EX.Widget, classes)

    def test_the_project_catalog_is_empty_where_the_views_are_not(self):
        source = sparse_graph()
        views = build_ontology_views(source)
        self.assertEqual(entity_catalog(source), [])
        self.assertGreater(len(views["instance"]), 0)
        self.assertGreater(len(views["patterns"]), 0)

    def test_an_unknown_object_range_stays_unknown(self):
        patterns = build_ontology_views(sparse_graph())["patterns"]
        record = [p for p in patterns if p["predicate"] == EX.madeIn]
        self.assertEqual(len(record), 1)
        self.assertEqual(record[0]["range_kind"], "unknown")
        self.assertIsNone(record[0]["range"])


class SupportTest(unittest.TestCase):
    """Case 6: ontology metadata and shapes stay in the remainder."""

    def test_ontology_metadata_is_support_and_not_schema(self):
        views = build_ontology_views(declared_graph())
        self.assertIn((ONTO.ontology, RDF.type, OWL.Ontology), views["support"])
        self.assertNotIn((ONTO.ontology, RDF.type, OWL.Ontology), views["schema"])

    def test_the_repository_remainder_holds_its_shape(self):
        views = build_ontology_views(repository_graph())
        self.assertGreater(len(list(views["support"].triples((None, SH.path, None)))), 0)


class BindingTest(unittest.TestCase):
    """Case 7: every derived graph can still be read with prefixes."""

    def test_the_project_prefixes_survive_on_all_four_graphs(self):
        views = build_ontology_views(declared_graph())
        for field in ("schema", "instance", "support", "skeleton"):
            bound = {prefix for prefix, _ in views[field].namespaces()}
            for prefix in ("onto", "entity", "class", "relation", "fact", "skos"):
                self.assertIn(prefix, bound, field)

    def test_a_foreign_prefix_survives_too(self):
        views = build_ontology_views(sparse_graph())
        for field in ("schema", "instance", "support", "skeleton"):
            self.assertIn("ex", {prefix for prefix, _ in views[field].namespaces()})

    def test_a_selected_uri_can_be_shortened_for_rendering(self):
        views = build_ontology_views(declared_graph())
        manager = views["skeleton"].namespace_manager
        self.assertEqual(manager.normalizeUri(CLASS.person), "class:person")


class ImmutabilityTest(unittest.TestCase):
    """Case 8: building views never touches the graph it was given."""

    def check(self, source):
        triples = set(source)
        namespaces = set(source.namespaces())
        build_ontology_views(source)
        self.assertEqual(set(source), triples)
        self.assertEqual(set(source.namespaces()), namespaces)

    def test_the_schema_rich_graph_is_unchanged(self):
        self.check(declared_graph())

    def test_the_sparse_graph_is_unchanged(self):
        self.check(sparse_graph())

    def test_the_repository_graph_is_unchanged(self):
        original = GRAPH_PATH.read_bytes()
        self.check(repository_graph())
        self.assertEqual(GRAPH_PATH.read_bytes(), original)

    def test_editing_a_derived_view_does_not_reach_the_source(self):
        source = declared_graph()
        triples = set(source)
        views = build_ontology_views(source)
        views["skeleton"].add((EX.Invented, RDF.type, OWL.Class))
        views["instance"].remove((ENTITY.ada, FACT.born, Literal("1815")))
        self.assertEqual(set(source), triples)


if __name__ == "__main__":
    unittest.main()
