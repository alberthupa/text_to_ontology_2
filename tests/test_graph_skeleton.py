"""Proposal 2: copying the explicit structural core out of a schema graph."""

import unittest
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

from graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from graph_partition import partition_graph
from graph_skeleton import create_graph_skeleton


REPOSITORY = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPOSITORY / "ontology.ttl"
EX = Namespace("http://example.com/other/")


def core_graph():
    """The supported non-restriction core, in one small schema graph."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.person, RDFS.label, Literal("Person")))
    graph.add((CLASS.person, RDFS.comment, Literal("A human being")))
    graph.add((CLASS.person, SKOS.prefLabel, Literal("Person")))
    graph.add((CLASS.person, SKOS.altLabel, Literal("Human")))
    graph.add((CLASS.person, SKOS.definition, Literal("Somebody")))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.domain, CLASS.person))
    graph.add((RELATION.knows, RDFS.range, CLASS.person))
    graph.add((RELATION.knows, RDFS.label, Literal("knows")))
    graph.add((FACT.born, RDF.type, OWL.DatatypeProperty))
    graph.add((FACT.born, RDFS.range, XSD.gYear))
    graph.add((FACT.born, RDFS.label, Literal("born")))
    return graph


def restricted_graph(*constraint):
    """A class carrying one blank-node restriction through rdfs:subClassOf."""
    graph = Graph()
    node = BNode()
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.subClassOf, node))
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, RELATION.knows))
    for predicate, target in zip(constraint[::2], constraint[1::2]):
        graph.add((node, predicate, target))
    return graph, node


class CoreTest(unittest.TestCase):
    """Case 1: the approved declarations, axioms, and naming survive."""

    def test_the_whole_supported_core_is_retained(self):
        source = core_graph()
        skeleton = create_graph_skeleton(source)
        self.assertEqual(set(skeleton), set(source))

    def test_declarations_hierarchy_domain_and_range_are_retained(self):
        skeleton = create_graph_skeleton(core_graph())
        for triple in (
            (CLASS.person, RDF.type, OWL.Class),
            (CLASS.person, RDFS.subClassOf, ONTO.Entity),
            (RELATION.knows, RDF.type, OWL.ObjectProperty),
            (RELATION.knows, RDFS.domain, CLASS.person),
            (RELATION.knows, RDFS.range, CLASS.person),
            (FACT.born, RDF.type, OWL.DatatypeProperty),
            (FACT.born, RDFS.range, XSD.gYear),
        ):
            self.assertIn(triple, skeleton)

    def test_labels_comments_and_skos_naming_are_retained(self):
        skeleton = create_graph_skeleton(core_graph())
        for predicate, value in (
            (RDFS.label, Literal("Person")),
            (RDFS.comment, Literal("A human being")),
            (SKOS.prefLabel, Literal("Person")),
            (SKOS.altLabel, Literal("Human")),
            (SKOS.definition, Literal("Somebody")),
        ):
            self.assertIn((CLASS.person, predicate, value), skeleton)


class ExclusionTest(unittest.TestCase):
    """Cases 2, 3, and 4: instances and support material never appear."""

    def polluted(self):
        graph = core_graph()
        rule = BNode()
        graph.add((ENTITY.ada, RDF.type, OWL.NamedIndividual))
        graph.add((ENTITY.ada, RDF.type, CLASS.person))
        graph.add((ENTITY.ada, RDFS.label, Literal("Ada")))
        graph.add((ENTITY.ada, SKOS.prefLabel, Literal("Ada")))
        graph.add((ENTITY.ada, ONTO.kind, Literal("Person")))
        graph.add((ENTITY.ada, RELATION.knows, ENTITY.grace))
        graph.add((ENTITY.ada, FACT.born, Literal("1815")))
        graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
        graph.add((ONTO.ontology, RDFS.label, Literal("The ontology")))
        graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
        graph.add((ONTO.EntityShape, SH.property, rule))
        graph.add((rule, SH.path, SKOS.prefLabel))
        return graph

    def test_individuals_and_their_annotations_are_absent(self):
        skeleton = create_graph_skeleton(self.polluted())
        self.assertEqual(len(list(skeleton.triples((ENTITY.ada, None, None)))), 0)

    def test_instance_relations_and_literal_values_are_absent(self):
        skeleton = create_graph_skeleton(self.polluted())
        self.assertNotIn((ENTITY.ada, RELATION.knows, ENTITY.grace), skeleton)
        self.assertNotIn((ENTITY.ada, FACT.born, Literal("1815")), skeleton)

    def test_ontology_metadata_and_shacl_structures_are_absent(self):
        skeleton = create_graph_skeleton(self.polluted())
        self.assertNotIn((ONTO.ontology, RDF.type, OWL.Ontology), skeleton)
        self.assertNotIn((ONTO.ontology, RDFS.label, Literal("The ontology")), skeleton)
        self.assertEqual(len(list(skeleton.triples((None, SH.path, None)))), 0)

    def test_the_polluted_graph_still_yields_exactly_the_core(self):
        skeleton = create_graph_skeleton(self.polluted())
        self.assertEqual(set(skeleton), set(core_graph()))


class SupportedRestrictionTest(unittest.TestCase):
    """Case 5, per decision gate 2: the approved forms copy whole."""

    def check_copied(self, *constraint):
        source, node = restricted_graph(*constraint)
        skeleton = create_graph_skeleton(source)
        self.assertIn((CLASS.person, RDFS.subClassOf, node), skeleton)
        self.assertIn((node, RDF.type, OWL.Restriction), skeleton)
        self.assertIn((node, OWL.onProperty, RELATION.knows), skeleton)
        self.assertEqual(len(list(skeleton.triples((node, None, None)))), 3)

    def test_some_values_from_is_copied(self):
        self.check_copied(OWL.someValuesFrom, CLASS.person)

    def test_all_values_from_is_copied(self):
        self.check_copied(OWL.allValuesFrom, CLASS.person)

    def test_has_value_is_copied(self):
        self.check_copied(OWL.hasValue, ENTITY.ada)

    def test_unqualified_cardinalities_are_copied(self):
        one = Literal(1, datatype=XSD.nonNegativeInteger)
        self.check_copied(OWL.cardinality, one)
        self.check_copied(OWL.minCardinality, one)
        self.check_copied(OWL.maxCardinality, one)

    def test_the_named_filler_and_property_keep_their_declarations(self):
        source, _ = restricted_graph(OWL.someValuesFrom, CLASS.person)
        source.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
        source.add((RELATION.knows, RDFS.label, Literal("knows")))
        skeleton = create_graph_skeleton(source)
        self.assertIn((RELATION.knows, RDF.type, OWL.ObjectProperty), skeleton)
        self.assertIn((RELATION.knows, RDFS.label, Literal("knows")), skeleton)


class UnsupportedRestrictionTest(unittest.TestCase):
    """Case 6: an unsupported or incomplete restriction is omitted whole."""

    def check_omitted(self, *constraint):
        source, node = restricted_graph(*constraint)
        skeleton = create_graph_skeleton(source)
        self.assertNotIn((CLASS.person, RDFS.subClassOf, node), skeleton)
        self.assertEqual(len(list(skeleton.triples((node, None, None)))), 0)
        self.assertEqual(set(skeleton), {(CLASS.person, RDF.type, OWL.Class)})

    def test_a_qualified_cardinality_is_omitted_whole(self):
        self.check_omitted(
            OWL.qualifiedCardinality, Literal(1, datatype=XSD.nonNegativeInteger),
            OWL.onClass, CLASS.person,
        )

    def test_a_restriction_without_a_constraint_is_omitted_whole(self):
        self.check_omitted()

    def test_a_restriction_carrying_an_extra_predicate_is_omitted_whole(self):
        self.check_omitted(OWL.someValuesFrom, CLASS.person, EX.weight, Literal(3))

    def test_a_restriction_with_two_constraints_is_omitted_whole(self):
        self.check_omitted(
            OWL.someValuesFrom, CLASS.person, OWL.allValuesFrom, CLASS.person,
        )

    def test_a_blank_node_filler_is_omitted_whole(self):
        self.check_omitted(OWL.someValuesFrom, BNode())

    def test_a_restriction_without_a_type_is_omitted_whole(self):
        graph = Graph()
        node = BNode()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDFS.subClassOf, node))
        graph.add((node, OWL.onProperty, RELATION.knows))
        graph.add((node, OWL.someValuesFrom, CLASS.person))
        skeleton = create_graph_skeleton(graph)
        self.assertEqual(set(skeleton), {(CLASS.person, RDF.type, OWL.Class)})

    def test_a_boolean_class_expression_is_omitted_whole(self):
        graph = Graph()
        node = BNode()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, OWL.equivalentClass, node))
        graph.add((node, OWL.unionOf, BNode()))
        skeleton = create_graph_skeleton(graph)
        self.assertEqual(set(skeleton), {(CLASS.person, RDF.type, OWL.Class)})


class ReferencedResourceTest(unittest.TestCase):
    """Case 7: a resource a retained axiom names keeps its own naming."""

    def test_a_superclass_keeps_its_declaration_and_naming(self):
        graph = Graph()
        graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
        graph.add((ONTO.Entity, RDF.type, OWL.Class))
        graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))
        graph.add((ONTO.Entity, SKOS.definition, Literal("Anything named")))
        skeleton = create_graph_skeleton(graph)
        self.assertEqual(len(skeleton), 4)

    def test_unrelated_statements_about_a_referenced_resource_are_not_copied(self):
        graph = Graph()
        graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
        graph.add((ONTO.Entity, RDF.type, OWL.Class))
        graph.add((ONTO.Entity, EX.curator, Literal("Albert")))
        skeleton = create_graph_skeleton(graph)
        self.assertNotIn((ONTO.Entity, EX.curator, Literal("Albert")), skeleton)
        self.assertEqual(len(skeleton), 2)


class NoInferenceTest(unittest.TestCase):
    """Case 8: nothing is materialized that the source did not state."""

    def test_a_property_without_a_declared_domain_does_not_gain_one(self):
        graph = Graph()
        graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
        skeleton = create_graph_skeleton(graph)
        self.assertEqual(len(list(skeleton.triples((None, RDFS.domain, None)))), 0)
        self.assertEqual(len(list(skeleton.triples((None, RDFS.range, None)))), 0)

    def test_no_transitive_subclass_triple_is_added(self):
        graph = Graph()
        graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
        graph.add((EX.Scientist, RDFS.subClassOf, CLASS.person))
        skeleton = create_graph_skeleton(graph)
        self.assertNotIn((EX.Scientist, RDFS.subClassOf, ONTO.Entity), skeleton)

    def test_a_class_used_as_a_range_does_not_gain_a_declaration(self):
        graph = Graph()
        graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
        graph.add((RELATION.knows, RDFS.range, CLASS.person))
        skeleton = create_graph_skeleton(graph)
        self.assertNotIn((CLASS.person, RDF.type, OWL.Class), skeleton)

    def test_the_skeleton_is_always_a_subset_of_its_input(self):
        for source in (core_graph(), ExclusionTest().polluted()):
            self.assertTrue(set(create_graph_skeleton(source)) <= set(source))


class BindingTest(unittest.TestCase):
    """Case 9: prefixes survive."""

    def test_source_bindings_are_kept(self):
        skeleton = create_graph_skeleton(core_graph())
        bound = {prefix for prefix, _ in skeleton.namespaces()}
        for prefix in ("onto", "class", "relation", "fact", "skos"):
            self.assertIn(prefix, bound)


class ImmutabilityTest(unittest.TestCase):
    """Case 10: the schema graph handed in comes back untouched."""

    def test_the_schema_input_is_unchanged(self):
        source = ExclusionTest().polluted()
        before = set(source)
        create_graph_skeleton(source)
        self.assertEqual(set(source), before)

    def test_the_repository_schema_view_is_unchanged(self):
        original = GRAPH_PATH.read_bytes()
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        schema, _, _ = partition_graph(graph)
        before = set(schema)
        create_graph_skeleton(schema)
        self.assertEqual(set(schema), before)
        self.assertEqual(GRAPH_PATH.read_bytes(), original)


class RepositoryGraphTest(unittest.TestCase):
    """The current graph has no restrictions, so its skeleton is its schema."""

    def test_the_current_skeleton_equals_the_current_schema_view(self):
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        schema, _, _ = partition_graph(graph)
        skeleton = create_graph_skeleton(schema)
        self.assertEqual(len(skeleton), 43)
        self.assertEqual(set(skeleton), set(schema))


if __name__ == "__main__":
    unittest.main()
