# syntax=docker/dockerfile:1

##############
# base stage #
##############

# Common setup shared by the dev and web stages: OS packages, the uv binary,
# the unprivileged user, and the locked dependency files.

FROM python:3.14-slim AS base

WORKDIR /app

# hadolint ignore=DL3008
RUN apt-get --quiet --yes update \
    && apt-get --quiet --yes install --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN useradd --create-home exporter \
    && chown exporter:exporter /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

USER exporter

COPY --chown=exporter:exporter pyproject.toml uv.lock ./

EXPOSE 8000

HEALTHCHECK --interval=3s --timeout=2s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8000/ || exit 1

#############
# dev stage #
#############

# Used by docker-compose.yml for local development. The app code is bind
# mounted rather than copied in, so this image never needs rebuilding when
# the code changes; only rebuild it when the dependencies change.

FROM base AS dev

RUN uv sync --frozen

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

#############
# web stage #
#############

# This is the stage that gets built and deployed for staging and production.

FROM base AS web

RUN uv sync --frozen --no-install-project --no-dev

COPY --chown=exporter:exporter app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
