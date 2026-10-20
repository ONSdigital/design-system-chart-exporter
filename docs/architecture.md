# Design System Chart Exporter — Architecture and Design

This document explains how the chart exporter service is built: its
responsibilities, the request path, every layer and module, the design
patterns used, the decisions taken (and the alternatives rejected), the
security model, the testing strategy, and how the design accommodates the
changes we can foresee.

---

## 1. Purpose and scope

The service has exactly one job:

> Accept an ONS Design System chart configuration, render it to a PNG in a
> headless Chromium, upload it **privately** to S3-compatible object storage,
> and return the object's metadata.

| In scope                                            | Out of scope (owned elsewhere)                                                                                                        |
|-----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `POST /charts` — synchronous render + store         | Publishing / unpublishing, signed URLs, object lifecycle (Wagtail)                                                                    |
| `GET /health` — DP-standards health check           | Authentication (the API router upstream)                                                                                              |
| Private upload, deterministic key `charts/{id}.png` | Caching / deduplication (the service is deliberately **non-idempotent**); orphan-object cleanup after a client disconnect (see below) |
| Structured JSON logging with correlation IDs        | Background / async job patterns (render is synchronous, connection held)                                                              |

The caller is Wagtail. The service never manages access state beyond
uploading privately.

---

## 2. System context

```text
                 POST /charts (JSON)                    PutObject (private)
  Wagtail CMS  ─────────────────────▶  chart-exporter  ─────────────────────▶  S3 bucket
      ▲                                     │                                 (or Floci locally)
      │      201 {id, key, bucket, size,    │
      └───── width, height, created_at}     ▼
                                      headless Chromium
                                      (one per process, launched at startup;
                                       all network access blocked)
```

Deployment shape: one container = one gunicorn worker = one uvicorn event
loop = one Chromium. Scaling is horizontal (more pods), never more workers
per pod.

---

## 3. The request path

Every `POST /charts` passes through these layers in order. Each layer has
one responsibility and hands a typed value to the next.

```text
HTTP request
  │
  ▼  CorrelationIdMiddleware      (pure ASGI, OUTERMOST) — read/generate X-Request-Id,
  │                                 set the trace_id contextvar, echo the header on
  │                                 every response including early rejections
  ▼  BodySizeLimitMiddleware      (pure ASGI) — 413 if Content-Length > cap, and
  │                                 413 if the streamed body crosses the cap
  ▼  require_json_content_type    (router-level dependency) — 415 unless
  │                                 Content-Type is application/json; runs BEFORE
  │                                 the body is read
  ▼  ChartRenderRequest           (pydantic) — language=="en", device=="desktop",
  │                                 chart_config is a non-empty object; failures
  │                                 are remapped from FastAPI's 422 to the spec's 400
  ▼  create_chart route           — one line of logic: call the service
  │
  ▼  ChartExportService.export    THE ORCHESTRATOR
  │     1. uuid4()                           → id (generated FIRST)
  │     2. key = f"charts/{id}.png"          → deterministic, derived from id
  │     3. render_chart_html(config)         → Jinja over vendored DS templates
  │     4. renderer.render(html)             → semaphore → browser context → PNG
  │     5. read_png_dimensions(png)          → true pixel size from the IHDR chunk
  │     6. to_thread(storage.put(...))       → boto3 upload off the event loop
  │
  ▼  RenderedChart (domain dataclass)  →  ChartObjectResponse (pydantic)  →  201
```

Failures anywhere raise a **domain exception** (`RenderError`,
`RenderTimeout`, `RendererBusy`, `StorageError`) which the handlers in
`api/errors.py` translate into the spec's error document and status code.
Routes and services contain no error-formatting code.

---

## 4. Code layout and the dependency rule

```text
app/
  main.py            app object, lifespan (browser + storage), middleware/handler/router registration
  config.py          Settings (pydantic-settings, env-only), cached accessor
  version.py         service name / version / build metadata (from pyproject + CI env vars)
  logging.py         DP-standards structlog pipeline + trace_id contextvar
  api/               ── knows HTTP ──
    deps.py            content-type guard, chart exporter provider (DI)
    errors.py          exception handlers → spec error document
    middleware.py      body-size cap (413), correlation ID
    routes/charts.py   POST /charts
    routes/health.py   GET /health
  schemas/           ── HTTP boundary types (pydantic) ──
    requests.py        ChartRenderRequest
    responses.py       ChartObjectResponse, ErrorItem, ErrorDocument
    health.py          DP health-check envelope
  domain/            ── shared vocabulary, imports nothing of ours ──
    exceptions.py      ChartExporterError → RenderError → RenderTimeout; RendererBusy; StorageError
    models.py          RenderedChart, StoredObject (frozen dataclasses)
  services/          ── no HTTP knowledge ──
    templating.py      Jinja environment over vendored DS templates; safe tojson
    renderer.py        ChartRenderer: browser lifecycle, contexts, semaphore, timeouts
    png.py             PNG IHDR dimension parser
    exporter.py        ChartExportService: the orchestration
  storage/           ── no HTTP knowledge ──
    base.py            StorageBackend Protocol
    s3.py              boto3 implementation (AWS, or Floci via endpoint_url)
    memory.py          in-memory fake with fault injection (tests)
templates/
  chart.html         our page shell (inlines CSS/JS, calls the DS onsChart macro)
  components/, layout/, assets/   vendored Design System files (build-time, git-ignored)
scripts/             vendoring, font inlining, Floci bucket bootstrap, OpenAPI export
tests/               four layers (see §9)
```

**The dependency rule (enforced, not aspirational):**

| Package                 | May import                                     | Must never import                 |
|-------------------------|------------------------------------------------|-----------------------------------|
| `api/`                  | `services/`, `storage/`, `domain/`, `schemas/` | —                                 |
| `services/`, `storage/` | `domain/`, each other's Protocols              | FastAPI, Starlette, anything HTTP |
| `domain/`               | stdlib only                                    | any of our packages               |

You can see the rule bite in small places: the upload offload uses
`asyncio.to_thread` rather than Starlette's `run_in_threadpool` — identical
behaviour, chosen purely so `services/` has no Starlette import.

---

## 5. Module-by-module

### 5.1 `config.py` — Settings

- One `Settings(BaseSettings)`; every field is read from the environment
  with the `CHART_EXPORTER_` prefix (12-factor; no config file).
- `s3_bucket` has no default → missing env var raises `ValidationError`
  when the lifespan calls `get_settings()` → **the pod crashes on boot**,
  never 500s on first request.
- Numeric limits carry `gt=0` constraints, so a zero semaphore or timeout is
  also a boot failure rather than a wedged service.
- `frozen=True`: settings are an immutable value, safe to share across tasks.
- `get_settings()` is `@lru_cache`d: the environment is read once per
  process; tests call `cache_clear()` after monkeypatching.
- No credential fields, by design — boto3 resolves identity from the
  standard AWS env vars or the pod IAM role.
- `launch_browser_on_startup` exists because dependency overrides cannot
  reach the lifespan; tests set it `false` so the fast suite never launches
  Chromium. Production leaves it `true` so a broken browser install fails
  the pod immediately.

### 5.2 `main.py` — composition root and lifespan

`main.py` only assembles. The lifespan is the single place process-lifetime
resources are created and torn down:

```text
startup:  get_settings()  →  app.state.settings / start_time
          ChartRenderer(...)  →  app.state.renderer
          S3StorageBackend(...)  →  app.state.storage
          renderer.start()     (launch Chromium, if enabled)
  ─── yield: serve requests ───
shutdown: renderer.stop()     (safe even if never started)
```

Middleware is added body-size first, correlation last — `add_middleware`
wraps the app like an onion, so **last added = outermost**. Correlation must
be outermost so a 413 short-circuit or an unhandled crash still carries
`X-Request-Id`.

### 5.3 `api/middleware.py` — pure ASGI

Both middlewares are written against the raw ASGI interface
(`scope`, `receive`, `send`) rather than `BaseHTTPMiddleware`, because the
latter buffers the request body — which would defeat a streaming size cap.

- **CorrelationIdMiddleware**: decodes the inbound header as `latin-1`
  (total, lossless, can never raise), validates it against
  `^[A-Za-z0-9._:-]{1,128}$` (log-injection guard), otherwise generates
  `uuid4().hex`; sets the `trace_id` contextvar for the request, and appends
  the header to the response by wrapping `send`. The contextvar is reset in
  a `finally` so a recycled task never leaks a stale ID.
- **BodySizeLimitMiddleware**: two layers — reject immediately on an honest
  `Content-Length` over the cap (before reading a byte), and wrap `receive`
  to count streamed bytes so chunked or lying clients are cut off mid-stream.
  The mid-stream abort raises `HTTPException(413)` specifically, because
  FastAPI re-raises that type untouched while wrapping arbitrary exceptions
  into a generic 400.

### 5.4 `api/errors.py` — one vocabulary for failure

All non-2xx responses have the shape
`{"errors": [{"code": ..., "description": ...}]}` with client-facing
descriptions only. Handlers are registered for:

| Exception                                       | Status              | Code                                                                                    | Log level                                     |
|-------------------------------------------------|---------------------|-----------------------------------------------------------------------------------------|-----------------------------------------------|
| `RequestValidationError` (incl. malformed JSON) | 400                 | `invalid_language` / `invalid_device` / `invalid_chart_config` / `invalid_request_body` | info (codes only — never the offending input) |
| `RequestError` (guards, e.g. 415)               | as raised           | as raised                                                                               | info                                          |
| `RenderError`                                   | 500                 | `render_failed`                                                                         | error + stack                                 |
| `RenderTimeout`                                 | 500                 | `render_timeout`                                                                        | error + stack                                 |
| `StorageError`                                  | 500                 | `storage_failed`                                                                        | error + stack                                 |
| `RendererBusy`                                  | 503 + `Retry-After` | `renderer_busy`                                                                         | warning (backpressure working, not a fault)   |
| Starlette `HTTPException` (404/405/413)         | as raised           | `not_found` / `method_not_allowed` / `request_body_too_large`                           | —                                             |
| `Exception` (catch-all)                         | 500                 | `internal_error`                                                                        | error + stack                                 |

Starlette resolves handlers by walking the exception's MRO, so
`RenderTimeout` (a subclass of `RenderError`) gets its specific handler
regardless of registration order.

### 5.5 `api/deps.py` — dependency injection seams

- `ChartExporter` **Protocol**: what the route needs (`async export(...)`),
  defined next to its consumer. `ChartExportService` satisfies it by shape.
- `require_json_content_type`: a router-level dependency (guard mode). FastAPI
  resolves dependencies before parsing the body, so a wrong Content-Type
  short-circuits with 415 without the payload ever being read.
- `get_chart_exporter`: the provider. Reads the process-wide renderer and
  storage from `app.state` and assembles a per-request `ChartExportService`
  (three attribute assignments — cheap and stateless). This is the bridge
  between lifespan-created singletons and request-scoped handlers.

Tests can swap at two seams: override `get_chart_exporter` (fake the whole
service) or replace `app.state.renderer` / `app.state.storage` (run the real
service over fakes).

### 5.6 `schemas/` and `domain/` — two kinds of data object

- **`schemas/` = pydantic**, at the HTTP boundary where data is untrusted and
  needs parsing/validation/serialisation. `language: Literal["en"]` and
  `device: Literal["desktop"]` encode the MVP restriction as types;
  `chart_config: dict[str, Any]` is deliberately **opaque** — the Design
  System owns that contract, so we validate only "non-empty object".
- **`domain/` = frozen, slotted dataclasses**, for trusted values built by our
  own code (`RenderedChart`, `StoredObject`) — no validation overhead, no
  framework dependency, immutable.
- Exception hierarchy: `RenderTimeout` *is a* `RenderError` (catchable
  together, distinguishable when needed); `RendererBusy` is deliberately a
  sibling (nothing failed — the render never started → 503, not 500).

### 5.7 `services/templating.py` — Jinja over Nunjucks templates

The DS templates are Nunjucks (`.njk`), a near-port of Jinja2. Three shims
close the gap: an `extend` global (list append usable from both languages),
`ChainableUndefined` (so `params.download.title` on a missing `download` is
undefined-and-falsy instead of raising, as Nunjucks behaves), and
`undefined = None` in globals.

The `tojson` filter is overridden **around, not instead of** Jinja's own
`do_tojson`: Undefined values are recursively cleaned to `None`, then the
real filter escapes `<`, `>`, `&`, `'`, U+2028 and U+2029 as `\uXXXX`. That is
what stops a `</script>` inside a chart title from terminating the script
block (the spike's bug).

Vendored CSS and JS are read once and exposed as `Markup` globals so the page
can inline them; autoescape is on for `.html`, `.xml` and `.njk`. The
environment is built once per process (`lru_cache`).

### 5.8 `services/renderer.py` — browser lifecycle and concurrency

```text
render(html)
  ├─ wait_for(sem.acquire(), queue_timeout)   → RendererBusy   (503)  ── slot not held: no release
  └─ try:
       wait_for(_do_render(html), render_timeout)  → RenderTimeout (500)  ── cancels the render
     finally:
       sem.release()                                                     ── ALWAYS returns the slot

_do_render(html)
  ├─ _ensure_browser()          double-checked locking: N concurrent requests on a
  │                              crashed browser trigger exactly one relaunch
  ├─ browser.new_context(viewport, device_scale_factor)    isolated, ~20 ms
  ├─ context.route("**/*", abort)                          NETWORK BLACKOUT (SSRF defence)
  ├─ page.set_content(html); _wait_until_ready(page)
  ├─ screenshot the chart element (.ons-chart, .chart, [data-chart]) or the page
  └─ finally: context.close()
```

- One browser per process, one context per request (the spike launched a
  browser per request: ~500 ms cold start and unbounded process growth).
- `asyncio.Semaphore(max_concurrent_renders)` is a **memory** ceiling (each
  open context with a rendered chart ≈ 50–100 MB), not a CPU one.
- Two timeouts are mandatory: bounded queueing (prevents unbounded backlog)
  and bounded rendering (prevents a pathological config pinning a slot while
  liveness still passes). Nesting: `queue + render` (20 s) < gunicorn worker
  timeout (25 s) < caller timeout < LB idle timeout.
- `_wait_until_ready` is isolated in one method because `networkidle` is a
  heuristic; it is the swap point for a DS render-complete signal.

### 5.9 `services/png.py` — dimensions from bytes

Playwright's bounding boxes are CSS pixels — wrong whenever
`device_scale_factor > 1`. The PNG itself cannot lie: signature check, IHDR
at offset 12, `struct.unpack(">II")` at offset 16, zero-dimension guard.
Invalid bytes raise `RenderError` (from the caller's view, garbage output
*is* a render failure).

### 5.10 `services/exporter.py` — orchestration

Spec-mandated ordering (id first, key derived), timing of the render and the
upload (`perf_counter`, logged as `render_ms` / `upload_ms`), dimensions read
**before** upload (fail before spending an S3 round-trip), upload via
`asyncio.to_thread` because boto3 blocks. Depends on a `SupportsRender`
Protocol rather than `ChartRenderer`, so the orchestration is testable with a
three-line fake. **`chart_config` is never logged.**

### 5.11 `storage/` — Protocol + two implementations

`StorageBackend.put(*, key, data, content_type) -> StoredObject` is
synchronous by design (boto3 blocks; async offloading is the caller's
concern), keyword-only (three string-ish args are easy to mis-order), and
returns domain data (the spike's storage returned a Flask `Response`).

`S3StorageBackend`: one boto3 client per instance (thread-safe, created once);
`endpoint_url` unset = real AWS, set = Floci; path-style addressing only with
a custom endpoint; `ACL=private` sent only when `s3_set_private_acl` is true
(BucketOwnerEnforced buckets reject any ACL); `BotoCoreError`/`ClientError`
→ `StorageError` with the boto detail in the message (logs only). A
pre-built client can be injected for tests (botocore `Stubber`).

`MemoryStorageBackend`: a dict, inspectable by tests, with a `fail_with`
fault-injection hook for exercising the 500 path through the real exporter.

### 5.12 `logging.py` and `version.py`

`logging.py` is the ONS template's DP-standards structlog pipeline
(namespace, severity codes, `spec_version`, structured `errors` chain,
`created_at`), routed so uvicorn's own loggers emit the same JSON. The branch
adds a `trace_id` `ContextVar` and processor: every log line in a request —
including from `to_thread` workers — carries the correlation ID with zero
coupling in `services/`.

`version.py` resolves `VERSION = GIT_TAG or GIT_COMMIT or pyproject version`
and converts the CI-provided `BUILD_TIME` epoch to ISO 8601 with a `Z`
suffix; a shared `iso8601()` helper keeps every timestamp in one format.

### 5.13 `api/routes/health.py`

Follows the DP health check specification. The single check reflects
`renderer.is_ready` (`browser is not None and browser.is_connected()`);
a dead browser yields `status: CRITICAL` with HTTP 500 so orchestrators stop
routing to the instance. `uptime` is milliseconds from the lifespan-captured
start time. The `checks` list is built with `all(...)`, so a second check
(e.g. S3 reachability, open question) participates automatically.

---

## 6. Design patterns in use

| Pattern                                                    | Where                                                                                              | Why                                                                                                                   |
|------------------------------------------------------------|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| **Layered architecture with a dependency rule**            | `api/` → `services/`/`storage/` → `domain/`                                                        | Services and storage are testable and reusable without HTTP; the route layer is thin                                  |
| **Dependency injection (constructor + FastAPI `Depends`)** | `ChartExportService(renderer, storage, key_prefix)`, `get_chart_exporter`, `Depends(get_settings)` | Construction separated from use; production wiring in lifespan, fakes in tests via `dependency_overrides`             |
| **Structural interfaces (Protocols)**                      | `ChartExporter`, `SupportsRender`, `StorageBackend`                                                | Consumers declare what they need; implementations conform by shape with no inheritance or imports in either direction |
| **Consumer-defined interface**                             | Protocols live next to the code that needs them                                                    | The interface is sized to the consumer's needs, not the implementation's surface                                      |
| **Composition root**                                       | `main.py` + lifespan                                                                               | One place to read the whole shape of the service; nothing stateful is created at import time                          |
| **Singleton per process + façade per request**             | browser / boto3 client on `app.state`; `ChartExportService` per request                            | Expensive resources shared; request handling stateless                                                                |
| **Exception translation at boundaries**                    | Playwright → `RenderError`; boto3 → `StorageError`; domain → HTTP in `errors.py`                   | Each layer speaks its own failure vocabulary; internals never reach clients                                           |
| **Double-checked locking**                                 | `_ensure_browser`                                                                                  | One relaunch under N concurrent failures                                                                              |
| **Bounded-resource guard (semaphore + timeouts)**          | `ChartRenderer.render`                                                                             | Predictable memory ceiling and bounded latency                                                                        |
| **Fault injection in fakes**                               | `MemoryStorageBackend(fail_with=...)`, `StubExporter(error=...)`                                   | Error paths tested through real code, not mocks of internals                                                          |
| **Pure functions where possible**                          | `read_png_dimensions`, `render_chart_html`, `inline_fonts`                                         | Trivially unit-testable with hand-built inputs                                                                        |
| **Immutable value objects**                                | frozen `Settings`, frozen slotted dataclasses                                                      | Safe to share across async tasks; typos in attribute names fail loudly                                                |

---

## 7. Decisions and the alternatives rejected

| Decision                                                             | Alternative(s) rejected                        | Reason                                                                                                                                              |
|----------------------------------------------------------------------|------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `async_playwright`, one browser per process, one context per request | Browser per request (spike); `sync_playwright` | ~500 ms cold start and process growth per request; sync API deadlocks inside an event loop                                                          |
| `asyncio.Semaphore` sized by memory (default 4)                      | Unbounded concurrency; CPU-based sizing        | Each open context ≈ 50–100 MB; the bound is what the pod memory limit is sized against                                                              |
| Two timeouts (queue → 503, render → 500)                             | One timeout; none                              | Unbounded queueing serves nobody; a pinned slot wedges the service while liveness passes                                                            |
| Pure ASGI middleware                                                 | `BaseHTTPMiddleware`                           | It buffers the body, defeating a streaming 413 cap                                                                                                  |
| 415 as a router-level dependency                                     | Middleware                                     | Dependency scope is exactly the charts router; middleware would police `/health` too                                                                |
| 422 → 400 remap with hand-written descriptions                       | FastAPI default 422                            | Spec mandates 400 and a fixed document; pydantic's raw errors echo the input                                                                        |
| `chart_config` opaque (`dict[str, Any]`)                             | Model the DS schema                            | Every validated field is a field we must change when the DS changes; validation scope follows ownership                                             |
| Dimensions from PNG bytes                                            | Playwright bounding box                        | Bounding boxes are CSS pixels; wrong at `device_scale_factor > 1`                                                                                   |
| Sync `StorageBackend` + `to_thread` at the call site                 | Async Protocol / aioboto3                      | Keeps implementations trivial; one async concern in one place; upload is not the bottleneck                                                         |
| Protocols over ABCs                                                  | ABCs                                           | No shared behaviour to inherit; implementations must not import interface modules (dependency rule); drift is caught by a typed assignment in tests |
| Vendor all DS assets at build time and inline them                   | Load from the CDN at render time               | Zero runtime fetches makes the total network block possible                                                                                         |
| Block **all** network in the render context                          | Allowlist                                      | Nothing legitimate to fetch; an allowlist is a maintenance surface and an SSRF hole waiting to happen                                               |
| Env-only configuration, fail loudly at boot                          | Config files; lazy validation                  | 12-factor; a misconfigured pod must die before receiving traffic                                                                                    |
| Module-level `app` singleton                                         | `create_app()` factory                         | Simpler for uvicorn/gunicorn targets; tests compensate with an autouse override-reset fixture                                                       |
| Frozen dataclasses in `domain/`                                      | pydantic models everywhere                     | Internally-built data needs no validation; `domain/` stays dependency-free                                                                          |
| `python:3.14-slim` + `playwright install-deps`                       | `mcr.microsoft.com/playwright/python`          | Python 3.14 and the template's uv-based build; system deps are installed the same way                                                               |
| Floci for local S3                                                   | MinIO, moto                                    | Speaks the AWS wire protocol unmodified; compat image ships init hooks and the aws CLI for bucket bootstrap                                         |

---

## 8. Security model

The service renders **caller-supplied data in a real browser inside a
private network**, so these are load-bearing:

1. **SSRF mitigation (defence in depth).** All DS assets (CSS, fonts as
   `data:` URIs, the Highcharts JS bundle) are vendored into the image at
   build time and inlined into the page. The render context then blocks the
   network in four independent ways: it aborts every HTTP request
   (`context.route("**/*", abort)`) and every WebSocket
   (`context.route_web_socket`); the page carries a `connect-src 'none'`
   Content-Security-Policy that blocks fetch/XHR/WebSocket/EventSource/beacon
   at the browser layer; and Chromium runs with non-proxied WebRTC UDP
   disabled. This holds even if caller-supplied markup reaches a raw-HTML
   (`| safe`) sink in the opaque `chart_config` — it cannot make Chromium
   reach the instance-metadata endpoint or any internal service. Deploy-time:
   IMDSv2 enforced; pod IAM role scoped to `s3:PutObject` on the charts
   prefix; an egress NetworkPolicy on the pod is recommended as a fifth layer.
2. **Script-context escaping.** Config is serialised into `<script>` blocks
   via Jinja's `tojson` (with `<`, `>`, `&`, `'`, U+2028/9 escaped); HTML
   contexts — including the DS `.njk` macros — are autoescaped; and strings
   under known raw-HTML keys (`download`, which the DS list macro renders
   through `| safe`) are HTML-escaped before templating. All injection
   surfaces are covered and regression-tested with real payloads.
3. **Body size cap (413)** on `Content-Length` *and* the streamed byte count.
4. **`chart_config` is never logged.** Logs carry the chart id, key, sizes,
   dimensions, durations and error codes. Validation logs carry mapped error
   codes only, never pydantic's `input` echo.
5. **Private uploads.** `ACL=private` or no ACL at all; there is no code path
   that can send a public ACL.
6. **Sanitised errors.** Responses carry fixed descriptions; exception
   messages, boto3 errors and paths go to logs only. Framework 404/405 are
   also wrapped in the spec document.
7. **Correlation header hygiene.** Inbound `X-Request-Id` is validated
   against a strict character class and length; anything else is replaced.
8. **Container.** Non-root user; Chromium runs **without** `--no-sandbox`;
   `Server` header blanked by the gunicorn config.

---

## 9. Testing strategy

Four layers, each faking exactly the layer below it — possible only because
every boundary is a Protocol with constructor injection.

| Layer                 | Location                               | Fakes                                                                                                | Proves                                                                                                                                                  |
|-----------------------|----------------------------------------|------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| API (the bulk)        | `tests/unit/api/`                      | `StubExporter` via `dependency_overrides`, or `StubRenderer` + `MemoryStorageBackend` on `app.state` | Every status code and error document, byte-exact; the wiring from `app.state` through the real service                                                  |
| Service orchestration | `tests/unit/services/test_exporter.py` | `StubRenderer`, `MemoryStorageBackend`                                                               | id-first ordering, key derivation, nothing stored on failure                                                                                            |
| Renderer              | `tests/unit/services/test_renderer.py` | fast tier: `_do_render` stubbed; slow tier: real Chromium                                            | semaphore bounds, both timeouts and slot release (fast); DSF pixel doubling, element screenshot, real DS chart with zero network, crash recovery (slow) |
| Templating / PNG      | `tests/unit/services/`                 | none (vendored templates, hand-built bytes)                                                          | the `</script>`, U+2028 and autoescape regressions; IHDR parsing edge cases                                                                             |
| Storage               | `tests/unit/storage/`                  | botocore `Stubber` (fast); Floci (e2e)                                                               | exact `put_object` params incl. ACL present/absent; real round-trip and no public grants                                                                |
| End to end            | `tests/e2e/`                           | none                                                                                                 | POST → 201 → object in Floci → parsed PNG dimensions equal the response                                                                                 |

`make test` runs the fast layers in parallel with a **100 % coverage gate**
(browser-touching methods are marked `pragma: no cover` and measured by the
slow tier instead). `make test-all` adds the slow and e2e layers; e2e tests
skip with a message when Floci is not reachable.

Mutation checks (performed during review) confirmed the suite fails when the
semaphore is not released, the JSON escaping is naïve, the ACL is dropped or
made public, the 415 guard or streamed 413 check is removed, validation
returns 422, internal detail leaks into a 500, `Retry-After` is dropped,
PNG width/height are swapped, the key is not derived from the id, an
invalid PNG is uploaded, empty `chart_config` or `language=cy` is accepted,
health always reports OK, or `s3_bucket` becomes optional.

---

## 10. Local development and build

- `make up` starts the service (dev image, code bind-mounted, `shm_size` 2 GB
  for Chromium) and Floci with a ready-hook that creates the bucket;
  templates are vendored first if missing.
- `.design-system-version` pins the DS release. `make design-system` /
  the `web` image build download the templates, the CSS/JS bundle and every
  font referenced by the CSS, then rewrite the font URLs to `data:` URIs.
- `openapi.yaml` is generated from the app and checked in CI for drift.
- Lint: ruff (incl. bandit rules), mypy (strict-ish), pylint 10/10;
  pre-commit runs all of them plus the OpenAPI export.

---

## 11. How the design accommodates foreseeable change

| Foreseeable change                                | What changes                                                                                          | What does not                                                                           |
|---------------------------------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| Welsh (`language=cy`)                             | `Literal["en", "cy"]` in the request schema; `language` already flows to the template's `<html lang>` | Route, service, renderer, storage                                                       |
| `device=mobile`                                   | A per-device viewport/scale lookup replacing the single Settings values                               | Everything downstream of the renderer's constructor args                                |
| Canonical viewport / `device_scale_factor` agreed | Env vars                                                                                              | Code — dimensions are already read from the PNG, so metadata stays correct at any scale |
| DS release                                        | `.design-system-version`, re-vendor                                                                   | The page shell and the service — the DS macro owns the chart markup                     |
| DS render-complete signal                         | `_wait_until_ready` (one method)                                                                      | The rest of the renderer                                                                |
| `BucketOwnerEnforced` bucket                      | `CHART_EXPORTER_S3_SET_PRIVATE_ACL=false`                                                             | Code                                                                                    |
| A different object store                          | A new `StorageBackend` implementation                                                                 | Service, route, tests above the storage layer                                           |
| S3 reachability in `/health`                      | A second `Check` appended to the list                                                                 | Aggregation, status mapping                                                             |
| Metrics / histograms                              | Emit from the already-measured `render_ms` / `upload_ms`                                              | Orchestration                                                                           |
| Async/queued rendering (future phase)             | A new route + worker over the same `ChartExportService`                                               | Renderer, storage, templating                                                           |
| Wagtail integration, auth                         | Upstream at the API router                                                                            | This service                                                                            |

The properties that make this cheap: the opaque config (no DS field
knowledge to update), Protocol boundaries (swap any layer without touching
its neighbours), env-only config (behaviour changes without rebuilds), and a
single orchestration function that reads as the spec's ordering.

---

## 12. Open questions (tracked, not silently resolved)

1. 503 + `Retry-After` for queue saturation — an extension to the agreed spec.
2. 413 for oversized bodies — likewise.
3. S3 bucket ACL mode (`BucketOwnerEnforced` vs ACL-enabled) — the config flag
   keeps us compatible either way; the platform team owns the answer.
4. Canonical viewport and `device_scale_factor` for `device=desktop`.
5. A DS render-complete signal to replace `networkidle`.
6. Whether `/health` should include an S3 reachability check.
