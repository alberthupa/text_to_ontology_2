"""The chat client: providers, empty answers, retries. No network."""

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from text_to_ontology import llm
from text_to_ontology.llm import InvalidResponseError, OpenRouterExtractor, ask_llm


def reply(content, finish_reason="stop"):
    body = json.dumps({"choices": [{"message": {"content": content},
                                    "finish_reason": finish_reason}]})
    return mock.MagicMock(__enter__=lambda self: io.StringIO(body),
                          __exit__=lambda *args: False)


def busy():
    return urllib.error.HTTPError("https://x", 429, "busy", {},
                                  io.BytesIO(b"rate limited"))


class Base(unittest.TestCase):
    environment = {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "or-key"}

    def ask(self, *answers, environment=None, model=None):
        """Call ask_llm with scripted HTTP answers; return result and requests."""
        sent = []

        def urlopen(request, timeout):
            sent.append(request)
            answer = answers[len(sent) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        settings = {key: value for key, value in os.environ.items()
                    if not key.startswith(("LLM_", "OPENROUTER_", "GEMINI_"))}
        settings.update(environment or self.environment)
        with mock.patch.dict(os.environ, settings, clear=True), \
                mock.patch("text_to_ontology.llm.load_env"), \
                mock.patch("text_to_ontology.llm.time.sleep"), \
                mock.patch("urllib.request.urlopen", side_effect=urlopen):
            result = ask_llm("prompt", model=model)
        return result, sent


class EmptyAnswerTest(Base):
    def test_no_content_is_an_invalid_response_naming_the_reason(self):
        with self.assertRaises(InvalidResponseError) as caught:
            self.ask(reply(None, "length"))
        self.assertIn("finish reason: length", str(caught.exception))

    def test_a_normal_answer_still_parses(self):
        result, _ = self.ask(reply('{"entities": []}'))
        self.assertEqual(result, {"entities": []})


class ProviderTest(Base):
    def test_openrouter_is_the_default(self):
        _, sent = self.ask(reply("{}"), environment={"OPENROUTER_API_KEY": "k"})
        self.assertIn("openrouter.ai", sent[0].full_url)
        body = json.loads(sent[0].data)
        self.assertEqual(body["model"], llm.DEFAULT_MODEL)
        self.assertNotIn("reasoning_effort", body)

    def test_google_uses_its_address_key_model_and_no_thinking(self):
        _, sent = self.ask(reply("{}"), environment={
            "LLM_PROVIDER": "google", "GEMINI_API_KEY": "g-key"})
        request = sent[0]
        self.assertIn("generativelanguage.googleapis.com", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer g-key")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "gemini-3.1-flash-lite")
        self.assertEqual(body["reasoning_effort"], "none")

    def test_google_model_and_thinking_can_be_configured(self):
        _, sent = self.ask(reply("{}"), environment={
            "LLM_PROVIDER": "google", "GEMINI_API_KEY": "g",
            "GEMINI_MODEL": "gemini-3.5-flash-lite",
            "GEMINI_REASONING_EFFORT": "low"})
        body = json.loads(sent[0].data)
        self.assertEqual((body["model"], body["reasoning_effort"]),
                         ("gemini-3.5-flash-lite", "low"))

    def test_a_missing_key_names_the_variable(self):
        with self.assertRaises(RuntimeError) as caught:
            self.ask(reply("{}"), environment={"LLM_PROVIDER": "google"})
        self.assertIn("GEMINI_API_KEY", str(caught.exception))

    def test_an_unknown_provider_is_a_clear_error(self):
        with self.assertRaises(RuntimeError) as caught:
            self.ask(reply("{}"), environment={"LLM_PROVIDER": "acme"})
        self.assertIn("google", str(caught.exception))

    def test_a_model_override_is_what_is_sent(self):
        _, sent = self.ask(reply("{}"), model="some/model")
        self.assertEqual(json.loads(sent[0].data)["model"], "some/model")


class RetryTest(Base):
    def test_a_busy_answer_is_retried(self):
        result, sent = self.ask(busy(), busy(), reply('{"ok": 1}'))
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(len(sent), 3)

    def test_retries_end(self):
        with self.assertRaises(RuntimeError) as caught:
            self.ask(busy(), busy(), busy(), busy())
        self.assertIn("429", str(caught.exception))


class ExtractorTest(unittest.TestCase):
    def test_the_extractor_sends_its_model_override(self):
        with mock.patch("text_to_ontology.llm.ask_llm",
                        return_value={}) as ask:
            OpenRouterExtractor(model="m/x").extract("p")
        self.assertEqual(ask.call_args.kwargs["model"], "m/x")


if __name__ == "__main__":
    unittest.main()
