from datetime import timedelta
from dataclasses import dataclass
from temporalio import workflow
from temporalio.common import RetryPolicy


with workflow.unsafe.imports_passed_through():
    from activities import download_from_s3,extract_to_markdown,upload_markdown_to_s3
    from helper import PDFProcessInput,extractpdfinput,uploadinput

@dataclass
class pdfpipelineinput:
    s3_pdf_path:str

@dataclass
class pdfpipelineoutput:
    s3_markdown_path:str

DEFAULT_RETRY_POLICY=RetryPolicy(initial_interval=timedelta(seconds=5),
                                    backoff_coefficient=2.0,
                                    maximum_interval=timedelta(seconds=10),
                                    maximum_attempts=5)

@workflow.defn
class pdfpipelineworkflow:

    @workflow.run
    async def run(self,input:pdfpipelineinput) -> pdfpipelineoutput:
        retry_policy = DEFAULT_RETRY_POLICY

        download_activity=await workflow.execute_activity(download_from_s3,PDFProcessInput(s3_pdf_path=input.s3_pdf_path),
                                                  retry_policy=retry_policy,start_to_close_timeout=timedelta(minutes=1))

        extract_activity=await workflow.execute_activity(extract_to_markdown,extractpdfinput(pdf_path=download_activity.s3_md_path),
                                                  retry_policy=retry_policy,
                                                start_to_close_timeout=timedelta(minutes=1))

        upload_activity=await workflow.execute_activity(upload_markdown_to_s3,uploadinput(markdown_content=extract_activity.md_doc,s3_pdf_path=input.s3_pdf_path),
                                                  retry_policy=retry_policy,
                                                  start_to_close_timeout=timedelta(minutes=1))
        return pdfpipelineoutput(s3_markdown_path=upload_activity.s3_md_path)