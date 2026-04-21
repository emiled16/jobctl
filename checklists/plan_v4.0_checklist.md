# Checklist for Plan v4.0 — Resume Ingest Reconciliation And Refinement

Reference plan: `plans/plan_v4.0.md`

## M1: Reconciliation Contracts And Graph Helpers

- [x] T1: Add resume reconciliation schemas for candidate matches and classified facts
- [x] T2: Add graph helper functions for duplicate-safe edge checks and node source writes
- [x] T3: Implement deterministic candidate matching for extracted resume facts
- [x] T4: Implement LLM-assisted fact classification over bounded graph candidates
- [x] T5: Implement batch resume fact reconciliation with deterministic fast paths

## M2: Safe Persistence After Reconciliation

- [x] T6: Add duplicate-aware persistence for high-confidence new resume facts
- [x] T7: Create update proposals for additive changes to existing graph nodes
- [x] T8: Extend curation proposal application for `add_fact` and `update_fact`
- [x] T9: Update Curate UI rendering for resume add/update/refinement proposal kinds

## M3: Durable Refinement Questions

- [x] T10: Add a migration for durable refinement questions
- [x] T11: Implement `RefinementQuestionStore` CRUD and lifecycle transitions
- [x] T12: Generate prioritized refinement questions from reconciliation results
- [x] T13: Persist generated refinement questions and deduplicate repeated pending questions

## M4: Ingestion-Time Interactive Refinement UX

- [x] T14: Extend resume ingestion result events with reconciliation and refinement summary counts
- [x] T15: Add a refinement session state contract to the agent state
- [x] T16: Implement a resume refinement node that asks one pending question at a time
- [x] T17: Route refinement answers from Chat into the active refinement session
- [ ] T18: Offer start-now or later refinement after resume ingestion completes

## M5: Answer-To-Graph Enrichment

- [x] T19: Implement answer extraction into graph update plans
- [x] T20: Apply low-risk answered refinement updates to the graph
- [x] T21: Mark refinement question lifecycle after graph update handling

## M6: Resume Ingestion Pipeline Integration

- [x] T22: Add `ingest_resume_enriched()` as the new resume ingestion orchestration function
- [x] T23: Wire background resume ingestion to `ingest_resume_enriched()`
- [x] T24: Add a later-resume-refinement entrypoint

## M7: Tests And Documentation

- [x] T25: Add unit tests for deterministic candidate matching and classification fast paths
- [x] T26: Add unit tests for safe persistence and proposal creation
- [x] T27: Add unit tests for refinement question generation and storage lifecycle
- [ ] T28: Add agent and TUI tests for ingestion-time one-question refinement
- [ ] T29: Add tests for answer-to-graph enrichment guardrails
- [x] T30: Update README and behavior docs for resume ingest v2
- [x] T31: Run focused and full verification for resume ingest v2
