"""Async event bus and typed event dataclasses used across jobctl.

The event bus decouples long-running pipelines (ingestion, apply,
curation) from the Textual TUI: pipelines publish typed events without
importing Textual, and widgets subscribe to rerender reactively.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobctlEvent:
    """Marker base class for all events published on the bus."""


@dataclass(frozen=True)
class AgentTokenEvent(JobctlEvent):
    token: str


@dataclass(frozen=True)
class AgentDoneEvent(JobctlEvent):
    role: str
    content: str


@dataclass(frozen=True)
class AgentToolCallEvent(JobctlEvent):
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentModeChangeRequestEvent(JobctlEvent):
    new_mode: str


@dataclass(frozen=True)
class ConfirmationRequestedEvent(JobctlEvent):
    question: str
    confirm_id: str
    kind: str = "yes_no"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmationAnsweredEvent(JobctlEvent):
    confirm_id: str
    answer: bool
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestProgressEvent(JobctlEvent):
    source: str
    current: int
    total: int
    message: str = ""
    job_id: str | None = None


@dataclass(frozen=True)
class IngestDoneEvent(JobctlEvent):
    source: str
    facts_added: int
    job_id: str | None = None
    facts_extracted: int = 0
    duplicates_skipped: int = 0
    updates_proposed: int = 0
    refinement_questions_saved: int = 0
    pending_question_ids: list[str] = field(default_factory=list)
    can_start_refinement: bool = False
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestErrorEvent(JobctlEvent):
    source: str
    error: str
    job_id: str | None = None


@dataclass(frozen=True)
class ApplyProgressEvent(JobctlEvent):
    step: str
    message: str = ""
    job_id: str | None = None


JobLifecyclePhase = Literal[
    "queued",
    "running",
    "waiting_for_user",
    "done",
    "error",
    "cancelled",
]


@dataclass(frozen=True)
class JobLifecycleEvent(JobctlEvent):
    job_id: str
    kind: str
    label: str
    phase: JobLifecyclePhase
    message: str = ""


class AsyncEventBus:
    """Fan-out async pub/sub using one ``asyncio.Queue`` per subscriber.

    Thread-safe ``publish`` is provided via ``asyncio.run_coroutine_threadsafe``
    when a loop is attached; otherwise ``publish`` can be called from the loop.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[JobctlEvent]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, maxsize: int = 0) -> asyncio.Queue[JobctlEvent]:
        queue: asyncio.Queue[JobctlEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[JobctlEvent]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def publish(self, event: JobctlEvent) -> None:
        """Publish an event to all subscribers.

        Safe to call from any thread as long as ``attach_loop`` was invoked
        with the event loop on which subscribers run.
        """
        if self._loop is not None and not self._loop.is_closed():
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is self._loop:
                self._deliver(event)
            else:
                self._loop.call_soon_threadsafe(self._deliver, event)
            return
        self._deliver(event)

    async def publish_async(self, event: JobctlEvent) -> None:
        self._deliver(event)

    def _deliver(self, event: JobctlEvent) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("event bus subscriber queue full, dropping %r", event)


__all__ = [
    "AgentDoneEvent",
    "AgentModeChangeRequestEvent",
    "AgentToolCallEvent",
    "AgentTokenEvent",
    "ApplyProgressEvent",
    "AsyncEventBus",
    "ConfirmationAnsweredEvent",
    "ConfirmationRequestedEvent",
    "IngestDoneEvent",
    "IngestErrorEvent",
    "IngestProgressEvent",
    "JobctlEvent",
    "JobLifecycleEvent",
    "JobLifecyclePhase",
]
