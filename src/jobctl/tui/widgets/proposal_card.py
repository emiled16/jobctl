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
    CurationProposalCard #edit-error {
        color: #f38ba8;
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
        if self.proposal.kind == "add_fact":
            fact = payload.get("fact") or payload
            return (
                f"Add fact: {fact.get('entity_type')} / {fact.get('entity_name')}\n"
                f"Source: {payload.get('source_ref', '')}\n"
                f"Text: {fact.get('text_representation', '')}\n"
                f"Reason: {payload.get('reason', '')}"
            )
        if self.proposal.kind == "update_fact":
            return (
                f"Update node: {payload.get('node_id')}\n"
                f"Source: {payload.get('source_ref', '')}\n"
                f"Reason: {payload.get('reason', '')}\n"
                f"Current: {payload.get('current_text', '')}\n"
                f"Proposed: {payload.get('proposed_text', '')}\n"
                f"Risk: {'requires confirmation' if payload.get('requires_confirmation') else 'low'}"
            )
        if self.proposal.kind == "refine_experience":
            return (
                f"Refine node: {payload.get('target_node_id')}\n"
                f"Source: {payload.get('source_ref', '')}\n"
                f"Reason: {payload.get('reason', '')}\n"
                f"Proposed: {payload.get('resume_ready_phrasing', '')}\n"
                f"Risk: {'requires review' if payload.get('requires_review') else 'low'}"
            )
        return json.dumps(payload, indent=2)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            self.action_accept()
        elif event.button.id == "reject":
            self.action_reject()
        elif event.button.id == "edit":
            self.action_edit()
        elif event.button.id == "save":
            self.action_save()
        elif event.button.id == "cancel":
            self.action_cancel()

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
                Static("", id="edit-error"),
                Horizontal(
                    Button("Save", id="save"),
                    Button("Cancel", id="cancel"),
                ),
                id="edit-box",
            )
        )

    def action_save(self) -> None:
        if not self._editing:
            return
        editor = self.query_one("#editor", TextArea)
        try:
            payload = json.loads(editor.text)
        except json.JSONDecodeError as exc:
            self.query_one("#edit-error", Static).update(f"Invalid JSON: {exc.msg}")
            return
        if not isinstance(payload, dict):
            self.query_one("#edit-error", Static).update("Payload must be a JSON object.")
            return
        self.proposal.payload = payload
        self.post_message(self.Edited(self.proposal.id, payload))
        self._restore_body()

    def action_cancel(self) -> None:
        if self._editing:
            self._restore_body()

    def _restore_body(self) -> None:
        self._editing = False
        self.query_one("#body", Static).update(self._body_markup())
        self.query_one("#body", Static).display = True
        try:
            self.query_one("#edit-box").remove()
        except Exception:
            pass

    def on_mount(self) -> None:
        self.can_focus = True


__all__ = ["CurationProposalCard"]
