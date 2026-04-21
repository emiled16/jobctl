"""Regression tests for the Apply node's LLM shim.

The shim used to call ``provider.chat(...)`` and then parse the text as JSON,
which made JD extraction fragile for gated/noisy pages where the model
returned partial or non-JSON content. The shim must now delegate to the
provider's native ``chat_structured`` when available so OpenAI-style
structured outputs are used.
"""

from __future__ import annotations

from typing import Any

from jobctl.agent.nodes.apply_node import _build_shim
from jobctl.llm.schemas import ExtractedJD


class _StructuredProvider:
    def __init__(self, jd: ExtractedJD) -> None:
        self._jd = jd
        self.structured_calls: list[tuple[list[dict[str, Any]], type]] = []
        self.chat_calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.chat_calls.append(list(messages))
        return {"content": "should-not-be-used"}

    def chat_structured(self, messages, *, response_format):
        self.structured_calls.append((list(messages), response_format))
        return self._jd

    def embed(self, texts):
        return [[0.0] for _ in texts]


class _TextOnlyProvider:
    def __init__(self, content: str) -> None:
        self._content = content
        self.chat_calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.chat_calls.append(list(messages))
        return {"content": self._content}

    def embed(self, texts):
        return [[0.0] for _ in texts]


class _SchemaRefusingProvider:
    """Mimics an OpenAI provider that rejects strict schema (e.g. ResumeYAML)."""

    def __init__(self, fallback_content: str) -> None:
        self._content = fallback_content
        self.structured_calls: int = 0
        self.chat_calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, **kwargs):
        self.chat_calls.append(list(messages))
        return {"content": self._content}

    def chat_structured(self, messages, *, response_format):
        self.structured_calls += 1
        raise RuntimeError(
            "400 - Invalid schema for response_format: Extra required key 'sections' supplied."
        )

    def embed(self, texts):
        return [[0.0] for _ in texts]


def _jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build systems"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="Senior Engineer at Acme",
    )


def test_shim_uses_native_chat_structured_when_available() -> None:
    provider = _StructuredProvider(_jd())
    shim = _build_shim(provider)  # type: ignore[arg-type]

    result = shim.chat_structured(
        [{"role": "user", "content": "extract jd"}],
        response_format=ExtractedJD,
    )

    assert result.title == "Senior Engineer"
    assert len(provider.structured_calls) == 1
    assert provider.chat_calls == []


def test_shim_falls_back_to_json_parse_when_no_chat_structured() -> None:
    provider = _TextOnlyProvider(
        '{"title": "Senior Engineer", "company": "Acme", "location": "Remote", '
        '"compensation": null, "requirements": [], "responsibilities": [], '
        '"qualifications": [], "nice_to_haves": [], "raw_text": "x"}'
    )
    shim = _build_shim(provider)  # type: ignore[arg-type]

    result = shim.chat_structured([], response_format=ExtractedJD)

    assert result.company == "Acme"


def test_shim_fallback_coerces_null_fields_via_schema_validators() -> None:
    provider = _TextOnlyProvider(
        '{"title": null, "company": "Acme", "location": null, "compensation": null, '
        '"requirements": null, "responsibilities": null, "qualifications": null, '
        '"nice_to_haves": null, "raw_text": null}'
    )
    shim = _build_shim(provider)  # type: ignore[arg-type]

    result = shim.chat_structured([], response_format=ExtractedJD)

    assert result.title == ""
    assert result.requirements == []


def test_shim_falls_back_to_json_chat_when_provider_refuses_schema() -> None:
    """OpenAI strict mode rejects complex schemas like ResumeYAML. The shim
    must degrade gracefully to plain chat + JSON parse instead of failing
    the whole Apply job."""
    jd_json = (
        '{"title": "Senior Engineer", "company": "Acme", "location": "Remote", '
        '"compensation": null, "requirements": ["Python"], "responsibilities": [], '
        '"qualifications": [], "nice_to_haves": [], "raw_text": "x"}'
    )
    provider = _SchemaRefusingProvider(jd_json)
    shim = _build_shim(provider)  # type: ignore[arg-type]

    result = shim.chat_structured(
        [{"role": "user", "content": "extract"}], response_format=ExtractedJD
    )

    assert result.title == "Senior Engineer"
    assert provider.structured_calls == 1
    assert len(provider.chat_calls) == 1
    assert any(
        "JSON schema" in msg.get("content", "") for msg in provider.chat_calls[0]
    )


def test_shim_fallback_strips_markdown_code_fences() -> None:
    fenced = (
        "```json\n"
        '{"title": "SE", "company": "Acme", "location": "Remote", "compensation": null, '
        '"requirements": [], "responsibilities": [], "qualifications": [], '
        '"nice_to_haves": [], "raw_text": "x"}\n'
        "```"
    )
    provider = _TextOnlyProvider(fenced)
    shim = _build_shim(provider)  # type: ignore[arg-type]

    result = shim.chat_structured([], response_format=ExtractedJD)

    assert result.title == "SE"
    assert result.company == "Acme"
