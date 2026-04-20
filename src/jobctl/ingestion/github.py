"""GitHub repository ingestion."""

from __future__ import annotations

import base64
import logging
import sqlite3
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.prompt import Confirm, Prompt

from jobctl.core.events import (
    AsyncEventBus,
    IngestDoneEvent,
    IngestErrorEvent,
    IngestProgressEvent,
)
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.ingestion.resume import _EXTRACTED_PROFILE_SCHEMA_GUIDANCE, persist_facts
from jobctl.llm.schemas import ExtractedProfile

logger = logging.getLogger(__name__)


GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubError(RuntimeError):
    """Raised when GitHub API requests fail."""


class GitHubFetcher:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = client or httpx.Client(
            base_url=GITHUB_API_BASE_URL,
            headers=headers,
            timeout=30.0,
        )

    def get_user_repos(self, username: str) -> list[dict]:
        response = self._request("GET", f"/users/{username}/repos", params={"per_page": 100})
        repos = response.json()
        return [
            {
                "name": repo["name"],
                "description": repo.get("description"),
                "language": repo.get("language"),
                "languages_url": repo.get("languages_url"),
                "stargazers_count": repo.get("stargazers_count", 0),
                "forks_count": repo.get("forks_count", 0),
                "html_url": repo.get("html_url"),
                "created_at": repo.get("created_at"),
                "updated_at": repo.get("updated_at"),
            }
            for repo in repos
        ]

    def get_repo_detail(self, owner: str, repo: str) -> dict:
        repo_data = self._request("GET", f"/repos/{owner}/{repo}").json()
        languages = self._request("GET", f"/repos/{owner}/{repo}/languages").json()
        contents = self._request("GET", f"/repos/{owner}/{repo}/contents/").json()
        readme = self._get_readme(owner, repo)
        top_level_files = [
            item["name"] for item in contents if item.get("type") == "file" and "name" in item
        ]

        return {
            "owner": owner,
            "name": repo_data["name"],
            "full_name": repo_data["full_name"],
            "description": repo_data.get("description"),
            "language": repo_data.get("language"),
            "languages": languages,
            "stargazers_count": repo_data.get("stargazers_count", 0),
            "forks_count": repo_data.get("forks_count", 0),
            "html_url": repo_data.get("html_url"),
            "created_at": repo_data.get("created_at"),
            "updated_at": repo_data.get("updated_at"),
            "readme": readme,
            "top_level_files": top_level_files,
        }

    def get_file_content(self, owner: str, repo: str, path: str) -> str:
        data = self._request("GET", f"/repos/{owner}/{repo}/contents/{path}").json()
        return _decode_content(data)

    def _get_readme(self, owner: str, repo: str) -> str:
        try:
            data = self._request("GET", f"/repos/{owner}/{repo}/readme").json()
        except GitHubError as exc:
            if "not found" in str(exc).lower():
                return ""
            raise
        return _decode_content(data)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code == 404:
            raise GitHubError(f"GitHub resource not found: {path}")
        if response.status_code in {403, 429}:
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining == "0" or response.status_code == 429:
                raise GitHubError("GitHub rate limit exceeded")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubError(f"GitHub request failed: {exc.response.status_code}") from exc
        return response


def extract_facts_from_repo(repo_detail: dict, llm_client) -> ExtractedProfile:
    messages = [
        {
            "role": "system",
            "content": (
                "Extract career knowledge graph facts from GitHub repository metadata. Create "
                "a Project fact, Skill facts for technologies, Achievement facts for metrics "
                "or adoption, and relations connecting skills and achievements to the project.\n\n"
                + _EXTRACTED_PROFILE_SCHEMA_GUIDANCE
            ),
        },
        {
            "role": "user",
            "content": (
                f"Repository: {repo_detail.get('full_name', repo_detail.get('name'))}\n"
                f"Description: {repo_detail.get('description')}\n"
                f"Languages: {repo_detail.get('languages')}\n"
                f"Stars: {repo_detail.get('stargazers_count')}\n"
                f"Forks: {repo_detail.get('forks_count')}\n"
                f"Files: {repo_detail.get('top_level_files')}\n\n"
                f"README:\n{repo_detail.get('readme', '')}"
            ),
        },
    ]
    return llm_client.chat_structured(messages, response_format=ExtractedProfile)


def ingest_github(
    conn: sqlite3.Connection,
    username_or_urls: list[str],
    llm_client,
    interactive: bool = True,
    fetcher: GitHubFetcher | None = None,
    *,
    bus: AsyncEventBus | None = None,
    store: BackgroundJobStore | None = None,
    job_id: str | None = None,
    preselected_repos: list[tuple[str, str]] | None = None,
) -> int:
    """Ingest GitHub repositories, optionally with event-bus progress reporting.

    When ``bus`` / ``store`` / ``job_id`` are provided:

    * Already-ingested repos (by ``owner/name`` + ``updated_at``) are skipped.
    * Progress events are published per-repo.
    * Rich prompts are bypassed; the caller is expected to pass an explicit
      ``preselected_repos`` list assembled from :class:`MultiSelectList`.
    """
    fetcher = fetcher or GitHubFetcher()
    if preselected_repos is not None:
        repos = list(preselected_repos)
    else:
        repos = _resolve_repositories(username_or_urls, fetcher, interactive)

    persisted_count = 0
    total = len(repos)
    for index, (owner, repo) in enumerate(repos, start=1):
        external_id = f"{owner}/{repo}"
        try:
            repo_detail = fetcher.get_repo_detail(owner, repo)
        except Exception as exc:  # noqa: BLE001
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("github fetch failed for %s", external_id)
            else:
                logger.error("github fetch failed for %s: %s", external_id, exc)
            if bus is not None:
                bus.publish(IngestErrorEvent(source="github", error=str(exc), job_id=job_id))
            continue

        updated_at = repo_detail.get("updated_at")
        if (
            store is not None
            and job_id is not None
            and store.is_item_seen(job_id, external_id=external_id, external_updated_at=updated_at)
        ):
            if bus is not None:
                bus.publish(
                    IngestProgressEvent(
                        source="github",
                        current=index,
                        total=total,
                        message=f"{external_id} (skipped)",
                        job_id=job_id,
                    )
                )
            continue

        try:
            profile = extract_facts_from_repo(repo_detail, llm_client)
            persisted_count += persist_facts(
                conn,
                profile.facts,
                llm_client,
                interactive=interactive and bus is None,
                bus=bus,
                store=store,
                job_id=job_id,
            )
            if store is not None and job_id is not None:
                store.mark_item_done(
                    job_id,
                    external_id=external_id,
                    external_updated_at=updated_at,
                )
        except Exception as exc:  # noqa: BLE001
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("github persist failed for %s", external_id)
            else:
                logger.error("github persist failed for %s: %s", external_id, exc)
            if bus is not None:
                bus.publish(IngestErrorEvent(source="github", error=str(exc), job_id=job_id))
            continue

        if bus is not None:
            bus.publish(
                IngestProgressEvent(
                    source="github",
                    current=index,
                    total=total,
                    message=external_id,
                    job_id=job_id,
                )
            )

    if bus is not None:
        bus.publish(IngestDoneEvent(source="github", facts_added=persisted_count, job_id=job_id))
    return persisted_count


def _resolve_repositories(
    username_or_urls: list[str],
    fetcher: GitHubFetcher,
    interactive: bool,
) -> list[tuple[str, str]]:
    if not username_or_urls:
        return []

    selected_repos: list[tuple[str, str]] = []
    usernames: list[str] = []
    for value in username_or_urls:
        if _looks_like_url(value):
            parsed_url = _parse_github_url(value)
            if isinstance(parsed_url, tuple):
                selected_repos.append(parsed_url)
            else:
                usernames.append(parsed_url)
        else:
            usernames.append(value)

    for username in usernames:
        repos = fetcher.get_user_repos(username)
        if interactive:
            selected_repos.extend(_prompt_for_repos(username, repos))
        else:
            selected_repos.extend((username, repo["name"]) for repo in repos)

    return selected_repos


def _prompt_for_repos(username: str, repos: list[dict]) -> list[tuple[str, str]]:
    console = Console()
    selected_repos: list[tuple[str, str]] = []
    for index, repo in enumerate(repos, start=1):
        console.print(f"{index}. {repo['name']} - {repo.get('description') or 'No description'}")

    if Confirm.ask("Ingest all repositories?", default=False):
        return [(username, repo["name"]) for repo in repos]

    selection = Prompt.ask("Enter repository numbers to ingest, separated by commas", default="")
    selected_indexes = {
        int(value.strip())
        for value in selection.split(",")
        if value.strip().isdigit() and 1 <= int(value.strip()) <= len(repos)
    }
    for index in sorted(selected_indexes):
        selected_repos.append((username, repos[index - 1]["name"]))
    return selected_repos


def _parse_repo_url(url: str) -> tuple[str, str]:
    parsed_url = _parse_github_url(url)
    if not isinstance(parsed_url, tuple):
        raise ValueError(f"Invalid GitHub repository URL: {url}")
    return parsed_url


def _parse_github_url(url: str) -> str | tuple[str, str]:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.netloc.lower().removeprefix("www.") != "github.com" or not path_parts:
        raise ValueError(f"Invalid GitHub URL: {url}")
    if len(path_parts) == 1:
        return path_parts[0]
    return path_parts[0], path_parts[1].removesuffix(".git")


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _decode_content(data: dict) -> str:
    content = data.get("content")
    if not content:
        return ""
    encoding = data.get("encoding")
    if encoding != "base64":
        raise GitHubError(f"Unsupported GitHub content encoding: {encoding}")
    return base64.b64decode(content).decode("utf-8", errors="replace")
