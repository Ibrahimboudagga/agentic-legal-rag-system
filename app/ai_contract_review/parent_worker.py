import json
from json_repair import json_repair
import asyncio
import textwrap
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
import prompts

from temporalio.common import RetryPolicy
from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ParentClosePolicy
with workflow.unsafe.imports_passed_through():
    from activities import (call_llm, calllminput)
    from child_worker import (pdfsummaryworkflow,pdfsummaryinput)


@dataclass
class ContractReviewerWorkflowinput:
    s3_paths: list[str]
    max_revesion:int =2


@dataclass
class ContractReviewerWorkflowoutput:
    report:str
    sources:str
    approved_by:str

@workflow.defn
class ContractReviewerWorkflow:
    
    def __init__(self):

        self.status:str = "processing"
        self.summuries:list = []
        self.report:str = ""

        self.review_decision:Optional[str] = None
        self.review_feedback:str=""
        self.approved_by:str=""

    @workflow.signal
    async def assign_reviewer(self, name:str=""):
        self.approved_by = name

    @workflow.update
    async def submit_decision(self, decision:str, feedback:str):
        self.review_decision = decision
        self.review_feedback = feedback
        return f'decision {decision} recorded'

    @submit_decision.validator
    async def validate_decision(self,decision:str,feedback:str):
        valid_decisions = ["approved","revise"]
        if decision not in valid_decisions:
            raise ApplicationError(f"invalid decision {decision}")
        
        if decision =="revise" and not feedback:
            raise ApplicationError("feedback is required for revise decision")
        return True

    @workflow.query
    def query_status(self):
        return {
            "status":self.status,
            "review_decision":self.review_decision,
            "review_feedback":self.review_feedback,
            "approved_by":self.approved_by
        }

    @workflow.query
    def query_fullreport(self):
        return {
            "status":self.status,
            "review_decision":self.review_decision,
            "review_feedback":self.review_feedback,
            "approved_by":self.approved_by,
            "summuries":self.summuries,
            "report":json.dumps(self.report,ensure_ascii=False,indent=4  ),
            "sources":[s["s3_md_path"] for s in self.summuries]
        }

    @workflow.run
    async def run(self, param: ContractReviewerWorkflowinput) -> ContractReviewerWorkflowoutput:
        
        self.status = "extracting"
        workflow.logger.info(f"start extracting pdfs from {param.s3_paths}")

        workflow_id = workflow.info().workflow_id
        workflow_task_queue = workflow.info().task_queue

        # TERMINATE: kill child workflows when parent closes
        # REQUEST_CANCEL: ask child workflows to cancel gracefully
        # ABANDON: leave them alone and let them keep running

        raw_results = await asyncio.gather(
            *[
                workflow.execute_child_workflow(
                    pdfsummaryworkflow.run,
                    pdfsummaryinput(s3_pdf_path=s3_path),
                    id=f"{workflow_id}-summary-{idx}",
                    task_queue=workflow_task_queue,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
                for idx, s3_path in enumerate(param.s3_paths)
            ],
            return_exceptions=True,
        )


        for idx, result in enumerate(raw_results):
            if isinstance(result, Exception):
                workflow.logger.warning(
                    f"child workflow {idx} failed with {result}"
                )
            
            else:
                self.summuries.append({
                    "s3_md_path":result.s3_md_path,
                    "summary":result.summary,
                    "key_risks":result.key_risks
                })
        
        if len(self.summuries)==0:
            raise ApplicationError("no summuries generated")
        
        self.status = "synthesizing"
        workflow.logger.info(f"synthesizing summuries from {len(self.summuries)} contracts")
        llm_result = await workflow.execute_activity(
            call_llm,
            calllminput(
                prompt = prompts._SYNTHESIS_PROMPT.format(
                    n = len(self.summuries),
                    summaries = "\n\n".join(f"contract{i+1}:\n{s['summary']}\nkey_risk:{s['key_risks']}" for i,s in enumerate(self.summuries))
                    
                )
            ),
            schedule_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=120),
            start_to_close_timeout=timedelta(minutes=5)
        )
        self.report = json_repair.loads(llm_result.response)
        # return ContractReviewerWorkflowoutput(
        #     report=self.report,
        #     sources=params.s3_paths,
        #     approved_by=""
        # )

        # Human in the Loop 
        
        for rev in range (param.max_revesion +1 ) :
            self.status = "human_in_loop"
            self.review_decision = None
            try:
                await workflow.wait_condition(
                    lambda: self.review_decision is not None,
                    timeout=timedelta(days=3),
                )
            except asyncio.TimeoutError:
                workflow.logger.warning("Review timed out after 3 days — auto-completing")
                break
            if self.review_decision == "APPROVED":
                workflow.logger.info(f"review approved after {rev+1} revision(s) {self.approved_by}")
                break

            self.status = "revising"
            workflow.logger.info(f"revising after {rev+1} revision(s)")

            llm_prompt = prompts._REVISION_PROMPT.format(
                report = json.dumps(
                    self.report,ensure_ascii=False,indent=4  
                ),
                feedback = self.review_feedback
                
            )
            revised_report = await workflow.execute_activity(
                call_llm,
                calllminput(
                    prompt = llm_prompt
                ),
                schedule_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=120),
                start_to_close_timeout=timedelta(minutes=5)
            )
            self.report = json_repair.loads(revised_report.response)
        
        self.status = "completed"

        return ContractReviewerWorkflowoutput(
            report=self.report,
            sources=[s["s3_md_path"] for s in self.summuries],
            approved_by=self.approved_by
        )
            


                

         

             

        



