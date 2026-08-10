# Agentic Legal RAG System

A production-grade agentic RAG platform for legal contract intelligence with strict separation: deterministic infrastructure, LangGraph agentic reasoning, and centralized LLM inference via OpenRouter.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Infrastructure Setup](#infrastructure-setup)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Layer C: LLM Inference                       │
│              shared/llm_client.py  (OpenRouter only)                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                        Layer B: Agentic Reasoning                   │
│  planner → retrieval → rerank → evidence → validate → analysis      │
│  → comparison → synthesis → END                                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                  Layer A: Deterministic Infrastructure              │
│  PostgreSQL+pgvector │ Ingestion │ Retrieval │ Reranker │ Evidence │
└─────────────────────────────────────────────────────────────────────┘
```

**Three-layer separation:**
- **Layer A** — Deterministic infrastructure (NO LLM): Temporal, PostgreSQL+pgvector, FTS, S3, PDF extraction, chunking, embedding, reranking (cross-encoder), metadata filtering, Pydantic, observability.
- **Layer B** — Agentic reasoning (LangGraph): planner, tool selection, retrieval sufficiency decisions, evidence sufficiency, analysis selection, synthesis.
- **Layer C** — LLM inference: ALL calls through centralized `LLMClient` → OpenRouter only. No direct model provider calls from agents.

---

## Project Structure

```
agentic-legal-rag-system/
├── app/
│   ├── shared/                          # Shared infrastructure
│   │   ├── config.py                    # Frozen dataclasses for all config
│   │   ├── database.py                  # Async SQLAlchemy ORM (Document, Chunk)
│   │   ├── s3.py                        # S3 download/upload/content-hash
│   │   ├── llm_client.py                # Centralized LLMClient → OpenRouter
│   │   └── observability/               # Prometheus, OTel, structlog, Loki
│   │
│   ├── ingestion/                       # Ingestion pipeline
│   │   ├── chunker.py                   # Markdown-aware paragraph-boundary chunker
│   │   ├── embedder.py                  # Local sentence-transformers
│   │   └── pipeline.py                  # Download → Extract → Chunk → Embed → Store
│   │
│   ├── retrieval/                       # Retrieval layer
│   │   ├── vector_store.py              # pgvector ANN + FTS search
│   │   └── hybrid_search.py             # RRF merge of results
│   │
│   ├── agents/                          # Agentic pipeline
│   │   ├── state.py                     # AgentState TypedDict
│   │   ├── graph.py                     # LangGraph graph wiring
│   │   ├── infrastructure_nodes.py      # Deterministic retrieval/rerank/evidence
│   │   ├── planner.py                   # Query decomposition (LLM)
│   │   ├── analysis_agent.py            # Legal analysis (LLM)
│   │   ├── comparison_agent.py          # Cross-contract (LLM)
│   │   ├── synthesis_node.py            # Final report (LLM)
│   │   ├── retrieval_tools.py           # ANN + FTS + Metadata tools
│   │   ├── retrieval_agent.py           # Deterministic retrieval
│   │   ├── reranker.py                  # Cross-encoder reranker
│   │   ├── evidence_store.py            # Evidence accumulator
│   │   ├── evidence_validator.py        # Heuristic validation
│   │   ├── activities.py                # Temporal activities
│   │   ├── review_workflow.py           # Agent review workflow
│   │   └── ingest_workflow.py           # Ingest workflow
│   │
│   ├── client_app/                      # FastAPI HTTP server
│   │   ├── main.py
│   │   └── requirements.txt
│   │
│   ├── ai_contract_review/              # Original contract review
│   │   ├── worker.py
│   │   ├── parent_worker.py
│   │   ├── child_worker.py
│   │   ├── activities.py
│   │   └── requirements.txt
│   │
│   ├── pdf_extraction_01/               # Standalone PDF pipeline
│   └── pdf_extraction_01_temporal/      # Temporal PDF pipeline
│
├── samples-server/compose/              # Docker Compose configs
├── ARCHITECTURE.md
├── OBSERVABILITY.md
├── RUN.md
└── README.md
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| Docker Desktop | Latest | Temporal server, PostgreSQL, pgvector, observability |
| pip | Latest | Python package management |

**PostgreSQL extensions required:** `vector` (pgvector), `unaccent`, `pg_trgm`.

---

## Infrastructure Setup

### Start All Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

This starts:
- **PostgreSQL + pgvector** on port `5432`
- **Temporal Server** on port `7233`
- **Temporal UI** on port `8080`
- **OTel Collector** on ports `4317`, `8889`
- **Jaeger** on port `16686`
- **Prometheus** on port `9090`
- **Loki** on port `3100`
- **Grafana** on port `8085`

### Initialize Database Extensions

```bash
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Verify Infrastructure

```bash
docker compose -f docker-compose-observability.yml ps
```

---

## Environment Variables

### `app/client_app/.env`

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

### `app/ai_contract_review/.env`

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

---

## Running the Application

### 1. Start Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-observability.yml up -d
```

### 2. Initialize Database

```bash
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Install Dependencies

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

### 4. Start the Worker

```bash
cd app/ai_contract_review
python worker.py
```

### 5. Start the API

```bash
cd app/client_app
uvicorn main:app --reload --port 5000
```

### 6. Verify

```bash
curl http://localhost:5000/health
# {"status":"ok"}
```

---

## API Endpoints

### Ingestion

```
POST /ingest
{
  "s3_path": "s3://temporal/contract.pdf",
  "batch_size": 2,
  "max_chunk_tokens": 512
}
```

### Agentic RAG Review

```
POST /agent-review/start
{
  "query": "What are the termination clauses and liability caps?",
  "s3_paths": ["s3://temporal/contract1.pdf", "s3://temporal/contract2.pdf"],
  "top_k": 5
}
```

```
GET /agent-review/{workflow_id}/status
GET /agent-review/{workflow_id}/report
```

### Contract Review (Legacy)

```
POST /contract-review/start
GET /contract-review/{workflow_id}/status
GET /contract-review/{workflow_id}/report
POST /contract-review/{workflow_id}/post_reviewer
POST /contract-review/{workflow_id}/revise
POST /contract-review/{workflow_id}/approve
```

### PDF Extraction

```
POST /process_pdf/execute
POST /process_pdf/start
GET /workflow/status/{workflow_id}
```

---

## Testing

### Ingest a Document

```bash
curl -X POST http://localhost:5000/ingest \
  -H "Content-Type: application/json" \
  -d '{"s3_path": "s3://temporal/vendor-service-agreement.pdf"}'
```

### Run Agentic Review

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

### Check Metrics

```bash
curl http://localhost:9001/metrics  # worker
curl http://localhost:9002/metrics  # api
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `pgvector extension not found` | Run `CREATE EXTENSION IF NOT EXISTS vector;` in PostgreSQL |
| `Embedding dimension mismatch` | Ensure `EMBEDDING_DIM=384` matches the model |
| Worker not picking up tasks | Verify worker is running and Temporal is on `localhost:7233` |
| S3 connection errors | Check AWS credentials and endpoint URL in `.env` |
| LLM errors | Verify `OPENROUTER_API_KEY` is valid |
| Docker containers not starting | `docker compose down` then `docker compose up -d` |

---

## License

Internal project — not licensed for distribution.
