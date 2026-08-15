"""Tiny OpenRouter client used by ontology.py."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "openrouter/pareto-code:nitro"


def load_env(path=None):
    """Load simple KEY=value lines from the .env beside this file."""
    path = Path(path) if path else Path(__file__).with_name(".env")
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


def model_name():
    load_env()
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)


def ask_llm(prompt):
    """Send one prompt to OpenRouter and return its JSON object."""
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY first")

    body = json.dumps({
        "model": model_name(),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Extract knowledge. Return only JSON."},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "Simple Text to Ontology",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.load(response)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as error:
        message = error.read().decode(errors="replace")
        raise RuntimeError(f"OpenRouter error {error.code}: {message}") from error

    # Also accept JSON wrapped in a Markdown code block.
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"The model did not return JSON:\n{answer}")
    try:
        return json.loads(answer[start:end + 1])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"The model returned invalid JSON:\n{answer}") from error
