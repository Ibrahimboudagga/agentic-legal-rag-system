# Testing Guide - Agentic Legal RAG System

## Table of Contents

- [Testing Strategy](#testing-strategy)
- [Prerequisites](#prerequisites)
- [Test Environment Setup](#test-environment-setup)
- [Unit Tests](#unit-tests)
- [Integration Tests](#integration-tests)
- [Manual API Testing](#manual-api-testing)
- [End-to-End Scenarios](#end-to-end-scenarios)
- [Troubleshooting](#troubleshooting)

---

## Testing Strategy

Three layers tested independently:

| Layer | What to Test | How |
|-------|-------------|-----|
| A - Deterministic | Chunker, embedder, reranker, validator, hybrid search | Unit tests, no mocks |
| B - Agentic Reasoning | Planner, analysis, comparison, synthesis nodes | Integration tests with mocked LLM |
| C - LLM Inference | LLMClient retry, cost tracking, JSON repair | Unit tests with mocked HTTP |

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| Python 3.11+ | Runtime |
| Docker Desktop | PostgreSQL, Temporal |
| pytest | Test runner |
| pytest-asyncio | Async test support |
| httpx | HTTP client for API tests |

---

## Test Environment Setup

### 1. Start Test Infrastructure

```bash
cd samples-server/compose
docker compose -f docker-compose-postgres.yml up -d
```

### 2. Initialize pgvector

```bash
docker exec temporal-postgresql psql -U postgres -d legal_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Install Test Dependencies

```bash
cd app/ai_contract_review
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx
```

### 4. Create Test .env

**app/ai_contract_review/.env.test:**

```env
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE=contract-review-queue
AWS_ACCESS_KEY_ID=test-key
AWS_SECRET_ACCESS_KEY=test-secret
AWS_REGION=us-west-2
AWS_S3_ENDPOINT_URL=https://s3.us-west-2.idrivee2.com
S3_BUCKET=test-bucket
TEMP_DIR=/tmp/pdf-pipeline-test
OPENROUTER_API_KEY=test-key
LLM_MODEL_NAME=deepseek/deepseek-v4-flash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag
DATABASE_SYNC_URL=postgresql://postgres:postgres@localhost:5432/legal_rag
DB_POOL_SIZE=2
EMBEDDING_DIM=384
LOG_LEVEL=DEBUG
```

---

## Unit Tests

### Test 1: Configuration Loading

```python
# tests/test_config.py
import os

def test_temporal_config_defaults():
    os.environ.setdefault("TEMPORAL_HOST", "localhost:7233")
    from shared.config import TemporalConfig
    config = TemporalConfig()
    assert config.host == "localhost:7233"
    assert config.namespace == "default"
    assert config.pdf_task_queue == "pdf-pipeline-queue"
    assert config.contract_review_task_queue == "contract-review-queue"

def test_database_config_defaults():
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag")
    from shared.config import DatabaseConfig
    config = DatabaseConfig()
    assert "legal_rag" in config.url
    assert config.embedding_dim == 384
```

### Test 2: Chunker

```python
# tests/test_chunker.py
from ingestion.chunker import chunk_markdown

def test_basic_chunking():
    text = "# Contract\n\nThis is clause one.\n\nThis is clause two."
    chunks = chunk_markdown(text, max_tokens=50)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert "content" in chunk

def test_empty_text():
    chunks = chunk_markdown("", max_tokens=512)
    assert chunks == []

def test_single_paragraph():
    text = "Single paragraph with no breaks."
    chunks = chunk_markdown(text, max_tokens=512)
    assert len(chunks) >= 1
    assert "Single paragraph" in chunks[0]["content"]
```

### Test 3: Embedder

```python
# tests/test_embedder.py
import numpy as np

def test_embedding_dimensions():
    from ingestion.embedder import get_embedding
    embedding = get_embedding("test text")
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (384,)

def test_embedding_deterministic():
    from ingestion.embedder import get_embedding
    e1 = get_embedding("hello world")
    e2 = get_embedding("hello world")
    np.testing.assert_array_equal(e1, e2)

def test_embedding_similarity():
    from ingestion.embedder import get_embedding
    e1 = get_embedding("termination clause")
    e2 = get_embedding("termination provision")
    e3 = get_embedding("weather forecast")
    sim_12 = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
    sim_13 = np.dot(e1, e3) / (np.linalg.norm(e1) * np.linalg.norm(e3))
    assert sim_12 > sim_13
```

### Test 4: Reranker

```python
# tests/test_reranker.py
from agents.reranker import rerank_chunks

def test_rerank_returns_sorted():
    chunks = [
        {"chunk_id": "1", "content": "termination clause", "s3_path": "a.pdf", "score": 0.5},
        {"chunk_id": "2", "content": "liability cap provisions", "s3_path": "a.pdf", "score": 0.7},
        {"chunk_id": "3", "content": "indemnification terms", "s3_path": "a.pdf", "score": 0.3},
    ]
    query = "What are the termination provisions?"
    results = rerank_chunks(query, chunks, top_k=2)
    assert len(results) == 2
    assert results[0]["rerank_score"] >= results[1]["rerank_score"]

def test_rerank_respects_top_k():
    chunks = [{"chunk_id": str(i), "content": f"chunk {i}", "s3_path": "a.pdf", "score": 0.5} for i in range(10)]
    results = rerank_chunks("test query", chunks, top_k=3)
    assert len(results) == 3
```

### Test 5: Evidence Validator

```python
# tests/test_evidence_validator.py
from agents.evidence_validator import validate_evidence

def test_sufficient_evidence():
    evidence = [
        {"citation_id": 1, "content": "Termination clause allows 30 days notice.", "relevance_score": 0.9, "s3_path": "a.pdf"},
        {"citation_id": 2, "content": "Liability capped at $100,000.", "relevance_score": 0.85, "s3_path": "a.pdf"},
        {"citation_id": 3, "content": "Indemnification applies to third-party claims.", "relevance_score": 0.8, "s3_path": "b.pdf"},
    ]
    result = validate_evidence(evidence, query="What are termination and liability terms?")
    assert result["passed"] is True
    assert result["coverage_score"] > 0.5

def test_insufficient_evidence():
    evidence = [{"citation_id": 1, "content": "Something unrelated.", "relevance_score": 0.3, "s3_path": "a.pdf"}]
    result = validate_evidence(evidence, query="What are the termination clauses?")
    assert result["passed"] is False
```

### Test 6: Evidence Store

```python
# tests/test_evidence_store.py
from agents.evidence_store import EvidenceStore

def test_add_and_dedup():
    store = EvidenceStore()
    chunks = [
        {"chunk_id": "c1", "content": "text1", "s3_path": "a.pdf", "score": 0.9},
        {"chunk_id": "c2", "content": "text2", "s3_path": "a.pdf", "score": 0.8},
        {"chunk_id": "c1", "content": "text1 dup", "s3_path": "a.pdf", "score": 0.9},
    ]
    items = store.add_raw(chunks)
    assert len(items) == 2

def test_citation_ids_sequential():
    store = EvidenceStore()
    store.add_raw([{"chunk_id": "c1", "content": "a", "s3_path": "x.pdf", "score": 0.9}])
    store.add_raw([{"chunk_id": "c2", "content": "b", "s3_path": "x.pdf", "score": 0.8}])
    items = store.get_all()
    assert items[0].citation_id == 1
    assert items[1].citation_id == 2

def test_clear():
    store = EvidenceStore()
    store.add_raw([{"chunk_id": "c1", "content": "a", "s3_path": "x.pdf", "score": 0.9}])
    store.clear()
    assert store.count() == 0
```

### Test 7: Hybrid Search RRF Merge

```python
# tests/test_hybrid_search.py
from retrieval.hybrid_search import rrf_merge

def test_rrf_merge():
    semantic = [{"chunk_id": "1", "score": 0.9}, {"chunk_id": "2", "score": 0.8}, {"chunk_id": "3", "score": 0.7}]
    keyword = [{"chunk_id": "2", "score": 0.95}, {"chunk_id": "4", "score": 0.6}, {"chunk_id": "1", "score": 0.5}]
    merged = rrf_merge(semantic, keyword, k=60)
    assert len(merged) == 4
    assert merged[0]["chunk_id"] == "2"
```

---

## Integration Tests

### Test 8: Database Operations

```python
# tests/test_database.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from shared.database import Base, Document, Chunk

@pytest.fixture
async def db_session():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()

@pytest.mark.asyncio
async def test_create_document(db_session):
    doc = Document(s3_path="s3://test/contract.pdf", content_hash="abc123", total_pages=10, extraction_status="completed")
    db_session.add(doc)
    await db_session.commit()
    assert doc.id is not None

@pytest.mark.asyncio
async def test_create_chunk_with_embedding(db_session):
    import numpy as np
    doc = Document(s3_path="s3://test/contract.pdf", content_hash="abc123", total_pages=10, extraction_status="completed")
    db_session.add(doc)
    await db_session.commit()
    embedding = np.random.rand(384).tolist()
    chunk = Chunk(document_id=doc.id, s3_path="s3://test/contract.pdf", content="Termination clause allows 30 days notice.", chunk_index=0, page_number=1, start_line=0, end_line=10, token_count=8, embedding=embedding)
    db_session.add(chunk)
    await db_session.commit()
    assert chunk.id is not None
```

### Test 9: LLM Client (Mocked)

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_llm_client_complete_json():
    from shared.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)
    client._api_key = "test-key"
    client._model = "test-model"
    client._base_url = "https://openrouter.ai/api/v1"
    client._max_tokens = 8000
    client._input_price = 0.00014
    client._output_price = 0.00028
    client._max_retries = 1
    client._retry_delay = 0.1
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    with patch.object(client, "_get_client") as mock_get:
        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get.return_value = mock_openai
        result = await client.complete_json("test prompt", "system")
        assert result == {"result": "ok"}

@pytest.mark.asyncio
async def test_llm_client_json_repair():
    from shared.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)
    client._api_key = "test-key"
    client._model = "test-model"
    client._base_url = "https://openrouter.ai/api/v1"
    client._max_tokens = 8000
    client._input_price = 0.00014
    client._output_price = 0.00028
    client._max_retries = 1
    client._retry_delay = 0.1
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok",}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    with patch.object(client, "_get_client") as mock_get:
        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get.return_value = mock_openai
        result = await client.complete_json("test prompt", "system")
        assert result == {"result": "ok"}
```

---

## Manual API Testing

### Health Check

```bash
curl http://localhost:5000/health
# Expected: {"status":"ok"}
```

### Metrics

```bash
curl http://localhost:9001/metrics | head -5
curl http://localhost:9002/metrics | head -5
```

### Ingest

```bash
curl -X POST http://localhost:5000/ingest \
  -H "Content-Type: application/json" \
  -d '{"s3_path": "s3://temporal/vendor-service-agreement.pdf"}'
```

### Agent Review

```bash
curl -X POST http://localhost:5000/agent-review/start \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the termination clauses?", "s3_paths": ["s3://temporal/vendor-service-agreement.pdf"]}'
curl http://localhost:5000/agent-review/{workflow_id}/status
curl http://localhost:5000/agent-review/{workflow_id}/report
```

---

## End-to-End Scenarios

### Scenario 1: Single Contract Analysis

```bash
# 1. Ingest
curl -X POST http://localhost:5000/ingest \
  -H "Content-Type: application/json" \
  -d '{"s3_path": "s3://temporal/vendor-service-agreement.pdf"}'

# 2. Wait for ingestion (check Temporal UI)

# 3. Run review
curl -X POST http://localhost:5000/agent-review/start \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the termination clauses, liability caps, and indemnification terms?", "s3_paths": ["s3://temporal/vendor-service-agreement.pdf"]}'

# 4. Get report
curl http://localhost:5000/agent-review/{workflow_id}/report
```

### Scenario 2: Multi-Contract Comparison

```bash
# 1. Ingest all
for pdf in vendor-service-agreement.pdf nda-innovate-consultpro.pdf software-license-globalsoft.pdf; do
  curl -X POST http://localhost:5000/ingest \
    -H "Content-Type: application/json" \
    -d "{\"s3_path\": \"s3://temporal/$pdf\"}"
done

# 2. Run comparison
curl -X POST http://localhost:5000/agent-review/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare termination clauses across all contracts.", "s3_paths": ["s3://temporal/vendor-service-agreement.pdf", "s3://temporal/nda-innovate-consultpro.pdf", "s3://temporal/software-license-globalsoft.pdf"]}'
```

### Scenario 3: HITL Flow

```bash
# 1. Start review
curl -X POST http://localhost:5000/agent-review/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Key risks in this vendor agreement?", "s3_paths": ["s3://temporal/vendor-service-agreement.pdf"]}'

# 2. Wait for human_in_loop status

# 3. Assign reviewer
curl -X POST http://localhost:5000/contract-review/{workflow_id}/post_reviewer \
  -H "Content-Type: application/json" \
  -d '{"name": "john.doe"}'

# 4. Approve or revise
curl -X POST http://localhost:5000/contract-review/{workflow_id}/approve
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Tests fail with connection refused | Ensure Docker containers are running: docker compose ps |
| pgvector extension not found | Run: CREATE EXTENSION IF NOT EXISTS vector; |
| Embedding dimension mismatch | Ensure EMBEDDING_DIM=384 |
| LLM tests fail | Check mocked responses return valid JSON |
| Ingestion fails | Verify S3 credentials and bucket |
| Agent review stuck | Check Temporal UI for activity failures |
| Module not found errors | Run from correct directory with sys.path configured |

### Running All Tests

```bash
cd app/ai_contract_review
python -m pytest tests/ -v
```

### Running Specific Test

```bash
python -m pytest tests/test_chunker.py -v
python -m pytest tests/test_evidence_validator.py::test_sufficient_evidence -v
```
