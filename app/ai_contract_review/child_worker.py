from datetime import timedelta
import json_repair
from datetime import datetime
from temporalio.common import RetryPolicy
from temporalio import workflow

from dataclasses import dataclass
import prompts

with workflow.unsafe.imports_passed_through():
    from activities import (extract_pdf, call_llm, extractpdfinput, calllminput)


@dataclass
class pdfsummaryinput:
    s3_pdf_path:str

@dataclass
class pdfsummaryoutput:
    s3_md_path:str
    summary:str
    key_risks:str

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)

@workflow.defn
class pdfsummaryworkflow:
    @workflow.run
    async def run(self,param:pdfsummaryinput)->pdfsummaryoutput:

        extract_md = await workflow.execute_activity(
            extract_pdf,
            extractpdfinput(
                s3_path=param.s3_pdf_path
            ),
            retry_policy=DEFAULT_RETRY_POLICY,
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(seconds=120),
        )



        llm_call = await workflow.execute_activity(
            call_llm,
            calllminput(
                prompt=prompts._SUMMARY_PROMPT.format(text=extract_md.markdown_txt[:5_000]),

            ),
            retry_policy=DEFAULT_RETRY_POLICY,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=120),
        )

        parsed_output = json_repair.loads(llm_call.response)
        if hasattr(extract_md, "s3_md_path"):
            s3_md_path = extract_md.s3_md_path
        else:
            s3_md_path = extract_md.s3_path

        return pdfsummaryoutput(
            s3_md_path=s3_md_path,
            summary=parsed_output["summary"],
            key_risks=parsed_output["key_risks"]
        )




        

