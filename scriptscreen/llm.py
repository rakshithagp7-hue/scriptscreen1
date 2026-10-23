import json
import re

import requests

from . import config
from .util import cache_file, key_of, retry


def available():
    if config.OFFLINE:
        return False
    if config.LLM_PROVIDER == "gemini":
        return bool(config.GEMINI_API_KEY)
    if config.LLM_PROVIDER == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def _check(r):
    """Like raise_for_status, but keeps the server's error message so the log says WHY it failed."""
    if not r.ok:
        raise requests.HTTPError(f"HTTP {r.status_code}: {r.text[:200]}")


def _gemini(prompt, system):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    r = requests.post(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body, timeout=120)
    _check(r)
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai(prompt, system):
    r = requests.post(
        f"{config.OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        json={
            "model": config.OPENAI_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        },
        timeout=120,
    )
    _check(r)
    return r.json()["choices"][0]["message"]["content"]


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM reply")
    return json.loads(text[start:end + 1])


def call_json(prompt, system, trace=None, label="llm"):
    """Cached + retried JSON call. Same prompt => no API quota used.
    5 tries with growing waits (8, 16, 32, 64 s) so per-minute rate limits (429) can clear."""
    key = key_of(config.LLM_PROVIDER, config.GEMINI_MODEL, config.OPENAI_MODEL, system, prompt)
    path = cache_file("llm", key, "json")
    if path.exists():
        if trace:
            trace.log(label, "cache hit (no API call)")
        return json.loads(path.read_text(encoding="utf-8"))

    fn = _gemini if config.LLM_PROVIDER == "gemini" else _openai
    data = retry(lambda: _parse_json(fn(prompt, system)), tries=5, base=8, trace=trace, label=label)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def forget(prompt, system):
    """Delete a cached reply that turned out to be unusable, so it is not reused next time."""
    key = key_of(config.LLM_PROVIDER, config.GEMINI_MODEL, config.OPENAI_MODEL, system, prompt)
    cache_file("llm", key, "json").unlink(missing_ok=True)