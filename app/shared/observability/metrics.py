from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

# ── WORKFLOW METRICS ──────────────────────────────────────────────

workflow_started_total = Counter(
    "contract_review_workflow_started_total",
    "Total workflows started",
    ["workflow_type", "task_queue"],
    registry=REGISTRY,
)

workflow_completed_total = Counter(
    "contract_review_workflow_completed_total",
    "Total workflows completed successfully",
    ["workflow_type", "task_queue"],
    registry=REGISTRY,
)

workflow_failed_total = Counter(
    "contract_review_workflow_failed_total",
    "Total workflows that failed",
    ["workflow_type", "task_queue", "error_type"],
    registry=REGISTRY,
)

workflow_duration_seconds = Histogram(
    "contract_review_workflow_duration_seconds",
    "Workflow end-to-end duration",
    ["workflow_type"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
    registry=REGISTRY,
)

# ── ACTIVITY METRICS ──────────────────────────────────────────────

activity_duration_seconds = Histogram(
    "contract_review_activity_duration_seconds",
    "Activity execution duration",
    ["activity_type", "task_queue"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
    registry=REGISTRY,
)

activity_completed_total = Counter(
    "contract_review_activity_completed_total",
    "Total activities completed",
    ["activity_type", "task_queue"],
    registry=REGISTRY,
)

activity_failed_total = Counter(
    "contract_review_activity_failed_total",
    "Total activities that failed",
    ["activity_type", "task_queue", "error_type"],
    registry=REGISTRY,
)

# ── LLM METRICS ───────────────────────────────────────────────────

llm_requests_total = Counter(
    "contract_review_llm_requests_total",
    "Total LLM API requests",
    ["model", "operation"],
    registry=REGISTRY,
)

llm_request_duration_seconds = Histogram(
    "contract_review_llm_request_duration_seconds",
    "LLM API request duration",
    ["model", "operation"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
    registry=REGISTRY,
)

llm_tokens_input_total = Counter(
    "contract_review_llm_tokens_input_total",
    "Total LLM input tokens consumed",
    ["model"],
    registry=REGISTRY,
)

llm_tokens_output_total = Counter(
    "contract_review_llm_tokens_output_total",
    "Total LLM output tokens consumed",
    ["model"],
    registry=REGISTRY,
)

llm_cost_dollars = Counter(
    "contract_review_llm_cost_dollars",
    "Estimated LLM cost in USD (configurable via env vars)",
    ["model"],
    registry=REGISTRY,
)

# ── DOCUMENT METRICS ──────────────────────────────────────────────

documents_processed_total = Counter(
    "contract_review_documents_processed_total",
    "Total documents processed",
    ["status"],
    registry=REGISTRY,
)

pdf_extraction_duration_seconds = Histogram(
    "contract_review_pdf_extraction_duration_seconds",
    "PDF extraction to markdown duration",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
    registry=REGISTRY,
)

# ── HUMAN-IN-THE-LOOP METRICS ────────────────────────────────────

human_review_wait_seconds = Histogram(
    "contract_review_human_review_wait_seconds",
    "Time waiting for human reviewer decision",
    buckets=[60, 300, 600, 1800, 3600, 86400, 172800, 259200],
    registry=REGISTRY,
)

human_review_started_total = Counter(
    "contract_review_human_review_started_total",
    "Total human reviews initiated",
    registry=REGISTRY,
)

human_review_approved_total = Counter(
    "contract_review_human_review_approved_total",
    "Total human reviews approved",
    registry=REGISTRY,
)

human_review_revised_total = Counter(
    "contract_review_human_review_revised_total",
    "Total human reviews requesting revision",
    registry=REGISTRY,
)

human_review_timeout_total = Counter(
    "contract_review_human_review_timeout_total",
    "Total human reviews that timed out",
    registry=REGISTRY,
)

# ── WORKER METRICS ────────────────────────────────────────────────

active_workflows = Gauge(
    "contract_review_active_workflows",
    "Number of currently active workflows",
    ["workflow_type"],
    registry=REGISTRY,
)

active_activities = Gauge(
    "contract_review_active_activities",
    "Number of currently running activities",
    ["activity_type"],
    registry=REGISTRY,
)

# ── RAG / VECTOR STORE METRICS ────────────────────────────────────

rag_documents_ingested_total = Counter(
    "contract_review_rag_documents_ingested_total",
    "Total documents ingested into vector store",
    ["status"],
    registry=REGISTRY,
)

rag_chunks_created_total = Counter(
    "contract_review_rag_chunks_created_total",
    "Total chunks created during ingestion",
    registry=REGISTRY,
)

rag_search_requests_total = Counter(
    "contract_review_rag_search_requests_total",
    "Total hybrid search requests",
    ["search_type"],
    registry=REGISTRY,
)

rag_search_duration_seconds = Histogram(
    "contract_review_rag_search_duration_seconds",
    "Hybrid search duration",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)

rag_search_results_count = Histogram(
    "contract_review_rag_search_results_count",
    "Number of results returned by search",
    buckets=[0, 1, 2, 5, 10, 20, 50],
    registry=REGISTRY,
)

# ── AGENT METRICS ─────────────────────────────────────────────────

agent_analysis_requests_total = Counter(
    "contract_review_agent_analysis_requests_total",
    "Total agent analysis requests",
    ["agent_type"],
    registry=REGISTRY,
)

agent_analysis_duration_seconds = Histogram(
    "contract_review_agent_analysis_duration_seconds",
    "Agent analysis duration",
    ["agent_type"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
    registry=REGISTRY,
)

agent_execution_count = Counter(
    "contract_review_agent_execution_count",
    "Agent node executions",
    ["agent_name", "status"],
    registry=REGISTRY,
)

agent_latency_seconds = Histogram(
    "contract_review_agent_latency_seconds",
    "Agent node latency",
    ["agent_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
    registry=REGISTRY,
)

retrieval_iterations_total = Counter(
    "contract_review_retrieval_iterations_total",
    "Retrieval loop iterations",
    ["status"],
    registry=REGISTRY,
)

evidence_validation_failures_total = Counter(
    "contract_review_evidence_validation_failures_total",
    "Evidence validation failures",
    ["issue_type"],
    registry=REGISTRY,
)

tool_calls_total = Counter(
    "contract_review_tool_calls_total",
    "Agent tool calls",
    ["tool_name", "status"],
    registry=REGISTRY,
)

agent_critic_approvals_total = Counter(
    "contract_review_agent_critic_approvals_total",
    "Total critic approvals",
    registry=REGISTRY,
)

agent_critic_rejections_total = Counter(
    "contract_review_agent_critic_rejections_total",
    "Total critic rejections",
    registry=REGISTRY,
)

agent_citations_total = Counter(
    "contract_review_agent_citations_total",
    "Total citations used in agent reports",
    registry=REGISTRY,
)


# ── HELPERS ───────────────────────────────────────────────────────


def record_llm_call(
    model: str,
    operation: str,
    duration: float,
    tokens_in: int,
    tokens_out: int,
    input_price_per_1k: float,
    output_price_per_1k: float,
) -> None:
    llm_requests_total.labels(model=model, operation=operation).inc()
    llm_request_duration_seconds.labels(model=model, operation=operation).observe(
        duration
    )
    llm_tokens_input_total.labels(model=model).inc(tokens_in)
    llm_tokens_output_total.labels(model=model).inc(tokens_out)
    cost = (tokens_in / 1000 * input_price_per_1k) + (
        tokens_out / 1000 * output_price_per_1k
    )
    llm_cost_dollars.labels(model=model).inc(cost)


def get_metrics_endpoint() -> bytes:
    return generate_latest(REGISTRY)
