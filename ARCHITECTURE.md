# Agentic Legal RAG System — Architecture & Technology Reference

> A production-grade, AI-powered contract intelligence platform that automates PDF extraction, multi-document legal analysis, and human-in-the-loop review through durable workflow orchestration.

---

## Table of Contents

- [Project Overview](#project-overview)
- [High-Level Architecture](#high-level-architecture)
- [Module Breakdown](#module-breakdown)
- [Technology Stack](#technology-stack)
  - [Core Orchestration — Temporal](#1-core-orchestration--temporal)
  - [API Layer — FastAPI](#2-api-layer--fastapi)
  - [PDF Processing — PyMuPDF / pymupdf4llm](#3-pdf-processing--pymupdf--pymupdf4llm)
  - [AI / LLM Layer — OpenRouter + OpenAI SDK](#4-ai--llm-layer--openrouter--openai-sdk)
  - [Object Storage — AWS S3 / iDrive E2](#5-object-storage--aws-s3--idrive-e2)
  - [Observability — Prometheus, OpenTelemetry, Loki, Jaeger, Grafana](#6-observability--prometheus-opentelemetry-loki-jaeger-grafana)
  - [Structured Logging — structlog](#7-structured-logging--structlog)
  - [JSON Repair — json-repair](#8-json-repair--json-repair)
  - [Infrastructure — Docker Compose + PostgreSQL](#9-infrastructure--docker-compose--postgresql)
  - [Configuration — python-dotenv](#10-configuration--python-dotenv)
  - [Validation — Pydantic](#11-validation--pydantic)
- [Workflow Architecture Deep Dive](#workflow-architecture-deep-dive)
  - [PDF Extraction Pipeline](#pdf-extraction-pipeline)
  - [Contract Review Workflow (Parent-Child)](#contract-review-workflow-parentchild)
  - [Human-in-the-Loop Design](#human-in-the-loop-design)
- [Observability Architecture](#observability-architecture)
- [Data Flow Diagram](#data-flow-diagram)
- [API Endpoint Reference](#api-endpoint-reference)
- [Environment Variables](#environment-variables)
- [Design Decisions & Rationale](#design-decisions--rationale)

---

## Project Overview

The **Agentic Legal RAG System** is a back-end platform designed for legal teams that need to review and risk-assess multiple contracts simultaneously. The core idea is:

1. **Ingest** — PDFs are stored in S3 object storage.
2. **Extract** — Each PDF is downloaded and converted into clean Markdown text.
3. **Analyze** — An LLM reads each contract, generates a structured summary and key risk list.
4. **Synthesize** — A second LLM call aggregates all individual summaries into a cross-contract consolidated risk report.
5. **Review** — A human reviewer inspects the report, optionally requests AI-powered revisions, and ultimately approves.

All steps are orchestrated as **durable, fault-tolerant workflows** using **Temporal**, meaning any step can fail and retry without losing progress.

---

## High-Level Architecture

```
+-------------------------------------------------------------------------+
|                          Client Layer                                   |
|                                                                         |
|          FastAPI  (port 5000)  --  REST API + Prometheus /metrics       |
+---------------------------+---------------------------------------------+
                            |  Temporal gRPC (port 7233)
                            v
+-------------------------------------------------------------------------+
|                     Temporal Server  (port 7233)                        |
|  +------------------------+   +--------------------------------------+   |
|  |   pdf-pipeline-queue   |   |      contract-review-queue           |   |
|  +----------+-------------+   +-------------+------------------------+   |
|             |                               |                            |
+-------------+-------------------------------+----------------------------+
              |                               |
              v                               v
+---------------------+     +--------------------------------------------+
|  PDF Worker         |     |  Contract Review Worker                    |
|  pdfpipelineworkflow|     |  +-------------------------------------+   |
|  - download_from_s3 |     |  |  ContractReviewerWorkflow (Parent)   |   |
|  - extract_to_md    |     |  |    Fan-out to child workflows        |   |
|  - upload_to_s3     |     |  |    +-- pdfsummaryworkflow (child 1)  |   |
+---------------------+     |  |    +-- pdfsummaryworkflow (child 2)  |   |
              |              |  |    +-- pdfsummaryworkflow (child N)  |   |
              v              |  |  Synthesis LLM call                  |   |
+---------------------+     |  |  Human-in-the-loop wait              |   |
|  S3 Object Storage  |     |  +-------------------------------------+   |
|  (iDrive E2 / AWS)  |<----+  Activities: extract_pdf, call_llm         |
+---------------------+     +---------------------+----------------------+
                                                   |
                                                   v
                                        +------------------+
                                        |  OpenRouter API  |
                                        |  (deepseek model)|
                                        +------------------+
```

---

## Module Breakdown

```
agentic-legal-rag-system/
|
+-- app/
|   +-- client_app/                   # REST API gateway
|   |   +-- main.py                   # FastAPI app, all HTTP endpoints, Temporal client
|   |   +-- requirements.txt
|   |
|   +-- pdf_extraction_01/            # Standalone (non-Temporal) PDF pipeline
|   |   +-- process_pdf.py            # CLI script: S3 download -> Markdown -> S3 upload
|   |
|   +-- pdf_extraction_01_temporal/   # Temporal-orchestrated PDF pipeline
|   |   +-- workflow_process_pdf.py   # Workflow definition (3-step sequential)
|   |   +-- activities.py             # Temporal activities (download, extract, upload)
|   |   +-- worker.py                 # Worker entrypoint (registers workflow + activities)
|   |   +-- helper.py                 # Dataclasses, S3 helpers
|   |
|   +-- ai_contract_review/           # Core AI contract review system
|   |   +-- parent_worker.py          # ContractReviewerWorkflow: orchestrator, HITL logic
|   |   +-- child_worker.py           # pdfsummaryworkflow: per-PDF extraction + LLM summary
|   |   +-- activities.py             # extract_pdf + call_llm Temporal activities
|   |   +-- prompts.py                # LLM prompt templates (summary, synthesis, revision)
|   |   +-- worker.py                 # Worker entrypoint (registers all workflows + activities)
|   |
|   +-- shared/
|       +-- observability/
|           +-- logging.py            # structlog config + Loki handler + context vars
|           +-- metrics.py            # Prometheus registry + 20 custom metrics
|           +-- middleware.py         # FastAPI ObservabilityMiddleware
|           +-- tracing.py            # OpenTelemetry setup + Temporal TracingInterceptor
|
+-- samples-server/compose/           # Docker Compose configurations for Temporal server
|   +-- docker-compose-postgres.yml   # Primary: PostgreSQL + Temporal + UI
|   +-- docker-compose-observability.yml  # Prometheus, Grafana, Jaeger, Loki, OTel Collector
|
+-- services/
    +-- temporal.service              # systemd unit for Linux production deployments
```

---

## Technology Stack

### 1. Core Orchestration — Temporal

| | |
|---|---|
| **Package** | `temporalio >= 1.29.0` |
| **Role** | Durable workflow orchestration engine |

**What it does in this project:**
- Manages the full lifecycle of PDF extraction and contract review workflows
- Provides automatic retries, timeouts, and heartbeat monitoring on every activity
- Enables **child workflow fan-out** — the parent workflow spawns one `pdfsummaryworkflow` per PDF in parallel, collects all results, then proceeds
- Powers the **human-in-the-loop** mechanism through three advanced Temporal primitives:
  - **Signals** (`assign_reviewer`) — fire-and-forget external events injected into a running workflow
  - **Updates** (`submit_decision`) — synchronous RPC into a running workflow with validation and response
  - **Queries** (`query_status`, `query_fullreport`) — real-time read of internal workflow state without mutating it
- Maintains workflow state durably in **PostgreSQL**, so if a worker crashes mid-execution, the workflow resumes exactly where it left off after restart

**Why Temporal instead of a simpler queue (Celery, RQ)?**
Long-lived legal review processes span hours or days (the HITL timeout is 3 days). Celery tasks lose all state on worker restart and cannot natively support signals, updates, or queries into running jobs. Temporal's event-sourced execution model guarantees exactly-once semantics and full replay capability with zero extra code.

---

### 2. API Layer — FastAPI

| | |
|---|---|
| **Package** | `fastapi == 0.115.12`, `uvicorn == 0.34.3` |
| **Role** | Async HTTP server, request gateway to Temporal |

**What it does in this project:**
- Exposes the REST API consumed by legal teams or front-end clients
- Acts as the **Temporal client** — translates HTTP requests into `client.start_workflow()` / `client.execute_workflow()` / `handle.signal()` / `handle.execute_update()` calls
- Serves a `/metrics` endpoint scraped by Prometheus for API-level telemetry
- Uses `pydantic.BaseModel` for automatic request/response validation and serialisation
- Runs the `ObservabilityMiddleware` on every request to inject `request_id`, timing, and trace context

**Why FastAPI?**
- Native `async/await` support matches Temporal's async Python SDK perfectly — no thread-pool overhead
- Auto-generated OpenAPI docs at `/docs` are useful for API exploration during development
- Pydantic v2 integration provides zero-boilerplate validation

---

### 3. PDF Processing — PyMuPDF / pymupdf4llm

| | |
|---|---|
| **Packages** | `pymupdf == 1.27.2.3`, `pymupdf4llm == 1.27.2.3` |
| **Role** | PDF parsing and LLM-optimised Markdown extraction |

**What it does in this project:**
- `fitz.open()` (PyMuPDF) opens the downloaded PDF and reports total page count
- `pymupdf4llm.to_markdown()` converts each page batch to clean Markdown, preserving tables, headings, and paragraph structure in a format that LLMs understand much better than raw text dumps
- Processing is done in **page batches** (default `batch_size=2`) so that Temporal heartbeat signals can be sent between batches, preventing the activity from being timed out during large document processing
- The resulting Markdown is passed directly to the LLM prompt

**Why pymupdf4llm over alternatives (pdfplumber, PDFMiner)?**
pymupdf4llm is purpose-built for feeding LLMs: it preserves document structure (headers, bullet lists, tables) as Markdown rather than producing a flat stream of characters, which dramatically improves LLM comprehension and extraction quality.

---

### 4. AI / LLM Layer — OpenRouter + OpenAI SDK

| | |
|---|---|
| **Package** | `openai == 2.43.0` |
| **External Service** | OpenRouter (`https://openrouter.ai/api/v1`) |
| **Default Model** | `deepseek/deepseek-v4-flash` |
| **Role** | Legal analysis, risk synthesis, and report revision |

**What it does in this project:**
The `call_llm` Temporal activity wraps the OpenAI SDK pointed at OpenRouter. Three distinct prompt templates are used:

| Prompt | Template | Output |
|--------|----------|--------|
| `_SUMMARY_PROMPT` | Per-contract analysis | `{summary, key_risks}` JSON |
| `_SYNTHESIS_PROMPT` | Cross-contract risk report | `{overall_risk_level, top_cross_contract_risks, recommended_actions}` JSON |
| `_REVISION_PROMPT` | Rewrite report with reviewer feedback | Same schema as synthesis |

All prompts explicitly instruct the model to return **raw JSON only** (no markdown fences), keeping downstream parsing deterministic.

Token usage (`prompt_tokens`, `completion_tokens`) is captured and fed into Prometheus counters for cost tracking.

**Why OpenRouter instead of calling OpenAI directly?**
OpenRouter is a unified gateway that provides access to dozens of models (DeepSeek, Claude, GPT-4, Mistral) through a single API key and a single `base_url` swap. This makes it trivial to switch or A/B-test models by changing a single environment variable (`LLM_MODEL_NAME`) without changing any code.

---

### 5. Object Storage — AWS S3 / iDrive E2

| | |
|---|---|
| **Package** | `boto3 == 1.43.32` |
| **Role** | Persistent storage for PDFs and extracted Markdown |

**What it does in this project:**
- Source PDFs uploaded by users are stored in the S3 bucket
- Workers download PDFs to a local temp directory (`TEMP_DIR`), process them, and the resulting Markdown is uploaded back
- All S3 paths are passed through workflows as `s3://bucket/key` URI strings
- The endpoint URL is configurable (`AWS_S3_ENDPOINT_URL`) so the system works with **iDrive E2** (the default), **MinIO** (local dev), or **AWS S3** proper — no code change needed

**Why S3-compatible object storage?**
Temporal workers are stateless and may run on different machines. Sharing files through S3 is the correct cloud-native approach: no shared filesystem, no NFS mounts, and built-in durability with replication.

---

### 6. Observability — Prometheus, OpenTelemetry, Loki, Jaeger, Grafana

| | |
|---|---|
| **Packages** | `prometheus-client >= 0.21.0`, `opentelemetry-api/sdk >= 1.29.0`, `opentelemetry-exporter-otlp-proto-grpc >= 1.29.0`, `python-logging-loki >= 0.3.1` |
| **Infrastructure** | OTel Collector, Jaeger, Prometheus, Loki, Grafana |
| **Role** | Full-stack observability: metrics, traces, logs |

This project implements the **three pillars of observability** as a production-grade shared module in `app/shared/observability/`.

#### Metrics (`metrics.py`) — Prometheus

20 custom metrics with the `contract_review_` prefix, organised into five groups:

| Group | Metrics |
|-------|---------|
| **Workflow** | `workflow_started_total`, `workflow_completed_total`, `workflow_failed_total`, `workflow_duration_seconds` |
| **Activity** | `activity_duration_seconds`, `activity_completed_total`, `activity_failed_total` |
| **LLM** | `llm_requests_total`, `llm_request_duration_seconds`, `llm_tokens_input_total`, `llm_tokens_output_total`, `llm_cost_dollars` |
| **Document** | `documents_processed_total`, `pdf_extraction_duration_seconds` |
| **Human Review** | `human_review_wait_seconds`, `human_review_started/approved/revised/timeout_total` |
| **Workers** | `active_workflows` (Gauge), `active_activities` (Gauge) |

Both the FastAPI server (`:9002`) and the Temporal worker (`:9001`) expose a dedicated Prometheus scrape endpoint.

#### Distributed Tracing (`tracing.py`) — OpenTelemetry + Jaeger

- A `TracingInterceptor` wraps every Temporal workflow and activity execution, automatically creating parent/child spans
- Spans are exported via **OTLP gRPC** to the OTel Collector (`:4317`), which forwards them to **Jaeger**
- The `TracerProvider` is configured with the service name so traces are clearly attributed in Jaeger UI

#### Log Aggregation (`logging.py`) — structlog + Grafana Loki

- All logs are structured JSON via **structlog**, with correlation IDs (`trace_id`, `workflow_id`, `run_id`, `activity_type`, `request_id`, `task_queue`) injected into every log line via Python `contextvars`
- A `LokiBatchQueueHandler` ships logs directly to **Grafana Loki** via HTTP push — no sidecar needed
- This allows log lines to be correlated with traces in Grafana (click a trace -> see all logs for that workflow execution)

#### Dashboards — Grafana

6 pre-provisioned dashboards covering:
- Workflow Health
- LLM Usage & Cost
- Worker Performance
- Latency Distributions
- Failure Analysis
- Human Review Tracking

**Why this observability stack?**
Legal automation is a regulated domain. When a workflow fails or a decision is made, you need an audit trail. The combination of structured logs (who, what, when), distributed traces (what called what, how long), and metrics (system health at a glance) provides the complete picture needed for debugging, SLA management, and compliance.

---

### 7. Structured Logging — structlog

| | |
|---|---|
| **Package** | `structlog >= 24.1.0` |
| **Role** | Machine-readable, contextual JSON log output |

Every log line automatically includes:
- `timestamp` (ISO 8601)
- `log_level`
- `trace_id`, `workflow_id`, `run_id`, `activity_type`, `request_id`, `task_queue` — all injected automatically via Python `contextvars`

This means you can filter logs in Loki/Grafana to show only log lines belonging to a specific workflow execution with a single label query.

---

### 8. JSON Repair — json-repair

| | |
|---|---|
| **Package** | `json-repair == 0.61.0` |
| **Role** | Robust parsing of LLM-generated JSON |

**The problem:** LLMs sometimes return malformed JSON — trailing commas, unescaped characters, truncated output, or markdown fences despite instructions to the contrary.

**The solution:** `json_repair.loads()` is a drop-in replacement for `json.loads()` that attempts to fix common JSON errors before parsing. This prevents the entire contract review workflow from failing simply because the LLM added an extra comma. A fallback `isinstance(report, dict)` check provides a final safety net.

---

### 9. Infrastructure — Docker Compose + PostgreSQL

| | |
|---|---|
| **Technology** | Docker Compose, PostgreSQL |
| **Role** | Local and production deployment of Temporal server |

The `samples-server/compose/` directory contains multiple Docker Compose configurations:

| File | Purpose |
|------|---------|
| `docker-compose-postgres.yml` | **Primary** — Temporal Server + PostgreSQL + Temporal UI |
| `docker-compose-observability.yml` | Full observability stack: OTel Collector, Prometheus, Grafana, Jaeger, Loki |
| `docker-compose-multirole.yaml` | Multi-node Temporal cluster (production-scale) |
| `docker-compose-mysql.yml` / `docker-compose-cass-es.yml` | Alternative backends |

**Why PostgreSQL for Temporal?**
Temporal requires a persistent store for workflow event histories. PostgreSQL offers the best balance of operational simplicity, ACID guarantees, and tooling support for development environments. For large-scale production, Cassandra + Elasticsearch can be used instead.

---

### 10. Configuration — python-dotenv

| | |
|---|---|
| **Package** | `python-dotenv == 1.2.2` |
| **Role** | Per-module `.env` file loading |

Each sub-application (`client_app`, `pdf_extraction_01_temporal`, `ai_contract_review`) maintains its own `.env` file with its specific configuration. This enables each module to be deployed independently with different settings. `load_dotenv()` is called at the top of every entrypoint.

---

### 11. Validation — Pydantic

| | |
|---|---|
| **Package** | Bundled with FastAPI |
| **Role** | API request/response schema validation |

All FastAPI request and response bodies (`ExtractPDFRequest`, `startreviewrequest`, `requestsignal`, `requestrevise`) are Pydantic `BaseModel` subclasses, providing:
- Automatic type coercion and validation
- Clear error messages on bad input (HTTP 422)
- Auto-generated OpenAPI schema

Temporal activity inputs and workflow inputs use Python `@dataclass`, which integrates cleanly with Temporal's serialization layer.

---

## Workflow Architecture Deep Dive

### PDF Extraction Pipeline

A simple sequential 3-step Temporal workflow:

```
[S3 PDF path]
     |
     v
download_from_s3   (timeout: 1 min, retry: 5 attempts)
     |
     v
extract_to_markdown  (timeout: 1 min, retry: 5 attempts)
     |  pymupdf4llm.to_markdown()
     v
upload_markdown_to_s3  (timeout: 1 min, retry: 5 attempts)
     |
     v
[s3://bucket/document.md]
```

### Contract Review Workflow (Parent-Child)

```
ContractReviewerWorkflow.run(s3_paths=[A, B, C], max_revision=2)
|
+-- PHASE 1: Fan-out (asyncio.gather)
|   +-- execute_child_workflow(pdfsummaryworkflow, s3=A) --> extract_pdf + call_llm(SUMMARY_PROMPT)
|   +-- execute_child_workflow(pdfsummaryworkflow, s3=B) --> extract_pdf + call_llm(SUMMARY_PROMPT)
|   +-- execute_child_workflow(pdfsummaryworkflow, s3=C) --> extract_pdf + call_llm(SUMMARY_PROMPT)
|           All run in parallel. Failures are isolated.
|
+-- PHASE 2: Synthesis
|   +-- execute_activity(call_llm, SYNTHESIS_PROMPT(summaries=[A, B, C]))
|           -> {overall_risk_level, top_cross_contract_risks, recommended_actions}
|
+-- PHASE 3: Human-in-the-Loop (up to max_revision + 1 iterations)
|   +-- wait_condition(review_decision is not None, timeout=3 days)
|   |       [external API calls inject decisions via Temporal Update]
|   |
|   +-- if decision == "approved"  -> break
|   +-- if decision == "revise"   -> execute_activity(call_llm, REVISION_PROMPT(report, feedback))
|                                    -> update self.report -> loop
|
+-- PHASE 4: Complete
    +-- return ContractReviewerWorkflowoutput(report, sources, approved_by)
```

### Human-in-the-Loop Design

The HITL mechanism uses two distinct Temporal primitives:

| Primitive | Endpoint | Effect |
|-----------|----------|--------|
| **Signal** `assign_reviewer` | `POST /contract-review/{id}/post_reviewer` | Writes `approved_by` name asynchronously; no response payload |
| **Update** `submit_decision` | `POST /contract-review/{id}/revise` or `/approve` | Synchronous RPC with validator — the Update handler validates the decision, sets `review_decision`, and returns a confirmation string to the caller |

The `submit_decision` **validator** (`validate_decision`) runs _before_ the handler and rejects invalid inputs (`ApplicationError`) without mutating any state — a key Temporal safety feature.

A `wait_condition` with a **3-day timeout** suspends the workflow durably with zero CPU usage until a decision arrives. If no decision comes in 3 days, the workflow auto-completes.

---

## Observability Architecture

```
+----------------------------------------------------------------------+
|                        Application Layer                             |
|   FastAPI (:9002/metrics)          Temporal Worker (:9001/metrics)   |
|   ObservabilityMiddleware           OTel TracingInterceptor           |
|   structlog -> stdout + Loki        structlog -> stdout + Loki        |
+----------+-------------------------------------------+---------------+
           | OTLP gRPC :4317                            | Prometheus scrape
           v                                            v
+-------------------------+          +-----------------------------------+
|   OTel Collector        |          |   Prometheus (:9090)             |
|   traces -> Jaeger      |          |   Scrapes: :9001, :9002, :8889   |
|   metrics -> :8889      |          +------------------+----------------+
+-----------+-------------+                             |
            |                                           |
            v                                           v
+---------------------+              +-----------------------------------+
|   Jaeger (:16686)   |              |   Grafana (:8085)                |
|   Trace explorer    |<-------------| Datasources: Prometheus,         |
+---------------------+              |   Jaeger, Loki                   |
                                     |   6 pre-built dashboards         |
                      Loki (:3100)-->|                                  |
                      Log aggregator +-----------------------------------+
```

---

## Data Flow Diagram

```
User / Client
    |
    |  HTTP POST /contract-review/start
    v
FastAPI (client_app/main.py)
    |  client.start_workflow("ContractReviewerWorkflow", ...)
    v
Temporal Server (PostgreSQL backend)
    |  Dispatches tasks to contract-review-queue
    v
Temporal Worker (ai_contract_review/worker.py)
    |
    +-- ContractReviewerWorkflow.run()
    |       |
    |       +-- [for each PDF] execute_child_workflow(pdfsummaryworkflow)
    |       |       |
    |       |       +-- extract_pdf activity
    |       |       |       +-- boto3: S3.download_file(pdf) -> /tmp/
    |       |       |       +-- pymupdf4llm.to_markdown(pdf) -> markdown_text
    |       |       |
    |       |       +-- call_llm activity (SUMMARY_PROMPT)
    |       |               +-- OpenRouter API -> DeepSeek -> {summary, key_risks}
    |       |
    |       +-- call_llm activity (SYNTHESIS_PROMPT)
    |       |       +-- OpenRouter API -> DeepSeek -> {risk_level, risks, actions}
    |       |
    |       +-- wait_condition (human decision via API)
    |               |
    |     +---------+----------+
    |     |                    |
    |  approve              revise
    |     |                    |
    |  complete           call_llm (REVISION_PROMPT)
    |                          |
    |                     loop back
    |
    +-- return final report
```

---

## API Endpoint Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics scrape |
| `POST` | `/process_pdf/execute` | Start PDF extraction and wait for result |
| `POST` | `/process_pdf/start` | Start PDF extraction asynchronously |
| `GET` | `/workflow/status/{id}` | Get workflow status and result |
| `POST` | `/contract-review/start` | Start multi-contract review workflow |
| `GET` | `/contract-review/{id}/status` | Poll workflow state (RUNNING query) |
| `GET` | `/contract-review/{id}/report` | Get full AI-generated report |
| `POST` | `/contract-review/{id}/post_reviewer` | Assign reviewer name (Signal) |
| `POST` | `/contract-review/{id}/revise` | Submit revision feedback (Update) |
| `POST` | `/contract-review/{id}/approve` | Approve the report (Update) |

---

## Environment Variables

### `app/client_app/.env`

| Variable | Description |
|----------|-------------|
| `TEMPORAL_HOST` | Temporal server address (e.g. `localhost:7233`) |
| `TEMPORAL_NAMESPACE` | Temporal namespace (e.g. `default`) |
| `TEMPORAL_PDF_PROCESS_TASK_QUEUE` | Task queue name for PDF pipeline |
| `TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE` | Task queue name for contract review |
| `API_METRICS_PORT` | Port for Prometheus scrape (default `9002`) |
| `LOKI_URL` | Optional: Loki endpoint for log shipping |

### `app/ai_contract_review/.env`

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter (LLM gateway) |
| `LLM_MODEL_NAME` | Model to use (default `deepseek/deepseek-v4-flash`) |
| `LLM_INPUT_PRICE_PER_1K_TOKENS` | For cost tracking in Prometheus |
| `LLM_OUTPUT_PRICE_PER_1K_TOKENS` | For cost tracking in Prometheus |
| `AWS_ACCESS_KEY_ID` | S3 credentials |
| `AWS_SECRET_ACCESS_KEY` | S3 credentials |
| `AWS_REGION` | S3 region |
| `AWS_S3_ENDPOINT_URL` | S3 endpoint (iDrive E2, MinIO, or AWS) |
| `S3_BUCKET` | Default S3 bucket name |
| `TEMP_DIR` | Local temp directory for PDF downloads |
| `TEMPORAL_HOST` | Temporal server address |
| `TEMPORAL_NAMESPACE` | Temporal namespace |
| `TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE` | Task queue name |
| `WORKER_METRICS_PORT` | Port for worker Prometheus scrape (default `9001`) |
| `OTEL_ENDPOINT` | OpenTelemetry Collector endpoint (default `http://localhost:4317`) |
| `LOKI_URL` | Loki endpoint for log shipping |
| `LOG_LEVEL` | Logging level (`INFO`, `DEBUG`, etc.) |

---

## Design Decisions & Rationale

### Why Temporal for orchestration?
Legal review workflows are inherently long-running (hours to days) and stateful. Temporal provides durable execution, automatic retries, and built-in primitives (signals, updates, queries) that map directly to the HITL use case. Building this on top of a traditional queue (Celery, RQ) would require significant custom state management, persistence, and retry logic.

### Why the Parent-Child workflow pattern?
Each PDF is independent — processing one should not block or fail the others. The fan-out pattern using `asyncio.gather` with `execute_child_workflow` allows N contracts to be processed fully in parallel. `ParentClosePolicy.ABANDON` ensures child workflows complete even if the parent is interrupted, preventing orphaned work.

### Why OpenRouter instead of a single LLM provider?
OpenRouter abstracts the underlying model provider. The model name is an environment variable, so switching from DeepSeek to Claude or GPT-4 requires no code change. This is especially important in a legal domain where model performance needs to be evaluated and swapped.

### Why separate activities for `extract_pdf` and `call_llm`?
Temporal activities are the unit of retryability. Separating PDF extraction from LLM calls means each can have its own retry policy and timeout. PDF extraction is typically slow but deterministic; LLM calls are fast but rate-limited. This separation also enables independent observability (separate Prometheus metrics per activity type).

### Why `json-repair` instead of `json.loads`?
LLMs are instructed to return raw JSON, but they are not reliable in practice — especially under edge cases like very long contracts or ambiguous prompts. `json-repair` is a production safety net that increases system resilience without requiring prompt re-engineering.

### Why structlog over the standard `logging` module?
Structured JSON logs are machine-readable and easily queryable in Loki/Elasticsearch. The `contextvars`-based correlation ID injection means every log line automatically carries `workflow_id`, `trace_id`, etc., without requiring them to be passed explicitly through every function call.

### Why a shared `observability/` module?
Both the FastAPI app and the Temporal worker need logging, metrics, and tracing. Centralising the implementation prevents duplication and guarantees consistent metric naming, label cardinality, and log format across all components. It also makes adding a new service (e.g., a notification worker) straightforward.

---

*Generated on 2026-08-09 — Agentic Legal RAG System v2.0.0*
