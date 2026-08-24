# The window candidate graph

After an LLM response passes validation, `candidate_graph.build_candidate_graph`
converts it deterministically into one RDF graph. This document shows a complete
example and explains the two design choices people ask about most.

## What goes in

Each extraction record becomes three kinds of statements:

1. **The assertions themselves** — ordinary triples such as
   `fact:birth-date "1815-12-10"^^xsd:date`. Reification alone is never
   treated as assertion; the triple is really there.
2. **Reified evidence** — the record is a `prov:Collection` whose members are
   RDF 1.1 reified statements (`rdf:Statement` with `rdf:subject`,
   `rdf:predicate`, `rdf:object`) naming exactly the triples the record
   supports.
3. **A confidence measurement** — a `dqv:QualityMeasurement` on the record,
   typed `xsd:decimal` in `[0,1]`, measured against the project-owned metric
   `<...>/metric/extraction-confidence`.

PROV-O links document → window → extraction activity → records and
measurements, with the model named as a `prov:SoftwareAgent`.

## A complete example

Input: one entity ("Ada Lovelace", confidence 0.9) and one fact
("birth date" = 1815-12-10, confidence 0.95), extracted from document
`doc-abc123`, window `win-def456`, activity `act-789`.

```turtle
@prefix class: <http://example.org/text-ontology/class/> .
@prefix dqv:   <http://www.w3.org/ns/dqv#> .
@prefix fact:  <http://example.org/text-ontology/fact/> .
@prefix onto:  <http://example.org/text-ontology/> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

<http://example.org/text-ontology/provisional/doc-abc123/e1>
    a class:person ;
    rdfs:label "Ada Lovelace" ;
    skos:definition "Wrote the first program." ;
    skos:altLabel "Ada" ;
    fact:birth-date "1815-12-10"^^xsd:date .

class:person a owl:Class ;
    rdfs:label "Person" ;
    rdfs:subClassOf onto:Entity .

### The entity record: what it claimed, as reified evidence

<http://example.org/text-ontology/candidate/doc-abc123/win-def456/entity/0>
    a prov:Collection ;
    prov:hadMember <.../entity/0/statement/0>, <.../entity/0/statement/1>,
                   <.../entity/0/statement/2>, <.../entity/0/statement/3>,
                   <.../entity/0/statement/4>, <.../entity/0/statement/5>,
                   <.../entity/0/statement/6> ;
    prov:wasGeneratedBy <http://example.org/text-ontology/activity/act-789> .

<.../entity/0/statement/4> a rdf:Statement ;     # for example
    rdf:subject   <http://example.org/text-ontology/provisional/doc-abc123/e1> ;
    rdf:predicate rdfs:label ;
    rdf:object    "Ada Lovelace" .

### Its confidence, as a DQV measurement

<http://example.org/text-ontology/candidate/doc-abc123/win-def456/entity/0/confidence>
    a dqv:QualityMeasurement ;
    dqv:computedOn      <.../candidate/doc-abc123/win-def456/entity/0> ;
    dqv:isMeasurementOf onto:metric/extraction-confidence ;
    dqv:value           0.9 ;
    prov:wasGeneratedBy <http://example.org/text-ontology/activity/act-789> .

### The same pattern for the fact record

<http://example.org/text-ontology/candidate/doc-abc123/win-def456/fact/0/confidence>
    a dqv:QualityMeasurement ;
    dqv:value 0.95 ;   # computedOn, isMeasurementOf, wasGeneratedBy omitted

onto:metric/extraction-confidence a dqv:Metric ;
    rdfs:label "extraction confidence" .

### Provenance chain

<http://example.org/text-ontology/document/doc-abc123> a prov:Entity .
<http://example.org/text-ontology/window/win-def456> a prov:Entity ;
    prov:wasDerivedFrom <http://example.org/text-ontology/document/doc-abc123> .
<http://example.org/text-ontology/activity/act-789> a prov:Activity ;
    prov:used <http://example.org/text-ontology/window/win-def456> ;
    prov:wasAssociatedWith <http://example.org/text-ontology/agent/test-model> .
<http://example.org/text-ontology/agent/test-model> a prov:SoftwareAgent ;
    rdfs:label "test-model" .
```

(`...` abbreviations above stand for the corresponding full
`http://example.org/text-ontology/candidate/...` IRIs; the module's output is
always fully expanded.)

## Why DQV?

DQV (`dqv:QualityMeasurement` on a `dqv:Metric`) was selected because it is the
existing W3C vocabulary that says exactly what we mean: *a number produced by
measuring a resource against a defined metric*. It interoperates with standard
RDF tooling without inventing project-specific confidence predicates. It is the
selected interoperable pattern for this project, not a claim that DQV is some
universal confidence law; if a future need outgrows it, that decision can be
revisited explicitly.

## Rules the converter follows

- Provisional entity IRIs are `.../provisional/{document_id}/{local_id}` —
  deterministic, so the same thing named twice gets one IRI.
- Kinds become RDF types on generated class IRIs, never string literals.
- Labels use `rdfs:label`, definitions `skos:definition`, aliases
  `skos:altLabel`.
- Fact literals are typed conservatively: real ISO dates to `xsd:date`, JSON
  booleans/integers/finite floats to their XSD types; anything ambiguous
  (leading zeros, impossible dates) stays a plain string.
- Only standard vocabularies (RDF/RDFS/SKOS/OWL/PROV/DQV/XSD) plus generated
  domain IRIs appear. No custom infrastructure predicates.
