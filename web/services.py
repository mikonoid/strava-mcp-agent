"""Data access layer: wraps Strava/Garmin clients with caching and a common activity shape."""
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from garmin_client import GarminClient
from strava_client import StravaClient, format_activity_summary

from . import analytics, config

LOAD_DAYS = 90
FETCH_DAYS = LOAD_DAYS + analytics.CTL_DAYS


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: Any, ttl: float, fn: Callable[[], Any]) -> Any:
        hit = self._data.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
            value = fn()
            self._data[key] = (time.time() + ttl, value)
            return value

    def clear(self) -> None:
        self._data.clear()


def normalize_strava(act: dict) -> dict:
    s = format_activity_summary(act)
    return {
        "source": "strava",
        "id": s["id"],
        "name": s["name"],
        "type": s["type"],
        "date": s["date"],
        "distance_km": s["distance_km"],
        "duration_min": s["moving_time_min"],
        "pace": s["avg_pace_per_km"],
        "avg_hr": s["avg_heart_rate"],
        "max_hr": s["max_heart_rate"],
        "elevation_gain_m": s["elevation_gain_m"],
        "url": f"https://www.strava.com/activities/{s['id']}",
    }


def normalize_garmin(act: dict) -> dict:
    return {
        "source": "garmin",
        "id": act["id"],
        "name": act["name"],
        "type": act["type"],
        "date": act["date"],
        "distance_km": act["distance_km"],
        "duration_min": act["duration_min"],
        "pace": act["avg_pace_per_km"],
        "avg_hr": act["avg_hr"],
        "max_hr": act["max_hr"],
        "elevation_gain_m": act["elevation_gain_m"],
        "url": f"https://connect.garmin.com/modern/activity/{act['id']}",
    }


class Services:
    def __init__(self) -> None:
        self.cache = TTLCache()
        self.strava: StravaClient | None = None
        self.garmin: GarminClient | None = None
        self._garmin_lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        config.load()
        self.strava = StravaClient() if config.strava_connected() else None
        self.garmin = GarminClient() if config.garmin_configured() else None
        self.cache.clear()

    def sources(self) -> list[str]:
        return [name for name, client in (("strava", self.strava), ("garmin", self.garmin)) if client]

    # ── Activities ────────────────────────────────────────────────────
    def _all_activities(self, source: str) -> list[dict]:
        """All activities for the analytics window, newest first."""
        def fetch() -> list[dict]:
            if source == "strava" and self.strava:
                acts = [normalize_strava(a) for a in self.strava.get_all_activities(days=FETCH_DAYS)]
            elif source == "garmin" and self.garmin:
                with self._garmin_lock:
                    acts = [normalize_garmin(a) for a in self.garmin.get_activities(days=FETCH_DAYS)]
            else:
                raise ValueError(f"Source '{source}' is not configured")
            return sorted(acts, key=lambda a: a["date"], reverse=True)

        return self.cache.get(("activities", source), 600, fetch)

    def activities(self, source: str, days: int) -> list[dict]:
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        return [a for a in self._all_activities(source) if a["date"] >= cutoff]

    def summary(self, source: str) -> dict:
        acts = self._all_activities(source)
        return {
            "load": analytics.load_series(acts, days=LOAD_DAYS),
            "weekly": analytics.weekly_volume(acts, weeks=12),
            "last7": analytics.totals(self.activities(source, 7)),
            "last28": analytics.totals(self.activities(source, 28)),
        }

    def strava_activity(self, activity_id: int) -> dict:
        def fetch() -> dict:
            detail = self.strava.get_activity(activity_id)
            result = normalize_strava(detail)
            result["description"] = detail.get("description")
            result["gear"] = (detail.get("gear") or {}).get("name")
            result["calories"] = detail.get("calories")
            result["splits"] = [
                {
                    "km": s.get("split"),
                    "distance_m": s.get("distance"),
                    "moving_time_s": s.get("moving_time"),
                    "pace_s_per_km": round(s["moving_time"] / (s["distance"] / 1000)) if s.get("distance") else None,
                    "avg_hr": s.get("average_heartrate"),
                    "elev_m": s.get("elevation_difference"),
                }
                for s in detail.get("splits_metric") or []
            ]
            result["laps"] = [
                {
                    "name": lap.get("name"),
                    "distance_km": round((lap.get("distance") or 0) / 1000, 2),
                    "moving_time_min": round((lap.get("moving_time") or 0) / 60, 1),
                    "avg_hr": lap.get("average_heartrate"),
                    "avg_speed_kmh": round((lap.get("average_speed") or 0) * 3.6, 1),
                }
                for lap in self.strava.get_activity_laps(activity_id)
            ]
            return result

        if not self.strava:
            raise ValueError("Strava is not connected")
        return self.cache.get(("strava_activity", activity_id), 3600, fetch)

    def profile(self) -> dict | None:
        if not self.strava:
            return None

        def fetch() -> dict:
            a = self.strava.get_athlete()
            return {
                "name": f"{a.get('firstname', '')} {a.get('lastname', '')}".strip(),
                "city": a.get("city"),
                "country": a.get("country"),
                "weight_kg": a.get("weight"),
                "ftp": a.get("ftp"),
                "avatar": a.get("profile_medium"),
            }

        return self.cache.get("profile", 3600, fetch)

    # ── Garmin wellness ───────────────────────────────────────────────
    def wellness(self, days: int = 14) -> dict:
        if not self.garmin:
            raise ValueError("Garmin is not configured")

        def fetch() -> dict:
            with self._garmin_lock:
                sleep = list(reversed(self.garmin.get_sleep(days)))
                hr = list(reversed(self.garmin.get_heart_rate(days)))
                steps = list(reversed(self.garmin.get_daily_steps(days)))
            return {
                "labels": [s["date"] for s in sleep],
                "sleep_hours": [s.get("duration_hours") for s in sleep],
                "deep_hours": [s.get("deep_sleep_hours") for s in sleep],
                "rem_hours": [s.get("rem_sleep_hours") for s in sleep],
                "sleep_score": [s.get("score") for s in sleep],
                "resting_hr": [h.get("resting_hr") for h in hr],
                "steps": [s.get("steps") for s in steps],
            }

        return self.cache.get(("wellness", days), 1800, fetch)

    # ── AI context ────────────────────────────────────────────────────
    def ai_context(self) -> dict:
        """Compact snapshot of training data to send to the LLM."""
        ctx: dict[str, Any] = {}
        if profile := self.profile():
            ctx["athlete"] = {k: v for k, v in profile.items() if k != "avatar"}
        for source in self.sources():
            s = self.summary(source)
            ctx[source] = {
                "training_load_today": s["load"]["current"],
                "load_trend_last_28_days": {
                    "dates": s["load"]["labels"][-28:],
                    "atl": s["load"]["atl"][-28:],
                    "ctl": s["load"]["ctl"][-28:],
                    "tsb": s["load"]["tsb"][-28:],
                },
                "weekly_volume_last_12_weeks": s["weekly"],
                "last_7_days_totals": s["last7"],
                "last_28_days_totals": s["last28"],
                "activities_last_21_days": [
                    {k: v for k, v in a.items() if k not in ("url", "source")}
                    for a in self.activities(source, 21)
                ],
            }
        if self.garmin:
            try:
                ctx["garmin_wellness_last_14_days"] = self.wellness(14)
            except Exception as e:  # wellness is a bonus; don't fail the analysis
                ctx["garmin_wellness_error"] = str(e)
        return ctx


services = Services()
