import asyncio
import os
from dotenv import load_dotenv

from temporalio.worker import Worker
from temporalio.client import Client

from activities import call_llm, extract_pdf
from child_worker import pdfsummaryworkflow
from parent_worker import ContractReviewerWorkflow



load_dotenv()


TEMPORAL_HOST = os.getenv("TEMPORAL_HOST")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_CONTRACT_REVIEW_TASK_QUEUE", "contract-review-queue")



async def main():
    client = await Client.connect(TEMPORAL_HOST,namespace=TEMPORAL_NAMESPACE)

    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[ContractReviewerWorkflow,pdfsummaryworkflow],
        activities=[call_llm, extract_pdf]
    )

    await worker.run()



if __name__ == "__main__":
    asyncio.run(main())

