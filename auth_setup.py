"""
One-time OAuth setup for Strava.

Usage:
    python3 auth_setup.py

Opens browser → you authorize → script saves tokens to .env
"""
import http.server
import os
import threading
import urllib.parse
import webbrowser

import requests
from dotenv import dotenv_values, set_key

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"

_auth_code: str | None = None
_server_done = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _auth_code = params["code"][0]
            message = b"<h2>Authorization successful! You can close this tab.</h2>"
        else:
            error = params.get("error", ["unknown"])[0]
            message = f"<h2>Authorization failed: {error}</h2>".encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(message)
        _server_done.set()

    def log_message(self, *args):
        pass  # suppress request logs


def _run_server():
    server = http.server.HTTPServer(("localhost", 8765), _CallbackHandler)
    server.handle_request()


def main():
    # Read existing .env or prompt for values
    existing = dotenv_values(ENV_FILE)

    client_id = existing.get("STRAVA_CLIENT_ID") or input("Strava Client ID: ").strip()
    client_secret = existing.get("STRAVA_CLIENT_SECRET") or input("Strava Client Secret: ").strip()

    if not client_id or not client_secret:
        print("ERROR: Client ID and Secret are required.")
        print("Get them at: https://www.strava.com/settings/api")
        return

    # Start callback server in background
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    # Build auth URL
    auth_params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all,profile:read_all",
    })
    url = f"{AUTH_URL}?{auth_params}"

    print(f"\nOpening browser for Strava authorization...")
    print(f"If browser doesn't open, go to:\n{url}\n")
    webbrowser.open(url)

    _server_done.wait(timeout=120)

    if not _auth_code:
        print("ERROR: Did not receive authorization code within 2 minutes.")
        return

    # Exchange code for tokens
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": _auth_code,
        "grant_type": "authorization_code",
    }, timeout=10)

    if not resp.ok:
        print(f"ERROR: Token exchange failed: {resp.text}")
        return

    tokens = resp.json()
    refresh_token = tokens["refresh_token"]
    athlete = tokens.get("athlete", {})

    # Save to .env
    set_key(ENV_FILE, "STRAVA_CLIENT_ID", client_id)
    set_key(ENV_FILE, "STRAVA_CLIENT_SECRET", client_secret)
    set_key(ENV_FILE, "STRAVA_REFRESH_TOKEN", refresh_token)

    print(f"\nAuthorized as: {athlete.get('firstname')} {athlete.get('lastname')}")
    print(f"Tokens saved to: {ENV_FILE}")
    print("\nNext steps:")
    print("  1. Add the MCP server to Claude Desktop config (see README)")
    print("  2. Restart Claude Desktop")


if __name__ == "__main__":
    main()
