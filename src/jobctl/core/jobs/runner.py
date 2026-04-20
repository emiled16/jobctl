"""Thread-pool-backed runner for background jobs."""

from __future__ import annotations

import asyncio
from contextlib import closing
import inspect
import logging
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from jobctl.core.events import (
    ApplyProgressEvent,
    AsyncEventBus,
    IngestErrorEvent,
    JobLifecycleEvent,
    JobLifecyclePhase,
)
from jobctl.db.connection import get_connection
from jobctl.core.jobs.store import BackgroundJobStore

logger = logging.getLogger(__name__)


class BackgroundJobRunner:
    """Run arbitrary callables in a thread pool and track their lifecycle.

    Each submission is identified by a job id (created via
    :class:`BackgroundJobStore`). Domain code owns success/progress events;
    this runner owns lifecycle persistence and fallback error events.
    """

    def __init__(
        self,
        store: BackgroundJobStore,
        bus: AsyncEventBus,
        *,
        max_workers: int = 2,
        source_label: str = "ingest",
        db_path: Path | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future[Any]] = {}
        self._source_label = source_label
        self._db_path = db_path

    def submit(
        self,
        job_id: str,
        fn: Callable[..., Any],
        /,
        *args: Any,
        source: str | None = None,
        label: str | None = None,
        **kwargs: Any,
    ) -> Future[Any]:
        source_label = source or self._source_label
        job_label = label or source_label.capitalize()
        self._publish_lifecycle(
            job_id,
            kind=source_label,
            label=job_label,
            phase="queued",
            message="Queued",
        )
        self._store.update_job(job_id, state="running")
        self._publish_lifecycle(
            job_id,
            kind=source_label,
            label=job_label,
            phase="running",
            message="Running",
        )

        def _target() -> Any:
            try:
                result = fn(*args, **kwargs)
                if inspect.iscoroutine(result):
                    result = asyncio.run(result)
                self._update_job(job_id, state="done")
                self._publish_lifecycle(
                    job_id,
                    kind=source_label,
                    label=job_label,
                    phase="done",
                    message="Done",
                )
                return result
            except Exception as exc:
                tb = traceback.format_exc()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.exception("background job %s failed", job_id)
                else:
                    logger.error("background job %s failed: %s", job_id, exc)
                self._update_job(job_id, state="failed", error=tb)
                self._publish_lifecycle(
                    job_id,
                    kind=source_label,
                    label=job_label,
                    phase="error",
                    message=str(exc),
                )
                if source_label == "apply":
                    self._bus.publish(
                        ApplyProgressEvent(
                            step="error",
                            message=str(exc),
                            job_id=job_id,
                        )
                    )
                else:
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
            self._store.update_job(job_id, state="cancelled", error="cancelled")
            self._bus.publish(
                JobLifecycleEvent(
                    job_id=job_id,
                    kind=self._source_label,
                    label=self._source_label.capitalize(),
                    phase="cancelled",
                    message="Cancelled",
                )
            )
        return cancelled

    def active_jobs(self) -> list[str]:
        return [job_id for job_id, f in self._futures.items() if not f.done()]

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _update_job(
        self,
        job_id: str,
        *,
        state: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._db_path is None:
            self._store.update_job(job_id, state=state, error=error)
            return
        with closing(get_connection(self._db_path)) as conn:
            BackgroundJobStore(conn).update_job(job_id, state=state, error=error)

    def _publish_lifecycle(
        self,
        job_id: str,
        *,
        kind: str,
        label: str,
        phase: JobLifecyclePhase,
        message: str,
    ) -> None:
        self._bus.publish(
            JobLifecycleEvent(
                job_id=job_id,
                kind=kind,
                label=label,
                phase=phase,
                message=message,
            )
        )


__all__ = ["BackgroundJobRunner"]
