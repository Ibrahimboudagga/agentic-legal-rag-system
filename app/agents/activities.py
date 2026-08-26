from __future__ import annotations

import time
from dataclasses import dataclass

from temporalio import activity

from shared.observability.logging import activity_type_var, get_logger
from shared.observability.metrics import (
    active_activities,
    activity_completed_total,
    activity_duration_seconds,
    activity_failed_total,
    agent_analysis_requests_total,
    agent_analysis_duration_seconds,
    rag_documents_ingested_total,
    rag_chunks_created_total,
)
from ingestion.pipeline import ingest_document, IngestionResult
from shared.database import init_db

log = get_logger("agent_activities")


@dataclass
class IngestDocumentInput:
    s3_path: str
    batch_size: int = 2
    max_chunk_tokens: int = 512


@dataclass
class IngestDocumentOutput:
    document_id: str
    s3_path: str
    total_chunks: int
    total_pages: int
    duration_seconds: float


@dataclass
class RunAgentGraphInput:
    query: str
    s3_paths: list[str]
    top_k: int = 8
    max_iterations: int = 2
    max_retrieval_iterations: int = 3


@dataclass
class RunAgentGraphOutput:
    synthesis: dict
    analysis: dict
    comparison: dict
    evidence_count: int
    citations: list[dict]
    validation_passed: bool
    status: str


@activity.defn
async def ingest_document_activity(param: IngestDocumentInput) -> IngestDocumentOutput:
    """Temporal activity: ingest a document into the vector store."""
    activity_type_var.set("ingest_document")
    start = time.monotonic()
    active_activities.labels(activity_type="ingest_document").inc()

    try:
        log.info("ingestion_started", s3_path=param.s3_path)
        activity.heartbeat({"current_step": "starting_ingestion"})

        await init_db()

        result: IngestionResult = await ingest_document(
            s3_path=param.s3_path,
            batch_size=param.batch_size,
            max_chunk_tokens=param.max_chunk_tokens,
        )

        duration = time.monotonic() - start
        activity_duration_seconds.labels(
            activity_type="ingest_document", task_queue=activity.info().task_queue
        ).observe(duration)
        activity_completed_total.labels(
            activity_type="ingest_document", task_queue=activity.info().task_queue
        ).inc()
        rag_documents_ingested_total.labels(status="success").inc()
        rag_chunks_created_total.inc(result.total_chunks)

        log.info(
            "ingestion_completed",
            s3_path=param.s3_path,
            total_chunks=result.total_chunks,
            duration_seconds=round(duration, 3),
        )

        return IngestDocumentOutput(
            document_id=result.document_id,
            s3_path=result.s3_path,
            total_chunks=result.total_chunks,
            total_pages=result.total_pages,
            duration_seconds=result.duration_seconds,
        )

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="ingest_document",
            task_queue=activity.info().task_queue,
            error_type=type(exc).__name__,
        ).inc()
        rag_documents_ingested_total.labels(status="failed").inc()
        log.error(
            "ingestion_failed",
            s3_path=param.s3_path,
            error=str(exc),
            error_type=type(exc).__name__,
            duration_seconds=round(duration, 3),
        )
        raise

    finally:
        active_activities.labels(activity_type="ingest_document").dec()


@activity.defn
async def run_agent_graph_activity(param: RunAgentGraphInput) -> RunAgentGraphOutput:
    """Temporal activity: run the full Agentic RAG LangGraph pipeline.

    Executes the complete workflow:
    PLANNER -> RETRIEVAL -> RERANKER -> EVIDENCE BUILD -> EVIDENCE VALIDATE
    -> (loop or) -> ANALYSIS -> (COMPARISON) -> SYNTHESIS

    This runs entirely within a single Temporal activity. The LangGraph
    state machine handles the internal loops (retrieval retry, evidence
    validation).
    """
    activity_type_var.set("run_agent_graph")
    start = time.monotonic()
    active_activities.labels(activity_type="run_agent_graph").inc()
    agent_analysis_requests_total.labels(agent_type="full_pipeline").inc()

    try:
        log.info(
            "agent_graph_started",
            query_length=len(param.query),
            s3_paths_count=len(param.s3_paths),
        )
        activity.heartbeat({"current_step": "initializing_graph"})

        from agents.graph import get_agent_graph, reset_evidence_store
        from agents.state import AgentState

        reset_evidence_store()
        graph = get_agent_graph()

        initial_state: AgentState = {
            "query": param.query,
            "objective": param.query,
            "s3_paths": param.s3_paths,
            "top_k": param.top_k,
            "max_iterations": param.max_iterations,
            "plan": {},
            "sub_queries": [],
            "comparison_needed": len(param.s3_paths) > 1,
            "analysis_focus": [],
            "required_capabilities": [],
            "retrieval_strategy": "focused",
            "retrieval_queries": [],
            "retrieval_results": [],
            "tools_used": [],
            "retrieval_iteration": 0,
            "max_retrieval_iterations": param.max_retrieval_iterations,
            "reranked_chunks": [],
            "evidence": [],
            "evidence_citations": [],
            "evidence_count": 0,
            "validation_result": {},
            "validation_attempts": 0,
            "needs_retrieval": False,
            "missing_information": [],
            "_evidence_store": None,
            "analysis": {},
            "comparison": {},
            "synthesis": {},
            "status": "started",
            "error": None,
            "iteration": 0,
        }

        activity.heartbeat({"current_step": "running_agent_graph"})

        result = await graph.ainvoke(initial_state)
        try:
            from repositories.review_results import persist_agent_run

            await persist_agent_run(
                workflow_id=activity.info().workflow_id,
                query=param.query,
                analysis=result.get("analysis", {}),
                synthesis=result.get("synthesis", {}),
                evidence=result.get("evidence", []),
                citations=result.get("evidence_citations", []),
            )
        except Exception as exc:
            log.warning(
                "agent_graph_persistence_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

        duration = time.monotonic() - start
        activity_duration_seconds.labels(
            activity_type="run_agent_graph", task_queue=activity.info().task_queue
        ).observe(duration)
        agent_analysis_duration_seconds.labels(agent_type="full_pipeline").observe(duration)
        activity_completed_total.labels(
            activity_type="run_agent_graph", task_queue=activity.info().task_queue
        ).inc()

        log.info(
            "agent_graph_completed",
            query_length=len(param.query),
            status=result.get("status", "unknown"),
            evidence_count=result.get("evidence_count", 0),
            duration_seconds=round(duration, 3),
        )

        validation = result.get("validation_result", {})

        return RunAgentGraphOutput(
            synthesis=result.get("synthesis", {}),
            analysis=result.get("analysis", {}),
            comparison=result.get("comparison", {}),
            evidence_count=result.get("evidence_count", 0),
            citations=result.get("evidence_citations", []),
            validation_passed=validation.get("passed", False),
            status=result.get("status", "completed"),
        )

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="run_agent_graph",
            task_queue=activity.info().task_queue,
            error_type=type(exc).__name__,
        ).inc()
        log.error(
            "agent_graph_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            duration_seconds=round(duration, 3),
        )
        raise

    finally:
        active_activities.labels(activity_type="run_agent_graph").dec()
