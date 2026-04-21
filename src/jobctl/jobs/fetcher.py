"""Job description fetching pipeline."""

import re
from html.parser import HTMLParser

import anyio
import httpx
from rich.console import Console

from jobctl.llm.schemas import ExtractedJD


HTTP_TIMEOUT_SECONDS = 15.0
MIN_VISIBLE_TEXT_LENGTH = 500
MAX_CLEANED_HTML_CHARS = 20_000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

console = Console()


def fetch_jd_http(url: str, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    return anyio.run(_fetch_jd_http, url, transport)


async def _fetch_jd_http(
    url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            transport=transport,
        ) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return None
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return None
        html = response.text
        if len(_visible_text(html)) < MIN_VISIBLE_TEXT_LENGTH:
            return None
        return html
    except httpx.HTTPError:
        return None


def fetch_jd_browser(url: str) -> str | None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("Playwright is not installed; falling back to pasted job description.")
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="networkidle", timeout=int(HTTP_TIMEOUT_SECONDS * 1000))
                return page.content()
            finally:
                browser.close()
    except PlaywrightTimeoutError:
        console.print("Timed out fetching the job page in a browser.")
        return None
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
            console.print("Missing Playwright browser. Run `npx playwright install chromium`.")
        else:
            console.print("Browser fetch failed; falling back to pasted job description.")
        return None


def extract_jd(html: str, llm_client) -> ExtractedJD:
    cleaned_text = _clean_html_for_llm(html)
    messages = [
        {
            "role": "system",
            "content": (
                "Extract a structured job description from the provided page text. Return title, "
                "company, location, compensation when present, requirements, responsibilities, "
                "qualifications, nice-to-haves, and raw_text. Preserve factual details and do "
                "not invent missing fields. If a field is not present in the page, return an "
                "empty string for text fields and an empty array for list fields (never null)."
            ),
        },
        {"role": "user", "content": cleaned_text},
    ]
    jd = llm_client.chat_structured(messages, response_format=ExtractedJD)
    if not (jd.title.strip() or jd.company.strip()):
        raise ValueError(
            "Could not extract a usable job description from that page. "
            "The page may be gated or dynamically rendered. "
            "Re-run Apply and paste the full job description text instead."
        )
    return jd


def fetch_and_parse_jd(url_or_text: str, llm_client) -> ExtractedJD:
    source = url_or_text.strip()
    if _looks_like_url(source):
        html = fetch_jd_http(source)
        if html is None:
            html = fetch_jd_browser(source)
        if html is None:
            console.print("Could not fetch that page. Paste the job description:")
            html = _read_multiline_input()
    else:
        html = source

    jd = extract_jd(html, llm_client)
    console.print(f"Extracted JD: {jd.title} @ {jd.company} ({jd.location})")
    return jd


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _read_multiline_input() -> str:
    lines: list[str] = []
    while True:
        line = console.input("")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _clean_html_for_llm(html: str) -> str:
    stripped = re.sub(
        r"<(script|style|nav|footer|noscript|svg|header)\b[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    visible_text = _visible_text(stripped)
    return visible_text[:MAX_CLEANED_HTML_CHARS]


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "nav", "footer", "noscript", "svg", "header"}:
            self._ignored_tags.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tags and self._ignored_tags[-1] == tag.lower():
            self._ignored_tags.pop()

    def handle_data(self, data: str) -> None:
        if not self._ignored_tags:
            self.parts.append(data)
