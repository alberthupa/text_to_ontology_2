"""Proposal 2: splitting one source graph into schema, instance, and support."""

import subprocess
import unittest
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD

from graph_management import CLASS, ENTITY, FACT, ONTO, RELATION, bind
from graph_partition import partition_graph


REPOSITORY = Path(__file__).resolve().parent.parent
GRAPH_PATH = REPOSITORY / "ontology.ttl"
EX = Namespace("http://example.com/other/")


def small_graph():
    """One class, one property, one individual, one shape, one ontology."""
    graph = Graph()
    bind(graph)
    graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
    graph.add((ONTO.Entity, RDF.type, OWL.Class))
    graph.add((ONTO.Entity, RDFS.label, Literal("Entity")))
    graph.add((CLASS.person, RDF.type, OWL.Class))
    graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
    graph.add((CLASS.person, RDFS.label, Literal("Person")))
    graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
    graph.add((RELATION.knows, RDFS.label, Literal("knows")))
    graph.add((ENTITY.ada, RDF.type, OWL.NamedIndividual))
    graph.add((ENTITY.ada, RDF.type, CLASS.person))
    graph.add((ENTITY.ada, RDFS.label, Literal("Ada")))
    return graph


class DeclarationTest(unittest.TestCase):
    """Case 1: explicit class and property declarations are schema."""

    def test_class_and_property_declarations_are_schema(self):
        schema, instance, support = partition_graph(small_graph())
        for triple in (
            (ONTO.Entity, RDF.type, OWL.Class),
            (CLASS.person, RDF.type, OWL.Class),
            (RELATION.knows, RDF.type, OWL.ObjectProperty),
        ):
            self.assertIn(triple, schema)
            self.assertNotIn(triple, instance)
            self.assertNotIn(triple, support)

    def test_rdfs_class_and_datatype_property_are_schema(self):
        graph = Graph()
        graph.add((EX.Thing, RDF.type, RDFS.Class))
        graph.add((FACT.height, RDF.type, OWL.DatatypeProperty))
        schema, _, _ = partition_graph(graph)
        self.assertEqual(len(schema), 2)


class AxiomTest(unittest.TestCase):
    """Case 2: subclass, domain, and range axioms are schema."""

    def test_subclass_domain_and_range_are_schema(self):
        graph = Graph()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDFS.subClassOf, ONTO.Entity))
        graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
        graph.add((RELATION.knows, RDFS.domain, CLASS.person))
        graph.add((RELATION.knows, RDFS.range, CLASS.person))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(schema), 5)
        self.assertEqual(len(instance), 0)
        self.assertEqual(len(support), 0)

    def test_a_class_named_only_as_a_range_is_still_a_schema_resource(self):
        graph = Graph()
        graph.add((RELATION.knows, RDF.type, OWL.ObjectProperty))
        graph.add((RELATION.knows, RDFS.range, CLASS.person))
        graph.add((CLASS.person, RDFS.label, Literal("Person")))
        schema, _, _ = partition_graph(graph)
        self.assertIn((CLASS.person, RDFS.label, Literal("Person")), schema)


class AnnotationRoleTest(unittest.TestCase):
    """Case 3 and 6: labels and definitions follow the role of the subject."""

    def test_schema_labels_are_schema_and_instance_labels_are_instance(self):
        schema, instance, _ = partition_graph(small_graph())
        self.assertIn((CLASS.person, RDFS.label, Literal("Person")), schema)
        self.assertIn((ENTITY.ada, RDFS.label, Literal("Ada")), instance)

    def test_instance_aliases_descriptions_and_kind_stay_instance(self):
        graph = Graph()
        graph.add((ENTITY.ada, RDF.type, OWL.NamedIndividual))
        graph.add((ENTITY.ada, SKOS.prefLabel, Literal("Ada")))
        graph.add((ENTITY.ada, SKOS.altLabel, Literal("Lovelace")))
        graph.add((ENTITY.ada, RDFS.comment, Literal("A person")))
        graph.add((ENTITY.ada, ONTO.kind, Literal("Person")))
        _, instance, _ = partition_graph(graph)
        self.assertEqual(len(instance), 5)

    def test_schema_definitions_are_schema(self):
        graph = Graph()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, SKOS.prefLabel, Literal("Person")))
        graph.add((CLASS.person, SKOS.definition, Literal("A human being")))
        graph.add((CLASS.person, RDFS.comment, Literal("A human being")))
        schema, instance, _ = partition_graph(graph)
        self.assertEqual(len(schema), 4)
        self.assertEqual(len(instance), 0)


class InstanceTest(unittest.TestCase):
    """Cases 4 and 5: individual types and property assertions are instance."""

    def test_individual_type_statements_are_instance(self):
        _, instance, _ = partition_graph(small_graph())
        self.assertIn((ENTITY.ada, RDF.type, OWL.NamedIndividual), instance)
        self.assertIn((ENTITY.ada, RDF.type, CLASS.person), instance)

    def test_object_and_datatype_assertions_are_instance(self):
        graph = small_graph()
        graph.add((ENTITY.grace, RDF.type, CLASS.person))
        graph.add((ENTITY.ada, RELATION.knows, ENTITY.grace))
        graph.add((ENTITY.ada, FACT.born, Literal("1815")))
        _, instance, _ = partition_graph(graph)
        self.assertIn((ENTITY.ada, RELATION.knows, ENTITY.grace), instance)
        self.assertIn((ENTITY.ada, FACT.born, Literal("1815")), instance)

    def test_a_skos_concept_that_is_not_a_schema_resource_is_instance(self):
        graph = Graph()
        graph.add((ENTITY.ada, RDF.type, SKOS.Concept))
        graph.add((ENTITY.ada, SKOS.prefLabel, Literal("Ada")))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(instance), 2)
        self.assertEqual(len(schema), 0)
        self.assertEqual(len(support), 0)


class SupportTest(unittest.TestCase):
    """Case 7: ontology metadata and whole SHACL structures are support."""

    def test_ontology_declaration_is_support(self):
        _, _, support = partition_graph(small_graph())
        self.assertIn((ONTO.ontology, RDF.type, OWL.Ontology), support)

    def test_the_complete_shacl_structure_is_support(self):
        graph = Graph()
        rule = BNode()
        graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
        graph.add((ONTO.EntityShape, SH.targetClass, ONTO.Entity))
        graph.add((ONTO.EntityShape, SH.property, rule))
        graph.add((rule, SH.path, SKOS.prefLabel))
        graph.add((rule, SH.minCount, Literal(1)))
        graph.add((ONTO.Entity, RDF.type, OWL.Class))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(support), 5)
        self.assertEqual(len(schema), 1)
        self.assertEqual(len(instance), 0)

    def test_ontology_annotations_are_support(self):
        graph = Graph()
        graph.add((ONTO.ontology, RDF.type, OWL.Ontology))
        graph.add((ONTO.ontology, RDFS.label, Literal("The ontology")))
        _, _, support = partition_graph(graph)
        self.assertEqual(len(support), 2)


class RestrictionTest(unittest.TestCase):
    """Case 8: a recognized restriction is schema whatever the skeleton keeps."""

    def test_a_value_restriction_is_schema_as_a_whole_structure(self):
        graph = Graph()
        restriction = BNode()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDFS.subClassOf, restriction))
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, RELATION.knows))
        graph.add((restriction, OWL.someValuesFrom, CLASS.person))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(schema), 5)
        self.assertEqual(len(instance), 0)
        self.assertEqual(len(support), 0)

    def test_a_qualified_cardinality_restriction_is_still_schema(self):
        graph = Graph()
        restriction = BNode()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDFS.subClassOf, restriction))
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, RELATION.knows))
        graph.add((restriction, OWL.onClass, CLASS.person))
        graph.add((
            restriction, OWL.qualifiedCardinality, Literal(1, datatype=XSD.nonNegativeInteger)
        ))
        schema, _, _ = partition_graph(graph)
        self.assertEqual(len(schema), 6)

    def test_the_property_a_restriction_names_becomes_a_schema_resource(self):
        graph = Graph()
        restriction = BNode()
        graph.add((CLASS.person, RDFS.subClassOf, restriction))
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, RELATION.knows))
        graph.add((RELATION.knows, RDFS.label, Literal("knows")))
        schema, _, _ = partition_graph(graph)
        self.assertIn((RELATION.knows, RDFS.label, Literal("knows")), schema)


class RemainderTest(unittest.TestCase):
    """Case 9: an unrecognized statement is not guessed into schema."""

    def test_an_unknown_statement_lands_in_the_remainder(self):
        graph = Graph()
        graph.add((EX.thing, EX.relates, EX.other))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(schema), 0)
        self.assertEqual(len(instance), 0)
        self.assertIn((EX.thing, EX.relates, EX.other), support)

    def test_an_unrecognized_blank_node_expression_stays_whole_in_remainder(self):
        graph = Graph()
        expression = BNode()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, OWL.equivalentClass, expression))
        graph.add((expression, OWL.unionOf, BNode()))
        schema, _, support = partition_graph(graph)
        self.assertEqual(len(schema), 1)
        self.assertEqual(len(support), 2)

    def test_an_orphan_annotation_lands_in_the_remainder(self):
        graph = Graph()
        graph.add((EX.mystery, RDFS.label, Literal("Mystery")))
        _, _, support = partition_graph(graph)
        self.assertEqual(len(support), 1)


class DualRoleTest(unittest.TestCase):
    """Decision gate 1: a resource may play more than one role."""

    def test_declaration_and_individual_assertions_split_by_triple(self):
        graph = Graph()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDF.type, OWL.NamedIndividual))
        graph.add((CLASS.person, ONTO.kind, Literal("Class")))
        schema, instance, support = partition_graph(graph)
        self.assertIn((CLASS.person, RDF.type, OWL.Class), schema)
        self.assertIn((CLASS.person, RDF.type, OWL.NamedIndividual), instance)
        self.assertIn((CLASS.person, ONTO.kind, Literal("Class")), instance)
        self.assertEqual(len(support), 0)

    def test_annotations_on_a_dual_role_resource_follow_the_schema_role(self):
        graph = Graph()
        graph.add((CLASS.person, RDF.type, OWL.Class))
        graph.add((CLASS.person, RDF.type, OWL.NamedIndividual))
        graph.add((CLASS.person, RDFS.label, Literal("Person")))
        schema, instance, _ = partition_graph(graph)
        self.assertIn((CLASS.person, RDFS.label, Literal("Person")), schema)
        self.assertNotIn((CLASS.person, RDFS.label, Literal("Person")), instance)

    def test_a_support_resource_outranks_its_schema_role(self):
        graph = Graph()
        graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
        graph.add((ONTO.EntityShape, RDF.type, OWL.Class))
        graph.add((ONTO.EntityShape, RDFS.label, Literal("Entity shape")))
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(support), 3)
        self.assertEqual(len(schema), 0)
        self.assertEqual(len(instance), 0)


class BindingTest(unittest.TestCase):
    """Case 10: every derived view keeps the source prefixes."""

    def test_all_three_views_keep_the_source_bindings(self):
        for view in partition_graph(small_graph()):
            bound = {prefix for prefix, _ in view.namespaces()}
            for prefix in ("onto", "entity", "class", "relation", "fact", "skos"):
                self.assertIn(prefix, bound)


class InvariantTest(unittest.TestCase):
    """Cases 11 and 12: the partition is disjoint, exhaustive, and read only."""

    def check(self, graph):
        before = set(graph)
        schema, instance, support = partition_graph(graph)
        parts = [set(schema), set(instance), set(support)]
        self.assertEqual(parts[0] & parts[1], set())
        self.assertEqual(parts[0] & parts[2], set())
        self.assertEqual(parts[1] & parts[2], set())
        self.assertEqual(parts[0] | parts[1] | parts[2], before)
        self.assertEqual(len(schema) + len(instance) + len(support), len(before))
        self.assertEqual(set(graph), before)

    def test_the_small_graph_is_partitioned_losslessly(self):
        self.check(small_graph())

    def test_an_empty_graph_is_partitioned_losslessly(self):
        self.check(Graph())

    def test_a_mixed_graph_is_partitioned_losslessly(self):
        graph = small_graph()
        restriction = BNode()
        rule = BNode()
        graph.add((CLASS.person, RDFS.subClassOf, restriction))
        graph.add((restriction, RDF.type, OWL.Restriction))
        graph.add((restriction, OWL.onProperty, RELATION.knows))
        graph.add((restriction, OWL.allValuesFrom, CLASS.person))
        graph.add((ONTO.EntityShape, RDF.type, SH.NodeShape))
        graph.add((ONTO.EntityShape, SH.property, rule))
        graph.add((rule, SH.path, SKOS.prefLabel))
        graph.add((ENTITY.ada, RELATION.knows, ENTITY.grace))
        graph.add((ENTITY.ada, FACT.born, Literal("1815")))
        graph.add((EX.mystery, EX.strange, Literal("?")))
        self.check(graph)

    def test_the_repository_graph_is_partitioned_losslessly(self):
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        self.check(graph)


class RepositoryGraphTest(unittest.TestCase):
    """Case 13: the repository graph is only ever read."""

    def test_partitioning_leaves_the_working_tree_file_untouched(self):
        original = GRAPH_PATH.read_bytes()
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        before = set(graph)
        partition_graph(graph)
        self.assertEqual(set(graph), before)
        self.assertEqual(GRAPH_PATH.read_bytes(), original)
        diff = subprocess.run(
            ["git", "diff", "--", "ontology.ttl"],
            cwd=REPOSITORY, capture_output=True, text=True,
        )
        self.assertEqual(diff.stdout, "")

    def test_the_repository_graph_splits_into_the_expected_sizes(self):
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        schema, instance, support = partition_graph(graph)
        self.assertEqual(len(graph), 169)
        self.assertEqual(len(schema), 43)
        self.assertEqual(len(instance), 120)
        self.assertEqual(len(support), 6)

    def test_the_repository_remainder_is_only_the_ontology_and_the_shape(self):
        graph = Graph()
        graph.parse(GRAPH_PATH, format="turtle")
        _, _, support = partition_graph(graph)
        subjects = {s for s, _, _ in support if isinstance(s, URIRef)}
        self.assertEqual(subjects, {ONTO.ontology, ONTO.EntityShape})


if __name__ == "__main__":
    unittest.main()
