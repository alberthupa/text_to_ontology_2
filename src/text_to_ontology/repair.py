"""Bounded self-repair: let the model fix its own messy answer, a few times.

An LLM response is untrusted. When it does not parse as one JSON object, or
parses but fails the extraction contract, the model gets its own original
answer back together with the deterministic issue list and one clear job:
return the complete corrected JSON, nothing else.

The coordinator never bypasses validation - every repaired answer goes
through exactly the same gate as the first one. When attempts are exhausted
or the network fails, the caller receives the failure unchanged.
"""

import json

from .llm import InvalidResponseError

REPAIR_PROMPT = """
Your previous answer was rejected. Produce the corrected extraction now.

PROBLEM: {problem}
{issue_block}

YOUR ORIGINAL ANSWER (untrusted; it may be malformed or incomplete):
{original}

Return ONLY the complete corrected JSON object in the exact required shape -
{shape}. No apologies, no explanations, no Markdown.
""".strip()

# The extraction contract; a caller with another contract passes its own.
EXTRACTION_SHAPE = '"entities", "relations", "facts"'


def repair_prompt(original=None, raw_problem=None, issues=(),
                  shape=EXTRACTION_SHAPE):
    """One repair prompt built from the original answer and what went wrong."""
    if raw_problem is not None:
        problem = "The previous answer was not one parseable JSON object."
        original_text = raw_problem
    else:
        problem = "The previous answer parsed as JSON but broke the contract."
        original_text = json.dumps(original, indent=2, ensure_ascii=False)
    issue_block = ""
    if issues:
        listed = "\n".join(
            f"- [{issue['severity']}] {issue['path']}: {issue['message']}"
            for issue in sorted(
                issues,
                key=lambda item: (
                    item.get("path", ""), item.get("code", ""),
                    item.get("severity", ""), item.get("message", ""))))
        issue_block = f"ISSUES:\n{listed}\n"
    return REPAIR_PROMPT.format(
        problem=problem, issue_block=issue_block, original=original_text,
        shape=shape)


class ExtractionOutcome:
    """What one extract-and-repair round produced."""

    def __init__(self, validation, raw_problem, repair_attempts):
        self.validation = validation      # None when nothing parsed as JSON
        self.raw_problem = raw_problem    # None when something parsed
        self.repair_attempts = repair_attempts

    @property
    def ok(self):
        return self.raw_problem is None and self.validation["valid"]


def extract_validated(extractor, prompt, validate, max_repair_attempts=0,
                      shape=EXTRACTION_SHAPE):
    """Extract once, validate, and let the model repair up to N times."""
    response, problem = _attempt(extractor, prompt)
    validation = None if problem is not None else validate(response)
    repairs = 0
    while ((problem is not None or not validation["valid"])
           and repairs < max_repair_attempts):
        repairs += 1
        ask = repair_prompt(
            original=response,
            raw_problem=problem,
            issues=validation["issues"] if validation is not None else (),
            shape=shape,
        )
        response, problem = _attempt(extractor, ask)
        validation = None if problem is not None else validate(response)
    return ExtractionOutcome(validation, problem, repairs)


def _attempt(extractor, prompt):
    """One call; unparseable answers become problem text, not exceptions."""
    try:
        return extractor.extract(prompt), None
    except InvalidResponseError as failure:
        return None, str(failure)
