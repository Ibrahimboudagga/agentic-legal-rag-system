from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_aws_config_required_fields():
    os.environ["AWS_ACCESS_KEY_ID"] = "test_key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test_secret"
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["AWS_S3_ENDPOINT_URL"] = "https://s3.test.com"
    os.environ["S3_BUCKET"] = "test-bucket"

    from shared.config import AWSConfig

    config = AWSConfig()
    assert config.access_key_id == "test_key"
    assert config.secret_access_key == "test_secret"
    assert config.region == "us-east-1"
    assert config.endpoint_url == "https://s3.test.com"
    assert config.bucket == "test-bucket"


def test_temporal_config_defaults():
    os.environ.pop("TEMPORAL_HOST", None)
    os.environ.pop("TEMPORAL_NAMESPACE", None)
    os.environ.pop("TEMPORAL_PDF_PROCESS_TASK_QUEUE", None)
    os.environ.pop("TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE", None)

    from shared.config import TemporalConfig

    config = TemporalConfig()
    assert config.host == "localhost:7233"
    assert config.namespace == "default"
    assert config.pdf_task_queue == "pdf-pipeline-queue"
    assert config.contract_review_task_queue == "contract-review-queue"


def test_llm_config_custom_values():
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["LLM_MODEL_NAME"] = "custom-model"
    os.environ["LLM_MAX_TOKENS"] = "4000"

    from shared.config import LLMConfig

    config = LLMConfig()
    assert config.api_key == "test-key"
    assert config.model == "custom-model"
    assert config.max_tokens == 4000


def test_database_config_defaults():
    from shared.config import DatabaseConfig

    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("DATABASE_SYNC_URL", None)
    os.environ.pop("DB_POOL_SIZE", None)

    config = DatabaseConfig()
    assert "postgresql" in config.url
    assert config.pool_size == 5


def test_app_config_defaults():
    from shared.config import AppConfig

    config = AppConfig()
    assert config.temp_dir == "/tmp/pdf-pipeline"
    assert config.log_level == "INFO"
