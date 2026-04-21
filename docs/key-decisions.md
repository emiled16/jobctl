# Key Decisions

## [2026-04-16] D-001: Use Lazy WeasyPrint Import
- Plan: v1.0
- Context: PDF rendering needs WeasyPrint, but native libraries may be missing in local development environments.
- Options considered:
  - Import WeasyPrint at module import time
  - Import WeasyPrint only when rendering a PDF
- Decision: Import WeasyPrint lazily inside the renderer.
- Rationale: The CLI, tests, and non-rendering workflows should remain usable even when PDF system libraries are not installed.
- Consequences: `jobctl render` reports the missing native dependency at command time.

## [2026-04-20] D-002: Keep Legacy Fact Persistence While Adding Enriched Resume Ingestion
- Plan: v4.0
- Context: Resume ingestion needs reconciliation and refinement, but GitHub ingestion and existing tests still rely on direct fact persistence.
- Options considered:
  - Replace `persist_facts()` for all callers immediately
  - Add `ingest_resume_enriched()` and keep `persist_facts()` compatible
- Decision: Add a resume-specific enriched orchestration path and preserve `persist_facts()`.
- Rationale: This limits migration risk while enabling duplicate-aware resume ingestion.
- Consequences: GitHub ingestion keeps the older persistence path until it is intentionally migrated.
