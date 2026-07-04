import time
from dataclasses import dataclass
from datetime import timedelta

import json_repair
from temporalio import workflow
from temporalio.common import RetryPolicy

from shared.observability.logging import get_logger, workflow_id_var
from shared.observability.metrics import (
    active_workflows,
    workflow_completed_total,
    workflow_duration_seconds,
    workflow_failed_total,
    workflow_started_total,
)

with workflow.unsafe.imports_passed_through():
    from activities import extract_pdf, call_llm, extractpdfinput, calllminput
    import prompts

log = get_logger("child_workflow")


@dataclass
class pdfsummaryinput:
    s3_pdf_path: str


@dataclass
class pdfsummaryoutput:
    s3_md_path: str
    summary: str
    key_risks: str


DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)


@workflow.defn
class pdfsummaryworkflow:
    @workflow.run
    async def run(self, param: pdfsummaryinput) -> pdfsummaryoutput:
        start_time = time.time()
        info = workflow.info()

        workflow_id_var.set(info.workflow_id)
        workflow_started_total.labels(
            workflow_type="pdfsummaryworkflow",
            task_queue=info.task_queue,
        ).inc()
        active_workflows.labels(workflow_type="pdfsummaryworkflow").inc()

        log.info(
            "child_workflow_started",
            workflow_type="pdfsummaryworkflow",
            s3_pdf_path=param.s3_pdf_path,
        )

        try:
            extract_start = time.monotonic()
            extract_md = await workflow.execute_activity(
                extract_pdf,
                extractpdfinput(s3_path=param.s3_pdf_path),
                retry_policy=DEFAULT_RETRY_POLICY,
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(seconds=120),
            )
            extract_duration = time.monotonic() - extract_start

            log.info(
                "pdf_extraction_completed",
                s3_pdf_path=param.s3_pdf_path,
                pages=extract_md.pages_num,
                duration_seconds=round(extract_duration, 3),
            )

            llm_start = time.monotonic()
            llm_call = await workflow.execute_activity(
                call_llm,
                calllminput(
                    prompt=prompts._SUMMARY_PROMPT.format(
                        text=extract_md.markdown_txt[:5_000]
                    ),
                ),
                retry_policy=DEFAULT_RETRY_POLICY,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=120),
            )
            llm_duration = time.monotonic() - llm_start

            parsed_output = json_repair.loads(llm_call.response)
            if hasattr(extract_md, "s3_md_path"):
                s3_md_path = extract_md.s3_md_path
            else:
                s3_md_path = extract_md.s3_path

            duration = time.time() - start_time
            workflow_completed_total.labels(
                workflow_type="pdfsummaryworkflow",
                task_queue=info.task_queue,
            ).inc()
            workflow_duration_seconds.labels(
                workflow_type="pdfsummaryworkflow"
            ).observe(duration)

            log.info(
                "child_workflow_completed",
                s3_pdf_path=param.s3_pdf_path,
                duration_seconds=round(duration, 3),
                extract_duration_seconds=round(extract_duration, 3),
                llm_duration_seconds=round(llm_duration, 3),
                pages=extract_md.pages_num,
            )

            return pdfsummaryoutput(
                s3_md_path=s3_md_path,
                summary=parsed_output["summary"],
                key_risks=parsed_output["key_risks"],
            )

        except Exception as exc:
            duration = time.time() - start_time
            workflow_failed_total.labels(
                workflow_type="pdfsummaryworkflow",
                task_queue=info.task_queue,
                error_type=type(exc).__name__,
            ).inc()
            workflow_duration_seconds.labels(
                workflow_type="pdfsummaryworkflow"
            ).observe(duration)

            log.error(
                "child_workflow_failed",
                s3_pdf_path=param.s3_pdf_path,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_seconds=round(duration, 3),
            )
            raise

        finally:
            active_workflows.labels(workflow_type="pdfsummaryworkflow").dec()
