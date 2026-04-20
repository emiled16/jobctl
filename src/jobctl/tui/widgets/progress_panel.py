"""Right-sidebar widget that tracks background job progress."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static

from jobctl.core.events import (
    ApplyProgressEvent,
    AsyncEventBus,
    IngestDoneEvent,
    IngestErrorEvent,
    IngestProgressEvent,
    JobctlEvent,
)


@dataclass
class JobEntry:
    key: str
    label: str
    current: int = 0
    total: int = 0
    message: str = ""
    state: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None


class _JobCard(Vertical):
    DEFAULT_CSS = """
    _JobCard {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        border: solid #45475a;
    }
    _JobCard Label.-title {
        color: #cdd6f4;
    }
    _JobCard Label.-msg {
        color: #a6adc8;
    }
    _JobCard Label.-status-done {
        color: #a6e3a1;
    }
    _JobCard Label.-status-error {
        color: #f38ba8;
    }
    """

    def __init__(self, entry: JobEntry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self):
        yield Label(self.entry.label, classes="-title")
        yield ProgressBar(
            total=max(self.entry.total or 1, 1),
            show_eta=False,
            show_percentage=True,
            id="bar",
        )
        yield Label(self.entry.message or "starting...", classes="-msg", id="msg")
        yield Label(self._status_text(), id="status")

    def refresh_entry(self) -> None:
        bar = self.query_one("#bar", ProgressBar)
        bar.total = max(self.entry.total or 1, 1)
        bar.progress = self.entry.current
        self.query_one("#msg", Label).update(self.entry.message or "")
        status = self.query_one("#status", Label)
        status.update(self._status_text())
        status.remove_class("-status-done")
        status.remove_class("-status-error")
        if self.entry.state == "done":
            status.add_class("-status-done")
        elif self.entry.state == "error":
            status.add_class("-status-error")

    def _status_text(self) -> str:
        now = self.entry.completed_at or time.monotonic()
        elapsed = int(now - self.entry.started_at)
        if self.entry.state == "done":
            return f"done ({elapsed}s)"
        if self.entry.state == "error":
            return f"error ({elapsed}s)"
        return f"running ({elapsed}s)"


class ProgressPanel(Widget):
    """Tracks active and recent background jobs in the right sidebar."""

    DEFAULT_CSS = """
    ProgressPanel {
        height: auto;
    }
    ProgressPanel Static.-empty {
        color: #6c7086;
        padding: 1;
    }
    """

    def __init__(self, bus: AsyncEventBus) -> None:
        super().__init__()
        self._bus = bus
        self._entries: dict[str, JobEntry] = {}
        self._queue = None
        self._pump_task = None
        self._has_active = False

    def compose(self):
        yield Static("No active jobs.", id="empty", classes="-empty")

    def on_mount(self) -> None:
        self._queue = self._bus.subscribe()
        self._pump_task = self.run_worker(self._pump(), exclusive=False)

    def on_unmount(self) -> None:
        if self._queue is not None:
            self._bus.unsubscribe(self._queue)

    async def _pump(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                self._apply_event(event)
            except Exception:  # pragma: no cover - defensive
                import logging

                logging.getLogger(__name__).exception(
                    "ProgressPanel failed to render event"
                )

    def _key_for(self, event: JobctlEvent) -> str | None:
        if isinstance(event, (IngestProgressEvent, IngestDoneEvent, IngestErrorEvent)):
            return event.job_id or f"ingest:{event.source}"
        if isinstance(event, ApplyProgressEvent):
            return event.job_id or f"apply:{event.step}"
        return None

    def _label_for(self, event: JobctlEvent) -> str:
        if isinstance(event, (IngestProgressEvent, IngestDoneEvent, IngestErrorEvent)):
            return f"Ingest: {event.source}"
        if isinstance(event, ApplyProgressEvent):
            return f"Apply: {event.step}"
        return "job"

    def _apply_event(self, event: JobctlEvent) -> None:
        key = self._key_for(event)
        if key is None:
            return

        entry = self._entries.get(key)
        if entry is None:
            entry = JobEntry(key=key, label=self._label_for(event))
            self._entries[key] = entry
            self._mount_card(entry)

        if isinstance(event, IngestProgressEvent):
            entry.current = event.current
            entry.total = max(event.total, 1)
            entry.message = event.message or entry.message
            entry.state = "running"
        elif isinstance(event, IngestDoneEvent):
            entry.current = entry.total or entry.current
            entry.total = entry.total or max(event.facts_added, 1)
            entry.message = f"done ({event.facts_added} facts)"
            entry.state = "done"
            entry.completed_at = time.monotonic()
        elif isinstance(event, IngestErrorEvent):
            entry.message = event.error
            entry.state = "error"
            entry.completed_at = time.monotonic()
        elif isinstance(event, ApplyProgressEvent):
            entry.message = event.message or event.step
            entry.state = "running"

        self._refresh_card(entry)
        self._recompute_active()

    def _mount_card(self, entry: JobEntry) -> None:
        try:
            empty = self.query_one("#empty", Static)
            empty.display = False
        except Exception:
            pass
        card = _JobCard(entry)
        card.id = f"job-{entry.key}".replace(":", "-")
        self.mount(card)

    def _refresh_card(self, entry: JobEntry) -> None:
        try:
            card = self.query_one(
                f"#job-{entry.key.replace(':', '-')}", _JobCard
            )
        except Exception:
            return
        card.refresh_entry()

    def _recompute_active(self) -> None:
        has_active = any(e.state == "running" for e in self._entries.values())
        if has_active == self._has_active:
            return
        self._has_active = has_active
        try:
            app = self.app
        except Exception:  # pragma: no cover - not mounted yet
            return
        try:
            sidebar = app.query_one("#sidebar")
        except Exception:
            return
        if has_active and "-visible" not in sidebar.classes:
            sidebar.add_class("-visible")
        if not has_active and not any(
            e.state == "running" for e in self._entries.values()
        ):
            # Keep sidebar open briefly but allow user to collapse.
            pass


__all__ = ["ProgressPanel", "JobEntry"]
