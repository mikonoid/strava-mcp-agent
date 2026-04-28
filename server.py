"""Strava MCP server — exposes Strava data as tools for Claude Desktop."""
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from strava_client import StravaClient

server = Server("strava-training")
client = StravaClient()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_athlete_profile",
            description="Get the authenticated athlete's profile (name, location, fitness stats).",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_athlete_stats",
            description="Get lifetime and recent totals: distance, time, elevation for runs/rides/swims.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_recent_activities",
            description=(
                "Get a list of recent activities from Strava. "
                "Returns type, date, distance, duration, pace, HR, elevation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "How many days back to fetch (default 14)",
                        "default": 14,
                    }
                },
            },
        ),
        types.Tool(
            name="get_activity_detail",
            description="Get full details of a single activity including laps, splits, HR zones.",
            inputSchema={
                "type": "object",
                "required": ["activity_id"],
                "properties": {
                    "activity_id": {
                        "type": "integer",
                        "description": "Strava activity ID",
                    },
                    "include_laps": {
                        "type": "boolean",
                        "description": "Also fetch lap data (default true)",
                        "default": True,
                    },
                    "include_zones": {
                        "type": "boolean",
                        "description": "Also fetch HR/power zone distribution (default true)",
                        "default": True,
                    },
                },
            },
        ),
        types.Tool(
            name="get_training_load",
            description=(
                "Calculate training load metrics: ATL (acute, 7-day), CTL (chronic, 42-day), "
                "TSB (training stress balance). Helps detect overtraining or freshness."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_athlete_zones",
            description="Get the athlete's configured heart rate and power zones.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _format_activity_summary(act: dict) -> dict:
    """Strip down a raw Strava activity to useful fields."""
    distance_km = round(act.get("distance", 0) / 1000, 2)
    moving_time_min = round(act.get("moving_time", 0) / 60, 1)
    avg_pace = None
    if distance_km > 0 and moving_time_min > 0:
        pace_sec = (act["moving_time"] / (act["distance"] / 1000))
        avg_pace = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d} /km"

    return {
        "id": act["id"],
        "name": act.get("name"),
        "type": act.get("sport_type", act.get("type")),
        "date": act.get("start_date_local", "")[:10],
        "distance_km": distance_km,
        "moving_time_min": moving_time_min,
        "avg_pace_per_km": avg_pace,
        "avg_heart_rate": act.get("average_heartrate"),
        "max_heart_rate": act.get("max_heartrate"),
        "avg_speed_kmh": round(act.get("average_speed", 0) * 3.6, 2),
        "elevation_gain_m": act.get("total_elevation_gain"),
        "suffer_score": act.get("suffer_score"),
        "kudos": act.get("kudos_count"),
        "pr_count": act.get("pr_count"),
    }


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "get_athlete_profile":
            data = client.get_athlete()
            result = {
                "name": f"{data.get('firstname')} {data.get('lastname')}",
                "city": data.get("city"),
                "country": data.get("country"),
                "sex": data.get("sex"),
                "weight_kg": data.get("weight"),
                "ftp": data.get("ftp"),
                "follower_count": data.get("follower_count"),
                "friend_count": data.get("friend_count"),
            }

        elif name == "get_athlete_stats":
            result = client.get_athlete_stats()

        elif name == "get_recent_activities":
            days = arguments.get("days", 14)
            activities = client.get_activities(days=days)
            result = {
                "total": len(activities),
                "period_days": days,
                "activities": [_format_activity_summary(a) for a in activities],
            }

        elif name == "get_activity_detail":
            activity_id = arguments["activity_id"]
            include_laps = arguments.get("include_laps", True)
            include_zones = arguments.get("include_zones", True)

            detail = client.get_activity(activity_id)
            result = _format_activity_summary(detail)
            result["description"] = detail.get("description")
            result["gear"] = detail.get("gear", {}).get("name") if detail.get("gear") else None
            result["splits_metric"] = detail.get("splits_metric", [])

            if include_laps:
                result["laps"] = client.get_activity_laps(activity_id)
            if include_zones:
                try:
                    result["zones"] = client.get_activity_zones(activity_id)
                except Exception:
                    result["zones"] = "Not available (requires Strava subscription)"

        elif name == "get_training_load":
            result = client.calculate_training_load()

        elif name == "get_athlete_zones":
            result = client.get_athlete_zones()

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
