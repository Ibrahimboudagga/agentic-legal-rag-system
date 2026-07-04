# Observability Implementation — Technical Documentation

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [New Files](#new-files)
- [Modified Files](#modified-files)
- [Design Decisions](#design-decisions)
- [Metrics Reference](#metrics-reference)
- [Correlation IDs](#correlation-ids)
- [Grafana Dashboards](#grafana-dashboards)
- [Infrastructure](#infrastructure)
- [Environment Variables](#environment-variables)
- [Running the Stack](#running-the-stack)

---

## Overview

This document describes the production-grade observability layer added to the AI Contract Intelligence Platform. The implementation adds three pillars of observability — **logs**, **metrics**, and **traces** — with full correlation across all three.

### What Was Added

| Pillar | Technology | Details |
|--------|-----------|---------|
| **Structured Logging** | structlog + python-logging-loki | JSON logs with correlation IDs, pushed directly to Loki via HTTP |
| **Metrics** | prometheus-client | 20 custom metrics with `contract_review_` prefix, scraped by Prometheus |
| **Distributed Tracing** | OpenTelemetry + Temporal TracingInterceptor | End-to-end traces from API → Workflow → Activity → LLM → S3 |
| **Dashboards** | Grafana | 6 pre-provisioned dashboards covering all operational concerns |
| **Log Aggregation** | Grafana Loki | Direct HTTP push from Python app (no Promtail sidecar) |
| **Trace Backend** | Jaeger | Receives OTLP traces from OTel Collector |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Application Layer                               │
│                                                                         │
│  FastAPI (:5000)              Temporal Worker (:9001 metrics)           │
│  ┌──────────────────┐         ┌──────────────────────────────┐          │
│  │ ObservabilityMW  │         │ OTel TracingInterceptor      │          │
│  │ - request_id     │         │ - workflow_id propagation     │          │
│  │ - trace_id       │         │ - activity span creation      │          │
│  │ - timing         │         │ - SDK metrics → OTel          │          │
│  │ /metrics → :9002 │         │ /metrics → :9001              │          │
│  └────────┬─────────┘         └──────────────┬───────────────┘          │
│           │                                  │                          │
│           │    ┌─────────────────────────────┘                          │
│           │    │                                                        │
│           │    │  shared/observability/                                 │
│           │    │  ├── logging.py    (structlog + Loki handler)          │
│           │    │  ├── metrics.py    (Prometheus registry)               │
│           │    │  ├── tracing.py    (OTel + Temporal interceptor)       │
│           │    │  └── middleware.py (FastAPI request middleware)         │
│           │    │                                                        │
└───────────┼────┼────────────────────────────────────────────────────────┘
            │    │
     stdout │    │ OTLP gRPC :4317
            ▼    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     OpenTelemetry Collector                              │
│  receivers: OTLP (gRPC :4317, HTTP :4318)                               │
│  processors: batch (1s timeout, 1024 batch size)                        │
│  exporters:                                                             │
│    traces  → Jaeger (:14250)                                            │
│    metrics → Prometheus (:8889)                                         │
└────────┬──────────────────────────────────────────────┬─────────────────┘
         │                                              │
         ▼                                              ▼
┌────────────────┐                    ┌──────────────────────────┐
│    Jaeger       │                    │      Prometheus          │
│  :16686 (UI)    │                    │      :9090               │
│                 │                    │                          │
│  Distributed    │                    │  Scrapes:                │
│  Tracing UI     │                    │  - OTel Collector :8889  │
└────────────────┘                    │  - Python Worker  :9001  │
                                      │  - Python API     :9002  │
                                      │  - Temporal Server:8233  │
                                      └────────────┬─────────────┘
                                                   │
                                                   ▼
                                      ┌──────────────────────────┐
                                      │      Grafana :8085       │
                                      │                          │
                                      │  Datasources:            │
                                      │  - Prometheus (default)  │
                                      │  - Jaeger                │
                                      │  - Loki                  │
                                      │                          │
                                      │  6 Dashboards:           │
                                      │  - Workflow Health       │
                                      │  - LLM Usage & Cost      │
                                      │  - Worker Performance    │
                                      │  - Latency               │
                                      │  - Failures              │
                                      │  - Human Review          │
                                      └──────────────────────────┘

Log Flow (direct to Loki):
  Python app → structlog JSON → LokiBatchQueueHandler → HTTP POST → Loki :3100
```

---

## New Files

### `app/shared/__init__.py`

Empty package marker for the shared library.

### `app/shared/observability/__init__.py`

Re-exports all public APIs from the four observability modules for convenient imports:

```python
from shared.observability import (
    configure_logging, get_logger,
    REGISTRY, record_llm_call, get_metrics_endpoint,
    setup_tracing, setup_temporal_runtime,
    ObservabilityMiddleware,
)
```

### `app/shared/observability/logging.py`

**Purpose:** Structured JSON logging with correlation IDs and direct Loki push.

**Key components:**

| Component | Description |
|-----------|-------------|
| `trace_id_var` | `contextvars.ContextVar[str]` — OTel trace ID |
| `workflow_id_var` | `contextvars.ContextVar[str]` — Temporal workflow ID |
| `run_id_var` | `contextvars.ContextVar[str]` — Temporal run ID |
| `activity_type_var` | `contextvars.ContextVar[str]` — Current activity type |
| `request_id_var` | `contextvars.ContextVar[str]` — HTTP request UUID |
| `task_queue_var` | `contextvars.ContextVar[str]` — Temporal task queue |
| `_add_correlation_ids()` | structlog processor that injects all context vars into every log line |
| `configure_logging()` | Configures structlog pipeline and optionally sets up Loki handler |
| `_setup_loki_handler()` | Creates `LokiBatchQueueHandler` for non-blocking batched log shipping |
| `get_logger()` | Factory returning a structlog bound logger |
| `flush_loki()` | Manual flush for graceful shutdown |

**structlog processor pipeline:**

```
1. merge_contextvars     → picks up any contextvars set by structlog.bind()
2. add_log_level         → adds "level" field
3. TimeStamper(fmt="iso") → adds ISO timestamp
4. StackInfoRenderer     → renders stack info if requested
5. format_exc_info       → formats exception info
6. _add_correlation_ids  → injects trace_id, workflow_id, run_id, activity_type, request_id, task_queue
7. JSONRenderer          → final JSON output
```

**Loki handler configuration:**

```python
LokiBatchQueueHandler(
    Queue(-1),                          # non-blocking queue
    url="{LOKI_URL}/loki/api/v1/push", # Loki push endpoint
    tags={"app": APP_NAME, "environment": ENVIRONMENT},
    version="2",                        # Loki push API v2
    flush_interval=LOKI_BATCH_INTERVAL, # default 5.0 seconds
)
```

**Why `LokiBatchQueueHandler` over `LokiHandler`:**
- `LokiHandler` blocks on every log call (HTTP POST per line)
- `LokiBatchQueueHandler` buffers logs and flushes in batches
- Reduces HTTP overhead, improves throughput
- Non-blocking: log calls never delay application code
- Groups logs by label set for efficient Loki ingestion

**Why not Promtail:**
- Promtail requires a sidecar container or host agent
- Direct HTTP push is simpler for a Python-only deployment
- `python-logging-loki` is well-maintained and documented by Grafana
- Fewer moving parts in the infrastructure

### `app/shared/observability/metrics.py`

**Purpose:** Prometheus metrics registry with `contract_review_` prefix.

**Why `contract_review_` prefix:**
- Temporal SDK emits metrics with `temporal_` prefix via Rust core
- Using a different prefix avoids label collisions
- Makes it clear which metrics are application-level vs SDK-level
- Follows Prometheus naming best practices (`namespace_subsystem_name`)

**Complete metrics inventory:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_workflow_started_total` | Counter | `workflow_type`, `task_queue` | Total workflows started |
| `contract_review_workflow_completed_total` | Counter | `workflow_type`, `task_queue` | Total workflows completed |
| `contract_review_workflow_failed_total` | Counter | `workflow_type`, `task_queue`, `error_type` | Total workflows failed |
| `contract_review_workflow_duration_seconds` | Histogram | `workflow_type` | End-to-end workflow duration |
| `contract_review_activity_duration_seconds` | Histogram | `activity_type`, `task_queue` | Activity execution duration |
| `contract_review_activity_completed_total` | Counter | `activity_type`, `task_queue` | Total activities completed |
| `contract_review_activity_failed_total` | Counter | `activity_type`, `task_queue`, `error_type` | Total activities failed |
| `contract_review_llm_requests_total` | Counter | `model`, `operation` | Total LLM API requests |
| `contract_review_llm_request_duration_seconds` | Histogram | `model`, `operation` | LLM request duration |
| `contract_review_llm_tokens_input_total` | Counter | `model` | Total input tokens consumed |
| `contract_review_llm_tokens_output_total` | Counter | `model` | Total output tokens consumed |
| `contract_review_llm_cost_dollars` | Counter | `model` | Estimated LLM cost in USD |
| `contract_review_documents_processed_total` | Counter | `status` | Documents processed (success/failed) |
| `contract_review_pdf_extraction_duration_seconds` | Histogram | — | PDF extraction duration |
| `contract_review_human_review_wait_seconds` | Histogram | — | Time waiting for human decision |
| `contract_review_human_review_started_total` | Counter | — | Reviews initiated |
| `contract_review_human_review_approved_total` | Counter | — | Reviews approved |
| `contract_review_human_review_revised_total` | Counter | — | Reviews requesting revision |
| `contract_review_human_review_timeout_total` | Counter | — | Reviews that timed out |
| `contract_review_active_workflows` | Gauge | `workflow_type` | Currently active workflows |
| `contract_review_active_activities` | Gauge | `activity_type` | Currently running activities |

**Histogram bucket choices:**

| Metric | Buckets | Rationale |
|--------|---------|-----------|
| `workflow_duration_seconds` | 1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600 | Workflows can range from seconds to hours (HITL waits) |
| `activity_duration_seconds` | 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600 | Activities range from sub-second to 10 min (PDF extraction) |
| `llm_request_duration_seconds` | 0.5, 1, 2, 5, 10, 30, 60, 120 | LLM calls typically 1-60 seconds |
| `pdf_extraction_duration_seconds` | 0.5, 1, 2, 5, 10, 30, 60, 120 | PDF extraction depends on page count |
| `human_review_wait_seconds` | 60, 300, 600, 1800, 3600, 86400, 172800, 259200 | Review can take minutes to 3 days |

**Helper function: `record_llm_call()`**

```python
def record_llm_call(
    model: str,           # e.g. "deepseek/deepseek-v4-flash"
    operation: str,       # e.g. "summary", "synthesis", "revision"
    duration: float,      # seconds
    tokens_in: int,       # prompt tokens from response.usage
    tokens_out: int,      # completion tokens from response.usage
    input_price_per_1k: float,   # from env var
    output_price_per_1k: float,  # from env var
):
```

Cost formula: `(tokens_in / 1000 * input_price_per_1k) + (tokens_out / 1000 * output_price_per_1k)`

### `app/shared/observability/tracing.py`

**Purpose:** OTel TracerProvider setup and Temporal runtime configuration.

**Two factory functions:**

1. `setup_tracing(service_name)` → returns `TracingInterceptor`
   - Creates `TracerProvider` with OTLP gRPC exporter
   - Points to OTel Collector at `OTEL_ENDPOINT` (default: `http://localhost:4317`)
   - Returns a `TracingInterceptor` that implements both `ClientInterceptor` and `WorkerInterceptor`
   - Automatically creates spans for: workflow execution, activity execution, client calls

2. `setup_temporal_runtime()` → returns `Runtime`
   - Configures Temporal SDK to route its internal metrics to OTel Collector
   - Uses `durations_as_seconds=True` for Prometheus-compatible float seconds
   - SDK metrics become `temporal_*` metrics visible in Prometheus via OTel Collector

**Why OTel instead of direct Jaeger integration:**
- OTel is the CNCF standard for telemetry
- Collector acts as a single pipeline for traces, metrics, and logs
- Easy to swap backends (Jaeger → Datadog → Grafana Cloud) without code changes
- Temporal SDK has native OTel support via `temporalio[opentelemetry]`

### `app/shared/observability/middleware.py`

**Purpose:** FastAPI middleware that instruments every HTTP request.

**What it does per request:**

1. Extracts or generates `X-Request-ID` (UUID4)
2. Sets `request_id_var` contextvar (propagates to all downstream logs)
3. Extracts OTel `trace_id` from current span
4. Sets `trace_id_var` contextvar
5. Logs `http_request_started` with method, path, query, client IP
6. Times the request
7. Logs `http_request_completed` with status code and duration
8. Adds `X-Request-ID` and `X-Trace-ID` response headers
9. On exception: logs `http_request_failed` with error details

**Why not `prometheus-fastapi-instrumentator`:**
- The instrumentator provides generic `http_requests_total` and `http_request_duration_seconds`
- Our middleware adds correlation ID propagation which the instrumentator doesn't support
- We can still add the instrumentator later for additional generic metrics
- Custom middleware gives full control over label cardinality

---

## Modified Files

### `app/ai_contract_review/activities.py`

**Changes:**

| Section | Before | After |
|---------|--------|-------|
| Imports | None | Added `time`, `shared.observability.logging`, `shared.observability.metrics` |
| Env vars | None | Added `LLM_MODEL`, `LLM_INPUT_PRICE_PER_1K`, `LLM_OUTPUT_PRICE_PER_1K` |
| Logging | `activity.logger.info()` only | `structlog.get_logger()` with correlation IDs |
| `extract_pdf` | No metrics | Added timing, `active_activities` gauge, `activity_duration_seconds`, `activity_completed_total`, `pdf_extraction_duration_seconds`, `documents_processed_total` |
| `call_llm` | No metrics, no token tracking | Added timing, token extraction from `response.usage`, `record_llm_call()` with cost calculation |
| Error handling | No metrics on failure | Added `activity_failed_total` with `error_type` label, `documents_processed_total.labels(status="failed")` |

**LLM token extraction:**

```python
tokens_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
tokens_out = getattr(response.usage, "completion_tokens", 0) if response.usage else 0
```

Uses `getattr` with fallback because OpenRouter responses may not always include usage data.

### `app/ai_contract_review/parent_worker.py`

**Changes:**

| Section | Before | After |
|---------|--------|-------|
| Imports | None | Added `time`, `shared.observability.logging`, `shared.observability.metrics` |
| `__init__` | No timing | Added `_start_time`, `_review_wait_start` |
| `run()` | No metrics | Added `workflow_started_total.inc()` at start, `workflow_completed_total`/`workflow_failed_total` at end, `workflow_duration_seconds` observation, `active_workflows` gauge management |
| Fan-out | Logged child failures only | Added `fan_out_started`/`fan_out_completed` logs with succeeded/failed counts |
| Synthesis | No timing | Added `synthesis_start` timing and `synthesis_completed` log |
| HITL loop | No metrics | Added `human_review_started_total` when entering wait, `human_review_wait_seconds` on decision, `human_review_approved_total`/`human_review_revised_total`/`human_review_timeout_total` based on outcome |
| Error handling | No metrics | Added `workflow_failed_total` with `error_type` label |

**Exception handling structure:**

```python
try:
    result = await self._run_inner(param)
    # record completion metrics
    return result
except Exception as exc:
    # record failure metrics
    raise
finally:
    active_workflows.labels(workflow_type="ContractReviewerWorkflow").dec()
```

The `finally` block ensures the active workflow gauge is always decremented, even on unexpected exceptions.

### `app/ai_contract_review/child_worker.py`

**Changes:**

| Section | Before | After |
|---------|--------|-------|
| Imports | None | Added `time`, `shared.observability.logging`, `shared.observability.metrics` |
| `run()` | No metrics | Added `workflow_started_total` at start, `workflow_completed_total`/`workflow_failed_total` at end, `workflow_duration_seconds`, `active_workflows` gauge |
| PDF extraction | No timing | Added `extract_start` timing and `pdf_extraction_completed` log with page count |
| LLM call | No timing | Added `llm_start` timing and `child_workflow_completed` log with durations |
| Error handling | No metrics | Added `workflow_failed_total` with `error_type` label |

### `app/ai_contract_review/worker.py`

**Changes:**

| Section | Before | After |
|---------|--------|-------|
| Imports | Basic | Added `prometheus_client.start_http_server`, `shared.observability.logging`, `shared.observability.metrics`, `shared.observability.tracing` |
| Startup | `asyncio.run(main())` only | Added `configure_logging()`, `setup_loki_handler()`, Prometheus metrics server on port 9001 |
| Temporal client | `Client.connect(TEMPORAL_HOST)` | `Client.connect(TEMPORAL_HOST, interceptors=[tracing_interceptor], runtime=temporal_runtime)` |
| Logging | None | Worker startup log with task_queue, workflows, activities, metrics_port |

**Port allocation:**

| Port | Service | Reason |
|------|---------|--------|
| 9001 | Worker Prometheus metrics | Separate from API to allow independent scaling |
| 9002 | API Prometheus metrics | Separate from worker to avoid port conflicts |
| 4317 | OTel Collector gRPC | Standard OTLP port |
| 8889 | OTel Collector Prometheus export | Scraped by Prometheus |

### `app/client_app/main.py`

**Changes:**

| Section | Before | After |
|---------|--------|-------|
| Imports | Basic | Added `shared.observability.logging`, `shared.observability.middleware`, `shared.observability.metrics` |
| App setup | `FastAPI(title="S3 PDF Extraction Client")` | `FastAPI(title="AI Contract Intelligence Platform", version="2.0.0")` + `app.add_middleware(ObservabilityMiddleware)` |
| Startup | None | `configure_logging()`, Prometheus metrics server on port 9002 |
| Endpoints | No logging | Added `log.info()` at request start/completion for all endpoints |
| Error handling | `raise HTTPException` only | Added `log.error()` before raising |

**Title change rationale:** The original title "S3 PDF Extraction Client" didn't reflect the system's actual capability as an AI Contract Intelligence Platform.

### `app/ai_contract_review/requirements.txt`

**Added packages:**

| Package | Version | Purpose |
|---------|---------|---------|
| `temporalio[opentelemetry]` | ≥1.29.0 | OTel tracing interceptor for Temporal |
| `structlog` | ≥24.1.0 | Structured JSON logging |
| `prometheus-client` | ≥0.21.0 | Prometheus metrics registry |
| `python-logging-loki` | ≥0.3.2 | Loki log handler with batch support |
| `opentelemetry-api` | ≥1.29.0 | OTel API |
| `opentelemetry-sdk` | ≥1.29.0 | OTel SDK |
| `opentelemetry-exporter-otlp-proto-grpc` | ≥1.29.0 | OTLP gRPC exporter |

### `app/client_app/requirements.txt`

**Added packages:**

| Package | Version | Purpose |
|---------|---------|---------|
| `structlog` | ≥24.1.0 | Structured JSON logging |
| `prometheus-client` | ≥0.21.0 | Prometheus metrics registry |
| `python-logging-loki` | ≥0.3.2 | Loki log handler |

### `samples-server/compose/deployment/otel/otel-config.yaml`

**Changes:**

| Before | After |
|--------|-------|
| Only traces pipeline (OTLP → Jaeger) | Added metrics pipeline (OTLP → Prometheus) |
| No Prometheus exporter | Added `prometheus` exporter on `0.0.0.0:8889` |
| No namespace | Added `namespace: "temporal_app"` |
| No batch config | Added `timeout: 1s`, `send_batch_size: 1024` |

### `samples-server/compose/deployment/prometheus/config.yml`

**Added scrape targets:**

| Job Name | Target | Purpose |
|----------|--------|---------|
| `contract_review_worker` | `host.docker.internal:9001` | Python worker custom metrics |
| `contract_review_api` | `host.docker.internal:9002` | Python API custom metrics |
| `otel_collector` | `host.docker.internal:8889` | Temporal SDK metrics via OTel |

### `samples-server/compose/deployment/grafana/provisioning/datasources/all.yml`

**Added:** Jaeger datasource pointing to `http://jaeger-all-in-one:16686`

### `samples-server/compose/deployment/grafana/provisioning/dashboards/all.yml`

**Changed:** Folder from `''` to `'Contract Review'` for dashboard organization.

---

## Design Decisions

### 1. Direct Loki Push vs Promtail

| Option | Pros | Cons |
|--------|------|------|
| **Direct HTTP push (chosen)** | No sidecar needed, simpler infra, Python-native | App handles its own log shipping |
| Promtail | Separate concerns, auto-discovery | Extra container, config overhead, Docker-only |

**Decision:** Direct push via `python-logging-loki` because:
- Fewer infrastructure components to manage
- Works in any deployment (Docker, K8s, bare metal)
- `LokiBatchQueueHandler` provides production-grade batching
- Grafana themselves maintain the `python-logging-loki` library

### 2. Metric Prefix: `contract_review_` vs `app_` vs `temporal_app_`

| Option | Pros | Cons |
|--------|------|------|
| `app_` | Generic, reusable | Too generic, collides with other services |
| `temporal_app_` | Connects to Temporal | Confusing with `temporal_` SDK prefix |
| **`contract_review_` (chosen)** | Specific, unambiguous, no collision | Tied to this specific application |

**Decision:** `contract_review_` because:
- Zero collision risk with Temporal SDK's `temporal_` prefix
- Clear ownership — anyone reading Prometheus knows exactly what this metric is for
- Follows the convention of `<service>_<metric>` in Prometheus

### 3. Two Metrics Endpoints (9001 + 9002) vs One

| Option | Pros | Cons |
|--------|------|------|
| **Two endpoints (chosen)** | Independent scaling, separate concerns, fault isolation | Two scrape targets in Prometheus |
| One shared endpoint | Simpler | Couples worker and API metrics, port conflicts during scaling |

**Decision:** Separate ports because:
- Worker and API scale independently (different pods/containers)
- Worker crashes don't affect API metrics availability
- Allows different scrape intervals if needed

### 4. OTel Collector vs Direct Export

| Option | Pros | Cons |
|--------|------|------|
| **OTel Collector (chosen)** | Single pipeline, backend-agnostic, batching, easy swaps | Extra component |
| Direct to Jaeger | Simpler | Tightly coupled to Jaeger |

**Decision:** OTel Collector because:
- Temporal SDK already supports OTel natively
- Can export to multiple backends simultaneously
- Easy to add Datadog, Grafana Cloud, etc. later
- CNCF standard — portable across vendors

### 5. Histogram Buckets

Custom buckets were chosen over default Prometheus buckets because:

- Default buckets (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, ...) are too fine-grained for workflow durations
- Workflows can take hours (HITL with 3-day timeout) — need buckets up to 3600s
- LLM calls are typically 1-60 seconds — buckets optimized for that range
- PDF extraction depends on page count — sub-second to 2 minutes

### 6. Structured Logging with structlog vs Standard Library logging

| Option | Pros | Cons |
|--------|------|------|
| **structlog (chosen)** | JSON output, processor pipeline, context binding, clean API | New dependency |
| stdlib logging | Built-in | JSON formatting requires manual `Formatter`, no context binding |

**Decision:** structlog because:
- Clean JSON output by default
- Processor pipeline allows adding correlation IDs non-invasively
- `contextvars` integration works naturally with async code
- Used by the Temporal Python SDK examples

---

## Correlation IDs

Every log line includes these correlation fields:

```json
{
  "timestamp": "2026-07-04T12:00:00.000000Z",
  "level": "info",
  "event": "llm_call_completed",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "workflow_id": "contract-review-abc-123",
  "run_id": "def-456-ghi",
  "activity_type": "call_llm",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_queue": "contract-review-queue",
  "model": "deepseek/deepseek-v4-flash",
  "tokens_in": 1234,
  "tokens_out": 567,
  "duration_seconds": 12.34
}
```

**How they propagate:**

| ID | Set By | Propagated Via |
|----|--------|---------------|
| `request_id` | `ObservabilityMiddleware` | `contextvars` → all downstream code in same async context |
| `trace_id` | OTel `TracingInterceptor` | OTel context → `contextvars` → log processor |
| `workflow_id` | `workflow.info()` in workflow code | `contextvars` set at workflow entry → activities |
| `run_id` | `workflow.info()` in workflow code | `contextvars` set at workflow entry |
| `activity_type` | Activity function body | `activity_type_var.set()` at activity start |
| `task_queue` | `workflow.info()` or env var | `contextvars` |

---

## Grafana Dashboards

### Dashboard 1: Workflow Health (`workflow-health`)

**Purpose:** Monitor overall workflow lifecycle health.

| Panel | Type | Key Query |
|-------|------|-----------|
| Active Workflows | Stat | `contract_review_active_workflows` |
| Start Rate | Time Series | `rate(contract_review_workflow_started_total[5m])` |
| Completion Rate | Time Series | `rate(contract_review_workflow_completed_total[5m])` |
| Failure Rate | Time Series | `rate(contract_review_workflow_failed_total[5m])` |
| Success Ratio | Gauge | `completed / (completed + failed)` |
| Duration P50/P95/P99 | Time Series | `histogram_quantile(...)` |
| Temporal SDK Completed | Time Series | `rate(temporal_workflow_completed_total[5m])` |
| Temporal SDK Failed | Time Series | `rate(temporal_workflow_failed_total[5m])` |

### Dashboard 2: LLM Usage & Cost (`llm-usage-cost`)

**Purpose:** Track LLM API consumption and costs.

| Panel | Type | Key Query |
|-------|------|-----------|
| Requests Rate | Time Series | `rate(contract_review_llm_requests_total[5m])` |
| Latency P50/P95/P99 | Time Series | `histogram_quantile(...)` |
| Cost ($/hr) | Stat | `rate(contract_review_llm_cost_dollars[1h]) * 3600` |
| Total Cost | Stat | `sum(contract_review_llm_cost_dollars)` |
| Token Input/Output | Time Series | `rate(contract_review_llm_tokens_*_total[5m])` |
| Token by Model | Pie Chart | `sum(contract_review_llm_tokens_*_total) by (model)` |
| Cost by Operation | Time Series | `rate(contract_review_llm_cost_dollars[5m]) by (operation)` |
| Token Efficiency | Time Series | `output_tokens / input_tokens` |

### Dashboard 3: Worker Performance (`worker-performance`)

**Purpose:** Monitor activity execution and worker health.

| Panel | Type | Key Query |
|-------|------|-----------|
| Active Activities | Stat | `contract_review_active_activities` |
| Activity Duration P50/P95/P99 | Time Series | `histogram_quantile(...)` |
| Activity Rate | Time Series | `rate(contract_review_activity_completed_total[5m])` |
| Activity Failure Rate | Time Series | `rate(contract_review_activity_failed_total[5m])` |
| Success Ratio | Time Series | `completed / (completed + failed)` |
| Documents Processed | Time Series | `rate(contract_review_documents_processed_total[5m])` |
| PDF Extraction Latency | Time Series | P95 of `pdf_extraction_duration_seconds` |
| Worker Task Slots | Gauge | `temporal_worker_task_slots_available` |
| Temporal E2E Latency | Time Series | P95 of `temporal_activity_endtoend_latency` |

### Dashboard 4: Latency (`latency`)

**Purpose:** Comprehensive latency view across all components.

| Panel | Type | Key Query |
|-------|------|-----------|
| E2E Workflow Latency Heatmap | Heatmap | `sum(rate(workflow_duration_seconds_bucket[5m])) by (le)` |
| Workflow Latency Percentiles | Time Series | P50/P95/P99 of `workflow_duration_seconds` |
| PDF Extraction Latency | Time Series | P50/P95/P99 of `pdf_extraction_duration_seconds` |
| LLM Call Latency | Time Series | P50/P95/P99 of `llm_request_duration_seconds` |
| API Request Latency | Time Series | P95 of `http_request_duration_seconds` by path |
| Task Queue Wait | Time Series | P95 of `temporal_workflow_task_schedule_to_start_latency` |
| Activity Task Queue Wait | Time Series | P95 of `temporal_activity_task_schedule_to_start_latency` |

### Dashboard 5: Failures (`failures`)

**Purpose:** Monitor all failure modes.

| Panel | Type | Key Query |
|-------|------|-----------|
| Overall Failure Rate | Stat | `sum(rate(workflow_failed_total[5m]))` |
| Total Failures (24h) | Stat | `sum(increase(workflow_failed_total[24h]))` |
| Time Since Last Failure | Stat | `time() - temporal_workflow_failed` |
| Failures by Error Type | Time Series | `rate(workflow_failed_total[5m]) by (error_type)` |
| Failures by Workflow | Time Series | `rate(workflow_failed_total[5m]) by (workflow_type)` |
| Activity Failures | Time Series | `rate(activity_failed_total[5m]) by (activity_type, error_type)` |
| Failure Trend (7-day) | Time Series | `sum(increase(workflow_failed_total[24h]))` |
| Retry Effectiveness | Gauge | `completed / (completed + failed)` |
| Error Distribution | Pie Chart | `sum(workflow_failed_total) by (error_type)` |
| Failure by Activity | Bar Chart | `sum(activity_failed_total) by (activity_type)` |

### Dashboard 6: Human Review (`human-review`)

**Purpose:** Monitor the human-in-the-loop process.

| Panel | Type | Key Query |
|-------|------|-----------|
| Active Reviews Waiting | Stat | `active_workflows{workflow_type="ContractReviewerWorkflow"}` |
| Total Reviews Started | Stat | `sum(human_review_started_total)` |
| Approval Rate | Gauge | `approved / (approved + revised + timeout)` |
| Revision Rate | Gauge | `revised / (approved + revised + timeout)` |
| Wait Time P50/P95/P99 | Time Series | `histogram_quantile(human_review_wait_seconds)` |
| Decisions Over Time | Time Series (stacked) | Approved, Revised, Timed Out rates |
| Auto-Timeout Rate | Time Series | `rate(human_review_timeout_total[5m])` |
| Avg Revisions/Workflow | Stat | `revised_total / started_total` |
| Turnaround Distribution | Time Series | `human_review_wait_seconds_bucket` |
| Decisions by Type | Pie Chart | Approved vs Revised vs Timeout |

---

## Infrastructure

### `docker-compose-observability.yml`

Extends the base Temporal stack with full observability:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| postgresql | `postgres:16` | 5432 | Temporal persistence |
| temporal | `temporalio/server:1.31.0` | 7233, 8233 | Workflow engine + metrics |
| temporal-ui | `temporalio/ui:2.49.1` | 8080 | Temporal Web UI |
| otel-collector | `otel/opentelemetry-collector:0.47.0` | 4317, 4318, 8889, 13133 | Telemetry pipeline |
| jaeger-all-in-one | `jaegertracing/all-in-one:1.37` | 16686, 14268, 14250 | Distributed tracing |
| prometheus | `prom/prometheus:v2.37.0` | 9090 | Metrics storage |
| loki | `grafana/loki:latest` | 3100 | Log aggregation |
| grafana | `grafana/grafana:11.0.0` | 8085 → 3000 | Dashboards |

**Why Grafana 11.0.0 instead of 7.5.16:**
- The existing multirole compose uses 7.5.16 (old)
- Grafana 11 has native Prometheus, Jaeger, and Loki datasource support
- Better heatmap panel support for latency dashboards
- Improved pie chart and bar chart visualizations
- Security patches

---

## Environment Variables

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENDPOINT` | `http://localhost:4317` | OTel Collector gRPC endpoint |
| `LOKI_URL` | (none) | Loki push endpoint. If unset, logs only go to stdout |
| `LOKI_BATCH_INTERVAL` | `5.0` | Seconds between Loki batch flushes |
| `APP_NAME` | `contract-review` | Application name for Loki labels |
| `ENVIRONMENT` | `development` | Environment label for Loki |
| `LOG_LEVEL` | `INFO` | Structlog log level |
| `WORKER_METRICS_PORT` | `9001` | Prometheus metrics port for worker |
| `API_METRICS_PORT` | `9002` | Prometheus metrics port for API |

### LLM Cost (Configurable, No Hardcoding)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL_NAME` | `deepseek/deepseek-v4-flash` | Model identifier for metrics labels |
| `LLM_INPUT_PRICE_PER_1K_TOKENS` | `0.00014` | Cost per 1K input tokens in USD |
| `LLM_OUTPUT_PRICE_PER_1K_TOKENS` | `0.00028` | Cost per 1K output tokens in USD |

**To change models or pricing:** Update the env vars. No code changes needed.

---

## Running the Stack

### 1. Start Observability Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

### 2. Start the Worker

```bash
cd app/ai_contract_review
pip install -r requirements.txt
python worker.py
```

Worker logs go to stdout (JSON) and to Loki (if `LOKI_URL` is set).
Metrics available at `http://localhost:9001/metrics`.

### 3. Start the API

```bash
cd app/client_app
pip install -r requirements.txt
uvicorn main:app --reload --port 5000
```

API logs go to stdout (JSON) and to Loki.
Metrics available at `http://localhost:9002/metrics`.

### 4. Access Dashboards

| Dashboard | URL |
|-----------|-----|
| Grafana | http://localhost:8085 |
| Jaeger | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Temporal UI | http://localhost:8080 |

### 5. Verify Everything Works

```bash
# Health check
curl http://localhost:5000/health

# Check metrics endpoint
curl http://localhost:5001/metrics  # worker
curl http://localhost:5002/metrics  # api

# Check Loki is receiving logs
curl "http://localhost:3100/loki/api/v1/query?query={app=%22contract-review%22}" | head -20

# Check Prometheus targets
curl http://localhost:9090/api/v1/targets | python -m json.tool | grep "health"
```
