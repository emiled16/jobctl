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
