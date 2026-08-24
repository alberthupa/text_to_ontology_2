"""M6: SHACL validation of a complete source graph."""

import unittest
from pathlib import Path

from rdflib import Graph
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, SH

from text_to_ontology.source_validation import (
    combine_shape_graphs,
    embedded_shape_graph,
    validate_source_graph,
)


FIXTURES = Path(__file__).parent / "fixtures" / "shacl"


def loaded(name):
    graph = Graph()
    graph.parse(FIXTURES / name, format="turtle")
    return graph


class ShapeCombinationTest(unittest.TestCase):
    def test_every_configured_shape_graph_is_combined(self):
        label = loaded("label_shape.ttl")
        founded = loaded("founded_year_shape.ttl")
        combined, count = combine_shape_graphs((label, founded))
        self.assertEqual(count, 2)
        self.assertEqual(len(combined), len(label) + len(founded))

    def test_embedded_shapes_are_copied_without_domain_data(self):
        combined = loaded("label_shape.ttl")
        data = loaded("valid_source.ttl")
        for triple in data:
            combined.add(triple)
        shapes = embedded_shape_graph(combined)
        self.assertTrue(any(shapes.subjects(RDF.type, SH.NodeShape)))
        for triple in data:
            self.assertNotIn(triple, shapes)


class SourceValidationTest(unittest.TestCase):
    def setUp(self):
        self.shapes = (loaded("label_shape.ttl"),
                       loaded("founded_year_shape.ttl"))

    def test_valid_data_conforms_to_constraints_from_both_graphs(self):
        result = validate_source_graph(loaded("valid_source.ttl"), self.shapes)
        self.assertTrue(result.conforms)
        self.assertEqual(result.shape_graphs_checked, 2)
        self.assertIn((None, RDF.type, SH.ValidationReport),
                      result.report_graph)

    def test_a_missing_required_label_is_reported(self):
        result = validate_source_graph(loaded("missing_label.ttl"), self.shapes)
        self.assertFalse(result.conforms)
        paths = set(result.report_graph.objects(None, SH.resultPath))
        self.assertIn(next(iter(self.shapes[0].objects(None, SH.path))), paths)

    def test_a_datatype_mismatch_is_reported(self):
        result = validate_source_graph(
            loaded("datatype_mismatch.ttl"), self.shapes)
        self.assertFalse(result.conforms)
        self.assertTrue(list(result.report_graph.objects(None, SH.sourceConstraintComponent)))

    def test_validation_does_not_mutate_data_or_shape_graphs(self):
        data = loaded("valid_source.ttl")
        before_data = Graph()
        for triple in data:
            before_data.add(triple)
        before_shapes = [Graph() for _ in self.shapes]
        for copy, graph in zip(before_shapes, self.shapes):
            for triple in graph:
                copy.add(triple)
        validate_source_graph(data, self.shapes)
        self.assertTrue(isomorphic(data, before_data))
        for graph, copy in zip(self.shapes, before_shapes):
            self.assertTrue(isomorphic(graph, copy))


if __name__ == "__main__":
    unittest.main()
