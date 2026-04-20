import subprocess
from pathlib import Path

import pytest

from jobctl.llm import client as llm_client_module
from jobctl.llm.client import (
    EMBEDDING_DIMENSIONS,
    LLMClient,
    _codex_output_schema,
    get_embedding,
    get_embeddings_batch,
)
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile, FitEvaluation


class FakeCodexRunner:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[dict] = []

    def __call__(
        self,
        prompt: str,
        output_schema: Path | None,
        model: str | None,
        cwd: Path | None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "output_schema": output_schema,
                "model": model,
                "cwd": cwd,
            }
        )
        return self.output


class FakeEmbedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        embeddings: list[list[float]] = []
        for text in texts:
            embedding = [0.0] * EMBEDDING_DIMENSIONS
            embedding[0] = float(len(text))
            embeddings.append(embedding)
        return embeddings


def test_get_embedding_uses_transformers_model(monkeypatch: pytest.MonkeyPatch) -> None:
    created_embedders: list[FakeEmbedder] = []

    llm_client_module._EMBEDDERS.clear()
    monkeypatch.setattr(
        llm_client_module,
        "TransformerEmbedder",
        lambda model_name: created_embedders.append(FakeEmbedder(model_name))
        or created_embedders[-1],
    )

    embedding = get_embedding("hello", model="local-test-model")

    assert created_embedders[0].model_name == "local-test-model"
    assert created_embedders[0].calls == [["hello"]]
    assert len(embedding) == EMBEDDING_DIMENSIONS
    assert embedding[0] == 5.0


def test_get_embedding_reuses_cached_transformers_model(monkeypatch: pytest.MonkeyPatch) -> None:
    load_count = 0

    def fake_loader(_model_name: str):
        nonlocal load_count
        load_count += 1
        return FakeEmbedder(_model_name)

    llm_client_module._EMBEDDERS.clear()
    monkeypatch.setattr(llm_client_module, "TransformerEmbedder", fake_loader)

    get_embedding("hello", model="local-test-model")
    get_embedding("world", model="local-test-model")

    assert load_count == 1


def test_get_embedding_is_deterministic_for_same_transformer_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_client_module._EMBEDDERS.clear()
    monkeypatch.setattr(
        llm_client_module,
        "TransformerEmbedder",
        lambda model_name: FakeEmbedder(model_name),
    )

    embedding = get_embedding("hello")

    assert embedding == get_embedding("hello")
    assert len(embedding) == EMBEDDING_DIMENSIONS


def test_get_embeddings_batch_uses_transformers_model(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_client_module._EMBEDDERS.clear()
    monkeypatch.setattr(
        llm_client_module,
        "TransformerEmbedder",
        lambda model_name: FakeEmbedder(model_name),
    )

    embeddings = get_embeddings_batch(["a", "b"])

    assert len(embeddings) == 2
    assert all(len(embedding) == EMBEDDING_DIMENSIONS for embedding in embeddings)


def test_llm_client_chat_uses_codex_runner_non_interactively() -> None:
    runner = FakeCodexRunner("hello\n")
    client = LLMClient(
        api_key="unused",
        model="gpt-5.4",
        cwd=Path("/tmp/project"),
        runner=runner,
    )
    messages = [{"role": "user", "content": "Say hello"}]

    assert client.chat(messages) == "hello"
    assert runner.calls[0]["output_schema"] is None
    assert runner.calls[0]["model"] == "gpt-5.4"
    assert runner.calls[0]["cwd"] == Path("/tmp/project")
    assert "USER:\nSay hello" in runner.calls[0]["prompt"]


def test_llm_client_chat_stream_yields_single_codex_response() -> None:
    runner = FakeCodexRunner("hello")
    client = LLMClient(api_key="unused", model="gpt-5.4", runner=runner)

    assert list(client.chat_stream([{"role": "user", "content": "Say hello"}])) == ["hello"]


def test_llm_client_chat_structured_returns_parsed_model() -> None:
    parsed_json = ExtractedProfile(
        facts=[
            ExtractedFact(
                entity_type="skill",
                entity_name="Python",
                relation=None,
                related_to=None,
                properties={},
                text_representation="Python",
            )
        ]
    ).model_dump_json()
    runner = FakeCodexRunner(parsed_json)
    client = LLMClient(api_key="unused", model="gpt-5.4", runner=runner)

    result = client.chat_structured(
        [{"role": "user", "content": "Extract"}],
        response_format=ExtractedProfile,
    )

    assert result.facts[0].entity_name == "Python"
    assert runner.calls[0]["output_schema"] is not None
    assert runner.calls[0]["output_schema"].exists() is False
    assert "Return only JSON" in runner.calls[0]["prompt"]


def test_llm_client_chat_structured_rejects_invalid_json() -> None:
    runner = FakeCodexRunner("not json")
    client = LLMClient(api_key="unused", model="gpt-5.4", runner=runner)

    with pytest.raises(ValueError):
        client.chat_structured([], response_format=ExtractedProfile)


def test_codex_output_schema_is_strict_for_extracted_profile() -> None:
    schema = _codex_output_schema(ExtractedProfile)
    fact_schema = schema["$defs"]["ExtractedFact"]
    properties_schema = fact_schema["properties"]["properties"]

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["facts"]
    assert fact_schema["additionalProperties"] is False
    assert fact_schema["required"] == [
        "entity_type",
        "entity_name",
        "relation",
        "related_to",
        "properties",
        "text_representation",
    ]
    assert properties_schema["type"] == "array"
    assert properties_schema["items"]["additionalProperties"] is False
    assert properties_schema["items"]["required"] == ["key", "value"]


def test_extracted_fact_accepts_structured_property_pairs() -> None:
    fact = ExtractedFact(
        entity_type="achievement",
        entity_name="Reduced latency",
        relation="achieved",
        related_to="Staff Engineer",
        properties=[{"key": "metric", "value": "40%"}],
        text_representation="Reduced latency by 40%",
    )

    assert fact.properties == {"metric": "40%"}


def test_run_codex_raises_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["codex", "exec"],
            stderr="invalid_json_schema",
        )

    monkeypatch.setattr(subprocess, "run", fail_run)
    client = LLMClient(api_key="unused", model="gpt-5.4")

    with pytest.raises(RuntimeError, match="invalid_json_schema"):
        client._run_codex("prompt", None, "gpt-5.4", Path("/tmp/project"))


def test_schema_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValueError):
        FitEvaluation(
            score=0.8,
            matching_strengths=[],
            gaps=[],
            recommendations=[],
            summary="Good fit",
            unknown=True,
        )
