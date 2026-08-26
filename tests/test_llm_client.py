from __future__ import annotations

import os

import pytest


def test_llm_client_singleton():
    from shared.llm_client import get_llm_client, LLMClient
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["LLM_MODEL_NAME"] = "test-model"

    client1 = get_llm_client()
    client2 = get_llm_client()
    assert client1 is client2
    assert isinstance(client1, LLMClient)


def test_llm_response_parse_json_valid():
    from shared.llm_client import LLMResponse

    resp = LLMResponse(content='{"key": "value"}', model="test")
    assert resp.parse_json() == {"key": "value"}


def test_llm_response_parse_json_invalid():
    from shared.llm_client import LLMResponse

    resp = LLMResponse(content="not json", model="test")
    assert resp.parse_json() == {}


def test_llm_response_parse_json_empty():
    from shared.llm_client import LLMResponse

    resp = LLMResponse(content="", model="test")
    assert resp.parse_json() == {}
