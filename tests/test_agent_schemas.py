from __future__ import annotations

from agents.capability_registry import select_capabilities
from agents.schemas import PlanSchema


def test_plan_schema_defaults_and_validation():
    plan = PlanSchema.model_validate({
        "objective": "Find termination risk",
        "sub_queries": ["termination for convenience"],
        "required_capabilities": ["termination"],
    })
    assert plan.requires_retrieval is True
    assert plan.retrieval_strategy == "focused"


def test_capability_registry_filters_unknown_capabilities():
    assert select_capabilities(["termination", "unknown"]) == ["termination"]
