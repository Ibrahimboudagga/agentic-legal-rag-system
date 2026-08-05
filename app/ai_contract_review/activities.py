import asyncio
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import boto3
import fitz
import pymupdf4llm
from dotenv import load_dotenv
from openai import OpenAI
from temporalio import activity

from shared.observability.logging import (
    activity_type_var,
    get_logger,
    workflow_id_var,
)
from shared.observability.metrics import (
    active_activities,
    activity_completed_total,
    activity_duration_seconds,
    activity_failed_total,
    documents_processed_total,
    llm_tokens_input_total,
    llm_tokens_output_total,
    pdf_extraction_duration_seconds,
    record_llm_call,
)

load_dotenv()

log = get_logger("activities")

AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_S3_ENDPOINT_URL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
TEMP_DIR = os.environ["TEMP_DIR"]

os.makedirs(TEMP_DIR, exist_ok=True)

LLM_MODEL = os.getenv("LLM_MODEL_NAME", "deepseek/deepseek-v4-flash")
LLM_INPUT_PRICE_PER_1K = float(os.getenv("LLM_INPUT_PRICE_PER_1K_TOKENS", "0.00014"))
LLM_OUTPUT_PRICE_PER_1K = float(os.getenv("LLM_OUTPUT_PRICE_PER_1K_TOKENS", "0.00028"))


@dataclass
class extractpdfinput:
    s3_path: str
    batch_size: int = 2


@dataclass
class extractpdfoutput:
    s3_md_path: str
    markdown_txt: str
    pages_num: int


@dataclass
class calllminput:
    prompt: str


@dataclass
class calllmoutput:
    response: str


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=AWS_S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )


def parse_s3_path(path: str):
    s3_path_no_scheme = path.replace("s3://", "")
    bucket, _, key = s3_path_no_scheme.partition("/")
    return bucket, key


@activity.defn
async def extract_pdf(param: extractpdfinput) -> extractpdfoutput:
    activity_type_var.set("extract_pdf")
    start = time.monotonic()
    active_activities.labels(activity_type="extract_pdf").inc()

    try:
        log.info("pdf_extraction_started", s3_path=param.s3_path)

        activity.heartbeat(
            {
                "current_step": "downloading pdf",
                "page_progress": 0,
                "start_time": datetime.now().isoformat(),
            }
        )
        client = get_s3_client()
        bucket, key = parse_s3_path(param.s3_path)
        filename = Path(key).name
        local_path = Path(TEMP_DIR) / filename

        await asyncio.to_thread(client.download_file, bucket, key, str(local_path))
        doc = await asyncio.to_thread(fitz.open, local_path)
        total_pages = doc.page_count
        activity.logger.info(f"Total pages: {total_pages}")

        total_num_batches = math.ceil(total_pages / param.batch_size)
        all_text_chunks = []
        for i in range(total_num_batches):
            start_page = i * param.batch_size
            end_page = min((i + 1) * param.batch_size, total_pages)
            activity.logger.info(f"Processing pages {start_page} to {end_page}")
            batch_md = await asyncio.to_thread(
                pymupdf4llm.to_markdown,
                doc,
                from_page=start_page,
                to_page=end_page,
            )

            all_text_chunks.append(batch_md)

            activity.heartbeat(
                {
                    "current_step": "extracting pdf to markdown",
                    "page_progress": end_page,
                    "start_time": datetime.now().isoformat(),
                    "s3_path": param.s3_path,
                    "pages_processed": end_page,
                    "total_pages": total_pages,
                    "progressed_batch": round(end_page / total_pages * 100, 2),
                    "total_batches": total_num_batches,
                    "current_batch": i + 1,
                }
            )

        full_markdown = "\n\n".join(all_text_chunks)
        activity.heartbeat(
            {
                "current_step": "pdf extracted to markdown",
                "start_time": datetime.now().isoformat(),
                "s3_path": param.s3_path,
                "total_pages": total_pages,
                "total_batches": total_num_batches,
            }
        )

        duration = time.monotonic() - start
        activity_duration_seconds.labels(
            activity_type="extract_pdf", task_queue="contract-review-queue"
        ).observe(duration)
        pdf_extraction_duration_seconds.observe(duration)
        activity_completed_total.labels(
            activity_type="extract_pdf", task_queue="contract-review-queue"
        ).inc()
        documents_processed_total.labels(status="success").inc()

        log.info(
            "pdf_extraction_completed",
            s3_path=param.s3_path,
            total_pages=total_pages,
            duration_seconds=round(duration, 3),
        )

        return extractpdfoutput(
            s3_md_path=param.s3_path,
            markdown_txt=full_markdown,
            pages_num=total_pages,
        )

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="extract_pdf",
            task_queue="contract-review-queue",
            error_type=type(exc).__name__,
        ).inc()
        documents_processed_total.labels(status="failed").inc()
        log.error(
            "pdf_extraction_failed",
            s3_path=param.s3_path,
            error=str(exc),
            error_type=type(exc).__name__,
            duration_seconds=round(duration, 3),
        )
        raise

    finally:
        active_activities.labels(activity_type="extract_pdf").dec()


@activity.defn
async def call_llm(param: calllminput) -> calllmoutput:
    activity_type_var.set("call_llm")
    start = time.monotonic()
    active_activities.labels(activity_type="call_llm").inc()

    try:
        log.info("llm_call_started", model=LLM_MODEL, prompt_length=len(param.prompt))

        activity.logger.info(f"Calling LLM with prompt: {param.prompt}")
        activity.heartbeat(
            {
                "current_step": "calling llm",
                "start_time": datetime.now().isoformat(),
                "prompt": param.prompt,
            }
        )

        client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": param.prompt},
            ],
            max_tokens=8000,
        )
        resp = response.choices[0].message.content

        tokens_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        tokens_out = (
            getattr(response.usage, "completion_tokens", 0) if response.usage else 0
        )

        duration = time.monotonic() - start
        record_llm_call(
            model=LLM_MODEL,
            operation="general",
            duration=duration,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            input_price_per_1k=LLM_INPUT_PRICE_PER_1K,
            output_price_per_1k=LLM_OUTPUT_PRICE_PER_1K,
        )

        activity.heartbeat(
            {
                "current_step": "llm called",
                "start_time": datetime.now().isoformat(),
                "len_content": len(resp),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        )

        log.info(
            "llm_call_completed",
            model=LLM_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_seconds=round(duration, 3),
            response_length=len(resp),
        )

        return calllmoutput(response=resp)

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="call_llm",
            task_queue="contract-review-queue",
            error_type=type(exc).__name__,
        ).inc()
        log.error(
            "llm_call_failed",
            model=LLM_MODEL,
            error=str(exc),
            error_type=type(exc).__name__,
            duration_seconds=round(duration, 3),
        )
        raise

    finally:
        active_activities.labels(activity_type="call_llm").dec()
