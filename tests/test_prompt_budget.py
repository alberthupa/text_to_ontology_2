"""Proposal 5C: fitting complete context items into a stated token allowance."""

import unittest

from prompt_budget import (
    DEFAULT_CHARS_PER_TOKEN, context_allowance, estimate_tokens,
    fit_context_items,
)


RESULT_FIELDS = {
    "items", "used_tokens", "budget_tokens", "dropped_ids", "item_costs",
    "estimator",
}


def rendered(identifier, priority, text, section="declared", dependencies=()):
    return {"id": identifier, "section": section, "priority": priority,
            "text": text, "dependencies": list(dependencies)}


def words(text):
    """A stand-in for an exact tokenizer: one token per word."""
    return len(text.split())


def ids(items):
    return [item["id"] for item in items]


class EstimatorTest(unittest.TestCase):
    """Case 1: a conservative, explicit character estimate."""

    def test_an_empty_string_costs_nothing(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_ascii_text_rounds_up(self):
        self.assertEqual(estimate_tokens("abc"), 1)
        self.assertEqual(estimate_tokens("abcd"), 2)
        self.assertEqual(estimate_tokens("a" * 30), 10)

    def test_the_characters_per_token_value_is_configurable(self):
        self.assertEqual(estimate_tokens("abcd", chars_per_token=2), 2)
        self.assertEqual(estimate_tokens("abcd", chars_per_token=1), 4)
        self.assertEqual(DEFAULT_CHARS_PER_TOKEN, 3)

    def test_unicode_is_counted_by_character_not_by_byte(self):
        self.assertEqual(estimate_tokens("Łódź"), estimate_tokens("Lodz"))

    def test_newlines_and_blank_lines_are_counted(self):
        self.assertGreater(estimate_tokens("abc\ndef\n\nghi"), estimate_tokens("abc"))


class AllowanceTest(unittest.TestCase):
    """Case 2: the allowance is arithmetic on stated numbers, never a guess."""

    def test_every_part_of_the_prompt_is_subtracted(self):
        self.assertEqual(context_allowance(1000, 100, 200, 300, 50), 350)

    def test_an_exhausted_prompt_leaves_zero_rather_than_a_negative_budget(self):
        self.assertEqual(context_allowance(1000, 500, 600, 300, 50), 0)

    def test_a_source_that_fills_the_prompt_leaves_zero(self):
        self.assertEqual(context_allowance(1000, 0, 1000, 0, 0), 0)


class FitTest(unittest.TestCase):
    """Case 3: complete items, in priority order, within the allowance."""

    def items(self):
        return [
            rendered("b|second", 2, "b" * 30),
            rendered("a|first", 1, "a" * 30),
            rendered("c|third", 3, "c" * 30),
        ]

    def test_everything_fits_when_the_allowance_is_generous(self):
        result = fit_context_items(self.items(), 1000)
        self.assertEqual(set(result), RESULT_FIELDS)
        self.assertEqual(ids(result["items"]), ["a|first", "b|second", "c|third"])
        self.assertEqual(result["dropped_ids"], [])

    def test_the_highest_priority_item_wins_when_only_one_fits(self):
        result = fit_context_items(self.items(), 11)
        self.assertEqual(ids(result["items"]), ["a|first"])
        self.assertEqual(result["dropped_ids"], ["b|second", "c|third"])

    def test_the_used_cost_never_exceeds_the_allowance(self):
        for budget in range(0, 40):
            result = fit_context_items(self.items(), budget)
            self.assertLessEqual(result["used_tokens"], budget)

    def test_equal_priorities_fall_back_to_the_identifier(self):
        items = [rendered("z|last", 1, "z" * 30), rendered("a|first", 1, "a" * 30)]
        self.assertEqual(ids(fit_context_items(items, 1000)["items"]),
                         ["a|first", "z|last"])

    def test_a_zero_allowance_selects_nothing_and_reports_everything(self):
        result = fit_context_items(self.items(), 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["used_tokens"], 0)
        self.assertEqual(len(result["dropped_ids"]), 3)

    def test_no_item_is_ever_sliced(self):
        items = [rendered("a|huge", 1, "a" * 300), rendered("b|small", 2, "b" * 15)]
        result = fit_context_items(items, 10)
        self.assertEqual(ids(result["items"]), ["b|small"])
        self.assertEqual(result["dropped_ids"], ["a|huge"])
        for item in result["items"]:
            self.assertIn(item["text"], ("b" * 15,))

    def test_a_multiline_item_is_all_or_nothing(self):
        rule = rendered("restriction|whole", 1, "- [rule] line one\n  line two\n  line three")
        result = fit_context_items([rule], 5)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["dropped_ids"], ["restriction|whole"])
        generous = fit_context_items([rule], 500)
        self.assertEqual(generous["items"][0]["text"], rule["text"])

    def test_a_lower_priority_item_still_fits_after_a_dropped_one(self):
        items = [rendered("a|huge", 1, "a" * 300), rendered("b|small", 2, "b" * 15)]
        result = fit_context_items(items, 12)
        self.assertEqual(ids(result["items"]), ["b|small"])


class CounterTest(unittest.TestCase):
    """Case 4: the token counter is replaceable without touching selection."""

    def test_an_injected_counter_decides_the_costs(self):
        items = [rendered("a|one", 1, "one two three four five")]
        result = fit_context_items(items, 4, count_tokens=words)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["item_costs"]["a|one"], 5)

    def test_the_same_items_fit_under_a_more_precise_counter(self):
        items = [rendered("a|one", 1, "one two three four five")]
        result = fit_context_items(items, 6, count_tokens=words)
        self.assertEqual(ids(result["items"]), ["a|one"])

    def test_the_estimator_is_named_in_the_result(self):
        default = fit_context_items([], 10)
        injected = fit_context_items([], 10, count_tokens=words)
        self.assertIn("estimate_tokens", default["estimator"])
        self.assertIn("words", injected["estimator"])


class DependencyTest(unittest.TestCase):
    """Case 5: an item that needs another is only kept with it."""

    def items(self):
        return [
            rendered("example|one", 1, "e" * 30, dependencies=["resource|one"]),
            rendered("resource|one", 5, "r" * 30),
        ]

    def test_a_dependency_is_pulled_in_with_its_dependent(self):
        result = fit_context_items(self.items(), 1000)
        self.assertEqual(sorted(ids(result["items"])), ["example|one", "resource|one"])

    def test_a_dependent_is_dropped_when_the_pair_does_not_fit(self):
        result = fit_context_items(self.items(), 12)
        self.assertNotIn("example|one", ids(result["items"]))

    def test_a_missing_dependency_is_not_invented(self):
        items = [rendered("example|one", 1, "e" * 30, dependencies=["resource|gone"])]
        result = fit_context_items(items, 1000)
        self.assertEqual(ids(result["items"]), ["example|one"])

    def test_the_pair_cost_is_charged_once(self):
        result = fit_context_items(self.items(), 1000)
        self.assertEqual(result["used_tokens"],
                         sum(result["item_costs"][name]
                             for name in ("example|one", "resource|one")))


class DiagnosticTest(unittest.TestCase):
    """Case 6: what was kept, what was dropped, and what each cost."""

    def test_costs_are_reported_for_every_candidate(self):
        items = [rendered("a|one", 1, "a" * 30), rendered("b|two", 2, "b" * 300)]
        result = fit_context_items(items, 11)
        self.assertEqual(set(result["item_costs"]), {"a|one", "b|two"})
        self.assertEqual(result["item_costs"]["a|one"], 10)
        self.assertEqual(result["item_costs"]["b|two"], 100)

    def test_the_budget_is_echoed_unchanged(self):
        self.assertEqual(fit_context_items([], 123)["budget_tokens"], 123)

    def test_used_tokens_is_the_sum_of_the_selected_costs(self):
        items = [rendered("a|one", 1, "a" * 30), rendered("b|two", 2, "b" * 30)]
        result = fit_context_items(items, 1000)
        self.assertEqual(result["used_tokens"], 20)

    def test_dropped_identifiers_are_reported_in_a_stable_order(self):
        items = [rendered("z|last", 3, "z" * 300), rendered("a|first", 2, "a" * 300)]
        result = fit_context_items(items, 0)
        self.assertEqual(result["dropped_ids"], ["a|first", "z|last"])

    def test_nothing_supplied_is_a_valid_empty_result(self):
        result = fit_context_items([], 100)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["dropped_ids"], [])
        self.assertEqual(result["used_tokens"], 0)
        self.assertEqual(result["item_costs"], {})


class ImmutabilityTest(unittest.TestCase):
    """Case 7: budgeting reads the rendered items and changes none of them."""

    def test_the_supplied_items_are_unchanged(self):
        items = self.items = [rendered("a|one", 1, "a" * 30)]
        before = [dict(item) for item in items]
        fit_context_items(items, 5)
        self.assertEqual(items, before)


if __name__ == "__main__":
    unittest.main()
