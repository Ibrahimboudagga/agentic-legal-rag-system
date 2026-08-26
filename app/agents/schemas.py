from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["Critical", "High", "Medium", "Low", "N/A", "unknown"]


class PlanSchema(BaseModel):
    objective: str = ""
    sub_queries: list[str] = Field(default_factory=list)
    comparison_needed: bool = False
    analysis_focus: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    retrieval_strategy: Literal["broad", "focused", "exhaustive"] = "focused"
    requires_retrieval: bool = True


class QueryRewriteSchema(BaseModel):
    rewritten_queries: list[str] = Field(default_factory=list)
    reason: str = ""


class EvidenceSchema(BaseModel):
    citation_id: int
    document_id: str = ""
    s3_path: str
    chunk_id: str
    section: str | None = None
    clause: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    text: str
    retrieval_score: float = 0.0
    rerank_score: float | None = None
    source_tool: str = ""


class AnalysisFindingSchema(BaseModel):
    topic: str
    analysis: str
    risk_level: RiskLevel
    legal_basis: str = ""
    citation_ids: list[int] = Field(default_factory=list)
    implications: str = ""


class AnalysisSchema(BaseModel):
    findings: list[AnalysisFindingSchema] = Field(default_factory=list)
    overall_risk_level: RiskLevel = "unknown"
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    citations_used: list[int] = Field(default_factory=list)
    capabilities_applied: list[str] = Field(default_factory=list)


class FinalReportSchema(BaseModel):
    query: str = ""
    executive_summary: str = ""
    detailed_findings: list[dict] = Field(default_factory=list)
    cross_contract_analysis: dict = Field(default_factory=dict)
    overall_risk_level: RiskLevel = "unknown"
    risk_justification: str = ""
    recommendations: list[dict] = Field(default_factory=list)
    evidence_quality: dict = Field(default_factory=dict)
    citations: list[dict] = Field(default_factory=list)
