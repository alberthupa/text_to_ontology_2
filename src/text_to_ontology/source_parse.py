"""Turn one ingested source text into candidate entities, relations, and facts.

The prompt receives context that was already selected and budgeted for this one
source. It does not go looking for graph context itself: sending the whole entity
catalog and every property label was what Phase 5 replaced. The extraction
contract - the JSON shape and the conservative entity-resolution rule - is
unchanged.
"""

from . import prompts
from .llm import ask_llm


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


def make_prompt(text, context_text="", library=None):
    """Build the extraction prompt from one source and its selected context.

    The wording is the `extraction_user` template from `prompts.py`, so an
    edited prompt is used here without this module changing.
    """
    return prompts.render(
        "extraction_user",
        {"context": context_block(context_text), "text": text},
        library=library)


def parse_source(text, context_text="", library=None):
    """Ask the model what this one source says, given the context selected for it."""
    return parse_prompt(make_prompt(text, context_text, library=library))


def parse_prompt(prompt):
    """Send one already-built extraction prompt to the model."""
    return ask_llm(prompt)
