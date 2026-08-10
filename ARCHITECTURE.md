# Agentic Legal RAG System — Architecture & Technology Reference

> A production-grade, agentic RAG platform for legal contract intelligence with strict separation: deterministic infrastructure, LangGraph agentic reasoning, and centralized LLM inference.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Three-Layer Architecture](#three-layer-architecture)
- [Module Breakdown](#module-breakdown)
- [Technology Stack](#technology-stack)
- [LangGraph Agentic Pipeline](#langgraph-agentic-pipeline)
- [Ingestion Pipeline](#ingestion-pipeline)
- [Retrieval Layer](#retrieval-layer)
- [Observability Architecture](#observability-architecture)
- [Data Flow Diagrams](#data-flow-diagrams)
- [API Endpoint Reference](#api-endpoint-reference)
- [Environment Variables](#environment-variables)
- [Design Decisions & Rationale](#design-decisions--rationale)

---

## Project Overview

The **Agentic Legal RAG System** is a back-end platform for legal teams that need to review and risk-assess contracts using retrieval-augmented generation. The core idea:

1. **Ingest** — PDFs are extracted, chunked, embedded, and stored in PostgreSQL + pgvector.
2. **Retrieve** — Hybrid search (pgvector semantic + FTS) finds relevant chunks with metadata filtering.
3. **Rerank** — Cross-encoder model re-ranks results locally (no LLM).
4. **Analyze** — LangGraph agent nodes decompose queries, retrieve evidence, validate it, perform legal analysis, compare contracts, and synthesize final reports.
5. **Review** — Human-in-the-loop via Temporal signals/updates/queries.

All steps are orchestrated as **durable, fault-tolerant workflows** using **Temporal**.

---

## Three-Layer Architecture

The system enforces strict separation of concerns across three layers:

### Layer A — Deterministic Infrastructure (NO LLM)

Pure code with zero LLM dependency. Fully testable, deterministic, reproducible.

| Component | File | Role |
|-----------|------|------|
| PostgreSQL + pgvector | `shared/database.py` | Async ORM, connection pooling, vector storage |
| Chunking | `ingestion/chunker.py` | Markdown-aware paragraph-boundary chunker |
| Embedding | `ingestion/embedder.py` | Local `all-MiniLM-L6-v2` (384-dim, free) |
| Ingestion Pipeline | `ingestion/pipeline.py` | Download → Extract → Chunk → Embed → Store |
| Vector Store | `retrieval/vector_store.py` | pgvector ANN + FTS search |
| Hybrid Search | `retrieval/hybrid_search.py` | RRF merge of semantic + keyword results |
| Reranker | `agents/reranker.py` | `ms-marco-MiniLM-L-6-v2` cross-encoder (local) |
| Evidence Validator | `agents/evidence_validator.py` | Heuristic coverage/diversity/negation checks |
| Evidence Store | `agents/evidence_store.py` | Deduplicating evidence accumulator |
| Observability | `shared/observability/` | Prometheus, OTel, structlog, Loki |
| Configuration | `shared/config.py` | Frozen dataclasses for all env vars |
| S3 Utilities | `shared/s3.py` | Download, upload, content-hash, file type |
| Temporal Workflows | `agents/review_workflow.py`, `ingest_workflow.py` | Durable orchestration |

### Layer B — Agentic Reasoning (LangGraph)

LLM-powered reasoning nodes. Each node calls the centralized `LLMClient` abstraction.

| Node | File | Role |
|------|------|------|
| Planner | `agents/planner.py` | Decompose query into sub-tasks |
| Analysis | `agents/analysis_agent.py` | Legal analysis with evidence grounding |
| Comparison | `agents/comparison_agent.py` | Cross-contract risk analysis |
| Synthesis | `agents/synthesis_node.py` | Final evidence-grounded report |

### Layer C — LLM Inference (Centralized)

All LLM calls go through a single abstraction. **No direct model provider calls from agents.**

| Component | File | Role |
|-----------|------|------|
| LLMClient | `shared/llm_client.py` | OpenRouter gateway, retry, token counting, cost tracking, JSON repair |

---

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Layer C: LLM Inference                       │
│                                                                     │
│              shared/llm_client.py  (OpenRouter only)                │
│              retry, token counting, cost tracking, json_repair      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ get_llm_client()
┌───────────────────────────────┼─────────────────────────────────────┐
│                        Layer B: Agentic Reasoning                   │
│                                                                     │
│  planner → retrieval → rerank → evidence_build → evidence_validate  │
│       ↓                                                      ↓      │
│  analysis ←──────────────────────────────────────── (loop or pass)  │
│       ↓                                                              │
│  comparison (if multi-contract)                                     │
│       ↓                                                              │
│  synthesize → END                                                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                  Layer A: Deterministic Infrastructure              │
│                                                                     │
│  PostgreSQL+pgvector │ Ingestion │ Retrieval │ Reranker │ Evidence │
│  Chunker │ Embedder │ HybridSearch │ Database │ S3 │ Observability│
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Breakdown

```
agentic-legal-rag-system/
|
+-- app/
|   +-- shared/                          # Shared infrastructure (Layer A + C)
|   |   +-- config.py                    # Frozen dataclasses: AWS, Temporal, LLM, Database, AppConfig
|   |   +-- database.py                  # Async SQLAlchemy ORM (Document, Chunk with Vector(384))
|   |   +-- s3.py                        # S3 download/upload/content-hash/file-type
|   |   +-- llm_client.py                # Centralized LLMClient → OpenRouter (Layer C)
|   |   +-- observability/
|   |       +-- logging.py               # structlog + Loki + context vars
|   |       +-- metrics.py               # 30 custom Prometheus metrics
|   |       +-- middleware.py             # FastAPI ObservabilityMiddleware
|   |       +-- tracing.py               # OTel + Temporal TracingInterceptor
|   |
|   +-- ingestion/                       # Ingestion pipeline (Layer A)
|   |   +-- chunker.py                   # Markdown-aware paragraph-boundary chunker
|   |   +-- embedder.py                  # Local sentence-transformers all-MiniLM-L6-v2
|   |   +-- pipeline.py                  # Download → Extract → Chunk → Embed → Store
|   |
|   +-- retrieval/                       # Retrieval layer (Layer A)
|   |   +-- vector_store.py              # pgvector ANN + FTS search
|   |   +-- hybrid_search.py             # RRF merge of semantic + keyword results
|   |
|   +-- agents/                          # Agentic pipeline (Layer B)
|   |   +-- state.py                     # AgentState TypedDict with all dataclasses
|   |   +-- graph.py                     # LangGraph graph wiring + routing
|   |   +-- infrastructure_nodes.py      # Deterministic retrieval/rerank/evidence nodes
|   |   +-- planner.py                   # Query decomposition (LLM via LLMClient)
|   |   +-- analysis_agent.py            # Legal analysis (LLM via LLMClient)
|   |   +-- comparison_agent.py          # Cross-contract (LLM via LLMClient)
|   |   +-- synthesis_node.py            # Final report (LLM via LLMClient)
|   |   +-- retrieval_tools.py           # ANN + FTS + Metadata tools with RRF
|   |   +-- retrieval_agent.py           # Deterministic retrieval node
|   |   +-- reranker.py                  # Cross-encoder deterministic reranker
|   |   +-- evidence_store.py            # Deduplicating evidence accumulator
|   |   +-- evidence_validator.py        # Heuristic evidence validation
|   |   +-- activities.py                # Temporal activities for agent pipeline
|   |   +-- review_workflow.py           # Temporal HITL agent review workflow
|   |   +-- ingest_workflow.py           # Temporal ingestion workflow
|   |
|   +-- client_app/                      # FastAPI HTTP server
|   |   +-- main.py                      # All API endpoints + Temporal client
|   |   +-- requirements.txt
|   |
|   +-- ai_contract_review/              # Original contract review (existing)
|   |   +-- worker.py                    # Registers all workflows + activities
|   |   +-- parent_worker.py             # Parent workflow with HITL
|   |   +-- child_worker.py              # Per-PDF child workflow
|   |   +-- activities.py                # extract_pdf + call_llm
|   |   +-- prompts.py                   # LLM prompt templates
|   |   +-- requirements.txt
|   |
|   +-- pdf_extraction_01/               # Standalone PDF pipeline (no Temporal)
|   +-- pdf_extraction_01_temporal/      # Temporal-based PDF pipeline
|
+-- samples-server/compose/              # Docker Compose for Temporal + observability
```

---

## Technology Stack

### 1. Core Orchestration — Temporal

| | |
|---|---|
| **Package** | `temporalio >= 1.29.0` |
| **Role** | Durable workflow orchestration engine |

Manages ingestion and agentic review workflows with retries, timeouts, heartbeats, signals, updates, and queries. PostgreSQL-backed for durability across worker restarts.

### 2. API Layer — FastAPI

| | |
|---|---|
| **Package** | `fastapi == 0.115.12` |
| **Role** | Async HTTP server, Temporal client gateway |

Exposes REST API for ingestion, agent review, contract review, health, and metrics.

### 3. Database — PostgreSQL + pgvector

| | |
|---|---|
| **Packages** | `asyncpg`, `sqlalchemy[asyncio]`, `pgvector` |
| **Role** | Vector store for embeddings, document/chunk metadata |

Async SQLAlchemy ORM with `Document` and `Chunk` models. `Chunk.embedding` uses `Vector(384)` for `all-MiniLM-L6-v2`. Content-hash deduplication. FTS via `to_tsvector`/`ts_rank`.

### 4. Embeddings — sentence-transformers (Local)

| | |
|---|---|
| **Package** | `sentence-transformers >= 3.0.0` |
| **Model** | `all-MiniLM-L6-v2` (384-dim, free) |

Runs locally. No API calls. `lru_cache` singleton for efficiency.

### 5. Reranking — Cross-Encoder (Local)

| | |
|---|---|
| **Package** | `sentence-transformers >= 3.0.0` |
| **Model** | `ms-marco-MiniLM-L-6-v2` |

Deterministic cross-encoder reranking. No LLM involved. `lru_cache` singleton.

### 6. LLM Inference — OpenRouter (Centralized)

| | |
|---|---|
| **Package** | `openai == 2.43.0` |
| **Gateway** | OpenRouter (`https://openrouter.ai/api/v1`) |
| **Default Model** | `deepseek/deepseek-v4-flash` |

`LLMClient` wraps OpenRouter with retry, token counting, cost tracking, and `json_repair`. All agent reasoning nodes call `get_llm_client()` — no direct `OpenAI()` instantiation anywhere in agent code.

### 7. LangGraph — Agentic Reasoning

| | |
|------|---|
| **Packages** | `langgraph >= 0.2.0`, `langchain-core >= 0.3.0` |
| **Role** | Multi-step reasoning state machine |

State graph with deterministic routing: `planner → retrieval → rerank → evidence_build → evidence_validate → (loop or) analysis → (comparison) → synthesis`.

### 8. Observability — Prometheus, OTel, Loki, Jaeger, Grafana

| | |
|---|---|
| **Packages** | `prometheus-client`, `opentelemetry-*`, `python-logging-loki`, `structlog` |

30 custom metrics across workflow, activity, LLM, document, human review, RAG, and agent categories. Structured JSON logs with correlation IDs. Distributed tracing via OTel.

### 9. PDF Processing — PyMuPDF / pymupdf4llm

| | |
|---|---|
| **Packages** | `pymupdf == 1.27.2.3`, `pymupdf4llm == 1.27.2.3` |

PDF to Markdown extraction preserving document structure. Page-batched processing for heartbeat support.

### 10. JSON Repair

| | |
|---|---|
| **Package** | `json-repair == 0.61.0` |

Production safety net for malformed LLM JSON output.

---

## LangGraph Agentic Pipeline

```
Entry Point
    │
    ▼
┌──────────┐
│ PLANNER  │  LLM: decompose query into sub-tasks, decide comparison needed
└────┬─────┘
     │
     ▼
┌──────────┐
│RETRIEVAL │  Deterministic: pgvector ANN + FTS + metadata filtering
└────┬─────┘
     │
     ▼
┌──────────┐
│ RERANK   │  Deterministic: cross-encoder ms-marco-MiniLM-L-6-v2
└────┬─────┘
     │
     ▼
┌──────────────┐
│EVIDENCE BUILD│  Deterministic: accumulate evidence with citation IDs
└────┬─────────┘
     │
     ▼
┌──────────────┐
│EVIDENCE VALID│  Deterministic: heuristic checks (coverage, diversity, negation)
└────┬─────────┘
     │
     ├──── passed ──────────────────┐
     │                              ▼
     ├──── needs_retrieval ──► retrieval (loop, max 3)
     │
     ▼
┌──────────┐
│ ANALYSIS │  LLM: legal analysis on validated evidence
└────┬─────┘
     │
     ├──── comparison_needed ──► ┌────────────┐
     │                           │ COMPARISON │  LLM: cross-contract risk analysis
     │                           └─────┬──────┘
     │                                 │
     ▼                                 ▼
┌───────────┐
│ SYNTHESIS │  LLM: final evidence-grounded report with citations
└─────┬─────┘
      │
      ▼
     END
```

---

## Ingestion Pipeline

```
S3 PDF path
    │
    ▼
Download PDF (boto3 → temp_dir)
    │
    ▼
Extract Markdown (pymupdf4llm)
    │
    ▼
Content-hash dedup (SHA-256)
    │
    ▼
Chunk (markdown-aware, paragraph-boundary, ~512 tokens)
    │
    ▼
Embed (sentence-transformers all-MiniLM-L6-v2, 384-dim)
    │
    ▼
Store (PostgreSQL + pgvector: Document + Chunk records)
```

---

## Retrieval Layer

```
Query
    │
    ├──► pgvector ANN search (cosine similarity, top 20)
    │
    ├──► FTS search (ts_rank, top 20)
    │
    ├──► Metadata filtering (s3_path, page_number)
    │
    ▼
RRF Merge (k=60, deduplicated, top 20)
    │
    ▼
Cross-Encoder Rerank (ms-marco-MiniLM-L-6-v2, top 8)
    │
    ▼
Evidence Build (citation IDs, dedup)
    │
    ▼
Evidence Validate (heuristic checks)
    │
    ├──── passed ──► proceed to analysis
    └──── failed ──► retrieve again (max 3 attempts)
```

---

## Observability Architecture

```
+----------------------------------------------------------------------+
|                        Application Layer                             |
|                                                                      |
|  FastAPI (:5000)              Temporal Worker (:9001 metrics)        |
|  /metrics → :9002             /metrics → :9001                       |
|  ObservabilityMiddleware      OTel TracingInterceptor                 |
|  structlog → stdout + Loki    structlog → stdout + Loki              |
+----------+-------------------------------------------+---------------+
           │ OTLP gRPC :4317                            | Prometheus
           v                                            v
+-------------------------+          +-----------------------------------+
|   OTel Collector        |          |   Prometheus (:9090)             |
|   traces → Jaeger      |          |   Scrapes: :9001, :9002, :8889   |
|   metrics → :8889      |          +------------------+----------------+
+-----------+-------------+                             |
            |                                           v
            v                              +-----------------------------------+
+---------------------+                   |   Grafana (:8085)                |
|   Jaeger (:16686)   |                   |   7 dashboards                   |
+---------------------+                   |   Prometheus + Jaeger + Loki      |
                                          +-----------------------------------+
Log Flow: Python app → structlog JSON → LokiBatchQueueHandler → HTTP → Loki :3100
```

### Metrics Inventory (30 metrics)

| Category | Metrics |
|----------|---------|
| **Workflow** | `workflow_started_total`, `workflow_completed_total`, `workflow_failed_total`, `workflow_duration_seconds` |
| **Activity** | `activity_duration_seconds`, `activity_completed_total`, `activity_failed_total` |
| **LLM** | `llm_requests_total`, `llm_request_duration_seconds`, `llm_tokens_input_total`, `llm_tokens_output_total`, `llm_cost_dollars` |
| **Document** | `documents_processed_total`, `pdf_extraction_duration_seconds` |
| **Human Review** | `human_review_wait_seconds`, `human_review_started_total`, `human_review_approved_total`, `human_review_revised_total`, `human_review_timeout_total` |
| **Workers** | `active_workflows`, `active_activities` |
| **RAG** | `rag_documents_ingested_total`, `rag_chunks_created_total`, `rag_search_requests_total`, `rag_search_duration_seconds`, `rag_search_results_count` |
| **Agent** | `agent_analysis_requests_total`, `agent_analysis_duration_seconds`, `agent_critic_approvals_total`, `agent_critic_rejections_total`, `agent_citations_total` |

---

## Data Flow Diagrams

### Ingestion Flow

```
User → POST /ingest → FastAPI → Temporal.start(IngestDocumentWorkflow)
    → Activity: ingest_document_activity
        → S3 download → pymupdf4llm → chunker → embedder → store in pgvector
    → return {document_id, total_chunks}
```

### Agentic Review Flow

```
User → POST /agent-review/start → FastAPI → Temporal.start(AgentReviewWorkflow)
    → Activity: run_agent_graph_activity
        → LangGraph:
            planner (LLM) → retrieval (pgvector) → rerank (cross-encoder)
            → evidence_build → evidence_validate → analysis (LLM)
            → comparison (LLM, if multi-contract) → synthesis (LLM)
        → return {synthesis, analysis, comparison, evidence_count, citations}
    → HITL: wait for approve/revise via signals/updates
```

---

## API Endpoint Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |
| `POST` | `/process_pdf/execute` | PDF extraction (sync) |
| `POST` | `/process_pdf/start` | PDF extraction (async) |
| `GET` | `/workflow/status/{id}` | PDF pipeline status |
| `POST` | `/contract-review/start` | Start contract review (legacy) |
| `GET` | `/contract-review/{id}/status` | Contract review status |
| `GET` | `/contract-review/{id}/report` | Contract review report |
| `POST` | `/contract-review/{id}/post_reviewer` | Assign reviewer (Signal) |
| `POST` | `/contract-review/{id}/revise` | Request revision (Update) |
| `POST` | `/contract-review/{id}/approve` | Approve report (Update) |
| `POST` | `/ingest` | Ingest document into vector store |
| `POST` | `/agent-review/start` | Start agentic RAG review |
| `GET` | `/agent-review/{id}/status` | Agent review status |
| `GET` | `/agent-review/{id}/report` | Agent review report |

---

## Environment Variables

### `app/shared/config.py` — Centralized Configuration

All env vars are read through frozen dataclasses in `shared/config.py`.

**AWS:**
| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | (required) | S3 access key |
| `AWS_SECRET_ACCESS_KEY` | (required) | S3 secret key |
| `AWS_REGION` | (required) | S3 region |
| `AWS_S3_ENDPOINT_URL` | (required) | S3 endpoint (iDrive E2, MinIO, AWS) |
| `S3_BUCKET` | (required) | Default S3 bucket |

**Temporal:**
| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TEMPORAL_PDF_PROCESS_TASK_QUEUE` | `pdf-pipeline-queue` | PDF pipeline task queue |
| `TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE` | `contract-review-queue` | Contract review task queue |

**LLM (OpenRouter):**
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (required) | OpenRouter API key |
| `LLM_MODEL_NAME` | `deepseek/deepseek-v4-flash` | Model identifier |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `LLM_INPUT_PRICE_PER_1K_TOKENS` | `0.00014` | Cost per 1K input tokens |
| `LLM_OUTPUT_PRICE_PER_1K_TOKENS` | `0.00028` | Cost per 1K output tokens |
| `LLM_MAX_TOKENS` | `8000` | Max tokens per request |

**Database:**
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag` | Async database URL |
| `DATABASE_SYNC_URL` | `postgresql://postgres:postgres@localhost:5432/legal_rag` | Sync URL for init |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `EMBEDDING_DIM` | `384` | Embedding dimensions |

**App:**
| Variable | Default | Description |
|----------|---------|-------------|
| `TEMP_DIR` | `/tmp/pdf-pipeline` | Temp directory |
| `LOG_LEVEL` | `INFO` | Log level |
| `OTEL_ENDPOINT` | `http://localhost:4317` | OTel Collector endpoint |
| `LOKI_URL` | (none) | Loki endpoint (optional) |

---

## Design Decisions & Rationale

### Why strict three-layer separation?
Deterministic infrastructure (Layer A) must be fully testable without LLM calls. Agentic reasoning (Layer B) is the only place LLMs are used, making it easy to swap models or add caching. LLM inference (Layer C) is centralized for consistent retry, cost tracking, and model switching.

### Why OpenRouter as the only LLM gateway?
Single entry point for all LLM calls. Model switching via env var. No direct provider calls from agent code.

### Why local embeddings + reranking?
Zero cost, zero latency for embedding/reranking. No API dependency. `all-MiniLM-L6-v2` and `ms-marco-MiniLM-L-6-v2` are production-quality models that run on CPU.

### Why pgvector over dedicated vector DBs?
Single database for both metadata and vectors. No extra infrastructure. Content-hash deduplication. FTS via PostgreSQL `tsvector`. Battle-tested.

### Why LangGraph over raw agent loops?
Explicit state machine with typed state, deterministic routing, and checkpointing. No hidden control flow.

### Why Temporal for both ingestion and review?
Durable execution, automatic retries, heartbeat monitoring. Ingestion can fail mid-chunk and resume. Review can wait days for human input with zero CPU.

---

*Generated on 2026-08-10 — Agentic Legal RAG System v3.0.0*
