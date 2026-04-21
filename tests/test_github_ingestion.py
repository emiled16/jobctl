import base64
import sqlite3
from pathlib import Path

import httpx
import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import get_nodes_by_type
from jobctl.ingestion.github import GitHubError, GitHubFetcher, ingest_github
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile


class FakeLLMClient:
    def __init__(self) -> None:
        self.embedded_texts: list[str] = []
        self.repo_prompts: list[str] = []
        self.system_prompts: list[str] = []

    def get_embedding(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [0.0] * 1536

    def chat_structured(self, messages: list[dict], response_format: type) -> ExtractedProfile:
        self.system_prompts.append(messages[0]["content"])
        self.repo_prompts.append(messages[1]["content"])
        assert response_format is ExtractedProfile
        return ExtractedProfile(
            facts=[
                ExtractedFact(
                    entity_type="Project",
                    entity_name="repo",
                    relation=None,
                    related_to=None,
                    properties={},
                    text_representation="repo project",
                )
            ]
        )


class FakeFetcher:
    def __init__(self) -> None:
        self.details_requested: list[tuple[str, str]] = []
        self.usernames_requested: list[str] = []

    def get_repo_detail(self, owner: str, repo: str) -> dict:
        self.details_requested.append((owner, repo))
        return {
            "full_name": f"{owner}/{repo}",
            "name": repo,
            "description": "A useful project",
            "languages": {"Python": 1000},
            "stargazers_count": 3,
            "forks_count": 1,
            "top_level_files": ["README.md"],
            "readme": "Built with Python",
        }

    def get_user_repos(self, username: str) -> list[dict]:
        self.usernames_requested.append(username)
        return [{"name": "repo-a"}, {"name": "repo-b"}]


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_github_fetcher_reads_repo_detail_and_decodes_content() -> None:
    readme = base64.b64encode(b"# README").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/repo":
            return httpx.Response(
                200,
                json={
                    "name": "repo",
                    "full_name": "acme/repo",
                    "description": "desc",
                    "language": "Python",
                    "stargazers_count": 5,
                    "forks_count": 2,
                    "html_url": "https://github.com/acme/repo",
                    "created_at": "2024-01-01",
                    "updated_at": "2024-02-01",
                },
            )
        if request.url.path == "/repos/acme/repo/languages":
            return httpx.Response(200, json={"Python": 100})
        if request.url.path == "/repos/acme/repo/contents/":
            return httpx.Response(200, json=[{"type": "file", "name": "README.md"}])
        if request.url.path == "/repos/acme/repo/readme":
            return httpx.Response(200, json={"encoding": "base64", "content": readme})
        raise AssertionError(request.url.path)

    client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    fetcher = GitHubFetcher(client=client)

    detail = fetcher.get_repo_detail("acme", "repo")

    assert detail["full_name"] == "acme/repo"
    assert detail["languages"] == {"Python": 100}
    assert detail["readme"] == "# README"
    assert detail["top_level_files"] == ["README.md"]


def test_github_fetcher_raises_not_found() -> None:
    client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )
    fetcher = GitHubFetcher(client=client)

    with pytest.raises(GitHubError, match="not found"):
        fetcher.get_user_repos("missing")


def test_ingest_github_from_urls_persists_extracted_facts(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    fetcher = FakeFetcher()
    llm_client = FakeLLMClient()

    persisted_count = ingest_github(
        conn,
        ["https://github.com/acme/repo"],
        llm_client,
        interactive=False,
        fetcher=fetcher,
        vector_store=fake_vector_store,
    )

    assert persisted_count == 1
    assert fetcher.details_requested == [("acme", "repo")]
    assert get_nodes_by_type(conn, "project")[0]["name"] == "repo"
    assert llm_client.embedded_texts == ["repo project"]
    assert "entity_type" in llm_client.system_prompts[0]
    assert "Do not use legacy keys like type, name" in llm_client.system_prompts[0]


def test_ingest_github_username_uses_all_repos_when_noninteractive(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    fetcher = FakeFetcher()
    llm_client = FakeLLMClient()

    persisted_count = ingest_github(
        conn,
        ["acme"],
        llm_client,
        interactive=False,
        fetcher=fetcher,
        vector_store=fake_vector_store,
    )

    assert persisted_count == 2
    assert fetcher.details_requested == [("acme", "repo-a"), ("acme", "repo-b")]
    assert fetcher.usernames_requested == ["acme"]


def test_ingest_github_profile_url_uses_all_repos_when_noninteractive(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    fetcher = FakeFetcher()
    llm_client = FakeLLMClient()

    persisted_count = ingest_github(
        conn,
        ["https://github.com/acme"],
        llm_client,
        interactive=False,
        fetcher=fetcher,
        vector_store=fake_vector_store,
    )

    assert persisted_count == 2
    assert fetcher.details_requested == [("acme", "repo-a"), ("acme", "repo-b")]
    assert fetcher.usernames_requested == ["acme"]


def test_ingest_github_mixes_profile_and_repo_urls(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    fetcher = FakeFetcher()
    llm_client = FakeLLMClient()

    persisted_count = ingest_github(
        conn,
        ["https://github.com/acme", "https://github.com/other/repo.git"],
        llm_client,
        interactive=False,
        fetcher=fetcher,
        vector_store=fake_vector_store,
    )

    assert persisted_count == 3
    assert fetcher.details_requested == [
        ("other", "repo"),
        ("acme", "repo-a"),
        ("acme", "repo-b"),
    ]
    assert fetcher.usernames_requested == ["acme"]
