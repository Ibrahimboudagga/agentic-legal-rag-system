from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from typing_extensions import TypedDict


# ── Retrieval Tool Results ────────────────────────────────────────

@dataclass
class ANNResult:
    """Approximate Nearest Neighbor result from pgvector."""
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    score: float
    page_number: int | None = None
    chunk_index: int = 0
    source: str = "ann"


@dataclass
class FTSResult:
    """Full-Text Search result from PostgreSQL ts_rank."""
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    rank: float
    page_number: int | None = None
    chunk_index: int = 0
    source: str = "fts"


@dataclass
class MetadataResult:
    """Metadata-filtered result."""
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    score: float
    page_number: int | None = None
    chunk_index: int = 0
    source: str = "metadata"


@dataclass
class UnifiedRetrievalResult:
    """Unified result from any retrieval tool."""
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    score: float
    page_number: int | None = None
    chunk_index: int = 0
    source: str = ""
    metadata: dict = field(default_factory=dict)


# ── Reranker ──────────────────────────────────────────────────────

@dataclass
class RerankedChunk:
    """Reranked chunk with final relevance score."""
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    original_score: float
    rerank_score: float
    source: str = ""
    page_number: int | None = None
    chunk_index: int = 0


# ── Evidence ──────────────────────────────────────────────────────

@dataclass
class EvidenceItem:
    """A single piece of validated evidence."""
    chunk_id: str
    s3_path: str
    content: str
    page_number: int | None
    relevance_score: float
    citation_id: int = 0
    source_tool: str = ""
    validation_status: str = "pending"


@dataclass
class ValidationIssue:
    """An issue found during evidence validation."""
    issue_type: str
    description: str
    chunk_id: str | None = None
    severity: str = "medium"


@dataclass
class ValidationResult:
    """Result of evidence validation."""
    passed: bool
    coverage_score: float
    consistency_score: float
    issues: list[ValidationIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    needs_retrieval: bool = False


# ── Agent Outputs ─────────────────────────────────────────────────

@dataclass
class PlanOutput:
    """Planner agent decomposition output."""
    sub_queries: list[str]
    retrieval_strategy: str
    comparison_needed: bool
    analysis_focus: list[str]


@dataclass
class RetrievalOutput:
    """Retrieval agent output."""
    retrieved_chunks: list[dict]
    tools_used: list[str]
    retrieval_count: int
    iteration: int


@dataclass
class AnalysisOutput:
    """Analysis agent output."""
    findings: list[dict]
    risk_level: str
    summary: str
    confidence: float
    citations_used: list[int]


@dataclass
class ComparisonOutput:
    """Comparison agent output (cross-contract)."""
    cross_contract_risks: list[dict]
    contract_interactions: list[dict]
    overall_risk_level: str
    patterns: list[str]


@dataclass
class SynthesisOutput:
    """Final synthesis output."""
    executive_summary: str
    detailed_findings: list[dict]
    overall_risk_level: str
    recommendations: list[str]
    citations: list[dict]
    evidence_count: int
    validation_passed: bool


# ── LangGraph State ───────────────────────────────────────────────

class AgentState(TypedDict):
    """Main state for the Agentic RAG LangGraph workflow."""

    # ── Input ──
    query: str
    s3_paths: list[str]
    max_iterations: int

    # ── Planner ──
    plan: dict
    sub_queries: list[str]
    comparison_needed: bool
    analysis_focus: list[str]

    # ── Retrieval ──
    retrieval_results: list[dict]
    tools_used: list[str]
    retrieval_iteration: int
    max_retrieval_iterations: int

    # ── Reranker ──
    reranked_chunks: list[dict]

    # ── Evidence Store ──
    evidence: list[dict]
    evidence_citations: list[dict]
    evidence_count: int

    # ── Evidence Validator ──
    validation_result: dict
    validation_attempts: int
    needs_retrieval: bool

    # ── Analysis ──
    analysis: dict

    # ── Comparison ──
    comparison: dict

    # ── Synthesis ──
    synthesis: dict

    # ── Control ──
    status: str
    error: str | None
    iteration: int
