"""An interactive Textual widget rendering a single curation proposal."""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Label, Static, TextArea

from jobctl.curation.proposals import Proposal
from jobctl.curation.rephrase import compute_diff_lines


class CurationProposalCard(Vertical):
    """Render a :class:`Proposal` with accept/reject/edit controls."""

    DEFAULT_CSS = """
    CurationProposalCard {
        height: auto;
        padding: 1;
        margin: 1 0;
        border: solid #45475a;
    }
    CurationProposalCard .-title {
        color: #89b4fa;
    }
    CurationProposalCard Button.-accept {
        background: #a6e3a1;
        color: #1e1e2e;
    }
    CurationProposalCard Button.-reject {
        background: #f38ba8;
        color: #1e1e2e;
    }
    CurationProposalCard Button.-edit {
        background: #f9e2af;
        color: #1e1e2e;
    }
    CurationProposalCard TextArea {
        height: 10;
    }
    """

    class Accepted(Message):
        def __init__(self, proposal_id: str) -> None:
            super().__init__()
            self.proposal_id = proposal_id

    class Rejected(Message):
        def __init__(self, proposal_id: str) -> None:
            super().__init__()
            self.proposal_id = proposal_id

    class Edited(Message):
        def __init__(self, proposal_id: str, payload: dict[str, Any]) -> None:
            super().__init__()
            self.proposal_id = proposal_id
            self.payload = payload

    BINDINGS = [
        ("a", "accept", "Accept"),
        ("r", "reject", "Reject"),
        ("e", "edit", "Edit"),
    ]

    def __init__(self, proposal: Proposal) -> None:
        super().__init__()
        self.proposal = proposal
        self._editing = False

    def compose(self) -> ComposeResult:
        yield Label(self._title(), classes="-title")
        yield Static(self._body_markup(), id="body")
        with Horizontal(id="actions"):
            yield Button("Accept", id="accept", classes="-accept")
            yield Button("Reject", id="reject", classes="-reject")
            yield Button("Edit", id="edit", classes="-edit")

    def _title(self) -> str:
        return f"[{self.proposal.kind.upper()}] proposal {self.proposal.id[:8]}"

    def _body_markup(self) -> str:
        payload = self.proposal.payload
        if self.proposal.kind == "merge":
            return (
                f"Merge nodes:\n"
                f"  A: {payload.get('node_a_id')}  ({payload.get('merged_name')})\n"
                f"  B: {payload.get('node_b_id')}\n"
                f"Reason: {payload.get('reason', '')}"
            )
        if self.proposal.kind == "rephrase":
            original = payload.get("original_text", "")
            proposed = payload.get("proposed_text", "")
            before, after = compute_diff_lines(original, proposed)
            return f"Before: {before}\nAfter:  {after}"
        if self.proposal.kind == "connect":
            return (
                f"Connect: {payload.get('source_id')} "
                f"-[{payload.get('relation', 'related_to')}]-> "
                f"{payload.get('target_id')}"
            )
        if self.proposal.kind == "prune":
            return f"Prune node {payload.get('node_id')}\nReason: {payload.get('reason', '')}"
        return json.dumps(payload, indent=2)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            self.action_accept()
        elif event.button.id == "reject":
            self.action_reject()
        elif event.button.id == "edit":
            self.action_edit()

    def action_accept(self) -> None:
        self.post_message(self.Accepted(self.proposal.id))
        self.remove()

    def action_reject(self) -> None:
        self.post_message(self.Rejected(self.proposal.id))
        self.remove()

    def action_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        body = self.query_one("#body", Static)
        editor = TextArea(json.dumps(self.proposal.payload, indent=2), id="editor")
        editor.styles.height = 10
        body.display = False
        self.mount(
            Vertical(
                editor,
                Horizontal(
                    Button("Save", id="save"),
                    Button("Cancel", id="cancel"),
                ),
                id="edit-box",
            )
        )

    def on_mount(self) -> None:
        self.can_focus = True


__all__ = ["CurationProposalCard"]
