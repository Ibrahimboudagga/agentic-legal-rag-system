from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from prometheus_client import start_http_server
from temporalio.client import Client
from temporalio.worker import Worker

from shared.config import get_temporal_config
from shared.observability.logging import configure_logging, get_logger
from shared.observability.metrics import REGISTRY
from shared.observability.tracing import setup_temporal_runtime, setup_tracing

load_dotenv()
configure_logging()

log = get_logger("parent_worker")

from activities import extract_pdf, call_llm
from parent_worker import ContractReviewerWorkflow
from child_worker import pdfsummaryworkflow
from agents.activities import ingest_document_activity, run_agent_graph_activity
from agents.ingest_workflow import IngestDocumentWorkflow
from agents.review_workflow import AgentReviewWorkflow


async def main():
    config = get_temporal_config()
    metrics_port = int(os.getenv("WORKER_METRICS_PORT", "9001"))
    start_http_server(metrics_port, registry=REGISTRY)
    log.info("metrics_server_started", port=metrics_port)

    interceptor = setup_tracing(service_name="contract-review-parent-worker")
    runtime = setup_temporal_runtime()

    log.info(
        "connecting_to_temporal",
        host=config.host,
        namespace=config.namespace,
    )

    client = await Client.connect(
        config.host,
        namespace=config.namespace,
        interceptors=[interceptor],
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=config.contract_review_task_queue,
        workflows=[
            ContractReviewerWorkflow,
            pdfsummaryworkflow,
            IngestDocumentWorkflow,
            AgentReviewWorkflow,
        ],
        activities=[
            extract_pdf,
            call_llm,
            ingest_document_activity,
            run_agent_graph_activity,
        ],
    )

    log.info(
        "worker_started",
        task_queue=config.contract_review_task_queue,
        workflows=[
            "ContractReviewerWorkflow",
            "pdfsummaryworkflow",
            "IngestDocumentWorkflow",
            "AgentReviewWorkflow",
        ],
        activities=[
            "extract_pdf",
            "call_llm",
            "ingest_document_activity",
            "run_agent_graph_activity",
        ],
        metrics_port=metrics_port,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
