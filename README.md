# jobctl

`jobctl` is a single-entry Textual TUI and CLI for building a local career knowledge graph and using it to accelerate job search workflows. It stores project data in a `.jobctl/` directory, persists a graph in SQLite, embeds nodes with Transformers (or a remote provider), and drives chat, ingestion, curation, and job-application flows through a LangGraph-powered agent.

v2 collapses the legacy fleet of subcommands (`onboard`, `yap`, `agent`, `apply`, `track`, `profile`) into a unified TUI launched by running `jobctl`.

## Requirements

- Python `3.11` or newer (pinned in `.python-version`)
- `pyenv` recommended for Python installs
- `direnv` recommended for venv activation
- Native WeasyPrint libraries for PDF rendering
- Playwright Chromium for the job-posting scraper fallback
- Network access on first run (dependency and embedding-model downloads)
- One LLM backend: OpenAI, Ollama, or the local `codex` binary

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

## Quick start

```bash
jobctl init    # scaffold .jobctl/ in the current directory
jobctl         # launch the unified TUI
```

`jobctl init` creates:

```text
.jobctl/
├── config.yaml
├── jobctl.db
├── exports/
└── templates/
    ├── resume/
    └── cover-letters/
```

## CLI surface

v2 keeps only three subcommands. Everything else lives inside the TUI.

```bash
jobctl init                # scaffold a project
jobctl config              # inspect or edit config.yaml
jobctl config llm.provider openai
jobctl render <yaml>       # headless PDF render
jobctl                     # launch the TUI (same as jobctl --tui)
```

`jobctl render --no-headless` and any interactive rendering redirect to the TUI's Apply view.

## Inside the TUI

| View     | Shortcut | Purpose                                                        |
| -------- | -------- | -------------------------------------------------------------- |
| Chat     | `g c`    | Talk to the LangGraph agent; slash commands dispatch actions.  |
| Graph    | `g g`    | Browse the knowledge graph, edit nodes, inspect sources.       |
| Tracker  | `g t`    | Review applications, cycle status, open PDFs, add follow-ups.  |
| Apply    | `g a`    | See JD + fit evaluation, edit YAML, render PDFs, open in OS.   |
| Curate   | `g u`    | Accept / reject / edit agent-proposed merges and rephrases.    |
| Settings | `g ,`    | Read-only project and provider configuration summary.          |

Global shortcuts: `:` opens the command palette, `?` opens the keybinding overlay, `Ctrl-B` toggles the background-jobs sidebar, `q` quits (with confirmation if background jobs are active).

Chat slash commands: `/mode`, `/ingest resume`, `/ingest github`, `/curate`, `/apply`, `/graph`, `/report coverage`, `/report summary`, `/help`, `/quit`.

## LLM providers

The `llm` config block drives provider selection. Configure once in `.jobctl/config.yaml` or with `jobctl config`:

```yaml
llm:
  provider: openai    # or ollama, codex
  chat_model: gpt-4o-mini
  embedding_model: text-embedding-3-small
  openai:
    api_key_env: OPENAI_API_KEY
  ollama:
    host: http://localhost:11434
    embedding_model: nomic-embed-text
```

### OpenAI

```bash
export OPENAI_API_KEY=sk-...
jobctl config llm.provider openai
jobctl config llm.chat_model gpt-4o-mini
```

### Ollama

```bash
ollama serve
jobctl config llm.provider ollama
jobctl config llm.chat_model llama3.1:8b
jobctl config llm.ollama.host http://localhost:11434
```

### Legacy Codex CLI

```bash
jobctl config llm.provider codex
```

The embedding path still supports the local Transformers client (`sentence-transformers/all-MiniLM-L6-v2` by default) for provider-independent retrieval.

## Resumable ingestion

Resume and GitHub ingestion record per-item checkpoints in `ingestion_jobs` and `ingested_items`. If a run crashes, re-launching the same `/ingest resume` or `/ingest github` slash command picks up where it left off, skipping items already persisted. Progress is streamed to the ProgressPanel sidebar via the `AsyncEventBus`.

## Agent architecture

The agent is a LangGraph state machine:

1. `router` classifies the current turn based on slash command, `AgentState.mode`, and any pending confirmation.
2. `chat_node` streams an LLM response and proactively suggests ingestion when resume/GitHub keywords appear.
3. `graph_qa_node` binds `search_nodes` and vector-search tools for graph-grounded answers.
4. `ingest_node`, `curate_node`, and `apply_node` orchestrate background jobs through `BackgroundJobRunner` and the typed `AsyncEventBus`.
5. `wait_for_confirmation_node` pauses until the corresponding `ConfirmationAnsweredEvent` arrives, enabling inline `InlineConfirmCard`, `FilePicker`, and `MultiSelectList` interactions inside chat.

`AgentState` is persisted per session to the `agent_sessions` table and restored on every launch.

## Data layout

```text
.jobctl/config.yaml
.jobctl/jobctl.db
.jobctl/exports/<application>/artifacts/drafts/
.jobctl/exports/<application>/artifacts/final/
.jobctl/templates/resume/
.jobctl/templates/cover-letters/
```

The `.jobctl/` directory is gitignored.

## Development

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Run only the TUI smoke test:

```bash
.venv/bin/python -m pytest -k smoke
```
