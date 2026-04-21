# Plan v4.0 — Resume Ingest Reconciliation And Refinement

## Context

Resume ingestion currently parses a resume, asks the LLM for `ExtractedFact`
objects, and persists each fact directly into the SQLite career graph. This is
useful for first-time ingestion, but repeated ingestion can create duplicate
nodes and edges. It also misses a major product opportunity: using the resume as
a coaching trigger to refine weak or vague experience into stronger,
truth-preserving graph evidence for future resume generation.

The next version should implement the behavior documented in
`docs/resume-ingest-behavior.md`.

Goals:

- Reconcile extracted resume facts against the existing graph before writing.
- Skip duplicates and avoid duplicate edges.
- Persist safe new facts so ingestion remains useful even if the user does not
  answer refinement questions.
- Generate high-value refinement questions at ingestion time.
- Ask refinement questions interactively, one at a time, with progress and a
  "later" escape path.
- Store unanswered refinement questions for later continuation.
- Convert answered questions into graph updates, including positive but truthful
  positioning such as de facto technical leadership.

Constraints:

- Do not invent experience, titles, metrics, team sizes, or responsibilities.
- Do not silently apply ambiguous matches, conflicts, or stronger title-like
  positioning.
- Preserve existing `persist_facts()` compatibility for GitHub ingestion and
  tests until callers are migrated intentionally.
- Keep extraction, reconciliation, refinement planning, interactive question
  handling, and graph update application as separate implementation concerns.

Current baseline:

- `src/jobctl/ingestion/resume.py` contains parsing, LLM extraction, and direct
  persistence.
- `src/jobctl/agent/nodes/ingest_node.py` starts resume ingestion as a
  background job.
- `src/jobctl/db/graph.py` contains basic node and edge CRUD.
- `src/jobctl/db/vectors.py` contains embedding storage and vector search.
- `src/jobctl/curation/proposals.py` and Curate UI support accept/reject/edit
  proposal review for merge/rephrase/connect/prune, but not question/answer
  refinement.
- `src/jobctl/core/events.py` already has confirmation and job lifecycle events
  that can support foreground user interaction.

## Milestones

### M1: Reconciliation Contracts And Graph Helpers

#### Task T1: Add resume reconciliation schemas for candidate matches and classified facts
- Description: Add structured Pydantic models for resume reconciliation. Define `NodeMatch`, `FactReconciliation`, `ResumeReconciliationResult`, `PositioningOpportunity`, `RefinementQuestion`, and `GraphUpdatePlan`. Keep these in a focused module such as `src/jobctl/ingestion/schemas.py` so they do not overload the generic LLM schemas. `FactReconciliation.classification` must support `duplicate`, `update`, `new`, `ambiguous`, and `conflict`. Include fields for confidence, matched node IDs, reason, source fact, proposed action, and whether user confirmation is required.
- Inputs: Existing `ExtractedFact` and graph `Node` shape.
- Outputs: Typed contracts used by reconciliation, refinement, tests, and future LangGraph nodes.
- Dependencies: None

#### Task T2: Add graph helper functions for duplicate-safe edge checks and node source writes
- Description: Extend `src/jobctl/db/graph.py` or add a small graph utility module with `edge_exists(conn, source_id, target_id, relation)`, `add_edge_if_missing(...)`, and `merge_node_properties(existing, incoming)`. Add a source helper for `node_sources`, for example `add_node_source(conn, node_id, source_type, source_ref, confidence, source_quote)`. These helpers should be conservative: property merges should preserve existing non-empty values unless the incoming value is additive or the caller explicitly requests replacement.
- Inputs: SQLite graph tables, `node_sources` table from migration 004.
- Outputs: Reusable primitives for reconciliation and update application.
- Dependencies: None

#### Task T3: Implement deterministic candidate matching for extracted resume facts
- Description: Create `src/jobctl/ingestion/reconcile.py` with `find_candidate_nodes_for_fact(conn, fact, llm_client, limit=5)`. The matcher should normalize entity type and names, search exact and partial node names with `search_nodes()`, compute fuzzy name similarity with `difflib.SequenceMatcher`, and optionally use `llm_client.get_embedding()` with `search_similar()` when embeddings are available. Return ranked `NodeMatch` objects containing node ID, type, name, text, match signals, and a numeric score.
- Inputs: `ExtractedFact`, graph nodes, node embeddings.
- Outputs: Top candidate graph nodes for each extracted fact without using the LLM for broad graph search.
- Libraries and tools: Python standard library `difflib`, existing sqlite-vec vector search.
- Dependencies: T1

#### Task T4: Implement LLM-assisted fact classification over bounded graph candidates
- Description: Add `classify_fact_against_candidates(fact, candidates, llm_client)` in `src/jobctl/ingestion/reconcile.py`. The prompt must receive one extracted fact plus only the bounded candidate list from T3. It must return structured JSON matching `FactReconciliation`. The system instructions must require conservative classification: exact or near-exact same facts are duplicates, additive details are updates, multiple plausible matches are ambiguous, contradictions are conflicts, and absent matches are new.
- Inputs: `ExtractedFact`, `list[NodeMatch]`, structured LLM client.
- Outputs: `FactReconciliation` object for a single fact.
- Dependencies: T1, T3

#### Task T5: Implement batch resume fact reconciliation with deterministic fast paths
- Description: Add `reconcile_resume_facts(conn, facts, llm_client, source_ref)` that processes extracted facts and returns `ResumeReconciliationResult`. Use deterministic fast paths before the LLM: exact same type/name should classify as duplicate, no candidates should classify as new, and high fuzzy/name matches with identical text should classify as duplicate. Use T4 only for cases requiring judgment. Include counts by classification for UI summaries.
- Inputs: List of `ExtractedFact` from resume extraction.
- Outputs: Full reconciliation result with classifications and summary counts.
- Dependencies: T1, T3, T4

### M2: Safe Persistence After Reconciliation

#### Task T6: Add duplicate-aware persistence for high-confidence new resume facts
- Description: Implement `persist_reconciled_resume_facts(conn, reconciliation, llm_client, source_ref, *, bus=None, store=None, job_id=None)`. It should skip duplicate facts, add high-confidence `new` facts, add missing edges with `add_edge_if_missing()`, attach resume source records, embed new nodes, and mark ingestion items done. It must not auto-apply ambiguous, conflict, or positioning-heavy updates.
- Inputs: `ResumeReconciliationResult`, graph connection, embedding client, source resume path.
- Outputs: Persisted graph nodes/edges for safe facts and a persistence summary.
- Dependencies: T2, T5

#### Task T7: Create update proposals for additive changes to existing graph nodes
- Description: For `update` classifications, create durable review items instead of silently replacing graph data. The first implementation may reuse `curation_proposals` with a new `update_fact` kind. Payload should include `source_type=resume`, `source_ref`, `node_id`, `current_text`, `proposed_text`, `proposed_properties`, the original extracted fact, confidence, and reason.
- Inputs: `FactReconciliation` objects classified as `update`.
- Outputs: Pending `update_fact` proposals visible in Curate.
- Dependencies: T5

#### Task T8: Extend curation proposal application for `add_fact` and `update_fact`
- Description: Extend `ProposalKind` and `apply_proposal()` to support `add_fact` and `update_fact`. `add_fact` should validate and persist an `ExtractedFact`, resolve or create related nodes conservatively, add missing edges, add source records, and embed new nodes. `update_fact` should merge proposed properties into the target node, update text representation only when present in the proposal, re-embed the node, and add source evidence.
- Inputs: Existing `CurationProposalStore`, `apply_proposal()`, `ExtractedFact` payloads.
- Outputs: Accepting resume-derived add/update proposals mutates the graph safely.
- Dependencies: T2, T7

#### Task T9: Update Curate UI rendering for resume add/update/refinement proposal kinds
- Description: Update `src/jobctl/tui/views/curate.py` labels and `src/jobctl/tui/widgets/proposal_card.py` rendering so `add_fact`, `update_fact`, and later `refine_experience` proposals show useful summaries instead of raw JSON. Display source, target node or fact name, reason, proposed text, and confirmation risk. Preserve existing edit/accept/reject behavior.
- Inputs: Proposal payload shapes from T7 and T8.
- Outputs: Curate view can review resume-derived graph changes intelligibly.
- Dependencies: T7, T8

### M3: Durable Refinement Questions

#### Task T10: Add a migration for durable refinement questions
- Description: Add a new SQLite migration in `src/jobctl/db/connection.py` for `refinement_questions`. Fields should include `id`, `source_type`, `source_ref`, `target_node_id`, `fact_json`, `category`, `prompt`, `options_json`, `allow_free_text`, `status`, `answer_text`, `answer_json`, `priority`, `created_at`, and `answered_at`. Add indexes for status, target node, and source. Status values should include `pending`, `answered`, `skipped`, `dismissed`, and `converted_to_update`.
- Inputs: Existing migration system and SQLite connection setup.
- Outputs: Durable storage for ingestion-time and later refinement.
- Dependencies: None

#### Task T11: Implement `RefinementQuestionStore` CRUD and lifecycle transitions
- Description: Add `src/jobctl/ingestion/questions.py` with a store class that can create questions, list pending questions by source or target node, get a question, mark answered, mark skipped, dismiss, and mark converted to update. It should serialize fact/options/answer JSON consistently and return typed `RefinementQuestion` objects from T1.
- Inputs: `refinement_questions` table.
- Outputs: API for both ingestion-time sessions and later refinement workflows.
- Dependencies: T1, T10

#### Task T12: Generate prioritized refinement questions from reconciliation results
- Description: Add `src/jobctl/ingestion/refinement.py` with `plan_refinement_questions(conn, reconciliation, llm_client, max_questions=5)`. The prompt should detect missing metrics, scale, ownership, technical decision-making, architecture responsibility, business impact, collaboration, mentorship, production ownership, and positive positioning opportunities. Output typed questions with category, priority, target node or target fact, optional multiple-choice options, `allow_free_text`, raw evidence, and positioning opportunity fields.
- Inputs: Reconciliation result, matched graph context, extracted facts.
- Outputs: Three to five high-value `RefinementQuestion` objects for ingestion-time use and later storage.
- Dependencies: T1, T5

#### Task T13: Persist generated refinement questions and deduplicate repeated pending questions
- Description: Use `RefinementQuestionStore` to save planned questions. Avoid creating repeated pending questions for the same source, target node, category, and materially equivalent prompt. If a similar question was answered, do not recreate it unless the new resume adds materially different evidence.
- Inputs: Planned refinement questions, source resume path, existing pending/answered questions.
- Outputs: Durable pending refinement backlog for resume ingestion.
- Dependencies: T11, T12

### M4: Ingestion-Time Interactive Refinement UX

#### Task T14: Extend resume ingestion result events with reconciliation and refinement summary counts
- Description: Add or reuse event payloads so the background resume ingestion job can tell Chat/TUI how many facts were extracted, skipped as duplicates, added, proposed as updates, and saved as refinement questions. The summary should include whether ingestion can offer an interactive refinement session.
- Inputs: `AsyncEventBus`, `IngestProgressEvent`, `IngestDoneEvent`, new reconciliation result summary.
- Outputs: UI can render a clear post-ingestion summary and next action.
- Dependencies: T5, T6, T13

#### Task T15: Add a refinement session state contract to the agent state
- Description: Extend `AgentState` or a related typed payload with a `refinement_session` record containing pending question IDs, current index, source reference, and whether the session was started during ingestion or resumed later. Provide helper functions to create, advance, stop, and clear the session.
- Inputs: `src/jobctl/agent/state.py`, persisted agent session JSON.
- Outputs: Agent can ask one question at a time and resume/stop without losing progress.
- Dependencies: T11

#### Task T16: Implement a resume refinement node that asks one pending question at a time
- Description: Add `src/jobctl/agent/nodes/refinement_node.py`. The node should load the current question, publish an assistant message with "Question N of M", render multiple-choice options when present, allow free-text answers when allowed, and include Skip, Later, and Stop semantics. It should not dump all questions at once.
- Inputs: `RefinementQuestionStore`, refinement session state, `AsyncEventBus`.
- Outputs: One-question-at-a-time interactive refinement behavior.
- Dependencies: T11, T15

#### Task T17: Route refinement answers from Chat into the active refinement session
- Description: Update `ChatView` and/or `LangGraphRunner` workflow submission so user answers during an active refinement session are sent as structured refinement answer payloads, not normal chat. Support multiple-choice selection, custom free text, `skip`, and `later`. The runner should advance the session after each handled answer.
- Inputs: `ChatView._handle_submission()`, `LangGraphRunner`, `AgentState.refinement_session`.
- Outputs: User answers are captured against the correct pending question.
- Dependencies: T15, T16

#### Task T18: Offer start-now or later refinement after resume ingestion completes
- Description: After resume ingestion creates pending questions, show a summary and a clear choice: Start refinement, Later, Review graph. Start refinement should initialize the session and route to `refinement_node`. Later should leave questions pending and tell the user how to resume. Review graph should switch to Graph view without discarding pending questions.
- Inputs: Resume ingestion completion event, Chat/TUI interaction components, `JobctlApp.show_view()`.
- Outputs: Ingestion-time refinement is available but not mandatory.
- Dependencies: T14, T15, T16

### M5: Answer-To-Graph Enrichment

#### Task T19: Implement answer extraction into graph update plans
- Description: Add `src/jobctl/ingestion/enrichment.py` with `build_graph_update_from_answer(question, answer, llm_client)`. It should convert the user's answer into `GraphUpdatePlan` containing node updates, new extracted facts, new edges, source evidence, resume-ready phrasing, and positioning confirmation status. The prompt must enforce factual guardrails and separate confirmed facts from suggested phrasing.
- Inputs: `RefinementQuestion`, user answer text, LLM client.
- Outputs: Structured graph update plan ready for confirmation or safe application.
- Dependencies: T1, T11

#### Task T20: Apply low-risk answered refinement updates to the graph
- Description: Implement `apply_graph_update_plan(conn, plan, llm_client, source_ref)`. Low-risk additive updates may be applied directly: adding metrics from the answer, appending confirmed context, adding skill/project/achievement edges with existing nodes, adding source records, and re-embedding touched nodes. Strong positioning, title-like wording, conflicts, and destructive replacements should create review proposals instead of direct updates.
- Inputs: `GraphUpdatePlan`, graph CRUD helpers, embedding client.
- Outputs: Answered refinement questions enrich the graph while preserving guardrails.
- Dependencies: T2, T8, T19

#### Task T21: Mark refinement question lifecycle after graph update handling
- Description: After an answer is processed, mark the question `answered`; after its update plan is applied or converted to a proposal, mark it `converted_to_update`. If the user skips or defers, mark `skipped` or keep `pending` according to the chosen action. Ensure session progress and durable question state cannot diverge.
- Inputs: `RefinementQuestionStore`, update application result, session state.
- Outputs: Accurate pending/answered refinement backlog.
- Dependencies: T11, T17, T20

### M6: Resume Ingestion Pipeline Integration

#### Task T22: Add `ingest_resume_enriched()` as the new resume ingestion orchestration function
- Description: Implement a single orchestration function that reads the resume, extracts facts, reconciles facts, persists safe facts, creates update/add proposals as needed, plans and stores refinement questions, publishes progress events, and returns a summary. Keep `extract_facts_from_resume()` and `persist_facts()` available for compatibility.
- Inputs: Resume path, SQLite connection, LLM/embedding client, event bus, background job store, proposal store, refinement question store.
- Outputs: Enriched resume ingestion result with counts and pending question IDs.
- Dependencies: T5, T6, T7, T13, T14

#### Task T23: Wire background resume ingestion to `ingest_resume_enriched()`
- Description: Update `start_resume_ingest()` in `src/jobctl/agent/nodes/ingest_node.py` so resume jobs call the enriched ingestion function. The `_Shim` provider adapter must support any structured calls and embeddings required by reconciliation and refinement. Publish the final ingestion summary so Chat can offer refinement now or later.
- Inputs: Existing background resume ingestion job, provider shim, database path handoff.
- Outputs: Normal resume ingestion uses duplicate management and refinement planning.
- Dependencies: T22

#### Task T24: Add a later-resume-refinement entrypoint
- Description: Add a workflow request kind or slash command such as `/refine resume` or "continue resume refinement" that loads pending refinement questions and starts the one-question-at-a-time session. It should work independently of the original ingestion job and should prioritize older/high-priority pending questions.
- Inputs: `workflow_request_from_state()`, router, `RefinementQuestionStore`.
- Outputs: Users can defer refinement during ingestion and continue later.
- Dependencies: T15, T16, T17

### M7: Tests And Documentation

#### Task T25: Add unit tests for deterministic candidate matching and classification fast paths
- Description: Test exact duplicate detection, type-filtered matching, fuzzy name matching, no-candidate new classification, and bounded candidate output. Use in-memory SQLite and fake embedding clients.
- Inputs: `reconcile.py`, graph fixtures.
- Outputs: Regression coverage for non-LLM reconciliation behavior.
- Dependencies: T3, T5

#### Task T26: Add unit tests for safe persistence and proposal creation
- Description: Test that duplicate facts are skipped, high-confidence new facts are added once, duplicate edges are not created, update classifications create `update_fact` proposals, and source records are attached. Include tests for applying `add_fact` and `update_fact` proposals.
- Inputs: `persist_reconciled_resume_facts()`, `CurationProposalStore`, `apply_proposal()`.
- Outputs: Regression coverage for duplicate-safe graph mutations.
- Dependencies: T6, T7, T8

#### Task T27: Add unit tests for refinement question generation and storage lifecycle
- Description: Test that planner output is capped, questions are stored with status `pending`, repeated equivalent questions are deduplicated, answers can be marked, skipped questions remain resumable according to policy, and dismissed questions do not appear in pending lists.
- Inputs: `RefinementQuestionStore`, `plan_refinement_questions()`.
- Outputs: Regression coverage for deferred refinement behavior.
- Dependencies: T11, T12, T13

#### Task T28: Add agent and TUI tests for ingestion-time one-question refinement
- Description: Add tests that simulate resume ingestion completion with pending questions, show the start-now/later choice, start a refinement session, ask "Question 1 of N", accept a multiple-choice or free-text answer, advance to the next question, and stop with remaining questions pending. Cover the Later path to ensure facts are still stored.
- Inputs: `ChatView`, `LangGraphRunner`, `refinement_node`, Textual pilot tests.
- Outputs: End-to-end UX coverage for ingestion-time refinement.
- Dependencies: T16, T17, T18, T23

#### Task T29: Add tests for answer-to-graph enrichment guardrails
- Description: Test that confirmed metric answers update graph properties and achievements, technical leadership answers create confirmed positioning only when the answer supports it, title-like claims create proposals when confirmation is insufficient, and invented/disallowed fields from the LLM are rejected by schema validation.
- Inputs: `build_graph_update_from_answer()`, `apply_graph_update_plan()`.
- Outputs: Guardrail coverage for positive but truthful positioning.
- Dependencies: T19, T20, T21

#### Task T30: Update README and behavior docs for resume ingest v2
- Description: Update README workflow descriptions and `docs/resume-ingest-behavior.md` with any final command names, UI entrypoints, persistence behavior, and resume refinement lifecycle that differ from the initial plan. Keep examples aligned with implemented prompt behavior.
- Inputs: Implemented UX and commands.
- Outputs: User-facing documentation matches runtime behavior.
- Dependencies: T18, T24

#### Task T31: Run focused and full verification for resume ingest v2
- Description: Run focused tests for ingestion, reconciliation, refinement, curation apply, and TUI flows, then run the full project test suite. Capture any known limitations or follow-up risks in `docs/bugs.md` or `docs/progress.md` according to existing project practice.
- Inputs: Test suite and documentation updates.
- Outputs: Verified implementation with documented residual risks.
- Dependencies: T25, T26, T27, T28, T29, T30

## Revisions

- v4.0: Initial version. Defines the implementation plan for duplicate-aware
  resume ingestion, ingestion-time one-question-at-a-time refinement, deferred
  refinement continuation, and answer-to-graph enrichment.
