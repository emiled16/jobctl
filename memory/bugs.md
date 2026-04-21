# Bugs

## [2026-04-21] B-001: Alembic baseline used invalid SQLAlchemy real type
- Plan: v5.0
- Status: Fixed
- Severity: Medium
- Description: File-backed SQLite startup failed while running the new Alembic baseline because the migration used `sa.Real()`.
- Reproduction: Run background job tests that create a file-backed SQLite database.
- Root cause: SQLAlchemy exposes the SQLite real type as `sa.REAL()` or generic numeric types, not `sa.Real()`.
- Fix: Changed Alembic baseline columns to use `sa.REAL()`.
- Verification: `poetry run pytest tests/test_background_jobs.py tests/test_graph.py tests/test_tracker.py` and the full test suite passed.
