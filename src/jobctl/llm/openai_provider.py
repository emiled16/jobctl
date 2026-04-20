"""OpenAI implementation of the LLMProvider protocol."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pydantic import BaseModel

from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def _retry(operation: Callable[[], Any]) -> Any:
    try:
        from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
    except ModuleNotFoundError:
        APIConnectionError = APIError = APITimeoutError = RateLimitError = Exception  # type: ignore[assignment]

    transient = (RateLimitError, APITimeoutError, APIConnectionError, APIError)
    last_error: Exception | None = None
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            return operation()
        except transient as exc:
            last_error = exc
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                break
            time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _tool_specs_to_openai(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _parse_openai_tool_calls(raw: Any) -> list[ToolCall]:
    if not raw:
        return []
    calls: list[ToolCall] = []
    for tc in raw:
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", "") if fn else ""
        args_raw = getattr(fn, "arguments", "") if fn else ""
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        calls.append(
            ToolCall(id=getattr(tc, "id", "") or "", name=name or "", arguments=args),
        )
    return calls


class OpenAIProvider:
    """LLMProvider that talks to the OpenAI HTTP API via the official SDK."""

    def __init__(
        self,
        api_key: str,
        chat_model: str,
        embedding_model: str,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
        self._client = client
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        kwargs: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "temperature": temperature,
        }
        openai_tools = _tool_specs_to_openai(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = _retry(lambda: self._client.chat.completions.create(**kwargs))
        message = response.choices[0].message
        content = getattr(message, "content", "") or ""
        tool_calls = _parse_openai_tool_calls(getattr(message, "tool_calls", None))
        result: ChatResponse = {"content": content}
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        kwargs: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "stream": True,
        }
        openai_tools = _tool_specs_to_openai(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        stream = _retry(lambda: self._client.chat.completions.create(**kwargs))
        for event in stream:
            try:
                delta = event.choices[0].delta
            except (AttributeError, IndexError):
                continue
            text = getattr(delta, "content", None) or ""
            tc_delta = getattr(delta, "tool_calls", None)
            chunk: ChatChunk = {}
            if text:
                chunk["delta"] = text
            if tc_delta:
                parsed = _parse_openai_tool_calls(tc_delta)
                if parsed:
                    chunk["tool_call_delta"] = parsed[0]
            if chunk:
                yield chunk
        yield {"done": True}

    def chat_structured(
        self,
        messages: list[Message],
        response_format: type[StructuredModel],
        *,
        temperature: float = 0.3,
    ) -> StructuredModel:
        response = _retry(
            lambda: self._client.beta.chat.completions.parse(
                model=self.chat_model,
                messages=list(messages),
                response_format=response_format,
                temperature=temperature,
            )
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured response did not include parsed content")
        return parsed

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = _retry(
            lambda: self._client.embeddings.create(model=self.embedding_model, input=texts)
        )
        return [item.embedding for item in response.data]


__all__ = ["OpenAIProvider"]
