"""Interactive agent shell for jobctl."""

from __future__ import annotations

import shlex
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.tree import Tree

from jobctl.conversation.onboard import analyze_coverage, run_onboarding
from jobctl.ingestion.github import ingest_github
from jobctl.ingestion.resume import extract_facts_from_resume, persist_facts, read_resume
from jobctl.llm.schemas import ExtractedProfile


CommandHandler = Callable[[list[str]], bool]


@dataclass(frozen=True)
class AgentCommand:
    name: str
    summary: str
    usage: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()


class AgentShell:
    """Codex-style command shell for exploring and updating a jobctl project."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        llm_client,
        config,
        project_root: Path,
        console: Console | None = None,
    ) -> None:
        self.conn = conn
        self.llm_client = llm_client
        self.config = config
        self.project_root = project_root
        self.console = console or Console()
        self.mode = "explore"
        self._commands = self._build_commands()

    def run(self) -> None:
        self.console.print(
            Panel(
                "Talk naturally, or run slash commands. Start with /help.",
                title="jobctl agent",
            )
        )
        while True:
            try:
                line = Prompt.ask(f"[bold]jobctl:{self.mode}[/bold]", default="")
            except (EOFError, KeyboardInterrupt):
                self.console.print("\nLeaving jobctl agent.")
                return

            if not self.execute(line):
                return

    def execute(self, line: str) -> bool:
        stripped_line = line.strip()
        if not stripped_line:
            return True
        if stripped_line.startswith("/"):
            return self._execute_command(stripped_line)
        return self._handle_plain_text(stripped_line)

    def _execute_command(self, line: str) -> bool:
        try:
            parts = shlex.split(line[1:])
        except ValueError as exc:
            self.console.print(f"Could not parse command: {exc}")
            return True

        if not parts:
            return True

        command_name, args = parts[0].lower(), parts[1:]
        command = self._commands.get(command_name)
        if command is None:
            self.console.print(f"Unknown command: /{command_name}. Run /help.")
            return True
        return command.handler(args)

    def _handle_plain_text(self, text: str) -> bool:
        lowered = text.lower()
        if self.mode == "onboard":
            return self._handle_onboard_text(text)
        if self.mode == "apply":
            self.console.print("Apply mode is not interactive yet. Use `jobctl apply <url>`.")
            return True
        if lowered in {"help", "commands"}:
            return self._help([])
        if "graph" in lowered or "visualize" in lowered:
            return self._graph([])
        if "coverage" in lowered or "report" in lowered:
            return self._report(["coverage"])
        if lowered in {"exit", "quit"}:
            return False
        return self._ask([text])

    def _build_commands(self) -> dict[str, AgentCommand]:
        commands = [
            AgentCommand("help", "Show available commands.", "/help", self._help, ("?",)),
            AgentCommand("exit", "Leave the agent shell.", "/exit", self._exit, ("quit", "q")),
            AgentCommand(
                "mode",
                "Switch how plain text is interpreted.",
                "/mode [explore|onboard|apply]",
                self._mode,
            ),
            AgentCommand(
                "onboard",
                "Run the guided onboarding flow.",
                "/onboard",
                self._onboard,
            ),
            AgentCommand(
                "ingest",
                "Ingest a resume or GitHub profile/repository.",
                "/ingest resume <path> | /ingest github <username-or-url>[, ...]",
                self._ingest,
            ),
            AgentCommand(
                "graph",
                "Render the knowledge graph as a terminal tree.",
                "/graph [node-type]",
                self._graph,
            ),
            AgentCommand(
                "report",
                "Render a project report.",
                "/report coverage | /report summary",
                self._report,
            ),
            AgentCommand(
                "ask",
                "Ask the agent a question grounded in the graph.",
                "/ask <question>",
                self._ask,
            ),
        ]
        command_map = {command.name: command for command in commands}
        for command in commands:
            for alias in command.aliases:
                command_map[alias] = command
        return command_map

    def _help(self, _args: list[str]) -> bool:
        table = Table(title="jobctl agent commands")
        table.add_column("Command")
        table.add_column("What it does")
        table.add_column("Usage")
        for command in self._unique_commands():
            table.add_row(f"/{command.name}", command.summary, command.usage)
        self.console.print(table)
        return True

    def _exit(self, _args: list[str]) -> bool:
        self.console.print("Leaving jobctl agent.")
        return False

    def _mode(self, args: list[str]) -> bool:
        if not args:
            self.console.print(f"Current mode: {self.mode}")
            self.console.print("Available modes: explore, onboard, apply")
            return True

        requested_mode = args[0].lower()
        if requested_mode not in {"explore", "onboard", "apply"}:
            self.console.print("Unknown mode. Available modes: explore, onboard, apply")
            return True

        self.mode = requested_mode
        self.console.print(f"Mode switched to {self.mode}.")
        if self.mode == "onboard":
            self.console.print("Write profile details as plain text, or type done to return.")
        return True

    def _onboard(self, _args: list[str]) -> bool:
        run_onboarding(self.conn, self.llm_client, self.config)
        return True

    def _handle_onboard_text(self, text: str) -> bool:
        if text.strip().lower() == "done":
            self.mode = "explore"
            self.console.print("Mode switched to explore.")
            return True

        profile = self.llm_client.chat_structured(
            [
                {
                    "role": "system",
                    "content": "Extract career profile facts from the user's answer.",
                },
                {"role": "user", "content": text},
            ],
            response_format=ExtractedProfile,
        )
        persisted_count = persist_facts(
            self.conn,
            profile.facts,
            self.llm_client,
            interactive=False,
        )
        self.console.print(f"Saved profile facts: {persisted_count}")
        return True

    def _ingest(self, args: list[str]) -> bool:
        if len(args) < 2:
            self.console.print("Usage: /ingest resume <path> | /ingest github <username-or-url>")
            return True

        source_type = args[0].lower()
        source_value = " ".join(args[1:]).strip()
        if source_type == "resume":
            self._ingest_resume(Path(source_value).expanduser())
        elif source_type == "github":
            values = [value.strip() for value in source_value.split(",") if value.strip()]
            persisted_count = ingest_github(
                self.conn,
                values,
                self.llm_client,
                interactive=True,
            )
            self.console.print(f"Ingested GitHub facts: {persisted_count}")
        else:
            self.console.print("Unknown ingest source. Use resume or github.")
        return True

    def _ingest_resume(self, resume_path: Path) -> None:
        resume_text = read_resume(resume_path)
        profile = extract_facts_from_resume(resume_text, self.llm_client)
        persisted_count = persist_facts(
            self.conn,
            profile.facts,
            self.llm_client,
            interactive=True,
        )
        self.console.print(f"Ingested resume facts: {persisted_count}")

    def _graph(self, args: list[str]) -> bool:
        node_type = args[0].lower() if args else None
        rows = self._graph_rows(node_type)
        if not rows:
            message = f"No {node_type} nodes found." if node_type else "No graph nodes found."
            self.console.print(message)
            return True

        tree = Tree("Knowledge Graph")
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            groups.setdefault(row["type"], []).append(row)

        for group_name, group_rows in groups.items():
            branch = tree.add(f"{group_name.title()} ({len(group_rows)})")
            for row in group_rows:
                child = branch.add(row["name"])
                for edge in self._edges_for_node(row["id"]):
                    child.add(f"{edge['relation']} -> {edge['target_name']} ({edge['target_type']})")
        self.console.print(tree)
        return True

    def _report(self, args: list[str]) -> bool:
        report_name = args[0].lower() if args else "coverage"
        if report_name == "coverage":
            self._coverage_report()
        elif report_name == "summary":
            self._summary_report()
        else:
            self.console.print("Unknown report. Available reports: coverage, summary")
        return True

    def _ask(self, args: list[str]) -> bool:
        question = " ".join(args).strip()
        if not question:
            self.console.print("Usage: /ask <question>")
            return True

        messages = [
            {
                "role": "system",
                "content": (
                    "You are jobctl, a career knowledge graph agent. Answer using only the "
                    "provided graph context. If the graph does not contain enough evidence, "
                    "say what is missing and suggest the next command to run."
                ),
            },
            {
                "role": "user",
                "content": f"Graph context:\n{self._graph_context()}\n\nQuestion:\n{question}",
            },
        ]
        self.console.print(self.llm_client.chat(messages, temperature=0.3))
        return True

    def _coverage_report(self) -> None:
        coverage = analyze_coverage(self.conn)
        table = Table(title="Coverage")
        table.add_column("Area")
        table.add_column("Status")
        table.add_row("Roles", str(coverage["roles_count"]))
        table.add_row("Skills", str(coverage["skills_count"]))
        table.add_row("Achievements", str(coverage["achievements_count"]))
        table.add_row("Education", "yes" if coverage["has_education"] else "missing")
        table.add_row("Stories", "yes" if coverage["has_stories"] else "missing")
        table.add_row(
            "Missing sections",
            ", ".join(coverage["missing_sections"]) or "none",
        )
        table.add_row(
            "Roles missing achievements",
            self._format_node_names(coverage["roles_without_achievements"]),
        )
        table.add_row(
            "Roles missing skills",
            self._format_node_names(coverage["roles_without_skills"]),
        )
        self.console.print(table)

    def _summary_report(self) -> None:
        summary_rows = self.conn.execute(
            """
            SELECT type, COUNT(*) AS count, MAX(updated_at) AS updated_at
            FROM nodes
            GROUP BY type
            ORDER BY type
            """
        ).fetchall()
        edge_count = self.conn.execute("SELECT COUNT(*) AS count FROM edges").fetchone()["count"]

        table = Table(title="Graph Summary")
        table.add_column("Type")
        table.add_column("Nodes")
        table.add_column("Last updated")
        for row in summary_rows:
            table.add_row(row["type"], str(row["count"]), row["updated_at"] or "")
        table.caption = f"{sum(row['count'] for row in summary_rows)} nodes, {edge_count} edges"
        self.console.print(table)

    def _graph_rows(self, node_type: str | None) -> list[sqlite3.Row]:
        if node_type:
            return self.conn.execute(
                "SELECT * FROM nodes WHERE type = ? ORDER BY type, name",
                (node_type,),
            ).fetchall()
        return self.conn.execute("SELECT * FROM nodes ORDER BY type, name").fetchall()

    def _edges_for_node(self, node_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT edges.relation, nodes.name AS target_name, nodes.type AS target_type
            FROM edges
            JOIN nodes ON nodes.id = edges.target_id
            WHERE edges.source_id = ?
            ORDER BY edges.relation, nodes.name
            """,
            (node_id,),
        ).fetchall()

    def _graph_context(self) -> str:
        nodes = self.conn.execute(
            "SELECT id, type, name, text_representation FROM nodes ORDER BY type, name"
        ).fetchall()
        edges = self.conn.execute(
            """
            SELECT source.name AS source_name, edges.relation, target.name AS target_name
            FROM edges
            JOIN nodes AS source ON source.id = edges.source_id
            JOIN nodes AS target ON target.id = edges.target_id
            ORDER BY source.name, edges.relation, target.name
            """
        ).fetchall()

        node_lines = [
            f"- {row['type']}: {row['name']} - {row['text_representation']}" for row in nodes
        ]
        edge_lines = [
            f"- {row['source_name']} {row['relation']} {row['target_name']}" for row in edges
        ]
        return "\n".join(["Nodes:", *node_lines, "Edges:", *edge_lines])

    def _unique_commands(self) -> list[AgentCommand]:
        seen_names: set[str] = set()
        commands: list[AgentCommand] = []
        for command in self._commands.values():
            if command.name in seen_names:
                continue
            seen_names.add(command.name)
            commands.append(command)
        return commands

    @staticmethod
    def _format_node_names(nodes: list[dict[str, Any]]) -> str:
        return ", ".join(node["name"] for node in nodes) or "none"


def run_agent_shell(
    conn: sqlite3.Connection,
    llm_client,
    config,
    project_root: Path,
) -> None:
    AgentShell(conn, llm_client, config, project_root).run()
