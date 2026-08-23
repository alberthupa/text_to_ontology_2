# How prompt-context budgeting works

The important distinction is:

> `task_context` decides what is relevant. `prompt_budget` decides what relevant material fits.

`prepare_prompt_context()` does **not** receive the complete graph partitions,
skeleton, and pattern collection. Those complete views are used earlier by
`build_task_context()` to produce a smaller, relevant `ContextPackage`.

## Complete flow

```text
whole graph
  │
  ▼
build_ontology_views()
  │  complete schema / instance / support / skeleton / patterns
  ▼
select_task_context()
  │  relevance selection and per-kind caps
  ▼
ContextPackage
  │  selected schema / patterns / resources / examples
  ▼
prepare_prompt_context()
  │  rendering, token allowance, dependency-aware packing
  ▼
prompt context text + budget diagnostics + allowed existing_ids
```

There are therefore two separate narrowing stages.

## Stage 1: relevance selection

`task_context.build_task_context()` combines:

- concepts extracted from the source text;
- the five complete views returned by `ontology_views.build_ontology_views()`;
- the native entity catalog returned by `entity_lookup.entity_catalog()`.

It calls `select_task_context()`, which selects graph items that the current
source gives a reason to include. Every selected item receives a priority:

| Priority | Meaning |
|---:|---|
| 1 | A resource name or alias occurs directly in the source. |
| 2 | A class, property, or predicate label occurs directly in the source. |
| 3 | An extracted source concept matches a graph name or local name. |
| 4 | The source overlaps with words in a graph description. |
| 5 | A dependency is needed to understand a directly matched item. |
| 6 | An observed pattern is connected to a directly matched class or property. |
| 7 | A one-hop assertion or neighboring resource is relevant. |
| 8 | A pattern was reached indirectly through a matched resource. |

The selector also applies the caps in `task_context.DEFAULT_LIMITS`, including:

- 12 classes;
- 16 properties;
- 8 restrictions;
- 20 patterns;
- 15 resources;
- 12 examples.

The result is a `ContextPackage` containing only the selected candidates:

```text
concepts
schema
patterns
resources
examples
labels
diagnostics
```

Changing the prompt budget does not change these relevance decisions or caps.
It only changes which selected candidates survive the next stage.

## Stage 2: budget packing

In `ontology.py`, `budget_for(text)` copies `PROMPT_BUDGET` and adds the
estimated cost of the current source:

```python
def budget_for(text):
    return dict(PROMPT_BUDGET, source_tokens=estimate_tokens(text))
```

The default estimator is deliberately simple and conservative:

```text
source_tokens = ceil(number of source characters / 3)
```

`prepare_prompt_context()` then performs these steps.

### 1. Render every selected candidate

`render_context_items()` converts each selected class, property, restriction,
pattern, resource, and example into a complete text block.

At this point nothing has been dropped because of the token budget yet.

### 2. Calculate the effective context budget

With the current configuration, the calculation is:

```text
arithmetic remainder = max(
    0,
    total_limit
      - fixed_prompt_tokens
      - source_tokens
      - output_reserve
      - safety_margin
)

effective context budget = min(context_tokens, arithmetic remainder)
```

Current defaults from `prompt_budget.PROMPT_BUDGET`:

| Control | Current value | Effect when increased |
|---|---:|---|
| `context_tokens` | 1,400 | Normally allows more ontology context. This is the intended tuning control. |
| `total_limit` | 30,000 | Provides more arithmetic room, but normally does not bind. It is not a detected model context window. |
| `fixed_prompt_tokens` | 400 | Leaves less room for ontology context. |
| `output_reserve` | 4,000 | Leaves less room for ontology context. It is bookkeeping, not an OpenRouter response-token limit. |
| `safety_margin` | 500 | Leaves less room for ontology context. |
| `source_tokens` | Per file | A longer source can leave less room for ontology context. This value is calculated automatically. |

Where both `context_tokens` and the arithmetic limit exist, the smaller value
always wins.

### 3. Reserve formatting overhead

`assembly_overhead()` estimates the cost of section headings and line breaks.
That cost is reserved before items are packed:

```text
space available for items = effective context budget - formatting overhead
```

The overhead calculation is deliberately pessimistic so the final assembled
context does not exceed the effective budget.

### 4. Pack complete dependency bundles

`fit_context_items()` considers rendered items in this order:

```text
(priority, stable item ID)
```

For each item it:

1. Finds every dependency the item still needs.
2. Calculates the cost of the complete bundle.
3. Keeps the complete bundle if it fits.
4. Otherwise drops the complete bundle.
5. Continues checking later items.

An item is never sliced to fill the remaining space. A later, smaller item can
still fit after an earlier, larger bundle was rejected.

## Packing example

Assume formatting overhead has already been reserved and 200 tokens remain:

| Candidate | Priority | Bundle cost | Decision | Used tokens |
|---|---:|---:|---|---:|
| Existing resource | 1 | 90 | Keep | 90 |
| Directly matched property | 2 | 60 | Keep | 150 |
| Restriction plus required property | 5 | 120 | Drop: only 50 remain | 150 |
| Connected pattern | 6 | 45 | Keep | 195 |

The restriction bundle is dropped whole. The smaller pattern considered after
it can still fit.

## What changes in the returned result

`prepare_prompt_context()` returns:

```text
{
  text,
  budget,
  existing_ids
}
```

Changing the budget can affect each field:

### `text`

Contains the complete rendered items that survived packing, assembled into:

1. relevant declared ontology;
2. observed usage evidence;
3. relevant existing resources;
4. representative current assertions.

A smaller budget normally removes lower-priority patterns, neighbors, and
examples first, although bundle size also matters.

### `budget`

Contains diagnostics including:

- `items`: the rendered items that survived;
- `used_tokens`: the cost of kept item text;
- `budget_tokens`: the effective context budget before formatting overhead;
- `dropped_ids`: every rendered item that did not fit;
- `item_costs`: the estimated cost of each candidate item;
- `estimator`: the token-counting function used.

`used_tokens` reports item-text cost. Formatting overhead was reserved
separately.

### `existing_ids`

This contains only exact IDs from native resource cards that survived packing.

If a native resource card is dropped because it does not fit, its URI is also
removed from `existing_ids`. The LLM is therefore not allowed to return that URI
as an explicit `existing_id`, because it was not shown in the final prompt.

This does not remove the entity from merge-time identity resolution. Later,
`merge_policy` still searches the complete graph and may resolve the candidate
by its exact name and kind.

## Worked examples with the current defaults

### A normal source

```text
source characters:      3,000
source_tokens:          1,000
arithmetic remainder:  24,100
context_tokens ceiling: 1,400
effective budget:       1,400
```

The explicit `context_tokens` ceiling binds. This is the expected normal case.

### A very long source

```text
source characters:     75,000
source_tokens:         25,000
arithmetic remainder:     100
context_tokens ceiling: 1,400
effective budget:         100
```

After formatting overhead, few or no item bundles may fit.

### An exhausted context allowance

```text
source characters:     78,000
source_tokens:         26,000
arithmetic remainder:    -900 → clamped to 0
effective budget:           0
```

The prompt still contains the complete source and extraction instructions, but
the ontology-context block is empty and `existing_ids` is empty.

## What the budget does not control

The prompt-context budget does not:

- change which graph items initially count as relevant;
- change the caps in `task_context.DEFAULT_LIMITS`;
- truncate the raw source text;
- discover the actual model context window;
- directly set an OpenRouter response-token limit;
- prevent merge-time identity resolution against the complete graph.

For normal prompt-size tuning, `context_tokens` is the main control. Selection
caps should be changed separately only when the number of candidates reaching
the renderer also needs to change.
