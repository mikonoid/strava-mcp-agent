"""Run the dashboard: python -m web"""
import os

import uvicorn


def main() -> None:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    print(f"Training dashboard: http://localhost:{port}")
    uvicorn.run("web.app:app", host=host, port=port, reload=os.environ.get("WEB_RELOAD") == "1")


if __name__ == "__main__":
    main()
