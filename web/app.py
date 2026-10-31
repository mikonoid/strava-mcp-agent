"""FastAPI web dashboard: `python -m web` then open http://localhost:8000"""
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config, llm
from .services import services

HERE = Path(__file__).resolve().parent
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_SCOPE = "read,activity:read_all,profile:read_all"

MESSAGES = {
    "saved": ("success", "Settings saved."),
    "strava_connected": ("success", "Strava connected."),
    "strava_disconnected": ("success", "Strava disconnected."),
    "strava_needs_app": ("error", "Enter your Strava Client ID and Secret first."),
    "strava_denied": ("error", "Strava authorization was cancelled or failed."),
    "strava_state": ("error", "Strava authorization expired — please try again."),
    "strava_scope": ("error", "Please allow access to activities (activity:read_all) on the Strava page."),
    "strava_token": ("error", "Could not exchange the Strava code for a token. Check Client ID / Secret."),
    "refreshed": ("success", "Data refreshed."),
    "welcome": ("info", "Welcome! Connect Strava and/or Garmin to get started."),
}

app = FastAPI(title="Training dashboard", docs_url=None, redoc_url=None)
allowed_hosts = [h.strip() for h in config.get("WEB_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

_oauth_states: dict[str, float] = {}


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    """Block cross-site POSTs so other websites can't change settings or trigger requests."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if not origin or urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"error": "Cross-origin request blocked"}, status_code=403)
    return await call_next(request)


# ── Template helpers ──────────────────────────────────────────────────
def fmt_duration(minutes: float | None) -> str:
    if not minutes:
        return "—"
    total = int(round(minutes))
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total}m"


def fmt_pace(seconds: float | None) -> str:
    if not seconds:
        return "—"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


templates.env.filters["duration"] = fmt_duration
templates.env.filters["pace"] = fmt_pace


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    msg = MESSAGES.get(request.query_params.get("msg", ""))
    ctx.setdefault("sources", services.sources())
    return templates.TemplateResponse(request, name, {"flash": msg, **ctx})


def _error_message(e: Exception) -> str:
    if isinstance(e, requests.HTTPError) and e.response is not None:
        status = e.response.status_code
        hint = {
            401: "Authorization failed — reconnect Strava in Settings.",
            403: "Missing permission — click “Reconnect with Strava” in Settings and allow access to activities.",
            429: "API rate limit reached — try again in ~15 minutes.",
        }.get(status, "")
        return f"{status} {e.response.reason}. {hint}".strip()
    return str(e)


def _error_json(e: Exception) -> JSONResponse:
    return JSONResponse({"error": _error_message(e)}, status_code=502)


# ── Pages ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, source: str | None = None):
    sources = services.sources()
    if not sources:
        return RedirectResponse("/settings?msg=welcome", status_code=303)
    source = source if source in sources else sources[0]
    try:
        profile = services.profile()
    except Exception:
        profile = None
    return render(
        request,
        "dashboard.html",
        source=source,
        profile=profile,
        garmin=services.garmin is not None,
        llm_ready=config.llm_configured(),
        llm_provider=config.llm_provider(),
        llm_model=config.llm_model(),
        default_question=llm.DEFAULT_QUESTION,
    )


@app.get("/activity/{activity_id}", response_class=HTMLResponse)
def activity_page(request: Request, activity_id: int):
    try:
        activity = services.strava_activity(activity_id)
        error = None
    except Exception as e:
        activity, error = None, str(e)
    return render(request, "activity.html", activity=activity, error=error)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    values = {key: ("" if secret else config.get(key)) for key, _, secret in config.SETTINGS_FIELDS}
    saved_secrets = {key for key in config.SECRET_KEYS if config.get(key)}
    return render(
        request,
        "settings.html",
        values=values,
        saved_secrets=saved_secrets,
        strava_connected=config.strava_connected(),
        llm_provider=config.llm_provider(),
        default_models=config.DEFAULT_MODELS,
        env_file=str(config.ENV_FILE),
        callback_url=str(request.url_for("strava_callback")),
    )


@app.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    updates: dict[str, str] = {}
    for key, _, secret in config.SETTINGS_FIELDS:
        value = str(form.get(key, "")).strip()
        if secret and not value:
            continue  # empty password field = keep current value
        updates[key] = value
    if updates.get("STRAVA_CLIENT_ID", config.get("STRAVA_CLIENT_ID")) != config.get("STRAVA_CLIENT_ID"):
        updates["STRAVA_REFRESH_TOKEN"] = ""
    config.save(updates)
    services.reload()
    return RedirectResponse("/settings?msg=saved", status_code=303)


@app.post("/refresh")
def refresh(request: Request):
    services.cache.clear()
    back = urlparse(request.headers.get("referer", "/"))
    return RedirectResponse(f"{back.path or '/'}?msg=refreshed", status_code=303)


# ── Strava OAuth ──────────────────────────────────────────────────────
@app.get("/auth/strava")
def strava_login(request: Request):
    if not config.strava_app_configured():
        return RedirectResponse("/settings?msg=strava_needs_app", status_code=303)
    now = time.time()
    for s, ts in list(_oauth_states.items()):
        if now - ts > 600:
            _oauth_states.pop(s, None)
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = now
    params = urlencode({
        "client_id": config.get("STRAVA_CLIENT_ID"),
        "redirect_uri": str(request.url_for("strava_callback")),
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": STRAVA_SCOPE,
        "state": state,
    })
    return RedirectResponse(f"{STRAVA_AUTH_URL}?{params}", status_code=303)


@app.get("/auth/strava/callback", name="strava_callback")
def strava_callback(code: str | None = None, state: str | None = None, scope: str = "", error: str | None = None):
    if error or not code:
        return RedirectResponse("/settings?msg=strava_denied", status_code=303)
    if not state or _oauth_states.pop(state, None) is None:
        return RedirectResponse("/settings?msg=strava_state", status_code=303)
    if "activity:read" not in scope:
        return RedirectResponse("/settings?msg=strava_scope", status_code=303)
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": config.get("STRAVA_CLIENT_ID"),
        "client_secret": config.get("STRAVA_CLIENT_SECRET"),
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=15)
    if not resp.ok:
        return RedirectResponse("/settings?msg=strava_token", status_code=303)
    config.save({"STRAVA_REFRESH_TOKEN": resp.json()["refresh_token"]})
    services.reload()
    return RedirectResponse("/?msg=strava_connected", status_code=303)


@app.post("/auth/strava/disconnect")
def strava_disconnect():
    config.save({"STRAVA_REFRESH_TOKEN": ""})
    services.reload()
    return RedirectResponse("/settings?msg=strava_disconnected", status_code=303)


# ── Data API / partials ───────────────────────────────────────────────
@app.get("/api/summary")
def api_summary(source: str):
    try:
        return services.summary(source)
    except Exception as e:
        return _error_json(e)


@app.get("/api/wellness")
def api_wellness(days: int = 14):
    try:
        return services.wellness(max(1, min(days, 60)))
    except Exception as e:
        return _error_json(e)


@app.get("/partials/activities", response_class=HTMLResponse)
def partial_activities(request: Request, source: str, days: int = 14):
    days = max(1, min(days, 90))
    try:
        activities, error = services.activities(source, days), None
    except Exception as e:
        activities, error = [], _error_message(e)
    return templates.TemplateResponse(
        request, "partials/activities.html",
        {"activities": activities, "error": error, "source": source, "days": days},
    )


@app.post("/api/ai/analyze")
async def api_ai_analyze(request: Request):
    if not config.llm_configured():
        return JSONResponse({"error": "AI is not configured — add an API key in Settings."}, status_code=400)
    body = await request.json()
    question = str(body.get("question", ""))[:4000]
    try:
        context = await run_in_threadpool(services.ai_context)
        text = await run_in_threadpool(llm.analyze, context, question)
        return {"text": text, "provider": config.llm_provider(), "model": config.llm_model()}
    except Exception as e:
        return _error_json(e)
