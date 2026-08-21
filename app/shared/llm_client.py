from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from shared.config import get_llm_config
from shared.observability.metrics import (
    llm_requests_total,
    llm_request_duration_seconds,
    llm_tokens_input_total,
    llm_tokens_output_total,
    llm_cost_dollars,
)
from shared.observability.logging import get_logger

log = get_logger("llm_client")


@dataclass
class LLMResponse:
    """Structured response from the LLM client."""
    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    duration_seconds: float = 0.0
    raw: Any = None

    def parse_json(self) -> dict:
        """Parse response content as JSON. Falls back to empty dict."""
        try:
            return json.loads(self.content)
        except (json.JSONDecodeError, TypeError):
            return {}


class LLMClient:
    """Centralized LLM abstraction over OpenRouter.

    ALL LLM calls in the system MUST go through this client.
    No agent, node, or activity should call OpenAI/Anthropic/etc directly.

    Responsibilities:
    - Single point of LLM access
    - Automatic retry with backoff
    - Token counting and cost tracking
    - Structured JSON output with repair
    - Model selection from config
    """

    def __init__(self):
        self._config = get_llm_config()
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a completion request. Returns LLMResponse."""
        client = self._get_client()
        use_model = model or self._config.model
        use_max_tokens = max_tokens or self._config.max_tokens

        start = time.monotonic()

        response = await client.chat.completions.create(
            model=use_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=use_max_tokens,
            temperature=temperature,
        )

        duration = time.monotonic() - start
        content = response.choices[0].message.content or ""
        tokens_in = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        tokens_out = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        cost = (tokens_in / 1000 * self._config.input_price_per_1k) + (
            tokens_out / 1000 * self._config.output_price_per_1k
        )

        llm_requests_total.labels(model=use_model, operation="complete").inc()
        llm_request_duration_seconds.labels(model=use_model, operation="complete").observe(duration)
        llm_tokens_input_total.labels(model=use_model).inc(tokens_in)
        llm_tokens_output_total.labels(model=use_model).inc(tokens_out)
        llm_cost_dollars.labels(model=use_model).inc(cost)

        log.info(
            "llm_call_completed",
            model=use_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_seconds=round(duration, 3),
        )

        return LLMResponse(
            content=content,
            model=use_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_seconds=duration,
            raw=response,
        )

    async def complete_json(
        self,
        prompt: str,
        system: str = "You are a helpful assistant. Respond with valid JSON only.",
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> dict:
        """Send a completion request and parse the response as JSON.

        Attempts json_repair for malformed output.
        """
        resp = await self.complete(prompt, system, model, max_tokens, temperature)
        try:
            from json_repair import json_repair
            parsed = json_repair.loads(resp.content)
        except (ImportError, Exception):
            parsed = resp.parse_json()

        if response_schema is None:
            return parsed if isinstance(parsed, dict) else {}

        try:
            return response_schema.model_validate(parsed).model_dump()
        except ValidationError as exc:
            log.warning(
                "llm_structured_output_validation_failed",
                schema=response_schema.__name__,
                error=str(exc),
            )
            return {}

    def model_for(self, operation: str) -> str:
        """Resolve task-specific model routing from configuration."""
        return {
            "planner": self._config.planner_model,
            "query_rewrite": self._config.query_rewrite_model,
            "validator": self._config.validator_model,
            "analysis": self._config.analysis_model,
            "synthesis": self._config.synthesis_model,
        }.get(operation, self._config.model)


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get the singleton LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
