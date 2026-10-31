"""Training analytics shared by all data sources."""
from collections import defaultdict
from datetime import date, timedelta

ATL_DAYS = 7
CTL_DAYS = 42


def interpret_tsb(tsb: float) -> str:
    if tsb > 10:
        return "Fresh / recovered"
    if tsb >= -10:
        return "Optimal training zone"
    return "Accumulated fatigue — consider recovery"


def daily_minutes(activities: list[dict]) -> dict[str, float]:
    """Sum activity duration (minutes) per calendar day."""
    load: dict[str, float] = defaultdict(float)
    for act in activities:
        if act.get("date"):
            load[act["date"]] += act.get("duration_min") or 0
    return load


def load_series(activities: list[dict], days: int = 90, today: date | None = None) -> dict:
    """
    Daily ATL/CTL/TSB series using the same model as the MCP tools:
    ATL = 7-day avg minutes/day, CTL = 42-day avg, TSB = CTL - ATL.
    `activities` must cover at least `days + CTL_DAYS` days.
    """
    today = today or date.today()
    load = daily_minutes(activities)

    def avg(end: date, n: int) -> float:
        return sum(load.get((end - timedelta(days=i)).isoformat(), 0) for i in range(n)) / n

    labels, minutes, atl, ctl, tsb = [], [], [], [], []
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        a, c = avg(d, ATL_DAYS), avg(d, CTL_DAYS)
        labels.append(d.isoformat())
        minutes.append(round(load.get(d.isoformat(), 0), 1))
        atl.append(round(a, 1))
        ctl.append(round(c, 1))
        tsb.append(round(c - a, 1))

    return {
        "labels": labels,
        "minutes": minutes,
        "atl": atl,
        "ctl": ctl,
        "tsb": tsb,
        "current": {
            "atl": atl[-1],
            "ctl": ctl[-1],
            "tsb": tsb[-1],
            "interpretation": interpret_tsb(tsb[-1]),
        },
    }


def weekly_volume(activities: list[dict], weeks: int = 12, today: date | None = None) -> dict:
    """Distance, time and count per ISO week (Monday start)."""
    today = today or date.today()
    current_monday = today - timedelta(days=today.weekday())
    mondays = [current_monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    buckets = {m.isoformat(): {"km": 0.0, "hours": 0.0, "count": 0} for m in mondays}

    for act in activities:
        if not act.get("date"):
            continue
        d = date.fromisoformat(act["date"])
        key = (d - timedelta(days=d.weekday())).isoformat()
        if key in buckets:
            buckets[key]["km"] += act.get("distance_km") or 0
            buckets[key]["hours"] += (act.get("duration_min") or 0) / 60
            buckets[key]["count"] += 1

    return {
        "labels": list(buckets),
        "km": [round(b["km"], 1) for b in buckets.values()],
        "hours": [round(b["hours"], 1) for b in buckets.values()],
        "count": [b["count"] for b in buckets.values()],
    }


def totals(activities: list[dict]) -> dict:
    return {
        "count": len(activities),
        "km": round(sum(a.get("distance_km") or 0 for a in activities), 1),
        "hours": round(sum(a.get("duration_min") or 0 for a in activities) / 60, 1),
        "elevation_m": round(sum(a.get("elevation_gain_m") or 0 for a in activities)),
    }
