# strava-mcp-agent

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects Claude Desktop to your Strava and Garmin Connect accounts — enabling AI-powered training analysis and planning through natural language.

## How it works

```
You (Claude Desktop)  →  MCP Server (server.py)  →  Strava API
        ↑                                        ↘  Garmin Connect
        └─────────── analysis & training plan ───────────┘
```

Both data sources are **optional and independent** — use one or both. Claude autonomously decides which tools to call based on your request:

> *"Analyze my last 2 weeks of training and check for signs of overtraining"*
> *"Build me a training plan for next week based on my current fitness"*
> *"How was my sleep and recovery this week?"*
> *"Cross-reference my Strava activities with my Garmin sleep data"*

## Available Tools

### Strava

| Tool | Description |
|------|-------------|
| `strava_get_athlete_profile` | Name, location, weight, FTP |
| `strava_get_athlete_stats` | Lifetime totals: distance, time, elevation |
| `strava_get_recent_activities` | Activities list for last N days with pace, HR, elevation |
| `strava_get_activity_detail` | Full details: laps, splits, HR zones for a single activity |
| `strava_get_training_load` | ATL (7-day), CTL (42-day), TSB — detects fatigue vs freshness |
| `strava_get_athlete_zones` | Configured heart rate and power zones |

### Garmin Connect

| Tool | Description |
|------|-------------|
| `garmin_get_profile` | Garmin user profile |
| `garmin_get_recent_activities` | Activities with pace, HR, calories, VO2max, training effect |
| `garmin_get_training_load` | ATL (7-day), CTL (42-day), TSB from Garmin data |
| `garmin_get_sleep` | Sleep duration, deep/light/REM breakdown, sleep score |
| `garmin_get_resting_hr` | Daily resting heart rate — key recovery indicator |
| `garmin_get_daily_steps` | Daily step counts |
| `garmin_get_training_status` | Garmin Training Status and Readiness Score |

## Prerequisites

- **Claude Desktop** — [download here](https://claude.ai/download) (free)
- **Python 3.11+**
- **Strava account** (optional)
- **Garmin Connect account** (optional)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/mikonoid/strava-mcp-agent.git
cd strava-mcp-agent
```

### 2. Create virtual environment

> **Important (Apple Silicon Mac):** packages must be installed as `arm64` since Claude Desktop runs natively on arm64.

```bash
python3 -m venv .venv
arch -arm64 .venv/bin/pip install -r requirements.txt
```

On Linux / Intel Mac:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Configure credentials

```bash
cp .env.example .env
```

#### Strava (optional)

1. Go to [strava.com/settings/api](https://www.strava.com/settings/api)
2. Create an app — set **Authorization Callback Domain** to `localhost`
3. Note your **Client ID** and **Client Secret**
4. Run the OAuth helper:

```bash
python3 auth_setup.py
```

This will:
- Open a browser for Strava OAuth
- Request `activity:read_all` scope
- Save `STRAVA_REFRESH_TOKEN` to `.env` automatically

#### Garmin Connect (optional)

Add your Garmin credentials directly to `.env`:

```env
GARMIN_EMAIL=your@email.com
GARMIN_PASSWORD=yourpassword
```

> Garmin Connect uses email/password authentication (no OAuth). Your credentials stay local in `.env` — never committed to git.

### 5. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strava": {
      "command": "/absolute/path/to/strava-mcp-agent/.venv/bin/python3",
      "args": ["/absolute/path/to/strava-mcp-agent/server.py"]
    }
  }
}
```

> On Apple Silicon verify the venv python is arm64:
> ```bash
> file .venv/bin/python3.11
> # should show: Mach-O 64-bit executable arm64
> ```

### 6. Restart Claude Desktop

After restart, click `+` in the chat input → **Connectors** → toggle **strava** on.

## Project structure

```
strava-mcp-agent/
├── server.py          # MCP server — defines and handles all tools
├── strava_client.py   # Strava REST API client + ATL/CTL/TSB calculation
├── garmin_client.py   # Garmin Connect client (sleep, HR, steps, activities)
├── auth_setup.py      # One-time OAuth flow for Strava — saves tokens to .env
├── requirements.txt
├── .env.example
└── .gitignore
```

## .env format

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
STRAVA_REFRESH_TOKEN=filled_by_auth_setup
```

## Troubleshooting

**Server disconnected in Claude Desktop**
```bash
cat ~/Library/Logs/Claude/mcp-server-strava.log | tail -30
```

**Architecture mismatch on Apple Silicon:**
Rebuild venv with `arch -arm64 .venv/bin/pip install -r requirements.txt`

**Wrong scope / 403 errors:**
Delete `.env` refresh token and re-run `python3 auth_setup.py` to re-authorize with `activity:read_all` scope.

