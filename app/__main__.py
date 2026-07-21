"""Entrypoint for running the app with `python -m app`."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=30300, reload=True)  # noqa: S104
