# Plan v3.0 — Seamless TUI UX Hardening

## Context

`jobctl` now has a unified Textual TUI with Chat, Graph, Tracker, Apply, Curate, Settings, command palette, help overlay, and background job sidebar. The UX flow assessment in `docs/ux-flow-assessment.md` found several paths that look available but are broken, incomplete, or silent. The goal of this milestone is to make the app feel seamless: visible navigation, no dead-end confirmations, no buttons that pretend to work, no destructive action without confirmation, real streaming assistant output, and clear foreground/background task visibility.

Current baseline:

- `JobctlApp` uses a `ContentSwitcher`, not installed Textual screens.
- `chat_node` emits streaming token events, but the end-to-end Chat rendering path needs verification and polish so users see model output as it arrives.
- `ProgressPanel` exists, but background task visibility is limited and there is no consistent spinner/running indicator in the main chrome.
- Apply, ingest, curation, graph edit/delete, and tracker notes have rough edges documented in `docs/ux-flow-assessment.md`.

Success criteria:

- Every visible shortcut, palette command, and primary button either completes a real workflow or is disabled/renamed to reflect its current behavior.
- Users can start ingest/apply/curation flows from Chat and the command palette without hitting dead ends.
- Chat slash commands that claim to change app or agent state actually update the same state used by the agent runtime.
- Long-running jobs show immediate activity through a spinner, sidebar entry, status text, and completion/error state.
- Chat model responses visibly stream instead of appearing only after final completion.
- Core flows have Textual pilot/widget tests covering the previously broken paths.

## Milestones

### M1: Navigation And Command Contract Cleanup

#### Task T1: Add a public `JobctlApp.show_view(name)` method for ContentSwitcher navigation
- Description: Replace private `_show_view()` coupling with a public method that validates `SCREEN_NAMES`, updates `#main-switcher`, refreshes header metadata, and focuses the Chat input when appropriate. Keep `_show_view()` as a private wrapper only if needed for backward compatibility inside the class.
- Inputs: `SCREEN_NAMES`, `ContentSwitcher`, existing `action_show_*` methods in `src/jobctl/tui/app.py`.
- Outputs: A single public app-level view navigation contract used by slash commands, palette commands, tests, and future widgets.
- Dependencies: None

#### Task T2: Fix Chat slash navigation commands to use `JobctlApp.show_view`
- Description: Update `ChatView._handle_slash_command()` so `/graph` and any future navigation slash commands call the public app navigation method instead of `switch_screen()`. Add `/tracker`, `/apply`, `/curate`, and `/settings` as cheap local navigation commands so the command surface matches the app views.
- Inputs: `ChatView._handle_slash_command()`, `JobctlApp.show_view`.
- Outputs: Slash navigation changes views without exceptions and without invoking the LLM.
- Dependencies: T1

#### Task T3: Convert palette view commands to direct `JobctlApp.show_view` actions
- Description: Update `JobctlApp._register_default_palette_commands()` so View commands call `show_view(name)` directly. Keep workflow commands available, but do not claim they are complete until the structured workflow tasks in M2 wire their payload collection.
- Inputs: `JobctlApp._register_default_palette_commands()`, `JobctlApp.show_view`.
- Outputs: Palette View commands switch views reliably without sending synthetic Chat messages.
- Dependencies: T1

#### Task T4: Add Textual pilot tests for global navigation, slash navigation, and palette navigation
- Description: Extend TUI tests to cover `Ctrl-*`, `g` chords after defocus, `/graph`, `/tracker`, `/apply`, `/curate`, `/settings`, and command palette View commands. The tests should assert `#main-switcher.current` and should fail if any path calls `switch_screen()` incorrectly.
- Inputs: `tests/tui/test_smoke.py`, Textual `App.run_test()`, `ContentSwitcher`.
- Outputs: Regression coverage for app navigation paths.
- Libraries and tools: `pytest`, AnyIO, Textual pilot.
- Dependencies: T1, T2, T3

### M2: Streaming Chat And Inline Agent Flow Completion

#### Task T5: Make Chat streaming render one live assistant message instead of token-per-line output
- Description: Update `ChatView._render_event()` so `AgentTokenEvent` appends to a single in-progress assistant message area. If `RichLog` cannot update a prior line cleanly, introduce a lightweight `StreamingMessage` widget above the input and finalize it on `AgentDoneEvent`. Preserve Markdown rendering for completed assistant messages.
- Inputs: `AgentTokenEvent`, `AgentDoneEvent`, `ChatView._stream`, `RichLog` or a new widget in `src/jobctl/tui/widgets`.
- Outputs: Users see assistant text appear incrementally while the model is running.
- Dependencies: None

#### Task T6: Add provider streaming conformance tests for ChatView event rendering
- Description: Add a fake provider that emits several stream chunks with delays and a Textual test that submits a chat message, observes partial text before final completion, then verifies the completed assistant message is rendered once.
- Inputs: `FakeLLMProvider`, `ChatView`, `LangGraphRunner`, `AsyncEventBus`.
- Outputs: Tests prove model answers stream in the UI before final completion.
- Libraries and tools: `pytest`, AnyIO, Textual pilot.
- Dependencies: T5

#### Task T7: Define a structured Chat workflow request contract
- Description: Add a small typed payload contract for workflow starts, for example `WorkflowRequest(kind, payload)` stored in `AgentState.last_tool_result` or submitted through a helper on `LangGraphRunner`. Cover at least resume ingest, GitHub ingest, and apply. Avoid encoding required data only in free-form slash text.
- Inputs: `AgentState`, `LangGraphRunner.submit()`, `router.route()`, `ingest_node`, `apply_node`.
- Outputs: A single way for UI widgets and palette actions to start agent workflows with required inputs.
- Dependencies: None

#### Task T8: Make `/mode` update persisted `AgentState.mode` through confirmation
- Description: Replace the current Chat-local `/mode` behavior with the agent confirmation flow. `/mode` with no argument should read the persisted agent state. `/mode <name>` should validate the target mode, publish a confirmation prompt, and on acceptance update `AgentState.mode` so `router.route()` sees the same mode the UI reported.
- Inputs: `ChatView._handle_slash_command()`, `AgentState`, `wait_for_confirmation_node()`, `LangGraphRunner`, session persistence helpers.
- Outputs: Mode changes are real agent state changes, not a transient app attribute.
- Dependencies: T7

#### Task T9: Add file selection validation before starting resume ingestion
- Description: Validate `FilePicker` selections before submitting a resume ingest workflow. The UI should reject empty paths, non-existent paths, directories, and unsupported extensions with inline feedback. Valid files should submit a structured resume ingest request.
- Inputs: `FilePicker`, `read_resume()` supported extensions, structured workflow request contract.
- Outputs: Resume ingest cannot start from an invalid file path without a visible explanation.
- Dependencies: T7

#### Task T10: Implement inline GitHub ingest input flow
- Description: Add an inline widget or modal that asks for a GitHub username, profile URL, or repo URLs. On submit, publish or submit a structured GitHub ingest workflow request. If repo discovery later returns selectable repos, use `MultiSelectList` with labels and selected repo payload.
- Inputs: GitHub ingest requirements in `start_github_ingest()`, `MultiSelectList`, `ConfirmationAnsweredEvent`.
- Outputs: A user can start GitHub ingestion from Chat/palette without a dead-end yes/no card.
- Dependencies: T7

#### Task T11: Implement inline Apply input flow for Chat and palette starts
- Description: Add an inline widget or modal that accepts a job URL or pasted JD text. `/apply` with no argument and palette Apply should open this input. `/apply <url-or-text>` should submit directly. The resulting payload should use the structured workflow request contract and start `apply_node`.
- Inputs: `ChatView._handle_slash_command()`, `apply_node`, `JobctlApp._register_default_palette_commands()`, structured workflow request contract.
- Outputs: Apply can be started intentionally from Chat or palette without a missing-URL dead end.
- Dependencies: T7

#### Task T12: Wire proactive resume and GitHub prompts into real workflow starts
- Description: Replace the current dead-end proactive prompts from `chat_node` with a complete flow. Resume keyword prompts should open `FilePicker`; selected path should start resume ingestion via the structured workflow contract. GitHub keyword prompts should open the GitHub input flow from T10. Cancel should remove the widget and record a visible "Canceled" message.
- Inputs: `chat_node._maybe_suggest_ingestion()`, `ChatView._render_event()`, `FilePicker`, GitHub input widget, structured workflow contract.
- Outputs: Proactive prompts either start work or clearly cancel; no confirmation response is dropped.
- Dependencies: T7, T9, T10

#### Task T13: Convert palette workflow commands from raw slash text into structured UI actions
- Description: Replace palette actions for `/ingest resume`, `/ingest github`, `/apply`, and `/curate` with explicit actions. Resume should open the validated file picker, GitHub should open the GitHub input flow, Apply should open the Apply input flow, and Curate should start the curation workflow or switch to Curate with a clear "Run curation" action.
- Inputs: `JobctlApp._register_default_palette_commands()`, `ChatView`, `FilePicker`, GitHub input widget, Apply input widget, structured workflow request contract.
- Outputs: Palette workflow commands start real workflows or collect required input before dispatch.
- Dependencies: T1, T7, T9, T10, T11

#### Task T14: Add tests for proactive ingest prompts, Apply starts, mode changes, and palette workflow starts
- Description: Add Textual tests for "resume" mention -> file picker -> job starts, invalid resume path -> inline error, "GitHub" mention -> GitHub input -> job starts, `/apply <JD>` -> apply job starts, palette Apply -> Apply input, `/mode graph_qa` -> persisted mode changes after confirmation, palette resume ingest -> file picker, and palette GitHub ingest -> GitHub input. Use fake providers/fetchers and assert job records/progress events rather than calling external services.
- Inputs: T8-T13 UI flows, `BackgroundJobStore`, fake provider/fetcher.
- Outputs: Regression coverage for no-dead-end ingest starts.
- Dependencies: T8, T9, T10, T11, T12, T13

### M3: Background Task Visibility And Spinner UX

#### Task T15: Add explicit background job lifecycle events with labels and phases
- Description: Extend `jobctl.core.events` with job lifecycle events or enrich existing events so every background task can publish `queued`, `running`, `waiting_for_user`, `done`, `error`, and `cancelled` states with `job_id`, `kind`, `label`, and `message`. Keep existing `IngestProgressEvent` and `ApplyProgressEvent` compatibility while normalizing what the UI consumes.
- Inputs: `AsyncEventBus`, `BackgroundJobRunner`, `IngestProgressEvent`, `ApplyProgressEvent`.
- Outputs: A consistent event contract for spinner/header/sidebar visibility.
- Dependencies: None

#### Task T16: Implement a reusable `SpinnerStatus` widget for active jobs
- Description: Add a Textual widget that subscribes to job lifecycle events and shows a spinner plus the most important active task label. It should render in the app header or footer and disappear or switch to a recent completion message when no jobs are active.
- Inputs: Textual widgets, event bus, lifecycle events from T11.
- Outputs: A visible spinner whenever background work is running.
- Libraries and tools: Textual built-in `LoadingIndicator` or a small custom animated label.
- Dependencies: T15

#### Task T17: Upgrade `ProgressPanel` into a useful background jobs dashboard
- Description: Improve `ProgressPanel` so every active/recent job shows kind, label, phase, progress count when available, elapsed time, and latest message. Add stable done/error states and avoid one card per apply step. Keep the sidebar auto-opening when jobs begin, but allow user collapse with `Ctrl-B`.
- Inputs: `ProgressPanel`, lifecycle events, `IngestProgressEvent`, `ApplyProgressEvent`.
- Outputs: Background task visibility that lets users understand what is running and what completed or failed.
- Dependencies: T15

#### Task T18: Mark user-waiting jobs distinctly in spinner and sidebar
- Description: When apply or ingest waits for an inline confirmation, file selection, or other user input, publish a `waiting_for_user` phase and show that state separately from running. The spinner should pause or display "Waiting for input" rather than implying CPU/network work is still progressing.
- Inputs: `run_apply()` confirmation flow, `FilePicker`, `InlineConfirmCard`, job lifecycle events.
- Outputs: Users can distinguish background work from workflows blocked on their answer.
- Dependencies: T15, T16, T17

#### Task T19: Add tests for spinner and sidebar lifecycle behavior
- Description: Add Textual tests that submit fake background jobs and assert spinner visible while running, sidebar receives a card, waiting-for-user state is shown for confirmation, and done/error states remain visible after completion.
- Inputs: `SpinnerStatus`, `ProgressPanel`, fake job event publishers.
- Outputs: Regression coverage for background visibility.
- Dependencies: T16, T17, T18

### M4: Apply Flow Completion And Material Actions

#### Task T20: Persist rendered PDF paths from ApplyView actions
- Description: Update `ApplyView.action_render_pdf()` so after `render_pdf()` returns it calls `update_application(conn, app_id, resume_pdf_path=str(pdf_path))`, refreshes `_applications`, preserves `current_app_id`, and updates the YAML/PDF status. `action_open_pdf()` should then use the refreshed stored path.
- Inputs: `ApplyView.action_render_pdf()`, `jobctl.jobs.tracker.update_application()`.
- Outputs: Render PDF -> Open PDF works in one continuous flow.
- Dependencies: None

#### Task T21: Implement real cover-letter generation from ApplyView or disable the button
- Description: Replace the current `Generate cover letter` stub with a real workflow that loads the selected application's JD/evaluation, generates cover-letter YAML, renders PDF if requested, and updates `cover_letter_yaml_path` / `cover_letter_pdf_path`. If the existing data is insufficient, disable the button and show exact missing prerequisites.
- Inputs: `generate_cover_letter_yaml()`, `save_and_review_cover_letter()`, `render_pdf()`, tracker update APIs, selected `ApplicationRow`.
- Outputs: The cover-letter button either performs real work or clearly explains why it is unavailable.
- Dependencies: T15

#### Task T22: Auto-refresh ApplyView on apply job completion
- Description: Subscribe `ApplyView` to job/apply completion events. When an apply job reaches done, reload application rows, select the newly created or most recently updated application, and show a clear status. Optionally switch to Apply view from Chat when the user started `/apply`.
- Inputs: `ApplyProgressEvent` or lifecycle done event, `ApplyView._refresh_applications()`, `JobctlApp.show_view`.
- Outputs: After Chat apply completes, materials appear in Apply view without manual refresh.
- Dependencies: T1, T15

#### Task T23: Add tests for Apply render, open-path availability, cover-letter action, and auto-refresh
- Description: Add focused tests with monkeypatched render/generation functions. Cover: render persists `resume_pdf_path`, Open PDF sees the stored path, cover-letter action updates tracker fields or is disabled with status, and ApplyView refreshes on job done.
- Inputs: ApplyView, tracker DB helpers, fake render/generation functions.
- Outputs: Regression coverage for Apply flow continuity.
- Dependencies: T20, T21, T22

### M5: Curation Flow That Actually Applies User Decisions

#### Task T24: Implement Save and Cancel handling in `CurationProposalCard`
- Description: Extend `on_button_pressed()` to handle `save` and `cancel`. Save should parse JSON from the editor, emit `Edited(proposal_id, payload)`, and remove the edit box or card according to the parent view contract. Invalid JSON should show an inline error and keep editing. Cancel should restore the original body and action buttons.
- Inputs: `CurationProposalCard.action_edit()`, `Edited` message, Textual `TextArea`.
- Outputs: Editing proposals is reversible and saveable.
- Dependencies: None

#### Task T25: Add proposal application functions for merge, rephrase, connect, and prune
- Description: Add functions that apply accepted proposal payloads to the graph. Merge should preserve edges and sources before deleting the duplicate node. Rephrase should update `text_representation` and re-embed. Connect should create an edge if it does not already exist. Prune should delete or archive the node according to the chosen policy.
- Inputs: `CurationProposalStore`, `jobctl.db.graph`, `node_sources`, vector embedding helpers.
- Outputs: Accepting a proposal changes graph state, not only proposal status.
- Dependencies: None

#### Task T26: Wire CurateView accept/edit actions to proposal application
- Description: Update `CurateView.on_curation_proposal_card_accepted()` so it applies the proposal effect from T21, marks status, removes the card, refreshes counts, and shows success/error status. `Edited` should save the edited payload and either keep it pending for later accept or apply it immediately if the user clicked Save from an accept flow.
- Inputs: `CurateView`, `CurationProposalCard`, proposal application functions.
- Outputs: Curation decisions have visible and durable graph effects.
- Dependencies: T24, T25

#### Task T27: Implement or remove CurateView `accept_group` binding
- Description: Either implement `action_accept_group()` to apply all proposals in the focused group with confirmation, or remove `Binding("ctrl+a", "accept_group", ...)` so help does not advertise a broken action.
- Inputs: `CurateView.BINDINGS`, grouped proposal rendering.
- Outputs: No advertised Curate shortcut is a no-op.
- Dependencies: T25, T26

#### Task T28: Add tests for proposal edit and accept effects
- Description: Add widget/store tests for Save/Cancel, invalid JSON handling, rephrase updates node text, connect creates an edge, prune removes/archives a node, and merge preserves relationships.
- Inputs: `CurationProposalCard`, `CurateView`, graph DB helpers.
- Outputs: Regression coverage for curation decisions.
- Dependencies: T24, T25, T26, T27

### M6: Graph And Tracker Safety Polish

#### Task T29: Make Graph actions operate on the tree cursor when no detail is selected
- Description: Update `GraphView.action_edit_selected()` and `action_delete_selected()` to use `tree.cursor_node.data` when `current_node_id` is unset. Keep Enter-to-detail behavior, but do not require Enter before edit/delete if the cursor is on a leaf node.
- Inputs: `GraphView`, Textual `Tree`.
- Outputs: Cursor-based Graph actions behave like users expect.
- Dependencies: None

#### Task T30: Add confirmation and status feedback for Graph delete
- Description: Before deleting a node, show a confirmation modal or inline prompt with node name, type, and relationship count. On confirm, delete, refresh, and show status. On cancel, leave selection intact. Surface delete errors in the detail/status area.
- Inputs: `GraphView.action_delete_selected()`, `delete_node()`, edge lookup helpers, Textual modal or `InlineConfirmCard`.
- Outputs: Graph deletion is intentional and recoverable from cancel.
- Dependencies: T29

#### Task T31: Resolve Escape behavior between global blur and Graph search clear
- Description: Make global `Escape` behavior context-aware. If Graph search is focused and has text, clear search first; if focus is inside an editor/input, blur; otherwise no-op. Update help text if the behavior changes.
- Inputs: `JobctlApp.action_blur_focus()`, `GraphView.action_clear_search()`.
- Outputs: Escape does the expected local cleanup before global defocus.
- Dependencies: T1

#### Task T32: Add visible Tracker notes save status and error handling
- Description: Add a small status label to `TrackerView`. When notes save on blur, show "Notes saved" or "Save failed: ...". Consider adding an explicit `Ctrl-S` binding for users who want deterministic save.
- Inputs: `TrackerView.on_blur()`, `update_application()`.
- Outputs: Tracker note edits provide visible feedback.
- Dependencies: None

#### Task T33: Add tests for Graph safety and Tracker save feedback
- Description: Add Textual tests for edit/delete using cursor selection, delete confirmation cancel/accept, Escape search clearing, and Tracker notes save status.
- Inputs: GraphView, TrackerView, temporary SQLite DB.
- Outputs: Regression coverage for Graph and Tracker UX polish.
- Dependencies: T29, T30, T31, T32

### M7: End-To-End UX Acceptance Coverage

#### Task T34: Add an end-to-end "happy path" TUI pilot test
- Description: Create a pilot test that launches the app, verifies Chat starts, navigates every view, starts a fake resume ingest, observes spinner/sidebar activity, creates or loads an application, renders a fake PDF, opens Apply view, edits Tracker notes, and exits cleanly. External APIs and OS open calls must be monkeypatched.
- Inputs: JobctlApp, fake provider, fake job functions, temp SQLite DB.
- Outputs: A single acceptance test proving the UX does not feel broken across major flows.
- Dependencies: T4, T14, T19, T23, T28, T33

#### Task T35: Update README and UX flow assessment after fixes land
- Description: Revise `README.md` and `docs/ux-flow-assessment.md` so documented shortcuts, palette commands, background task behavior, streaming behavior, and curation/apply semantics match the implemented product. Remove any issue marked fixed from the active issue list or move it to a resolved section.
- Inputs: Finished implementation tasks, existing docs.
- Outputs: User-facing docs and UX flow docs reflect the seamless milestone behavior.
- Dependencies: T34

#### Task T36: Run full verification and capture residual UX risks
- Description: Run the full test suite, lint, format check, and any focused TUI pilot tests. Create a short residual-risk note in the plan or a follow-up issue list for anything intentionally deferred.
- Inputs: `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`.
- Outputs: Verified milestone with remaining risks explicitly documented.
- Dependencies: T35

## Revisions

- v3.0: Initial version. Defines the seamless TUI UX hardening milestone from the current UX assessment, adding explicit streaming Chat output, background task spinner/visibility, complete workflow starts, and fixes for broken navigation, real agent mode changes, Apply, Curate, Graph, and Tracker flows.
