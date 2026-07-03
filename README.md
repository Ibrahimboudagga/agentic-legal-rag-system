# Agentic Legal Rag System 

A production-grade workflow orchestration system built with **Temporal** and **FastAPI** that automates PDF extraction, AI-powered contract analysis, and human-in-the-loop review processes.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Infrastructure Setup (Docker)](#infrastructure-setup-docker)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Workflow Details](#workflow-details)
- [Temporal Workers](#temporal-workers)
- [Testing](#testing)

---

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   FastAPI   │────▶│   Temporal   │────▶│  PDF Extraction │────▶│  S3 Storage  │
│  (Client)   │     │   Server     │     │    Worker       │     │  (iDrive E2) │
│  Port 5000  │     │  Port 7233   │     └─────────────────┘     └──────────────┘
└─────────────┘     └──────┬───────┘
                           │
                           ▼
                    ┌─────────────────┐     ┌──────────────┐
                    │  Contract Review│────▶│  OpenRouter   │
                    │    Worker       │     │  (LLM API)   │
                    │  (Parent+Child) │     └──────────────┘
                    └─────────────────┘
                           │
                           ▼
                    ┌─────────────────┐
                    │  Temporal UI    │
                    │  Port 8080      │
                    └─────────────────┘
```

**Flow:**
1. FastAPI receives HTTP requests and starts Temporal workflows
2. Temporal orchestrates worker execution with retries, timeouts, and visibility
3. PDF Worker downloads PDFs from S3, converts to Markdown, uploads back
4. Contract Review Worker uses AI (OpenRouter) to analyze contracts, synthesize reports
5. Human-in-the-loop: reviewer can request revisions via signals/updates
6. Temporal UI provides real-time visibility into all workflow executions

---

## Project Structure

```
temporalworkflow/
├── app/
│   ├── client_app/                    # FastAPI HTTP server
│   │   ├── main.py                    # API endpoints & workflow orchestration
│   │   ├── .env                       # Client configuration
│   │   └── requirements.txt
│   │
│   ├── pdf_extraction_01/             # Standalone PDF pipeline (no Temporal)
│   │   ├── process_pdf.py             # CLI-based PDF extraction
│   │   ├── .env
│   │   └── requirements.txt
│   │
│   ├── pdf_extraction_01_temporal/    # Temporal-based PDF pipeline
│   │   ├── worker.py                  # Temporal worker entrypoint
│   │   ├── workflow_process_pdf.py    # Workflow definition (3-step pipeline)
│   │   ├── activities.py              # Activity implementations
│   │   ├── helper.py                  # Dataclasses & S3 utilities
│   │   ├── .env
│   │   └── requirements.txt
│   │
│   └── ai_contract_review/            # AI Contract Review system
│       ├── worker.py                  # Temporal worker entrypoint
│       ├── parent_worker.py           # Parent workflow (orchestrator)
│       ├── child_worker.py            # Child workflow (per-PDF summarizer)
│       ├── activities.py              # PDF extraction & LLM call activities
│       ├── prompts.py                 # LLM prompt templates
│       ├── .env
│       ├── requirements.txt
│       └── samples/                   # Sample PDF contracts for testing
│           ├── vendor-service-agreement.pdf
│           ├── nda-innovate-consultpro.pdf
│           └── software-license-globalsoft.pdf
│
├── samples-server/                    # Temporal Docker Compose configs
│   └── compose/
│       ├── docker-compose-postgres.yml  # Primary: PostgreSQL + Temporal
│       ├── docker-compose-dev.yml       # Development setup
│       ├── .env                         # Docker image versions
│       └── scripts/                     # DB setup scripts
│
├── services/
│   └── temporal.service              # systemd unit (optional)
│
└── Dockerfile                        # (unrelated - aiohttp test infra)
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Runtime |
| Docker Desktop | Latest | Temporal server & infrastructure |
| pip | Latest | Python package management |

**Python Dependencies:**
- `fastapi`, `uvicorn` — HTTP server
- `temporalio` — Temporal Python SDK
- `boto3` — AWS S3 client
- `pymupdf4llm` — PDF to Markdown extraction
- `openai` — LLM API client (OpenRouter)
- `json-repair` — Robust JSON parsing from LLM output
- `python-dotenv` — Environment variable management

---

## Infrastructure Setup (Docker)

### Start Temporal Server

```bash
cd samples-server/compose
docker compose -f docker-compose-postgres.yml up -d
```

This starts:
- **PostgreSQL** on port `5432`
- **Temporal Server** on port `7233`
- **Temporal UI** on port `8080`
- **Admin Tools** (runs setup then exits)

### Verify Infrastructure

```bash
# Check all containers are running
docker ps

# Expected output:
# temporal-postgresql    (port 5432)
# temporal              (port 7233)
# temporal-ui           (port 8080)
```

### Access Temporal UI

Open [http://localhost:8080](http://localhost:8080) in your browser.

### Stop Infrastructure

```bash
docker compose -f docker-compose-postgres.yml down
```

### Optional: systemd Service (Linux)

```bash
sudo cp services/temporal.service /etc/systemd/system/
sudo systemctl enable temporal
sudo systemctl start temporal
```

---

## Environment Variables

Each sub-application has its own `.env` file. Below are the required variables:

### Client App (`app/client_app/.env`)

```env
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue
S3_BUCKET=temporal
```

### PDF Extraction Worker (`app/pdf_extraction_01_temporal/.env`)

```env
# S3 Storage
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_REGION=us-west-2
AWS_S3_ENDPOINT_URL=https://s3.us-west-2.idrivee2.com
S3_BUCKET=temporal
TEMP_DIR=/tmp/pdf-pipeline

# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
```

### Contract Review Worker (`app/ai_contract_review/.env`)

```env
# LLM API (OpenRouter)
OPENROUTER_API_KEY=<your-openrouter-key>
OPENROUTER_MODEL=deepseek/deepseek-v4-flash

# S3 Storage
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_REGION=us-west-2
AWS_S3_ENDPOINT_URL=https://s3.us-west-2.idrivee2.com
S3_BUCKET=temporal
TEMP_DIR=/tmp/pdf-pipeline

# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_PDF_PROCESS_TASK_QUEUE=pdf-pipeline-queue
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue
```

---

## Running the Application

### 1. Start Temporal Server

```bash
cd samples-server/compose
docker compose -f docker-compose-postgres.yml up -d
```

### 2. Start Workers (each in a separate terminal)

```bash
# Terminal 1: PDF Extraction Worker
cd app/pdf_extraction_01_temporal
pip install -r requirements.txt
python worker.py

# Terminal 2: Contract Review Worker
cd app/ai_contract_review
pip install -r requirements.txt
python worker.py
```

### 3. Start FastAPI Server

```bash
# Terminal 3: FastAPI Client
cd app/client_app
pip install -r requirements.txt
uvicorn main:app --reload --port 5000
```

### 4. Verify Everything is Running

```bash
# Health check
curl http://localhost:5000/health
# Expected: {"status":"ok"}

# Check Temporal UI
# Open http://localhost:8080
```

---

## API Endpoints

### Health Check

```
GET /health
```

**Response:**
```json
{"status": "ok"}
```

---

### PDF Extraction (Standalone Pipeline)

#### Execute and Wait

```
POST /process_pdf/execute
Content-Type: application/json

{
  "s3_path": "s3://temporal/document.pdf"
}
```

#### Start (Async)

```
POST /process_pdf/start
Content-Type: application/json

{
  "s3_path": "s3://temporal/document.pdf"
}
```

**Response:**
```json
{
  "workflow_id": "pdf-pipeline-<uuid>",
  "response": null
}
```

#### Check Status

```
GET /workflow/status/{workflow_id}
```

**Response:**
```json
{
  "status": "COMPLETED",
  "workflow_id": "pdf-pipeline-<uuid>",
  "result": {
    "s3_markdown_path": "s3://temporal/document.md"
  }
}
```

---

### AI Contract Review

#### Start Review

```
POST /contract-review/start
Content-Type: application/json

{
  "s3_paths": [
    "s3://temporal/contract1.pdf",
    "s3://temporal/contract2.pdf",
    "s3://temporal/contract3.pdf"
  ],
  "max_revesion": 2
}
```

**Response:**
```json
{
  "workflow_id": "contract-review-<uuid>"
}
```

#### Check Status

```
GET /contract-review/{workflow_id}/status
```

**Response:**
```json
{
  "workflow_id": "contract-review-<uuid>",
  "desc_status": "RUNNING",
  "workflow_status": {
    "status": "human_in_loop",
    "review_decision": null,
    "review_feedback": "",
    "approved_by": ""
  }
}
```

#### Get Full Report

```
GET /contract-review/{workflow_id}/report
```

**Response includes:**
- `overall_risk_level` — High/Medium/Low assessment
- `top_cross_contract_risks` — Cross-contract risk patterns
- `recommended_actions` — Actionable steps for the legal team
- `summuries` — Individual contract summaries with key risks
- `sources` — List of analyzed S3 document paths

#### Assign Reviewer (Signal)

```
POST /contract-review/{workflow_id}/post_reviewer
Content-Type: application/json

{
  "name": "ibrahim"
}
```

**Response:**
```json
{
  "status": "ok",
  "message": "reviewer assigned to ibrahim"
}
```

#### Submit Revision (Update)

```
POST /contract-review/{workflow_id}/revise
Content-Type: application/json

{
  "feedback": "Please write the report in Arabic."
}
```

**Response:**
```json
{
  "status": "ok",
  "message": "decision revise recorded"
}
```

#### Approve Report (Update)

```
POST /contract-review/{workflow_id}/approve
```

**Response:**
```json
{
  "status": "ok",
  "message": "decision approved recorded"
}
```

---

## Workflow Details

### PDF Extraction Workflow (`pdfpipelineworkflow`)

A simple 3-step sequential pipeline:

```
Download from S3 ──▶ Extract to Markdown ──▶ Upload to S3
```

| Step | Activity | Timeout | Retry |
|------|----------|---------|-------|
| 1 | `download_from_s3` | 1 min | 5 attempts |
| 2 | `extract_to_markdown` | 1 min | 5 attempts |
| 3 | `upload_markdown_to_s3` | 1 min | 5 attempts |

### Contract Review Workflow (`ContractReviewerWorkflow`)

A sophisticated parent workflow with child workflows and human-in-the-loop:

```
┌──────────────────────────────────────────────────────────────┐
│                    Parent Workflow                            │
│                                                              │
│  1. EXTRACTING: Fan-out to child workflows (parallel)        │
│     ├── Child 1: Download PDF → Extract → Summarize (LLM)   │
│     ├── Child 2: Download PDF → Extract → Summarize (LLM)   │
│     └── Child 3: Download PDF → Extract → Summarize (LLM)   │
│                                                              │
│  2. SYNTHESIZING: Combine summaries into cross-contract      │
│     risk report (LLM)                                        │
│                                                              │
│  3. HUMAN-IN-THE-LOOP: Wait for reviewer decision            │
│     ├── APPROVE → Complete                                   │
│     └── REVISE → Re-run LLM with feedback (up to N times)   │
│                                                              │
│  4. COMPLETED: Return final report                           │
└──────────────────────────────────────────────────────────────┘
```

**Temporal Features Used:**
- **Child Workflows** — Parallel PDF processing with `ParentClosePolicy.ABANDON`
- **Signals** — `assign_reviewer` to set reviewer name
- **Updates** — `submit_decision` for approve/revise with validation
- **Queries** — `query_status` and `query_fullreport` for real-time state
- **Activities** — PDF extraction and LLM calls with heartbeats
- **Retry Policies** — Configurable backoff for transient failures
- **Timeouts** — `schedule_to_close_timeout`, `start_to_close_timeout`, `heartbeat_timeout`

---

## Temporal Workers

### PDF Extraction Worker

**File:** `app/pdf_extraction_01_temporal/worker.py`

```bash
cd app/pdf_extraction_01_temporal
python worker.py
```

**Registers:**
- Workflow: `pdfpipelineworkflow`
- Activities: `download_from_s3`, `extract_to_markdown`, `upload_markdown_to_s3`
- Task Queue: `pdf-pipeline-queue`

### Contract Review Worker

**File:** `app/ai_contract_review/worker.py`

```bash
cd app/ai_contract_review
python worker.py
```

**Registers:**
- Workflows: `ContractReviewerWorkflow`, `pdfsummaryworkflow`
- Activities: `call_llm`, `extract_pdf`
- Task Queue: `contract-review-queue`

---

## Testing

### Test PDF Extraction

```bash
# Single document
curl -X POST http://localhost:5000/process_pdf/start \
  -H "Content-Type: application/json" \
  -d '{"s3_path": "s3://temporal/vendor-service-agreement.pdf"}'

# Check status
curl http://localhost:5000/workflow/status/pdf-pipeline-<uuid>
```

### Test Contract Review (Full Flow)

```bash
# 1. Start review with multiple contracts
curl -X POST http://localhost:5000/contract-review/start \
  -H "Content-Type: application/json" \
  -d '{
    "s3_paths": [
      "s3://temporal/vendor-service-agreement.pdf",
      "s3://temporal/nda-innovate-consultpro.pdf",
      "s3://temporal/software-license-globalsoft.pdf"
    ]
  }'

# 2. Check status (will show "extracting" → "synthesizing" → "human_in_loop")
curl http://localhost:5000/contract-review/{workflow_id}/status

# 3. Get the report
curl http://localhost:5000/contract-review/{workflow_id}/report

# 4. Assign a reviewer
curl -X POST http://localhost:5000/contract-review/{workflow_id}/post_reviewer \
  -H "Content-Type: application/json" \
  -d '{"name": "ibrahim"}'

# 5. Request revision
curl -X POST http://localhost:5000/contract-review/{workflow_id}/revise \
  -H "Content-Type: application/json" \
  -d '{"feedback": "Please write the report in Arabic."}'

# 6. Or approve the report
curl -X POST http://localhost:5000/contract-review/{workflow_id}/approve
```

### Sample PDFs

Test documents are available in `app/ai_contract_review/samples/`:
- `vendor-service-agreement.pdf` — Cloud services retainer agreement
- `nda-innovate-consultpro.pdf` — Non-disclosure agreement
- `software-license-globalsoft.pdf` — Software license agreement

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `uvicorn not found` | Run `pip install uvicorn fastapi` in the client app directory |
| `Could not import module "main"` | Ensure you're running from `app/client_app/` directory |
| Worker not picking up tasks | Verify worker is running and Temporal server is accessible on `localhost:7233` |
| S3 connection errors | Check AWS credentials and endpoint URL in `.env` |
| LLM errors | Verify `OPENROUTER_API_KEY` is valid and model is available |
| Docker containers not starting | Run `docker compose down` then `docker compose up -d` again |
| Port conflicts | Ensure ports 5000, 7233, 8080, 5432 are available |

---

## License

Internal project — not licensed for distribution.
