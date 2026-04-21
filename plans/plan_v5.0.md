# Plan v5.0 — Qdrant Vector Store Migration

## Context

`jobctl` currently stores graph records, application workflow state, agent
sessions, ingestion state, and vector embeddings in the same SQLite database.
Vector search is implemented by `src/jobctl/db/vectors.py` with `sqlite-vec`
when available and a JSON/Python fallback otherwise. Several call sites import
these functions directly, and `src/jobctl/curation/duplicates.py` reads the
`node_embeddings` table manually.

The desired architecture is:

- SQLite remains the local relational database for app state such as events,
  conversations, agent sessions, jobs, tracker records, curation proposals, and
  other workflow data.
- SQLite access moves toward SQLAlchemy and Alembic for relational persistence.
- Qdrant becomes the vector database for RAG data and the only vector backend.
- Local usage remains single-process: new projects use Qdrant Python local mode
  with persistent storage under `.jobctl/qdrant/`.
- The implementation should remove `sqlite-vec` and old vector table behavior
  instead of adapting Qdrant to the previous `sqlite3.Connection` vector API.

Current baseline:

- `src/jobctl/db/connection.py` initializes SQLite and calls `init_vec(conn)`.
- `src/jobctl/db/vectors.py` owns `node_embeddings`, embedding upsert/search,
  and `embed_node()` / `embed_all_nodes()`.
- Vector consumers include evaluator retrieval, graph QA, resume reconciliation,
  ingestion enrichment, curation apply, Graph UI edits, duplicate detection, and
  vector tests.
- `pyproject.toml` depends on `sqlite-vec` and does not depend on
  `qdrant-client`, SQLAlchemy, or Alembic.
- The migration system is currently a hand-rolled Python migration list in
  `src/jobctl/db/connection.py`.

## Milestones

### M1: Storage Contracts And Configuration

#### Task T1: Add Qdrant vector store configuration to `JobctlConfig`
- Description: Extend `src/jobctl/config.py` with a `VectorStoreConfig` dataclass containing `provider`, `mode`, `path`, `url`, `api_key_env`, `collection`, and `distance`. Default to `provider="qdrant"`, `mode="local"`, `path=".jobctl/qdrant"`, `collection="jobctl_nodes"`, and cosine distance. Add validation so only Qdrant is supported after this migration, local mode requires a path, and remote mode requires a URL. Expose dotted config keys through `config_field_names()`.
- Inputs: Existing config loading, saving, and dotted key replacement behavior.
- Outputs: Runtime configuration for local and remote Qdrant without requiring a second local process.
- Dependencies: None

#### Task T2: Define RAG document and vector store contracts independent of SQLite connections
- Description: Create a new module such as `src/jobctl/rag/store.py` with typed contracts for `RagDocument`, `VectorHit`, and `VectorStore`. `RagDocument` should contain `id`, `text`, `embedding`, and payload fields such as `node_id`, `node_type`, `name`, `source_type`, `source_ref`, `embedding_model`, and timestamps. `VectorStore` should expose explicit methods such as `ensure_ready()`, `upsert_documents(documents)`, `delete_documents(ids)`, `search(embedding, top_k, filters=None)`, `list_document_ids(filters=None)`, and `close()`. The contract must not accept or depend on `sqlite3.Connection`.
- Inputs: Current node embedding requirements and Qdrant payload/filter concepts.
- Outputs: New vector storage boundary used by all RAG callers.
- Dependencies: T1

#### Task T3: Add an application runtime context that carries relational DB, vector store, config, and provider
- Description: Introduce an object such as `JobctlContext` in `src/jobctl/app/context.py`. It should own the SQLite connection, SQLAlchemy session factory once added, Qdrant vector store, config, provider, project root, DB path, event bus, and job runner dependencies. Update TUI and agent construction paths to receive this context or explicit `vector_store` dependency rather than allowing vector code to be discovered through module-level imports.
- Inputs: `JobctlApp`, `LangGraphRunner`, `build_graph()`, app startup helpers.
- Outputs: A dependency boundary that makes Qdrant an application resource instead of a hidden database side effect.
- Dependencies: T1, T2

### M2: Qdrant Runtime Implementation

#### Task T4: Add Qdrant dependencies and remove `sqlite-vec`
- Description: Update `pyproject.toml` and the lock file to add `qdrant-client` and remove `sqlite-vec`. Keep installation single-process by using Qdrant Python local mode. Do not add Docker, Compose, or a required server process. Remove imports of `sqlite_vec` from application code and tests.
- Inputs: Current dependency declarations and lock file.
- Outputs: Package dependencies match the new vector backend.
- Libraries and tools: `qdrant-client`.
- Dependencies: T2

#### Task T5: Implement `QdrantVectorStore` using local and remote Qdrant clients
- Description: Add `src/jobctl/rag/qdrant_store.py` implementing the `VectorStore` contract. In local mode, initialize `QdrantClient(path=<project-root-resolved-path>)`; in remote mode, initialize `QdrantClient(url=..., api_key=...)`. `ensure_ready()` should create or update the configured collection with the configured vector size and distance. `upsert_documents()` should use stable point IDs derived from document IDs, store full retrieval metadata as Qdrant payload, and fail clearly on embedding dimension mismatch. `search()` should translate typed filters into Qdrant filters and return `VectorHit` objects.
- Inputs: `VectorStoreConfig`, `RagDocument`, embedding dimensions.
- Outputs: Persistent local Qdrant vector storage and optional remote Qdrant compatibility.
- Dependencies: T1, T2, T4

#### Task T6: Add a vector store factory and lifecycle wiring
- Description: Add `create_vector_store(config, project_root)` that returns `QdrantVectorStore`, calls `ensure_ready()` during app startup, and closes the store during app shutdown if the client exposes close semantics. Wire this into CLI/TUI startup and background job contexts so foreground and worker paths open their own Qdrant clients against the same local path.
- Inputs: App startup in `run_tui()`, `JobctlApp`, background job runner DB path handoff.
- Outputs: Qdrant is initialized automatically for users without starting a second process.
- Dependencies: T3, T5

### M3: Retrieval And Indexing Rewrite

#### Task T7: Replace `src/jobctl/db/vectors.py` with RAG indexing services
- Description: Delete the old sqlite-backed vector storage implementation. Add a module such as `src/jobctl/rag/indexing.py` with functions that build `RagDocument` objects from graph nodes, embed node text with the configured embedding client, and upsert them through `VectorStore`. Provide explicit services such as `index_node(conn, vector_store, node_id, embedding_client)`, `index_nodes(conn, vector_store, node_ids, embedding_client)`, and `index_all_nodes(conn, vector_store, embedding_client)`. These services may query SQLite for node text, but all vector persistence must go through Qdrant.
- Inputs: Existing `nodes` table, embedding clients, `VectorStore`.
- Outputs: Qdrant-backed node indexing with no `node_embeddings` table.
- Dependencies: T2, T5

#### Task T8: Rewrite job fit retrieval to consume `VectorStore`
- Description: Update `src/jobctl/jobs/evaluator.py` so `retrieve_relevant_experience()` accepts a vector store dependency and calls `vector_store.search()` directly. Keep graph expansion through `get_subgraph(conn, node_id, depth=1)` after Qdrant returns node IDs. Update all callers, including apply pipeline and tests, so the vector store is passed explicitly.
- Inputs: `ExtractedJD`, embedding client, graph connection, vector store.
- Outputs: Job fit evaluation retrieves RAG candidates from Qdrant.
- Dependencies: T7

#### Task T9: Rewrite graph QA vector search tool to consume `VectorStore`
- Description: Update `src/jobctl/agent/nodes/graph_qa_node.py` so the `vector_search` tool uses a vector store dependency supplied by graph construction or runtime context. The tool should embed the user query, search Qdrant, load matched graph nodes from SQLite, and return the same user-facing node summaries without importing vector helpers inside the tool handler.
- Inputs: LangGraph build dependencies, provider embeddings, graph connection.
- Outputs: Agent graph QA no longer imports `jobctl.db.vectors`.
- Dependencies: T3, T7

#### Task T10: Rewrite resume reconciliation semantic matching to consume `VectorStore`
- Description: Update `src/jobctl/ingestion/reconcile.py` so `find_candidate_nodes_for_fact()` accepts a vector store dependency for optional semantic matching. Preserve deterministic exact/fuzzy matching through SQLite graph queries, but semantic candidates must come from Qdrant filters instead of `search_similar(conn, ...)`.
- Inputs: Extracted facts, graph connection, embedding client, vector store.
- Outputs: Resume reconciliation uses Qdrant for semantic candidate lookup.
- Dependencies: T7

#### Task T11: Rewrite all graph mutation paths to reindex changed nodes through Qdrant
- Description: Replace calls to `embed_node(conn, node_id, llm_client)` in resume ingestion, enrichment, curation proposal application, and Graph UI edits with explicit `index_node(conn, vector_store, node_id, embedding_client)` calls. Update function signatures and caller chains as needed instead of keeping compatibility wrappers. Ensure node deletions and merges delete obsolete Qdrant documents.
- Inputs: `src/jobctl/ingestion/resume.py`, `src/jobctl/ingestion/enrichment.py`, `src/jobctl/curation/apply.py`, `src/jobctl/tui/views/graph.py`, related agent nodes.
- Outputs: Every graph write path keeps Qdrant synchronized with changed nodes.
- Dependencies: T7

#### Task T12: Rewrite duplicate detection to use Qdrant search instead of reading stored vectors
- Description: Replace `_load_embeddings()` in `src/jobctl/curation/duplicates.py` with a Qdrant-based candidate generation strategy. For each node or indexed document, search nearby vectors in Qdrant with same-type filters, combine semantic score with fuzzy name similarity, and return `DuplicateCandidate` objects. Remove manual vector deserialization, JSON fallback handling, and any direct reference to `node_embeddings`.
- Inputs: Graph nodes, vector store search, fuzzy name matching.
- Outputs: Duplicate candidate generation works without SQLite vector storage.
- Dependencies: T7

### M4: SQLite, SQLAlchemy, And Alembic Separation

#### Task T13: Introduce SQLAlchemy engine/session setup for the local SQLite database
- Description: Add `src/jobctl/db/engine.py` with SQLAlchemy engine creation, session factory creation, SQLite pragmas, and project path handling. Keep compatibility with the current `sqlite3.Connection` call sites during the first phase by allowing both a SQLAlchemy engine and legacy connection to be created from the same `.jobctl/jobctl.db` path. Do not include vector initialization in relational DB setup.
- Inputs: Existing SQLite DB path conventions and connection pragmas.
- Outputs: SQLAlchemy foundation for local relational state.
- Libraries and tools: SQLAlchemy.
- Dependencies: None

#### Task T14: Add Alembic migration environment for relational schema only
- Description: Add Alembic configuration and migration scripts for the current relational schema. The initial Alembic baseline should include graph, tracker, ingestion job, node source, agent session, curation proposal, embedding metadata if still needed for model tracking, and refinement question tables. It must not create `node_embeddings` or any Qdrant collection. Update startup to run Alembic migrations instead of the hand-rolled migration list once the baseline is verified.
- Inputs: Current migration list in `src/jobctl/db/connection.py`.
- Outputs: Alembic-managed SQLite schema for non-vector local data.
- Libraries and tools: Alembic, SQLAlchemy.
- Dependencies: T13

#### Task T15: Remove `sqlite-vec` migrations and vector table initialization from relational startup
- Description: Delete `init_vec(conn)` calls from `get_connection()`, remove vector table creation from runtime startup, and ensure new SQLite databases are created without `node_embeddings`. If `embedding_meta` remains useful, keep it as relational metadata only and document that the actual vectors live in Qdrant. Add a cleanup migration or maintenance command for existing local projects that drops `node_embeddings` after Qdrant reindexing succeeds.
- Inputs: Existing local database initialization and migration code.
- Outputs: SQLite no longer owns or initializes vector storage.
- Dependencies: T7, T14

### M5: Existing Data Migration And Reindexing

#### Task T16: Add a Qdrant reindex command for existing projects
- Description: Add a command such as `jobctl rag reindex` that reads all graph nodes from SQLite, embeds `text_representation`, and upserts the resulting documents into Qdrant. The command should report indexed, skipped, failed, and deleted-stale counts. It should support `--force` to overwrite existing Qdrant documents and `--dry-run` to show planned changes.
- Inputs: Existing graph nodes, embedding provider, vector store config.
- Outputs: Existing projects can populate Qdrant without relying on old `node_embeddings`.
- Dependencies: T6, T7

#### Task T17: Add a one-time startup health check for missing Qdrant index data
- Description: During app startup, detect when SQLite contains graph nodes but Qdrant has no matching documents. Surface a clear TUI/CLI message that retrieval needs `jobctl rag reindex` or offer to run the reindex workflow. Do not silently fall back to SQLite vector tables.
- Inputs: Node count from SQLite, document count from Qdrant.
- Outputs: Users get an actionable migration path when opening an older project.
- Dependencies: T6, T16

#### Task T18: Add a cleanup command for legacy vector artifacts
- Description: Add a command such as `jobctl rag cleanup-legacy-vectors` that verifies Qdrant contains indexed documents for current graph nodes and then removes old SQLite vector artifacts such as `node_embeddings`. Require an explicit confirmation flag such as `--yes`. Keep this separate from reindexing so destructive cleanup is deliberate.
- Inputs: Existing SQLite database, Qdrant indexed document IDs.
- Outputs: Legacy vector storage can be removed safely after migration.
- Dependencies: T15, T16

### M6: Tests And Verification

#### Task T19: Replace sqlite vector tests with Qdrant vector store contract tests
- Description: Delete `tests/test_vectors.py` coverage for `sqlite-vec` and add tests for the `VectorStore` contract using Qdrant local `:memory:` or temporary path mode. Cover collection initialization, upsert, overwrite, filtered search, delete, invalid embedding dimensions, and persistence across client reopen when using a path.
- Inputs: `QdrantVectorStore`, temporary test directories.
- Outputs: Regression coverage for Qdrant-backed vector storage.
- Dependencies: T5

#### Task T20: Update retrieval, reconciliation, curation, and TUI tests for explicit vector store dependencies
- Description: Update tests that currently monkeypatch `search_similar()` or import `EMBEDDING_DIMENSIONS` from `jobctl.db.vectors`. Provide fake `VectorStore` implementations where unit tests do not need Qdrant, and use temporary Qdrant stores for integration tests. Ensure evaluator, graph QA, reconciliation, duplicate detection, curation apply, resume ingestion, and Graph UI tests pass without `sqlite-vec`.
- Inputs: Existing tests under `tests/` and `tests/tui/`.
- Outputs: The test suite validates the new dependency flow and no longer relies on the old vector module.
- Dependencies: T8, T9, T10, T11, T12, T19

#### Task T21: Add migration tests for old projects with SQLite vector artifacts
- Description: Create test fixtures that simulate an existing `.jobctl/jobctl.db` with graph nodes and old `node_embeddings`. Verify startup does not initialize `sqlite-vec`, `rag reindex` indexes all graph nodes into Qdrant, health checks detect missing Qdrant data, and cleanup removes legacy artifacts only after Qdrant coverage is complete.
- Inputs: Temporary SQLite databases, temporary Qdrant paths.
- Outputs: Confidence that existing local projects can move forward cleanly.
- Dependencies: T16, T17, T18

#### Task T22: Run focused and full verification after dependency migration
- Description: Run focused tests for config, Qdrant store, reindexing, evaluator retrieval, graph QA, reconciliation, curation, and TUI graph editing, then run the full test suite. Run linting if available. Capture residual migration risks in `docs/bugs.md` or `docs/progress.md`.
- Inputs: Updated code and test suite.
- Outputs: Verified Qdrant migration with documented residual risks.
- Dependencies: T19, T20, T21

### M7: Documentation And Product Cleanup

#### Task T23: Update README and product docs for Qdrant local mode
- Description: Update README, `.env.example`, `docs/product-spec.md`, and relevant plan references to describe Qdrant as the vector store, local embedded Qdrant path under `.jobctl/qdrant/`, remote Qdrant configuration, reindexing commands, and the fact that SQLite remains for relational app state. Remove user-facing `sqlite-vec` references from current documentation.
- Inputs: Implemented config and commands.
- Outputs: Documentation matches the new storage architecture.
- Dependencies: T16, T17, T18

#### Task T24: Remove obsolete sqlite vector source files and compatibility paths
- Description: Delete obsolete vector modules, fallback code, imports, tests, and docs that preserve `sqlite-vec` behavior. Ensure no production code imports `jobctl.db.vectors`, queries `node_embeddings`, imports `sqlite_vec`, or describes SQLite as the vector backend. Keep only migration/cleanup references needed for existing project upgrades.
- Inputs: Completed code migration.
- Outputs: The codebase has one vector backend and one RAG storage contract.
- Dependencies: T15, T20, T23

## Revisions

- v5.0: Initial version. Defines the migration from SQLite/`sqlite-vec` vector
  storage to Qdrant local mode, with explicit vector store dependencies,
  SQLAlchemy/Alembic separation for relational SQLite data, existing project
  reindexing, legacy cleanup, tests, and documentation.
