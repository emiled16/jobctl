"""Right-sidebar widget that tracks background job progress."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Label, ProgressBar, Static

from jobctl.core.events import (
    ApplyProgressEvent,
    AsyncEventBus,
    IngestDoneEvent,
    IngestErrorEvent,
    IngestProgressEvent,
    JobLifecycleEvent,
    JobctlEvent,
)


@dataclass
class JobEntry:
    key: str
    kind: str
    label: str
    phase: str = "running"
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
        yield Label(Text(self.entry.label), classes="-title", id="title")
        yield Label(Text(self._phase_text()), id="phase")
        yield ProgressBar(
            total=max(self.entry.total or 1, 1),
            show_eta=False,
            show_percentage=True,
            id="bar",
        )
        yield Label(Text(self.entry.message or "starting..."), classes="-msg", id="msg")
        yield Label(Text(self._status_text()), id="status")

    def refresh_entry(self) -> None:
        bar = self.query_one("#bar", ProgressBar)
        bar.total = max(self.entry.total or 1, 1)
        bar.progress = self.entry.current
        self.query_one("#title", Label).update(Text(self.entry.label))
        self.query_one("#msg", Label).update(Text(self.entry.message or ""))
        self.query_one("#phase", Label).update(Text(self._phase_text()))
        status = self.query_one("#status", Label)
        status.update(Text(self._status_text()))
        status.remove_class("-status-done")
        status.remove_class("-status-error")
        if self.entry.state == "done":
            status.add_class("-status-done")
        elif self.entry.state == "error":
            status.add_class("-status-error")

    def _status_text(self) -> str:
        now = self.entry.completed_at or time.monotonic()
        elapsed = int(now - self.entry.started_at)
        progress = ""
        if self.entry.total:
            progress = f" {self.entry.current}/{self.entry.total}"
        if self.entry.state == "done":
            return f"done{progress} ({elapsed}s)"
        if self.entry.state == "error":
            return f"error{progress} ({elapsed}s)"
        if self.entry.state == "waiting_for_user":
            return f"waiting for input{progress} ({elapsed}s)"
        return f"running{progress} ({elapsed}s)"

    def _phase_text(self) -> str:
        return f"{self.entry.kind} / {self.entry.phase.replace('_', ' ')}"


class ProgressPanel(Vertical):
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
        self._max_message_chars = 240

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

                logging.getLogger(__name__).exception("ProgressPanel failed to render event")

    def _key_for(self, event: JobctlEvent) -> str | None:
        if isinstance(event, JobLifecycleEvent):
            return event.job_id
        if isinstance(event, (IngestProgressEvent, IngestDoneEvent, IngestErrorEvent)):
            return event.job_id or f"ingest:{event.source}"
        if isinstance(event, ApplyProgressEvent):
            return event.job_id or f"apply:{event.step}"
        return None

    def _label_for(self, event: JobctlEvent) -> str:
        if isinstance(event, JobLifecycleEvent):
            return event.label
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
            entry = JobEntry(key=key, kind=self._kind_for(event), label=self._label_for(event))
            self._entries[key] = entry
            self._mount_card(entry)

        if isinstance(event, JobLifecycleEvent):
            entry.kind = event.kind
            entry.label = event.label
            entry.phase = event.phase
            entry.message = self._compact_message(event.message) or entry.message
            if event.phase in {"queued", "running"}:
                entry.state = "running"
            elif event.phase == "waiting_for_user":
                entry.state = "waiting_for_user"
            elif event.phase == "done":
                entry.state = "done"
                entry.completed_at = time.monotonic()
            elif event.phase in {"error", "cancelled"}:
                entry.state = "error"
                entry.completed_at = time.monotonic()
        elif isinstance(event, IngestProgressEvent):
            entry.current = event.current
            entry.total = max(event.total, 1)
            entry.message = self._compact_message(event.message) or entry.message
            entry.phase = "running"
            entry.state = "running"
        elif isinstance(event, IngestDoneEvent):
            entry.current = entry.total or entry.current
            entry.total = entry.total or max(event.facts_added, 1)
            entry.message = f"done ({event.facts_added} facts)"
            entry.phase = "done"
            entry.state = "done"
            entry.completed_at = time.monotonic()
        elif isinstance(event, IngestErrorEvent):
            entry.message = self._compact_message(event.error)
            entry.phase = "error"
            entry.state = "error"
            entry.completed_at = time.monotonic()
        elif isinstance(event, ApplyProgressEvent):
            entry.message = self._compact_message(event.message) or event.step
            if event.step == "done":
                entry.phase = "done"
                entry.state = "done"
                entry.completed_at = time.monotonic()
            elif event.step == "error":
                entry.phase = "error"
                entry.state = "error"
                entry.completed_at = time.monotonic()
            else:
                entry.phase = "running"
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
            card = self.query_one(f"#job-{entry.key.replace(':', '-')}", _JobCard)
        except Exception:
            return
        try:
            card.refresh_entry()
        except Exception:
            self.call_after_refresh(card.refresh_entry)

    def _recompute_active(self) -> None:
        has_active = any(e.state in {"running", "waiting_for_user"} for e in self._entries.values())
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
        if not has_active and not any(e.state == "running" for e in self._entries.values()):
            # Keep sidebar open briefly but allow user to collapse.
            pass

    def _kind_for(self, event: JobctlEvent) -> str:
        if isinstance(event, JobLifecycleEvent):
            return event.kind
        if isinstance(event, (IngestProgressEvent, IngestDoneEvent, IngestErrorEvent)):
            return "ingest"
        if isinstance(event, ApplyProgressEvent):
            return "apply"
        return "job"

    def _compact_message(self, message: str | None) -> str:
        single_line = " ".join((message or "").split())
        if len(single_line) <= self._max_message_chars:
            return single_line
        return f"{single_line[: self._max_message_chars - 1]}…"


__all__ = ["ProgressPanel", "JobEntry"]
