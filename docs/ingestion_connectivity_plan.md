# Ingestion connectivity plan

Status: P0–P6 implemented on branch `connectivity` (2026-10-09). P0-T3
(fresh baseline) and P7 (rebuild and compare) need real model runs and your
gold file — not done yet.
Written: 2026-10-09, against branch `starter-ontology` (commit `77be670`).

### Where the implementation differs from the plan below

- **Data-only only.** Core schema, document header, anchors, same-folder
  block, endpoint checks, and the link check apply when the vocabulary is
  frozen (`--data-only`, and always in the studio). Legacy runs are unchanged.
- **Prompt rules live in the core schema block**, not in the
  `extraction_user` template (P2-T4, P3-T4, P4-T1). That way they also reach
  users who saved their own `extraction_user` override, and no template
  changed.
- **Provenance `onto:sourcePath` is unchanged** (the path as discovered). The
  path relative to the ingestion root (`RunRequest.source_root`) is used only
  for the prompt header (P3-T1).
- **Gaps are found by a direct graph check**, not by running pySHACL
  (P5-T2): the expected links are still read from the SHACL warning shapes.
- **The link-check answer is a small `{"links": [...]}` shape** with
  candidate keys; the code builds the ordinary candidate package from it
  (P5-T3). The model never writes entity records there.
- **The health report has no built-in expected links** (P0-T1): it reports
  missing links only for shapes declared with `text-to-ontology-expect`.
- **Repair stays in `repair.py`**, which now also keeps the last parsed
  answer on its outcome, so the pipeline can drop wrongly connected records
  after repair (P2-T3).

## 1. The problem in one example

The project *Pharmaceutical Assistant* is delivered for the client *Polpharma*.
The graph does not know that. Instead it has:

- `Pharmaceutical Assistant` (Project) with five technology links and **no**
  `has client` link;
- `Polpharma` (Client) and a second node `Polpharmy` (the Polish genitive of
  the same name, typed only as the root class `Entity`);
- `Lingaro --has client--> Polpharma` and `Lingaro --has client--> Polpharmy`,
  although `has client` starts at a Project, and Lingaro is not one.

The one ingested document about it, `michalek_maciej/chatbots/own_solution_vs_copilot.md`,
actually says it in its very first line: *"Porównanie copilota z WAP na
potrzeby zapytania Polpharmy"* ("Comparison of Copilot with WAP for Polpharma's
request"). The four files in `projects/Polpharma/Pharma Assistant/` were never
ingested.

### Why it went wrong (measured, not guessed)

Measured on the current `ontology.trig` with today's code (scripts in the
session scratchpad, read-only):

| What | Number |
|---|---|
| Entities in the data graph | 512 |
| Entities with no link to any other entity | 293 (57%) |
| Entities typed only as root `Entity` (no business class) | 210 (41%) |
| Projects with a `has client` link | 2 of 13 |
| `originates from` statements that break its domain/range (Project → Proposal) | 117 of 117 (83 are Offer → Offer) |
| Other relation statements with a wrong subject or object class | `has client` 3/5, `project uses technology` 9/54, `client uses technology` 3/7, `offer source note` 3/29 |
| Fact statements on the wrong class (e.g. `business need` 138/146, `proposed solution` 47/54) | 541 |
| **All statements breaking a declared domain/range** | **676** |
| Files of the Polpharma project folder present in provenance | 0 of 4 |

And what the extraction prompt shows the model (`_window_context` in
`pipeline.py`) for the comparison document, which is cut into 5 windows:

| Window | Schema-only graph | Schema + current data |
|---|---|---|
| 1 | **empty context** | 3 classes, **0 relations** (`has client` visible only as the example `Lingaro → has client → Polpharmy`) |
| 2 | **empty context** | 2 classes, **0 relations** |
| 3 | 7 classes, 0 relations | 7 classes, 0 relations |

Five root causes follow from this:

1. **The schema is selected by word matching, and Polish text does not match
   English labels.** Window 1 of a Polish note gets nothing. Once the data
   graph is big, resources and examples fill the 1,400-token context budget
   and the relation declarations (with their domain and range) are pushed
   out. The model then picks predicates by name only — hence 117 wrong
   `originates from` statements.
2. **Nothing checks relation endpoints.** `candidate_validation.py` checks that
   a predicate is declared, never that its subject is a Project and its object
   a Client. The SHACL shapes graph only requires a label.
3. **`Entity` is an escape hatch.** In data-only mode the root class counts as
   a declared class, so the model types 41% of things as `Entity`, and those
   then sit at the wrong end of relations.
4. **Windows lose the document's subject.** The title line is only in window
   1. Later windows see earlier-window knowledge only when words match. The
   studio also throws away folder names (`file.name` in `studio.js`,
   `Path(name).name` in `workspace._write_source`), so
   `projects/Polpharma/Pharma Assistant/` is lost.
5. **Identity is exact-name only.** `Polpharmy` ≠ `Polpharma` for every
   matcher (`SequenceMatcher` ratio 0.89, threshold 0.96), and the selector
   never shows the `Polpharma` card for a window that says `Polpharmy`, so
   the model cannot set `existing_id`.

## 2. Strategy: what "well connected" means here

Not more predicates. The 14 relations the starter declares are enough
(`has client` already means "project is delivered for this client"). A
well-connected graph here means:

1. **Every entity has a real class.** `Entity` is allowed only for things that
   fit no class, and such things cannot be relation endpoints.
2. **Every relation has the right endpoints.** Wrong links are worse than
   missing ones — they mislead the chat and hide the gap.
3. **One real thing is one node.** `Polpharma`/`Polpharmy`, `WAP`/`Wirtualny
   Asystent Polpharmy`/`Pharmaceutical Assistant`.
4. **Every window knows what the document is about** — its path, title,
   heading, and the main project/client found so far.
5. **Expected links are checked and filled from evidence.** A project
   without a client is a known gap; after a document is extracted, one
   targeted question per gap either finds the evidence or records "not
   established". Never invented.
6. **It is measured.** Every change is judged by the same health report and
   a small hand-written list of true links.

### On the "seed": include it whole, mark it by graph, not by flag

Yes — the complete starter schema goes into every extraction prompt, as its
own block with its own budget. It is small: the current one renders in about
3,000 characters (~1,000 tokens).

It is already marked: it lives in `graphs/schema`, separate from
`graphs/data`. No per-triple flag is needed. Two additions make it explicit:
the prompt block is headed `CORE SCHEMA` (authoritative, unlike
`OBSERVED USAGE`), and each run records a digest of the schema graph next to
the prompt digests, so a report names the schema it used. If someday the seed
includes curated individuals (e.g. a client list), they stay in `graphs/data`
and get a `prov:wasDerivedFrom` to the seed import, like any other source.

### Where this plan differs from the earlier proposal

- Endpoint checking moves **early** (phase 2), not last: it is the cheapest,
  most certain fix, and it is what turns the full schema into correct links.
- No new "alias catalog" file: aliases are `skos:altLabel` on the canonical
  entity, which **Edit the graph** can already write and both matchers
  already read.
- Expected links are **standard SHACL** (`sh:minCount 1`,
  `sh:severity sh:Warning`) in the existing shapes graph, not custom
  configuration. The link check reads the warnings.
- The folder path is a **hint for finding context, not evidence**. A link
  still has to be supported by text. This avoids a new "evidence origin" tag
  on every fact. (If you later want folder-derived links, that is one
  sentence of prompt policy plus a flag — see §6.)
- The existing graph is **not migrated**. After the phases land, the dataset
  is rebuilt from sources with the same starter, and compared to the baseline.

## 3. Phases at a glance

| Phase | What | Depends on | Size |
|---|---|---|---|
| P0 | Health report + gold links (measure first) | – | S |
| P1 | Full core schema in every prompt | P0 | S |
| P2 | Endpoint checks in the validation gate | P1 | M |
| P3 | Document context that survives windows | P1 | M |
| P4 | Names: inflection and aliases | P1 | S |
| P5 | Link check after each document | P2, P3 | M |
| P6 | Same-folder context (optional) | P3 | S |
| P7 | Rebuild the dataset and compare | all | S |

Each phase ends with: all tests green
(`python3 -m unittest discover -s tests -p 'test_*.py'`), README and
`docs/current_architecture.md` updated for any changed behaviour, and the
health report re-run on a small real sample (the Polpharma folder plus
`own_solution_vs_copilot.md`) with its numbers pasted into §7 of this file.

Test data rule: unit tests use **fictional** names (client `Farmexa`, its
genitive `Farmexy`, project `Virtual Assistant of Farmexa` / `VAF`), never
company or client data. Real gold data lives only in a git-ignored file.

---

## P0 — Measure first

### P0-T1 Graph health report

New module `src/text_to_ontology/graph_health.py` (read-only, no RDF writes)
and console script `text-to-ontology-health`:

```bash
text-to-ontology-health ontology.trig
text-to-ontology-health ontology.trig --sources ~/Desktop/members_notes --gold eval/gold.local.json
```

It reports, as plain data (a dict) and as short text:

- entity count; isolated entities (no entity-to-entity link either way);
  entities typed only as the root class;
- per relation and per fact: statements whose subject or object class breaks
  the declared domain/range (subclasses count as matching);
- missing expected links: every SHACL warning from the shapes graph (P5-T1),
  and until P5 exists, a built-in list "Project without `has client`,
  Proposal without `proposal for client`";
- duplicate suspects: pairs of entities of the same class whose names are
  the same word up to an inflected ending (the rule from P4-T2) or share an
  alias;
- `--sources DIR`: files under DIR whose content digest has no document in
  the provenance graph (source coverage);
- `--gold FILE`: recall and precision of the gold links (P0-T2).

Keep the functions small and one per metric (`isolated_entities(graph)`,
`endpoint_violations(graph)`, …) so tests can call them one by one.

**Definition of done**
- Running it on the current `ontology.trig` prints the numbers of §1 (512 /
  293 / 210 / 2 of 13 / 117 of 117 / 676).
- `--sources` on `michalek_maciej/` lists the four Polpharma files as missing.
- The report is a pure function of the dataset (and the source folder): no
  model call, no writes.

**Tests** — `tests/test_graph_health.py`, on a small TriG fixture built in
the test:
- an entity with no links counts as isolated; one with a link does not;
- an entity typed only `onto:Entity` counts as root-only;
- `Lingaro(Entity) --has client--> X(Client)` is one domain violation;
  a Project subject is none; a subclass of Project is none;
- a fact used on the wrong class is reported;
- `Farmexa` and `Farmexy` (both Client) are a duplicate suspect; `Farmexa`
  (Client) and `Farmexy` (Technology) are not;
- a source file whose digest is in provenance is covered; a changed file is
  not;
- gold: 2 expected links, 1 present and 1 extra wrong link → recall 0.5,
  precision 0.5; matching uses any `skos:prefLabel`/`skos:altLabel`.

### P0-T2 Gold links

- Commit `eval/gold.example.json` with fictional data, and document the
  format in README:

  ```json
  {"links": [
    {"subject": "Virtual Assistant of Farmexa", "predicate": "has client", "object": "Farmexa"}
  ]}
  ```
- You write the real `eval/gold.local.json`. Add `eval/*.local.json` to
  `.gitignore` (today it only ignores `prompts.local.json`). Start with 10–20 project→client and proposal→client
  pairs you know from the member notes, including Pharmaceutical Assistant →
  Polpharma.

**Definition of done**: the example file is loaded by the health test; the
real file exists locally and is not tracked by git (`git status` clean).

### P0-T3 Baseline

Record the health report of the current dataset, and of a **fresh** dataset
built with today's code from the same starter plus the sample (Polpharma
folder + `own_solution_vs_copilot.md`), in §7. Every later phase is compared
to this fresh baseline, not to the old graph.

---

## P1 — The full core schema in every prompt

### P1-T1 Render the core schema

New module `src/text_to_ontology/schema_context.py` with one public function
`render_core_schema(graph) -> str`. Deterministic order (classes, then
relations, then facts, each sorted by label). One line per item, meaning
included:

```text
CORE SCHEMA — the only classes and relationships you may use
Classes:
- Project: paid delivery work for a client
- Client: customer organization
- Entity: only for things that fit no class above; an Entity cannot be in a relationship
Relationships (subject --name--> object):
- Project --has client--> Client: project is delivered for this client
- Project --originates from--> Proposal: proposal the project came from
Facts (subject . name = text):
- Project . project summary = text: short summary
```

Read classes, relations, facts, domains, ranges and comments from the schema
graph only (`owl:Class`/`rdfs:Class`, `owl:ObjectProperty`,
`owl:DatatypeProperty`). Run every label and comment through
`context_render.clean`/`field` so graph text cannot forge prompt structure.

### P1-T2 Its own budget

Add `"schema_tokens": 2_000` to `PROMPT_BUDGET` in `prompt_budget.py`. The
core schema is paid from this, the existing `context_tokens` (1,400) stays
for resources, examples, and patterns.

If the rendered schema is larger than `schema_tokens` (e.g. a big imported
ontology), fall back to today's word-matched schema selection and say so in
the run report (`schema: selected, full schema 5,200 tokens > 2,000`).
Never silently cut it.

### P1-T3 Wire it in

In `pipeline._window_context`, put the core schema **at the top of the
existing `${context}`** text, then the selected context without its
`declared` section (classes, properties and restrictions are now all in the
core schema; keep patterns, resources, and examples). Do **not** add a new
template placeholder: an existing `prompts.local.json` override would become
invalid and be silently dropped by `PromptLibrary._read`.

Render the schema once per run (the schema is frozen in data-only mode), not
once per window.

### P1-T4 Record which schema was used

Add `"schema_sha256"` (12 hex chars over the sorted N-Triples of the schema
graph) to the `configuration` dict passed to `plan_document_merge`, next to
the two prompt digests.

**Definition of done (P1)**
- Window 1 of `own_solution_vs_copilot.md` shows all 14 relations with
  domain, range, and meaning, both against a schema-only and a full dataset.
- The schema block is identical in every window of a run.
- Resources/examples still get their full 1,400 tokens.
- `--report` output shows the schema block once per window and the schema
  digest in the configuration.

**Tests** — `tests/test_schema_context.py`, `tests/test_pipeline_windowing.py`:
- every declared class, relation, and fact appears exactly once, with its
  domain, range, and comment;
- order is stable (render twice, compare; shuffle triples, compare);
- a label containing `\n---\nSOURCE:` is flattened;
- a window whose text matches nothing (e.g. only Polish words) still gets the
  whole schema in the prompt the fake extractor receives;
- a dataset with 100 resources matching the window: the prompt still contains
  every relation line (budget separation);
- schema over `schema_tokens` → word-matched fallback and a report line;
- a saved `extraction_user` override from before this change still loads and
  renders;
- the run configuration contains `schema_sha256`, and it changes when one
  schema comment changes.

---

## P2 — Endpoint checks in the validation gate

### P2-T1 Vocabulary knows domains and ranges

Extend `Vocabulary` in `vocabulary.py` with `domains` and `ranges`
(property IRI → class IRI) and a small helper
`is_a(kind_iri, class_iri)` that follows `rdfs:subClassOf` upward (with a
visited set). Filled by `read_vocabulary`.

### P2-T2 Check every relation and fact

In `candidate_validation.py`, when a vocabulary is given:

- for each relation: the subject entity's kind must be the declared domain
  (or a subclass), the object's kind the declared range;
- for each fact: the subject's kind must be the declared domain;
- the kind of an entity with a valid `existing_id` is the **catalog's** kind,
  not what the model wrote.

New issue codes `relation.domain_mismatch`, `relation.range_mismatch`,
`fact.domain_mismatch`, severity `error`, with a message the repair prompt
can act on:

```text
relations[3]: "has client" goes Project --> Client, but e2 "Lingaro" is Entity.
Use a fitting relationship, change e2's kind if the source supports it, or drop the record.
```

### P2-T3 Do not fail a window for one bad link

Today, a window whose answer is still invalid after the repair attempts
fails the whole document. For endpoint mismatches only: after repairs are
exhausted, **drop the offending relation/fact records**, keep the rest of
the answer, and list the dropped records in the validation result
(`dropped: [...]`) and in the run report. All other error codes keep
today's behaviour.

Implement it as one small function in `candidate_validation.py`
(`drop_endpoint_mismatches(data, validation)`) that `pipeline._extract_window`
calls once, then re-validates; do not change `repair.py`.

### P2-T4 Prompt rules

Add to the default `extraction_user` template, near the entity rules:

```text
"kind" must be one of the CORE SCHEMA classes, the most specific one the
source supports. Use "Entity" only when no class fits; an Entity cannot be the
subject or object of a relationship. Use a relationship only between the
classes shown for it.
```

Existing user overrides are not changed; the studio's **Back to default**
picks up the new wording.

**Definition of done (P2)**
- No published relation or fact breaks its declared domain/range — the health
  report shows 0 endpoint violations on a fresh sample run.
- A relation the model got wrong is first sent back for repair with the
  message above, and only dropped when the repair fails; the drop is visible
  in the report.
- Legacy (non data-only) runs are unchanged.

**Tests** — `tests/test_candidate_validation.py`, `tests/test_vocabulary.py`,
`tests/test_data_only.py`:
- `Project --has client--> Client` passes; `Entity --has client--> Client`
  fails with `relation.domain_mismatch`; `Project --has client--> Technology`
  fails with `relation.range_mismatch`;
- a subclass of Project as subject passes;
- an object with an `existing_id` of a canonical Client is checked as a
  Client (the catalog's kind is used, not the answer's);
- a fact on the wrong class fails with `fact.domain_mismatch`;
- without a vocabulary, nothing new is checked;
- fake extractor answers wrong, then right after the repair prompt → the
  right answer is admitted, the repair prompt contains the mismatch message;
- fake extractor stays wrong → the window is admitted without that one
  relation, everything else kept, the drop reported;
- a property with no declared domain/range is not checked on that side.

---

## P3 — Document context that survives windows

### P3-T1 Keep the folder path

- `frontend/studio.js`: send `webkitRelativePath` (file picker) or
  `entry.fullPath` (drag-and-drop) as the file name, e.g.
  `michalek_maciej/projects/Polpharma/Pharma Assistant/project_description.md`.
- `workspace._write_source`: keep the sub-folders under `sources/inbox/`.
  Clean each path part with today's character rule, drop empty parts, `.`
  and `..`, never allow an absolute path, and check the final path is still
  inside the inbox (`resolve()` + `is_relative_to`). Duplicate names still get
  `-2`, `-3`.
- `SourceDocument.source_path` becomes the path **relative to the ingestion
  root** (the inbox, or the folder given to the CLI), so the same file gives
  the same path whichever way it was ingested. Provenance `onto:sourcePath`
  then carries it automatically.
- Update the README sentence "directory structure is not retained".

### P3-T2 Document header in every window

New module `src/text_to_ontology/document_context.py`:

- `document_title(text)`: the first Markdown heading, else the first
  non-empty line, cut to 200 characters;
- `heading_trail(text, start)`: the Markdown headings in force at a window's
  start offset (`# A` > `## B`), so window 3 of a backlog knows it is inside
  `# Add BLOZ identifier … > ## Acceptance Criteria`;
- `render_document_header(document, window, total)`:

```text
DOCUMENT CONTEXT — where this text comes from (a hint, not evidence)
Path: michalek_maciej/projects/Polpharma/Pharma Assistant/20260522_backlog_refinement.md
Title: Add BLOZ identifier and Polpharma ownership flag to product entities
Section: # Change Farmindex data refresh frequency to weekly > ## User Story
Window: 3 of 11
```

All text through `context_render.clean`. The header is always included (it
is ~60 tokens, paid from `fixed_prompt_tokens`, which goes from 400 to 500).

### P3-T3 Pinned document anchors

The things a document is *about* must be visible in every later window,
whether or not the window repeats their name.

- **Anchor classes** are derived from the schema: every class that is the
  domain of at least one relationship (here: Project, Proposal, Offer,
  Client). No configuration.
- Before each window, take the entities already in this document's staging
  graph whose class is an anchor class, ordered by how many windows mentioned
  them (then by name), at most 8.
- Render them first in the `(this document)` part, as today's resource cards
  plus their links, and give them priority over every word-matched item (a
  new tier `ANCHOR = 0` in `task_context.py`, or a separate list placed
  before the fitted items — whichever is simpler in the code).

### P3-T4 Prompt rule

```text
A part of a document may refer to its subject without naming it ("the
assistant", "the client"). If it refers to a DOCUMENT ANCHOR, reuse that
anchor's exact name and kind instead of creating a new entity.
```

Exact name + kind is what the staging admission already matches on, so no
identity code changes.

**Definition of done (P3)**
- Dropping the `michalek_maciej` folder in the studio stores files under
  `sources/inbox/michalek_maciej/projects/Polpharma/Pharma Assistant/…`, and
  provenance shows those relative paths.
- Every window prompt of a multi-window document starts with the document
  header; windows after the first show the document's project/client anchors.
- On the sample run, the windows of `20260522_backlog_refinement.md` that
  never name the assistant still link their technologies to the same project
  node (no second "assistant" project).

**Tests** — `tests/test_document_context.py`, `tests/test_studio.py`,
`tests/test_pipeline_windowing.py`:
- title from `# Heading`, from a plain first line, and from an empty file;
- heading trail at offsets before the first heading, inside `##`, after a new
  `#` (the old `##` disappears);
- header text is cleaned (a path with `---` or a newline cannot forge a
  delimiter);
- `_write_source("a/../../etc/x.md")`, `"/abs/x.md"`, `"a//b/./c.md"` all
  stay inside the inbox; `"a/b/c.md"` keeps `a/b/`;
- the same file ingested from the CLI and from the inbox gets the same
  `source_path`;
- anchor classes derived from a schema: a class that is only a range
  (Technology) is not an anchor;
- fake extractor: window 1 returns Project `VAF`; the prompt for window 2
  contains `VAF` under the anchors although window 2 text never says `VAF`;
- at most 8 anchors, ordered by mentions then name.

---

## P4 — Names: inflection and aliases

### P4-T1 Base-form names in the prompt

Add to the default `extraction_user`:

```text
"name" is the base (dictionary) form of the name: "Polpharma", not
"Polpharmy" or "Polpharmie". Put other forms you saw in "aliases".
```

(Use the fictional example in the template text if you prefer not to have a
client name in the code; the instruction is what matters.)

### P4-T2 Inflection-tolerant matching in the selector

One helper, `same_word_stem(a, b)`, in `source_concepts.py`: two
normalized words of at least 5 characters are the same word when their
lengths differ by at most 2 and they share every character except at most
the last 2 of the longer one. (`polpharmy`/`polpharma` → yes;
`pharmacy`/`pharmindex` → no.)

In `task_context.name_match`, when no exact phrase or concept matches, try
the stem rule per word of a name against the source words; a hit is a
`CONCEPT`-tier match with reason `"inflected name match"`. This makes the
`Polpharma` card (with its `id:`) appear for a window that says `Polpharmy`,
so the model can set `existing_id`.

### P4-T3 Inflection as a review hint, never an automatic merge

In `entity_lookup.identity_decision`, after the existing `close_spelling`
step: same kind + `same_word_stem` on the preferred names → `review` with
method `inflected_form` and reason `identity.inflected_form`, suggestion
pointing at the existing entity. The health report lists them as duplicate
suspects. Nothing is merged without an `existing_id`, an exact name, or an
alias.

### P4-T4 Aliases are `skos:altLabel` — document the workflow

No new code. Add a short README section "Teach it a name": open **Edit the
graph…**, add

```turtle
entity:pharmaceutical-assistant skos:altLabel "WAP", "Wirtualny Asystent Polpharmy", "Pharma Assistant" .
entity:polpharma skos:altLabel "Polpharmy" .
```

and apply. Both the selector (`task_context.name_index`) and the identity
matcher (`entity_catalog`) already read `skos:altLabel`, so the next
ingestion resolves those names to the existing nodes. The health report's
duplicate suspects (P0-T1) are the to-do list for this.

**Definition of done (P4)**
- Ingesting a text that says only "Farmexy" into a dataset with Client
  `Farmexa` produces no new Client node (resolved via `existing_id`, or held
  in review with `inflected_form` — never a silent new node).
- After adding `skos:altLabel "VAF"` to the project, a text naming only
  "VAF" resolves to that project.

**Tests** — `tests/test_source_concepts.py`, `tests/test_task_context.py`,
`tests/test_entity_lookup.py`, `tests/test_data_only.py`:
- `same_word_stem`: `farmexa/farmexy` yes, `farmexa/farmexami` yes (diff 2),
  `pharma/pharmindex` no, `rag/rug` no (too short), identical words yes;
- a window text containing "Farmexy" selects the `Farmexa` resource card,
  reason `inflected name match`, with its `id:` line;
- identity: same kind + stem → review `inflected_form`; different kind →
  not suggested; exact alias still wins as `exact_alias`;
- an altLabel added through `graph_edit` apply is used by the next
  ingestion's identity decision (fake extractor, name "VAF", kind Project →
  `existing`).

---

## P5 — Link check after each document

The model extracts what each window says. Some links are only clear across
windows (title in window 1, project description in window 4). After the
whole document is in its staging graph, ask once per missing expected link.

### P5-T1 Expected links as SHACL warnings

An expected link is a standard SHACL shape in the shapes graph:

```turtle
onto:ProjectHasClient a sh:NodeShape ;
    sh:targetClass class:project ;
    sh:property [
        sh:path relation:has-client ;
        sh:minCount 1 ;
        sh:severity sh:Warning ;
        sh:message "Which client is this project delivered for?"
    ] .
```

- Add `expected_links.py` with `add_expected_link(store, class_iri,
  relation_iri, question)` and `expected_links(shapes_graph)` (reads them
  back), and a CLI `text-to-ontology-expect ontology.trig Project "has client"
  "Which client is this project delivered for?"` (`--list` to show them).
  Names resolve through `Vocabulary`, unknown names are refused.
- `source_validation.validate_source_graph`: pass `allow_warnings=True`, so a
  warning never blocks a document, but keep warnings in the report.
- Suggested set for your dataset: Project → `has client`; Proposal →
  `proposal for client`. (Only links that should almost always exist.)

### P5-T2 Find the gaps

New module `src/text_to_ontology/link_check.py`. After
`reconcile_document` and before `plan_document_merge` in
`run_text_to_graph`:

1. validate the source graph against **only** the expected-link shapes;
2. every warning result is one gap: (focus entity, relation);
3. skip a gap when the canonical graph already has that link for the
   entity's existing id (the project may already have a client from an
   earlier document);
4. at most `max_link_checks` gaps per document (default 5), anchors first.

### P5-T3 Ask once per gap

For each gap, one model call with a new editable template
`link_check_user` in `prompts.py` (placeholders `${question}`, `${subject}`,
`${relation}`, `${candidates}`, `${passages}`, all required), containing:

- the question from the shape (`sh:message`) and the relation line from the
  core schema;
- the subject entity (name, kind, aliases);
- **candidates**: this document's entities of the range class, plus canonical
  entities of that class (with `id:`), word-matched against the passages
  first, at most 20;
- **passages**: the document header, window 1 (title), and every window that
  mentions a name or alias of the subject or of a candidate, until a fixed
  2,500-token cap, in document order.

Answer shape — the normal extraction shape plus one `evidence` field:

```json
{"entities": [{"id": "c1", "name": "Farmexa", "kind": "Client", "existing_id": "…", "confidence": 0.9, …}],
 "relations": [{"subject": "s", "predicate": "has client", "object": "c1",
                "confidence": 0.9, "evidence": "Comparison of Copilot with VAF for Farmexy's request"}],
 "facts": []}
```

or empty lists when the passages do not establish it.

### P5-T4 Accept only quoted evidence

- Strip `evidence` before the ordinary `validate_candidates` gate (with the
  P2 endpoint checks), so the gate itself is unchanged.
- Keep a relation only when its `evidence` is found in the passages after
  whitespace and case normalization. Otherwise drop it and record
  `link_check.unsupported_evidence`.
- An accepted answer is admitted exactly like a window (`_admit_window`),
  with a synthetic window id `link-<sha256(document_id|gap)>[:16]` and the
  passages as its text, so provenance, reconciliation and publication need
  no special case.
- A gap with no accepted relation is reported as `not established`.

### P5-T5 Report it

`DocumentResult.link_check = {"gaps": n, "filled": [...], "not_established":
[...], "dropped": [...]}`, one `Link check:` line in the run report, and the
same counts in the studio progress log.

Config: `ExtractionConfig(link_check=True, max_link_checks=5)`; the CLI gets
`--no-link-check`.

**Definition of done (P5)**
- On the sample run, `own_solution_vs_copilot.md` alone produces
  `<its project> --has client--> Polpharma` with an evidence quote from its
  first line, and that quote is in the provenance of the statement.
- A document whose text does not name a client leaves the gap as `not
  established` and adds nothing.
- No gap → no extra model call.
- A shape-free dataset behaves exactly as before.

**Tests** — `tests/test_link_check.py`, `tests/test_source_validation.py`,
`tests/test_prompts.py`:
- a Project without `has client` + the shape → one gap; with the link → none;
  with the link already in the canonical graph for its existing id → none;
- a warning shape never makes `conforms` false; a violation shape still does;
- passages: window 1 always included, windows mentioning the subject or a
  candidate included, cap respected, document order kept;
- candidates: range class only, at most 20, canonical ones carry `id:`;
- fake extractor returns the link with a quote present in window 1 →
  admitted, published, with the synthetic window id in provenance;
- quote not in the passages → dropped, `unsupported_evidence` reported;
- link with the wrong range class → dropped by the P2 gate;
- empty answer → `not established`, graph unchanged;
- more gaps than `max_link_checks` → only that many calls, anchors first;
- `link_check_user` passes `PromptLibrary.validate`, preview renders, digest
  recorded in the run configuration.

---

## P6 — Same-folder context (optional)

Files in one project folder describe one project. When
`projects/Polpharma/Pharma Assistant/20260522_backlog_refinement.md` is
ingested after `project_description.md`, the canonical project and client
from that folder should be visible in its prompt even if the backlog never
names them.

### P6-T1 Folder neighbours

In `document_context.py`: `folder_anchors(canonical_graph, provenance_graph,
source_path)` — canonical entities of anchor classes whose `onto:sourceFile`
records have a `onto:sourcePath` in the **same folder**, at most 5, by number
of supporting files. Rendered as resource cards (with `id:`) in a
`SAME FOLDER` block after the document anchors.

**Definition of done**: ingesting the four Polpharma files in any order ends
with one project node and one Polpharma client node, linked by `has client`.

**Tests**: two fake documents in `x/y/` share a project; the second prompt
lists it under `SAME FOLDER` with its `id:`; a document in `x/z/` does not;
order swapped → same final links.

---

## P7 — Rebuild and compare

### P7-T1 Fresh dataset

1. Back up `ontology.trig`.
2. **Reset everything**, import the same starter (export the schema graph of
   the old dataset as Turtle and import it, so classes and IRIs are
   identical).
3. Add the expected links (P5-T1).
4. Ingest the whole `members_notes` folder through the studio (folder paths
   kept).
5. Add the aliases the duplicate-suspect list asks for; re-ingest only the
   files whose entities were affected, or accept the review items.
6. Run the health report with `--sources` and `--gold`.

### P7-T2 Order check

Ingest the Polpharma folder into two fresh datasets in opposite file
orders; the sets of gold links found must be equal.

**Definition of done (P7)** — targets, to confirm after P0-T3:

| Metric | Old graph | Target |
|---|---|---|
| Endpoint violations (relations + facts) | 676 | **0** (enforced) |
| Entities typed only `Entity` | 41% | ≤ 15% |
| Isolated entities | 57% | ≤ 35% |
| Gold links recall | measure | ≥ 80% |
| Gold links precision | measure | ≥ 90% |
| Duplicate suspects among gold clients/projects | 1+ | 0 after aliases |
| Source files without a document | 4+ | 0 |
| Gold links equal in both orders (P7-T2) | – | yes |

`Pharmaceutical Assistant` (under whatever name, with the others as aliases)
`--has client--> Polpharma` is present, with evidence from at least two
source files.

---

## 6. Deliberately not in this plan

- **New predicates or classes.** The starter already says it; data-only
  stays data-only.
- **A flag on every seed triple.** The named graph is the mark (§2).
- **Links made from folder names alone.** Paths help find context; a link
  needs text evidence. If you want folder-derived links later: allow the
  link check to cite `Path:` as evidence, and record that on the statement
  (`onto:evidenceKind "path"`), so they can be filtered out.
- **Automatic fuzzy merging.** Inflection and close spelling only produce
  review items; merging needs an id, exact name, or alias.
- **Inferring links through shared technologies.** Two projects using
  Langfuse do not share a client.
- **Embeddings / NER for selection.** The stem rule and the full schema
  remove the measured failures; `source_concepts.py` stays the place to
  swap in something smarter later.

## 7. Results log

Fill in after each phase (date, dataset, numbers from `text-to-ontology-health`).

| Date | Phase | Dataset | Isolated | Root-only | Endpoint viol. | Gold recall / precision | Notes |
|---|---|---|---|---|---|---|---|
| 2026-10-09 | baseline | current `ontology.trig` | 293/512 | 210/512 | 676 (135 relations, 541 facts) | – | measured by hand, see §1 |
| 2026-10-09 | P0–P6 | fresh starter + 4 Polpharma files (`openrouter/pareto-code:nitro`) | 14/49 | 14/49 | 0 | – | `Pharma Assistant --has client--> Polpharma` found; 1 project, 1 client node; aliases over-collected ("the node", "the backlog") — see notes |
