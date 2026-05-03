"""Garmin Connect client using the unofficial garminconnect library."""
import os
from datetime import date, timedelta

from garminconnect import Garmin


class GarminClient:
    def __init__(self):
        self.email = os.environ["GARMIN_EMAIL"]
        self.password = os.environ["GARMIN_PASSWORD"]
        self._client: Garmin | None = None

    def _get_client(self) -> Garmin:
        if self._client is None:
            self._client = Garmin(self.email, self.password)
            self._client.login()
        return self._client

    def get_profile(self) -> dict:
        """Get user profile."""
        c = self._get_client()
        return c.get_user_profile()

    def get_activities(self, days: int = 14) -> list[dict]:
        """Get recent activities for the last N days."""
        c = self._get_client()
        start_date = (date.today() - timedelta(days=days)).isoformat()
        end_date = date.today().isoformat()
        activities = c.get_activities_by_date(start_date, end_date)
        return [_format_activity(a) for a in activities]

    def get_activity_detail(self, activity_id: int) -> dict:
        """Get detailed info for a single activity."""
        c = self._get_client()
        return c.get_activity(activity_id)

    def get_heart_rate(self, days: int = 7) -> list[dict]:
        """Get daily resting heart rate for last N days."""
        c = self._get_client()
        results = []
        for i in range(days):
            d = (date.today() - timedelta(days=i)).isoformat()
            try:
                hr = c.get_heart_rates(d)
                results.append({
                    "date": d,
                    "resting_hr": hr.get("restingHeartRate"),
                    "max_hr": hr.get("maxHeartRate"),
                    "min_hr": hr.get("minHeartRate"),
                })
            except Exception:
                results.append({"date": d, "error": "no data"})
        return results

    def get_sleep(self, days: int = 7) -> list[dict]:
        """Get sleep data for last N days."""
        c = self._get_client()
        results = []
        for i in range(days):
            d = (date.today() - timedelta(days=i)).isoformat()
            try:
                sleep = c.get_sleep_data(d)
                daily = sleep.get("dailySleepDTO", {})
                results.append({
                    "date": d,
                    "duration_hours": round(daily.get("sleepTimeSeconds", 0) / 3600, 1),
                    "deep_sleep_hours": round(daily.get("deepSleepSeconds", 0) / 3600, 1),
                    "light_sleep_hours": round(daily.get("lightSleepSeconds", 0) / 3600, 1),
                    "rem_sleep_hours": round(daily.get("remSleepSeconds", 0) / 3600, 1),
                    "awake_hours": round(daily.get("awakeSleepSeconds", 0) / 3600, 1),
                    "score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
                })
            except Exception:
                results.append({"date": d, "error": "no data"})
        return results

    def get_training_status(self) -> dict:
        """Get Garmin training status and readiness score."""
        c = self._get_client()
        today = date.today().isoformat()
        result = {}
        try:
            status = c.get_training_status(today)
            result["training_status"] = status
        except Exception as e:
            result["training_status_error"] = str(e)
        try:
            readiness = c.get_training_readiness(today)
            result["readiness"] = readiness
        except Exception as e:
            result["readiness_error"] = str(e)
        return result

    def get_daily_steps(self, days: int = 7) -> list[dict]:
        """Get daily step counts for last N days."""
        c = self._get_client()
        results = []
        for i in range(days):
            d = (date.today() - timedelta(days=i)).isoformat()
            try:
                steps = c.get_steps_data(d)
                total = sum(s.get("steps", 0) for s in steps) if steps else 0
                results.append({"date": d, "steps": total})
            except Exception:
                results.append({"date": d, "error": "no data"})
        return results

    def calculate_training_load(self, days: int = 42) -> dict:
        """
        Calculate ATL/CTL/TSB using Garmin activity moving time as load proxy.
        ATL = 7-day avg minutes/day
        CTL = 42-day avg minutes/day
        TSB = CTL - ATL
        """
        from datetime import date, timedelta
        c = self._get_client()
        start_date = (date.today() - timedelta(days=days)).isoformat()
        end_date = date.today().isoformat()
        activities = c.get_activities_by_date(start_date, end_date)

        daily_load: dict[str, float] = {}
        for act in activities:
            d = act.get("startTimeLocal", "")[:10]
            duration_min = act.get("duration", 0) / 60
            daily_load[d] = daily_load.get(d, 0) + duration_min

        today = date.today()

        def avg(n: int) -> float:
            total = sum(daily_load.get((today - timedelta(days=i)).isoformat(), 0) for i in range(n))
            return round(total / n, 1)

        atl = avg(7)
        ctl = avg(42)
        tsb = round(ctl - atl, 1)

        return {
            "atl_7d_avg_minutes": atl,
            "ctl_42d_avg_minutes": ctl,
            "tsb": tsb,
            "interpretation": (
                "Fresh / recovered" if tsb > 10 else
                "Optimal training zone" if tsb >= -10 else
                "Accumulated fatigue — consider recovery"
            ),
        }


def _format_activity(act: dict) -> dict:
    distance_km = round((act.get("distance") or 0) / 1000, 2)
    duration_min = round((act.get("duration") or 0) / 60, 1)
    avg_pace = None
    if distance_km > 0 and duration_min > 0:
        pace_sec = (act["duration"] / (act["distance"] / 1000))
        avg_pace = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d} /km"

    return {
        "id": act.get("activityId"),
        "name": act.get("activityName"),
        "type": act.get("activityType", {}).get("typeKey"),
        "date": act.get("startTimeLocal", "")[:10],
        "distance_km": distance_km,
        "duration_min": duration_min,
        "avg_pace_per_km": avg_pace,
        "avg_hr": act.get("averageHR"),
        "max_hr": act.get("maxHR"),
        "avg_speed_kmh": round((act.get("averageSpeed") or 0) * 3.6, 2),
        "elevation_gain_m": act.get("elevationGain"),
        "calories": act.get("calories"),
        "training_effect": act.get("aerobicTrainingEffect"),
        "vo2max": act.get("vO2MaxValue"),
    }
