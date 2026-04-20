# Plan v2.0 — jobctl Unified TUI & Smart Agent

## Context

`jobctl` exists as a working CLI that builds a SQLite knowledge graph from a user's career data, evaluates job-fit, and generates tailored resumes and cover letters. The core data model (graph nodes/edges, vector embeddings, applications table) is sound and must be preserved. However, the product has three critical problems that v2 addresses:

1. **Fragmented UX.** Nine independent Typer subcommands (`onboard`, `yap`, `agent`, `apply`, `track`, `profile`, `render`, `config`, `init`) each launch a different style of interaction — some Rich-prompt loops, some Textual screens — with no shared chrome or navigation.
2. **Primitive LLM layer.** The only backend shells out to a Codex CLI subprocess. The OpenAI SDK client is commented out in `llm/client.py`. There is no provider abstraction; switching to OpenAI or Ollama requires rewriting call sites.
3. **Dumb agent.** `conversation/agent.py` is a manual command dispatcher, not an agent. It cannot plan, chain tools, propose connections between facts, deduplicate nodes, or switch modes intelligently.

### Goals for v2
- Single entry point: `jobctl` (no args) launches a unified Textual TUI.
- Swappable LLM providers (OpenAI, Ollama, legacy Codex CLI) behind a common protocol.
- A LangGraph-powered agent that handles chat, onboarding, ingestion, curation, and job application workflows as distinct modes, with explicit mode-switch confirmation.
- Resumable ingestion: partially completed GitHub or resume ingestion picks up where it failed.
- Curation mode: agent identifies and proposes duplicate merges, orphan resolutions, bullet rewrites, and new graph edges.
- All Rich-prompt I/O moved inside Textual widgets; pipelines become pure functions that emit events.

### Non-goals for v2
- Web UI.
- Multi-user or team features.
- Job board registry and scheduled fetching (deferred to v3).
- Company recommender (deferred to v3).

### Baseline (completed in v1)
All tasks in `checklists/plan_v1.0_checklist.md` are complete. The schema has migrations 001 (graph tables) and 002 (applications/events tables). The existing modules under `src/jobctl/` are the starting point for v2.

---

## Milestones

### M0: LLM Provider Abstraction and Core Infrastructure

#### Task T1: Define `LLMProvider` protocol with message and response types in `src/jobctl/llm/base.py`
- Description: Create a `Protocol` class `LLMProvider` with three methods: `chat(messages, *, tools, temperature) -> ChatResponse`, `stream(messages, *, tools, temperature) -> Iterator[ChatChunk]`, and `embed(texts) -> list[list[float]]`. Define `Message` as a `TypedDict` with `role`, `content`, and optional `tool_calls`/`tool_call_id` fields. Define `ChatResponse` (full text, optional tool calls) and `ChatChunk` (delta text, optional tool call delta). Define `ToolSpec` as a `TypedDict` describing a callable tool (name, description, JSON schema parameters). This file is pure protocol and types; no implementation.
- Outputs: `LLMProvider`, `Message`, `ChatResponse`, `ChatChunk`, `ToolSpec` exported from `llm/base.py`.
- Libraries and tools: `typing`, `collections.abc`, no new dependencies.
- Dependencies: None

#### Task T2: Implement `OpenAIProvider` class in `src/jobctl/llm/openai_provider.py`
- Description: Implement `LLMProvider` using the `openai` Python SDK (`openai.OpenAI`). `chat()` calls `client.chat.completions.create` with `tools` when provided; extracts `.choices[0].message.content` and any `.tool_calls`. `stream()` calls the same endpoint with `stream=True`, yields `ChatChunk` per delta. `chat_structured(messages, schema)` (extra convenience not in base protocol) uses `client.beta.chat.completions.parse` with `response_format=schema`. `embed()` calls `client.embeddings.create` with the configured embedding model. Retry transient errors (rate limit, timeout, connection) with exponential back-off up to 3 attempts. Constructor takes `api_key: str`, `chat_model: str`, `embedding_model: str`.
- Inputs: OpenAI API key, model names from config.
- Outputs: Concrete class satisfying `LLMProvider`; structured output via Pydantic model validation.
- Libraries and tools: `openai` (already in `pyproject.toml`), `pydantic`.
- Dependencies: T1

#### Task T3: Implement `OllamaProvider` class in `src/jobctl/llm/ollama_provider.py`
- Description: Implement `LLMProvider` using `httpx` against the Ollama `/api/chat` endpoint. `chat()` sends a POST with `{"model": ..., "messages": ..., "stream": false}`; parses `.message.content`. `stream()` sends with `"stream": true`; reads newline-delimited JSON and yields `ChatChunk`. `embed()` calls `/api/embed` with the configured embedding model. Structured output: append a system instruction to request JSON output, then parse the response with `pydantic.BaseModel.model_validate_json`; validate against the schema, raise a `ValueError` if it fails. Constructor takes `host: str` (default `http://localhost:11434`), `chat_model: str`, `embedding_model: str`.
- Inputs: Ollama host, model names from config.
- Outputs: Concrete class satisfying `LLMProvider`.
- Libraries and tools: `httpx` (already in `pyproject.toml`), `pydantic`.
- Dependencies: T1

#### Task T4: Refactor `CodexCLIProvider` from `src/jobctl/llm/client.py` to implement `LLMProvider`
- Description: Extract the existing `LLMClient` subprocess logic into a new class `CodexCLIProvider` in `src/jobctl/llm/codex_provider.py` that satisfies the `LLMProvider` protocol. `chat()` and `stream()` wrap `_run_codex`. `embed()` delegates to `TransformerEmbedder` (keep the local HuggingFace path). Keep the `TransformerEmbedder`, `get_embedding`, and `get_embeddings_batch` helpers in `llm/client.py` for backward compatibility but mark as deprecated. All callers inside `llm/` and `conversation/` should import from `codex_provider.py` going forward.
- Outputs: `CodexCLIProvider` class in `llm/codex_provider.py`; `llm/client.py` retained with deprecation warnings.
- Libraries and tools: `subprocess`, `transformers`, `torch` (existing dependencies).
- Dependencies: T1

#### Task T5: Implement `LLMProviderRegistry` in `src/jobctl/llm/registry.py`
- Description: Implement a `get_provider(config: JobctlConfig) -> LLMProvider` factory function that reads `config.llm.provider` and instantiates the matching provider class (`OpenAIProvider`, `OllamaProvider`, or `CodexCLIProvider`). Raise `ConfigError` with a helpful message if the provider name is unrecognised or required fields are missing. Cache the instance per process so the heavy `TransformerEmbedder` loads only once.
- Inputs: `JobctlConfig` with the `llm` block populated.
- Outputs: A `LLMProvider` instance ready for use.
- Dependencies: T1, T2, T3, T4, T6

#### Task T6: Refactor `JobctlConfig` to support a nested `llm` provider block
- Description: Replace the flat `openai_api_key`, `embedding_model`, `llm_model` fields in `src/jobctl/config.py` with a nested structure: `llm.provider` (string, one of `openai`/`ollama`/`codex`), `llm.chat_model`, `llm.embedding_model`, `llm.openai.api_key_env` (env-var name, default `OPENAI_API_KEY`), `llm.ollama.host`, `llm.ollama.embedding_model`. Keep backward-compatible loading: if the old flat keys exist in `config.yaml`, map them to the new structure and write a migration hint to stderr. Update `default_config()`, `save_config()`, `load_config()`, and `replace_config_value()` accordingly. Update `jobctl config` command to accept dotted key paths (e.g. `jobctl config llm.provider openai`).
- Inputs: Existing `config.yaml` files (flat format).
- Outputs: New `JobctlConfig` dataclass with nested `LLMConfig`; backwards-compatible YAML loader.
- Dependencies: None

#### Task T7: Implement `AsyncEventBus` with typed event dataclasses in `src/jobctl/core/events.py`
- Description: Implement a simple `AsyncEventBus` using `asyncio.Queue` per subscriber. Define a `JobctlEvent` base dataclass. Define the concrete event types needed for v2: `AgentTokenEvent(token: str)`, `AgentDoneEvent(role: str, content: str)`, `AgentToolCallEvent(name: str, args: dict)`, `AgentModeChangeRequestEvent(new_mode: str)`, `ConfirmationRequestedEvent(question: str, confirm_id: str)`, `ConfirmationAnsweredEvent(confirm_id: str, answer: bool)`, `IngestProgressEvent(source: str, current: int, total: int, message: str)`, `IngestDoneEvent(source: str, facts_added: int)`, `IngestErrorEvent(source: str, error: str)`, `ApplyProgressEvent(step: str, message: str)`. Implement `EventBus.publish(event)`, `EventBus.subscribe() -> AsyncQueue`, `EventBus.unsubscribe(queue)`. The TUI subscribes on screen mount; pipelines import and publish without importing Textual.
- Outputs: `AsyncEventBus`, all event dataclasses, exported from `core/events.py`.
- Libraries and tools: `asyncio`, `dataclasses`.
- Dependencies: None

#### Task T8: Implement `BackgroundJobRunner` in `src/jobctl/core/jobs/runner.py`
- Description: Implement a `BackgroundJobRunner` class that executes `Callable` jobs (sync or async) in a `ThreadPoolExecutor`, updates job state in the `BackgroundJobStore` on start/progress/completion/failure, and publishes matching events to the `AsyncEventBus`. Expose `runner.submit(job_id, fn, *args) -> Future` and `runner.cancel(job_id)`. On uncaught exception, write the traceback to the job store's error column and publish `IngestErrorEvent`. On normal completion, set state to `done` and publish `IngestDoneEvent`.
- Inputs: `BackgroundJobStore` instance, `AsyncEventBus` instance.
- Outputs: Runnable background task with persistent state tracking.
- Libraries and tools: `concurrent.futures`, `asyncio`.
- Dependencies: T7, T9

#### Task T9: Implement `BackgroundJobStore` CRUD in `src/jobctl/core/jobs/store.py` backed by `ingestion_jobs` and `ingested_items` tables
- Description: Implement a `BackgroundJobStore` class with methods: `create_job(source_type, source_key) -> str` (returns `job_id`); `update_job(job_id, state, cursor, error)`; `get_job(job_id) -> JobRecord`; `find_pending_job(source_type, source_key) -> JobRecord | None`; `mark_item_done(job_id, external_id, external_updated_at, node_id)`; `is_item_seen(job_id, external_id, external_updated_at) -> bool`. The `ingestion_jobs` table: `id, source_type, source_key, state (queued|running|failed|done), cursor (TEXT JSON), error, created_at, updated_at, completed_at`. The `ingested_items` table: `id, job_id, external_id, external_updated_at, node_id, status, error, created_at`. All writes are committed immediately (no batching) so partial progress survives crashes.
- Inputs: Open `sqlite3.Connection`.
- Outputs: `BackgroundJobStore` with full CRUD; the underlying table DDL in migration 003.
- Dependencies: T10

#### Task T10: Add DB migrations 003–007 for new tables
- Description: Add five new migration functions to `src/jobctl/db/connection.py` and register them in the `MIGRATIONS` list: migration 003 creates `ingestion_jobs` and `ingested_items` (see T9 for columns); migration 004 creates `node_sources(id, node_id REFERENCES nodes, source_type, source_ref, confidence REAL, source_quote TEXT, created_at)`; migration 005 creates `agent_sessions(id, created_at, updated_at, state_json TEXT)`; migration 006 creates `curation_proposals(id, kind, payload_json TEXT, status (pending|accepted|rejected|edited), created_at, decided_at)`; migration 007 adds `embedding_model TEXT` column to the `vec_nodes` virtual table companion row (if `sqlite-vec` supports it) or to a new `embedding_meta` table. Each migration is self-contained and idempotent; existing migrations 001 and 002 are not modified.
- Outputs: Five new migration functions; updated `MIGRATIONS` list; all new tables created on first `get_connection()` call after the update.
- Dependencies: None

#### Task T11: Write `LLMProvider` conformance test suite in `tests/llm/test_provider_conformance.py`
- Description: Write a shared pytest parametrize fixture that runs the same assertions against any `LLMProvider` implementation. Tests: `test_chat_returns_string` (non-empty string); `test_stream_yields_chunks` (at least one `ChatChunk` with non-empty token); `test_embed_returns_correct_shape` (list of lists, each with length == embedding_model dimension); `test_chat_structured_returns_model` (validates a trivial Pydantic schema). Provide a `FakeLLMProvider` in `tests/conftest.py` that returns canned responses; run the suite against it in CI (fast). Gate real provider tests behind env vars (`TEST_OPENAI=1`, `TEST_OLLAMA=1`).
- Inputs: Each `LLMProvider` implementation.
- Outputs: `tests/llm/test_provider_conformance.py`; `FakeLLMProvider` in `tests/conftest.py`.
- Libraries and tools: `pytest`, `pytest-asyncio`.
- Dependencies: T1, T2, T3, T4

---

### M1: Unified Textual Shell

#### Task T12: Implement new `JobctlApp` with header bar, main pane switcher, and status footer in `src/jobctl/tui/app.py`
- Description: Replace the existing `JobctlApp` stub with a full Textual `App` subclass. The app composes: a `Header` widget showing project path, active mode label, and LLM provider name (read from config); a `ContentSwitcher` for swapping views by name; a collapsible right `Sidebar` (width 30, toggled by `Ctrl-B`); a `Footer` with keybinding hints and a transient status bar. Install screens: `chat`, `graph`, `tracker`, `apply`, `curate`, `settings`. Default start screen: `chat`. Global keybindings: `g c` → chat, `g g` → graph, `g t` → tracker, `g a` → apply, `g u` → curate, `g comma` → settings, `:` → command palette, `?` → help overlay, `q` → quit (with confirmation if background jobs are running). Inject `sqlite3.Connection`, `LLMProvider`, `AsyncEventBus`, and `BackgroundJobRunner` as app-level attributes shared by all views.
- Inputs: `JobctlConfig`, open DB connection, `LLMProvider` from registry.
- Outputs: Runnable Textual app with view switching and global keybindings.
- Libraries and tools: `textual`.
- Dependencies: T5, T6, T7, T8

#### Task T13: Implement `CommandPaletteOverlay` widget in `src/jobctl/tui/widgets/command_palette.py`
- Description: Implement a modal `Screen` subclass that presents a fuzzy-searchable list of registered commands. Commands are registered as `PaletteCommand(label, description, action: Callable)` objects. The overlay is triggered by `:` keybinding globally. Typing filters the list (case-insensitive substring match). `Enter` invokes the action and closes the overlay. `Esc` cancels. Pre-register commands for every view switch action and every agent slash command (`/ingest resume`, `/ingest github`, `/curate`, `/apply`, `/mode`). The overlay announces itself via `app.push_screen`.
- Outputs: `CommandPaletteOverlay` screen; `PaletteCommand` dataclass; `register_command` helper on `JobctlApp`.
- Libraries and tools: `textual`.
- Dependencies: T12

#### Task T14: Implement `KeybindingHelpOverlay` widget in `src/jobctl/tui/widgets/help_overlay.py`
- Description: Implement a modal `Screen` that renders a formatted table of all active keybindings, grouped by context (global, chat, graph, tracker, apply, curate). Bindings are collected from each view's `BINDINGS` list via the app. Triggered by `?`. Closed by `Esc` or `q`.
- Outputs: `KeybindingHelpOverlay` screen.
- Libraries and tools: `textual`.
- Dependencies: T12

#### Task T15: Port `src/jobctl/tui/profile_view.py` to `src/jobctl/tui/views/graph.py` as `GraphView`
- Description: Move `ProfileScreen` into a new `GraphView(Screen)` class under `tui/views/graph.py`. Preserve all existing functionality (tree browse, Enter to detail, `e` to edit, `d` to delete, `a` to add node, auto-embed on save). Additionally: add a filter toolbar (type selector) above the tree; add a search input that highlights matching nodes; display node `source_quote` and `confidence` from `node_sources` table in the detail panel. Update the app chrome to install `GraphView` as the `graph` screen.
- Inputs: `sqlite3.Connection`, `LLMProvider`.
- Outputs: `GraphView` screen; `src/jobctl/tui/profile_view.py` deleted.
- Libraries and tools: `textual`.
- Dependencies: T10, T12

#### Task T16: Port `src/jobctl/tui/tracker_view.py` to `src/jobctl/tui/views/tracker.py` as `TrackerView`
- Description: Move `TrackerScreen` into `TrackerView(Screen)` under `tui/views/tracker.py`. Preserve existing functionality (DataTable, status filter, notes edit, status cycling). Add: a "New application" shortcut that opens an `InlineApplyForm` (company, role, URL, paste JD); column for follow-up date with colour-coded urgency (red if past due, yellow if within 3 days); `o` keybinding to open the PDF at `resume_pdf_path` in the system viewer via `subprocess.Popen`. Update the app chrome to install `TrackerView` as the `tracker` screen.
- Inputs: `sqlite3.Connection`.
- Outputs: `TrackerView` screen; `src/jobctl/tui/tracker_view.py` deleted.
- Libraries and tools: `textual`.
- Dependencies: T12

#### Task T17: Port `src/jobctl/tui/materials_render.py` to `src/jobctl/tui/views/apply.py` as `ApplyView`
- Description: Move the 571-line `materials_render.py` Textual screen into `ApplyView(Screen)` under `tui/views/apply.py`. Keep section picker, YAML preview, template selection, and PDF render trigger. Add: a "Job description" top panel that shows the active `ExtractedJD` (company, role, score); an evaluation panel that shows matching strengths and gaps from `FitEvaluation`; a "Generate resume" and "Generate cover letter" button that trigger `ApplyProgressEvent`-emitting workers rather than blocking calls. Update the app chrome to install `ApplyView` as the `apply` screen.
- Inputs: `sqlite3.Connection`, `LLMProvider`, `AsyncEventBus`.
- Outputs: `ApplyView` screen; `src/jobctl/tui/materials_render.py` deleted.
- Libraries and tools: `textual`.
- Dependencies: T7, T12

#### Task T18: Implement stub `ChatView` Textual Screen in `src/jobctl/tui/views/chat.py`
- Description: Implement `ChatView(Screen)` with: a scrollable `RichLog`-based message log that renders Markdown; a `TextArea` input at the bottom (multi-line, submitted by `Enter` or `Ctrl-Enter`); a non-blocking echo-bot `on_submit` handler that posts the user message and echoes it back, publishing both as `AgentDoneEvent` to validate the event bus. Slash commands (`/mode`, `/quit`, `/help`) are intercepted before the bus and handled locally. Subscribe to all `AgentTokenEvent`, `AgentDoneEvent`, and `AgentToolCallEvent` events from the bus to render live streaming responses. Install `ChatView` as the default `chat` screen.
- Outputs: `ChatView` screen; working event bus round-trip validated with echo bot.
- Libraries and tools: `textual`.
- Dependencies: T7, T12

#### Task T19: Wire `jobctl` (no args) to launch `JobctlApp`; add deprecation notices to old subcommands
- Description: Update `src/jobctl/cli.py` so that running `jobctl` with no args (or with `--tui`) calls `run_tui("chat")` via the new `JobctlApp`. Keep `init` and `config` as non-interactive subcommands unchanged. For `onboard`, `yap`, `agent`, `apply`, `track`, `profile`, `render`: each prints a deprecation warning (via `typer.echo`) and then invokes the TUI starting on the appropriate screen (e.g. `onboard` → `run_tui("chat")` with an initial message queued; `render` without `--headless` → `run_tui("apply")`). `render --headless` continues to render PDF from YAML without launching the TUI. Update `run_tui` in `app/common.py` to instantiate `JobctlApp` from `tui/app.py` with the new signature.
- Outputs: Updated `cli.py`; `run_tui` helper updated; all old subcommands still runnable but deprecated.
- Dependencies: T12

---

### M2: LangGraph Chat Agent

#### Task T20: Define `AgentState` TypedDict and `AgentMode` literal in `src/jobctl/agent/state.py`
- Description: Define `AgentMode = Literal["chat", "ingest", "curate", "apply", "graph_qa"]`. Define `Confirmation(TypedDict)` with `question: str` and `confirm_id: str`. Define `Coverage(TypedDict)` mirroring the dict returned by `analyze_coverage`. Define `AgentState(TypedDict)` with fields: `messages: list[Message]`, `mode: AgentMode`, `pending_confirmation: Confirmation | None`, `coverage: Coverage | None`, `last_tool_result: dict | None`, `session_id: str`. No LangGraph imports in this file; it is a pure data definition used by all nodes.
- Outputs: `AgentState`, `AgentMode`, `Confirmation`, `Coverage` in `agent/state.py`.
- Dependencies: T1

#### Task T21: Implement the router node that classifies user intent and selects the next graph node in `src/jobctl/agent/router.py`
- Description: Implement `route(state: AgentState) -> str` as a pure function (no LLM call). It returns the name of the next graph node. Rules (in order): if `state.pending_confirmation` is not None, return `"wait_for_confirmation"`; if the last user message starts with `/ingest`, return `"ingest_node"`; if the last user message starts with `/curate`, return `"curate_node"`; if the last user message starts with `/apply`, return `"apply_node"`; if `state.mode != "chat"`, return `f"{state.mode}_node"`; otherwise return `"chat_node"`. This is a deterministic conditional edge function for LangGraph.
- Outputs: `route` function in `agent/router.py`; unit tests in `tests/agent/test_router.py`.
- Dependencies: T20

#### Task T22: Implement `chat_node` with streaming LLM responses in `src/jobctl/agent/nodes/chat_node.py`
- Description: Implement `chat_node(state: AgentState, provider: LLMProvider, bus: AsyncEventBus) -> AgentState`. The node constructs a system prompt from `SYSTEM_PROMPTS["chat"]` (versioned string in `agent/prompts/__init__.py`) and the full `state.messages` history. It calls `provider.stream(messages)`, publishing each `ChatChunk` as `AgentTokenEvent` to the bus. After the stream ends, it appends the full assistant message to `state.messages` and returns the updated state. Also calls `propose_facts_tool` on the user's last message (non-blocking, best-effort) and appends any high-confidence proposed facts as a `AgentToolCallEvent` to the bus. Returns the updated `AgentState`.
- Inputs: `AgentState`, `LLMProvider`, `AsyncEventBus`.
- Outputs: Updated `AgentState` with assistant reply appended.
- Dependencies: T1, T7, T20, T21

#### Task T23: Implement `graph_qa_node` with `search_nodes` and vector-search tools in `src/jobctl/agent/nodes/graph_qa_node.py`
- Description: Implement `graph_qa_node(state: AgentState, provider: LLMProvider, conn: sqlite3.Connection, bus: AsyncEventBus) -> AgentState`. Bind two tools as `ToolSpec`: `search_nodes(query: str, type: str | None)` (calls `db/graph.py::search_nodes`) and `vector_search(query: str, top_k: int)` (calls `db/vectors.py::search_similar`). Call `provider.chat(messages, tools=[...])` and if the response includes tool calls, execute the tools and feed results back as a second LLM call. Stream the final text answer via `AgentTokenEvent`. This replaces the existing `_ask` method in `conversation/agent.py`.
- Inputs: `AgentState`, `LLMProvider`, `sqlite3.Connection`, `AsyncEventBus`.
- Outputs: Updated `AgentState`; graph-grounded answer published to bus.
- Dependencies: T1, T7, T20, T22

#### Task T24: Implement mode-switch confirmation flow using `ConfirmationRequestedEvent` and `ConfirmationAnsweredEvent`
- Description: When the router detects that the user's message implies a mode change (e.g. mentions "ingest" while in `chat` mode), the node sets `state.pending_confirmation = Confirmation(question="Switch to ingest mode?", confirm_id=uuid)` and publishes `ConfirmationRequestedEvent`. The LangGraph graph pauses at a `wait_for_confirmation` node that loops until `ConfirmationAnsweredEvent` with the matching `confirm_id` arrives via the bus. If `answer=True`, `state.mode` is updated and the router re-routes. If `answer=False`, `pending_confirmation` is cleared and execution returns to `chat_node`. Implement `wait_for_confirmation_node` in `src/jobctl/agent/nodes/confirm_node.py`. Wire it into the graph in `agent/graph.py`.
- Outputs: `wait_for_confirmation_node`; `ConfirmationCard` widget in `ChatView` that subscribes to `ConfirmationRequestedEvent` and publishes `ConfirmationAnsweredEvent` on yes/no.
- Dependencies: T7, T20, T21, T22

#### Task T25: Persist `AgentState` per-session to `agent_sessions` table; reload on `JobctlApp` start
- Description: Implement `save_session(conn, state: AgentState)` and `load_session(conn, session_id: str) -> AgentState | None` in `src/jobctl/agent/session.py`. `save_session` serialises `state` to JSON (messages, mode, pending_confirmation) and upserts into `agent_sessions`. `load_session` reads the latest row for the given session_id. In `ChatView.on_mount`, call `load_session` and restore history into the message log. On every `AgentDoneEvent`, call `save_session`. Session ID is generated once per process and stored in `JobctlApp`.
- Outputs: `save_session`, `load_session` in `agent/session.py`; session survives Ctrl-C.
- Dependencies: T10, T18, T20

#### Task T26: Implement slash-command dispatcher in `ChatView` for `/mode`, `/quit`, `/help`, `/graph`, `/report`
- Description: In `ChatView.on_submit`, before forwarding to the LangGraph runner, check if the input starts with `/`. Parse the command name and args. Handle: `/mode [name]` (print current or request mode change via `ConfirmationRequestedEvent`); `/quit` (call `app.exit()`); `/help` (push `KeybindingHelpOverlay`); `/graph [type]` (switch to `GraphView`); `/report coverage|summary` (call `analyze_coverage` and render a Rich table inline in the chat log). Unknown slash commands are forwarded to the LangGraph runner. This avoids an LLM call for simple navigation commands.
- Outputs: Slash-command handler in `ChatView`; integration test in `tests/tui/test_chat_view.py` using Textual `Pilot`.
- Dependencies: T18, T14

#### Task T27: Wire `LangGraphRunner` to stream agent tokens into `ChatView` via `AsyncEventBus`
- Description: Implement `LangGraphRunner` in `src/jobctl/agent/runner.py`. It holds the compiled LangGraph `CompiledGraph` and an `AgentState`. `runner.submit(user_message: str)` appends the message to state, then calls `graph.astream(state)` in a Textual `app.run_worker` background thread, publishing each yielded event (token, tool call, done) to the `AsyncEventBus`. The `ChatView` message log is updated reactively via the bus. Build the `CompiledGraph` in `src/jobctl/agent/graph.py`: add nodes `chat_node`, `graph_qa_node`, `wait_for_confirmation_node`; add edges via `route`; compile with `checkpointer=None` (session persistence is handled separately in T25).
- Inputs: Compiled LangGraph graph; `AsyncEventBus`; `AgentState`.
- Outputs: `LangGraphRunner`; `agent/graph.py` with compiled graph; end-to-end streaming chat working in TUI.
- Libraries and tools: `langgraph` (add to `pyproject.toml`).
- Dependencies: T7, T22, T23, T24, T25

---

### M3: Ingest Mode and Resumable Ingestion

#### Task T28: Implement `ingest_node` orchestrator in `src/jobctl/agent/nodes/ingest_node.py`
- Description: Implement `ingest_node(state: AgentState, provider: LLMProvider, conn: sqlite3.Connection, store: BackgroundJobStore, runner: BackgroundJobRunner, bus: AsyncEventBus) -> AgentState`. Based on `state.last_tool_result` (set by the router from parsed slash args or inline widget replies): if `source_type == "resume"`, call `start_resume_ingest`; if `source_type == "github"`, call `start_github_ingest`. Both functions create a job in the store, submit it to the runner, and return immediately. The node appends an assistant message describing the job and returns state. The actual ingestion runs in the background via `BackgroundJobRunner`.
- Inputs: Parsed `source_type` and `source_value` from user input; `BackgroundJobStore`, `BackgroundJobRunner`, `AsyncEventBus`.
- Outputs: Updated `AgentState` with job-started confirmation; background job submitted.
- Dependencies: T8, T9, T20, T29, T30

#### Task T29: Implement `FilePicker` inline Textual widget in `src/jobctl/tui/widgets/file_picker.py`
- Description: Implement `FilePicker(Widget)` that renders a `DirectoryTree` Textual widget for navigating the file system and a text input for typing a path directly. On selection, emits a custom `FileSelected(path: Path)` message. The widget is mounted inline in the `ChatView` message log as a message bubble when the agent publishes a `ConfirmationRequestedEvent` with `kind="file_pick"`. After selection, the widget unmounts and the selected path is forwarded to the ingest node via `ConfirmationAnsweredEvent`.
- Outputs: `FilePicker` widget; `FileSelected` message; integration with `ChatView` rendering logic.
- Libraries and tools: `textual`.
- Dependencies: T18, T24

#### Task T30: Implement `MultiSelectList` inline Textual widget in `src/jobctl/tui/widgets/multi_select.py`
- Description: Implement `MultiSelectList(Widget)` that renders a scrollable list of items with checkboxes and a "Confirm selection" button. Used for GitHub repo selection. Emits `MultiSelectConfirmed(selected_indices: list[int])`. Mounted inline in `ChatView` when the agent publishes a `ConfirmationRequestedEvent` with `kind="multi_select"`. After confirmation, the widget unmounts and the selection is forwarded to the ingest node via `ConfirmationAnsweredEvent`.
- Outputs: `MultiSelectList` widget; `MultiSelectConfirmed` message.
- Libraries and tools: `textual`.
- Dependencies: T18, T24

#### Task T31: Refactor `src/jobctl/ingestion/resume.py` to emit `IngestProgressEvent` and write checkpoints
- Description: Refactor `persist_facts` and `extract_facts_from_resume` to accept an optional `AsyncEventBus` and `BackgroundJobStore` + `job_id`. After each successfully persisted fact, call `store.mark_item_done(job_id, external_id=fact.entity_name, ...)` and publish `IngestProgressEvent(source="resume", current=n, total=total, message=fact.entity_name)`. At the start, call `store.is_item_seen` per fact to skip already-persisted items on resume. Remove all `Prompt.ask`, `Confirm.ask`, and `console.print` calls from `persist_facts`; the interactive confirmation path (the old `_confirm_fact`) is moved into a `ChatView`-rendered `CurationProposalCard` and only triggered when `interactive=True` and a bus is provided. Non-interactive callers (tests, headless) continue to work with `bus=None`.
- Outputs: Refactored `ingestion/resume.py` with no Rich prompts; events emitted; checkpoint writes.
- Dependencies: T7, T9

#### Task T32: Refactor `src/jobctl/ingestion/github.py` to use `ingested_items` for deduplication and incremental refresh
- Description: Refactor `ingest_github` to: (1) before fetching a repo, call `store.is_item_seen(job_id, external_id=f"{owner}/{repo}", external_updated_at=repo["updated_at"])`; if seen, skip; (2) after `persist_facts` for a repo, call `store.mark_item_done`; (3) publish `IngestProgressEvent` after each repo. Remove `_prompt_for_repos` (the interactive repo picker is now `MultiSelectList` from T30); the repo list is fetched first, emitted as a `ConfirmationRequestedEvent(kind="multi_select")`, and the user's selection drives which repos to ingest. Remove all `Console.print`, `Confirm.ask`, `Prompt.ask` from this module.
- Outputs: Refactored `ingestion/github.py` with no Rich prompts; incremental refresh via `ingested_items`; events emitted.
- Dependencies: T7, T9, T30

#### Task T33: Implement `ProgressPanel` sidebar widget in `src/jobctl/tui/widgets/progress_panel.py`
- Description: Implement `ProgressPanel(Widget)` that subscribes to `IngestProgressEvent`, `IngestDoneEvent`, `IngestErrorEvent`, and `ApplyProgressEvent`. Renders a list of active/recent jobs with a `ProgressBar` per job, last status message, and elapsed time. Mounted in the right sidebar of `JobctlApp`. Auto-shows the sidebar when an ingest job starts; sidebar collapses when all jobs are done (or the user closes it).
- Outputs: `ProgressPanel` widget; sidebar auto-show/hide behaviour.
- Libraries and tools: `textual`.
- Dependencies: T7, T12

#### Task T34: Add proactive ingestion suggestion to `chat_node` when resume or GitHub keywords appear
- Description: In `chat_node`, after constructing the response, check the last user message for keywords: `["resume", "cv", "curriculum vitae"]` → emit a `ConfirmationRequestedEvent(question="Want me to ingest a resume file?", kind="file_pick_resume")`; `["github", "repositories", "repos"]` → emit `ConfirmationRequestedEvent(question="Want me to ingest your GitHub repos?", kind="github_user")`. These checks run only when `state.mode == "chat"` and no ingest job is already running. The suggestion appears as an inline `ConfirmationCard` in `ChatView`.
- Outputs: Proactive suggestion logic in `chat_node`; wired to `ConfirmationCard` in `ChatView`.
- Dependencies: T22, T24

---

### M4: Curation Mode

#### Task T35: Implement `CurationDuplicateDetector` in `src/jobctl/curation/duplicates.py`
- Description: Implement `find_duplicate_candidates(conn: sqlite3.Connection, cosine_threshold: float = 0.92, fuzzy_threshold: float = 85) -> list[DuplicateCandidate]`. A `DuplicateCandidate` is a dataclass with `node_a: Node`, `node_b: Node`, `cosine_similarity: float`, `name_similarity: float`, `reason: str`. The function: (1) loads all node embeddings from `vec_nodes` via `db/vectors.py`; (2) computes pairwise cosine similarity (using `numpy` for efficiency, skip cross-type pairs); (3) for pairs above `cosine_threshold`, also compute fuzzy name match via `difflib.SequenceMatcher`; (4) return all pairs above either threshold, sorted by descending cosine similarity. Cap at 200 candidates to avoid overwhelming the UI.
- Outputs: `DuplicateCandidate` dataclass; `find_duplicate_candidates` function.
- Libraries and tools: `numpy`, `difflib`.
- Dependencies: T10

#### Task T36: Implement `CurationProposalStore` CRUD in `src/jobctl/curation/proposals.py`
- Description: Implement `CurationProposalStore` backed by the `curation_proposals` table (from migration 006). Methods: `create_proposal(kind: str, payload: dict) -> str` (returns proposal ID); `list_pending() -> list[Proposal]`; `accept(proposal_id: str)`; `reject(proposal_id: str)`; `mark_edited(proposal_id: str, edited_payload: dict)`. A `Proposal` dataclass has `id, kind, payload, status, created_at`. Kinds: `"merge"`, `"prune"`, `"connect"`, `"rephrase"`. The `payload` dict is kind-specific: merge has `node_a_id, node_b_id, merged_name, merged_text`; prune has `node_id, reason`; connect has `source_id, target_id, relation`; rephrase has `node_id, original_text, proposed_text`.
- Outputs: `CurationProposalStore`; `Proposal` dataclass; `Proposal.kind`-specific payload conventions documented in docstrings.
- Dependencies: T10

#### Task T37: Implement `BulletRephraser` in `src/jobctl/curation/rephrase.py`
- Description: Implement `propose_rephrase(node: Node, provider: LLMProvider) -> str` that calls the LLM with a prompt instructing it to rewrite `node["text_representation"]` as a single impact-oriented, metric-led bullet (start with a strong past-tense verb, quantify outcomes when data is present, remove filler). Returns the proposed rewrite as a string. Implement `compute_diff_lines(original: str, proposed: str) -> tuple[str, str]` that returns the original and proposed as strings with changed words highlighted using ANSI escape codes (or Rich markup), for display in the `CurationProposalCard`.
- Inputs: `Node` dict from `db/graph.py`; `LLMProvider`.
- Outputs: Proposed rewrite string; diff markup for display.
- Dependencies: T1, T35

#### Task T38: Implement `curate_node` in `src/jobctl/agent/nodes/curate_node.py`
- Description: Implement `curate_node(state: AgentState, provider: LLMProvider, conn: sqlite3.Connection, proposal_store: CurationProposalStore, bus: AsyncEventBus) -> AgentState`. The node: (1) runs `find_duplicate_candidates` and creates a `"merge"` proposal for each; (2) finds orphan roles (no achievements/skills) and generates a targeted follow-up question per orphan, publishing them as `AgentTokenEvent`; (3) runs `propose_rephrase` on nodes with `text_representation` shorter than 50 chars and creates `"rephrase"` proposals; (4) optionally calls the LLM with the full graph context to propose new `"connect"` edges (top 5 only). All proposals are written to `CurationProposalStore`. Publishes an `AgentDoneEvent` summarising counts ("Found 3 duplicates, 2 rephrase suggestions, 1 new connection").
- Inputs: `AgentState`, `LLMProvider`, DB connection, `CurationProposalStore`, `AsyncEventBus`.
- Outputs: Updated `AgentState`; proposals persisted in `curation_proposals`; summary published to bus.
- Dependencies: T7, T20, T35, T36, T37

#### Task T39: Implement `CurateView` Textual Screen in `src/jobctl/tui/views/curate.py`
- Description: Implement `CurateView(Screen)`. On mount, loads all pending proposals from `CurationProposalStore` and renders them in a scrollable list. Proposals are grouped by kind (Merge, Rephrase, Connect, Prune) with a count badge. Each group is collapsible. Keybindings: `a` → accept focused proposal; `r` → reject; `e` → edit (opens inline YAML editor); `Enter` → expand/collapse; `Ctrl-A` → accept all in current group. On accept/reject, calls the store and removes the card. Includes a "Run curation" button that triggers `curate_node` via the `BackgroundJobRunner`.
- Inputs: `CurationProposalStore`, `BackgroundJobRunner`.
- Outputs: `CurateView` screen installed as `curate` in `JobctlApp`.
- Libraries and tools: `textual`.
- Dependencies: T12, T36, T38

#### Task T40: Implement `CurationProposalCard` widget in `src/jobctl/tui/widgets/proposal_card.py`
- Description: Implement `CurationProposalCard(Widget)` that renders a single `Proposal`. For `merge`: shows both node names side-by-side with types and text; for `rephrase`: shows before/after diff with changed words bolded; for `connect`: shows `source → relation → target`; for `prune`: shows node name, type, and reason. Each card has three action buttons: Accept (green, `a`), Reject (red, `r`), Edit (yellow, `e`). On Edit, replaces the card body with a `TextArea` pre-filled with the proposal payload as YAML. Used both in `CurateView` and as an inline card in `ChatView` when the agent surfaces a suggestion.
- Outputs: `CurationProposalCard` widget.
- Libraries and tools: `textual`.
- Dependencies: T36

---

### M5: Apply Mode Integration

#### Task T41: Implement `apply_node` in `src/jobctl/agent/nodes/apply_node.py`
- Description: Implement `apply_node(state: AgentState, provider: LLMProvider, conn: sqlite3.Connection, config: JobctlConfig, store: BackgroundJobStore, runner: BackgroundJobRunner, bus: AsyncEventBus) -> AgentState`. The node parses a URL or JD text from the last user message or `state.last_tool_result`. It submits a background job that runs: `fetch_and_parse_jd` → `retrieve_relevant_experience` → `evaluate_fit` → publishes `ApplyProgressEvent` at each step → emits `AgentDoneEvent` with the fit score. Material generation (resume + cover letter) is triggered by a separate `ConfirmationRequestedEvent("Generate tailored materials?")` so the user can review the score first.
- Inputs: URL or pasted JD text; DB connection; `LLMProvider`; `JobctlConfig`.
- Outputs: Updated `AgentState` with JD and evaluation stored; background job running.
- Dependencies: T7, T8, T20, T42

#### Task T42: Refactor `src/jobctl/jobs/apply_pipeline.py` to emit events instead of Rich prompts
- Description: Replace every `Confirm.ask(...)` and `console.print(...)` call in `run_apply`, `_generate_reviewed_resume`, and `_generate_reviewed_cover_letter` with `bus.publish(ApplyProgressEvent(...))` calls. Confirmation steps become `bus.publish(ConfirmationRequestedEvent(...))` followed by awaiting `ConfirmationAnsweredEvent` from the bus. The function signature gains an optional `bus: AsyncEventBus | None`; when `bus is None` (headless/test mode), fall back to the original Rich prompts. This makes the pipeline testable and TUI-drivable without changing the headless `render --headless` path.
- Inputs: Existing `run_apply` logic; `AsyncEventBus` instance.
- Outputs: Refactored `apply_pipeline.py` with no hard Rich prompt dependency when `bus` is provided.
- Dependencies: T7

#### Task T43: Implement `ApplyView` full Textual Screen in `src/jobctl/tui/views/apply.py`
- Description: Extend the stub `ApplyView` from T17 to: show the active `ExtractedJD` in a top panel (company, role, location, comp, score badge); show `FitEvaluation.matching_strengths` and `gaps` in a two-column panel; show the generated YAML in a `TextArea` (editable); a "Render PDF" button that calls `render_pdf` in a background worker and publishes the output path; a "Open PDF" button (`subprocess.Popen`). The JD and evaluation are populated from the `applications` table row for the current job (identified by a `current_app_id` attribute set when the user starts an apply flow). Subscribe to `ApplyProgressEvent` to show a progress bar.
- Inputs: `sqlite3.Connection`, `LLMProvider`, `AsyncEventBus`, `JobctlConfig`.
- Outputs: Fully functional `ApplyView`; `ApplyView` installed as `apply` screen in `JobctlApp`.
- Libraries and tools: `textual`.
- Dependencies: T7, T12, T17, T41

#### Task T44: Implement `InlineConfirmCard` widget in `src/jobctl/tui/widgets/confirm_card.py`
- Description: Implement `InlineConfirmCard(Widget)` that renders a question string and two buttons: Yes (green) and No (red). Used in `ChatView` whenever a `ConfirmationRequestedEvent` is published (except `kind="file_pick"` which uses `FilePicker`, and `kind="multi_select"` which uses `MultiSelectList`). On click, publishes `ConfirmationAnsweredEvent(confirm_id=..., answer=True/False)` to the bus and self-unmounts. Keybindings: `y` → yes, `n` → no when the card is focused.
- Outputs: `InlineConfirmCard` widget; wired into `ChatView`'s event subscription handler.
- Libraries and tools: `textual`.
- Dependencies: T7, T18, T24

---

### M6: Polish and Deprecation Removal

#### Task T45: Remove deprecated CLI subcommands; retain `init`, `config`, and `render --headless`
- Description: In `src/jobctl/cli.py`, remove the `add_typer` calls for `onboard`, `yap`, `agent`, `apply`, `track`, `profile`, and `render` (without `--headless`). Keep `init_app`, `config_app`. Refactor `src/jobctl/app/renderer.py` to expose only the headless PDF-render path (no `--tui`, no `--interactive` flag). Delete `src/jobctl/app/agent.py`, `src/jobctl/app/yap.py`, `src/jobctl/app/onboard.py`, `src/jobctl/app/apply.py`, `src/jobctl/app/track.py`, `src/jobctl/app/profile.py`. Delete `src/jobctl/conversation/agent.py`, `src/jobctl/conversation/yap.py`, `src/jobctl/conversation/onboard.py`. Verify no remaining imports reference the deleted modules.
- Outputs: Slimmed `cli.py`; deleted files; `render --headless` still working.
- Dependencies: T19, T27, T28, T38, T41

#### Task T46: Define a central theme in `src/jobctl/tui/theme.py` and apply it across all views
- Description: Define a Textual CSS variables file (`src/jobctl/tui/theme.tcss`) with a Catppuccin Mocha-inspired palette (dark background `#1e1e2e`, surface `#313244`, overlay `#45475a`, accent `#89b4fa`, green `#a6e3a1`, red `#f38ba8`, yellow `#f9e2af`, text `#cdd6f4`, subtext `#a6adc8`). Update `JobctlApp.CSS_PATH` to load `theme.tcss`. Audit all views and widgets for hardcoded colour strings and replace with CSS variable references. Add empty-state placeholder text and icons to `GraphView` (no nodes), `TrackerView` (no applications), and `CurateView` (no proposals).
- Outputs: `theme.tcss` with palette; all views using CSS variables; empty states implemented.
- Libraries and tools: `textual`.
- Dependencies: T12, T15, T16, T17, T39, T43

#### Task T47: Add Textual `Pilot` smoke test that boots the TUI and navigates all views
- Description: Add `tests/tui/test_smoke.py`. Use Textual's `App.run_test()` async context manager and the `Pilot` driver. Test: launch `JobctlApp` with an in-memory DB and `FakeLLMProvider`; assert `ChatView` is the active screen; press `g t` and assert `TrackerView` is active; press `g g` and assert `GraphView`; press `g u` and assert `CurateView`; press `g a` and assert `ApplyView`; press `g comma` and assert `SettingsView`; press `q` and assert app exits cleanly. Add `pytest-asyncio` and `textual.testing` to dev dependencies.
- Outputs: `tests/tui/test_smoke.py`; smoke test runnable in CI via `pytest -k smoke`.
- Libraries and tools: `textual.testing`, `pytest-asyncio`.
- Dependencies: T12, T15, T16, T18, T39, T43

#### Task T48: Update `README.md` to reflect the v2 single-entry TUI
- Description: Rewrite the top-level `README.md`. Remove all multi-subcommand usage examples. Document: `jobctl init`, `jobctl config`, `jobctl` (launch the TUI). Add a view reference table (Chat, Graph, Curate, Apply, Tracker, Settings) with keybindings. Add a provider configuration section showing how to set `llm.provider`, `llm.chat_model`, and `llm.openai.api_key_env` for both OpenAI and Ollama. Add a "resumable ingestion" note. Remove references to `codex` binary as a required runtime. Keep the architecture section brief.
- Outputs: Updated `README.md`.
- Dependencies: T45, T46

---

## Revisions
- v2.0: Initial version. Full redesign from the v1 multi-command CLI to a unified Textual TUI driven by a LangGraph agent. Introduces provider abstraction, resumable ingestion, curation mode, and event-bus-driven pipelines.
