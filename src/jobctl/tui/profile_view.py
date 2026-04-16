"""Profile TUI view."""

import json
import sqlite3

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, Static, TextArea, Tree

from jobctl.db.graph import (
    add_node,
    delete_node,
    get_edges_from,
    get_edges_to,
    get_node,
    update_node,
)
from jobctl.db.vectors import embed_node


class ProfileScreen(Screen):
    """Knowledge graph profile view."""

    BINDINGS = [
        Binding("enter", "show_selected", "Details"),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("a", "add_node", "Add"),
    ]

    def __init__(self, conn: sqlite3.Connection, llm_client=None) -> None:
        super().__init__()
        self.conn = conn
        self.llm_client = llm_client
        self.current_node_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Profile"),
            Static(id="summary"),
            Horizontal(
                Tree("Graph", id="graph-tree"),
                Vertical(
                    Static("Select a node and press Enter.", id="node-detail"),
                    TextArea(id="editor"),
                ),
            ),
        )

    def on_mount(self) -> None:
        self._refresh()

    def action_show_selected(self) -> None:
        tree = self.query_one("#graph-tree", Tree)
        if tree.cursor_node and tree.cursor_node.data:
            self.current_node_id = str(tree.cursor_node.data)
            self._show_node(self.current_node_id)

    def action_edit_selected(self) -> None:
        if self.current_node_id is None:
            return
        node = get_node(self.conn, self.current_node_id)
        editor = self.query_one("#editor", TextArea)
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
        if not isinstance(event.sender, TextArea):
            return
        if (
            event.sender.id != "editor"
            or self.current_node_id is None
            or not event.sender.text.strip()
        ):
            return
        data = yaml.safe_load(event.sender.text) or {}
        update_node(
            self.conn,
            self.current_node_id,
            type=data["type"],
            name=data["name"],
            properties=data.get("properties") or {},
            text_representation=data["text_representation"],
        )
        self._embed_node_if_possible(self.current_node_id)
        self._refresh()
        self._show_node(self.current_node_id)

    def action_delete_selected(self) -> None:
        if self.current_node_id is None:
            return
        delete_node(self.conn, self.current_node_id)
        self.current_node_id = None
        self._refresh()
        self.query_one("#node-detail", Static).update("Node deleted.")

    def action_add_node(self) -> None:
        node_id = add_node(self.conn, "note", "New Node", {}, "New Node")
        self._embed_node_if_possible(node_id)
        self.current_node_id = node_id
        self._refresh()
        self._show_node(node_id)

    def _refresh(self) -> None:
        summary_rows = self.conn.execute(
            "SELECT type, COUNT(*) AS count, MAX(updated_at) AS updated_at FROM nodes GROUP BY type"
        ).fetchall()
        edge_count = self.conn.execute("SELECT COUNT(*) AS count FROM edges").fetchone()["count"]
        total_nodes = sum(row["count"] for row in summary_rows)
        last_updated = max(
            (row["updated_at"] for row in summary_rows if row["updated_at"]), default=""
        )
        summary = ", ".join(f"{row['count']} {row['type']}" for row in summary_rows) or "No nodes"
        self.query_one("#summary", Static).update(
            f"{total_nodes} nodes, {edge_count} edges. {summary}. Last updated: {last_updated}"
        )

        tree = self.query_one("#graph-tree", Tree)
        tree.clear()
        root_nodes = self.conn.execute("SELECT * FROM nodes ORDER BY type, name").fetchall()
        groups = {}
        for row in root_nodes:
            groups.setdefault(row["type"], []).append(row)
        for node_type, rows in groups.items():
            branch = tree.root.add(node_type.title())
            for row in rows:
                child = branch.add_leaf(row["name"], data=row["id"])
                child.add_leaf(json.dumps(json.loads(row["properties"] or "{}"), sort_keys=True))
        tree.root.expand()

    def _show_node(self, node_id: str) -> None:
        node = get_node(self.conn, node_id)
        edges = [*get_edges_from(self.conn, node_id), *get_edges_to(self.conn, node_id)]
        connected = "\n".join(
            f"- {edge['relation']}: {edge.get('target', edge.get('source', {})).get('name', '')}"
            for edge in edges
        )
        detail = (
            f"Type: {node['type']}\n"
            f"Name: {node['name']}\n"
            f"Properties: {node['properties']}\n"
            f"Text: {node['text_representation']}\n\n"
            f"Connected:\n{connected}"
        )
        self.query_one("#node-detail", Static).update(detail)

    def _embed_node_if_possible(self, node_id: str) -> None:
        if self.llm_client is not None:
            embed_node(self.conn, node_id, self.llm_client)
