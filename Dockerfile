# syntax=docker/dockerfile:1

##############
# base stage #
##############

# Common setup shared by the dev and web stages: OS packages, the uv binary,
# the unprivileged user, and the locked dependency files.

FROM python:3.14-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

RUN useradd --create-home exporter \
    && chown exporter:exporter /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

USER exporter

COPY --chown=exporter:exporter pyproject.toml uv.lock ./

EXPOSE 30300

#############
# dev stage #
#############

# Used by docker-compose.yml for local development. The app code is bind
# mounted rather than copied in, so this image never needs rebuilding when
# the code changes; only rebuild it when the dependencies change.

FROM base AS dev

RUN uv sync --frozen

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "30300", "--reload"]

#############
# web stage #
#############

# This is the stage that gets built and deployed for staging and production.

FROM base AS web

# Number of workers for gunicorn to spawn
ENV WEB_CONCURRENCY=2

RUN uv sync --frozen --no-install-project --no-dev

COPY --chown=exporter:exporter gunicorn.conf.py ./
COPY --chown=exporter:exporter app ./app

# Run gunicorn using the config in gunicorn.conf.py (the default location for
# the config file). To change gunicorn settings without needing to make code
# changes and rebuild this image, set the GUNICORN_CMD_ARGS environment variable.
CMD ["gunicorn"]
