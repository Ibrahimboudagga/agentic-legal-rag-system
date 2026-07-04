import asyncio
import json
import time

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from json_repair import json_repair
from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ParentClosePolicy

from shared.observability.logging import (
    get_logger,
    task_queue_var,
    workflow_id_var,
)
from shared.observability.metrics import (
    active_workflows,
    human_review_approved_total,
    human_review_revised_total,
    human_review_started_total,
    human_review_timeout_total,
    human_review_wait_seconds,
    workflow_completed_total,
    workflow_duration_seconds,
    workflow_failed_total,
    workflow_started_total,
)

with workflow.unsafe.imports_passed_through():
    from activities import call_llm, calllminput
    from child_worker import pdfsummaryworkflow, pdfsummaryinput
    import prompts


log = get_logger("parent_workflow")


@dataclass
class ContractReviewerWorkflowinput:
    s3_paths: list[str]
    max_revesion: int = 2


@dataclass
class ContractReviewerWorkflowoutput:
    report: str
    sources: str
    approved_by: str


@workflow.defn
class ContractReviewerWorkflow:
    def __init__(self):
        self.status: str = "processing"
        self.summuries: list = []
        self.report: str = ""

        self.review_decision: Optional[str] = None
        self.review_feedback: str = ""
        self.approved_by: str = ""

        self._start_time: float = 0.0
        self._review_wait_start: float = 0.0

    @workflow.signal
    async def assign_reviewer(self, name: str = ""):
        self.approved_by = name

    @workflow.update
    async def submit_decision(self, decision: str, feedback: str):
        self.review_decision = decision
        self.review_feedback = feedback
        return f"decision {decision} recorded"

    @submit_decision.validator
    async def validate_decision(self, decision: str, feedback: str):
        valid_decisions = ["approved", "revise"]
        if decision not in valid_decisions:
            raise ApplicationError(f"invalid decision {decision}")

        if decision == "revise" and not feedback:
            raise ApplicationError("feedback is required for revise decision")
        return True

    @workflow.query
    def query_status(self):
        return {
            "status": self.status,
            "review_decision": self.review_decision,
            "review_feedback": self.review_feedback,
            "approved_by": self.approved_by,
        }

    @workflow.query
    def query_fullreport(self):
        return {
            "status": self.status,
            "review_decision": self.review_decision,
            "review_feedback": self.review_feedback,
            "approved_by": self.approved_by,
            "summuries": self.summuries,
            "report": json.dumps(self.report, ensure_ascii=False, indent=4),
            "sources": [s["s3_md_path"] for s in self.summuries],
        }

    @workflow.run
    async def run(
        self, param: ContractReviewerWorkflowinput
    ) -> ContractReviewerWorkflowoutput:
        self._start_time = time.time()
        info = workflow.info()

        workflow_id_var.set(info.workflow_id)
        task_queue_var.set(info.task_queue)

        workflow_started_total.labels(
            workflow_type="ContractReviewerWorkflow",
            task_queue=info.task_queue,
        ).inc()
        active_workflows.labels(workflow_type="ContractReviewerWorkflow").inc()

        log.info(
            "workflow_started",
            workflow_type="ContractReviewerWorkflow",
            s3_paths_count=len(param.s3_paths),
            max_revision=param.max_revesion,
        )

        try:
            result = await self._run_inner(param)

            duration = time.time() - self._start_time
            workflow_completed_total.labels(
                workflow_type="ContractReviewerWorkflow",
                task_queue=info.task_queue,
            ).inc()
            workflow_duration_seconds.labels(
                workflow_type="ContractReviewerWorkflow"
            ).observe(duration)

            log.info(
                "workflow_completed",
                duration_seconds=round(duration, 3),
                final_status=self.status,
                approved_by=self.approved_by,
            )

            return result

        except Exception as exc:
            duration = time.time() - self._start_time
            workflow_failed_total.labels(
                workflow_type="ContractReviewerWorkflow",
                task_queue=info.task_queue,
                error_type=type(exc).__name__,
            ).inc()
            workflow_duration_seconds.labels(
                workflow_type="ContractReviewerWorkflow"
            ).observe(duration)

            log.error(
                "workflow_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_seconds=round(duration, 3),
            )
            raise

        finally:
            active_workflows.labels(workflow_type="ContractReviewerWorkflow").dec()

    async def _run_inner(
        self, param: ContractReviewerWorkflowinput
    ) -> ContractReviewerWorkflowoutput:
        self.status = "extracting"
        workflow.logger.info(f"start extracting pdfs from {param.s3_paths}")

        workflow_id = workflow.info().workflow_id
        workflow_task_queue = workflow.info().task_queue

        log.info(
            "fan_out_started",
            child_count=len(param.s3_paths),
            workflow_id=workflow_id,
        )

        raw_results = await asyncio.gather(
            *[
                workflow.execute_child_workflow(
                    pdfsummaryworkflow.run,
                    pdfsummaryinput(s3_pdf_path=s3_path),
                    id=f"{workflow_id}-summary-{idx}",
                    task_queue=workflow_task_queue,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
                for idx, s3_path in enumerate(param.s3_paths)
            ],
            return_exceptions=True,
        )

        succeeded = 0
        failed = 0
        for idx, result in enumerate(raw_results):
            if isinstance(result, Exception):
                failed += 1
                workflow.logger.warning(
                    f"child workflow {idx} failed with {result}"
                )
                log.warning(
                    "child_workflow_failed",
                    child_index=idx,
                    s3_path=param.s3_paths[idx],
                    error=str(result),
                )
            else:
                succeeded += 1
                self.summuries.append(
                    {
                        "s3_md_path": result.s3_md_path,
                        "summary": result.summary,
                        "key_risks": result.key_risks,
                    }
                )

        log.info(
            "fan_out_completed",
            succeeded=succeeded,
            failed=failed,
            total=len(param.s3_paths),
        )

        if len(self.summuries) == 0:
            raise ApplicationError("no summaries generated")

        self.status = "synthesizing"
        synthesis_start = time.monotonic()
        workflow.logger.info(
            f"synthesizing summaries from {len(self.summuries)} contracts"
        )

        log.info("synthesis_started", contract_count=len(self.summuries))

        llm_result = await workflow.execute_activity(
            call_llm,
            calllminput(
                prompt=prompts._SYNTHESIS_PROMPT.format(
                    n=len(self.summuries),
                    summaries="\n\n".join(
                        f"contract{i+1}:\n{s['summary']}\nkey_risk:{s['key_risks']}"
                        for i, s in enumerate(self.summuries)
                    ),
                )
            ),
            schedule_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=120),
            start_to_close_timeout=timedelta(minutes=5),
        )
        self.report = json_repair.loads(llm_result.response)

        synthesis_duration = time.monotonic() - synthesis_start
        log.info(
            "synthesis_completed",
            duration_seconds=round(synthesis_duration, 3),
            report_keys=list(self.report.keys()) if isinstance(self.report, dict) else [],
        )

        for rev in range(param.max_revesion + 1):
            self.status = "human_in_loop"
            self.review_decision = None

            self._review_wait_start = time.time()
            human_review_started_total.inc()

            log.info(
                "human_review_started",
                revision_round=rev + 1,
                max_revisions=param.max_revesion,
            )

            try:
                await workflow.wait_condition(
                    lambda: self.review_decision is not None,
                    timeout=timedelta(days=3),
                )
            except asyncio.TimeoutError:
                wait_duration = time.time() - self._review_wait_start
                human_review_timeout_total.inc()
                human_review_wait_seconds.observe(wait_duration)
                workflow.logger.warning(
                    "Review timed out after 3 days — auto-completing"
                )
                log.warning(
                    "human_review_timeout",
                    wait_seconds=round(wait_duration, 3),
                    revision_round=rev + 1,
                )
                break

            wait_duration = time.time() - self._review_wait_start
            human_review_wait_seconds.observe(wait_duration)

            if self.review_decision == "APPROVED":
                human_review_approved_total.inc()
                workflow.logger.info(
                    f"review approved after {rev+1} revision(s) {self.approved_by}"
                )
                log.info(
                    "human_review_approved",
                    reviewer=self.approved_by,
                    wait_seconds=round(wait_duration, 3),
                    revision_round=rev + 1,
                )
                break

            human_review_revised_total.inc()
            self.status = "revising"
            workflow.logger.info(f"revising after {rev+1} revision(s)")

            log.info(
                "revision_started",
                revision_round=rev + 1,
                feedback_length=len(self.review_feedback),
            )

            llm_prompt = prompts._REVISION_PROMPT.format(
                report=json.dumps(self.report, ensure_ascii=False, indent=4),
                feedback=self.review_feedback,
            )
            revised_report = await workflow.execute_activity(
                call_llm,
                calllminput(prompt=llm_prompt),
                schedule_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=120),
                start_to_close_timeout=timedelta(minutes=5),
            )
            self.report = json_repair.loads(revised_report.response)

            log.info(
                "revision_completed",
                revision_round=rev + 1,
            )

        self.status = "completed"

        return ContractReviewerWorkflowoutput(
            report=self.report,
            sources=[s["s3_md_path"] for s in self.summuries],
            approved_by=self.approved_by,
        )
