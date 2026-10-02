"""A conversation about the graph, one bounded subgraph at a time.

A turn is: select the part of the graph this question is about
(`graph_scope.select`), render it, send the question with a little history, and
remember both the answer and the subgraph that produced it. The subgraph is
kept in the transcript, so a reader can always see what the model was shown -
which is the whole point of talking to a graph instead of to a model.

Asking is injected (`ask(prompt, system) -> text`), so this module never talks
to a network, and a test can answer from a table.
"""

from dataclasses import dataclass, field

from . import graph_scope, prompts

HISTORY_TURNS = 6
MAX_TURNS = 200
# Only the newest turns keep the subgraph text; older turns keep the summary,
# so a long conversation does not grow without bound.
TRANSCRIPT_VIEWS = 20
MAX_FOCUS = graph_scope.DEFAULT_LIMITS["focus"]


@dataclass
class Turn:
    """One thing said, and the subgraph behind it when there is one."""

    role: str                    # "you" or "graph"
    text: str
    scope: dict = None           # the scope summary used for this turn
    index: int = 0
    view: dict = None            # the view directive that draws that subgraph


@dataclass
class ChatSession:
    """The conversation so far, and what it is currently about."""

    library: object = None
    history_turns: int = HISTORY_TURNS
    turns: list = field(default_factory=list)
    focus: tuple = ()

    # ---------- reading ----------

    def transcript(self):
        """Every turn; the newest ones also carry the subgraph they used."""
        newest = len(self.turns) - TRANSCRIPT_VIEWS
        return [{"role": turn.role, "text": turn.text, "scope": turn.scope,
                 "index": turn.index,
                 "view": turn.view if position >= newest else None}
                for position, turn in enumerate(self.turns)]

    def recent(self):
        """The last few turns as plain text for the prompt."""
        recent = self.turns[-self.history_turns:] if self.history_turns else []
        if not recent:
            return "(nothing yet)"
        return "\n".join(f"{turn.role}: {turn.text}" for turn in recent)

    def state(self):
        return {"ok": True, "turns": self.transcript(),
                "focus": list(self.focus)}

    # ---------- writing ----------

    def reset(self):
        self.turns = []
        self.focus = ()
        return self.state()

    def ask(self, message, graph, ask, limits=None, budget=None, on_step=None):
        """One turn: select, render, ask, remember.

        `ask(prompt, system)` returns the model's text answer. `on_step` is
        called once, after selection, with `(scope, rendered)` so a frontend can
        show how much of the graph is about to be sent.
        """
        message = str(message or "").strip()
        if not message:
            raise ValueError("no question was given")
        scope = graph_scope.select(message, graph, carry_over=self.focus,
                                   limits=limits)
        rendered = scope.render_for_model(budget=budget, graph=graph)
        if on_step is not None:
            on_step(scope, rendered)
        index = len(self.turns) // 2 + 1
        self.turns.append(Turn("you", message, scope.summary(), index))
        answer = ask(
            prompts.render("chat_user", {
                "question": message,
                "history": self.recent(),
                "scope_note": _scope_note(scope, rendered),
                "subgraph": rendered["text"] or "(nothing in the graph matches)",
            }, library=self.library),
            prompts.render("chat_system", library=self.library),
        )
        summary = scope.summary()
        summary["rendered"] = rendered["triples"]
        summary["dropped_for_space"] = rendered["dropped"]
        self.turns.append(Turn("graph", str(answer), summary, index,
                               view=scope.view()))
        self._remember(scope)
        self.turns = self.turns[-MAX_TURNS:]
        return {"answer": str(answer), "scope": scope, "summary": summary}

    def _remember(self, scope):
        """What the next question may still be about: newest matched first."""
        fresh = [str(node) for node in scope.nodes]
        kept = [node for node in self.focus if node not in fresh]
        self.focus = tuple((fresh + kept)[:MAX_FOCUS])


def _scope_note(scope, rendered):
    """One honest line about how much of the graph the model was shown."""
    note = (f"{rendered['triples']} of {len(scope.triples)} selected triples "
            f"fit the prompt")
    if rendered["dropped"]:
        note += (f"; {rendered['dropped']} related triples were left out for "
                 f"space")
    if scope.dropped:
        note += f"; {scope.dropped} more were beyond the scope limit"
    return note + "."


def chat_prompt(question, scope, history, graph=None, library=None,
                budget=None):
    """The exact prompt one turn would send; handy for a preview or a test."""
    rendered = scope.render_for_model(budget=budget, graph=graph)
    return prompts.render("chat_user", {
        "question": question,
        "history": history or "(nothing yet)",
        "scope_note": _scope_note(scope, rendered),
        "subgraph": rendered["text"] or "(nothing in the graph matches)",
    }, library=library)
