"""migrate_prefixes.py moves an old dataset to the src:/trace: prefixes."""

import hashlib
import importlib.util
import io
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import PROV, RDF, RDFS

from text_to_ontology.graph_management import (
    ENTITY, RELATION, SRC, TRACE, is_tracing,
)
from text_to_ontology.graph_store import GraphNames, RdflibGraphStore
from text_to_ontology.publication_sources import statement_uri

ROOT = Path(__file__).resolve().parents[1]

# A miniature dataset in the old layout: everything directly under onto:.
OLD = """
@prefix onto: <http://example.org/text-ontology/> .
@prefix entity: <http://example.org/text-ontology/entity/> .
@prefix relation: <http://example.org/text-ontology/relation/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

onto:graphs/schema {
    relation:works-for a owl:ObjectProperty .
}
onto:graphs/data {
    entity:alice a onto:Entity ; relation:works-for entity:acme .
    entity:acme a onto:Entity .
}
onto:graphs/provenance {
    onto:document/doc-1 a prov:Entity ; rdfs:label "a.md" ;
        onto:sourceFile onto:source-file/f1 .
    onto:source-file/f1 a prov:Entity ; rdfs:label "a.md" ;
        onto:sourcePath "notes/a.md" .
    entity:alice onto:sourceDocument onto:document/doc-1 ;
        onto:sourceFile onto:source-file/f1 .
    onto:statement/s1 a rdf:Statement, prov:Entity ;
        rdf:subject entity:alice ; rdf:predicate relation:works-for ;
        rdf:object entity:acme ;
        prov:wasDerivedFrom onto:document/doc-1 ;
        onto:sourceFile onto:source-file/f1 .
    onto:candidate/doc-1/win-1/entity/0 a prov:Collection ;
        prov:wasGeneratedBy onto:activity/act-1 .
    onto:activity/act-1 a prov:Activity .
}
onto:graphs/review {
    onto:review/doc-1/abc a prov:Collection ;
        prov:wasDerivedFrom onto:document/doc-1 .
}
"""
# Turtle names cannot contain "/": write those IRIs out in full.
OLD = re.sub(r"onto:([\w-]+/[\w/-]+)",
             r"<http://example.org/text-ontology/\1>", OLD)


def load_script():
    spec = importlib.util.spec_from_file_location(
        "migrate_prefixes", ROOT / "migrate_prefixes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrateTest(unittest.TestCase):
    def migrate(self, *extra):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "old.trig"
            new = Path(folder) / "new.trig"
            old.write_text(OLD, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                load_script().main([str(old), str(new), *extra])
            store = RdflibGraphStore(new)
            return {name: store.get(name) for name in store.graph_names()}

    def test_source_links_land_in_the_data_graph(self):
        graphs = self.migrate()
        data = graphs[GraphNames().target_graph]
        file = SRC["file/" + hashlib.sha256(b"notes/a.md").hexdigest()]
        self.assertIn((ENTITY.alice, SRC.fromFile, file), data)
        self.assertIn((file, SRC.path, Literal("notes/a.md")), data)
        self.assertIn((file, RDFS.label, Literal("a.md")), data)
        node = statement_uri((ENTITY.alice, RELATION["works-for"],
                              ENTITY.acme))
        self.assertIn((node, SRC.fromFile, file), data)

    def test_tracing_moves_under_trace_and_candidates_are_dropped(self):
        graphs = self.migrate()
        names = GraphNames()
        provenance = graphs[names.provenance_graph]
        self.assertIn((TRACE["document/doc-1"], RDF.type, PROV.Entity),
                      provenance)
        self.assertIn((ENTITY.alice, TRACE.sourceDocument,
                       TRACE["document/doc-1"]), provenance)
        self.assertFalse(any("candidate/" in str(s) or "activity/" in str(s)
                             for s in provenance.subjects()))
        for name, graph in graphs.items():
            for triple in graph:
                if str(triple[1]).startswith(str(PROV)):
                    self.assertTrue(is_tracing(triple), triple)
        review = graphs[names.review_graph]
        self.assertIn((TRACE["review/doc-1/abc"], RDF.type, PROV.Collection),
                      review)

    def test_keep_candidates_keeps_them_under_trace(self):
        provenance = self.migrate("--keep-candidates")[
            GraphNames().provenance_graph]
        self.assertIn((TRACE["candidate/doc-1/win-1/entity/0"],
                       PROV.wasGeneratedBy, TRACE["activity/act-1"]),
                      provenance)


if __name__ == "__main__":
    unittest.main()
