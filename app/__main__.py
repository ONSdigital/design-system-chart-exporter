"""Entrypoint for running the app with `python -m app`."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", "30300"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)  # noqa: S104
