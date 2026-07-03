import os
import boto3
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# Env variables
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_REGION = os.environ["AWS_REGION"]
AWS_S3_ENDPOINT_URL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
TEMP_DIR = os.environ["TEMP_DIR"]

os.makedirs(TEMP_DIR, exist_ok=True)

# Dataclasses
@dataclass
class PDFProcessInput:
    s3_pdf_path: str

@dataclass
class PDFProcessOutput:
    s3_md_path: str

@dataclass
class extractpdfinput:
    pdf_path: str

@dataclass
class extractpdfoutput:
    md_doc: str

@dataclass
class uploadinput:
    markdown_content: str
    s3_pdf_path: str

@dataclass
class uploadoutput:
    s3_md_path: str

# S3 helpers
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