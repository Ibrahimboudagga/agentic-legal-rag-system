from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.exceptions import ApplicationError

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
        RunAgentGraphInput,
        run_agent_graph_activity,
        IngestDocumentInput,
        ingest_document_activity,
    )

log = get_logger("agent_review_workflow")


@dataclass
class AgentReviewWorkflowInput:
    query: str
    s3_paths: list[str]
    max_iterations: int = 2
    max_retrieval_iterations: int = 3
    auto_ingest: bool = True


@dataclass
class AgentReviewWorkflowOutput:
    report: dict
    query: str
    citations: list[dict]
    evidence_count: int
    validation_passed: bool
    status: str


@workflow.defn
class AgentReviewWorkflow:
    """Agentic RAG review workflow.

    Architecture:
        Temporal Workflow
            └── LangGraph Agent Runtime (single Temporal activity)
                    ├── PLANNER
                    │     └── Decompose query into sub-tasks
                    ├── RETRIEVAL AGENT
                    │     ├── ANN Tool (pgvector)
                    │     ├── FTS Tool (PostgreSQL)
                    │     └── Metadata Filter Tool
                    ├── RERANKER
                    │     └── Cross-encoder relevance scoring
                    ├── EVIDENCE STORE
                    │     └── Accumulate validated evidence
                    ├── EVIDENCE VALIDATOR
                    │     ├── PASS → Analysis
                    │     └── FAIL → Retrieve Again (loop)
                    ├── ANALYSIS AGENT
                    │     └── Legal analysis with citations
                    ├── COMPARISON AGENT
                    │     └── Cross-contract risk analysis
                    └── SYNTHESIS
                          └── Final evidence-grounded report

    Human-in-the-Loop via Temporal signals/updates.
    """

    def __init__(self):
        self.status: str = "pending"
        self.report: dict = {}
        self.query: str = ""
        self.citations: list[dict] = []
        self.evidence_count: int = 0
        self.validation_passed: bool = False
        self._review_decision: Optional[str] = None
        self._review_feedback: str = ""
        self._approved_by: str = ""

    @workflow.signal
    async def assign_reviewer(self, name: str = ""):
        self._approved_by = name

    @workflow.update
    async def submit_decision(self, decision: str, feedback: str):
        self._review_decision = decision
        self._review_feedback = feedback
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
            "review_decision": self._review_decision,
            "review_feedback": self._review_feedback,
            "approved_by": self._approved_by,
            "evidence_count": self.evidence_count,
            "validation_passed": self.validation_passed,
        }

    @workflow.query
    def query_fullreport(self):
        return {
            "status": self.status,
            "query": self.query,
            "report": self.report,
            "citations": self.citations,
            "evidence_count": self.evidence_count,
            "validation_passed": self.validation_passed,
            "review_decision": self._review_decision,
            "approved_by": self._approved_by,
        }

    @workflow.run
    async def run(
        self, param: AgentReviewWorkflowInput
    ) -> AgentReviewWorkflowOutput:
        info = workflow.info()
        workflow_id_var.set(info.workflow_id)
        task_queue_var.set(info.task_queue)
        self.query = param.query

        with workflow.unsafe.sandbox_unrestricted():
            workflow_started_total.labels(
                workflow_type="AgentReviewWorkflow",
                task_queue=info.task_queue,
            ).inc()
            active_workflows.labels(workflow_type="AgentReviewWorkflow").inc()

        start_time = workflow.now().timestamp()

        try:
            result = await self._run_inner(param)

            duration = workflow.now().timestamp() - start_time
            with workflow.unsafe.sandbox_unrestricted():
                workflow_completed_total.labels(
                    workflow_type="AgentReviewWorkflow",
                    task_queue=info.task_queue,
                ).inc()
                workflow_duration_seconds.labels(
                    workflow_type="AgentReviewWorkflow"
                ).observe(duration)

            log.info(
                "agent_review_workflow_completed",
                duration_seconds=round(duration, 3),
                final_status=self.status,
            )

            return result

        except Exception as exc:
            duration = workflow.now().timestamp() - start_time
            self.status = "failed"
            with workflow.unsafe.sandbox_unrestricted():
                workflow_failed_total.labels(
                    workflow_type="AgentReviewWorkflow",
                    task_queue=info.task_queue,
                    error_type=type(exc).__name__,
                ).inc()
                workflow_duration_seconds.labels(
                    workflow_type="AgentReviewWorkflow"
                ).observe(duration)

            log.error(
                "agent_review_workflow_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_seconds=round(duration, 3),
            )
            raise

        finally:
            with workflow.unsafe.sandbox_unrestricted():
                active_workflows.labels(workflow_type="AgentReviewWorkflow").dec()

    async def _run_inner(
        self, param: AgentReviewWorkflowInput
    ) -> AgentReviewWorkflowOutput:
        # Phase 1: Auto-ingest documents if not yet in vector store
        if param.auto_ingest and param.s3_paths:
            self.status = "ingesting"
            log.info(
                "auto_ingest_started",
                s3_paths_count=len(param.s3_paths),
            )

            for s3_path in param.s3_paths:
                await workflow.execute_activity(
                    ingest_document_activity,
                    IngestDocumentInput(s3_path=s3_path),
                    schedule_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(seconds=120),
                    start_to_close_timeout=timedelta(minutes=30),
                )

            log.info("auto_ingest_completed")

        # Phase 2: Run the full Agentic RAG pipeline via LangGraph
        self.status = "running_agent_graph"
        log.info(
            "agent_graph_phase_started",
            query_length=len(param.query),
        )

        graph_result = await workflow.execute_activity(
            run_agent_graph_activity,
            RunAgentGraphInput(
                query=param.query,
                s3_paths=param.s3_paths,
                max_iterations=param.max_iterations,
                max_retrieval_iterations=param.max_retrieval_iterations,
            ),
            schedule_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(seconds=120),
            start_to_close_timeout=timedelta(minutes=15),
        )

        self.report = graph_result.synthesis
        self.citations = graph_result.citations
        self.evidence_count = graph_result.evidence_count
        self.validation_passed = graph_result.validation_passed

        log.info(
            "agent_graph_phase_completed",
            evidence_count=self.evidence_count,
            validation_passed=self.validation_passed,
        )

        # Phase 3: Human-in-the-Loop
        for rev in range(param.max_iterations + 1):
            self.status = "human_in_loop"
            self._review_decision = None

            log.info(
                "human_loop_started",
                revision_round=rev + 1,
                max_revisions=param.max_iterations,
            )

            try:
                await workflow.wait_condition(
                    lambda: self._review_decision is not None,
                    timeout=timedelta(days=3),
                )
            except asyncio.TimeoutError:
                log.warning(
                    "human_loop_timeout",
                    revision_round=rev + 1,
                )
                break

            if self._review_decision == "approved":
                log.info(
                    "approved",
                    reviewer=self._approved_by,
                    revision_round=rev + 1,
                )
                break

            # Revise: re-run the agent graph with feedback context
            self.status = "revising"
            log.info(
                "revision_started",
                revision_round=rev + 1,
                feedback_length=len(self._review_feedback),
            )

            revised_query = (
                f"{param.query}\n\n"
                f"REVISER FEEDBACK (incorporate this into your analysis):\n"
                f"{self._review_feedback}"
            )

            graph_result = await workflow.execute_activity(
                run_agent_graph_activity,
                RunAgentGraphInput(
                    query=revised_query,
                    s3_paths=param.s3_paths,
                    max_iterations=param.max_iterations,
                    max_retrieval_iterations=param.max_retrieval_iterations,
                    auto_ingest=False,
                ),
                schedule_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(seconds=120),
                start_to_close_timeout=timedelta(minutes=15),
            )

            self.report = graph_result.synthesis
            self.citations = graph_result.citations
            self.evidence_count = graph_result.evidence_count
            self.validation_passed = graph_result.validation_passed

            log.info(
                "revision_completed",
                revision_round=rev + 1,
            )

        self.status = "completed"

        return AgentReviewWorkflowOutput(
            report=self.report,
            query=self.query,
            citations=self.citations,
            evidence_count=self.evidence_count,
            validation_passed=self.validation_passed,
            status="completed",
        )
