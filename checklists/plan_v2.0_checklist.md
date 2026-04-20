# Checklist for Plan v2.0 — jobctl Unified TUI & Smart Agent

Reference plan: `docs/plan-v2.md`

---

## M0: LLM Provider Abstraction and Core Infrastructure

- [x] T1: Define `LLMProvider` protocol with message and response types in `src/jobctl/llm/base.py`
- [x] T2: Implement `OpenAIProvider` class in `src/jobctl/llm/openai_provider.py`
- [x] T3: Implement `OllamaProvider` class in `src/jobctl/llm/ollama_provider.py`
- [x] T4: Refactor `CodexCLIProvider` from `src/jobctl/llm/client.py` to implement `LLMProvider`
- [x] T5: Implement `LLMProviderRegistry` in `src/jobctl/llm/registry.py`
- [x] T6: Refactor `JobctlConfig` to support a nested `llm` provider block
- [x] T7: Implement `AsyncEventBus` with typed event dataclasses in `src/jobctl/core/events.py`
- [x] T8: Implement `BackgroundJobRunner` in `src/jobctl/core/jobs/runner.py`
- [x] T9: Implement `BackgroundJobStore` CRUD in `src/jobctl/core/jobs/store.py`
- [x] T10: Add DB migrations 003–007 for new tables
- [x] T11: Write `LLMProvider` conformance test suite in `tests/llm/test_provider_conformance.py`

---

## M1: Unified Textual Shell

- [x] T12: Implement new `JobctlApp` with header bar, main pane switcher, and status footer
- [ ] T13: Implement `CommandPaletteOverlay` widget in `src/jobctl/tui/widgets/command_palette.py`
- [ ] T14: Implement `KeybindingHelpOverlay` widget in `src/jobctl/tui/widgets/help_overlay.py`
- [ ] T15: Port `src/jobctl/tui/profile_view.py` to `src/jobctl/tui/views/graph.py` as `GraphView`
- [ ] T16: Port `src/jobctl/tui/tracker_view.py` to `src/jobctl/tui/views/tracker.py` as `TrackerView`
- [ ] T17: Port `src/jobctl/tui/materials_render.py` to `src/jobctl/tui/views/apply.py` as stub `ApplyView`
- [ ] T18: Implement stub `ChatView` Textual Screen in `src/jobctl/tui/views/chat.py`
- [ ] T19: Wire `jobctl` (no args) to launch `JobctlApp`; add deprecation notices to old subcommands

---

## M2: LangGraph Chat Agent

- [x] T20: Define `AgentState` TypedDict and `AgentMode` literal in `src/jobctl/agent/state.py`
- [ ] T21: Implement the router node that classifies user intent in `src/jobctl/agent/router.py`
- [ ] T22: Implement `chat_node` with streaming LLM responses in `src/jobctl/agent/nodes/chat_node.py`
- [ ] T23: Implement `graph_qa_node` with `search_nodes` and vector-search tools in `src/jobctl/agent/nodes/graph_qa_node.py`
- [ ] T24: Implement mode-switch confirmation flow using `ConfirmationRequestedEvent` and `ConfirmationAnsweredEvent`
- [ ] T25: Persist `AgentState` per-session to `agent_sessions` table; reload on `JobctlApp` start
- [ ] T26: Implement slash-command dispatcher in `ChatView` for `/mode`, `/quit`, `/help`, `/graph`, `/report`
- [ ] T27: Wire `LangGraphRunner` to stream agent tokens into `ChatView` via `AsyncEventBus`

---

## M3: Ingest Mode and Resumable Ingestion

- [ ] T28: Implement `ingest_node` orchestrator in `src/jobctl/agent/nodes/ingest_node.py`
- [ ] T29: Implement `FilePicker` inline Textual widget in `src/jobctl/tui/widgets/file_picker.py`
- [ ] T30: Implement `MultiSelectList` inline Textual widget in `src/jobctl/tui/widgets/multi_select.py`
- [ ] T31: Refactor `src/jobctl/ingestion/resume.py` to emit `IngestProgressEvent` and write checkpoints
- [ ] T32: Refactor `src/jobctl/ingestion/github.py` to use `ingested_items` for deduplication and incremental refresh
- [ ] T33: Implement `ProgressPanel` sidebar widget in `src/jobctl/tui/widgets/progress_panel.py`
- [ ] T34: Add proactive ingestion suggestion to `chat_node` when resume or GitHub keywords appear

---

## M4: Curation Mode

- [ ] T35: Implement `CurationDuplicateDetector` in `src/jobctl/curation/duplicates.py`
- [ ] T36: Implement `CurationProposalStore` CRUD in `src/jobctl/curation/proposals.py`
- [ ] T37: Implement `BulletRephraser` in `src/jobctl/curation/rephrase.py`
- [ ] T38: Implement `curate_node` in `src/jobctl/agent/nodes/curate_node.py`
- [ ] T39: Implement `CurateView` Textual Screen in `src/jobctl/tui/views/curate.py`
- [ ] T40: Implement `CurationProposalCard` widget in `src/jobctl/tui/widgets/proposal_card.py`

---

## M5: Apply Mode Integration

- [ ] T41: Implement `apply_node` in `src/jobctl/agent/nodes/apply_node.py`
- [ ] T42: Refactor `src/jobctl/jobs/apply_pipeline.py` to emit events instead of Rich prompts
- [ ] T43: Implement `ApplyView` full Textual Screen in `src/jobctl/tui/views/apply.py`
- [ ] T44: Implement `InlineConfirmCard` widget in `src/jobctl/tui/widgets/confirm_card.py`

---

## M6: Polish and Deprecation Removal

- [ ] T45: Remove deprecated CLI subcommands; retain `init`, `config`, and `render --headless`
- [ ] T46: Define a central theme in `src/jobctl/tui/theme.py` and apply it across all views
- [ ] T47: Add Textual `Pilot` smoke test that boots the TUI and navigates all views
- [ ] T48: Update `README.md` to reflect the v2 single-entry TUI
