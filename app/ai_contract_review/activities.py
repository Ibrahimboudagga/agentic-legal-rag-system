from datetime import datetime
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import math
import tempfile
import boto3
import fitz
import pymupdf4llm
from openai import OpenAI

# pyrefly: ignore [missing-import]
from temporalio import activity 
from dataclasses import dataclass

load_dotenv()

AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_S3_ENDPOINT_URL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
TEMP_DIR = os.environ["TEMP_DIR"]

os.makedirs(TEMP_DIR, exist_ok=True)

@dataclass
class extractpdfinput:
    s3_path:str
    batch_size:int = 2

@dataclass
class extractpdfoutput:
    s3_md_path:str
    markdown_txt:str
    pages_num:int


@dataclass
class calllminput:
    prompt:str

@dataclass
class calllmoutput:
    response:str


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=AWS_S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )

def parse_s3_path(path: str):
    s3_path_no_scheme = path.replace("s3://", "")
    bucket, _, key = s3_path_no_scheme.partition("/")
    return bucket, key

@activity.defn
async def extract_pdf(param: extractpdfinput)->extractpdfoutput:

    activity.heartbeat({
        "current_step": "downloading pdf",
        "page_progress":0,
        "start_time": datetime.now().isoformat()
    })
    client = get_s3_client()
    bucket,key = parse_s3_path(param.s3_path)
    filename = Path(key).name
    local_path = Path(TEMP_DIR) / filename

    await asyncio.to_thread(client.download_file, bucket, key, str(local_path))
    doc = await asyncio.to_thread(fitz.open, local_path)
    total_pages = doc.page_count
    activity.logger.info(f"Total pages: {total_pages}")

    total_num_batches = math.ceil(total_pages/param.batch_size)
    all_text_chunks = []
    for i in range(total_num_batches):
        start_page = i * param.batch_size
        end_page = min((i+1)*param.batch_size,total_pages)
        activity.logger.info(f"Processing pages {start_page} to {end_page}")
        batch_md = await asyncio.to_thread(
            pymupdf4llm.to_markdown,
            doc,
            from_page=start_page,
            to_page=end_page,
        )
        
        all_text_chunks.append(batch_md)
        
        activity.heartbeat({
        "current_step": "extracting pdf to markdown",
        "page_progress":end_page,
        "start_time": datetime.now().isoformat(),
        "s3_path": param.s3_path,
        "pages_processed":end_page,
        "total_pages":total_pages,
        "progeressed_batch":round(end_page/total_pages*100,2),
        "total_batches":total_num_batches,
        "current_batch":i+1
    })

    full_markdown = "\n\n".join(all_text_chunks)
    activity.heartbeat({
        "current_step": "pdf extracted to markdown",
        "start_time": datetime.now().isoformat(),
        "s3_path": param.s3_path,
        "total_pages":total_pages,
        "total_batches":total_num_batches
    })
    return extractpdfoutput(
        s3_md_path=param.s3_path,
        markdown_txt=full_markdown,
        pages_num=total_pages
    )
    
    



@activity.defn
async def call_llm(param: calllminput)-> calllmoutput:

    activity.logger.info(f"Calling LLM with prompt: {param.prompt}")
    activity.heartbeat({
        "current_step": "calling llm",
        "start_time": datetime.now().isoformat(),
        "prompt": param.prompt
    })
    client = OpenAI(
        api_key = os.getenv("OPENROUTER_API_KEY"),
        base_url = "https://openrouter.ai/api/v1"
    )
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=os.getenv("OPENROUTER_MODEL"),
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": param.prompt},
        ],
        max_tokens=8000,
    )
    resp = response.choices[0].message.content
    activity.heartbeat({
        "current_step": "llm called",
        "start_time": datetime.now().isoformat(),
        "len_content": len(resp)
    })
    return calllmoutput(response=resp)
