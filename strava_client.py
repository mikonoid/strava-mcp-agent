"""Strava API client with auto token refresh."""
import os
import time
import requests
from datetime import datetime, timedelta, timezone


STRAVA_API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"


class StravaClient:
    def __init__(self):
        self.client_id = os.environ["STRAVA_CLIENT_ID"]
        self.client_secret = os.environ["STRAVA_CLIENT_SECRET"]
        self.refresh_token = os.environ["STRAVA_REFRESH_TOKEN"]
        self._access_token = None
        self._token_expires = 0

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token

        resp = requests.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires = data["expires_at"]
        # Update refresh token if rotated
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    def get_athlete(self) -> dict:
        """Get authenticated athlete profile."""
        resp = requests.get(f"{STRAVA_API}/athlete", headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_athlete_stats(self) -> dict:
        """Get athlete totals and stats."""
        athlete = self.get_athlete()
        athlete_id = athlete["id"]
        resp = requests.get(
            f"{STRAVA_API}/athletes/{athlete_id}/stats",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_activities(self, days: int = 14, per_page: int = 50) -> list[dict]:
        """Get recent activities within last N days."""
        after = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
        resp = requests.get(
            f"{STRAVA_API}/athlete/activities",
            headers=self._headers(),
            params={"after": after, "per_page": per_page},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_activity(self, activity_id: int) -> dict:
        """Get detailed info for a single activity."""
        resp = requests.get(
            f"{STRAVA_API}/activities/{activity_id}",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_activity_zones(self, activity_id: int) -> list[dict]:
        """Get HR and power zones for an activity."""
        resp = requests.get(
            f"{STRAVA_API}/activities/{activity_id}/zones",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_athlete_zones(self) -> dict:
        """Get athlete's configured HR and power zones."""
        resp = requests.get(
            f"{STRAVA_API}/athlete/zones",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_activity_laps(self, activity_id: int) -> list[dict]:
        """Get laps for an activity."""
        resp = requests.get(
            f"{STRAVA_API}/activities/{activity_id}/laps",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def calculate_training_load(self, days: int = 42) -> dict:
        """
        Calculate basic training load metrics:
        - ATL (Acute Training Load) - last 7 days avg
        - CTL (Chronic Training Load) - last 42 days avg
        - TSB (Training Stress Balance) = CTL - ATL
        Uses moving time as proxy for load (seconds per day).
        """
        activities = self.get_activities(days=days, per_page=100)

        now = datetime.now(timezone.utc)
        daily_load: dict[str, float] = {}

        for act in activities:
            date_str = act["start_date"][:10]
            moving_time = act.get("moving_time", 0)
            # Normalise to "training points": 1 pt per minute of moving time
            daily_load[date_str] = daily_load.get(date_str, 0) + moving_time / 60

        def avg_load(n_days: int) -> float:
            total = 0.0
            for i in range(n_days):
                d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                total += daily_load.get(d, 0)
            return round(total / n_days, 1)

        atl = avg_load(7)
        ctl = avg_load(42)
        tsb = round(ctl - atl, 1)

        return {
            "atl_7d_avg_minutes": atl,
            "ctl_42d_avg_minutes": ctl,
            "tsb": tsb,
            "interpretation": (
                "Fresh / recovered" if tsb > 10 else
                "Optimal training zone" if tsb >= -10 else
                "Accumulated fatigue — consider recovery"
            )
        }
