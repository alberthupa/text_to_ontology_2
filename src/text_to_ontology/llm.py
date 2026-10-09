"""Tiny chat-completions client: OpenRouter or Google, one request shape.

Both providers speak the OpenAI chat-completions format, so one request
builder serves both; only the address, the key, the model name, and one or
two extra fields differ. Pick the provider in `.env`:

    LLM_PROVIDER=openrouter       (default)  OPENROUTER_API_KEY, OPENROUTER_MODEL
    LLM_PROVIDER=google                      GEMINI_API_KEY, GEMINI_MODEL

Google's models think before answering unless told not to;
GEMINI_REASONING_EFFORT (default "none") says how much. Some models refuse
"none" and need "low"; an empty value sends nothing.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


OLD_DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b:nitro"
DEFAULT_MODEL = "google/gemma-4-26b-a4b-it:free"
MAX_OUTPUT_TOKENS = 4_096
SYSTEM_PROMPT = "Extract knowledge. Return only JSON."

# One entry per provider: where to send, which key, which model by default.
PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key": "OPENROUTER_API_KEY",
        "model": "OPENROUTER_MODEL",
        "default_model": DEFAULT_MODEL,
        "headers": {"X-OpenRouter-Title": "Simple Text to Ontology"},
    },
    "google": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/"
               "chat/completions",
        "key": "GEMINI_API_KEY",
        "model": "GEMINI_MODEL",
        # Small and fast: about 2 seconds per extraction window.
        "default_model": "gemini-3.1-flash-lite",
        "headers": {},
    },
}

# Busy or rate-limited: wait and ask again, at most this many times.
RETRY_STATUSES = {429, 500, 502, 503}
RETRY_WAITS = (2, 5, 15)


class InvalidResponseError(RuntimeError):
    """The model answered, but the answer is not one parseable JSON object."""


def load_env(path=None):
    """Load simple KEY=value lines from a .env in the working directory.

    A variable already set in the shell wins over the same name in .env.
    """
    path = Path(path) if path else Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)


def provider_name():
    """Which provider answers: LLM_PROVIDER, openrouter by default."""
    load_env()
    name = os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()
    if name not in PROVIDERS:
        raise RuntimeError(f"LLM_PROVIDER={name!r} is not known; use one of: "
                           + ", ".join(sorted(PROVIDERS)))
    return name


def provider():
    return PROVIDERS[provider_name()]


def model_name():
    """The configured model of the configured provider."""
    settings = provider()
    return os.environ.get(settings["model"], settings["default_model"])


def max_output_tokens():
    """The output cap: MAX_OUTPUT_TOKENS, or OPENROUTER_MAX_TOKENS when set.

    Raise it for a source whose extraction is long (a whole technology
    stack); the default stays low so OpenRouter reserves little credit.
    """
    load_env()
    return int(os.environ.get("OPENROUTER_MAX_TOKENS", MAX_OUTPUT_TOKENS))


def _request_body(prompt, system, model):
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_output_tokens(),
        "messages": [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    if provider_name() == "google":
        effort = os.environ.get("GEMINI_REASONING_EFFORT", "none").strip()
        if effort:
            body["reasoning_effort"] = effort
    return body


def ask_choice(prompt, system=None, model=None):
    """Send one prompt; return the first answer choice of the response."""
    settings = provider()
    key = os.environ.get(settings["key"])
    if not key:
        raise RuntimeError(f"Set {settings['key']} first")
    body = json.dumps(_request_body(prompt, system, model or model_name()))
    for attempt in range(len(RETRY_WAITS) + 1):
        request = urllib.request.Request(
            settings["url"], data=body.encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     **settings["headers"]})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)["choices"][0]
        except urllib.error.HTTPError as error:
            message = error.read().decode(errors="replace")
            if error.code in RETRY_STATUSES and attempt < len(RETRY_WAITS):
                time.sleep(RETRY_WAITS[attempt])
                continue
            raise RuntimeError(
                f"{provider_name()} error {error.code}: {message}") from error


def ask_llm_text(prompt, system=None, model=None):
    """Send one prompt and return the answer as plain text.

    The graph chat needs prose, not the extraction contract's JSON, so this is
    the same request without the JSON parse.
    """
    choice = ask_choice(prompt, system, model)
    return str(choice["message"].get("content") or "").strip()


def ask_llm(prompt, system=None, model=None):
    """Send one prompt and return its JSON object.

    The system message defaults to `SYSTEM_PROMPT`; the pipeline passes the
    `extraction_system` prompt instead, which a user may have edited.
    """
    choice = ask_choice(prompt, system, model)
    answer = choice["message"].get("content")
    if not answer:
        # A reasoning model can spend every output token thinking and answer
        # nothing; that is a bad answer to repair, not a crash.
        raise InvalidResponseError(
            "The model returned no answer (finish reason: "
            f"{choice.get('finish_reason')}); it may have spent all "
            f"{max_output_tokens()} output tokens on reasoning"
        )

    # Also accept JSON wrapped in a Markdown code block.
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end < 0:
        raise InvalidResponseError(f"The model did not return JSON:\n{answer}")
    try:
        return json.loads(answer[start : end + 1])
    except json.JSONDecodeError as error:
        raise InvalidResponseError(
            f"The model returned invalid JSON:\n{answer}"
        ) from error


class OpenRouterExtractor:
    """The real extractor: one chat completion per prompt.

    Despite the name it serves every provider in PROVIDERS; LLM_PROVIDER picks
    one. This adapter is where environment loading lives; the core pipeline
    never reads environment variables itself.
    """

    def __init__(self, model=None, system_prompt=None):
        self.model_override = model
        self.system_prompt = system_prompt

    def model(self):
        """The model that answers, as reports name it."""
        return self.model_override if self.model_override else model_name()

    def _model_argument(self):
        """The model keyword, only when this extractor overrides it."""
        return {"model": self.model_override} if self.model_override else {}

    def extract(self, prompt):
        """Send one prompt and return its parsed JSON answer."""
        return ask_llm(prompt, system=self.system_prompt,
                       **self._model_argument())

    def extract_text(self, prompt, system=None):
        """Send one prompt and return the answer as plain text.

        `system` wins over this extractor's own system message, so the graph
        chat can use the chat prompt even though the same client also extracts
        JSON for ingestion.
        """
        return ask_llm_text(prompt, system=system or self.system_prompt,
                            **self._model_argument())
