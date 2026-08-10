from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from mypy_boto3_s3 import S3Client

from shared.config import AWSConfig, get_aws_config


def parse_s3_path(path: str) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    s3_path_no_scheme = path.replace("s3://", "")
    bucket, _, key = s3_path_no_scheme.partition("/")
    return bucket, key


def build_s3_uri(bucket: str, key: str) -> str:
    """Build s3://bucket/key URI."""
    return f"s3://{bucket}/{key}"


def get_s3_client(config: AWSConfig | None = None) -> S3Client:
    """Create an S3 client from config."""
    cfg = config or get_aws_config()
    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        aws_access_key_id=cfg.access_key_id,
        aws_secret_access_key=cfg.secret_access_key,
        region_name=cfg.region,
    )


def extract_s3_filename(s3_path: str) -> str:
    """Extract filename from S3 path."""
    _, key = parse_s3_path(s3_path)
    return key.rsplit("/", 1)[-1]


def get_markdown_s3_path(pdf_s3_path: str) -> str:
    """Derive the S3 path for the markdown output from a PDF path."""
    bucket, key = parse_s3_path(pdf_s3_path)
    md_key = key.rsplit(".", 1)[0] + ".md"
    return build_s3_uri(bucket, md_key)
