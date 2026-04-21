# Plan v1.0
[2026-04-16 14:38:59] [plan v1.0] [START] M11: Implement resume YAML generation
[2026-04-16 14:40:26] [plan v1.0] [DONE] M11: Added resume YAML schemas, generation prompt, review workflow, and tests
[2026-04-16 14:40:27] [plan v1.0] [START] M12-M18: Implement remaining milestones
[2026-04-16 14:51:01] [plan v1.0] [DONE] M12-M18: Added cover letters, rendering, tracker, apply pipeline, TUI shells, CLI wiring, tests, and README updates

---
# Plan v4.0
[2026-04-20 23:27:57] [plan v4.0] [START] T1-T13,T19-T23,T25-T27,T30-T31: Implement enriched resume reconciliation and refinement core
[2026-04-20 23:36:03] [plan v4.0] [DONE] T1-T17,T19-T27,T30-T31: Added enriched resume reconciliation, duplicate-safe persistence, durable refinement questions, chat continuation, proposal handling, tests, and docs
[2026-04-20 23:45:23] [plan v4.0] [DONE] T6,T23,T31: Added conservative relation inference for relationless resume nodes, backfilled local graph edges, and made Graph view render relationship leaves
[2026-04-21 00:08:32] [plan v4.0] [DONE] T6,T23,T31: Fixed resume ingestion failure from invalid OpenAI embedding model, made embeddings non-fatal, corrected local config, and verified retry
[2026-04-21 00:17:28] [plan v4.0] [DONE] T6,T23,T31: Promoted nested resume technology properties into skill nodes, added used_skill links, normalized relation labels, and backfilled local graph
[2026-04-21 00:23:19] [plan v4.0] [DONE] T24,T28: Added command palette entry and chat slash workflow for `/refine resume`
[2026-04-21 00:35:41] [plan v4.0] [DONE] T17,T20,T21,T28,T29: Added diff-style refinement update review with accept/reject before graph mutation
[2026-04-21 00:41:36] [plan v4.0] [DONE] T31: Fixed Apply view crash when job errors contain Rich-markup-like validation text
[2026-04-21 01:00:15] [plan v4.0] [DONE] T31: Fixed Apply JD extraction failures by delegating to provider.chat_structured, hardening ExtractedJD against null fields, and raising a clear empty-page error
[2026-04-21 01:05:35] [plan v4.0] [DONE] T31: Added hinted JSON-chat fallback in Apply shim so OpenAI strict-schema rejection of complex generation schemas (ResumeYAML/CoverLetterYAML) no longer fails the apply pipeline
