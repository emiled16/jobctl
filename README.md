# jobctl

`jobctl` is a Python CLI for building a local career knowledge graph and using it to support job search workflows. It stores project data in a `.jobctl/` directory, persists graph data in SQLite, uses local Transformers embeddings for retrieval, and uses the local Codex CLI in non-interactive mode for LLM calls.

The project is under active implementation. The current working surface includes project initialization, config management, graph storage, resume/GitHub ingestion helpers, onboarding/yap conversation logic, job fetching, fit evaluation, resume and cover letter YAML generation, PDF rendering, an application tracker, and Textual TUI entry points.

## Requirements

- Python `3.12.8`
- `pyenv`
- `direnv` recommended
- Local `codex` binary available on `PATH`
- Native WeasyPrint libraries for PDF rendering
- Playwright Chromium for browser-based job page fallback
- Network access for first-time dependency and model downloads

The pinned Python version is in `.python-version`.

## Setup

```bash
pyenv install 3.12.8
pyenv local 3.12.8
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npx playwright install chromium
```

Verify the install:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

## Local Models

Chat and structured extraction use the local Codex CLI:

```bash
codex exec --help
```

Embeddings use Transformers locally. The default embedding model is:

```text
sentence-transformers/all-MiniLM-L6-v2
```

The first embedding call may download model files through Hugging Face. Embedding vectors are normalized and padded to `1536` dimensions to match the current SQLite vector table shape.

## Usage

Initialize a jobctl project in the current directory:

```bash
jobctl init
```

This creates:

```text
.jobctl/
├── config.yaml
├── exports/
└── templates/
```

View config:

```bash
jobctl config
```

Set a config value:

```bash
jobctl config llm_model gpt-5.4
```

Start yap mode:

```bash
jobctl yap
```

Yap mode lets you paste freeform notes about your experience. The LLM proposes facts, you confirm or edit them, and confirmed facts are added to the SQLite knowledge graph.

Start onboarding:

```bash
jobctl onboard
```

Evaluate a job and generate materials:

```bash
jobctl apply https://example.com/jobs/senior-engineer
```

Render a generated YAML file or an export directory:

```bash
jobctl render .jobctl/exports/2026-04-16-acme-senior-engineer/resume.yaml
jobctl render .jobctl/exports/2026-04-16-acme-senior-engineer
```

Open the tracker or profile TUI:

```bash
jobctl track
jobctl profile
```

Use logging flags before the subcommand:

```bash
jobctl --verbose apply ./sample-jd.txt
jobctl --quiet render .jobctl/exports/latest
```

## Implemented

- Click CLI with `init`, `config`, `onboard`, `yap`, `apply`, `render`, `track`, and `profile`
- `.jobctl/` project directory model
- Config load/save/discovery
- SQLite connection management and migrations
- Knowledge graph tables and CRUD operations
- Vector table initialization with sqlite-vec when available and SQLite fallback otherwise
- Local Transformers embedding client
- Local Codex CLI chat and structured-output client
- Pydantic schemas for extracted facts, job descriptions, fit evaluation, and proposed facts
- Resume text extraction for `.txt`, `.md`, `.pdf`, and `.docx`
- GitHub repository metadata ingestion helpers
- Onboarding coverage analysis and follow-up generation helpers
- Yap mode extraction, confirmation, and persistence loop
- Job description HTTP fetch, Playwright fallback, and structured extraction
- Fit evaluation against graph context
- Tailored resume and cover letter YAML generation with review/edit loops
- ATS-oriented HTML templates and WeasyPrint PDF rendering
- Application tracker tables and CRUD operations
- Apply pipeline orchestration
- Textual tracker and profile screens

## Configuration

`jobctl config` manages:

```text
openai_api_key      Kept for future OpenAI provider reuse; local Codex mode ignores it.
embedding_model     Local Transformers embedding model.
llm_model           Model name passed to `codex exec`.
default_template    Default resume template name.
```

## How It Works

`jobctl` stores career facts as typed graph nodes and relationship edges in SQLite. Resume, GitHub, onboarding, and yap inputs create or update this graph. Local Transformers embeddings are stored per node, then job descriptions are embedded and matched against graph nodes to retrieve relevant experience. The local Codex CLI produces structured job descriptions, fit evaluations, and tailored YAML materials. YAML is reviewed before rendering to PDF through HTML templates.

## Development

Run the full test suite:

```bash
.venv/bin/python -m pytest
```

Run linting and formatting checks:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Check Poetry metadata:

```bash
.venv/bin/poetry check --lock
```

## Data

Project data is local to each initialized directory:

```text
.jobctl/config.yaml
.jobctl/jobctl.db
.jobctl/exports/
.jobctl/templates/
```

The `.jobctl/` directory is ignored by git.
