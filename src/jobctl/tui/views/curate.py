"""Curate screen: browse and decide on pending curation proposals."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Label, Static

from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.curation.proposals import CurationProposalStore, Proposal
from jobctl.tui.widgets.proposal_card import CurationProposalCard


_KIND_LABELS = {
    "merge": "Merges",
    "rephrase": "Rephrases",
    "connect": "Connections",
    "prune": "Prunes",
}


class CurateView(Screen):
    BINDINGS = [
        Binding("r", "reload", "Reload", show=True),
        Binding("c", "run_curation", "Run curation", show=True),
        Binding("ctrl+a", "accept_group", "Accept group", show=False),
    ]

    DEFAULT_CSS = """
    #curate-toolbar {
        height: 3;
        padding: 0 1;
        background: #313244;
    }
    #curate-content {
        height: 1fr;
        padding: 0 1;
    }
    .curate-empty {
        color: #6c7086;
        padding: 2;
    }
    """

    def __init__(
        self, conn: sqlite3.Connection, runner: BackgroundJobRunner
    ) -> None:
        super().__init__()
        self.conn = conn
        self.runner = runner
        self.store = CurationProposalStore(conn)
        self._focused_group: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="curate-toolbar"):
            yield Button("Reload", id="btn-reload")
            yield Button("Run curation", id="btn-run", variant="primary")
            yield Label("", id="status")
        yield VerticalScroll(id="curate-content")
        yield Footer()

    def on_mount(self) -> None:
        self._reload()

    def action_reload(self) -> None:
        self._reload()

    def action_run_curation(self) -> None:
        status = self.query_one("#status", Label)
        status.update("Curation run requested; triggering agent…")
        try:
            from jobctl.app.common import _get_app  # type: ignore

            _ = _get_app
        except Exception:
            pass
        app = self.app
        try:
            runner = app.agent_runner  # type: ignore[attr-defined]
        except Exception:
            status.update("Curation runner unavailable.")
            return
        try:
            runner.submit_background("/curate")
        except Exception as exc:  # noqa: BLE001
            status.update(f"Curation failed to start: {exc}")

    def _reload(self) -> None:
        content = self.query_one("#curate-content", VerticalScroll)
        content.remove_children()
        proposals = self.store.list_pending()
        if not proposals:
            content.mount(
                Static(
                    "No pending proposals. Press 'c' to run curation.",
                    classes="curate-empty",
                )
            )
            return

        grouped: dict[str, list[Proposal]] = defaultdict(list)
        for proposal in proposals:
            grouped[proposal.kind].append(proposal)

        for kind, items in grouped.items():
            title = f"{_KIND_LABELS.get(kind, kind.title())} ({len(items)})"
            collapsible = Collapsible(title=title, id=f"group-{kind}")
            content.mount(collapsible)
            inner = Vertical()
            collapsible.mount(inner)
            for proposal in items:
                inner.mount(CurationProposalCard(proposal))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-reload":
            self._reload()
        elif event.button.id == "btn-run":
            self.action_run_curation()

    def on_curation_proposal_card_accepted(
        self, event: CurationProposalCard.Accepted
    ) -> None:
        self.store.accept(event.proposal_id)
        self.query_one("#status", Label).update("Accepted proposal")

    def on_curation_proposal_card_rejected(
        self, event: CurationProposalCard.Rejected
    ) -> None:
        self.store.reject(event.proposal_id)
        self.query_one("#status", Label).update("Rejected proposal")

    def on_curation_proposal_card_edited(
        self, event: CurationProposalCard.Edited
    ) -> None:
        self.store.mark_edited(event.proposal_id, event.payload)
        self.query_one("#status", Label).update("Saved edited proposal")


__all__ = ["CurateView"]
