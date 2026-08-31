# design-system-chart-exporter

[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/ci.yml)
[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/mega-linter.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/mega-linter.yml)
[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/codeql.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/codeql.yml)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![uv-managed](https://img.shields.io/badge/uv-managed-blue)](https://docs.astral.sh/uv/)
[![License - MIT](https://img.shields.io/badge/licence%20-MIT-1ac403.svg)](https://github.com/ONSdigital/design-system-chart-exporter/blob/main/LICENSE)

A FastAPI service with one job: accept an ONS Design System chart
configuration, render it to a PNG in a headless Chromium (Playwright), upload
it privately to S3-compatible object storage, and return the object metadata.

Wagtail (the caller) owns all publishing/unpublishing, signed URLs, and
lifecycle. This service never manages access state beyond uploading privately,
and it is deliberately **non-idempotent**: every POST renders and stores a new
object (caching/deduplication is the caller's job).

> **Orphaned objects on client disconnect.** The render and upload run
> synchronously and are not cancelled if the caller disconnects mid-request.
> A client that times out and retries can therefore leave a stored object it
> never receives metadata for, plus a second object for the retry. This is an
> accepted consequence of the non-idempotent design — the caller owns object
> lifecycle, so Wagtail must treat retries deliberately (and any orphan cleanup
> is handled by the caller's lifecycle management, not this service).

---

## Table of Contents

<!-- markdown-link-check-disable -->
- [API](#api)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
  - [Pre-requisites](#pre-requisites)
  - [Installation](#installation)
- [Development](#development)
  - [Run Tests with Coverage](#run-tests-with-coverage)
  - [Linting and Formatting](#linting-and-formatting)
- [Security model](#security-model)
- [Deployment notes](#deployment-notes)
- [Contributing](#contributing)
- [License](#license)
<!-- markdown-link-check-enable -->

## API

### POST /charts — synchronous render and store

Request body (`application/json`):

```json
{
    "language": "en",
    "device": "desktop",
    "chart_config": { "chartType": "column", "title": "...", "series": [], "xAxis": {} }
}
```

- `language` — required; the MVP accepts only `"en"`.
- `device` — required; the MVP accepts only `"desktop"`.
- `chart_config` — required non-empty object. An **opaque** Design System
  chart payload (camelCase, Highcharts-derived); its internal fields are not
  validated here so the DS contract can evolve without service changes.

Response `201 Created`:

```json
{
    "id": "6f9619ff-8b86-d011-b42d-00cf4fc964ff",
    "created_at": "2026-07-02T12:00:00Z",
    "bucket": "ons-charts",
    "key": "charts/6f9619ff-8b86-d011-b42d-00cf4fc964ff.png",
    "content_type": "image/png",
    "size_bytes": 48213,
    "width": 1200,
    "height": 640
}
```

`id` is a server-generated UUID4, generated first; the object key is always
derived from it as `charts/{id}.png`. `width`/`height` are the PNG's real
pixel dimensions (read from the file's IHDR chunk, so they are correct even
when `device_scale_factor` > 1).

### Errors

Every non-2xx response uses the shared error document:

```json
{ "errors": [ { "code": "invalid_chart_config", "description": "chart_config is required and must be a non-empty object." } ] }
```

| Status | Codes | When |
| --- | --- | --- |
| 400 | `invalid_language`, `invalid_device`, `invalid_chart_config`, `invalid_request_body` | Missing/unsupported fields, empty or non-object chart_config, malformed JSON |
| 413 | `request_body_too_large` | Body exceeds the configured cap (default 1MB) |
| 415 | `unsupported_media_type` | Content-Type is not `application/json` |
| 500 | `render_failed`, `render_timeout`, `storage_failed`, `internal_error` | Server-side render/upload failure |
| 503 | `renderer_busy` | Render queue saturated; includes `Retry-After` |

Descriptions are client-facing and never contain internal detail; full
detail (stack traces, boto3 errors) goes to the logs only.

### GET /health

Follows the [DP health check specification](https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md).
Readiness reflects the shared browser: if Chromium is not connected the
response is `status: CRITICAL` with HTTP 500, and orchestrators should stop
routing traffic to the instance.

### Correlation IDs

Requests may carry an `X-Request-Id` header (per ONS `dp-net`). It is
propagated to every log event for that request as the DP logging standard's
`trace_id` field and echoed on the response; when absent (or unsafe) a new ID
is generated.

## Architecture

```text
app/
    main.py                  # module-level app, lifespan (browser + storage), registration
    config.py                # Settings (pydantic-settings), cached accessor
    version.py               # service name/version/build metadata
    logging.py               # DP-standards structlog setup (+ trace_id contextvar)
    api/
        deps.py              # content-type guard, chart exporter provider
        errors.py            # exception handlers -> spec error document
        middleware.py        # 413 body-size cap, X-Request-Id correlation
        routes/charts.py     # POST /charts
        routes/health.py     # GET /health
    domain/                  # exceptions + models; imports nothing of ours
    schemas/                 # request/response/error pydantic models
    services/
        templating.py        # Jinja env over vendored DS templates (safe tojson)
        renderer.py          # ChartRenderer: one browser, contexts, semaphore, timeouts
        exporter.py          # ChartExportService: uuid -> template -> render -> dims -> upload
        png.py               # PNG IHDR dimension parsing
    storage/
        base.py              # StorageBackend Protocol
        s3.py                # boto3 implementation (AWS or Floci via endpoint_url)
        memory.py            # in-memory fake for tests
templates/                   # chart.html (ours) + vendored DS templates/assets
```

Dependency rule: `api/` may import `services/`, `storage/`, `domain/`,
`schemas/`; services and storage never import FastAPI/Starlette or anything
HTTP; `domain/` imports none of our packages.

Concurrency model: one Chromium per worker process (launched in the FastAPI
lifespan), one isolated browser context per request, an `asyncio.Semaphore`
bounding concurrent renders (a memory ceiling), a bounded wait to acquire a
render slot (503 on timeout) and a bound on the render itself (500 on
timeout). Blocking boto3 uploads run in a worker thread, never on the event
loop. A crashed browser is relaunched on demand under a lock.

## Configuration

All service settings come from the environment with the `CHART_EXPORTER_`
prefix (12-factor; there is no config file):

| Environment variable | Required | Default | Description |
| --- | --- | --- | --- |
| `CHART_EXPORTER_S3_BUCKET` | **yes** | — | Target bucket. A missing value crashes the service at startup, by design. |
| `CHART_EXPORTER_S3_ENDPOINT_URL` | no | unset | Custom S3 endpoint. Set to Floci locally; leave unset in AWS. |
| `CHART_EXPORTER_S3_REGION` | no | unset | Region; unset defers to the AWS default chain. |
| `CHART_EXPORTER_S3_KEY_PREFIX` | no | `charts/` | Object key prefix. |
| `CHART_EXPORTER_S3_SET_PRIVATE_ACL` | no | `true` | Send `ACL=private` on PutObject. Set `false` for `BucketOwnerEnforced` buckets, which reject ACLs. |
| `CHART_EXPORTER_DESIGN_SYSTEM_VERSION` | no | `latest` | Informational; the vendored DS version is pinned by `.design-system-version` at build time. |
| `CHART_EXPORTER_VIEWPORT_WIDTH` | no | `1200` | Render viewport width (CSS px). |
| `CHART_EXPORTER_VIEWPORT_HEIGHT` | no | `640` | Render viewport height (CSS px). |
| `CHART_EXPORTER_DEVICE_SCALE_FACTOR` | no | `1.0` | Device scale factor (2.0 = retina; doubles PNG pixel dimensions). |
| `CHART_EXPORTER_MAX_CONCURRENT_RENDERS` | no | `4` | Render slots per worker (~50–100MB each). |
| `CHART_EXPORTER_RENDER_TIMEOUT_SECONDS` | no | `15` | Bound on a single render. Must stay below the caller/gunicorn timeouts. |
| `CHART_EXPORTER_QUEUE_TIMEOUT_SECONDS` | no | `5` | Bound on waiting for a render slot (503 + `Retry-After` after this). |
| `CHART_EXPORTER_MAX_BODY_BYTES` | no | `1048576` | Request body cap (413 beyond it). |
| `CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP` | no | `true` | Launch Chromium at startup (fail fast, meaningful readiness). Tests set `false`. |

AWS credentials are **never** configured through this service's own settings:
boto3 uses the standard environment variables or the pod IAM role. Local dev
against Floci uses dummy credentials (see docker-compose.yml).

The template-provided variables (`LOG_LEVEL`, `LOG_AS_JSON`, `WEB_PORT`,
`GIT_COMMIT`, `GIT_TAG`, `BUILD_TIME`) keep their unprefixed names — see
[Logging](#logging).

## Getting Started

To get a local copy up and running, follow these simple steps.

### Pre-requisites

Ensure you have the following installed:

1. **Python**: Version specified in `.python-version`.
   We recommend using [uv](https://docs.astral.sh/uv/) to install and pin the project Python version.
2. **[uv](https://docs.astral.sh/uv/)**: This is used to manage package dependencies and virtual
   environments.
3. **[Docker](https://docs.docker.com/engine/install/)**
4. **Operating System**: Ubuntu/macOS

### Installation

1. Clone the repository and install the required dependencies.

   ```bash
   git clone https://github.com/ONSdigital/design-system-chart-exporter.git
   ```

2. Install dependencies

   To install the Python version pinned for this project, run:

   ```bash
   uv python install
   ```

   To install all dependencies, including development dependencies, run:

   ```bash
   make install-dev
   ```

   Install the Git hooks used for local validation:

   ```bash
   make install-pre-commit
   ```

3. Fetch the renderer's assets

   Vendor the ONS Design System templates and assets (pinned by
   `.design-system-version`) and install the Playwright Chromium browser:

   ```bash
   make design-system
   make playwright-browsers
   ```

4. Run the application

   The full local stack (service + Floci S3 emulator + bucket bootstrap) via
   Docker Compose:

   ```bash
   make compose-build
   make up
   ```

   Or run the service on the host (outside Docker), with only the Floci S3
   emulator in a container. Copy the example environment file once, then start
   the infrastructure and the app:

   ```bash
   cp .env.example .env   # git-ignored; `make run` loads it automatically
   make up-deps           # start Floci (S3) only, with the charts bucket ready
   make run               # uvicorn --reload on the host, reading .env
   ```

   This requires the DS templates and the Chromium browser from the
   installation steps above (`make design-system`, `make playwright-browsers`).
   If you prefer not to use `.env`, export the same variables in your shell
   before `make run` — `CHART_EXPORTER_S3_BUCKET`,
   `CHART_EXPORTER_S3_ENDPOINT_URL` and the dummy `AWS_*` credentials.

5. Render a chart

   With the service running, POST the sample payload:

   ```bash
   make example
   ```

By default, the application will be available at [http://localhost:30300](http://localhost:30300).
This can be customised by setting the `WEB_PORT` environment variable.

## Development

Get started with development by running the following commands.
Before proceeding, make sure you have the development dependencies installed using the `make install-dev` command.

A Makefile is provided to simplify common development tasks. To view all available commands, run:

```bash
make
```

### Run Tests with Coverage

The tests are written with [pytest](https://docs.pytest.org/en/stable/) in four layers:

1. **Fast tests** (`make test`) — API tests over stubbed renderer/storage,
   plus templating, PNG, storage (botocore Stubber) and renderer control-flow
   units. No browser, no Docker; enforces 100% coverage. Downloads the DS
   templates on first run.
2. **Renderer tests** (`@pytest.mark.slow`) — real Chromium via Playwright.
3. **Storage integration** (`@pytest.mark.e2e`) — against the Floci container
   (`make up`); skipped with a message when Floci is down.
4. **One end-to-end test** (`@pytest.mark.e2e`) — real browser + real Floci:
   POST → 201 → object fetched back → dimensions match.

```bash
make test      # fast layers only, 100% coverage gate
make test-all  # everything (requires `make up` for the e2e layers)
```

### OpenAPI specification

The OpenAPI specification for the service is available at [http://localhost:30300/openapi.json](http://localhost:30300/openapi.json)
when the service is running locally.

The repository also contains a YAML version of the OpenAPI specification at
`./openapi.yaml`. This can be used to generate client code.

The file can be updated by running the following command:

```bash
make openapi
```

### Linting and Formatting

Various tools are used to lint and format the code in this project.

#### Python

The project uses [Ruff](https://github.com/astral-sh/ruff) for linting and
formatting, [mypy](https://mypy-lang.org/) for type checking, and
[pylint](https://pylint.pycqa.org/) for additional linting of the Python code.

The tools are configured using the `pyproject.toml` file and `.pylintrc`.

To lint the Python code, run:

```bash
make lint
```

To auto-format the Python code, and correct fixable linting issues, run:

```bash
make format
```

To run the configured pre-commit hooks across the repository, run:

```bash
make pre-commit
```

#### MegaLinter (Lint/Format non-python files)

[MegaLinter](https://github.com/oxsecurity/megalinter) is utilised to lint the non-python files in the project.
It offers a single interface to execute a suite of linters for multiple languages and formats, ensuring adherence to
best practices and maintaining consistency across the repository without the need to install each linter individually.

MegaLinter examines various file types and tools, including GitHub Actions, Shell scripts, Dockerfile, etc. It is
configured using the `.mega-linter.yml` file.

To run MegaLinter, ensure you have **Docker** installed on your system.

> [!NOTE]
>
> 1. If you use Colima for Docker on macOS, run `colima start --edit` and set `mountType: virtiofs` in the profile YAML
> so that bind mounts work correctly with `make megalint`.
> 2. The initial run may take some time while the Docker image is downloaded.
> Subsequent runs will be considerably faster due to Docker caching. 🚀

To start the linter and automatically rectify fixable issues, run:

```bash
make megalint
```

To run only a specific linter, pass `LINTER` variable:

```bash
make megalint LINTER=YAML_YAMLLINT
```

This maps to MegaLinter's `ENABLE_LINTERS` environment variable. See the
[supported linters list](https://megalinter.io/latest/supported-linters/) for valid names.

## Security model

The service renders caller-supplied data in a real browser inside a private
network, so the following are load-bearing, not optional:

- **SSRF mitigation (defence in depth)**: all Design System assets (CSS,
  fonts, the Highcharts JS bundle) are vendored into the image at build time
  and inlined into the rendered page. On top of that, the render context
  aborts **every** HTTP request (`context.route("**/*", abort)`) and every
  WebSocket (`context.route_web_socket`), the page carries a
  `connect-src 'none'` Content-Security-Policy (blocking fetch/XHR/WebSocket/
  EventSource/beacon at the browser layer), and Chromium is launched with
  non-proxied WebRTC UDP disabled. So even caller-supplied markup that reaches
  a raw-HTML (`| safe`) sink in the opaque `chart_config` cannot open any
  channel out of the render context — it cannot make Chromium reach internal
  endpoints (e.g. instance metadata).
- **Script-context escaping**: chart config is serialised into `<script>`
  blocks with `<`, `>`, `&`, `'`, U+2028/U+2029 escaped as unicode sequences,
  so a `</script>` payload cannot break out; HTML contexts are autoescaped
  (including the DS `.njk` macros), and strings under known raw-HTML keys
  (`download`) are HTML-escaped before templating so they render as inert
  text rather than executing.
- **Body size cap** (413) checks Content-Length *and* counts streamed bytes,
  because Content-Length can lie.
- **chart_config is never logged** — charts may contain pre-release data.
  Logs carry the chart id, durations, sizes and error codes only.
- **Private uploads**: no public ACL is ever set; `ACL=private` is sent
  unless the bucket is `BucketOwnerEnforced` (config flag).
- **Sanitised errors**: responses never contain exception messages, library
  errors or paths.
- **Container**: runs as a non-root user; Chromium runs without
  `--no-sandbox`.

## Deployment notes

- One browser per worker process. The web image runs gunicorn with
  `WEB_CONCURRENCY=1`, i.e. **one Chromium instance per container** — size
  container memory accordingly (each render context is ~50–100 MB, bounded by
  `max_concurrent_renders`), and keep scaling horizontal.
- Timeout nesting must hold: `queue_timeout + render_timeout` (default 20s)
  < gunicorn timeout (25s) < caller's client timeout < LB idle timeout.
- Base image: `python:3.14-slim` with Chromium's system libraries added via
  `playwright install-deps` (rather than `mcr.microsoft.com/playwright/python`,
  which does not ship Python 3.14). The two are equivalent for the system deps
  Chromium needs.
- At deploy time: enforce IMDSv2, and scope the pod IAM role to
  `s3:PutObject` on the charts prefix only (defence in depth alongside the
  render-context network block).

## Logging

By default, the logging configuration is set to log messages at the `INFO` level and above.

Logging can be configured using the following environment variables:

| Environment Variable | Description                                                            | Default Value |
|----------------------|------------------------------------------------------------------------|---------------|
| `LOG_LEVEL`          | The logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. | `INFO`        |
| `LOG_AS_JSON`        | Whether to log messages as JSON. One of `true` or `false`.             | `true`        |

Log events follow the [DP logging standards](https://github.com/ONSdigital/dp-standards/blob/main/LOGGING_STANDARDS.md)
(`namespace`, `severity`, `created_at`, `errors` chain, `trace_id`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

Copyright © 2026 [Crown Copyright][crown-copyright] (Office for National Statistics)

Unless stated otherwise, the codebase is released under the [MIT License](LICENSE).
This covers both the codebase and any sample code in the documentation.

The documentation in this repo are released under the [Open Government Licence v3.0][ogl-v3].

[crown-copyright]: https://www.nationalarchives.gov.uk/information-management/re-using-public-sector-information/uk-government-licensing-framework/crown-copyright/
[ogl-v3]: https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
