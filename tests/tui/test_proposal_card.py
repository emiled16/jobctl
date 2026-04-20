"""Widget tests for curation proposal editing."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea

from jobctl.curation.proposals import Proposal
from jobctl.tui.widgets.proposal_card import CurationProposalCard


class CardApp(App):
    def __init__(self, card: CurationProposalCard) -> None:
        super().__init__()
        self.card = card
        self.edited_payload = None

    def compose(self) -> ComposeResult:
        yield self.card

    def on_curation_proposal_card_edited(self, event: CurationProposalCard.Edited) -> None:
        self.edited_payload = event.payload


@pytest.mark.anyio
async def test_proposal_card_save_and_cancel_edit() -> None:
    card = CurationProposalCard(
        Proposal(id="proposal-1", kind="connect", payload={"source_id": "a"})
    )
    app = CardApp(card)

    async with app.run_test() as pilot:
        await pilot.pause()
        card.action_edit()
        await pilot.pause()

        card.query_one("#editor", TextArea).text = '{"source_id": "a", "target_id": "b"}'
        card.action_save()
        await pilot.pause()

        assert app.edited_payload == {"source_id": "a", "target_id": "b"}
        assert card.proposal.payload == {"source_id": "a", "target_id": "b"}
        assert card.query_one("#body", Static).display is True

        card.action_edit()
        await pilot.pause()
        card.query_one("#editor", TextArea).text = '{"source_id": "changed"}'
        card.action_cancel()
        await pilot.pause()

        assert card.proposal.payload == {"source_id": "a", "target_id": "b"}


@pytest.mark.anyio
async def test_proposal_card_invalid_json_stays_editing() -> None:
    card = CurationProposalCard(
        Proposal(id="proposal-1", kind="connect", payload={"source_id": "a"})
    )
    app = CardApp(card)

    async with app.run_test() as pilot:
        await pilot.pause()
        card.action_edit()
        await pilot.pause()

        card.query_one("#editor", TextArea).text = "{"
        card.action_save()
        await pilot.pause()

        assert app.edited_payload is None
        assert "Invalid JSON" in str(card.query_one("#edit-error", Static).renderable)
