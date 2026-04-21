import httpx
import pytest

from jobctl.jobs import fetcher
from jobctl.llm.schemas import ExtractedJD


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    def chat_structured(self, messages: list[dict], response_format: type) -> ExtractedJD:
        self.messages.append(messages)
        assert response_format is ExtractedJD
        return ExtractedJD(
            title="Senior Engineer",
            company="Acme",
            location="Remote",
            compensation=None,
            requirements=["Python"],
            responsibilities=["Build systems"],
            qualifications=["5 years experience"],
            nice_to_haves=["SQLite"],
            raw_text=messages[1]["content"],
        )


def test_fetch_jd_http_returns_html_for_visible_job_page() -> None:
    html = _html_with_visible_text("Senior Engineer role", repeat=80)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )
    )

    assert fetcher.fetch_jd_http("https://example.com/job", transport=transport) == html


def test_fetch_jd_http_returns_none_for_thin_or_failed_pages() -> None:
    thin_transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>Hi</p>"
        )
    )
    failed_transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    json_transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"content-type": "application/json"}, json={})
    )

    assert fetcher.fetch_jd_http("https://example.com/thin", transport=thin_transport) is None
    assert fetcher.fetch_jd_http("https://example.com/fail", transport=failed_transport) is None
    assert fetcher.fetch_jd_http("https://example.com/json", transport=json_transport) is None


def test_extract_jd_cleans_html_before_structured_extraction() -> None:
    llm_client = FakeLLMClient()
    html = """
    <html>
      <script>var secret = "remove me";</script>
      <nav>Navigation</nav>
      <main><h1>Senior Engineer</h1><p>Build Python systems.</p></main>
      <footer>Footer</footer>
    </html>
    """

    jd = fetcher.extract_jd(html, llm_client)

    content = llm_client.messages[0][1]["content"]
    assert jd.title == "Senior Engineer"
    assert "Build Python systems" in content
    assert "remove me" not in content
    assert "Navigation" not in content
    assert "Footer" not in content


def test_fetch_and_parse_jd_uses_http_then_browser_fallback(monkeypatch) -> None:
    llm_client = FakeLLMClient()
    calls: list[str] = []

    def fake_http(url: str) -> None:
        calls.append(f"http:{url}")
        return None

    def fake_browser(url: str) -> str:
        calls.append(f"browser:{url}")
        return "<main>Senior Engineer Python role with enough text.</main>"

    monkeypatch.setattr(fetcher, "fetch_jd_http", fake_http)
    monkeypatch.setattr(fetcher, "fetch_jd_browser", fake_browser)

    jd = fetcher.fetch_and_parse_jd("https://example.com/job", llm_client)

    assert jd.company == "Acme"
    assert calls == ["http:https://example.com/job", "browser:https://example.com/job"]


def test_fetch_and_parse_jd_uses_paste_fallback(monkeypatch) -> None:
    llm_client = FakeLLMClient()
    monkeypatch.setattr(fetcher, "fetch_jd_http", lambda _url: None)
    monkeypatch.setattr(fetcher, "fetch_jd_browser", lambda _url: None)
    monkeypatch.setattr(fetcher, "_read_multiline_input", lambda: "Pasted Senior Engineer JD")

    jd = fetcher.fetch_and_parse_jd("https://example.com/job", llm_client)

    assert jd.title == "Senior Engineer"
    assert "Pasted Senior Engineer JD" in jd.raw_text


def test_fetch_and_parse_jd_treats_non_url_as_pasted_text(monkeypatch) -> None:
    llm_client = FakeLLMClient()
    monkeypatch.setattr(
        fetcher,
        "fetch_jd_http",
        lambda _url: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    jd = fetcher.fetch_and_parse_jd("Senior Engineer pasted JD", llm_client)

    assert jd.title == "Senior Engineer"
    assert "Senior Engineer pasted JD" in jd.raw_text


def test_extracted_jd_coerces_null_values_from_noisy_pages() -> None:
    jd = ExtractedJD.model_validate(
        {
            "title": None,
            "company": "Acme",
            "location": None,
            "compensation": None,
            "requirements": None,
            "responsibilities": None,
            "qualifications": [],
            "nice_to_haves": [],
            "raw_text": None,
        }
    )

    assert jd.title == ""
    assert jd.location == ""
    assert jd.raw_text == ""
    assert jd.requirements == []
    assert jd.responsibilities == []


def test_extract_jd_raises_when_page_has_no_usable_content() -> None:
    class _EmptyClient:
        def chat_structured(self, messages: list[dict], response_format: type) -> ExtractedJD:
            return ExtractedJD.model_validate(
                {
                    "title": None,
                    "company": None,
                    "location": None,
                    "compensation": None,
                    "requirements": None,
                    "responsibilities": None,
                    "qualifications": None,
                    "nice_to_haves": None,
                    "raw_text": None,
                }
            )

    html = "<html><body><main>Gated content; nothing useful here.</main></body></html>"

    with pytest.raises(ValueError, match="paste the full job description"):
        fetcher.extract_jd(html, _EmptyClient())


def _html_with_visible_text(text: str, repeat: int) -> str:
    return f"<html><body><main>{' '.join([text] * repeat)}</main></body></html>"
