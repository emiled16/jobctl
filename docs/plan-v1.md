# jobctl — Implementation Plan

## Project Overview

`jobctl` is a Python CLI tool with a TUI interface (Textual) that acts as an AI-powered job search assistant. It ingests professional documents (resumes, GitHub repos) and conducts conversations to build a knowledge graph of the user's career, stored in SQLite with vector embeddings via `sqlite-vec`. When given a job URL, it fetches the job description, evaluates fit, and generates ATS-optimized, tailored resumes and cover letters as reviewable YAML files rendered to PDF via HTML templates. It tracks all applications in a built-in CRM. The LLM backend is GPT-5.4 via OpenAI API. Data is stored in a project-directory model (`.jobctl/` folder, similar to `.git/`).

---

## Milestone 1: Project Scaffolding and CLI Skeleton

### Task 1.1: Initialize Python project with `pyproject.toml` and dependency list

Create the repository root with a `pyproject.toml` using `hatchling` or `setuptools` as build backend. Define the project metadata (name: `jobctl`, version: `0.1.0`, Python `>=3.11`). Add all known dependencies with version pins: `textual`, `openai`, `httpx`, `playwright`, `pyyaml`, `pygithub`, `weasyprint`, `sqlite-vec`, `click`, `rich`. Add a `[project.scripts]` entry so `jobctl` maps to `jobctl.cli:main`. Create a `.gitignore` covering Python, IDE, and `.jobctl/` data directories.

### Task 1.2: Create package directory structure with empty modules

Create the following directory tree under `src/jobctl/`:

```
src/jobctl/
├── __init__.py
├── cli.py            # Click CLI entry point
├── config.py         # Config loading/saving
├── db/
│   ├── __init__.py
│   ├── connection.py # SQLite connection manager
│   ├── graph.py      # Knowledge graph CRUD
│   └── vectors.py    # sqlite-vec embedding operations
├── ingestion/
│   ├── __init__.py
│   ├── resume.py     # Resume file parsing
│   └── github.py     # GitHub repo ingestion
├── conversation/
│   ├── __init__.py
│   ├── onboard.py    # Onboarding conversation logic
│   └── yap.py        # Freeform yap mode logic
├── jobs/
│   ├── __init__.py
│   ├── fetcher.py    # JD fetching pipeline
│   ├── evaluator.py  # Fit evaluation
│   └── tracker.py    # Job tracker CRUD
├── generation/
│   ├── __init__.py
│   ├── resume.py     # Resume YAML generation
│   ├── cover_letter.py # Cover letter YAML generation
│   └── renderer.py   # YAML -> HTML -> PDF rendering
├── llm/
│   ├── __init__.py
│   └── client.py     # OpenAI API wrapper
└── tui/
    ├── __init__.py
    ├── app.py         # Textual App root
    ├── tracker_view.py
    └── profile_view.py
```

Each file should contain a module docstring and no other content.

### Task 1.3: Implement Click CLI entry point with top-level command group

In `src/jobctl/cli.py`, implement the `main()` function as a `click.Group`. Register subcommands as stubs (each prints "not implemented yet"): `init`, `onboard`, `yap`, `apply`, `track`, `profile`, `render`, `config`. Ensure `jobctl --help` displays all commands with one-line descriptions. Verify the entry point works via `pip install -e .` and running `jobctl --help`.

### Task 1.4: Implement `jobctl init` command that scaffolds the `.jobctl/` directory

In the `init` subcommand, create the `.jobctl/` directory structure in the current working directory:

```
.jobctl/
├── config.yaml
├── templates/
│   └── (empty, populated later)
└── exports/
```

Generate a default `config.yaml` with fields: `openai_api_key: ""`, `embedding_model: "text-embedding-3-small"`, `llm_model: "gpt-5.4"`, `default_template: "resume.html"`. If `.jobctl/` already exists, print an error and exit. After creation, print a success message indicating next step (`jobctl config` to set API key).

### Task 1.5: Implement `config.py` for loading, validating, and saving `config.yaml`

Create a `JobctlConfig` dataclass with fields: `openai_api_key: str`, `embedding_model: str`, `llm_model: str`, `default_template: str`. Implement `load_config(project_root: Path) -> JobctlConfig` that reads `.jobctl/config.yaml`, validates required fields, and returns the dataclass. Implement `save_config(project_root: Path, config: JobctlConfig) -> None`. Implement `find_project_root(start: Path) -> Path` that walks up from `start` looking for a `.jobctl/` directory (like git does). Raise `ProjectNotFoundError` if none found.

### Task 1.6: Implement `jobctl config` command for viewing and setting config values

In the `config` subcommand, accept optional arguments `key` and `value`. If no arguments, pretty-print the current config (masking the API key except last 4 chars). If `key` and `value` provided, update that field in `config.yaml` and save. Validate that `key` is a known config field. Use `config.py` functions for load/save.

---

## Milestone 2: SQLite Database and Knowledge Graph Schema

### Task 2.1: Implement SQLite connection manager with migration support

In `src/jobctl/db/connection.py`, implement `get_connection(db_path: Path) -> sqlite3.Connection` that opens (or creates) `jobctl.db`, enables WAL mode and foreign keys, and runs any pending migrations. Implement a simple migration system: a `_migrations` table tracks applied migration names; migration files are Python functions in a list ordered by version. The connection manager applies any unapplied migrations on startup.

### Task 2.2: Create migration for knowledge graph tables (nodes and edges)

Write migration `001_create_graph_tables` that creates:

- `nodes` table: `id TEXT PRIMARY KEY`, `type TEXT NOT NULL` (person, company, role, project, skill, achievement, education, story), `name TEXT NOT NULL`, `properties TEXT` (JSON blob for flexible attributes like dates, descriptions, metrics), `text_representation TEXT NOT NULL` (human-readable string used for embedding), `created_at TEXT`, `updated_at TEXT`. Index on `type`.
- `edges` table: `id TEXT PRIMARY KEY`, `source_id TEXT NOT NULL REFERENCES nodes(id)`, `target_id TEXT NOT NULL REFERENCES nodes(id)`, `relation TEXT NOT NULL` (worked_at, held_role, used_skill, etc.), `properties TEXT` (JSON blob for attributes like start_date, end_date), `created_at TEXT`. Index on `source_id`, `target_id`, `relation`.

### Task 2.3: Implement graph CRUD operations in `graph.py`

In `src/jobctl/db/graph.py`, implement:

- `add_node(conn, type, name, properties, text_representation) -> node_id` — inserts a node, generates UUID for id, returns it.
- `add_edge(conn, source_id, target_id, relation, properties) -> edge_id` — inserts an edge.
- `get_node(conn, node_id) -> dict` — returns a single node.
- `get_nodes_by_type(conn, type) -> list[dict]` — returns all nodes of a given type.
- `get_edges_from(conn, node_id) -> list[dict]` — returns all outgoing edges and their target nodes.
- `get_edges_to(conn, node_id) -> list[dict]` — returns all incoming edges and their source nodes.
- `get_subgraph(conn, node_id, depth=2) -> dict` — BFS traversal from a node up to `depth` hops, returns all reachable nodes and edges.
- `update_node(conn, node_id, **kwargs)` — updates specified fields.
- `delete_node(conn, node_id)` — deletes node and all its edges.
- `search_nodes(conn, type=None, name_contains=None) -> list[dict]` — filtered search.

### Task 2.4: Write unit tests for graph CRUD operations

Create `tests/test_graph.py`. Test all functions from Task 2.3 using an in-memory SQLite database. Test cases: insert node and retrieve by id, insert edge and verify foreign key, `get_subgraph` with depth=1 and depth=2, `search_nodes` with type filter, `delete_node` cascades to edges, `update_node` changes fields and `updated_at`.

---

## Milestone 3: Vector Storage with sqlite-vec

### Task 3.1: Implement sqlite-vec initialization and embedding table

In `src/jobctl/db/vectors.py`, implement `init_vec(conn)` that loads the `sqlite-vec` extension and creates a virtual table: `CREATE VIRTUAL TABLE IF NOT EXISTS node_embeddings USING vec0(node_id TEXT PRIMARY KEY, embedding float[1536])` (1536 dimensions for `text-embedding-3-small`). Call `init_vec` from the connection manager after migrations.

### Task 3.2: Implement OpenAI embedding client wrapper

In `src/jobctl/llm/client.py`, implement `get_embedding(text: str, model: str = "text-embedding-3-small") -> list[float]` that calls `openai.embeddings.create()` and returns the embedding vector. Also implement `get_embeddings_batch(texts: list[str], model: str) -> list[list[float]]` for batch embedding (OpenAI supports up to 2048 inputs per call). Handle rate limiting with exponential backoff.

### Task 3.3: Implement vector upsert and similarity search functions

In `src/jobctl/db/vectors.py`, implement:

- `upsert_embedding(conn, node_id: str, embedding: list[float]) -> None` — inserts or replaces the embedding for a node in the `node_embeddings` virtual table.
- `search_similar(conn, query_embedding: list[float], top_k: int = 10, type_filter: str | None = None) -> list[tuple[str, float]]` — performs KNN search against `node_embeddings`, optionally joining with `nodes` table to filter by type. Returns list of `(node_id, distance)` tuples ordered by ascending distance.
- `delete_embedding(conn, node_id: str) -> None` — removes an embedding.

### Task 3.4: Implement `embed_node` and `embed_all_nodes` orchestration functions

In `src/jobctl/db/vectors.py`, implement:

- `embed_node(conn, node_id: str, llm_client) -> None` — reads the node's `text_representation` from the `nodes` table, calls `get_embedding()`, and upserts into `node_embeddings`.
- `embed_all_nodes(conn, llm_client) -> int` — finds all nodes that are missing from `node_embeddings` (LEFT JOIN), batch-embeds them using `get_embeddings_batch()`, upserts all. Returns count of newly embedded nodes. This is used after bulk ingestion.

### Task 3.5: Write unit tests for vector storage operations

Create `tests/test_vectors.py`. Use an in-memory SQLite database with sqlite-vec loaded. Test: `upsert_embedding` inserts and retrieves, `search_similar` returns correct ordering for known vectors (use simple hand-crafted 1536-dim vectors with known distances), `delete_embedding` removes entry, `search_similar` with `type_filter` only returns matching types.

---

## Milestone 4: LLM Client and Prompt Infrastructure

### Task 4.1: Implement OpenAI chat completion wrapper with structured output support

In `src/jobctl/llm/client.py`, implement `LLMClient` class. Constructor takes `api_key` and `model` from config. Methods:

- `chat(messages: list[dict], temperature: float = 0.7) -> str` — calls `openai.chat.completions.create()`, returns the assistant message content.
- `chat_structured(messages: list[dict], response_format: type[BaseModel], temperature: float = 0.3) -> BaseModel` — uses OpenAI structured outputs (response_format parameter) to return a parsed Pydantic model.
- `chat_stream(messages: list[dict], temperature: float = 0.7) -> Iterator[str]` — streaming variant, yields chunks.

Handle API errors with retries (3 attempts, exponential backoff).

### Task 4.2: Create Pydantic models for LLM-structured extraction schemas

Create `src/jobctl/llm/schemas.py`. Define Pydantic models:

- `ExtractedFact`: `entity_type: str`, `entity_name: str`, `relation: str | None`, `related_to: str | None`, `properties: dict`, `text_representation: str`
- `ExtractedProfile`: `facts: list[ExtractedFact]` — used when ingesting a resume or GitHub repo
- `ExtractedJD`: `title: str`, `company: str`, `location: str`, `compensation: str | None`, `requirements: list[str]`, `responsibilities: list[str]`, `qualifications: list[str]`, `nice_to_haves: list[str]`, `raw_text: str`
- `FitEvaluation`: `score: float`, `matching_strengths: list[str]`, `gaps: list[str]`, `recommendations: list[str]`, `summary: str`
- `ProposedFact`: `fact: ExtractedFact`, `confidence: float`, `source_quote: str` — used in yap mode for user confirmation

---

## Milestone 5: Resume Ingestion

### Task 5.1: Implement resume file reader supporting PDF, DOCX, and plain text

In `src/jobctl/ingestion/resume.py`, implement `read_resume(file_path: Path) -> str` that detects format by extension and extracts plain text:

- `.txt` / `.md`: read directly
- `.pdf`: use `pymupdf` (fitz) to extract text
- `.docx`: use `python-docx` to extract paragraph text

Return the full text content as a string. Raise `UnsupportedFormatError` for unknown extensions.

### Task 5.2: Implement LLM-based fact extraction from resume text

In `src/jobctl/ingestion/resume.py`, implement `extract_facts_from_resume(resume_text: str, llm_client: LLMClient) -> ExtractedProfile`. Build a system prompt instructing the LLM to decompose a resume into structured facts: for each role, extract the company (Company node), the role title (Role node), dates, skills used (Skill nodes), achievements with metrics (Achievement nodes), education (Education node), and the relationships between them. Use `llm_client.chat_structured()` with the `ExtractedProfile` schema. Return the parsed result.

### Task 5.3: Implement fact-to-graph persistence with user confirmation loop

In `src/jobctl/ingestion/resume.py`, implement `persist_facts(conn, facts: list[ExtractedFact], llm_client, interactive: bool = True) -> int`. For each fact:

1. If `interactive`, print the fact (formatted with Rich) and prompt the user: `[Y]es / [n]o / [e]dit`.
2. On "yes": create the node(s) and edge in the graph via `graph.py` functions, then call `embed_node()` for each new node.
3. On "edit": open the fact as YAML in `$EDITOR` (or inline prompt), re-parse, then persist.
4. On "no": skip.

Return count of persisted facts.

### Task 5.4: Write integration test for resume ingestion pipeline

Create `tests/test_resume_ingestion.py`. Use a sample resume text (hardcoded markdown string with 2 roles, 3 skills, 1 education entry). Mock the `LLMClient` to return a predefined `ExtractedProfile`. Verify that `persist_facts` (with `interactive=False`) creates the correct number of nodes and edges in an in-memory database, and that `embed_node` is called for each node.

---

## Milestone 6: GitHub Ingestion

### Task 6.1: Implement GitHub API client for repo metadata and file fetching

In `src/jobctl/ingestion/github.py`, implement `GitHubFetcher` class. Constructor takes an optional GitHub token from config. Methods:

- `get_user_repos(username: str) -> list[dict]` — calls GitHub API `/users/{username}/repos`, returns list of dicts with `name`, `description`, `language`, `languages_url`, `stargazers_count`, `forks_count`, `html_url`, `created_at`, `updated_at`.
- `get_repo_detail(owner: str, repo: str) -> dict` — fetches repo metadata + README content (via `/repos/{owner}/{repo}/readme`, base64-decoded) + languages breakdown (via `/repos/{owner}/{repo}/languages`) + list of top-level files (via `/repos/{owner}/{repo}/contents/`).
- `get_file_content(owner: str, repo: str, path: str) -> str` — fetches a specific file's content.

Use `httpx` for requests. Handle 404s and rate limiting.

### Task 6.2: Implement LLM-based fact extraction from GitHub repo data

In `src/jobctl/ingestion/github.py`, implement `extract_facts_from_repo(repo_detail: dict, llm_client: LLMClient) -> ExtractedProfile`. Build a prompt that provides the repo name, description, README content, languages, stars, and key file names. Instruct the LLM to extract: a Project node (with description, purpose, scale indicators), Skill nodes for each technology used, Achievement nodes if the README mentions metrics or adoption, and edges connecting them. Use `chat_structured()` with `ExtractedProfile`. Return the result.

### Task 6.3: Implement `ingest_github` orchestration function

In `src/jobctl/ingestion/github.py`, implement `ingest_github(conn, username_or_urls: list[str], llm_client, interactive: bool = True) -> int`. If input is a username, call `get_user_repos()` and let the user select which repos to ingest (checkbox list via Rich prompts). If input is specific URLs, parse owner/repo from each. For each selected repo, call `get_repo_detail()`, then `extract_facts_from_repo()`, then `persist_facts()` (from resume.py, reused). Return total count of persisted facts.

---

## Milestone 7: Onboarding Conversation

### Task 7.1: Implement graph coverage analyzer to identify profile gaps

In `src/jobctl/conversation/onboard.py`, implement `analyze_coverage(conn) -> dict`. Query the graph and compute:

- `roles_count`: number of Role nodes
- `has_education`: bool
- `skills_count`: number of Skill nodes
- `achievements_count`: number of Achievement nodes
- `roles_without_achievements`: list of Role nodes that have no outgoing `achieved` edges
- `roles_without_skills`: list of Role nodes with no `used_skill` edges
- `has_stories`: bool (any Story nodes exist)
- `missing_sections`: list of strings naming what's absent (e.g., "education", "achievements", "stories")

Return the dict. This drives the follow-up question generation.

### Task 7.2: Implement follow-up question generator based on coverage gaps

In `src/jobctl/conversation/onboard.py`, implement `generate_followup(conn, llm_client, coverage: dict) -> str`. Build a prompt that includes the current coverage summary and a serialized list of existing nodes (names + types). Instruct the LLM to generate the single most valuable follow-up question to deepen the profile, prioritizing: roles missing achievements > roles missing skills > no stories > no education > general depth. Return the question string.

### Task 7.3: Implement onboarding conversation loop

In `src/jobctl/conversation/onboard.py`, implement `run_onboarding(conn, llm_client, config) -> None`. Flow:

1. Ask if user has a resume file to ingest. If yes, call `read_resume()` + `extract_facts_from_resume()` + `persist_facts()`.
2. Ask if user has GitHub repos. If yes, call `ingest_github()`.
3. Enter follow-up loop: call `analyze_coverage()`, if gaps exist call `generate_followup()` and print the question. Read user's answer. Pass answer to LLM with `chat_structured()` using `ExtractedProfile` schema to extract new facts. Call `persist_facts()` with confirmation. Repeat until user types `done` or coverage is complete (all sections present, no roles missing achievements).
4. Print a summary: total nodes and edges created, sections covered.

### Task 7.4: Wire `jobctl onboard` CLI command to the onboarding loop

In `src/jobctl/cli.py`, update the `onboard` subcommand to: find project root, load config, validate API key is set, open DB connection, call `run_onboarding()`. Handle `KeyboardInterrupt` gracefully (save progress, print count of facts added so far).

---

## Milestone 8: Yap Mode

### Task 8.1: Implement freeform text fact extraction with proposed facts

In `src/jobctl/conversation/yap.py`, implement `extract_proposed_facts(text: str, existing_context: str, llm_client: LLMClient) -> list[ProposedFact]`. Build a prompt that includes the user's freeform text and a summary of what's already in the graph (`existing_context`). Instruct the LLM to identify any new factual claims about the user's professional experience, returning a list of `ProposedFact` objects (each with the extracted fact, confidence score, and the source quote from the user's text). Use `chat_structured()`.

### Task 8.2: Implement yap conversation loop with confirm/reject flow

In `src/jobctl/conversation/yap.py`, implement `run_yap(conn, llm_client) -> None`. Flow:

1. Print instructions: "Talk about your experience. The AI will extract facts. Type `done` to exit."
2. Loop: read multiline input from user (until blank line). Generate `existing_context` by serializing the current graph nodes (names + types, truncated to fit context). Call `extract_proposed_facts()`.
3. For each `ProposedFact`, display it formatted with Rich (fact summary, confidence, source quote) and prompt `[Y]es / [n]o / [e]dit`. Persist confirmed facts to graph + embed.
4. After each round, the AI generates a brief acknowledgment or asks a natural follow-up based on what the user said (using `llm_client.chat()`).
5. On `done`, print summary of facts added this session.

### Task 8.3: Wire `jobctl yap` CLI command to the yap loop

In `src/jobctl/cli.py`, update the `yap` subcommand to: find project root, load config, open DB connection, call `run_yap()`. Handle `KeyboardInterrupt` gracefully.

---

## Milestone 9: Job Description Fetching

### Task 9.1: Implement HTTP-based JD page fetcher with content detection

In `src/jobctl/jobs/fetcher.py`, implement `fetch_jd_http(url: str) -> str | None`. Use `httpx.AsyncClient` (with reasonable timeout of 15s, follow redirects, browser-like User-Agent) to GET the URL. If the response is HTML with less than 500 characters of visible text (stripped of tags), return `None` (indicates JS-rendered page). Otherwise return the raw HTML. Handle connection errors, timeouts, and non-200 status codes by returning `None`.

### Task 9.2: Implement Playwright-based JD page fetcher as fallback

In `src/jobctl/jobs/fetcher.py`, implement `fetch_jd_browser(url: str) -> str | None`. Launch Playwright Chromium headless, navigate to the URL, wait for `networkidle`, extract `page.content()`. Close the browser. Return the HTML. Handle Playwright errors by returning `None`. This is only called when `fetch_jd_http` returns `None`.

### Task 9.3: Implement LLM-based JD extraction from raw HTML

In `src/jobctl/jobs/fetcher.py`, implement `extract_jd(html: str, llm_client: LLMClient) -> ExtractedJD`. Strip the HTML to reduce token count (remove `<script>`, `<style>`, `<nav>`, `<footer>` tags and their content using a simple regex or `html.parser`). Pass the cleaned HTML to `llm_client.chat_structured()` with the `ExtractedJD` schema. The prompt instructs the LLM to extract title, company, location, compensation, requirements, responsibilities, qualifications, and nice-to-haves. Return the parsed `ExtractedJD`.

### Task 9.4: Implement unified `fetch_and_parse_jd` pipeline with paste fallback

In `src/jobctl/jobs/fetcher.py`, implement `fetch_and_parse_jd(url_or_text: str, llm_client: LLMClient) -> ExtractedJD`. Flow:

1. If input looks like a URL (starts with `http`), try `fetch_jd_http()`.
2. If that returns `None`, try `fetch_jd_browser()`.
3. If that also returns `None`, print "Could not fetch that page. Paste the job description:" and read multiline input.
4. If input was not a URL, treat it as pasted JD text directly.
5. Call `extract_jd()` on the HTML or raw text.
6. Print a summary of the extracted JD (title, company, location) for user verification.
7. Return the `ExtractedJD`.

---

## Milestone 10: Fit Evaluation

### Task 10.1: Implement graph-based experience retrieval for a given JD

In `src/jobctl/jobs/evaluator.py`, implement `retrieve_relevant_experience(conn, jd: ExtractedJD, llm_client) -> dict`. Steps:

1. Concatenate JD requirements + responsibilities into a single string.
2. Call `get_embedding()` on that string.
3. Call `search_similar()` with the query embedding, `top_k=20`.
4. For each matched node, call `get_subgraph(conn, node_id, depth=1)` to pull its immediate context.
5. Deduplicate and merge all subgraphs into a single dict with keys `nodes` and `edges`.
6. Return the merged subgraph.

### Task 10.2: Implement fit evaluation using LLM with retrieved context

In `src/jobctl/jobs/evaluator.py`, implement `evaluate_fit(jd: ExtractedJD, relevant_experience: dict, llm_client) -> FitEvaluation`. Build a prompt with:

- The full `ExtractedJD` serialized as YAML
- The `relevant_experience` subgraph serialized as a readable list of facts
- Instructions to evaluate fit on a 1-10 scale, list matching strengths (with specific evidence from the graph), identify gaps, and provide recommendations for how to position the application.

Use `chat_structured()` with `FitEvaluation` schema. Return the result.

### Task 10.3: Implement fit evaluation display with Rich formatting

In `src/jobctl/jobs/evaluator.py`, implement `display_evaluation(jd: ExtractedJD, evaluation: FitEvaluation) -> None`. Use Rich to print a formatted panel:

- Header: job title @ company, location
- Score: large colored number (green >=7, yellow 4-6, red <4)
- Strengths: bulleted list in green
- Gaps: bulleted list in yellow
- Recommendations: bulleted list in blue
- Summary paragraph

---

## Milestone 11: Resume YAML Generation

### Task 11.1: Define the resume YAML schema and create a Pydantic model

Create `src/jobctl/generation/schemas.py`. Define `ResumeYAML` Pydantic model:

```python
class ContactInfo(BaseModel):
    name: str
    email: str
    phone: str | None
    location: str | None
    linkedin: str | None
    github: str | None
    website: str | None

class ExperienceEntry(BaseModel):
    company: str
    title: str
    start_date: str
    end_date: str | None
    bullets: list[str]  # action-verb-led, quantified

class EducationEntry(BaseModel):
    institution: str
    degree: str
    field: str | None
    end_date: str | None
    details: list[str] | None

class ResumeYAML(BaseModel):
    contact: ContactInfo
    summary: str  # 2-3 sentence professional summary
    experience: list[ExperienceEntry]
    skills: dict[str, list[str]]  # category -> list of skills
    education: list[EducationEntry]
    certifications: list[str] | None
    projects: list[dict] | None  # name, description, url
```

Also define `CoverLetterYAML`:

```python
class CoverLetterYAML(BaseModel):
    recipient: str | None
    company: str
    role: str
    opening: str
    body_paragraphs: list[str]
    closing: str
```

### Task 11.2: Implement tailored resume YAML generation from graph context

In `src/jobctl/generation/resume.py`, implement `generate_resume_yaml(jd: ExtractedJD, relevant_experience: dict, evaluation: FitEvaluation, llm_client) -> ResumeYAML`. Build a prompt with:

- The JD requirements (from `ExtractedJD`)
- The relevant experience subgraph (serialized)
- The fit evaluation (strengths and gaps)
- ATS best-practice instructions: use standard section headings, lead bullets with action verbs, quantify achievements, incorporate JD keywords naturally, order bullets by relevance to this JD, include only skills that are relevant to the role, write a summary that positions the candidate for this specific role.

Use `chat_structured()` with `ResumeYAML` schema. Return the result.

### Task 11.3: Implement YAML file writing and review workflow

In `src/jobctl/generation/resume.py`, implement `save_and_review(resume: ResumeYAML, output_dir: Path) -> Path`. Steps:

1. Serialize `ResumeYAML` to YAML using `pyyaml` with `default_flow_style=False`.
2. Write to `output_dir/resume.yaml`.
3. Print the YAML to the terminal with Rich syntax highlighting.
4. Prompt: "Review the YAML above. [c]ontinue to PDF / [e]dit in $EDITOR / [r]egenerate"
5. On "edit": open the file in `$EDITOR` (or `vi`), wait for close, re-read and re-validate with Pydantic.
6. On "regenerate": return `None` (caller will re-run generation).
7. On "continue": return the file path.

---

## Milestone 12: Cover Letter Generation

### Task 12.1: Implement tailored cover letter YAML generation

In `src/jobctl/generation/cover_letter.py`, implement `generate_cover_letter_yaml(jd: ExtractedJD, relevant_experience: dict, evaluation: FitEvaluation, llm_client) -> CoverLetterYAML`. Build a prompt with the JD, relevant experience, and evaluation. Instruct the LLM to write a concise cover letter (3-4 paragraphs) that: opens with genuine interest in the specific role/company, maps 2-3 of the candidate's strongest relevant experiences to the JD's top requirements, addresses 1 gap constructively (if any), and closes with a call to action. Use `chat_structured()` with `CoverLetterYAML`. Return the result.

### Task 12.2: Implement cover letter YAML save and review workflow

In `src/jobctl/generation/cover_letter.py`, implement `save_and_review_cover_letter(cover_letter: CoverLetterYAML, output_dir: Path) -> Path | None`. Same flow as Task 11.3 but writes to `output_dir/cover-letter.yaml`. Reuse the same review prompt pattern.

---

## Milestone 13: PDF Rendering

### Task 13.1: Create ATS-optimized HTML/CSS resume template

Create `src/jobctl/templates/resume.html` as a Jinja2 template. Design:

- Single-column layout, 8.5x11 format with 0.5in margins
- Fonts: system fonts (Arial/Helvetica fallback for ATS compatibility)
- Sections: Contact (centered header), Summary, Experience, Skills (2-column grid of category: skills), Education, Certifications, Projects
- All content is real HTML text (no images, no CSS columns that break PDF extraction)
- Template variables match `ResumeYAML` fields: `{{ contact.name }}`, `{% for entry in experience %}`, etc.
- Clean, professional appearance with subtle horizontal rules between sections

### Task 13.2: Create HTML/CSS cover letter template

Create `src/jobctl/templates/cover-letter.html` as a Jinja2 template. Simple professional letter format: date, recipient (if known), company, salutation, body paragraphs, closing, name. Same font and margin conventions as the resume template.

### Task 13.3: Implement YAML-to-HTML-to-PDF rendering pipeline

In `src/jobctl/generation/renderer.py`, implement `render_pdf(yaml_path: Path, template_name: str, output_path: Path) -> Path`. Steps:

1. Read and parse the YAML file into the appropriate Pydantic model (`ResumeYAML` or `CoverLetterYAML`, detected by filename).
2. Load the corresponding Jinja2 template from the project's `.jobctl/templates/` directory, falling back to the bundled templates in `src/jobctl/templates/`.
3. Render the template with the YAML data.
4. Convert HTML to PDF using WeasyPrint (`weasyprint.HTML(string=html).write_pdf(output_path)`).
5. Return the output path.

### Task 13.4: Implement `jobctl render` CLI command

In `src/jobctl/cli.py`, update the `render` subcommand. Accept a `path` argument (path to a YAML file). Determine whether it's a resume or cover letter by filename. Call `render_pdf()`. Print the output PDF path. If `path` is a directory, render all YAML files found in it.

### Task 13.5: Copy bundled templates into `.jobctl/templates/` during `jobctl init`

Update the `init` subcommand (Task 1.4) to copy the bundled `resume.html` and `cover-letter.html` templates from the package's `templates/` directory into `.jobctl/templates/`. This lets users customize templates per project.

---

## Milestone 14: Job Tracker CRM

### Task 14.1: Create migration for job tracker tables

Write migration `002_create_tracker_tables`:

- `applications` table: `id TEXT PRIMARY KEY`, `company TEXT NOT NULL`, `role TEXT NOT NULL`, `url TEXT`, `status TEXT NOT NULL DEFAULT 'evaluated'`, `fit_score REAL`, `location TEXT`, `compensation TEXT`, `jd_raw TEXT` (full JD text), `jd_structured TEXT` (ExtractedJD as JSON), `resume_yaml_path TEXT`, `cover_letter_yaml_path TEXT`, `resume_pdf_path TEXT`, `cover_letter_pdf_path TEXT`, `notes TEXT`, `recruiter_name TEXT`, `recruiter_email TEXT`, `recruiter_linkedin TEXT`, `follow_up_date TEXT`, `created_at TEXT`, `updated_at TEXT`. Index on `status`, `company`.
- `application_events` table: `id TEXT PRIMARY KEY`, `application_id TEXT REFERENCES applications(id)`, `event_type TEXT NOT NULL` (e.g., "created", "status_changed", "note_added", "materials_generated"), `description TEXT`, `created_at TEXT`. Index on `application_id`.

### Task 14.2: Implement tracker CRUD operations in `tracker.py`

In `src/jobctl/jobs/tracker.py`, implement:

- `create_application(conn, company, role, url, jd: ExtractedJD, evaluation: FitEvaluation) -> str` — inserts application row with status "evaluated", stores JD as JSON, stores fit score. Also inserts a "created" event. Returns application id.
- `update_status(conn, app_id, new_status) -> None` — validates status is in allowed set, updates row, inserts "status_changed" event.
- `update_application(conn, app_id, **kwargs) -> None` — updates any fields (notes, recruiter info, comp, follow-up date, file paths). Inserts appropriate event.
- `get_application(conn, app_id) -> dict` — returns full application with its events.
- `list_applications(conn, status_filter=None, sort_by="created_at") -> list[dict]` — returns all applications, optionally filtered and sorted.
- `get_timeline(conn, app_id) -> list[dict]` — returns all events for an application ordered by date.

### Task 14.3: Write unit tests for tracker CRUD operations

Create `tests/test_tracker.py`. Test: create application and verify fields, update status through valid transitions, reject invalid status values, update notes and verify event is logged, `list_applications` with and without status filter, `get_timeline` returns events in order.

---

## Milestone 15: Apply Pipeline Orchestration

### Task 15.1: Implement end-to-end apply pipeline function

In `src/jobctl/jobs/apply_pipeline.py`, implement `run_apply(conn, url_or_text: str, llm_client, config) -> str`. This orchestrates the full flow:

1. Call `fetch_and_parse_jd(url_or_text, llm_client)` → `ExtractedJD`
2. Call `retrieve_relevant_experience(conn, jd, llm_client)` → subgraph
3. Call `evaluate_fit(jd, subgraph, llm_client)` → `FitEvaluation`
4. Call `display_evaluation(jd, evaluation)`
5. Prompt: "Generate tailored materials? [y/n]". If no, still create tracker entry and return.
6. Create output directory: `.jobctl/exports/{date}-{company_slug}/`
7. Call `generate_resume_yaml()` → `ResumeYAML`
8. Call `save_and_review()`. If user chose "regenerate", loop back to step 7.
9. Ask "Generate cover letter? [y/n]". If yes, call `generate_cover_letter_yaml()` + `save_and_review_cover_letter()`.
10. Call `render_pdf()` for each YAML file.
11. Call `create_application()` with all paths and data. Update status to "materials_ready".
12. Print summary: output paths, tracker entry created.
13. Return application id.

### Task 15.2: Wire `jobctl apply` CLI command to the apply pipeline

In `src/jobctl/cli.py`, update the `apply` subcommand. Accept a positional argument `url` (optional). If not provided, prompt for URL or pasted JD. Find project root, load config, open DB, call `run_apply()`. Handle `KeyboardInterrupt` by saving partial progress to tracker with status "evaluated".

---

## Milestone 16: TUI — Tracker View

### Task 16.1: Implement Textual App shell with navigation structure

In `src/jobctl/tui/app.py`, implement `JobctlApp(App)` extending Textual's `App` class. Define the base layout: a header with app name and project path, a footer with key bindings, and a content area. Define screen routing: `TrackerScreen` and `ProfileScreen` as separate screens, switchable via keybindings (`t` for tracker, `p` for profile, `q` to quit). Set a dark theme (Catppuccin Mocha or similar).

### Task 16.2: Implement tracker list view as a DataTable

In `src/jobctl/tui/tracker_view.py`, implement `TrackerScreen(Screen)`. On mount, query `list_applications()` and populate a Textual `DataTable` widget with columns: Company, Role, Status, Score, Date, Location, Follow-up. Color-code the Status column by value (green for offer, yellow for interviewing, gray for applied, red for rejected). Support sorting by clicking column headers. Support filtering by status via a `Select` widget at the top.

### Task 16.3: Implement tracker detail panel for a selected application

In `src/jobctl/tui/tracker_view.py`, add a detail panel that appears when a row is selected (Enter key). The panel shows: full JD text (scrollable), fit evaluation summary, file paths (resume/cover letter YAML and PDF), recruiter contact info, notes (editable TextArea), follow-up date, and timeline of events. Keybinding `s` opens a status change dropdown. Keybinding `n` focuses the notes textarea. Changes are saved to the database on blur/exit.

### Task 16.4: Wire `jobctl track` CLI command to launch the TUI

In `src/jobctl/cli.py`, update the `track` subcommand to: find project root, load config, open DB connection, instantiate `JobctlApp` with the connection, and call `app.run()`.

---

## Milestone 17: TUI — Profile View

### Task 17.1: Implement profile summary view showing graph statistics

In `src/jobctl/tui/profile_view.py`, implement `ProfileScreen(Screen)`. On mount, query the graph and display a summary panel: total nodes by type (e.g., "12 Skills, 4 Roles, 3 Companies, 8 Achievements"), total edges, last updated timestamp. Below the summary, show a `Tree` widget with top-level nodes grouped by type. Expanding a node shows its properties and connected edges.

### Task 17.2: Implement node detail and inline editing in profile view

In `src/jobctl/tui/profile_view.py`, add a detail panel for a selected node (Enter key). Shows: node type, name, all properties (as key-value pairs), text representation, connected nodes (with relationship labels). Keybindings: `e` to edit (opens properties as YAML in an inline TextArea), `d` to delete (with confirmation dialog), `a` to add a new node (form with type, name, properties fields). All mutations save to DB and re-embed the affected node.

### Task 17.3: Wire `jobctl profile` CLI command to launch the TUI

In `src/jobctl/cli.py`, update the `profile` subcommand to: find project root, load config, open DB connection, instantiate `JobctlApp` starting on the `ProfileScreen`, and call `app.run()`.

---

## Milestone 18: End-to-End Testing and Polish

### Task 18.1: Write end-to-end test for the full `init -> onboard -> apply` flow

Create `tests/test_e2e.py`. Using a temporary directory, run `jobctl init`, mock the LLM client throughout, call the onboarding pipeline with a sample resume text, verify graph is populated, then call the apply pipeline with a sample JD text, verify YAML and PDF files are created, verify a tracker entry exists with status "materials_ready".

### Task 18.2: Add `--verbose` and `--quiet` flags to the CLI root

In `src/jobctl/cli.py`, add `--verbose` (enables debug logging including LLM prompts/responses) and `--quiet` (suppresses all output except errors and essential prompts) flags to the `main` group. Configure Python `logging` accordingly. Pass the log level through to all subcommands.

### Task 18.3: Add error handling and user-friendly messages for common failures

Audit all modules for unhandled exceptions. Add specific error handling for:

- Missing or invalid API key: clear message pointing to `jobctl config`
- Network failures during JD fetch: fall back to paste with explanation
- OpenAI API errors (rate limit, invalid model): human-readable error with suggestion
- SQLite errors: message suggesting `jobctl init` if DB doesn't exist
- Missing Playwright browsers: message with `npx playwright install chromium` command

### Task 18.4: Write a README with installation instructions and usage examples

Create a `README.md` covering: one-line description, installation (`pip install .` + `npx playwright install chromium`), quickstart walkthrough (`init` → `config` → `onboard` → `apply`), all CLI commands with examples, configuration reference, project directory structure explanation, and a "How it works" section describing the knowledge graph + embedding approach.

---

## Summary

| Milestone | Tasks | Focus |
|---|---|---|
| 1. Scaffolding | 6 | Project setup, CLI skeleton, config |
| 2. Graph Schema | 4 | SQLite tables, CRUD operations |
| 3. Vectors | 5 | sqlite-vec, embeddings, similarity search |
| 4. LLM Client | 2 | OpenAI wrapper, Pydantic schemas |
| 5. Resume Ingestion | 4 | Parse resume, extract facts, persist |
| 6. GitHub Ingestion | 3 | GitHub API, extract facts, orchestrate |
| 7. Onboarding | 4 | Coverage analysis, Q&A loop, CLI wiring |
| 8. Yap Mode | 3 | Freeform capture, confirm/reject, CLI wiring |
| 9. JD Fetching | 4 | HTTP fetch, Playwright fallback, LLM extraction |
| 10. Fit Evaluation | 3 | Graph retrieval, LLM evaluation, display |
| 11. Resume Generation | 3 | YAML schema, LLM generation, review workflow |
| 12. Cover Letter | 2 | LLM generation, review workflow |
| 13. PDF Rendering | 5 | HTML templates, WeasyPrint pipeline, CLI |
| 14. Job Tracker | 3 | DB schema, CRUD, tests |
| 15. Apply Pipeline | 2 | End-to-end orchestration, CLI wiring |
| 16. TUI Tracker | 4 | Textual app, list view, detail panel |
| 17. TUI Profile | 3 | Graph summary, node editing, CLI wiring |
| 18. Polish | 4 | E2E tests, logging, error handling, README |

**Total: 64 tasks across 18 milestones**
