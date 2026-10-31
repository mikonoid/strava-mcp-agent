"""Training MCP server — exposes Strava and/or Garmin data as tools for Claude Desktop."""
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from strava_client import StravaClient, format_activity_summary as _format_activity_summary
from garmin_client import GarminClient

server = Server("training-agent")

# Each client is optional — only initialised when credentials are present
strava = StravaClient() if os.environ.get("STRAVA_CLIENT_ID") else None
garmin = GarminClient() if os.environ.get("GARMIN_EMAIL") else None


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    tools = []

    if strava:
        tools += [
            types.Tool(
                name="strava_get_athlete_profile",
                description="[Strava] Get athlete profile: name, location, weight, FTP.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="strava_get_athlete_stats",
                description="[Strava] Get lifetime totals: distance, time, elevation for runs/rides/swims.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="strava_get_recent_activities",
                description="[Strava] Get recent activities list with pace, HR, elevation.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days back to fetch (default 14)", "default": 14}
                    },
                },
            ),
            types.Tool(
                name="strava_get_activity_detail",
                description="[Strava] Get full details of a single activity: laps, splits, HR zones.",
                inputSchema={
                    "type": "object",
                    "required": ["activity_id"],
                    "properties": {
                        "activity_id": {"type": "integer", "description": "Strava activity ID"},
                        "include_laps": {"type": "boolean", "default": True},
                        "include_zones": {"type": "boolean", "default": True},
                    },
                },
            ),
            types.Tool(
                name="strava_get_training_load",
                description="[Strava] Calculate ATL (7-day), CTL (42-day), TSB — detects fatigue vs freshness.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="strava_get_athlete_zones",
                description="[Strava] Get configured heart rate and power zones.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    if garmin:
        tools += [
            types.Tool(
                name="garmin_get_profile",
                description="[Garmin] Get Garmin user profile.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="garmin_get_recent_activities",
                description="[Garmin] Get recent activities with pace, HR, calories, VO2max, training effect.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days back to fetch (default 14)", "default": 14}
                    },
                },
            ),
            types.Tool(
                name="garmin_get_training_load",
                description="[Garmin] Calculate ATL (7-day), CTL (42-day), TSB from Garmin activities.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="garmin_get_sleep",
                description="[Garmin] Get sleep data: duration, deep/light/REM breakdown, sleep score.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days back to fetch (default 7)", "default": 7}
                    },
                },
            ),
            types.Tool(
                name="garmin_get_resting_hr",
                description="[Garmin] Get daily resting heart rate — key recovery indicator.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days back to fetch (default 7)", "default": 7}
                    },
                },
            ),
            types.Tool(
                name="garmin_get_daily_steps",
                description="[Garmin] Get daily step counts.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days back to fetch (default 7)", "default": 7}
                    },
                },
            ),
            types.Tool(
                name="garmin_get_training_status",
                description="[Garmin] Get Garmin Training Status and Readiness Score.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        # ── Strava tools ──────────────────────────────────────────────
        if name == "strava_get_athlete_profile":
            data = strava.get_athlete()
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

        elif name == "strava_get_athlete_stats":
            result = strava.get_athlete_stats()

        elif name == "strava_get_recent_activities":
            days = arguments.get("days", 14)
            activities = strava.get_activities(days=days)
            result = {
                "source": "strava",
                "total": len(activities),
                "period_days": days,
                "activities": [_format_activity_summary(a) for a in activities],
            }

        elif name == "strava_get_activity_detail":
            activity_id = arguments["activity_id"]
            detail = strava.get_activity(activity_id)
            result = _format_activity_summary(detail)
            result["description"] = detail.get("description")
            result["gear"] = detail.get("gear", {}).get("name") if detail.get("gear") else None
            result["splits_metric"] = detail.get("splits_metric", [])
            if arguments.get("include_laps", True):
                result["laps"] = strava.get_activity_laps(activity_id)
            if arguments.get("include_zones", True):
                try:
                    result["zones"] = strava.get_activity_zones(activity_id)
                except Exception:
                    result["zones"] = "Not available (requires Strava subscription)"

        elif name == "strava_get_training_load":
            result = strava.calculate_training_load()
            result["source"] = "strava"

        elif name == "strava_get_athlete_zones":
            result = strava.get_athlete_zones()

        # ── Garmin tools ──────────────────────────────────────────────
        elif name == "garmin_get_profile":
            result = garmin.get_profile()

        elif name == "garmin_get_recent_activities":
            days = arguments.get("days", 14)
            activities = garmin.get_activities(days=days)
            result = {"source": "garmin", "total": len(activities), "period_days": days, "activities": activities}

        elif name == "garmin_get_training_load":
            result = garmin.calculate_training_load()
            result["source"] = "garmin"

        elif name == "garmin_get_sleep":
            result = {"source": "garmin", "sleep": garmin.get_sleep(days=arguments.get("days", 7))}

        elif name == "garmin_get_resting_hr":
            result = {"source": "garmin", "heart_rate": garmin.get_heart_rate(days=arguments.get("days", 7))}

        elif name == "garmin_get_daily_steps":
            result = {"source": "garmin", "steps": garmin.get_daily_steps(days=arguments.get("days", 7))}

        elif name == "garmin_get_training_status":
            result = garmin.get_training_status()
            result["source"] = "garmin"

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
