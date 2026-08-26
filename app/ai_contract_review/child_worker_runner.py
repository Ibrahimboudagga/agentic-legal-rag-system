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

log = get_logger("child_worker_runner")

from activities import call_llm, extract_pdf
from child_worker import pdfsummaryworkflow


async def main():
    config = get_temporal_config()
    metrics_port = int(os.getenv("CHILD_WORKER_METRICS_PORT", "9003"))
    start_http_server(metrics_port, registry=REGISTRY)
    log.info("metrics_server_started", port=metrics_port)

    interceptor = setup_tracing(service_name="pdf-summary-worker")
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
        task_queue=config.pdf_task_queue,
        workflows=[pdfsummaryworkflow],
        activities=[call_llm, extract_pdf],
    )

    log.info(
        "worker_started",
        task_queue=config.pdf_task_queue,
        workflows=["pdfsummaryworkflow"],
        activities=["call_llm", "extract_pdf"],
        metrics_port=metrics_port,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
