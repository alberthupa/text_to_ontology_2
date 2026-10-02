"""The relevant subgraph for one question, and the conversation built on it."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from text_to_ontology import graph_chat, graph_scope
from text_to_ontology.graph_chat import ChatSession, chat_prompt
from text_to_ontology.graph_scope import (
    MAX_TRIPLES, SCOPE_FILE, parse_trig, select,
)
from text_to_ontology.operations import call
from text_to_ontology.prompts import PromptLibrary
from text_to_ontology.starter import import_publication
from text_to_ontology.workspace import Workspace

EX = Namespace("http://example.org/geo#")


def graph_with_noise(noise=400):
    graph = Graph()
    graph.add((EX.Poland, RDF.type, OWL.Class))
    graph.add((EX.Poland, RDFS.label, Literal("Poland")))
    graph.add((EX.Country, RDF.type, OWL.Class))
    graph.add((EX.Country, RDFS.label, Literal("Country")))
    graph.add((EX.Poland, RDFS.subClassOf, EX.Country))
    graph.add((EX.population, RDF.type, OWL.DatatypeProperty))
    graph.add((EX.population, RDFS.label, Literal("population")))
    graph.add((EX.poland, RDF.type, EX.Poland))
    graph.add((EX.poland, RDFS.label, Literal("Poland")))
    graph.add((EX.poland, EX.population, Literal(38000000)))
    graph.add((EX.Warsaw, RDF.type, EX.Poland))
    graph.add((EX.Warsaw, RDFS.label, Literal("Warsaw")))
    graph.add((EX.Warsaw, EX.capital_of, EX.poland))
    for index in range(noise):
        graph.add((EX.Warsaw, EX.filler, Literal(f"noise {index}")))
    return graph


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.graph = graph_with_noise()

    def test_the_question_decides_the_focus(self):
        scope = select("Tell me about Poland and its population", self.graph)
        self.assertEqual([str(node) for node in scope.nodes],
                         [str(EX.poland), str(EX.Warsaw)])
        self.assertEqual(scope.focus_source, "matched")

    def test_the_subgraph_holds_the_statements_and_the_declarations(self):
        scope = select("population of Poland", self.graph)
        self.assertIn((EX.poland, EX.population, Literal(38000000)),
                      scope.triples)
        # the schema behind the statement is included, even under noise
        self.assertIn((EX.population, RDF.type, OWL.DatatypeProperty),
                      scope.triples)
        self.assertIn((EX.Poland, RDFS.label, Literal("Poland")),
                      scope.triples)
        self.assertIn((EX.Poland, RDFS.subClassOf, EX.Country), scope.triples)
        self.assertIn((EX.Warsaw, EX.capital_of, EX.poland), scope.triples)

    def test_the_scope_is_capped_by_whole_triples_and_reports_what_it_dropped(self):
        scope = select("Poland", self.graph)
        self.assertLessEqual(len(scope.triples), MAX_TRIPLES)
        self.assertGreater(scope.dropped, 0)
        self.assertEqual(len(self.graph), 413)

    def test_a_well_connected_node_cannot_eat_the_whole_scope(self):
        # Warsaw has 400 statements of its own. Types and labels are ranked
        # first and a slice of the scope is reserved for declarations, so the
        # class it points at still arrives with its own definition.
        scope = select("Warsaw", self.graph)
        self.assertIn((EX.Warsaw, RDF.type, EX.Poland), scope.triples)
        self.assertIn((EX.Poland, RDF.type, OWL.Class), scope.triples)
        self.assertIn((EX.Poland, RDFS.label, Literal("Poland")), scope.triples)
        self.assertLessEqual(len(scope.triples), MAX_TRIPLES)
        self.assertGreater(scope.dropped, 0)

    def test_statements_that_use_a_property_bring_its_declaration_in(self):
        scope = select("population of Poland", self.graph)
        self.assertIn((EX.poland, EX.population, Literal(38000000)),
                      scope.triples)
        self.assertIn((EX.population, RDF.type, OWL.DatatypeProperty),
                      scope.triples)
        self.assertIn((EX.population, RDFS.label, Literal("population")),
                      scope.triples)

    def test_selection_is_deterministic(self):
        first = select("Poland population", self.graph)
        second = select("Poland population", self.graph)
        self.assertEqual(first.triples, second.triples)
        self.assertEqual(first.nodes, second.nodes)

    def test_a_plural_question_still_finds_its_subject(self):
        # The strict layer matches whole words, so "countries" misses the
        # class labelled "Country"; the bounded fallback catches that.
        scope = select("What countries are in the graph?", self.graph)
        self.assertEqual(scope.focus_source, "loose")
        self.assertIn(str(EX.poland), [str(node) for node in scope.nodes])
        self.assertTrue(scope.diagnostics["loose"])

    def test_the_strict_match_is_preferred_when_it_works(self):
        scope = select("Tell me about Poland", self.graph)
        self.assertEqual(scope.focus_source, "matched")
        self.assertFalse(scope.diagnostics["loose"])

    def test_a_class_name_brings_its_instances(self):
        graph = Graph()
        graph.add((EX.Tool, RDF.type, OWL.Class))
        graph.add((EX.Tool, RDFS.label, Literal("Tool")))
        graph.add((EX.drill, RDF.type, EX.Tool))
        graph.add((EX.drill, RDFS.label, Literal("Drill")))
        graph.add((EX.saw, RDF.type, EX.Tool))
        graph.add((EX.saw, RDFS.label, Literal("Saw")))
        matched = graph_scope.loose_matches("what tools are there?", graph)
        self.assertEqual([str(uri) for uri in matched],
                         [str(EX.drill), str(EX.saw)])

    def test_nothing_matching_is_an_empty_scope_not_a_crash(self):
        scope = select("nothing here matches at all", self.graph)
        self.assertEqual(scope.nodes, ())
        self.assertEqual(scope.focus_source, "empty")
        self.assertIsNone(scope.view()["focus"])

    def test_an_empty_graph_gives_an_empty_scope(self):
        scope = select("Poland", Graph())
        self.assertEqual(scope.triples, ())
        self.assertEqual(scope.render_for_model()["triples"], 0)

    def test_carry_over_keeps_the_conversation_on_topic(self):
        first = select("population of Poland", self.graph)
        second = select("and how does that compare?", self.graph,
                        carry_over=[str(node) for node in first.nodes])
        self.assertEqual(second.focus_source, "carried")
        self.assertIn(str(EX.poland),
                      [str(node) for node in second.nodes])

    def test_the_trig_face_parses_back(self):
        scope = select("population of Poland", self.graph)
        parsed = parse_trig(scope.trig_text())
        self.assertEqual(len(parsed), len(scope.triples))
        for triple in scope.triples:
            self.assertIn(triple, parsed)

    def test_the_view_face_is_one_declarative_directive(self):
        scope = select("population of Poland", self.graph)
        view = scope.view()
        self.assertEqual(view["replace"], [SCOPE_FILE])
        self.assertEqual(view["files"][0]["name"], SCOPE_FILE)
        self.assertEqual(view["mode"], "instances")
        self.assertTrue(view["clearFilters"])
        self.assertEqual(view["focus"], str(EX.poland))
        trig = view["files"][0]["trig"]
        self.assertIn("@prefix ns1: <http://example.org/geo#>", trig)
        self.assertIn("ns1:Poland", trig)
        self.assertEqual(len(parse_trig(trig)), len(scope.triples))

    def test_the_model_face_is_labelled_and_capped(self):
        scope = select("population of Poland", self.graph)
        rendered = scope.render_for_model(budget=150, graph=self.graph)
        self.assertGreater(rendered["triples"], 0)
        self.assertLessEqual(rendered["tokens"], 150)
        self.assertGreater(rendered["dropped"], 0)
        self.assertIn('"Poland"', rendered["text"])

    def test_naming_comes_once_and_statements_stay_short(self):
        # The header carries the names; ordinary statements do not repeat them.
        scope = select("population of Poland", self.graph)
        text = scope.render_for_model(graph=self.graph)["text"]
        self.assertTrue(text.startswith("PREFIXES"), text[:40])
        blocks = text.split("\n\n")
        prefixes_block, names_block = blocks[0], blocks[1]
        body = "\n\n".join(blocks[2:])
        self.assertIn("geo = <http://example.org/geo#>", prefixes_block)
        self.assertTrue(names_block.startswith("NAMES"), names_block[:20])
        # two subjects are called Poland (the class and the individual), and
        # each is named exactly once
        self.assertEqual(names_block.count('= "Poland"'), 2)
        statement = [line for line in body.splitlines()
                     if line.startswith("geo:poland a ")][0]
        self.assertEqual(statement, "geo:poland a geo:Poland")
        population = [line for line in body.splitlines()
                      if line.startswith("geo:poland geo:population")][0]
        self.assertNotIn("Poland", population)
        # the label statement itself still carries the literal, as it must
        self.assertIn('geo:poland rdfs:label "Poland"', body)

    def test_a_wider_budget_shows_more_of_the_same_subgraph(self):
        scope = select("population of Poland", self.graph)
        narrow = scope.render_for_model(budget=200, graph=self.graph)
        wide = scope.render_for_model(budget=2000, graph=self.graph)
        self.assertGreater(wide["triples"], narrow["triples"])
        self.assertGreaterEqual(wide["dropped"], 0)
        self.assertEqual(scope.triples, select("population of Poland",
                                               self.graph).triples)

    def test_the_summary_is_plain_data(self):
        summary = select("population of Poland", self.graph).summary()
        self.assertEqual(summary["triples"], len(select(
            "population of Poland", self.graph).triples))
        self.assertIn("focus_source", summary)
        self.assertIsInstance(summary["nodes"], list)


class FakeAsk:
    """A model that never sees the network, and remembers what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []
        self.systems = []

    def __call__(self, prompt, system=None):
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]


class ChatSessionTest(unittest.TestCase):
    def setUp(self):
        self.graph = graph_with_noise(noise=0)
        self.ask = FakeAsk("About 38 million.")

    def session(self):
        return ChatSession()

    def test_a_turn_answers_from_the_selected_subgraph(self):
        session = self.session()
        outcome = session.ask("How many people live in Poland?", self.graph,
                              self.ask)
        self.assertEqual(outcome["answer"], "About 38 million.")
        self.assertIn("population", self.ask.prompts[0])
        self.assertIn("How many people live in Poland?", self.ask.prompts[0])
        self.assertIn("only", self.ask.systems[0].lower())
        self.assertEqual(len(session.turns), 2)

    def test_the_transcript_carries_a_view_only_for_the_newest_turns(self):
        session = self.session()
        for index in range(graph_chat.TRANSCRIPT_VIEWS // 2 + 2):
            session.ask(f"population of Poland ({index})", self.graph, self.ask)
        transcript = session.transcript()
        views = [turn for turn in transcript if turn["view"]]
        self.assertTrue(views)
        self.assertLessEqual(len(views), graph_chat.TRANSCRIPT_VIEWS)
        self.assertTrue(transcript[-1]["view"])
        self.assertIsNone(transcript[0]["view"])
        self.assertEqual(transcript[-1]["view"]["mode"], "instances")
        self.assertIn("files", transcript[-1]["view"])
        # the summary stays for every turn, view or not
        self.assertTrue(all(turn["scope"] for turn in transcript))

    def test_the_transcript_keeps_the_subgraph_behind_each_answer(self):
        session = self.session()
        session.ask("population of Poland", self.graph, self.ask)
        transcript = session.transcript()
        self.assertEqual([turn["role"] for turn in transcript],
                         ["you", "graph"])
        self.assertEqual([turn["index"] for turn in transcript], [1, 1])
        self.assertTrue(transcript[1]["scope"]["nodes"])
        self.assertGreater(transcript[1]["scope"]["triples"], 0)
        self.assertEqual(transcript[1]["role"], "graph")

    def test_a_follow_up_carries_the_topic_over(self):
        session = self.session()
        session.ask("population of Poland", self.graph, self.ask)
        session.ask("and what about its capital?", self.graph, self.ask)
        self.assertIn(str(EX.poland), session.focus)
        self.assertIn("population", self.ask.prompts[1])

    def test_the_recent_history_reaches_the_prompt(self):
        session = self.session()
        session.ask("population of Poland", self.graph, self.ask)
        session.ask("and its capital?", self.graph, self.ask)
        self.assertIn("About 38 million.", self.ask.prompts[1])

    def test_reset_forgets_everything(self):
        session = self.session()
        session.ask("population of Poland", self.graph, self.ask)
        state = session.reset()
        self.assertEqual(state["turns"], [])
        self.assertEqual(session.focus, ())
        self.assertEqual(session.recent(), "(nothing yet)")

    def test_an_empty_question_is_refused(self):
        with self.assertRaises(ValueError):
            self.session().ask("   ", self.graph, self.ask)

    def test_a_question_about_nothing_says_so_in_the_prompt(self):
        session = self.session()
        session.ask("zzzz nothing matches", self.graph, self.ask)
        self.assertIn("nothing in the graph matches", self.ask.prompts[0])

    def test_the_prompt_helper_matches_a_real_turn(self):
        session = self.session()
        scope = select("population of Poland", self.graph)
        prompt = chat_prompt("population of Poland", scope, "(nothing yet)",
                             graph=self.graph)
        self.assertIn("population of Poland", prompt)
        self.assertIn("selected triples fit the prompt", prompt)

    def test_a_session_uses_an_edited_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            library = PromptLibrary(Path(directory) / "prompts.local.json")
            library.set("chat_user", "MARKER ${question}\\n${subgraph}")
            session = ChatSession(library=library)
            session.ask("population of Poland", self.graph, self.ask)
            self.assertTrue(self.ask.prompts[0].startswith("MARKER"))
            self.assertNotIn("WHAT WAS ALREADY SAID", self.ask.prompts[0])


class ChatWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.extractor = FakeAsk("Poland has about 38 million people.")
        self.extractor.model = lambda: "fake"
        self.extractor.extract_text = self.extractor
        self.workspace = Workspace(
            graph_path=self.base / "ontology.trig",
            sources_dir=self.base / "inbox", extractor=self.extractor)
        # put the geography graph in the workspace's own store
        _publication, _summary = import_publication(
            _turtle(), "geo.ttl", self.workspace.names)
        self.workspace.store.publish(_publication)

    def test_the_chat_operations_work_end_to_end(self):
        started = call(self.workspace, "chat.ask",
                       {"message": "How many people live in Poland?"})
        self.assertTrue(started["ok"], started)
        while self.workspace.progress.running_now:
            import time
            time.sleep(0.01)
        result = self.workspace.progress.snapshot(
            self.workspace.progress.job_id)["result"]
        self.assertTrue(result["ok"], result)
        self.assertIn("38 million", result["answer"])
        self.assertTrue(result["scope"]["nodes"])
        self.assertIn("view", result["scope"])
        self.assertEqual(len(result["turns"]), 2)

        state = call(self.workspace, "chat.state", {})
        self.assertEqual(len(state["turns"]), 2)
        cleared = call(self.workspace, "chat.reset", {})
        self.assertEqual(cleared["turns"], [])

    def test_a_missing_question_is_reported(self):
        answer = call(self.workspace, "chat.ask", {"message": "  "})
        self.assertFalse(answer["ok"])
        self.assertIn("question", answer["error"])

    def test_a_running_job_refuses_a_second_chat_turn(self):
        started = call(self.workspace, "chat.ask", {"message": "Poland?"})
        self.assertTrue(started["ok"], started)
        second = call(self.workspace, "chat.ask", {"message": "Poland again?"})
        # either the first turn already finished, or the slot refused it
        if not second["ok"]:
            self.assertIn("already running", second["error"])
        while self.workspace.progress.running_now:
            import time
            time.sleep(0.01)

    def test_an_extractor_that_cannot_answer_with_text_is_reported(self):
        class NoText:
            def model(self):
                return "no-text"

            def extract(self, prompt):
                return {}

        workspace = Workspace(graph_path=self.base / "other.trig",
                              sources_dir=self.base / "inbox2",
                              extractor=NoText())
        answer = workspace.chat_ask("anything")
        self.assertFalse(answer["ok"])
        self.assertIn("cannot answer with text", answer["error"])


def _turtle():
    return """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix geo: <http://example.org/geo#> .
geo: a owl:Ontology .
geo:Poland a owl:Class ; rdfs:label "Poland" .
geo:Country a owl:Class ; rdfs:label "Country" .
geo:population a owl:DatatypeProperty ; rdfs:label "population" .
geo:poland a geo:Poland ; rdfs:label "Poland" ; geo:population 38000000 .
geo:warsaw a geo:Poland ; rdfs:label "Warsaw" .
"""


if __name__ == "__main__":
    unittest.main()
