"""Compact active-job status indicator for the app chrome."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.text import Text
from textual.widgets import Static

from jobctl.core.events import AsyncEventBus, JobLifecycleEvent, JobctlEvent


@dataclass
class _ActiveJob:
    label: str
    phase: str
    message: str = ""
    updated_at: float = field(default_factory=time.monotonic)


class SpinnerStatus(Static):
    """Show a compact spinner and current foreground job label."""

    DEFAULT_CSS = """
    SpinnerStatus {
        height: 1;
        padding: 0 1;
        color: #a6adc8;
        background: #181825;
    }
    """

    _FRAMES = ("|", "/", "-", "\\")
    _MAX_DETAIL_CHARS = 160

    def __init__(self, bus: AsyncEventBus, *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self._bus = bus
        self._queue = None
        self._pump_task = None
        self._timer = None
        self._frame_index = 0
        self._jobs: dict[str, _ActiveJob] = {}

    def on_mount(self) -> None:
        self.display = False
        self._queue = self._bus.subscribe()
        self._pump_task = self.run_worker(self._pump(), exclusive=False)
        self._timer = self.set_interval(0.2, self._tick, pause=True)

    def on_unmount(self) -> None:
        if self._queue is not None:
            self._bus.unsubscribe(self._queue)
            self._queue = None

    async def _pump(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            self._apply_event(event)

    def _apply_event(self, event: JobctlEvent) -> None:
        if not isinstance(event, JobLifecycleEvent):
            return
        safe_message = self._compact_message(event.message)
        if event.phase in {"queued", "running", "waiting_for_user"}:
            self._jobs[event.job_id] = _ActiveJob(
                label=event.label,
                phase=event.phase,
                message=safe_message,
            )
        else:
            self._jobs.pop(event.job_id, None)
            if not self._jobs:
                terminal = f"Done: {event.label}" if event.phase == "done" else safe_message
                self.update(Text(terminal or "Job ended"))
        self._render_status()

    def _tick(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(self._FRAMES)
        self._render_status()

    def _render_status(self) -> None:
        if not self._jobs:
            if self._timer is not None:
                self._timer.pause()
            if not self.renderable:
                self.display = False
            return

        if self._timer is not None:
            self._timer.resume()
        self.display = True
        job = max(self._jobs.values(), key=lambda entry: entry.updated_at)
        frame = self._FRAMES[self._frame_index]
        if job.phase == "waiting_for_user":
            self.update(Text(f"Waiting for input: {job.label}"))
            return
        detail = f" - {job.message}" if job.message else ""
        self.update(Text(f"{frame} {job.label}{detail}"))

    def _compact_message(self, message: str) -> str:
        single_line = " ".join((message or "").split())
        if len(single_line) <= self._MAX_DETAIL_CHARS:
            return single_line
        return f"{single_line[: self._MAX_DETAIL_CHARS - 1]}…"


__all__ = ["SpinnerStatus"]
