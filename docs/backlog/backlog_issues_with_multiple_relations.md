The underlying problem is that the extractor invents a new predicate for almost every sentence, so the file has almost no shared relation vocabulary. The parallel edges between the same pairs of nodes are one symptom of that.

**The numbers**
- The file has 1,077 relations between entities, expressed with 344 different predicates. That is about 3 uses per predicate.
- 198 of those predicates (58%) are used exactly once, and 253 are used at most twice.
- The ten most common predicates (`part-of`, `owned-by`, `uses`, `concerns` and so on) cover only 29% of the relations. In a healthy graph, a small core vocabulary covers most of them.
- 101 entity pairs have more than one relation between them, and the worst pair has 8.

**Three patterns produce the parallel edges**
- **Synonyms are not merged.** The same fact is asserted several times under different predicate names:
  - Nestlé → Lingaro has both `is-strategic-customer-of` and `strategic-customer-of`.
  - Distributor KAMs → Monthly Sales Plan has both `reviews` and `reviews-and-approves`.
  - Suggested Orders → Monthly Sales Plan has `delivers`, `generates` and `produces`.
  - An architecture → FICO has `uses-as-solver` and `uses-as-computation-engine`.
- **Inverses are stored as separate facts.**
  - Azure DevOps `part-of` the architecture sits next to the architecture `includes-component` Azure DevOps.
  - Assortment Prediction `precedes` Line Capacity sits next to Line Capacity `runs-after` Assortment Prediction.
  - PM `designated-by` Lingaro sits next to Lingaro `designates` PM.

  None of these pairs is declared `owl:inverseOf`, so nothing can tell they are the same fact.
- **Sentences become predicates.** Names like `agrees-on-delivery-delays-with`, `provides-visit-time-data-or-algorithm-recipe-to` and `configures-resources-created-by` are whole clauses. The content that should be a value or a separate node is baked into the predicate name, so the predicate can never be reused.

**Contributing schema issues**
- No property has an `rdfs:domain` or `rdfs:range`, so the schema says nothing about which relations are valid between which classes.
- Every entity carries three types: `Entity`, `skos:Concept` and a specific class. That is redundant and multiplies any class-level aggregation. The largest specific buckets are the generic `entity` (128) and `concept` (108), so the typing step often falls back to "don't know".
- There are 3 self-loops, for example Model Governance `part-of` Model Governance. These are most likely extraction or entity-resolution errors.
- Each relation is backed by about 14 provenance statements: reified `rdf:Statement` nodes, `prov:` collections and quality measurements. This is not wrong, but it means roughly 95% of the file is bookkeeping around a small core.

**What to fix upstream, in priority order**
1. **Normalise predicates at extraction time.** Give the extractor a closed or semi-closed relation vocabulary of roughly 30 to 50 predicates and make it map onto that. Alternatively, cluster the 344 predicates afterwards into canonical ones, for example by embedding similarity followed by human review. Keep the original phrase as an annotation on the reified statement, which the file already has.
2. **Pick one direction per relation.** Declare the inverse once with `owl:inverseOf` instead of materialising both directions.
3. **Move specifics out of predicate names.** "Agrees on delivery delays with" should become a generic `agrees-with` plus a topic, or an Agreement node.
4. **Add domain and range to the canonical predicates.** Then the SHACL shapes can reject nonsense such as the self-loops.
5. **Drop the redundant typing.** `Entity` is already implied by `subClassOf`, and `skos:Concept` on everything adds nothing.

The per-pair examples and counts above come from running the app's own parser over your file.