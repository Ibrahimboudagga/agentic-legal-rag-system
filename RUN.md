# Running the AI Contract Intelligence Platform

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | https://python.org |
| Docker Desktop | Latest | https://docker.com/products/docker-desktop |
| pip | Latest | Comes with Python |

---

## Step 1: Start Infrastructure

Open a terminal in the project root:

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

Wait for all containers to be healthy (about 30-60 seconds):

```bash
docker compose -f docker-compose-observability.yml ps
```

Expected output — all services should show `Up` or `running`:

| Container | Port | Status |
|-----------|------|--------|
| temporal-postgresql | 5432 | Up (healthy) |
| temporal | 7233 | Up (healthy) |
| temporal-ui | 8080 | Up |
| temporal-create-namespace | — | Exited (0) |
| otel-collector | 4317, 8889 | Up |
| jaeger-all-in-one | 16686 | Up |
| prometheus | 9090 | Up |
| loki | 3100 | Up |
| grafana | 8085 | Up |

Verify each service:

```bash
# Temporal
curl http://localhost:7233    # should return gRPC response (binary, expected)

# OTel Collector health
curl http://localhost:13133   # should return "200 OK"

# Prometheus
curl http://localhost:9090/-/healthy   # should return "Prometheus Server is Healthy."

# Loki
curl http://localhost:3100/ready   # should return "ready"

# Jaeger
curl http://localhost:16686/   # should return HTML page

# Grafana
curl http://localhost:8085/api/health   # should return {"database":"ok"}
```

---

## Step 2: Install Python Dependencies

Open **three separate terminals** (one for each service):

**Terminal 1 — Worker:**

```bash
cd app/ai_contract_review
pip install -r requirements.txt
```

**Terminal 2 — API:**

```bash
cd app/client_app
pip install -r requirements.txt
```

---

## Step 3: Set Up Environment Variables

Create or verify `.env` files exist with these values:

**`app/ai_contract_review/.env`:**

```env
# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue

# S3 Storage
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-west-2
AWS_S3_ENDPOINT_URL=https://s3.us-west-2.idrivee2.com
S3_BUCKET=temporal
TEMP_DIR=/tmp/pdf-pipeline

# LLM
OPENROUTER_API_KEY=your-openrouter-key
LLM_MODEL_NAME=deepseek/deepseek-v4-flash
LLM_INPUT_PRICE_PER_1K_TOKENS=0.00014
LLM_OUTPUT_PRICE_PER_1K_TOKENS=0.00028

# Observability
OTEL_ENDPOINT=http://localhost:4317
LOKI_URL=http://localhost:3100
APP_NAME=contract-review
ENVIRONMENT=development
LOG_LEVEL=INFO
WORKER_METRICS_PORT=9001
```

**`app/client_app/.env`:**

```env
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue
S3_BUCKET=temporal

# Observability
OTEL_ENDPOINT=http://localhost:4317
LOKI_URL=http://localhost:3100
APP_NAME=contract-review
ENVIRONMENT=development
LOG_LEVEL=INFO
API_METRICS_PORT=9002
```

---

## Step 4: Start the Worker

**Terminal 1:**

```bash
cd app/ai_contract_review
python worker.py
```

Expected output:

```
{"event":"metrics_server_started","level":"info","port":9001,...}
{"event":"connecting_to_temporal","level":"info","host":"localhost:7233",...}
{"event":"worker_started","level":"info","task_queue":"contract-review-queue",...}
```

Verify metrics are being exposed:

```bash
curl http://localhost:9001/metrics
```

You should see lines like:

```
# HELP contract_review_workflow_started_total Total workflows started
# TYPE contract_review_workflow_started_total counter
```

---

## Step 5: Start the API Server

**Terminal 2:**

```bash
cd app/client_app
uvicorn main:app --reload --port 5000
```

Expected output:

```
{"event":"api_metrics_server_started","level":"info","port":9002,...}
INFO:     Uvicorn running on http://127.0.0.1:5000
```

Verify the API is running:

```bash
curl http://localhost:5000/health
```

Response:

```json
{"status":"ok"}
```

Verify API metrics:

```bash
curl http://localhost:5002/metrics
```

---

## Step 6: Upload Test PDFs to S3

If your test PDFs are not already in S3, upload them:

```bash
# Using AWS CLI or your S3 client
aws s3 cp app/ai_contract_review/samples/vendor-service-agreement.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app/ai_contract_review/samples/nda-innovate-consultpro.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app/ai_contract_review/samples/software-license-globalsoft.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
```

---

## Step 7: Start a Contract Review

```bash
curl -X POST http://localhost:5000/contract-review/start \
  -H "Content-Type: application/json" \
  -d '{
    "s3_paths": [
      "s3://temporal/vendor-service-agreement.pdf",
      "s3://temporal/nda-innovate-consultpro.pdf",
      "s3://temporal/software-license-globalsoft.pdf"
    ],
    "max_revesion": 2
  }'
```

Response:

```json
{"workflow_id":"contract-review-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}
```

**Save the workflow_id** — you'll need it for the next steps.

---

## Step 8: Monitor the Workflow

**Check status:**

```bash
curl http://localhost:5000/contract-review/{workflow_id}/status
```

Status transitions:

```
extracting → synthesizing → human_in_loop → completed
                ↓ (if revision requested)
             revising → human_in_loop → ...
```

**Get the full report (when status is `human_in_loop` or `completed`):**

```bash
curl http://localhost:5000/contract-review/{workflow_id}/report
```

---

## Step 9: Human-in-the-Loop Review

**Assign a reviewer (signal):**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/post_reviewer \
  -H "Content-Type: application/json" \
  -d '{"name": "john.doe"}'
```

**Option A — Approve the report:**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/approve
```

**Option B — Request a revision:**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/revise \
  -H "Content-Type: application/json" \
  -d '{"feedback": "Add more detail about liability clauses and indemnification terms."}'
```

After approval or final revision, the workflow completes.

---

## Step 10: Access Grafana Dashboards

Open in your browser:

```
http://localhost:8085
```

No login required (anonymous admin access is enabled).

### Navigate to Dashboards

1. Click the **hamburger menu** (top-left) → **Dashboards**
2. Click **Browse**
3. Select the **Contract Review** folder
4. You'll see all 6 dashboards:

| Dashboard | What It Shows |
|-----------|--------------|
| **Workflow Health** | Workflow start/complete/fail rates, success ratio, duration percentiles |
| **LLM Usage & Cost** | LLM request rates, latency, token consumption, estimated USD cost |
| **Worker Performance** | Activity durations, success ratios, documents processed, worker slots |
| **Latency** | End-to-end latency heatmap, PDF extraction, LLM, API, queue wait times |
| **Failures** | Failure rates by type/workflow, retry effectiveness, error distribution |
| **Human Review** | Approval/revision rates, wait times, decision distribution, auto-timeouts |

### Dashboard Details

**Workflow Health:**
- Top-left: Active workflows stat
- Row 1: Start rate, completion rate, failure rate (time series)
- Row 1: Success ratio gauge (green > 95%, yellow > 90%, red < 90%)
- Row 1: Duration P50/P95/P99
- Row 2: Temporal SDK native metrics

**LLM Usage & Cost:**
- Top-left: Cost per hour stat, Total cost stat
- Row 1: Request rate, P50/P95/P99 latency
- Row 2: Token input vs output, cost by operation, token efficiency ratio

**Worker Performance:**
- Top-left: Active activities count
- Row 1: Activity duration percentiles, activity rate, failure rate
- Row 2: Success ratio, documents processed, worker slots, Temporal E2E latency

**Latency:**
- Full-width heatmap of end-to-end workflow latency
- Row 2: PDF extraction, LLM call, API endpoint, task queue wait times

**Failures:**
- Row 1: Overall failure rate, 24h total, time since last failure
- Row 2: Failures by error type, workflow type, activity type
- Row 3: Retry effectiveness gauge, error distribution pie chart

**Human Review:**
- Row 1: Active reviews waiting, total started, approval rate, revision rate
- Row 2: Wait time P50/P95/P99
- Row 3: Decisions over time (stacked), auto-timeout rate, avg revisions

---

## Step 11: Access Other Observability UIs

| Service | URL | What It Shows |
|---------|-----|---------------|
| **Temporal UI** | http://localhost:8080 | Workflow executions, history, signals, queries |
| **Jaeger** | http://localhost:16686 | Distributed traces — select "contract-review-worker" service |
| **Prometheus** | http://localhost:9090 | Raw metrics, PromQL queries, alerting rules |
| **Loki** | http://localhost:3100 | Log aggregation (query via Grafana Explore) |

### Querying Logs in Grafana

1. Go to **Grafana** → **Explore** (compass icon, top-left)
2. Select **Loki** datasource
3. Enter a LogQL query:

```logql
# All contract review logs
{app="contract-review"}

# Only errors
{app="contract-review"} | json | level="error"

# Logs for a specific workflow
{app="contract-review"} | json | workflow_id="<your-workflow-id>"

# LLM calls only
{app="contract-review"} | json | activity_type="call_llm"

# Human review events
{app="contract-review"} | json | event=~"human_review.*"
```

### Querying Traces in Jaeger

1. Go to **Jaeger** → http://localhost:16686
2. Select **contract-review-worker** from the Service dropdown
3. Click **Find Traces**
4. Click on any trace to see the full span tree:

```
ContractReviewerWorkflow (parent)
├── pdfsummaryworkflow (child 1)
│   ├── RunActivity: extract_pdf
│   └── RunActivity: call_llm
├── pdfsummaryworkflow (child 2)
│   ├── RunActivity: extract_pdf
│   └── RunActivity: call_llm
├── pdfsummaryworkflow (child 3)
│   ├── RunActivity: extract_pdf
│   └── RunActivity: call_llm
└── RunActivity: call_llm (synthesis)
```

### Querying Metrics in Prometheus

Go to http://localhost:9090 → **Graph** tab, try these PromQL queries:

```promql
# Workflow success rate
sum(rate(contract_review_workflow_completed_total[5m])) / (sum(rate(contract_review_workflow_completed_total[5m])) + sum(rate(contract_review_workflow_failed_total[5m])))

# LLM cost per hour
sum(rate(contract_review_llm_cost_dollars[1h])) * 3600

# P95 LLM latency
histogram_quantile(0.95, sum(rate(contract_review_llm_request_duration_seconds_bucket[5m])) by (le))

# Active workflows
contract_review_active_workflows

# Token consumption rate
sum(rate(contract_review_llm_tokens_input_total[5m])) + sum(rate(contract_review_llm_tokens_output_total[5m]))
```

---

## Quick Reference: All Ports

| Port | Service | Access |
|------|---------|--------|
| 5000 | FastAPI | `http://localhost:5000` |
| 7233 | Temporal Server | gRPC (used by workers) |
| 8080 | Temporal UI | `http://localhost:8080` |
| 8085 | Grafana | `http://localhost:8085` |
| 9001 | Worker Metrics | `http://localhost:9001/metrics` |
| 9002 | API Metrics | `http://localhost:9002/metrics` |
| 9090 | Prometheus | `http://localhost:9090` |
| 16686 | Jaeger UI | `http://localhost:16686` |
| 3100 | Loki | `http://localhost:3100` |
| 4317 | OTel Collector | gRPC (used by app) |
| 8889 | OTel Prometheus | Scraped by Prometheus |

---

## Stopping Everything

**Stop application services:**

```bash
# Stop worker (Ctrl+C in Terminal 1)
# Stop API (Ctrl+C in Terminal 2)
```

**Stop infrastructure:**

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml down
```

**To also remove volumes (reset all data):**

```bash
docker compose -f docker-compose-observability.yml down -v
```
