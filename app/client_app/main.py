import os
import sys
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import start_http_server
from pydantic import BaseModel
from temporalio.client import Client, WorkflowExecutionStatus as WES

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from shared.observability.logging import (
    configure_logging,
    get_logger,
    request_id_var,
)
from shared.observability.middleware import ObservabilityMiddleware
from shared.observability.metrics import REGISTRY, get_metrics_endpoint

configure_logging()
log = get_logger("api")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_PDF_PROCESS_TASK_QUEUE = os.getenv("TEMPORAL_PDF_PROCESS_TASK_QUEUE")
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE = os.getenv("TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE")
S3_BUCKET = os.getenv("S3_BUCKET")


class ExtractPDFRequest(BaseModel):
    s3_path: str


class ExtractPDFResponse(BaseModel):
    workflow_id: str
    response: dict


class startreviewrequest(BaseModel):
    s3_paths: list[str]
    max_revesion: int = 2


class requestsignal(BaseModel):
    name: str


class requestrevise(BaseModel):
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


async def get_temporal_client():
    try:
        client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
        return client
    except Exception as e:
        log.error("temporal_connection_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
        task_queue=TEMPORAL_PDF_PROCESS_TASK_QUEUE,
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
    response = await client.start_workflow(
        "pdfpipelineworkflow",
        {"s3_pdf_path": request.s3_path},
        id=workflow_id,
        task_queue=TEMPORAL_PDF_PROCESS_TASK_QUEUE,
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
async def startreview(request: startreviewrequest):
    req_id = request_id_var.get()
    log.info(
        "contract_review_start",
        s3_paths_count=len(request.s3_paths),
        max_revision=request.max_revesion,
        request_id=req_id,
    )

    client = await get_temporal_client()
    workflow_id = f"contract-review-{uuid.uuid4()}"
    response = await client.start_workflow(
        "ContractReviewerWorkflow",
        args=[{"s3_paths": request.s3_paths, "max_revesion": request.max_revesion}],
        id=workflow_id,
        task_queue=TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE,
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
async def post_reviewer(workflow_id: str, request: requestsignal):
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
async def submit_revise(workflow_id: str, request: requestrevise):
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
    result = await handle.execute_update("submit_decision", args=["approve", ""])

    return {"status": "ok", "message": result}
