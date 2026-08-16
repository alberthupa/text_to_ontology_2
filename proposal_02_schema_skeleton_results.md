# Proposal 02: Schema Skeleton and Pattern Results

What was actually built and measured for
[`proposal_02_schema_skeleton_and_patterns.md`](proposal_02_schema_skeleton_and_patterns.md).
Every number below comes from a real run against a read-only load of the
repository graph, not from the characterization hypotheses in the handoff.

## Environment

```text
python  3.12.3
rdflib  7.6.0
branch  proposal-02/skeleton
```

No dependency was added. No network access or API key is needed by anything in
this proposal.

## Commands used

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python ontology.py --help
.venv/bin/python -m py_compile *.py tests/*.py
git diff --check
git status --short
git diff -- ontology.ttl
```

## What was added

Three read-only modules and their tests. Nothing else in the repository changed
except the README module list and this file.

```text
graph_partition.py   148 lines   partition_graph()
graph_skeleton.py    103 lines   create_graph_skeleton()
graph_patterns.py    138 lines   observed_relationships()

tests/test_graph_partition.py   30 tests
tests/test_graph_skeleton.py    29 tests
tests/test_graph_patterns.py    28 tests
```

The supporting functions are `owned_nodes`, `support_roles`,
`restriction_roles`, `schema_roles`, `instance_roles`, and `choose_view` in
`graph_partition.py`; `supported_restriction` and `structural_triples` in
`graph_skeleton.py`; and `eligible`, `ancestors`, `usable_classes`,
`subject_classes`, `object_ranges`, `class_populations`, and `pattern_record` in
`graph_patterns.py`.

None of the three modules imports another. `graph_patterns.py` imports `ONTO`
from `graph_management.py` for the one project predicate it excludes; that is
the only dependency on existing code.

## Running it on the real graph

Every command below is meant to be pasted into a terminal at the repository
root, and every one of them was run against the committed `ontology.ttl` to
produce the results recorded further down. They only read the file. There is no
CLI for these modules, by decision gate 7, so the entry points are called
directly.

### Partition the current graph

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph

graph = open_graph(Path("ontology.ttl"))
schema, instance, support = partition_graph(graph)
for name, view in (("source", graph), ("schema", schema),
                   ("instance", instance), ("support", support)):
    print(f"{name:<9}{len(view):>4}")
PY
```

```text
source     169
schema      43
instance   120
support      6
```

### Check the partition invariant on the real data

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph

graph = open_graph(Path("ontology.ttl"))
before = set(graph)
parts = [set(view) for view in partition_graph(graph)]
print("disjoint ", all(not (a & b) for i, a in enumerate(parts) for b in parts[i + 1:]))
print("lossless ", set().union(*parts) == before)
print("read only", set(graph) == before)
PY
```

```text
disjoint  True
lossless  True
read only True
```

### See what could not be classified

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph

_, _, support = partition_graph(open_graph(Path("ontology.ttl")))
print(support.serialize(format="turtle"), end="")
PY
```

```turtle
@prefix onto: <http://example.org/text-ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

onto:EntityShape a sh:NodeShape ;
    sh:property [ sh:minCount 1 ;
            sh:path skos:prefLabel ] ;
    sh:targetClass onto:Entity .

onto:ontology a owl:Ontology .
```

### Build and read the semantic skeleton

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph
from graph_skeleton import create_graph_skeleton

schema, _, _ = partition_graph(open_graph(Path("ontology.ttl")))
skeleton = create_graph_skeleton(schema)
print(len(skeleton), "triples; identical to the schema view:",
      set(skeleton) == set(schema))
print(skeleton.serialize(format="turtle"), end="")
PY
```

```text
43 triples; identical to the schema view: True
```

followed by the Turtle: three `class:*` declarations with their labels and
`rdfs:subClassOf onto:Entity`, the 16 property declarations with their labels,
and `onto:Entity a owl:Class`.

### Print the empirical pattern table

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph
from graph_patterns import observed_relationships

graph = open_graph(Path("ontology.ttl"))
schema, instance, _ = partition_graph(graph)
short = graph.namespace_manager.normalizeUri

for r in observed_relationships(schema, instance):
    subject = short(r["subject_class"]) if r["subject_class"] else "(unclassed)"
    range_ = short(r["range"]) if r["range"] else "(unknown)"
    cover = f"{r['coverage']:.2f}" if r["coverage"] is not None else "   -"
    print(f"{subject:<19}{short(r['predicate']):<36}{range_:<19}"
          f"n={r['occurrences']:<3}subj={r['distinct_subjects']:<3}"
          f"pop={r['class_population'] or '-':<3}cover={cover}"
          f"  card={r['cardinality_min']}/{r['cardinality_median']:g}"
          f"/{r['cardinality_max']}")
PY
```

```text
class:location     fact:advanced-chip-demand           xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:affects                        xsd:string         n=2  subj=2  pop=7  cover=0.29  card=1/1/1
class:location     fact:critical-minerals-position     xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:diplomatic-talks-purpose       xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:export-control-effect          xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:overcapacity-sectors           xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:policy-framing                 xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     fact:shapes                         xsd:string         n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     relation:affects                    class:location     n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     relation:affects                    class:organization n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     relation:competes-with              class:location     n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     relation:coordinates-with           class:organization n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:location     relation:restricts-chip-exports-to  class:location     n=1  subj=1  pop=7  cover=0.14  card=1/1/1
class:organization fact:gray-market-routing-case       xsd:string         n=1  subj=1  pop=3  cover=0.33  card=1/1/1
class:organization fact:ranks                          xsd:string         n=1  subj=1  pop=3  cover=0.33  card=1/1/1
class:organization relation:restricted-gpus-sought-by  class:location     n=1  subj=1  pop=3  cover=0.33  card=1/1/1
class:person       relation:planned-summit-with        class:person       n=1  subj=1  pop=2  cover=0.50  card=1/1/1
```

### Check the class populations behind the coverage column

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph
from graph_patterns import class_populations

graph = open_graph(Path("ontology.ttl"))
schema, instance, _ = partition_graph(graph)
short = graph.namespace_manager.normalizeUri
for class_, size in sorted(class_populations(schema, instance, {}).items(), key=str):
    print(f"{short(class_):<20}{size:>3}")
PY
```

```text
class:location        7
class:organization    3
class:person          2
```

### Do the same for any other Turtle file

Nothing is hardcoded to the repository graph. Pass a path as an argument:

```bash
.venv/bin/python - ontology.ttl <<'PY'
import sys
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph
from graph_skeleton import create_graph_skeleton
from graph_patterns import observed_relationships

graph = open_graph(Path(sys.argv[1]))
schema, instance, support = partition_graph(graph)
print(f"{len(graph)} triples = {len(schema)} schema"
      f" + {len(instance)} instance + {len(support)} support")
print(f"{len(create_graph_skeleton(schema))} triples in the skeleton")
print(f"{len(observed_relationships(schema, instance))} observed patterns")
PY
```

```text
169 triples = 43 schema + 120 instance + 6 support
43 triples in the skeleton
17 observed patterns
```

Run it from the repository root either way; the modules are imported by plain
name, so the working directory has to be on the import path.

### Write the views out to look at them in an editor

No module in this proposal serializes anything, and none of them will. This is
an ad-hoc inspection: it calls `rdflib`'s own `serialize()` on the derived views
and writes outside the repository, so `ontology.ttl` and the working tree are
untouched.

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from graph_management import open_graph
from graph_partition import partition_graph
from graph_skeleton import create_graph_skeleton

out = Path("/tmp/ontology-views")
out.mkdir(exist_ok=True)
schema, instance, support = partition_graph(open_graph(Path("ontology.ttl")))
for name, view in (("schema", schema), ("instance", instance),
                   ("support", support),
                   ("skeleton", create_graph_skeleton(schema))):
    view.serialize(out / f"{name}.ttl", format="turtle")
    print(f"{name:<9}{len(view):>4} triples -> {out / (name + '.ttl')}")
PY
```

```text
schema     43 triples -> /tmp/ontology-views/schema.ttl
instance  120 triples -> /tmp/ontology-views/instance.ttl
support     6 triples -> /tmp/ontology-views/support.ttl
skeleton   43 triples -> /tmp/ontology-views/skeleton.ttl
```

### Prove the graph file was never written

Take the checksum before running anything above, and compare it after:

```bash
sha256sum ontology.ttl
git diff -- ontology.ttl
git status --short
```

```text
632f6d870134819a8e4d651ba7af8b2deddbcd4605b46c057f845c7aa3fe49b1  ontology.ttl
```

`git diff` prints nothing, and `ontology.ttl` never appears in `git status`.
The checksum is the one committed on this branch, so it also confirms the file
was not touched during the whole of Proposal 2.

## Partition of the current graph

```text
source graph                     169 triples
  current schema graph            43
  current instance graph         120
  current support/remainder        6
```

The three views are pairwise disjoint and their union is exactly the source
triple set, verified in the test suite for the repository graph, an empty
graph, and a mixed synthetic graph.

This matched the handoff's hypothesis exactly, so decision gate 6 was never
triggered. The schema view is 4 `owl:Class` declarations, 3 `rdfs:subClassOf`
statements, 6 `owl:ObjectProperty` declarations, 10 `owl:DatatypeProperty`
declarations, and the 20 `rdfs:label` statements on those resources.

The remainder is only:

```turtle
onto:ontology a owl:Ontology .

onto:EntityShape a sh:NodeShape ;
    sh:targetClass onto:Entity ;
    sh:property [ sh:path skos:prefLabel ; sh:minCount 1 ] .
```

Nothing in the current graph fell into the remainder for want of a rule.

## Semantic skeleton of the current graph

```text
current schema graph   43 triples
semantic skeleton      43 triples   (identical triple set)
```

The skeleton equals the schema view because the current graph declares no
domains, no ranges, and no OWL restrictions. Every schema statement it holds is
one of the supported forms, so nothing is dropped. Restriction handling is
therefore exercised only by synthetic fixtures, which is the honest state to
record: the copying code is tested, but this graph does not yet use it.

## Empirical relationship patterns of the current graph

18 eligible instance assertions aggregate into 17 patterns, again matching the
hypothesis.

```text
subject class       predicate                            range               kind      occ subj pop coverage card
class:location      fact:advanced-chip-demand            xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:affects                         xsd:string          datatype    2    2   7    0.286  1/1/1
class:location      fact:critical-minerals-position      xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:diplomatic-talks-purpose        xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:export-control-effect           xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:overcapacity-sectors            xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:policy-framing                  xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      fact:shapes                          xsd:string          datatype    1    1   7    0.143  1/1/1
class:location      relation:affects                     class:location      class       1    1   7    0.143  1/1/1
class:location      relation:affects                     class:organization  class       1    1   7    0.143  1/1/1
class:location      relation:competes-with               class:location      class       1    1   7    0.143  1/1/1
class:location      relation:coordinates-with            class:organization  class       1    1   7    0.143  1/1/1
class:location      relation:restricts-chip-exports-to   class:location      class       1    1   7    0.143  1/1/1
class:organization  fact:gray-market-routing-case        xsd:string          datatype    1    1   3    0.333  1/1/1
class:organization  fact:ranks                           xsd:string          datatype    1    1   3    0.333  1/1/1
class:organization  relation:restricted-gpus-sought-by   class:location       class      1    1   3    0.333  1/1/1
class:person        relation:planned-summit-with         class:person        class       1    1   2    0.500  1/1/1
```

Class populations are 7 locations, 3 organizations, and 2 people, which is the
whole set of 12 individuals. No subject or object in the current graph lacks a
usable class, and no pattern occurs more than twice. Every literal is a plain
string, which is why every datatype range is `xsd:string`.

Two things this table shows about the extraction pipeline rather than about
Proposal 2. First, the current graph carries almost no reuse: 15 of the 17
patterns occur exactly once, because the LLM invents a fresh predicate for most
facts. Second, `affects` exists twice with unrelated meanings, once as
`relation:affects` between resources and once as `fact:affects` to a string.
Neither is acted on here; step 5 will decide what to do with them.

## Decision gates

| Gate | Resolution |
|---|---|
| 1 | Resolved without user input: no overlapping roles exist in the current graph |
| 2 | Approved: direct `rdfs:subClassOf` restrictions with `owl:onProperty` and one unqualified constraint |
| 3 | Approved: most-specific explicit domain class, metatypes ignored, incomparable classes all kept |
| 4 | Approved: cardinality over participating subjects only, coverage carries the zero-valued members |
| 5 | Approved: deterministically sorted plain dictionaries |
| 6 | Never triggered: every measured count matched the handoff's hypothesis |
| 7 | Never triggered: no dependency, reasoner, CLI, serialization, or prompt change was needed |

### Gate 1 in detail

The current graph has no resource playing two roles, and its only blank node
belongs solely to the SHACL shape. The recommended rule was therefore pinned
with synthetic fixtures rather than decided against real data:

- an explicitly recognized support structure outranks any other role, so a
  resource typed both `sh:NodeShape` and `owl:Class` is entirely support;
- declarations and structural axioms are schema;
- individual assertions are classified per triple, so `class:person a owl:Class`
  can be schema while `class:person a owl:NamedIndividual` is instance on the
  same resource;
- no triple is ever duplicated across views.

One sub-case the handoff left open was resolved during implementation: a naming
statement such as `rdfs:label` on a resource that is both schema and instance
follows the **schema** role, on the grounds that a label on a declared class
describes the class. This is recorded here because it was a judgment call, not
a decision the handoff made.

### Gate 2 in detail

A restriction is copied into the skeleton only when it is the object of an
`rdfs:subClassOf` from a named class and carries exactly three statements: an
`rdf:type owl:Restriction`, one `owl:onProperty` naming a URI, and one of
`owl:someValuesFrom`, `owl:allValuesFrom`, `owl:hasValue`, `owl:cardinality`,
`owl:minCardinality`, or `owl:maxCardinality`.

Anything else is omitted as a whole structure, including the `rdfs:subClassOf`
triple that points at it. The fixtures cover qualified cardinality, a missing
constraint, a missing type, an extra predicate, two constraints, a blank-node
filler, and a Boolean class expression.

Note that partitioning and skeleton support are deliberately different
decisions: `graph_partition.py` routes any blank node typed `owl:Restriction`
with an `owl:onProperty` into the schema view, including forms the skeleton
declines to copy. A qualified cardinality restriction is schema, and is simply
not in the skeleton.

## Record shape

`observed_relationships(schema_graph, instance_graph)` returns a sorted list of
dictionaries. For a resource-valued assertion:

```python
{
    "subject_class": rdflib.URIRef(".../class/person"),
    "predicate": rdflib.URIRef(".../relation/planned-summit-with"),
    "range_kind": "class",
    "range": rdflib.URIRef(".../class/person"),
    "occurrences": 1,
    "distinct_subjects": 1,
    "class_population": 2,
    "coverage": 0.5,
    "cardinality_min": 1,
    "cardinality_median": 1.0,
    "cardinality_max": 1,
}
```

For a literal-valued assertion, `range_kind` is `"datatype"` and `range` is the
literal's datatype — `xsd:string` for a plain string, `rdf:langString` for a
language-tagged one.

When a subject has no usable class, `subject_class`, `class_population`, and
`coverage` are all `None`; when a resource object has no usable class,
`range_kind` is `"unknown"` and `range` is `None`. No class assertion is ever
invented to fill those in.

Records are sorted by subject class, then predicate, then range kind, then
range, all by string form, so `None` sorts last and the order is stable across
runs.

## Final verification

```text
.venv/bin/python -m unittest discover -s tests   ->  Ran 161 tests, OK
.venv/bin/python ontology.py --help              ->  unchanged usage output
.venv/bin/python -m py_compile *.py tests/*.py   ->  clean
git diff --check                                 ->  clean
git diff -- ontology.ttl                         ->  empty
```

The suite grew from 74 tests to 161. No existing test was changed. Every fixture
is a fresh in-memory `Graph()`; nothing was written to `ontology.ttl`, and the
partition, skeleton, and pattern tests each assert that the repository file's
bytes are identical after the operation.

`ontology.py`, `source_parse.py`, `entity_lookup.py`, `graph_merge.py`,
`graph_management.py`, `ingest_sources.py`, and `llm.py` are byte-for-byte
unchanged. Prompt construction is untouched: the prompt still sends the global
entity catalog and property list, exactly as Proposal 1 left it.

## What Proposal 2 deliberately did not do

The three modules are called only by their tests. They are not wired into
`ontology.py`, they never serialize anything, and none of their output reaches
an LLM. Nothing selects concepts for a source document, ranks context, or
budgets a prompt — that is step 5, and it can now be designed against measured
artifacts instead of guesswork.
