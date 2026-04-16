"""OpenAI API client wrapper."""

import time
from collections.abc import Iterator
from typing import Any, TypeVar

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
MAX_EMBEDDING_BATCH_SIZE = 2048
MAX_RETRY_ATTEMPTS = 3

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
Message = dict[str, Any]


class LLMClient:
    def __init__(self, api_key: str, model: str, client: OpenAI | None = None) -> None:
        self.model = model
        self._client = client or OpenAI(api_key=api_key)

    def chat(self, messages: list[Message], temperature: float = 0.7) -> str:
        response = _retry(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
        )
        content = response.choices[0].message.content
        return content or ""

    def chat_structured(
        self,
        messages: list[Message],
        response_format: type[StructuredModel],
        temperature: float = 0.3,
    ) -> StructuredModel:
        response = _retry(
            lambda: self._client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=response_format,
                temperature=temperature,
            )
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured response did not include parsed content")
        return parsed

    def chat_stream(self, messages: list[Message], temperature: float = 0.7) -> Iterator[str]:
        stream = _retry(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
            )
        )
        for event in stream:
            chunk = event.choices[0].delta.content
            if chunk:
                yield chunk

    def get_embedding(self, text: str, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
        return get_embedding(text, model=model, client=self._client)

    def get_embeddings_batch(
        self,
        texts: list[str],
        model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> list[list[float]]:
        return get_embeddings_batch(texts, model=model, client=self._client)


def get_embedding(
    text: str, model: str = DEFAULT_EMBEDDING_MODEL, client: OpenAI | None = None
) -> list[float]:
    embeddings = get_embeddings_batch([text], model=model, client=client)
    return embeddings[0]


def get_embeddings_batch(
    texts: list[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
    client: OpenAI | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    openai_client = client or OpenAI()
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), MAX_EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + MAX_EMBEDDING_BATCH_SIZE]
        response = _retry(
            lambda: openai_client.embeddings.create(
                model=model,
                input=batch,
            )
        )
        embeddings.extend([item.embedding for item in response.data])
    return embeddings


def _retry(operation: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            return operation()
        except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as exc:
            last_error = exc
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                break
            time.sleep(2**attempt)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Retry operation failed without an exception")
