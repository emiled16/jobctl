"""Shared conformance tests that run against every LLMProvider implementation.

The FakeLLMProvider always runs (fast). Real providers are gated behind
env vars (TEST_OPENAI=1, TEST_OLLAMA=1) so CI can opt in selectively.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from jobctl.llm.base import LLMProvider
from tests.conftest import FakeLLMProvider


class _Greeting(BaseModel):
    greeting: str


def _default_messages() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "Say hello."},
    ]


def _build_fake() -> LLMProvider:
    return FakeLLMProvider(chat_reply="hello world")


def _build_openai() -> LLMProvider | None:
    if not os.environ.get("TEST_OPENAI"):
        return None
    from jobctl.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        chat_model=os.environ.get("TEST_OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        embedding_model=os.environ.get("TEST_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )


def _build_ollama() -> LLMProvider | None:
    if not os.environ.get("TEST_OLLAMA"):
        return None
    from jobctl.llm.ollama_provider import OllamaProvider

    return OllamaProvider(
        host=os.environ.get("TEST_OLLAMA_HOST", "http://localhost:11434"),
        chat_model=os.environ.get("TEST_OLLAMA_CHAT_MODEL", "llama3.2"),
        embedding_model=os.environ.get("TEST_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
    )


def _provider_factories() -> list[tuple[str, Any]]:
    factories: list[tuple[str, Any]] = [("fake", _build_fake)]
    if os.environ.get("TEST_OPENAI"):
        factories.append(("openai", _build_openai))
    if os.environ.get("TEST_OLLAMA"):
        factories.append(("ollama", _build_ollama))
    return factories


@pytest.fixture(params=[f[0] for f in _provider_factories()])
def provider(request: pytest.FixtureRequest) -> LLMProvider:
    name_to_factory = dict(_provider_factories())
    factory = name_to_factory[request.param]
    instance = factory()
    if instance is None:
        pytest.skip(f"provider {request.param} not enabled via env var")
    return instance


def test_chat_returns_string(provider: LLMProvider) -> None:
    response = provider.chat(_default_messages())
    assert isinstance(response, dict)
    assert isinstance(response.get("content", ""), str)
    assert response["content"]


def test_stream_yields_chunks(provider: LLMProvider) -> None:
    saw_text = False
    for chunk in provider.stream(_default_messages()):
        assert isinstance(chunk, dict)
        if chunk.get("delta"):
            saw_text = True
    assert saw_text, "expected at least one non-empty delta"


def test_embed_returns_correct_shape(provider: LLMProvider) -> None:
    vectors = provider.embed(["alpha", "beta"])
    assert len(vectors) == 2
    dim = len(vectors[0])
    assert dim > 0
    for vec in vectors:
        assert isinstance(vec, list)
        assert all(isinstance(x, (int, float)) for x in vec)
        assert len(vec) == dim


def test_chat_structured_returns_model(provider: LLMProvider) -> None:
    if not hasattr(provider, "chat_structured"):
        pytest.skip("provider does not implement chat_structured")
    messages = [
        {"role": "system", "content": 'Return {"greeting": "hello"}.'},
        {"role": "user", "content": "Greet me."},
    ]
    if isinstance(provider, FakeLLMProvider):
        pytest.skip("FakeLLMProvider has no structured output")
    result = provider.chat_structured(messages, _Greeting)  # type: ignore[attr-defined]
    assert isinstance(result, _Greeting)
    assert isinstance(result.greeting, str)
