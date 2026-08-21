# How To Run The Agentic Legal RAG System

This file is the local operations guide for the project. It explains how to prepare infrastructure, configure environment variables, start the Temporal worker and FastAPI server, ingest contracts, run an agentic review, monitor the workflow, and stop everything cleanly.

For the architecture and technology rationale, see [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), [RAG.md](RAG.md), and [AGENTS.md](AGENTS.md).

## 1. What You Will Run

The local development stack has three layers:

```text
Application
  FastAPI API on port 5000
  Temporal worker on contract-review-queue
  Worker metrics on port 9001
  API metrics on port 9002

Infrastructure
  Temporal server on port 7233
  Temporal UI on port 8080
  PostgreSQL + pgvector on port 5432

Observability
  Prometheus on port 9090
  Grafana on port 8085
  Jaeger on port 16686
  Loki on port 3100
  OpenTelemetry Collector on port 4317
```

The API does not run the agent graph directly. It starts Temporal workflows. The worker executes Temporal workflows and activities. The agent graph runs inside a Temporal activity.

## 2. Prerequisites

Install these first:

| Tool | Required | Purpose |
|---|---:|---|
| Python | 3.11+ | Runs API, worker, tests, embeddings, reranker |
| Docker Desktop | Yes | Runs Temporal, PostgreSQL, observability stack |
| pip | Yes | Installs Python dependencies |
| AWS CLI | Optional but useful | Upload sample PDFs to S3-compatible storage |
| OpenRouter account/key | Yes for LLM calls | Centralized LLM gateway |
| S3-compatible bucket | Yes for ingestion | Stores contract PDFs |

The code is Python-first and does not require Ollama or a local LLM server.

## 3. Repository Root

Run commands from:

```powershell
cd "C:\Users\Bouda\OneDrive\Desktop\New folder\agentic-legal-rag-system"
```

On macOS/Linux, use the equivalent path to the cloned repository.

## 4. Create Environment Files

Start from the example file:

```powershell
Copy-Item .env.example app\ai_contract_review\.env
Copy-Item .env.example app\client_app\.env
```

Then edit both files.

### Worker Environment

File:

```text
app/ai_contract_review/.env
```

Recommended local development values:

```env
# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue

# S3-compatible storage
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-west-2
AWS_S3_ENDPOINT_URL=https://s3.us-west-2.idrivee2.com
S3_BUCKET=temporal
TEMP_DIR=/tmp/pdf-pipeline

# OpenRouter LLM gateway
OPENROUTER_API_KEY=your-openrouter-key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=deepseek/deepseek-v4-flash
LLM_MAX_TOKENS=8000
LLM_INPUT_PRICE_PER_1K_TOKENS=0.00014
LLM_OUTPUT_PRICE_PER_1K_TOKENS=0.00028

# Task-specific model routing
PLANNER_MODEL=deepseek/deepseek-v4-flash
QUERY_REWRITE_MODEL=deepseek/deepseek-v4-flash
VALIDATOR_MODEL=deepseek/deepseek-v4-flash
ANALYSIS_MODEL=deepseek/deepseek-v4-flash
SYNTHESIS_MODEL=deepseek/deepseek-v4-flash

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag
DATABASE_SYNC_URL=postgresql://postgres:postgres@localhost:5432/legal_rag
DB_POOL_SIZE=5
EMBEDDING_DIM=384

# RAG
EMBEDDING_MODEL=all-MiniLM-L6-v2
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
MAX_RETRIEVAL_ITERATIONS=3
TOP_K_RETRIEVAL=20
TOP_K_RERANK=8
HYBRID_SEMANTIC_WEIGHT=0.5
HYBRID_KEYWORD_WEIGHT=0.3
HYBRID_METADATA_WEIGHT=0.2
HYBRID_SIMILARITY_THRESHOLD=0.25

# Observability
OTEL_ENDPOINT=http://localhost:4317
LOKI_URL=http://localhost:3100
APP_NAME=contract-review
ENVIRONMENT=development
LOG_LEVEL=INFO
WORKER_METRICS_PORT=9001
```

### API Environment

File:

```text
app/client_app/.env
```

Recommended values:

```env
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue
S3_BUCKET=temporal

OTEL_ENDPOINT=http://localhost:4317
LOKI_URL=http://localhost:3100
APP_NAME=contract-review
ENVIRONMENT=development
LOG_LEVEL=INFO
API_METRICS_PORT=9002
```

The API does not need OpenRouter credentials unless it imports or executes code paths that instantiate the LLM client. The worker needs the full environment because it performs ingestion and agent review.

## 5. Install Python Dependencies

Use separate environments for worker and API. This mirrors the repository layout.

### Worker Dependencies

```powershell
cd app\ai_contract_review
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\..
```

The first run of embeddings/reranking may download local Sentence Transformers models. That can take a few minutes.

### API Dependencies

```powershell
cd app\client_app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\..
```

### Test Dependencies

If you want to run the tests, install pytest into the environment you will use:

```powershell
.\app\client_app\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

Some tests require heavier optional dependencies such as pgvector, SQLAlchemy, sentence-transformers, or a running database.

## 6. Start Infrastructure

The project includes Temporal sample compose files under `samples-server/compose`.

For the full stack with observability:

```powershell
cd samples-server\compose
docker compose -f docker-compose-observability.yml up -d
cd ..\..
```

Wait 30 to 60 seconds, then check status:

```powershell
cd samples-server\compose
docker compose -f docker-compose-observability.yml ps
cd ..\..
```

Expected services:

| Service | Port | Purpose |
|---|---:|---|
| PostgreSQL | 5432 | Temporal persistence and legal RAG database |
| Temporal | 7233 | Workflow server |
| Temporal UI | 8080 | Workflow inspection |
| OpenTelemetry Collector | 4317 | Trace/metric collection |
| Prometheus | 9090 | Metrics |
| Grafana | 8085 | Dashboards |
| Jaeger | 16686 | Traces |
| Loki | 3100 | Logs |

## 7. Initialize PostgreSQL Extensions

The RAG database needs pgvector and FTS-related extensions:

```powershell
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

The application also calls `init_db()` during ingestion and creates/updates the `documents` and `chunks` tables, metadata columns, FTS column, GIN index, and FTS trigger.

## 8. Upload Sample PDFs

The agentic ingestion endpoint expects S3 URIs. Upload the sample PDFs to your configured bucket:

```powershell
aws s3 cp app\ai_contract_review\samples\vendor-service-agreement.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app\ai_contract_review\samples\nda-innovate-consultpro.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
aws s3 cp app\ai_contract_review\samples\software-license-globalsoft.pdf s3://temporal/ --endpoint-url https://s3.us-west-2.idrivee2.com
```

Replace the endpoint URL and bucket name if you use AWS S3, MinIO, or another S3-compatible service.

## 9. Start The Temporal Worker

Open a terminal at the repository root:

```powershell
cd app\ai_contract_review
.\.venv\Scripts\python.exe worker.py
```

Expected log signals:

```json
{"event":"metrics_server_started","port":9001}
{"event":"worker_started","task_queue":"contract-review-queue"}
```

The worker registers:

- legacy contract review workflows
- child PDF summary workflow
- document ingestion workflow
- agentic review workflow
- extraction, LLM, ingestion, and agent graph activities

Keep this terminal running.

## 10. Start The FastAPI Server

Open a second terminal at the repository root:

```powershell
cd app\client_app
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 5000
```

Verify health:

```powershell
curl http://localhost:5000/health
```

Expected response:

```json
{"status":"ok"}
```

Interactive API docs are available at:

```text
http://localhost:5000/docs
```

## 11. Ingest Contracts

Ingest one contract:

```powershell
curl -X POST http://localhost:5000/ingest `
  -H "Content-Type: application/json" `
  -d "{\"s3_path\":\"s3://temporal/vendor-service-agreement.pdf\",\"batch_size\":2,\"max_chunk_tokens\":512}"
```

Expected response:

```json
{
  "workflow_id": "ingest-...",
  "status": "ingesting"
}
```

Check workflow state:

```powershell
curl http://localhost:5000/workflow/status/ingest-REPLACE_WITH_ID
```

You can also inspect the ingestion workflow in Temporal UI:

```text
http://localhost:8080
```

## 12. Run Agentic RAG Review

Start a review:

```powershell
curl -X POST http://localhost:5000/agent-review/start `
  -H "Content-Type: application/json" `
  -d "{
    \"query\":\"Which contracts allow unilateral termination with less than 30 days notice?\",
    \"s3_paths\":[
      \"s3://temporal/vendor-service-agreement.pdf\",
      \"s3://temporal/nda-innovate-consultpro.pdf\",
      \"s3://temporal/software-license-globalsoft.pdf\"
    ],
    \"top_k\":8
  }"
```

Expected response:

```json
{
  "workflow_id": "agent-review-..."
}
```

What happens internally:

```text
FastAPI starts AgentReviewWorkflow
-> workflow optionally auto-ingests documents
-> workflow executes run_agent_graph_activity
-> LangGraph planner creates objective/subqueries/capabilities
-> retrieval tools run vector search, FTS, metadata filtering
-> candidates are fused and reranked
-> evidence validator checks quality
-> weak evidence triggers query rewrite and another retrieval pass
-> analysis and comparison agents use validated evidence
-> synthesis produces final structured report
-> workflow enters human_in_loop status
```

## 13. Check Status And Report

Check status:

```powershell
curl http://localhost:5000/agent-review/agent-review-REPLACE_WITH_ID/status
```

Get report while workflow is running:

```powershell
curl http://localhost:5000/agent-review/agent-review-REPLACE_WITH_ID/report
```

The report includes:

- workflow status
- original query
- final report object
- citations
- evidence count
- evidence validation result
- review decision
- assigned reviewer

## 14. Human Review

The agentic workflow waits for a human decision after synthesis. Use the same update/signal names as the legacy review flow.

Assign a reviewer:

```powershell
curl -X POST http://localhost:5000/contract-review/agent-review-REPLACE_WITH_ID/post_reviewer `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"legal.reviewer\"}"
```

Approve:

```powershell
curl -X POST http://localhost:5000/contract-review/agent-review-REPLACE_WITH_ID/approve
```

Request revision:

```powershell
curl -X POST http://localhost:5000/contract-review/agent-review-REPLACE_WITH_ID/revise `
  -H "Content-Type: application/json" `
  -d "{\"feedback\":\"Add more detail about termination notice periods and cite each contract separately.\"}"
```

On revision, Temporal reruns the agent graph with reviewer feedback included in the query context.

## 15. Observability

### Service URLs

| Tool | URL |
|---|---|
| FastAPI | `http://localhost:5000` |
| FastAPI docs | `http://localhost:5000/docs` |
| API metrics | `http://localhost:9002/metrics` |
| Worker metrics | `http://localhost:9001/metrics` |
| Temporal UI | `http://localhost:8080` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:8085` |
| Jaeger | `http://localhost:16686` |
| Loki | `http://localhost:3100` |

### Useful Prometheus Queries

Workflow success rate:

```promql
sum(rate(contract_review_workflow_completed_total[5m])) /
(sum(rate(contract_review_workflow_completed_total[5m])) + sum(rate(contract_review_workflow_failed_total[5m])))
```

RAG search latency P95:

```promql
histogram_quantile(0.95, sum(rate(contract_review_rag_search_duration_seconds_bucket[5m])) by (le))
```

LLM cost by model:

```promql
sum(contract_review_llm_cost_dollars_total) by (model)
```

Evidence validation failures:

```promql
sum(rate(contract_review_evidence_validation_failures_total[5m])) by (issue_type)
```

Retrieval loop activity:

```promql
sum(rate(contract_review_retrieval_iterations_total[5m])) by (status)
```

### Useful Loki Queries

All application logs:

```logql
{app="contract-review"}
```

Errors:

```logql
{app="contract-review"} | json | level="error"
```

Single workflow:

```logql
{app="contract-review"} | json | workflow_id="agent-review-REPLACE_WITH_ID"
```

Agent graph activity logs:

```logql
{app="contract-review"} | json | activity_type="run_agent_graph"
```

## 16. Run Tests

Install test dependencies first:

```powershell
.\app\client_app\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

Run lightweight tests:

```powershell
.\app\client_app\.venv\Scripts\python.exe -m pytest tests\test_agent_schemas.py tests\test_evaluation.py -q
```

Run the full test suite:

```powershell
.\app\client_app\.venv\Scripts\python.exe -m pytest tests -q
```

Some tests may require optional dependencies or a running PostgreSQL/pgvector database. If a test imports sentence-transformers, the first run may download models.

## 17. Syntax And Import Checks

Quick syntax check:

```powershell
python -c "import compileall, re; ok=compileall.compile_dir('app', quiet=1, rx=re.compile(r'.*\\.venv.*')); ok=compileall.compile_dir('tests', quiet=1) and ok; raise SystemExit(0 if ok else 1)"
```

API import check:

```powershell
.\app\client_app\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app'); import client_app.main; print('api_import_ok')"
```

Worker activity import check with placeholder environment:

```powershell
$env:AWS_ACCESS_KEY_ID="x"
$env:AWS_SECRET_ACCESS_KEY="x"
$env:AWS_REGION="us-east-1"
$env:AWS_S3_ENDPOINT_URL="http://localhost"
$env:S3_BUCKET="test"
$env:OPENROUTER_API_KEY="x"
.\app\ai_contract_review\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app'); import ai_contract_review.activities; print('legacy_activities_import_ok')"
```

## 18. Common Problems

### `No module named pytest`

Install test dependencies:

```powershell
.\app\client_app\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

### `No module named sqlalchemy`, `pgvector`, or `sentence_transformers`

Install the worker requirements:

```powershell
.\app\ai_contract_review\.venv\Scripts\python.exe -m pip install -r app\ai_contract_review\requirements.txt
```

### `pgvector extension not found`

Run:

```powershell
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If that fails, the PostgreSQL image may not include pgvector.

### Worker does not pick up workflows

Check:

- worker terminal is still running
- `TEMPORAL_HOST=localhost:7233`
- API and worker use the same `TEMPORAL_NAMESPACE`
- API and worker use the same `TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE`

### S3 download fails

Check:

- credentials are valid
- bucket exists
- `AWS_S3_ENDPOINT_URL` is correct
- the object key in the `s3://bucket/key.pdf` URI exists

### OpenRouter call fails

Check:

- `OPENROUTER_API_KEY`
- `LLM_BASE_URL=https://openrouter.ai/api/v1`
- chosen model IDs are available in your OpenRouter account

### Agent review returns weak or empty evidence

Check:

- documents were ingested successfully
- database contains chunks
- `TOP_K_RETRIEVAL` is high enough
- `HYBRID_SIMILARITY_THRESHOLD` is not too strict
- queries include legal terms likely present in the contract

## 19. Stop Everything

Stop API and worker with `Ctrl+C` in their terminals.

Stop infrastructure:

```powershell
cd samples-server\compose
docker compose -f docker-compose-observability.yml down
cd ..\..
```

Stop and remove volumes:

```powershell
cd samples-server\compose
docker compose -f docker-compose-observability.yml down -v
cd ..\..
```

Removing volumes deletes local PostgreSQL and Temporal data.

## 20. Production Notes

Before production deployment:

- move secrets to a secret manager
- add authentication and authorization at the API layer
- use managed PostgreSQL with pgvector or a properly backed-up database
- configure TLS for Temporal and API traffic
- separate Temporal persistence from the RAG database if needed
- add Alembic migrations for schema changes
- pin dependency versions after validation
- run load tests for embedding and reranking throughput
- add an end-to-end evaluation runner
- review generated legal reports with qualified counsel
