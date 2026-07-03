import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from temporalio.client import Client
from pydantic import BaseModel
import uuid
from temporalio.client import WorkflowExecutionStatus as WES


load_dotenv()

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_PDF_PROCESS_TASK_QUEUE = os.getenv("TEMPORAL_PDF_PROCESS_TASK_QUEUE")
TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE = os.getenv("TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE")
S3_BUCKET = os.getenv("S3_BUCKET")


# Create a model for the request body to validate inputs
class ExtractPDFRequest(BaseModel):
    s3_path: str


class ExtractPDFResponse(BaseModel):
    workflow_id:str
    response:dict

class startreviewrequest(BaseModel):
    s3_paths:list[str]
    max_revesion:int=2

class requestsignal(BaseModel):
    name:str

class requestrevise(BaseModel):
    feedback:str
    

app = FastAPI(title="S3 PDF Extraction Client",description="Temporal workflow for S3 PDF Extraction",version="1.0.0")
async def get_temporal_client():
    try:
        client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
        return client
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status":"ok"}


@app.post("/process_pdf/execute", response_model=ExtractPDFResponse)
async def process_pdf(request: ExtractPDFRequest):

    client = await get_temporal_client()
    workflow_id = f"pdf-pipeline-{uuid.uuid4()}"
    response = await client.execute_workflow(
        "pdfpipelineworkflow",
        {"s3_pdf_path": request.s3_path},
        id=workflow_id,
        task_queue=TEMPORAL_PDF_PROCESS_TASK_QUEUE,
    )

    return ExtractPDFResponse(workflow_id=workflow_id,
    response=response if isinstance(response, dict) else vars(response))
    



@app.post("/process_pdf/start", response_model=ExtractPDFResponse)
async def process_pdf(request: ExtractPDFRequest):

    client = await get_temporal_client()
    workflow_id = f"pdf-pipeline-{uuid.uuid4()}"
    response = await client.start_workflow(
        "pdfpipelineworkflow",
        {"s3_pdf_path": request.s3_path},
        id=workflow_id,
        task_queue=TEMPORAL_PDF_PROCESS_TASK_QUEUE,
    )

    return ExtractPDFResponse(workflow_id=workflow_id,
    response=None)
    

@app.get("/workflow/status/{workflow_id}")
async def get_status(workflow_id: str):

    client = await get_temporal_client()
    try:
        handle = client.get_workflow_handle(workflow_id)
        description = await handle.describe()
        res = await handle.result()
        result = {"status": description.status.name,
        "workflow_id": workflow_id,
        "result":res}
        return result
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/contract-review/start")
async def startreview(request:startreviewrequest):

    client = await get_temporal_client()

    workflow_id = f"contract-review-{uuid.uuid4()}"
    response = await client.start_workflow(
        "ContractReviewerWorkflow",
        args = [{"s3_paths":request.s3_paths,"max_revesion":request.max_revesion}],
        id=workflow_id,
        task_queue=TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE,
    )

    return {"workflow_id":workflow_id}

@app.get("/contract-review/{workflow_id}/status")
async def get_review_status(workflow_id:str):
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_status = None
        if desc.status == WES.RUNNING:
            try:
                workflow_status = await handle.query("query_status", result_type = dict)
            except Exception as e:
                workflow_status = {"error":f'error is {e}'}
        
        return {
            "workflow_id":workflow_id,
            "desc_status":desc.status.name,
            "workflow_status":workflow_status,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/contract-review/{workflow_id}/report")
async def get_review_report(workflow_id:str):
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        workflow_report = None
        if desc.status == WES.RUNNING:
            try:
                workflow_report = await handle.query("query_fullreport", result_type = dict)
            except Exception as e:
                workflow_report = {"error":f'error is {e}'}
        
        return {
            "workflow_id":workflow_id,
            "desc_status":desc.status.name,
            "workflow_report":workflow_report,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/contract-review/{workflow_id}/post_reviewer")
async def post_reviewer(workflow_id:str, request: requestsignal):
    
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("assign_reviewer",request.name)

    return {
        "status": "ok",
        "message":f"reviewer assigned to {request.name}"
    }

@app.post("/contract-review/{workflow_id}/revise")
async def submit_revise(workflow_id:str, request: requestrevise):
    
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    result = await handle.execute_update("submit_decision",args = ["revise",request.feedback])

    return {
        "status": "ok",
        "message":result
    }

@app.post("/contract-review/{workflow_id}/approve")
async def submit_approve(workflow_id:str):
    
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    result = await handle.execute_update("submit_decision",args = ["approve",""])

    return {
        "status": "ok",
        "message":result
    }

