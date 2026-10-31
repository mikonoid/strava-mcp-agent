"""Minimal LLM client for Anthropic and OpenAI-compatible APIs (incl. Ollama)."""
import json

import requests

from . import config

SYSTEM_PROMPT = """You are an experienced endurance coach analysing an athlete's training data.
The data comes from Strava and/or Garmin Connect as JSON.

Training load model used in the data (minutes of activity per day as load proxy):
- ATL = 7-day average, CTL = 42-day average, TSB = CTL - ATL.
- TSB > 10: fresh; -10..10: optimal training zone; < -10: accumulated fatigue.

Guidelines:
- Be concrete: reference real dates, numbers and trends from the data.
- Flag overtraining / injury-risk signals (sudden volume jumps >10-15%/week, low TSB,
  rising resting HR, poor sleep) and also under-training.
- When asked for a plan, give a day-by-day table with type, duration/distance and intensity.
- Keep it concise and use Markdown headings, bullet lists and tables.
- Answer in the same language as the user's question."""

DEFAULT_QUESTION = (
    "Analyse my training over the last 2-3 weeks: load, consistency, recovery and risks. "
    "Then suggest a plan for the next 7 days."
)


class LLMError(RuntimeError):
    pass


def analyze(context: dict, question: str | None = None) -> str:
    question = (question or "").strip() or DEFAULT_QUESTION
    user_message = (
        f"{question}\n\nToday's training data (JSON):\n```json\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}\n```"
    )
    provider = config.llm_provider()
    if provider == "anthropic":
        return _anthropic(user_message)
    return _openai(user_message)


def _raise_for(resp: requests.Response, provider: str) -> None:
    if resp.ok:
        return
    try:
        detail = resp.json().get("error", resp.text)
        if isinstance(detail, dict):
            detail = detail.get("message", detail)
    except ValueError:
        detail = resp.text
    raise LLMError(f"{provider} API error {resp.status_code}: {detail}")


def _anthropic(user_message: str) -> str:
    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.llm_model(),
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=180,
    )
    _raise_for(resp, "Anthropic")
    blocks = resp.json().get("content", [])
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _openai(user_message: str) -> str:
    base_url = (config.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    headers = {"content-type": "application/json"}
    if key := config.get("OPENAI_API_KEY"):
        headers["authorization"] = f"Bearer {key}"
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": config.llm_model(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        },
        timeout=300,
    )
    _raise_for(resp, "OpenAI")
    return resp.json()["choices"][0]["message"]["content"].strip()
