"""RAG maintenance commands."""

from __future__ import annotations

from pathlib import Path

import typer

from jobctl.app.common import command_error
from jobctl.config import CONFIG_DIR_NAME, find_project_root, load_config
from jobctl.db.connection import get_connection
from jobctl.llm.registry import get_provider
from jobctl.rag.factory import create_vector_store
from jobctl.rag.indexing import document_id_for_node, index_all_nodes

app = typer.Typer(help="Maintain the Qdrant RAG index.")


@app.command("reindex")
def reindex_command(
    force: bool = typer.Option(False, "--force", help="Reindex nodes already present in Qdrant."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show counts without writing Qdrant data."),
) -> None:
    project_root = find_project_root(Path.cwd())
    config = load_config(project_root)
    db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
    conn = get_connection(db_path)
    vector_store = create_vector_store(config, project_root)
    try:
        total_nodes = conn.execute("SELECT COUNT(*) AS count FROM nodes").fetchone()["count"]
        existing = set(vector_store.list_document_ids())
        missing = conn.execute("SELECT id FROM nodes ORDER BY created_at, id").fetchall()
        missing_ids = [
            row["id"] for row in missing if force or document_id_for_node(row["id"]) not in existing
        ]
        if dry_run:
            typer.echo(
                f"Would index {len(missing_ids)} of {total_nodes} graph nodes into "
                f"Qdrant collection {config.vector_store.collection!r}."
            )
            return
        provider = get_provider(config, cwd=project_root)
        from jobctl.llm.adapter import as_embedding_client

        indexed = index_all_nodes(
            conn,
            vector_store,
            as_embedding_client(provider),
            config=config,
            force=force,
        )
        stale_ids = sorted(
            doc_id
            for doc_id in existing
            if doc_id.startswith("node:")
            and not conn.execute(
                "SELECT 1 FROM nodes WHERE id = ?",
                (doc_id.removeprefix("node:"),),
            ).fetchone()
        )
        if stale_ids:
            vector_store.delete_documents(stale_ids)
        typer.echo(
            f"Indexed {indexed} node(s), skipped {total_nodes - indexed}, "
            f"deleted {len(stale_ids)} stale vector document(s)."
        )
    finally:
        vector_store.close()
        conn.close()


@app.command("cleanup-legacy-vectors")
def cleanup_legacy_vectors_command(
    yes: bool = typer.Option(False, "--yes", help="Confirm dropping legacy SQLite vector table."),
) -> None:
    if not yes:
        raise command_error("Pass --yes to drop legacy SQLite vector artifacts.")
    project_root = find_project_root(Path.cwd())
    config = load_config(project_root)
    db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
    conn = get_connection(db_path)
    vector_store = create_vector_store(config, project_root)
    try:
        node_ids = [row["id"] for row in conn.execute("SELECT id FROM nodes").fetchall()]
        qdrant_ids = set(vector_store.list_document_ids())
        missing = [node_id for node_id in node_ids if document_id_for_node(node_id) not in qdrant_ids]
        if missing:
            raise command_error(
                f"Refusing cleanup: {len(missing)} graph node(s) are missing from Qdrant. "
                "Run `jobctl rag reindex` first."
            )
        conn.execute("DROP TABLE IF EXISTS node_embeddings")
        conn.commit()
        typer.echo("Dropped legacy SQLite vector artifacts.")
    finally:
        vector_store.close()
        conn.close()


def qdrant_health_message(project_root: Path, conn, vector_store) -> str | None:
    node_count = conn.execute("SELECT COUNT(*) AS count FROM nodes").fetchone()["count"]
    if int(node_count) == 0:
        return None
    indexed_count = vector_store.count_documents()
    if indexed_count:
        return None
    return (
        "This project has graph nodes but no Qdrant RAG index yet. "
        "Run `jobctl rag reindex` to enable semantic retrieval."
    )
