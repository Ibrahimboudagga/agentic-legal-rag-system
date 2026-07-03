import os
import asyncio
from pathlib import Path
# pyrefly: ignore [missing-import]
from temporalio import activity 
import pymupdf4llm
from dataclasses import dataclass
from helper import (PDFProcessInput,PDFProcessOutput,extractpdfinput,
                   extractpdfoutput,uploadinput,uploadoutput,
                   get_s3_client,parse_s3_path, TEMP_DIR)

 

@activity.defn
async def download_from_s3(parameter: PDFProcessInput) -> PDFProcessOutput:

    bucket,key = parse_s3_path(parameter.s3_pdf_path)
    local_path = str(Path(TEMP_DIR) / os.path.basename(key))
    activity.logger.info("Downloading %s from S3 to %s",key,local_path)
    s3 = get_s3_client()
    await asyncio.to_thread(s3.download_file, bucket, key, str(local_path))
    activity.logger.info("downloaded %s",local_path)
    return PDFProcessOutput(s3_md_path=local_path)

@activity.defn
async def extract_to_markdown(parameter: extractpdfinput) -> extractpdfoutput:
    """convert extracted pdf content to markdown"""
    activity.logger.info("converting %s to markdown",parameter.pdf_path)
    md_doc = await asyncio.to_thread(pymupdf4llm.to_markdown, parameter.pdf_path)
    activity.logger.info("converted to markdown")
    return extractpdfoutput(md_doc=md_doc)

@activity.defn
async def upload_markdown_to_s3(param1: uploadinput) -> uploadoutput:

    bucket,key = parse_s3_path(param1.s3_pdf_path)
    s3_key = key.replace(".pdf",".md")
    s3 = get_s3_client()
    await asyncio.to_thread(
        s3.put_object,
        Bucket=bucket,
        Key=s3_key,
        Body=param1.markdown_content.encode("utf-8"),
        ContentType="text/markdown",
    )
    activity.logger.info("uploaded %s to S3",s3_key)

    output_path = f"s3://{bucket}/{s3_key}"
    return uploadoutput(s3_md_path=output_path)
