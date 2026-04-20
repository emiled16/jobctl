"""Knowledge graph TUI view (ported from v1 ProfileScreen)."""

from __future__ import annotations

import json
import sqlite3

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Select, Static, TextArea, Tree

from jobctl.db.graph import (
    add_node,
    delete_node,
    get_edges_from,
    get_edges_to,
    get_node,
    update_node,
)
from jobctl.db.vectors import embed_node
from jobctl.llm.adapter import as_embedding_client
from jobctl.llm.base import LLMProvider


class GraphView(Vertical):
    """Browse, edit, and curate the knowledge graph."""

    BINDINGS = [
        Binding("enter", "show_selected", "Details"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("a", "add_node", "Add"),
        Binding("slash", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear search", show=False),
    ]

    DEFAULT_CSS = """
    GraphView { height: 1fr; }
    #graph-summary { padding: 0 1; color: #a6adc8; }
    #graph-toolbar { height: 3; padding: 0 1; }
    #graph-search { width: 1fr; }
    #graph-filter { width: 20; }
    #graph-tree { width: 40%; }
    #graph-detail { padding: 1; }
    #graph-editor { height: 12; }
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        provider: LLMProvider | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.conn = conn
        self.provider = provider
        self.current_node_id: str | None = None
        self._type_filter: str = "all"
        self._search_term: str = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Knowledge graph"),
            Static(id="graph-summary"),
            Horizontal(
                Select(
                    [("All types", "all")],
                    id="graph-filter",
                    value="all",
                    allow_blank=False,
                ),
                Input(placeholder="Search by name", id="graph-search"),
                id="graph-toolbar",
            ),
            Horizontal(
                Tree("Graph", id="graph-tree"),
                Vertical(
                    Static(
                        "Select a node and press Enter.",
                        id="graph-detail",
                    ),
                    TextArea(id="graph-editor"),
                ),
            ),
        )

    def on_mount(self) -> None:
        self._refresh()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "graph-filter":
            self._type_filter = str(event.value)
            self._refresh()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "graph-search":
            self._search_term = event.value.strip().lower()
            self._refresh(keep_filter=True)

    def action_focus_search(self) -> None:
        self.query_one("#graph-search", Input).focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#graph-search", Input)
        search.value = ""
        self._search_term = ""
        self._refresh(keep_filter=True)

    def action_show_selected(self) -> None:
        tree = self.query_one("#graph-tree", Tree)
        if tree.cursor_node and tree.cursor_node.data:
            self.current_node_id = str(tree.cursor_node.data)
            self._show_node(self.current_node_id)

    def action_edit_selected(self) -> None:
        if self.current_node_id is None:
            return
        node = get_node(self.conn, self.current_node_id)
        editor = self.query_one("#graph-editor", TextArea)
        editor.text = yaml.safe_dump(
            {
                "type": node["type"],
                "name": node["name"],
                "properties": node["properties"],
                "text_representation": node["text_representation"],
            },
            sort_keys=False,
        )
        editor.focus()

    def on_blur(self, event) -> None:
        sender = getattr(event, "sender", None)
        if not isinstance(sender, TextArea) or sender.id != "graph-editor":
            return
        if self.current_node_id is None or not sender.text.strip():
            return
        try:
            data = yaml.safe_load(sender.text) or {}
            update_node(
                self.conn,
                self.current_node_id,
                type=data["type"],
                name=data["name"],
                properties=data.get("properties") or {},
                text_representation=data["text_representation"],
            )
        except Exception as exc:
            self.query_one("#graph-detail", Static).update(f"Update failed: {exc}")
            return
        self._embed_node_if_possible(self.current_node_id)
        self._refresh(keep_filter=True)
        self._show_node(self.current_node_id)

    def action_delete_selected(self) -> None:
        if self.current_node_id is None:
            return
        delete_node(self.conn, self.current_node_id)
        self.current_node_id = None
        self._refresh(keep_filter=True)
        self.query_one("#graph-detail", Static).update("Node deleted.")

    def action_add_node(self) -> None:
        node_id = add_node(self.conn, "note", "New Node", {}, "New Node")
        self._embed_node_if_possible(node_id)
        self.current_node_id = node_id
        self._refresh(keep_filter=True)
        self._show_node(node_id)

    def _refresh(self, *, keep_filter: bool = False) -> None:
        summary_rows = self.conn.execute(
            "SELECT type, COUNT(*) AS count, MAX(updated_at) AS updated_at "
            "FROM nodes GROUP BY type"
        ).fetchall()
        edge_count = self.conn.execute("SELECT COUNT(*) AS count FROM edges").fetchone()[
            "count"
        ]
        total_nodes = sum(row["count"] for row in summary_rows)
        last_updated = max(
            (row["updated_at"] for row in summary_rows if row["updated_at"]), default=""
        )
        summary = ", ".join(f"{row['count']} {row['type']}" for row in summary_rows) or "No nodes"
        self.query_one("#graph-summary", Static).update(
            f"{total_nodes} nodes, {edge_count} edges. {summary}. Last updated: {last_updated}"
        )

        if not keep_filter:
            select = self.query_one("#graph-filter", Select)
            options = [("All types", "all")] + [
                (row["type"].title(), row["type"]) for row in summary_rows
            ]
            select.set_options(options)
            select.value = self._type_filter

        tree = self.query_one("#graph-tree", Tree)
        tree.clear()
        query = "SELECT * FROM nodes"
        params: list = []
        clauses: list[str] = []
        if self._type_filter and self._type_filter != "all":
            clauses.append("type = ?")
            params.append(self._type_filter)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY type, name"
        rows = self.conn.execute(query, params).fetchall()

        groups: dict[str, list] = {}
        search = self._search_term
        for row in rows:
            if search and search not in (row["name"] or "").lower():
                continue
            groups.setdefault(row["type"], []).append(row)

        for node_type, type_rows in groups.items():
            branch = tree.root.add(node_type.title())
            for row in type_rows:
                child = branch.add_leaf(row["name"], data=row["id"])
                child.add_leaf(
                    json.dumps(json.loads(row["properties"] or "{}"), sort_keys=True)
                )
        tree.root.expand()

    def _show_node(self, node_id: str) -> None:
        node = get_node(self.conn, node_id)
        edges = [*get_edges_from(self.conn, node_id), *get_edges_to(self.conn, node_id)]
        connected = "\n".join(
            f"- {edge['relation']}: "
            f"{edge.get('target', edge.get('source', {})).get('name', '')}"
            for edge in edges
        )
        sources = self._node_sources(node_id)
        detail_lines = [
            f"Type: {node['type']}",
            f"Name: {node['name']}",
            f"Properties: {node['properties']}",
            f"Text: {node['text_representation']}",
        ]
        if sources:
            detail_lines.append("")
            detail_lines.append("Sources:")
            for src in sources:
                confidence = (
                    f" (confidence {src['confidence']:.2f})"
                    if src["confidence"] is not None
                    else ""
                )
                quote = f"\n  > {src['source_quote']}" if src["source_quote"] else ""
                detail_lines.append(
                    f"- {src['source_type']}: {src['source_ref'] or ''}{confidence}{quote}"
                )
        detail_lines.append("")
        detail_lines.append("Connected:")
        detail_lines.append(connected or "(none)")
        self.query_one("#graph-detail", Static).update("\n".join(detail_lines))

    def _node_sources(self, node_id: str) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(
                "SELECT * FROM node_sources WHERE node_id = ? ORDER BY created_at DESC",
                (node_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _embed_node_if_possible(self, node_id: str) -> None:
        if self.provider is None:
            return
        try:
            embed_node(self.conn, node_id, as_embedding_client(self.provider))
        except Exception:
            # Embedding is best-effort; continue editing on failure.
            pass
