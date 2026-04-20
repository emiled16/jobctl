"""Ollama implementation of the LLMProvider protocol."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolCall, ToolSpec

logger = logging.getLogger(__name__)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def _tool_specs_to_ollama(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
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


def _parse_ollama_tool_calls(raw: Any) -> list[ToolCall]:
    if not raw:
        return []
    calls: list[ToolCall] = []
    for tc in raw:
        fn = tc.get("function") if isinstance(tc, dict) else None
        if not fn:
            continue
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        calls.append(ToolCall(id=tc.get("id", name) or name, name=name, arguments=args or {}))
    return calls


class OllamaProvider:
    """LLMProvider that talks to an Ollama HTTP server."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        chat_model: str = "llama3.2",
        embedding_model: str = "nomic-embed-text",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self._client = client or httpx.Client(timeout=timeout)

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        ollama_tools = _tool_specs_to_ollama(tools)
        if ollama_tools:
            payload["tools"] = ollama_tools

        response = self._client.post(f"{self.host}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {}) or {}
        content = message.get("content", "") or ""
        tool_calls = _parse_ollama_tool_calls(message.get("tool_calls"))
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
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": list(messages),
            "stream": True,
            "options": {"temperature": temperature},
        }
        ollama_tools = _tool_specs_to_ollama(tools)
        if ollama_tools:
            payload["tools"] = ollama_tools

        with self._client.stream("POST", f"{self.host}/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("skipping non-JSON ollama stream line: %r", line)
                    continue
                message = data.get("message", {}) or {}
                text = message.get("content", "") or ""
                tool_calls = _parse_ollama_tool_calls(message.get("tool_calls"))
                chunk: ChatChunk = {}
                if text:
                    chunk["delta"] = text
                if tool_calls:
                    chunk["tool_call_delta"] = tool_calls[0]
                if chunk:
                    yield chunk
                if data.get("done"):
                    yield {"done": True}
                    return

    def chat_structured(
        self,
        messages: list[Message],
        response_format: type[StructuredModel],
        *,
        temperature: float = 0.3,
    ) -> StructuredModel:
        schema_json = json.dumps(response_format.model_json_schema(), sort_keys=True)
        instruction: Message = {
            "role": "system",
            "content": (
                "Return ONLY a JSON object matching this schema. "
                "Do not add prose, markdown fences, or comments.\n"
                f"Schema:\n{schema_json}"
            ),
        }
        augmented = [instruction, *messages]
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": augmented,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        response = self._client.post(f"{self.host}/api/chat", json=payload)
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content", "")
        try:
            return response_format.model_validate_json(content)
        except Exception as exc:
            raise ValueError(
                f"Ollama structured response did not validate against schema: {exc}"
            ) from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.post(
            f"{self.host}/api/embed",
            json={"model": self.embedding_model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings")
        if embeddings is None and "embedding" in data:
            embeddings = [data["embedding"]]
        return embeddings or []


__all__ = ["OllamaProvider"]
