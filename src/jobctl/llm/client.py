"""Local Codex CLI LLM client wrapper.

Deprecated:
    Use :class:`jobctl.llm.codex_provider.CodexCLIProvider` (and the other
    providers under ``jobctl.llm``) instead. This module is retained for
    backward compatibility with callers that have not yet migrated to the
    :class:`jobctl.llm.base.LLMProvider` protocol.
"""

import json
import subprocess
import tempfile
import warnings
from collections.abc import Callable, Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 1536

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
Message = dict[str, Any]
CodexRunner = Callable[[str, Path | None, str | None, str | None], str]
_EMBEDDERS: dict[str, "TransformerEmbedder"] = {}


class LLMClient:
    """Deprecated direct subprocess wrapper.

    New code should use :class:`jobctl.llm.codex_provider.CodexCLIProvider` or
    another :class:`jobctl.llm.base.LLMProvider` implementation obtained from
    :func:`jobctl.llm.registry.get_provider`.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        codex_binary: str = "codex",
        cwd: Path | None = None,
        runner: CodexRunner | None = None,
    ) -> None:
        warnings.warn(
            "jobctl.llm.client.LLMClient is deprecated; use "
            "jobctl.llm.codex_provider.CodexCLIProvider or another LLMProvider.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.model = model
        self.codex_binary = codex_binary
        self.cwd = cwd
        self._runner = runner or self._run_codex

    def chat(self, messages: list[Message], temperature: float = 0.7) -> str:
        prompt = _messages_to_prompt(messages, temperature=temperature)
        return self._runner(prompt, None, self.model, self.cwd).strip()

    def chat_structured(
        self,
        messages: list[Message],
        response_format: type[StructuredModel],
        temperature: float = 0.3,
    ) -> StructuredModel:
        prompt = (
            f"{_messages_to_prompt(messages, temperature=temperature)}\n\n"
            "Return only JSON that matches the provided schema. Do not include Markdown fences."
        )
        schema_path = _write_json_schema(response_format)
        try:
            output = self._runner(prompt, schema_path, self.model, self.cwd)
        finally:
            schema_path.unlink(missing_ok=True)

        return response_format.model_validate_json(output)

    def chat_stream(self, messages: list[Message], temperature: float = 0.7) -> Iterator[str]:
        yield self.chat(messages, temperature=temperature)

    def get_embedding(self, text: str, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
        return get_embedding(text, model=model)

    def get_embeddings_batch(
        self,
        texts: list[str],
        model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> list[list[float]]:
        return get_embeddings_batch(texts, model=model)

    def _run_codex(
        self,
        prompt: str,
        output_schema: Path | None,
        model: str | None,
        cwd: Path | None,
    ) -> str:
        with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as output_file:
            output_path = Path(output_file.name)

        command = [
            self.codex_binary,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
        ]
        if model:
            command.extend(["--model", model])
        if cwd:
            command.extend(["--cd", str(cwd)])
        if output_schema:
            command.extend(["--output-schema", str(output_schema)])
        command.append("-")

        try:
            subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                check=True,
            )
            return output_path.read_text(encoding="utf-8")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or f"exit status {exc.returncode}"
            raise RuntimeError(f"Codex LLM call failed: {details}") from exc
        finally:
            output_path.unlink(missing_ok=True)


def get_embedding(text: str, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
    return get_embeddings_batch([text], model=model)[0]


def get_embeddings_batch(
    texts: list[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> list[list[float]]:
    if not texts:
        return []
    return _get_embedder(model).embed(texts)


class TransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.tokenizer, self.model = _load_transformer_model(model_name)
        self.model.eval()

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import torch
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Transformer embeddings require torch and transformers to be installed."
            ) from exc

        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            outputs = self.model(**encoded)

        pooled = _mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
        normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return [_fit_embedding_dimensions(row.tolist()) for row in normalized]


def _get_embedder(model: str) -> TransformerEmbedder:
    if model not in _EMBEDDERS:
        _EMBEDDERS[model] = TransformerEmbedder(model)
    return _EMBEDDERS[model]


def _load_transformer_model(model_name: str):
    try:
        from transformers import AutoModel, AutoTokenizer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Transformer embeddings require torch and transformers to be installed."
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    return tokenizer, model


def _mean_pool(last_hidden_state, attention_mask):
    import torch

    expanded_mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed_embeddings = torch.sum(last_hidden_state * expanded_mask, dim=1)
    token_counts = torch.clamp(expanded_mask.sum(dim=1), min=1e-9)
    return summed_embeddings / token_counts


def _fit_embedding_dimensions(embedding: list[float]) -> list[float]:
    if len(embedding) == EMBEDDING_DIMENSIONS:
        return embedding
    if len(embedding) > EMBEDDING_DIMENSIONS:
        return embedding[:EMBEDDING_DIMENSIONS]
    return [*embedding, *([0.0] * (EMBEDDING_DIMENSIONS - len(embedding)))]


def _messages_to_prompt(messages: list[Message], temperature: float) -> str:
    rendered_messages = [
        f"{message.get('role', 'user').upper()}:\n{message.get('content', '')}"
        for message in messages
    ]
    return "\n\n".join([*rendered_messages, f"TEMPERATURE: {temperature}"])


def _write_json_schema(response_format: type[BaseModel]) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".schema.json", delete=False) as schema_file:
        schema_path = Path(schema_file.name)
        json.dump(_codex_output_schema(response_format), schema_file)
    return schema_path


def _codex_output_schema(response_format: type[BaseModel]) -> dict[str, Any]:
    schema = deepcopy(response_format.model_json_schema())
    _replace_properties_map(schema)
    _make_objects_strict(schema)
    return schema


def _replace_properties_map(schema: dict[str, Any]) -> None:
    extracted_fact = schema.get("$defs", {}).get("ExtractedFact")
    if not isinstance(extracted_fact, dict):
        return

    fact_properties = extracted_fact.get("properties")
    if not isinstance(fact_properties, dict) or "properties" not in fact_properties:
        return

    fact_properties["properties"] = {
        "title": "Properties",
        "description": "Structured fact metadata as key/value pairs.",
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "key": {"type": "string"},
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "null"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                },
            },
            "required": ["key", "value"],
        },
    }


def _make_objects_strict(schema: Any) -> None:
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            properties = schema.get("properties")
            if isinstance(properties, dict):
                schema["additionalProperties"] = False
                schema["required"] = list(properties)
        for value in schema.values():
            _make_objects_strict(value)
    elif isinstance(schema, list):
        for item in schema:
            _make_objects_strict(item)


# OpenAI provider kept for later reuse.
#
# import time
# from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
#
# MAX_EMBEDDING_BATCH_SIZE = 2048
# MAX_RETRY_ATTEMPTS = 3
#
#
# class OpenAILLMClient:
#     def __init__(self, api_key: str, model: str, client: OpenAI | None = None) -> None:
#         self.model = model
#         self._client = client or OpenAI(api_key=api_key)
#
#     def chat(self, messages: list[Message], temperature: float = 0.7) -> str:
#         response = _retry(
#             lambda: self._client.chat.completions.create(
#                 model=self.model,
#                 messages=messages,
#                 temperature=temperature,
#             )
#         )
#         content = response.choices[0].message.content
#         return content or ""
#
#     def chat_structured(
#         self,
#         messages: list[Message],
#         response_format: type[StructuredModel],
#         temperature: float = 0.3,
#     ) -> StructuredModel:
#         response = _retry(
#             lambda: self._client.beta.chat.completions.parse(
#                 model=self.model,
#                 messages=messages,
#                 response_format=response_format,
#                 temperature=temperature,
#             )
#         )
#         parsed = response.choices[0].message.parsed
#         if parsed is None:
#             raise ValueError("OpenAI structured response did not include parsed content")
#         return parsed
#
#     def get_embedding(
#         self,
#         text: str,
#         model: str = "text-embedding-3-small",
#     ) -> list[float]:
#         response = _retry(
#             lambda: self._client.embeddings.create(
#                 model=model,
#                 input=[text],
#             )
#         )
#         return response.data[0].embedding
#
#
# def _retry(operation: Any) -> Any:
#     last_error: Exception | None = None
#     for attempt in range(MAX_RETRY_ATTEMPTS):
#         try:
#             return operation()
#         except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as exc:
#             last_error = exc
#             if attempt == MAX_RETRY_ATTEMPTS - 1:
#                 break
#             time.sleep(2**attempt)
#
#     if last_error is not None:
#         raise last_error
#     raise RuntimeError("Retry operation failed without an exception")
