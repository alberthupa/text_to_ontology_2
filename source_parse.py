"""Turn one ingested source text into candidate entities, relations, and facts.

The prompt receives context that was already selected and budgeted for this one
source. It does not go looking for graph context itself: sending the whole entity
catalog and every property label was what Phase 5 replaced. The extraction
contract - the JSON shape and the conservative entity-resolution rule - is
unchanged.
"""

from llm import ask_llm


CONTEXT_RULES = """
Only an exact "id:" value above may be used as existing_id. A "uri:" value is
context, not an identifier you may reuse. Observed usage is evidence about the
current data, not a rule you must follow, and this context is a selection: real
things missing from it are still worth extracting.
""".strip()


def context_block(context_text):
    """The selected context, headed and explained, or nothing at all."""
    if not str(context_text).strip():
        return ""
    return f"""
ONTOLOGY CONTEXT - selected for this source, not the whole ontology:
{context_text}

{CONTEXT_RULES}
""".strip() + "\n\n"


def make_prompt(text, context_text=""):
    """Build the extraction prompt from one source and its selected context."""
    return f"""
Extract only knowledge stated or clearly implied by SOURCE.

{context_block(context_text)}Entity resolution is important. Set existing_id to an
existing entity's exact id only when it is the same real thing in this context.
Use its names, kind, and description. A similar name alone is not enough.
Otherwise use null. Include one entity record per real thing mentioned in this
source.

Return this exact JSON shape:
{{
  "entities": [
    {{"id": "e1", "name": "preferred name", "kind": "Person",
      "description": "short source-grounded description",
      "aliases": ["other source name"], "existing_id": null,
      "confidence": 0.9}}
  ],
  "relations": [
    {{"subject": "e1", "predicate": "works for", "object": "e2",
      "confidence": 0.9}}
  ],
  "facts": [
    {{"subject": "e1", "predicate": "birth date", "value": "1950-01-01",
      "confidence": 0.9}}
  ]
}}

Every record requires a confidence from 0.0 to 1.0: your confidence that SOURCE
directly supports that complete record. It is not confidence that an identity
match is correct, not a probability that the statement is true in the world, and
not source authority.

Relation endpoints and fact subjects must use ids from entities. Use empty lists
when needed. Return JSON only.

SOURCE:
---
{text}
---
""".strip()


def parse_source(text, context_text=""):
    """Ask the model what this one source says, given the context selected for it."""
    # print("  Prompt text:", flush=True)
    # print(make_prompt(text, context_text), flush=True)
    # print("  Asking model...", flush=True)
    return ask_llm(make_prompt(text, context_text))
