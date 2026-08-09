from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import start_http_server
from pydantic import BaseModel
from temporalio.client import Client, WorkflowExecutionStatus as WES

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
load_dotenv()

from shared.config import get_temporal_config
from shared.observability.logging import (
    configure_logging,
    get_logger,
    request_id_var,
)
from shared.observability.middleware import ObservabilityMiddleware
from shared.observability.metrics import REGISTRY, get_metrics_endpoint

configure_logging()
log = get_logger("api")

_config = get_temporal_config()
_temporal_client: Optional[Client] = None


async def get_temporal_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        try:
            _temporal_client = await Client.connect(
                _config.host, namespace=_config.namespace
            )
        except Exception as e:
            log.error("temporal_connection_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    return _temporal_client


class ExtractPDFRequest(BaseModel):
    s3_path: str


class ExtractPDFResponse(BaseModel):
    workflow_id: str
    response: Optional[dict] = None


class StartReviewRequest(BaseModel):
    s3_paths: list[str]
    max_revision: int = 2


class AssignReviewerRequest(BaseModel):
    name: str


class ReviseRequest(BaseModel):
    feedback: str


app = FastAPI(
    title="AI Contract Intelligence Platform",
    description="Temporal-orchestrated contract review with AI analysis",
    version="2.0.0",
)
app.add_middleware(ObservabilityMiddleware)

metrics_port = int(os.getenv("API_METRICS_PORT", "9002"))
start_http_server(metrics_port, registry=REGISTRY)
log.info("api_metrics_server_started", port=metrics_port)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(get_metrics_endpoint(), media_type="text/plain")


@app.post("/process_pdf/execute", response_model=ExtractPDFResponse)
async def process_pdf_execute(request: ExtractPDFRequest):
    req_id = request_id_var.get()
    log.info("pdf_process_execute_started", s3_path=request.s3_path, request_id=req_id)

    client = await get_temporal_client()
    workflow_id = f"pdf-pipeline-{uuid.uuid4()}"
    start = time.monotonic()
    response = await client.execute_workflow(
        "pdfpipelineworkflow",
        {"s3_pdf_path": request.s3_path},
        id=workflow_id,
        task_queue=_config.pdf_task_queue,
    )
    duration = time.monotonic() - start

    log.info(
        "pdf_process_execute_completed",
        workflow_id=workflow_id,
        duration_seconds=round(duration, 3),
    )

    return ExtractPDFResponse(
        workflow_id=workflow_id,
        response=response if isinstance(response, dict) else vars(response),
    )


@app.post("/process_pdf/start", response_model=ExtractPDFResponse)
async def process_pdf_start(request: ExtractPDFRequest):
    req_id = request_id_var.get()
    log.info("pdf_process_start_started", s3_path=request.s3_path, request_id=req_id)

    client = await get_temporal_client()
    workflow_id = f"pdf-pipeline-{uuid.uuid4()}"
    await client.start_workflow(
        "pdfpipelineworkflow",
        {"s3_pdf_path": request.s3_path},
        id=workflow_id,
        task_queue=_config.pdf_task_queue,
    )

    log.info("pdf_process_start_completed", workflow_id=workflow_id)

    return ExtractPDFResponse(workflow_id=workflow_id, response=None)


@app.get("/workflow/status/{workflow_id}")
async def get_status(workflow_id: str):
    log.info("workflow_status_query", workflow_id=workflow_id)

    client = await get_temporal_client()
    try:
        handle = client.get_workflow_handle(workflow_id)
        description = await handle.describe()
        res = await handle.result()
        result = {
            "status": description.status.name,
            "workflow_id": workflow_id,
            "result": res,
        }
        return result
    except Exception as e:
        log.error("workflow_status_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/contract-review/start")
async def start_review(request: StartReviewRequest):
    req_id = request_id_var.get()
    log.info(
        "contract_review_start",
        s3_paths_count=len(request.s3_paths),
        max_revision=request.max_revision,
        request_id=req_id,
    )

    client = await get_temporal_client()
    workflow_id = f"contract-review-{uuid.uuid4()}"
    await client.start_workflow(
        "ContractReviewerWorkflow",
        args=[{
            "s3_paths": request.s3_paths,
            "max_revision": request.max_revision,
            "child_task_queue": _config.contract_review_task_queue,
        }],
        id=workflow_id,
        task_queue=_config.contract_review_task_queue,
    )

    log.info("contract_review_started", workflow_id=workflow_id)

    return {"workflow_id": workflow_id}


@app.get("/contract-review/{workflow_id}/status")
async def get_review_status(workflow_id: str):
    log.info("review_status_query", workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_status = None
        if desc.status == WES.RUNNING:
            try:
                workflow_status = await handle.query("query_status", result_type=dict)
            except Exception as e:
                workflow_status = {"error": f"error is {e}"}

        return {
            "workflow_id": workflow_id,
            "desc_status": desc.status.name,
            "workflow_status": workflow_status,
        }
    except Exception as e:
        log.error("review_status_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/contract-review/{workflow_id}/report")
async def get_review_report(workflow_id: str):
    log.info("review_report_query", workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_report = None
        if desc.status == WES.RUNNING:
            try:
                workflow_report = await handle.query(
                    "query_fullreport", result_type=dict
                )
            except Exception as e:
                workflow_report = {"error": f"error is {e}"}

        return {
            "workflow_id": workflow_id,
            "desc_status": desc.status.name,
            "workflow_report": workflow_report,
        }
    except Exception as e:
        log.error("review_report_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/contract-review/{workflow_id}/post_reviewer")
async def post_reviewer(workflow_id: str, request: AssignReviewerRequest):
    log.info(
        "reviewer_assignment",
        workflow_id=workflow_id,
        reviewer=request.name,
    )

    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("assign_reviewer", request.name)

    return {"status": "ok", "message": f"reviewer assigned to {request.name}"}


@app.post("/contract-review/{workflow_id}/revise")
async def submit_revise(workflow_id: str, request: ReviseRequest):
    log.info(
        "revision_submitted",
        workflow_id=workflow_id,
        feedback_length=len(request.feedback),
    )

    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    result = await handle.execute_update(
        "submit_decision", args=["revise", request.feedback]
    )

    return {"status": "ok", "message": result}


@app.post("/contract-review/{workflow_id}/approve")
async def submit_approve(workflow_id: str):
    log.info("approval_submitted", workflow_id=workflow_id)

    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    result = await handle.execute_update("submit_decision", args=["approved", ""])

    return {"status": "ok", "message": result}


# ── Agentic RAG Endpoints ────────────────────────────────────────


class IngestRequest(BaseModel):
    s3_path: str
    batch_size: int = 2
    max_chunk_tokens: int = 512


class AgentReviewRequest(BaseModel):
    query: str
    s3_paths: list[str]
    top_k: int = 5


@app.post("/ingest")
async def ingest_document_endpoint(request: IngestRequest):
    """Ingest a document into the vector store for retrieval."""
    req_id = request_id_var.get()
    log.info("ingest_started", s3_path=request.s3_path, request_id=req_id)

    client = await get_temporal_client()
    workflow_id = f"ingest-{uuid.uuid4()}"
    await client.start_workflow(
        "IngestDocumentWorkflow",
        args=[{
            "s3_path": request.s3_path,
            "batch_size": request.batch_size,
            "max_chunk_tokens": request.max_chunk_tokens,
        }],
        id=workflow_id,
        task_queue=_config.contract_review_task_queue,
    )

    log.info("ingest_started", workflow_id=workflow_id)

    return {"workflow_id": workflow_id, "status": "ingesting"}


@app.post("/agent-review/start")
async def start_agent_review(request: AgentReviewRequest):
    """Start an agentic RAG review workflow.

    Uses LangGraph multi-agent system with hybrid retrieval:
    - Retriever Agent: finds relevant chunks via semantic + keyword search
    - Analyzer Agent: performs legal analysis with evidence grounding
    - Critic Agent: evaluates quality and provides feedback
    - Finalizer: produces the final evidence-grounded report
    """
    req_id = request_id_var.get()
    log.info(
        "agent_review_start",
        query_length=len(request.query),
        s3_paths_count=len(request.s3_paths),
        request_id=req_id,
    )

    client = await get_temporal_client()
    workflow_id = f"agent-review-{uuid.uuid4()}"
    await client.start_workflow(
        "AgentReviewWorkflow",
        args=[{
            "query": request.query,
            "s3_paths": request.s3_paths,
            "top_k": request.top_k,
            "max_iterations": 2,
        }],
        id=workflow_id,
        task_queue=_config.contract_review_task_queue,
    )

    log.info("agent_review_started", workflow_id=workflow_id)

    return {"workflow_id": workflow_id}


@app.get("/agent-review/{workflow_id}/status")
async def get_agent_review_status(workflow_id: str):
    """Get status of an agent review workflow."""
    log.info("agent_review_status_query", workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_status = None
        if desc.status == WES.RUNNING:
            try:
                workflow_status = await handle.query("query_status", result_type=dict)
            except Exception as e:
                workflow_status = {"error": f"error is {e}"}

        return {
            "workflow_id": workflow_id,
            "desc_status": desc.status.name,
            "workflow_status": workflow_status,
        }
    except Exception as e:
        log.error("agent_review_status_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/agent-review/{workflow_id}/report")
async def get_agent_review_report(workflow_id: str):
    """Get the full evidence-grounded report from an agent review."""
    log.info("agent_review_report_query", workflow_id=workflow_id)

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_report = None
        if desc.status == WES.RUNNING:
            try:
                workflow_report = await handle.query(
                    "query_fullreport", result_type=dict
                )
            except Exception as e:
                workflow_report = {"error": f"error is {e}"}

        return {
            "workflow_id": workflow_id,
            "desc_status": desc.status.name,
            "workflow_report": workflow_report,
        }
    except Exception as e:
        log.error("agent_review_report_failed", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
