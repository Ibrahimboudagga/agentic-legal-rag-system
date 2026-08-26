from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class AWSConfig:
    access_key_id: str = field(default_factory=lambda: os.environ["AWS_ACCESS_KEY_ID"])
    secret_access_key: str = field(default_factory=lambda: os.environ["AWS_SECRET_ACCESS_KEY"])
    region: str = field(default_factory=lambda: os.environ["AWS_REGION"])
    endpoint_url: str = field(default_factory=lambda: os.environ["AWS_S3_ENDPOINT_URL"])
    bucket: str = field(default_factory=lambda: os.environ["S3_BUCKET"])


@dataclass(frozen=True)
class TemporalConfig:
    host: str = field(default_factory=lambda: os.getenv("TEMPORAL_HOST", "localhost:7233"))
    namespace: str = field(default_factory=lambda: os.getenv("TEMPORAL_NAMESPACE", "default"))
    pdf_task_queue: str = field(default_factory=lambda: os.getenv("TEMPORAL_PDF_PROCESS_TASK_QUEUE", "pdf-pipeline-queue"))
    contract_review_task_queue: str = field(default_factory=lambda: os.getenv("TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE", "contract-review-queue"))


@dataclass(frozen=True)
class LLMConfig:
    api_key: str = field(default_factory=lambda: os.environ["OPENROUTER_API_KEY"])
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash"))
    base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"))
    input_price_per_1k: float = field(default_factory=lambda: float(os.getenv("LLM_INPUT_PRICE_PER_1K_TOKENS", "0.00014")))
    output_price_per_1k: float = field(default_factory=lambda: float(os.getenv("LLM_OUTPUT_PRICE_PER_1K_TOKENS", "0.00028")))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "8000")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "3")))
    retry_delay_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_RETRY_DELAY_SECONDS", "1.0")))
    planner_model: str = field(default_factory=lambda: os.getenv("PLANNER_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")))
    query_rewrite_model: str = field(default_factory=lambda: os.getenv("QUERY_REWRITE_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")))
    validator_model: str = field(default_factory=lambda: os.getenv("VALIDATOR_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")))
    analysis_model: str = field(default_factory=lambda: os.getenv("ANALYSIS_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")))
    synthesis_model: str = field(default_factory=lambda: os.getenv("SYNTHESIS_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")))


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/legal_rag"))
    sync_url: str = field(default_factory=lambda: os.getenv("DATABASE_SYNC_URL", "postgresql://postgres:postgres@localhost:5432/legal_rag"))
    pool_size: int = field(default_factory=lambda: int(os.getenv("DB_POOL_SIZE", "5")))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "384")))


@dataclass(frozen=True)
class RAGConfig:
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    reranker_model: str = field(default_factory=lambda: os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"))
    retrieval_top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K_RETRIEVAL", "20")))
    rerank_top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K_RERANK", "8")))
    max_retrieval_iterations: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIEVAL_ITERATIONS", "3")))
    semantic_weight: float = field(default_factory=lambda: float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.5")))
    keyword_weight: float = field(default_factory=lambda: float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.3")))
    metadata_weight: float = field(default_factory=lambda: float(os.getenv("HYBRID_METADATA_WEIGHT", "0.2")))
    similarity_threshold: float = field(default_factory=lambda: float(os.getenv("HYBRID_SIMILARITY_THRESHOLD", "0.25")))


@dataclass(frozen=True)
class AppConfig:
    temp_dir: str = field(default_factory=lambda: os.getenv("TEMP_DIR", "/tmp/pdf-pipeline"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    otlp_endpoint: str = field(default_factory=lambda: os.getenv("OTEL_ENDPOINT", "http://localhost:4317"))
    loki_url: str | None = field(default_factory=lambda: os.getenv("LOKI_URL"))


@lru_cache(maxsize=1)
def get_aws_config() -> AWSConfig:
    return AWSConfig()


@lru_cache(maxsize=1)
def get_temporal_config() -> TemporalConfig:
    return TemporalConfig()


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
    return LLMConfig()


@lru_cache(maxsize=1)
def get_database_config() -> DatabaseConfig:
    return DatabaseConfig()


@lru_cache(maxsize=1)
def get_rag_config() -> RAGConfig:
    return RAGConfig()


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return AppConfig()
