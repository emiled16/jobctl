# jobctl

`jobctl` is a Python CLI for building a local career knowledge graph and using it to support job search workflows. It stores project data in a `.jobctl/` directory, persists graph data in SQLite, uses local Transformers embeddings for retrieval, and uses the local Codex CLI in non-interactive mode for LLM calls.

The project is under active implementation. The current working surface includes project initialization, config management, graph storage, resume/GitHub ingestion helpers, onboarding/yap conversation logic, and the `jobctl yap` CLI command. Job fetching, fit evaluation, material generation, rendering, and the tracker CRM are still planned.

## Requirements

- Python `3.12.8`
- `pyenv`
- `direnv` recommended
- Local `codex` binary available on `PATH`
- Network access for first-time dependency and model downloads

The pinned Python version is in `.python-version`.

## Setup

```bash
pyenv install 3.12.8
pyenv local 3.12.8
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
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

## Implemented

- Click CLI skeleton with `init`, `config`, and `yap`
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

## Planned

- Wire `jobctl onboard`
- Job description fetching and parsing
- Fit evaluation against graph context
- Tailored resume and cover letter YAML generation
- HTML/PDF rendering
- Application tracker CRM
- Textual TUI

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
