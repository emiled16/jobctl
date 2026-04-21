# Checklist for Plan v5.0 — Qdrant Vector Store Migration

Reference plan: `plans/plan_v5.0.md`

## M1: Storage Contracts And Configuration

- [x] T1: Add Qdrant vector store configuration to `JobctlConfig`
- [x] T2: Define RAG document and vector store contracts independent of SQLite connections
- [x] T3: Add an application runtime context that carries relational DB, vector store, config, and provider

## M2: Qdrant Runtime Implementation

- [x] T4: Add Qdrant dependencies and remove `sqlite-vec`
- [x] T5: Implement `QdrantVectorStore` using local and remote Qdrant clients
- [x] T6: Add a vector store factory and lifecycle wiring

## M3: Retrieval And Indexing Rewrite

- [x] T7: Replace `src/jobctl/db/vectors.py` with RAG indexing services
- [x] T8: Rewrite job fit retrieval to consume `VectorStore`
- [x] T9: Rewrite graph QA vector search tool to consume `VectorStore`
- [x] T10: Rewrite resume reconciliation semantic matching to consume `VectorStore`
- [x] T11: Rewrite all graph mutation paths to reindex changed nodes through Qdrant
- [x] T12: Rewrite duplicate detection to use Qdrant search instead of reading stored vectors

## M4: SQLite, SQLAlchemy, And Alembic Separation

- [x] T13: Introduce SQLAlchemy engine/session setup for the local SQLite database
- [x] T14: Add Alembic migration environment for relational schema only
- [x] T15: Remove `sqlite-vec` migrations and vector table initialization from relational startup

## M5: Existing Data Migration And Reindexing

- [x] T16: Add a Qdrant reindex command for existing projects
- [x] T17: Add a one-time startup health check for missing Qdrant index data
- [x] T18: Add a cleanup command for legacy vector artifacts

## M6: Tests And Verification

- [x] T19: Replace sqlite vector tests with Qdrant vector store contract tests
- [x] T20: Update retrieval, reconciliation, curation, and TUI tests for explicit vector store dependencies
- [x] T21: Add migration tests for old projects with SQLite vector artifacts
- [x] T22: Run focused and full verification after dependency migration

## M7: Documentation And Product Cleanup

- [x] T23: Update README and product docs for Qdrant local mode
- [x] T24: Remove obsolete sqlite vector source files and compatibility paths
