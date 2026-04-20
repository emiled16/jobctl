# Checklist for Plan v3.0 — Seamless TUI UX Hardening

Reference plan: `plans/plan_v3.0.md`

## M1: Navigation And Command Contract Cleanup

- [x] T1: Add a public `JobctlApp.show_view(name)` method for ContentSwitcher navigation
- [x] T2: Fix Chat slash navigation commands to use `JobctlApp.show_view`
- [x] T3: Convert palette view commands to direct `JobctlApp.show_view` actions
- [x] T4: Add Textual pilot tests for global navigation, slash navigation, and palette navigation

## M2: Streaming Chat And Inline Agent Flow Completion

- [x] T5: Make Chat streaming render one live assistant message instead of token-per-line output
- [ ] T6: Add provider streaming conformance tests for ChatView event rendering
- [ ] T7: Define a structured Chat workflow request contract
- [ ] T8: Make `/mode` update persisted `AgentState.mode` through confirmation
- [ ] T9: Add file selection validation before starting resume ingestion
- [ ] T10: Implement inline GitHub ingest input flow
- [ ] T11: Implement inline Apply input flow for Chat and palette starts
- [ ] T12: Wire proactive resume and GitHub prompts into real workflow starts
- [ ] T13: Convert palette workflow commands from raw slash text into structured UI actions
- [ ] T14: Add tests for proactive ingest prompts, Apply starts, mode changes, and palette workflow starts

## M3: Background Task Visibility And Spinner UX

- [ ] T15: Add explicit background job lifecycle events with labels and phases
- [ ] T16: Implement a reusable `SpinnerStatus` widget for active jobs
- [ ] T17: Upgrade `ProgressPanel` into a useful background jobs dashboard
- [ ] T18: Mark user-waiting jobs distinctly in spinner and sidebar
- [ ] T19: Add tests for spinner and sidebar lifecycle behavior

## M4: Apply Flow Completion And Material Actions

- [ ] T20: Persist rendered PDF paths from ApplyView actions
- [ ] T21: Implement real cover-letter generation from ApplyView or disable the button
- [ ] T22: Auto-refresh ApplyView on apply job completion
- [ ] T23: Add tests for Apply render, open-path availability, cover-letter action, and auto-refresh

## M5: Curation Flow That Actually Applies User Decisions

- [ ] T24: Implement Save and Cancel handling in `CurationProposalCard`
- [ ] T25: Add proposal application functions for merge, rephrase, connect, and prune
- [ ] T26: Wire CurateView accept/edit actions to proposal application
- [ ] T27: Implement or remove CurateView `accept_group` binding
- [ ] T28: Add tests for proposal edit and accept effects

## M6: Graph And Tracker Safety Polish

- [ ] T29: Make Graph actions operate on the tree cursor when no detail is selected
- [ ] T30: Add confirmation and status feedback for Graph delete
- [ ] T31: Resolve Escape behavior between global blur and Graph search clear
- [ ] T32: Add visible Tracker notes save status and error handling
- [ ] T33: Add tests for Graph safety and Tracker save feedback

## M7: End-To-End UX Acceptance Coverage

- [ ] T34: Add an end-to-end "happy path" TUI pilot test
- [ ] T35: Update README and UX flow assessment after fixes land
- [ ] T36: Run full verification and capture residual UX risks
