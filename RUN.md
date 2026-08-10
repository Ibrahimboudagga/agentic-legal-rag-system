# Running the Agentic Legal RAG System

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | https://python.org |
| Docker Desktop | Latest | https://docker.com/products/docker-desktop |
| pip | Latest | Comes with Python |

---

## Step 1: Start Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

Wait for all containers to be healthy (30-60 seconds):

```bash
docker compose -f docker-compose-observability.yml ps
```

Expected — all services should show `Up` or `running`:

| Container | Port | Status |
|-----------|------|--------|
| temporal-postgresql | 5432 | Up (healthy) |
| temporal | 7233 | Up (healthy) |
| temporal-ui | 8080 | Up |
| otel-collector | 4317, 8889 | Up |
| jaeger-all-in-one | 16686 | Up |
| prometheus | 9090 | Up |
| loki | 3100 | Up |
| grafana | 8085 | Up |

---

## Step 2: Initialize pgvector Extension

```bash
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

---

## Step 3: Install Python Dependencies

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

**Note:** `sentence-transformers` will download the embedding model (~80MB) on first run.

---

## Step 4: Set Up Environment Variables

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

# LLM (OpenRouter)
OPENROUTER_API_KEY=your-openrouter-key
LLM_MODEL_NAME=deepseek/deepseek-v4-flash
LLM_INPUT_PRICE_PER_1K_TOKENS=0.00014
LLM_OUTPUT_PRICE_PER_1K_TOKENS=0.00028

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag
DATABASE_SYNC_URL=postgresql://postgres:postgres@localhost:5432/legal_rag
DB_POOL_SIZE=5
EMBEDDING_DIM=384

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

## Step 5: Start the Worker

**Terminal 1:**

```bash
cd app/ai_contract_review
python worker.py
```

Expected output:

```
{"event":"metrics_server_started","level":"info","port":9001,...}
{"event":"worker_started","level":"info","task_queue":"contract-review-queue",...}
```

---

## Step 6: Start the API Server

**Terminal 2:**

```bash
cd app/client_app
uvicorn main:app --reload --port 5000
```

Verify:

```bash
curl http://localhost:5000/health
# {"status":"ok"}
```

---

## Step 7: Upload Test PDFs to S3

```bash
aws s3 cp app/ai_contract_review/samples/vendor-service-agreement.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app/ai_contract_review/samples/nda-innovate-consultpro.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app/ai_contract_review/samples/software-license-globalsoft.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
```

---

## Step 8: Ingest Documents

Before running agent reviews, ingest documents into the vector store:

```bash
curl -X POST http://localhost:5000/ingest \
  -H "Content-Type: application/json" \
  -d '{"s3_path": "s3://temporal/vendor-service-agreement.pdf"}'
```

Wait for the workflow to complete, then ingest more documents as needed.

---

## Step 9: Run Agentic RAG Review

```bash
curl -X POST http://localhost:5000/agent-review/start \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the termination clauses and liability caps across these contracts?",
    "s3_paths": [
      "s3://temporal/vendor-service-agreement.pdf",
      "s3://temporal/nda-innovate-consultpro.pdf",
      "s3://temporal/software-license-globalsoft.pdf"
    ]
  }'
```

Response:

```json
{"workflow_id": "agent-review-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}
```

---

## Step 10: Monitor the Review

**Check status:**

```bash
curl http://localhost:5000/agent-review/{workflow_id}/status
```

**Get the report:**

```bash
curl http://localhost:5000/agent-review/{workflow_id}/report
```

---

## Step 11: Human-in-the-Loop

**Assign a reviewer:**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/post_reviewer \
  -H "Content-Type: application/json" \
  -d '{"name": "john.doe"}'
```

**Approve:**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/approve
```

**Or request revision:**

```bash
curl -X POST http://localhost:5000/contract-review/{workflow_id}/revise \
  -H "Content-Type: application/json" \
  -d '{"feedback": "Add more detail about liability clauses."}'
```

---

## Step 12: Access Dashboards

| Dashboard | URL |
|-----------|-----|
| Grafana | http://localhost:8085 |
| Jaeger | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Temporal UI | http://localhost:8080 |

### Querying Logs in Grafana

1. Grafana → Explore → Loki datasource
2. LogQL queries:

```logql
# All logs
{app="contract-review"}

# Errors only
{app="contract-review"} | json | level="error"

# Specific workflow
{app="contract-review"} | json | workflow_id="<id>"

# Agent graph events
{app="contract-review"} | json | activity_type="run_agent_graph"
```

### Querying Metrics in Prometheus

```promql
# Workflow success rate
sum(rate(contract_review_workflow_completed_total[5m])) / (sum(rate(contract_review_workflow_completed_total[5m])) + sum(rate(contract_review_workflow_failed_total[5m])))

# RAG search latency P95
histogram_quantile(0.95, sum(rate(contract_review_rag_search_duration_seconds_bucket[5m])) by (le))

# Agent analysis rate
sum(rate(contract_review_agent_analysis_requests_total[5m])) by (agent_type)
```

---

## All Ports

| Port | Service | Access |
|------|---------|--------|
| 5000 | FastAPI | `http://localhost:5000` |
| 5432 | PostgreSQL | `localhost:5432` |
| 7233 | Temporal Server | gRPC |
| 8080 | Temporal UI | `http://localhost:8080` |
| 8085 | Grafana | `http://localhost:8085` |
| 9001 | Worker Metrics | `http://localhost:9001/metrics` |
| 9002 | API Metrics | `http://localhost:9002/metrics` |
| 9090 | Prometheus | `http://localhost:9090` |
| 16686 | Jaeger UI | `http://localhost:16686` |
| 3100 | Loki | `http://localhost:3100` |
| 4317 | OTel Collector | gRPC |

---

## Stopping Everything

```bash
# Stop application
# Ctrl+C in Terminal 1 (worker) and Terminal 2 (API)

# Stop infrastructure
cd samples-server/compose
docker compose -f docker-compose-observability.yml down

# To also remove volumes
docker compose -f docker-compose-observability.yml down -v
```
