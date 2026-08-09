from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import fitz
import pymupdf4llm
from dotenv import load_dotenv
from openai import OpenAI
from temporalio import activity

from shared.config import get_app_config, get_aws_config, get_llm_config
from shared.s3 import get_s3_client, parse_s3_path
from shared.observability.logging import (
    activity_type_var,
    get_logger,
)
from shared.observability.metrics import (
    active_activities,
    activity_completed_total,
    activity_duration_seconds,
    activity_failed_total,
    documents_processed_total,
    pdf_extraction_duration_seconds,
    record_llm_call,
)

load_dotenv()

log = get_logger("activities")

_app_config = get_app_config()
_aws_config = get_aws_config()
_llm_config = get_llm_config()

os.makedirs(_app_config.temp_dir, exist_ok=True)


@dataclass
class ExtractPDFInput:
    s3_path: str
    batch_size: int = 2


@dataclass
class ExtractPDFOutput:
    s3_md_path: str
    markdown_txt: str
    pages_num: int


@dataclass
class CallLLMInput:
    prompt: str


@dataclass
class CallLLMOutput:
    response: str


# Backward-compatible aliases for existing workflow references
extractpdfinput = ExtractPDFInput
extractpdfoutput = ExtractPDFOutput
calllminput = CallLLMInput
calllmoutput = CallLLMOutput


@activity.defn
async def extract_pdf(param: ExtractPDFInput) -> ExtractPDFOutput:
    activity_type_var.set("extract_pdf")
    start = time.monotonic()
    active_activities.labels(activity_type="extract_pdf").inc()

    try:
        log.info("pdf_extraction_started", s3_path=param.s3_path)

        activity.heartbeat(
            {
                "current_step": "downloading_pdf",
                "page_progress": 0,
                "start_time": datetime.now(timezone.utc).isoformat(),
            }
        )
        s3_client = get_s3_client(_aws_config)
        bucket, key = parse_s3_path(param.s3_path)
        filename = Path(key).name
        local_path = Path(_app_config.temp_dir) / filename

        await asyncio.to_thread(s3_client.download_file, bucket, key, str(local_path))
        doc = await asyncio.to_thread(fitz.open, local_path)
        total_pages = doc.page_count
        activity.logger.info(f"Total pages: {total_pages}")

        total_num_batches = math.ceil(total_pages / param.batch_size)
        all_text_chunks = []
        try:
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
                        "current_step": "extracting_pdf_to_markdown",
                        "page_progress": end_page,
                        "start_time": datetime.now(timezone.utc).isoformat(),
                        "s3_path": param.s3_path,
                        "pages_processed": end_page,
                        "total_pages": total_pages,
                        "progressed_batch": round(end_page / total_pages * 100, 2),
                        "total_batches": total_num_batches,
                        "current_batch": i + 1,
                    }
                )
        finally:
            doc.close()

        full_markdown = "\n\n".join(all_text_chunks)
        activity.heartbeat(
            {
                "current_step": "pdf_extracted_to_markdown",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "s3_path": param.s3_path,
                "total_pages": total_pages,
                "total_batches": total_num_batches,
            }
        )

        duration = time.monotonic() - start
        activity_duration_seconds.labels(
            activity_type="extract_pdf", task_queue=activity.info().task_queue
        ).observe(duration)
        pdf_extraction_duration_seconds.observe(duration)
        activity_completed_total.labels(
            activity_type="extract_pdf", task_queue=activity.info().task_queue
        ).inc()
        documents_processed_total.labels(status="success").inc()

        log.info(
            "pdf_extraction_completed",
            s3_path=param.s3_path,
            total_pages=total_pages,
            duration_seconds=round(duration, 3),
        )

        return ExtractPDFOutput(
            s3_md_path=param.s3_path,
            markdown_txt=full_markdown,
            pages_num=total_pages,
        )

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="extract_pdf",
            task_queue=activity.info().task_queue,
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
async def call_llm(param: CallLLMInput) -> CallLLMOutput:
    activity_type_var.set("call_llm")
    start = time.monotonic()
    active_activities.labels(activity_type="call_llm").inc()

    try:
        log.info("llm_call_started", model=_llm_config.model, prompt_length=len(param.prompt))

        activity.heartbeat(
            {
                "current_step": "calling_llm",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "prompt_length": len(param.prompt),
            }
        )

        client = OpenAI(
            api_key=_llm_config.api_key,
            base_url=_llm_config.base_url,
        )
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=_llm_config.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": param.prompt},
            ],
            max_tokens=_llm_config.max_tokens,
        )
        resp = response.choices[0].message.content

        tokens_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        tokens_out = (
            getattr(response.usage, "completion_tokens", 0) if response.usage else 0
        )

        duration = time.monotonic() - start
        record_llm_call(
            model=_llm_config.model,
            operation="general",
            duration=duration,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            input_price_per_1k=_llm_config.input_price_per_1k,
            output_price_per_1k=_llm_config.output_price_per_1k,
        )

        activity.heartbeat(
            {
                "current_step": "llm_called",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "len_content": len(resp),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        )

        log.info(
            "llm_call_completed",
            model=_llm_config.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_seconds=round(duration, 3),
            response_length=len(resp),
        )

        return CallLLMOutput(response=resp)

    except Exception as exc:
        duration = time.monotonic() - start
        activity_failed_total.labels(
            activity_type="call_llm",
            task_queue=activity.info().task_queue,
            error_type=type(exc).__name__,
        ).inc()
        log.error(
            "llm_call_failed",
            model=_llm_config.model,
            error=str(exc),
            error_type=type(exc).__name__,
            duration_seconds=round(duration, 3),
        )
        raise

    finally:
        active_activities.labels(activity_type="call_llm").dec()
