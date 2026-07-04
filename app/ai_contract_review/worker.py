import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv
from prometheus_client import start_http_server
from temporalio.client import Client
from temporalio.worker import Worker

from shared.observability.logging import configure_logging, get_logger
from shared.observability.metrics import REGISTRY
from shared.observability.tracing import setup_temporal_runtime, setup_tracing

load_dotenv()
configure_logging()

log = get_logger("worker")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_TASK_QUEUE = os.getenv(
    "TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE", "contract-review-queue"
)
from activities import call_llm, extract_pdf
from child_worker import pdfsummaryworkflow
from parent_worker import ContractReviewerWorkflow


async def main():
    metrics_port = int(os.getenv("WORKER_METRICS_PORT", "9001"))
    start_http_server(metrics_port, registry=REGISTRY)
    log.info("metrics_server_started", port=metrics_port)

    interceptor = setup_tracing(service_name="contract-review-worker")
    runtime = setup_temporal_runtime()

    log.info(
        "connecting_to_temporal",
        host=TEMPORAL_HOST,
        namespace=TEMPORAL_NAMESPACE,
    )

    client = await Client.connect(
        TEMPORAL_HOST,
        namespace=TEMPORAL_NAMESPACE,
        interceptors=[interceptor],
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[ContractReviewerWorkflow, pdfsummaryworkflow],
        activities=[call_llm, extract_pdf],
    )

    log.info(
        "worker_started",
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=["ContractReviewerWorkflow", "pdfsummaryworkflow"],
        activities=["call_llm", "extract_pdf"],
        metrics_port=metrics_port,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
