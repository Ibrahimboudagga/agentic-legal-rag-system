from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from shared.observability.logging import get_logger, task_queue_var, workflow_id_var
    from shared.observability.metrics import (
        active_workflows,
        workflow_completed_total,
        workflow_duration_seconds,
        workflow_failed_total,
        workflow_started_total,
    )
    from agents.activities import (
        IngestDocumentInput,
        ingest_document_activity,
    )

log = get_logger("ingest_workflow")


@dataclass
class IngestDocumentWorkflowInput:
    s3_path: str
    batch_size: int = 2
    max_chunk_tokens: int = 512


@dataclass
class IngestDocumentWorkflowOutput:
    document_id: str
    s3_path: str
    total_chunks: int
    status: str


@workflow.defn
class IngestDocumentWorkflow:
    """Temporal workflow for document ingestion into the vector store.

    Steps:
    1. Download PDF from S3
    2. Extract markdown
    3. Chunk text
    4. Generate embeddings
    5. Store in pgvector
    """

    def __init__(self):
        self.status: str = "pending"
        self.document_id: str = ""

    @workflow.query
    def query_status(self):
        return {
            "status": self.status,
            "document_id": self.document_id,
        }

    @workflow.run
    async def run(
        self, param: IngestDocumentWorkflowInput
    ) -> IngestDocumentWorkflowOutput:
        info = workflow.info()
        workflow_id_var.set(info.workflow_id)
        task_queue_var.set(info.task_queue)

        with workflow.unsafe.sandbox_unrestricted():
            workflow_started_total.labels(
                workflow_type="IngestDocumentWorkflow",
                task_queue=info.task_queue,
            ).inc()
            active_workflows.labels(workflow_type="IngestDocumentWorkflow").inc()

        start_time = workflow.now().timestamp()

        try:
            self.status = "ingesting"
            log.info(
                "ingest_workflow_started",
                s3_path=param.s3_path,
            )

            result = await workflow.execute_activity(
                ingest_document_activity,
                IngestDocumentInput(
                    s3_path=param.s3_path,
                    batch_size=param.batch_size,
                    max_chunk_tokens=param.max_chunk_tokens,
                ),
                schedule_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=120),
                start_to_close_timeout=timedelta(minutes=30),
            )

            self.document_id = result.document_id
            self.status = "completed"

            duration = workflow.now().timestamp() - start_time
            with workflow.unsafe.sandbox_unrestricted():
                workflow_completed_total.labels(
                    workflow_type="IngestDocumentWorkflow",
                    task_queue=info.task_queue,
                ).inc()
                workflow_duration_seconds.labels(
                    workflow_type="IngestDocumentWorkflow"
                ).observe(duration)

            log.info(
                "ingest_workflow_completed",
                s3_path=param.s3_path,
                total_chunks=result.total_chunks,
                duration_seconds=round(duration, 3),
            )

            return IngestDocumentWorkflowOutput(
                document_id=result.document_id,
                s3_path=result.s3_path,
                total_chunks=result.total_chunks,
                status="completed",
            )

        except Exception as exc:
            duration = workflow.now().timestamp() - start_time
            self.status = "failed"
            with workflow.unsafe.sandbox_unrestricted():
                workflow_failed_total.labels(
                    workflow_type="IngestDocumentWorkflow",
                    task_queue=info.task_queue,
                    error_type=type(exc).__name__,
                ).inc()
                workflow_duration_seconds.labels(
                    workflow_type="IngestDocumentWorkflow"
                ).observe(duration)

            log.error(
                "ingest_workflow_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_seconds=round(duration, 3),
            )
            raise

        finally:
            with workflow.unsafe.sandbox_unrestricted():
                active_workflows.labels(workflow_type="IngestDocumentWorkflow").dec()
