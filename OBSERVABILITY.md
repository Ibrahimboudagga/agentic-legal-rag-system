# Observability Implementation — Technical Documentation

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Metrics Reference](#metrics-reference)
- [Module Reference](#module-reference)
- [Correlation IDs](#correlation-ids)
- [Grafana Dashboards](#grafana-dashboards)
- [Infrastructure](#infrastructure)
- [Environment Variables](#environment-variables)
- [Running the Stack](#running-the-stack)

---

## Overview

Production-grade observability with three pillars — **logs**, **metrics**, and **traces** — with full correlation across all three.

| Pillar | Technology | Details |
|--------|-----------|---------|
| **Structured Logging** | structlog + python-logging-loki | JSON logs with correlation IDs, pushed to Loki |
| **Metrics** | prometheus-client | 30 custom metrics with `contract_review_` prefix |
| **Distributed Tracing** | OpenTelemetry + Temporal TracingInterceptor | End-to-end traces |
| **Dashboards** | Grafana | 7 pre-provisioned dashboards |
| **Log Aggregation** | Grafana Loki | Direct HTTP push from Python |
| **Trace Backend** | Jaeger | OTLP traces from OTel Collector |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Application Layer                           │
│                                                                     │
│  FastAPI (:5000)              Temporal Worker (:9001 metrics)       │
│  /metrics → :9002             /metrics → :9001                      │
│  ObservabilityMiddleware      OTel TracingInterceptor                │
│  structlog → stdout + Loki    structlog → stdout + Loki             │
└───────────┬───────────────────────────────────┬─────────────────────┘
            │ OTLP gRPC :4317                   │ Prometheus scrape
            v                                   v
┌─────────────────────┐     ┌───────────────────────────────────────┐
│   OTel Collector    │     │   Prometheus (:9090)                  │
│   traces → Jaeger   │     │   Scrapes: :9001, :9002, :8889        │
│   metrics → :8889   │     └──────────────┬────────────────────────┘
└──────────┬──────────┘                    │
           │                               v
           v                  ┌──────────────────────────────┐
┌──────────────┐              │   Grafana (:8085)            │
│   Jaeger     │              │   7 dashboards               │
│   :16686     │<─────────────│   Prometheus + Jaeger + Loki │
└──────────────┘              └──────────────────────────────┘
```

---

## Metrics Reference

### Workflow Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_workflow_started_total` | Counter | `workflow_type`, `task_queue` | Total workflows started |
| `contract_review_workflow_completed_total` | Counter | `workflow_type`, `task_queue` | Workflows completed |
| `contract_review_workflow_failed_total` | Counter | `workflow_type`, `task_queue`, `error_type` | Workflows failed |
| `contract_review_workflow_duration_seconds` | Histogram | `workflow_type` | End-to-end duration |

### Activity Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_activity_duration_seconds` | Histogram | `activity_type`, `task_queue` | Activity duration |
| `contract_review_activity_completed_total` | Counter | `activity_type`, `task_queue` | Activities completed |
| `contract_review_activity_failed_total` | Counter | `activity_type`, `task_queue`, `error_type` | Activities failed |

### LLM Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_llm_requests_total` | Counter | `model`, `operation` | LLM API requests |
| `contract_review_llm_request_duration_seconds` | Histogram | `model`, `operation` | LLM request duration |
| `contract_review_llm_tokens_input_total` | Counter | `model` | Input tokens consumed |
| `contract_review_llm_tokens_output_total` | Counter | `model` | Output tokens consumed |
| `contract_review_llm_cost_dollars` | Counter | `model` | Estimated cost (USD) |

### Document Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_documents_processed_total` | Counter | `status` | Documents processed |
| `contract_review_pdf_extraction_duration_seconds` | Histogram | — | PDF extraction duration |

### Human Review Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_human_review_wait_seconds` | Histogram | — | Time waiting for decision |
| `contract_review_human_review_started_total` | Counter | — | Reviews initiated |
| `contract_review_human_review_approved_total` | Counter | — | Reviews approved |
| `contract_review_human_review_revised_total` | Counter | — | Revisions requested |
| `contract_review_human_review_timeout_total` | Counter | — | Reviews timed out |

### Worker Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_active_workflows` | Gauge | `workflow_type` | Active workflows |
| `contract_review_active_activities` | Gauge | `activity_type` | Running activities |

### RAG Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_rag_documents_ingested_total` | Counter | `status` | Documents ingested |
| `contract_review_rag_chunks_created_total` | Counter | — | Chunks created |
| `contract_review_rag_search_requests_total` | Counter | `search_type` | Search requests |
| `contract_review_rag_search_duration_seconds` | Histogram | — | Search duration |
| `contract_review_rag_search_results_count` | Histogram | — | Results returned |

### Agent Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `contract_review_agent_analysis_requests_total` | Counter | `agent_type` | Agent requests |
| `contract_review_agent_analysis_duration_seconds` | Histogram | `agent_type` | Agent duration |
| `contract_review_agent_critic_approvals_total` | Counter | — | Critic approvals |
| `contract_review_agent_critic_rejections_total` | Counter | — | Critic rejections |
| `contract_review_agent_citations_total` | Counter | — | Citations used |

### Histogram Buckets

| Metric | Buckets | Rationale |
|--------|---------|-----------|
| `workflow_duration_seconds` | 1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600 | Workflows range from seconds to hours |
| `activity_duration_seconds` | 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600 | Activities up to 10 min |
| `llm_request_duration_seconds` | 0.5, 1, 2, 5, 10, 30, 60, 120 | LLM calls 1-60s |
| `rag_search_duration_seconds` | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0 | Search typically sub-second |
| `human_review_wait_seconds` | 60, 300, 600, 1800, 3600, 86400, 172800, 259200 | Minutes to 3 days |

---

## Module Reference

### `shared/observability/logging.py`

Structured JSON logging with correlation IDs and direct Loki push.

**Context vars:** `trace_id_var`, `workflow_id_var`, `run_id_var`, `activity_type_var`, `request_id_var`, `task_queue_var`.

**structlog pipeline:** `merge_contextvars → add_log_level → TimeStamper → StackInfoRenderer → format_exc_info → _add_correlation_ids → JSONRenderer`.

### `shared/observability/metrics.py`

Prometheus registry with 30 custom metrics. Helper `record_llm_call()` tracks tokens and cost.

### `shared/observability/tracing.py`

`setup_tracing(service_name)` → `TracingInterceptor` for Temporal.
`setup_temporal_runtime()` → Temporal `Runtime` with OTel metrics.

### `shared/observability/middleware.py`

FastAPI middleware: injects `request_id`, `trace_id`, logs request start/completion, adds response headers.

### `shared/llm_client.py`

Centralized `LLMClient` wrapping OpenRouter. Retry, token counting, cost tracking, JSON completion with `json_repair`. Singleton via `get_llm_client()`.

---

## Correlation IDs

Every log line includes:

```json
{
  "timestamp": "2026-08-10T12:00:00.000000Z",
  "level": "info",
  "event": "retrieval_completed",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "workflow_id": "agent-review-abc-123",
  "run_id": "def-456-ghi",
  "activity_type": "run_agent_graph",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_queue": "contract-review-queue"
}
```

| ID | Set By | Propagated Via |
|----|--------|---------------|
| `request_id` | `ObservabilityMiddleware` | `contextvars` |
| `trace_id` | OTel `TracingInterceptor` | OTel context → `contextvars` |
| `workflow_id` | `workflow.info()` | `contextvars` at workflow entry |
| `activity_type` | Activity function body | `activity_type_var.set()` |

---

## Grafana Dashboards

### Dashboard 1: Workflow Health

Active workflows, start/complete/fail rates, success ratio, duration percentiles.

### Dashboard 2: LLM Usage & Cost

Request rates, latency, token consumption, estimated USD cost, cost by operation.

### Dashboard 3: Worker Performance

Activity durations, success ratios, documents processed, worker slots.

### Dashboard 4: Latency

End-to-end heatmap, PDF extraction, LLM, API, queue wait times.

### Dashboard 5: Failures

Failure rates by type/workflow/activity, retry effectiveness, error distribution.

### Dashboard 6: Human Review

Approval/revision rates, wait times, decision distribution, auto-timeouts.

### Dashboard 7: RAG & Agent

Ingestion rates, search latency, chunk counts, agent analysis duration, critic approvals/rejections.

---

## Infrastructure

### `docker-compose-observability.yml`

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL + pgvector | 5432 | Vector store + Temporal persistence |
| Temporal Server | 7233 | Workflow engine |
| Temporal UI | 8080 | Workflow Web UI |
| OTel Collector | 4317, 8889 | Telemetry pipeline |
| Jaeger | 16686 | Distributed tracing |
| Prometheus | 9090 | Metrics storage |
| Loki | 3100 | Log aggregation |
| Grafana | 8085 | Dashboards |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENDPOINT` | `http://localhost:4317` | OTel Collector gRPC endpoint |
| `LOKI_URL` | (none) | Loki push endpoint |
| `LOKI_BATCH_INTERVAL` | `5.0` | Seconds between Loki flushes |
| `APP_NAME` | `contract-review` | Loki label |
| `ENVIRONMENT` | `development` | Loki label |
| `LOG_LEVEL` | `INFO` | Structlog level |
| `WORKER_METRICS_PORT` | `9001` | Worker Prometheus port |
| `API_METRICS_PORT` | `9002` | API Prometheus port |
| `LLM_MODEL_NAME` | `deepseek/deepseek-v4-flash` | Model for metrics labels |
| `LLM_INPUT_PRICE_PER_1K_TOKENS` | `0.00014` | Cost per 1K input tokens |
| `LLM_OUTPUT_PRICE_PER_1K_TOKENS` | `0.00028` | Cost per 1K output tokens |

---

## Running the Stack

### 1. Start Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

### 2. Initialize pgvector

```bash
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Start Worker

```bash
cd app/ai_contract_review
pip install -r requirements.txt
python worker.py
```

Metrics: `http://localhost:9001/metrics`

### 4. Start API

```bash
cd app/client_app
pip install -r requirements.txt
uvicorn main:app --reload --port 5000
```

Metrics: `http://localhost:9002/metrics`

### 5. Access Dashboards

| Dashboard | URL |
|-----------|-----|
| Grafana | http://localhost:8085 |
| Jaeger | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Temporal UI | http://localhost:8080 |

### 6. Verify

```bash
curl http://localhost:5000/health
curl http://localhost:9001/metrics | head -20
curl "http://localhost:3100/loki/api/v1/query?query={app=%22contract-review%22}" | head -20
```
