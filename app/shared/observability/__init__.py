from shared.observability.logging import (
    configure_logging,
    get_logger,
    trace_id_var,
    workflow_id_var,
    run_id_var,
    activity_type_var,
    request_id_var,
    task_queue_var,
)
from shared.observability.metrics import (
    REGISTRY,
    record_llm_call,
    get_metrics_endpoint,
    workflow_started_total,
    workflow_completed_total,
    workflow_failed_total,
    workflow_duration_seconds,
    activity_duration_seconds,
    activity_completed_total,
    activity_failed_total,
    llm_requests_total,
    llm_request_duration_seconds,
    llm_tokens_input_total,
    llm_tokens_output_total,
    llm_cost_dollars,
    documents_processed_total,
    pdf_extraction_duration_seconds,
    human_review_wait_seconds,
    human_review_started_total,
    human_review_approved_total,
    human_review_revised_total,
    human_review_timeout_total,
    active_workflows,
    active_activities,
    rag_documents_ingested_total,
    rag_chunks_created_total,
    rag_search_requests_total,
    rag_search_duration_seconds,
    rag_search_results_count,
    agent_analysis_requests_total,
    agent_analysis_duration_seconds,
    agent_critic_approvals_total,
    agent_critic_rejections_total,
    agent_citations_total,
)
from shared.observability.tracing import setup_tracing, setup_temporal_runtime
from shared.observability.middleware import ObservabilityMiddleware

# Re-export shared modules
from shared.config import (
    get_aws_config,
    get_temporal_config,
    get_llm_config,
    get_database_config,
    get_app_config,
)
from shared.s3 import (
    parse_s3_path,
    build_s3_uri,
    get_s3_client,
    extract_s3_filename,
    get_markdown_s3_path,
)
