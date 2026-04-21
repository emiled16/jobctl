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

| View     | Shortcut          | Purpose                                                        |
| -------- | ----------------- | -------------------------------------------------------------- |
| Chat     | `Ctrl-J` / `g c`  | Talk to the LangGraph agent; slash commands dispatch actions.  |
| Graph    | `Ctrl-G` / `g g`  | Browse the knowledge graph, edit nodes, inspect sources.       |
| Tracker  | `Ctrl-T` / `g t`  | Review applications, cycle status, open PDFs, add follow-ups.  |
| Apply    | `Ctrl-R` / `g a`  | See JD + fit evaluation, edit YAML, render PDFs, open in OS.   |
| Curate   | `Ctrl-E` / `g u`  | Accept / reject / edit agent-proposed merges and rephrases.    |
| Settings | `Ctrl-S` / `g ,`  | Read-only project and provider configuration summary.          |

The `Ctrl-` shortcuts always switch views (they work even while typing in the chat input). The `g`-chord shortcuts only fire when no text input is focused — press `Esc` first to defocus. `F1`–`F6` are also bound as aliases for keyboards with dedicated function keys.

Global shortcuts: `Ctrl-P` (or `:`) opens the command palette, `?` opens the keybinding overlay, `Ctrl-B` toggles the background-jobs sidebar, `Esc` defocuses the current input, `Ctrl-Q` quits (with confirmation if background jobs are active).

Inside the command palette: `Up` / `Down` (or `Ctrl-N` / `Ctrl-P`) move the selection while typing the filter, `Enter` runs the highlighted command, `Esc` closes.

Chat slash commands: `/mode`, `/apply`, `/apply <url-or-text>`, `/graph`, `/tracker`, `/curate`, `/refine resume`, `/settings`, `/report coverage`, `/report summary`, `/help`, `/quit`.

The command palette separates view navigation from workflow starts. View commands switch directly to the selected view. Workflow commands open the required input first: resume ingestion opens a validated file picker, GitHub ingestion asks for usernames/profile/repo URLs, Apply asks for a job URL or pasted JD text, Curate opens the Curate view, and Refine resume continues pending resume refinement questions.

Chat model output streams into one live assistant message while the provider is responding, then lands as a single completed assistant message. `/mode <name>` now uses an inline confirmation and persists to the agent session state used by the router.

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
vector_store:
  provider: qdrant
  mode: local
  path: .jobctl/qdrant
  collection: jobctl_nodes
  distance: cosine
```

For older projects, run `jobctl rag reindex` once to populate Qdrant from the
existing SQLite graph. After verifying retrieval works, `jobctl rag
cleanup-legacy-vectors --yes` removes old SQLite vector artifacts.

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

The embedding path still supports the local Transformers client (`sentence-transformers/all-MiniLM-L6-v2` by default) for provider-independent retrieval. Vector data is stored in Qdrant local mode under `.jobctl/qdrant/`; SQLite remains the local relational store for app state, conversations, jobs, and tracker data.

## Resumable ingestion

Resume and GitHub ingestion record per-item checkpoints in `ingestion_jobs` and `ingested_items`. If a run crashes, starting the same workflow again picks up where it left off, skipping items already persisted. Progress is streamed to the sidebar via the `AsyncEventBus`.

Resume ingestion reconciles extracted facts against the existing graph before writing. Exact duplicates are skipped, high-confidence new facts are persisted with source records, additive updates become `update_fact` Curate proposals, and ambiguous/conflicting changes are left for review. The ingestion run also stores prioritized refinement questions for vague experience; continue them later from chat with `/refine resume`.

Resume refinement answers are reviewed before they mutate the graph. After you answer a question, Chat shows a unified diff-style preview of property/text/fact/edge changes; reply `accept` to apply the change or `reject` to discard it and move on.

Background work publishes lifecycle events with `queued`, `running`, `waiting_for_user`, `done`, `error`, and `cancelled` phases. The top status line shows the active job or input-waiting state, and the sidebar keeps recent done/error cards visible.

## Apply, Curate, Graph, And Tracker Notes

Apply view can render a selected resume YAML to PDF, persist the generated PDF path back to the tracker, and then open the recorded PDF path. It can also generate cover-letter YAML/PDF when the selected application has structured JD and fit-evaluation data. Apply view refreshes when apply jobs complete.

Curate proposal cards support Accept, Reject, Edit, Save, and Cancel. Accepted merge/rephrase/connect/prune proposals apply durable graph changes before the proposal is marked accepted. Resume-derived `add_fact`, `update_fact`, and `refine_experience` proposals render with source, target, reason, proposed text, and review-risk context.

Graph edit and delete actions operate on the tree cursor even before pressing Enter. Delete uses a confirmation dialog with node and relationship context. Escape clears Graph search text before blurring the field.

Tracker notes show visible save success or failure status and can be saved explicitly with `Ctrl-S`.

## Agent architecture

The agent is a LangGraph state machine:

1. `router` classifies the current turn based on slash command, `AgentState.mode`, and any pending confirmation.
2. `chat_node` streams an LLM response and proactively suggests ingestion when resume/GitHub keywords appear.
3. `graph_qa_node` binds `search_nodes` and vector-search tools for graph-grounded answers.
4. `ingest_node`, `curate_node`, `apply_node`, and `refinement_node` orchestrate background jobs or one-question-at-a-time refinement through `BackgroundJobRunner` and the typed `AsyncEventBus`.
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
