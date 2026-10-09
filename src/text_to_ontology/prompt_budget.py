"""Fit complete context items into a stated token allowance.

Three separate jobs, none of which may guess:

    estimate_tokens     price a string, conservatively and explicitly;
    context_allowance   subtract the parts of the prompt that are not context;
    fit_context_items   keep the most relevant complete items that fit.

The estimate is an estimate. `chars_per_token` is a deliberately pessimistic
constant, not a model's tokenizer, and every caller may replace the counter with
its own callable: pass `count_tokens=` to price items with a real tokenizer
later without touching selection or rendering.

Nothing here trims text. An item that does not fit is dropped whole and named in
`dropped_ids`, because half a URI, half an entity card, or half a restriction
misleads more than an absent one.
"""

from math import ceil


# Conservative and named, not derived from any model's context window.
DEFAULT_CHARS_PER_TOKEN = 3

# The numbers the user approved on 2026-08-17 after seeing Phase 5C's
# measurements (proposal 05, gate 4). Two of them need care:
#
#   total_limit     chosen to be comfortably higher than any prompt this
#                   pipeline builds, so that it does not bind. It is NOT a
#                   measured window for any model, and must never be inferred
#                   or adjusted from OPENROUTER_MODEL, which may name a router.
#   context_tokens  the intended lever on prompt size. Where both limits apply
#                   the smaller one wins, so this is a real ceiling.
#
# `source_tokens` is not here: it belongs to one source and is supplied per file.
PROMPT_BUDGET = {
    "total_limit": 30_000,
    # Raised from 1200 to 1400 on 2026-08-17: at 1200 the ceiling was clipping
    # observations about classes and properties the source named directly.
    "context_tokens": 1_400,
    # Data-only ingestion shows the whole starter schema in every prompt,
    # paid from this separate allowance so it never competes with the
    # selected resources. A bigger schema falls back to word matching.
    # 3000 fits a glossary of ~40 classes with one-line meanings.
    "schema_tokens": 3_000,
    "fixed_prompt_tokens": 400,
    "output_reserve": 4_000,
    "safety_margin": 500,
}


def estimate_tokens(text, chars_per_token=DEFAULT_CHARS_PER_TOKEN):
    """A pessimistic token count: characters over a fixed divisor, rounded up."""
    return ceil(len(str(text)) / chars_per_token)


def context_allowance(total_limit, fixed_prompt_tokens, source_tokens,
                      output_reserve, safety_margin):
    """What is left for ontology context once everything else is paid for."""
    spent = fixed_prompt_tokens + source_tokens + output_reserve + safety_margin
    # An exhausted prompt leaves no context. It never leaves negative context.
    return max(0, total_limit - spent)


def estimator_name(count_tokens):
    """A readable name for whichever counter priced this result."""
    name = getattr(count_tokens, "__name__", type(count_tokens).__name__)
    return f"{name} (callable)"


def required(identifier, pool, chosen):
    """One item plus every dependency it still needs, in a stable order."""
    needed, seen, pending = [], set(), [identifier]
    while pending:
        name = pending.pop()
        if name in seen or name in chosen or name not in pool:
            continue
        seen.add(name)
        needed.append(name)
        pending.extend(pool[name]["dependencies"])
    return sorted(needed)


def fit_context_items(rendered_items, token_budget, count_tokens=estimate_tokens):
    """Select the highest-priority complete items that fit, and say what did not.

    Items are considered in the selector's priority order, so a direct match is
    offered a place before anything reached by expansion. An item is only taken
    together with the items it depends on, and only when the whole bundle fits.
    """
    budget = max(0, token_budget)
    pool = {entry["id"]: entry for entry in rendered_items}
    costs = {entry["id"]: count_tokens(entry["text"]) for entry in rendered_items}

    chosen, used = {}, 0
    for entry in sorted(rendered_items,
                        key=lambda entry: (entry["priority"], entry["id"])):
        if entry["id"] in chosen:
            continue
        bundle = required(entry["id"], pool, chosen)
        price = sum(costs[name] for name in bundle)
        if used + price <= budget:
            chosen.update({name: pool[name] for name in bundle})
            used += price
    return {
        "items": sorted(chosen.values(),
                        key=lambda entry: (entry["priority"], entry["id"])),
        "used_tokens": used,
        "budget_tokens": token_budget,
        "dropped_ids": sorted(name for name in pool if name not in chosen),
        "item_costs": costs,
        "estimator": estimator_name(count_tokens),
    }
