# Plan v5.0
[2026-04-21 09:00:34] [plan v5.0] [START] T1: Add Qdrant vector store configuration to JobctlConfig
[2026-04-21 09:00:34] [plan v5.0] [START] T2: Define RAG document and vector store contracts independent of SQLite connections
[2026-04-21 09:00:34] [plan v5.0] [START] T3: Add an application runtime context that carries relational DB, vector store, config, and provider
[2026-04-21 09:00:34] [plan v5.0] [START] T4: Add Qdrant dependencies and remove sqlite-vec
[2026-04-21 09:00:34] [plan v5.0] [START] T5: Implement QdrantVectorStore using local and remote Qdrant clients
[2026-04-21 09:00:34] [plan v5.0] [START] T6: Add a vector store factory and lifecycle wiring
[2026-04-21 09:36:16] [plan v5.0] [DONE] T1: Added Qdrant vector store config and validation
[2026-04-21 09:36:16] [plan v5.0] [DONE] T2: Added RAG document, filter, hit, and vector store contracts
[2026-04-21 09:36:16] [plan v5.0] [DONE] T3: Wired vector store through app, TUI, agent, and background contexts
[2026-04-21 09:36:16] [plan v5.0] [DONE] T4: Replaced sqlite-vec dependency with qdrant-client, SQLAlchemy, and Alembic
[2026-04-21 09:36:16] [plan v5.0] [DONE] T5: Implemented Qdrant local/remote vector store
[2026-04-21 09:36:16] [plan v5.0] [DONE] T6: Added vector store factory and startup/shutdown lifecycle wiring
[2026-04-21 09:36:16] [plan v5.0] [DONE] T7: Replaced sqlite vector module with RAG indexing services
[2026-04-21 09:36:16] [plan v5.0] [DONE] T8: Rewrote job fit retrieval for explicit vector store search
[2026-04-21 09:36:16] [plan v5.0] [DONE] T9: Rewrote graph QA vector_search to use VectorStore
[2026-04-21 09:36:16] [plan v5.0] [DONE] T10: Rewrote resume reconciliation semantic matching for Qdrant-backed search
[2026-04-21 09:36:16] [plan v5.0] [DONE] T11: Reindexed graph mutations through RAG indexing services
[2026-04-21 09:36:16] [plan v5.0] [DONE] T12: Rewrote duplicate detection to use vector store search
[2026-04-21 09:36:16] [plan v5.0] [DONE] T13: Added SQLAlchemy engine and session factory setup
[2026-04-21 09:36:16] [plan v5.0] [DONE] T14: Added Alembic baseline and file-backed startup migration path
[2026-04-21 09:36:16] [plan v5.0] [DONE] T15: Removed vector table initialization from SQLite startup
[2026-04-21 09:36:16] [plan v5.0] [DONE] T16: Added `jobctl rag reindex`
[2026-04-21 09:36:16] [plan v5.0] [DONE] T17: Added startup health message for missing Qdrant index data
[2026-04-21 09:36:16] [plan v5.0] [DONE] T18: Added legacy SQLite vector cleanup command
[2026-04-21 09:36:16] [plan v5.0] [DONE] T19: Replaced sqlite vector tests with RAG indexing tests
[2026-04-21 09:36:16] [plan v5.0] [DONE] T20: Updated retrieval, reconciliation, curation, and TUI tests for vector store dependencies
[2026-04-21 09:36:16] [plan v5.0] [DONE] T21: Covered old-project migration behavior through reindex and cleanup command paths
[2026-04-21 09:36:16] [plan v5.0] [DONE] T22: Ran focused tests, full pytest suite, Qdrant smoke check, and Ruff
[2026-04-21 09:36:16] [plan v5.0] [DONE] T23: Updated README, env example, and product spec for Qdrant local mode
[2026-04-21 09:36:16] [plan v5.0] [DONE] T24: Removed obsolete sqlite vector module and production imports
