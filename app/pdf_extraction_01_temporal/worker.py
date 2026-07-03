from dotenv import load_dotenv
import os
import asyncio
import logging
from dotenv import load_dotenv
from temporalio.client import Client
from workflow_process_pdf import pdfpipelineworkflow
from activities import download_from_s3,extract_to_markdown,upload_markdown_to_s3
from temporalio.worker import Worker




load_dotenv()

TEMPORAL_HOST=os.getenv("TEMPORAL_HOST")
TEMPORAL_NAMESPACE=os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_PDF_PROCESS_TASK_QUEUE=os.getenv("TEMPORAL_PDF_PROCESS_TASK_QUEUE")

async def main():
    temporal_client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
    worker_pdf_process = Worker(
        temporal_client,
        task_queue=TEMPORAL_PDF_PROCESS_TASK_QUEUE,
        workflows=[pdfpipelineworkflow],
        activities=[download_from_s3,extract_to_markdown,upload_markdown_to_s3]
    )
    print(f"started worker polling tasks from {TEMPORAL_PDF_PROCESS_TASK_QUEUE}")
    await worker_pdf_process.run()


if __name__ == "__main__":
    asyncio.run(main())
