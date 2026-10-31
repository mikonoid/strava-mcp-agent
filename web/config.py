"""Read and persist settings in the shared .env file."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("ENV_FILE", ROOT / ".env"))

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-6.1-sol",
}

# (env key, label, is_secret)
SETTINGS_FIELDS = [
    ("STRAVA_CLIENT_ID", "Strava Client ID", False),
    ("STRAVA_CLIENT_SECRET", "Strava Client Secret", True),
    ("GARMIN_EMAIL", "Garmin email", False),
    ("GARMIN_PASSWORD", "Garmin password", True),
    ("LLM_PROVIDER", "AI provider", False),
    ("LLM_MODEL", "AI model", False),
    ("ANTHROPIC_API_KEY", "Anthropic API key", True),
    ("OPENAI_API_KEY", "OpenAI API key", True),
    ("OPENAI_BASE_URL", "OpenAI-compatible base URL", False),
]
SECRET_KEYS = {key for key, _, secret in SETTINGS_FIELDS if secret}


def load() -> None:
    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE, override=True)


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_\-.:/@+=,]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(values: dict[str, str]) -> None:
    # Rewrite in place (not via temp file + rename) so it works with a Docker bind-mounted .env
    ENV_FILE.touch(exist_ok=True)
    lines = ENV_FILE.read_text().splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if "=" in line and not line.lstrip().startswith("#") and key in values:
            lines[i] = f"{key}={_quote(values[key])}"
            seen.add(key)
    lines += [f"{key}={_quote(value)}" for key, value in values.items() if key not in seen]
    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.environ.update(values)


def strava_app_configured() -> bool:
    return bool(get("STRAVA_CLIENT_ID") and get("STRAVA_CLIENT_SECRET"))


def strava_connected() -> bool:
    return strava_app_configured() and bool(get("STRAVA_REFRESH_TOKEN"))


def garmin_configured() -> bool:
    return bool(get("GARMIN_EMAIL") and get("GARMIN_PASSWORD"))


def llm_provider() -> str:
    provider = get("LLM_PROVIDER", "anthropic").lower()
    return provider if provider in DEFAULT_MODELS else "anthropic"


def llm_configured() -> bool:
    provider = llm_provider()
    if provider == "anthropic":
        return bool(get("ANTHROPIC_API_KEY"))
    # Local OpenAI-compatible servers (e.g. Ollama) don't need a key
    return bool(get("OPENAI_API_KEY") or get("OPENAI_BASE_URL"))


def llm_model() -> str:
    return get("LLM_MODEL") or DEFAULT_MODELS[llm_provider()]
