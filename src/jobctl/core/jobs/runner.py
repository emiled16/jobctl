"""Thread-pool-backed runner for background jobs."""

from __future__ import annotations

import asyncio
import inspect
import logging
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from jobctl.core.events import (
    AsyncEventBus,
    IngestDoneEvent,
    IngestErrorEvent,
)
from jobctl.core.jobs.store import BackgroundJobStore

logger = logging.getLogger(__name__)


class BackgroundJobRunner:
    """Run arbitrary callables in a thread pool and track their lifecycle.

    Each submission is identified by a job id (created via
    :class:`BackgroundJobStore`). Successful returns trigger
    ``IngestDoneEvent`` while uncaught exceptions persist the traceback
    to the store and trigger ``IngestErrorEvent``.
    """

    def __init__(
        self,
        store: BackgroundJobStore,
        bus: AsyncEventBus,
        *,
        max_workers: int = 2,
        source_label: str = "ingest",
    ) -> None:
        self._store = store
        self._bus = bus
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future[Any]] = {}
        self._source_label = source_label

    def submit(
        self,
        job_id: str,
        fn: Callable[..., Any],
        /,
        *args: Any,
        source: str | None = None,
        **kwargs: Any,
    ) -> Future[Any]:
        source_label = source or self._source_label
        self._store.update_job(job_id, state="running")

        def _target() -> Any:
            try:
                result = fn(*args, **kwargs)
                if inspect.iscoroutine(result):
                    result = asyncio.run(result)
                self._store.update_job(job_id, state="done")
                facts_added = int(result) if isinstance(result, int) else 0
                self._bus.publish(
                    IngestDoneEvent(
                        source=source_label,
                        facts_added=facts_added,
                        job_id=job_id,
                    )
                )
                return result
            except Exception as exc:
                tb = traceback.format_exc()
                logger.exception("background job %s failed", job_id)
                self._store.update_job(job_id, state="failed", error=tb)
                self._bus.publish(
                    IngestErrorEvent(source=source_label, error=str(exc), job_id=job_id)
                )
                raise

        future = self._executor.submit(_target)
        self._futures[job_id] = future
        future.add_done_callback(lambda _f, j=job_id: self._futures.pop(j, None))
        return future

    def cancel(self, job_id: str) -> bool:
        future = self._futures.get(job_id)
        if future is None:
            return False
        cancelled = future.cancel()
        if cancelled:
            self._store.update_job(job_id, state="failed", error="cancelled")
        return cancelled

    def active_jobs(self) -> list[str]:
        return [job_id for job_id, f in self._futures.items() if not f.done()]

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


__all__ = ["BackgroundJobRunner"]
