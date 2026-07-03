import os
import sys
import tempfile
import logging
from pathlib import Path

import boto3
import pymupdf4llm
from dotenv import load_dotenv

load_dotenv()

AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_S3_ENDPOINT_URL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]

TEMP_DIR = os.environ["TEMP_DIR"]
os.makedirs(TEMP_DIR, exist_ok=True)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# S3 helper-----------------------
def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=AWS_S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )

def parse_s3_path(path:str):
    
    s3_path_no_scheme = path.replace("s3://", "")
    bucket,_,key = s3_path_no_scheme.partition("/")

    return bucket, key 


def download_from_s3(s3_key: str) -> Path:

    bucket,key = parse_s3_path(s3_key)
    local_path = str(Path(TEMP_DIR) / os.path.basename(s3_key))
    logging.info("Downloading %s from S3 to %s",s3_key,local_path)
    s3 = get_s3_client()
    s3.download_file(bucket, key, str(local_path))
    logging.info("downloaded %s",local_path)
    return local_path

def extract_to_markdown(pdf_path: str) -> str:
    """convert extracted pdf content to markdown"""
    logging.info("converting %s to markdown",pdf_path)
    md_doc = pymupdf4llm.to_markdown(pdf_path)
    logging.info("converted to markdown")
    return md_doc

def upload_markdown_to_s3(s3_pdf_path:str,markdown_content:str):

    bucket,key = parse_s3_path(s3_pdf_path)
    s3_key = key.replace(".pdf",".md")
    s3 = get_s3_client()
    s3.put_object(Bucket=bucket, Key=s3_key, Body=markdown_content.encode("utf-8"),ContentType="text/markdown")
    logging.info("uploaded %s to S3",s3_key)

    output_path = f"s3://{bucket}/{s3_key}"
    return output_path


# Main pipeline
def run_pdf_pipeline(s3_pdf_path:str):

    try:
        local_pdf = download_from_s3(s3_pdf_path)
        markdown_content = extract_to_markdown(local_pdf)
        markdown_path = upload_markdown_to_s3(s3_pdf_path,markdown_content)
        os.remove(local_pdf)
        logging.info("removed local pdf %s",local_pdf)
        return markdown_path
    except Exception as e:
        logging.error("Error in PDF pipeline: %s",e)
        return None


if __name__ == "__main__":
    run_pdf_pipeline(sys.argv[1])
    logging.info(f"PDF pipeline completed {sys.argv[1]}")


    
