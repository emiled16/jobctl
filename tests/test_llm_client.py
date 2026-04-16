from dataclasses import dataclass
from typing import Any

import pytest

from jobctl.llm.client import LLMClient, get_embedding, get_embeddings_batch
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile, FitEvaluation


@dataclass
class EmbeddingItem:
    embedding: list[float]


@dataclass
class EmbeddingResponse:
    data: list[EmbeddingItem]


@dataclass
class Message:
    content: str | None = None
    parsed: Any = None


@dataclass
class Choice:
    message: Message | None = None
    delta: Message | None = None


@dataclass
class CompletionResponse:
    choices: list[Choice]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, model: str, input: list[str]) -> EmbeddingResponse:
        self.calls.append({"model": model, "input": input})
        return EmbeddingResponse(
            data=[EmbeddingItem([float(index)]) for index, _ in enumerate(input)]
        )


class FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        stream: bool = False,
    ) -> CompletionResponse | list[CompletionResponse]:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": stream,
            }
        )
        if stream:
            return [
                CompletionResponse(choices=[Choice(delta=Message(content="hel"))]),
                CompletionResponse(choices=[Choice(delta=Message(content="lo"))]),
            ]
        return CompletionResponse(choices=[Choice(message=Message(content="hello"))])


class FakeParsedCompletions:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    def parse(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response_format: type[Any],
        temperature: float,
    ) -> CompletionResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "temperature": temperature,
            }
        )
        return CompletionResponse(choices=[Choice(message=Message(parsed=self.parsed))])


class FakeClient:
    def __init__(self, parsed: Any | None = None) -> None:
        self.embeddings = FakeEmbeddings()
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()
        parsed_completions = FakeParsedCompletions(parsed)
        beta_chat = type("BetaChat", (), {"completions": parsed_completions})()
        self.beta = type("Beta", (), {"chat": beta_chat})()


def test_get_embedding_calls_openai_embeddings_client() -> None:
    fake_client = FakeClient()

    embedding = get_embedding("hello", model="text-embedding-3-small", client=fake_client)

    assert embedding == [0.0]
    assert fake_client.embeddings.calls == [{"model": "text-embedding-3-small", "input": ["hello"]}]


def test_get_embeddings_batch_splits_at_openai_limit() -> None:
    fake_client = FakeClient()
    texts = [str(index) for index in range(2049)]

    embeddings = get_embeddings_batch(texts, model="embedding-model", client=fake_client)

    assert len(embeddings) == 2049
    assert [len(call["input"]) for call in fake_client.embeddings.calls] == [2048, 1]


def test_llm_client_chat_and_stream() -> None:
    fake_client = FakeClient()
    client = LLMClient(api_key="sk-test", model="gpt-5.4", client=fake_client)
    messages = [{"role": "user", "content": "Say hello"}]

    assert client.chat(messages) == "hello"
    assert "".join(client.chat_stream(messages)) == "hello"


def test_llm_client_chat_structured_returns_parsed_model() -> None:
    parsed = ExtractedProfile(
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
    )
    fake_client = FakeClient(parsed=parsed)
    client = LLMClient(api_key="sk-test", model="gpt-5.4", client=fake_client)

    result = client.chat_structured(
        [{"role": "user", "content": "Extract"}],
        response_format=ExtractedProfile,
    )

    assert result == parsed


def test_llm_client_chat_structured_rejects_missing_parsed_content() -> None:
    fake_client = FakeClient(parsed=None)
    client = LLMClient(api_key="sk-test", model="gpt-5.4", client=fake_client)

    with pytest.raises(ValueError, match="parsed content"):
        client.chat_structured([], response_format=ExtractedProfile)


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
