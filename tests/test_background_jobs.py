from pathlib import Path

import pytest

from jobctl.agent.nodes.apply_node import start_apply
from jobctl.config import default_config
from jobctl.core.events import AsyncEventBus, JobLifecycleEvent
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.db.connection import get_connection
from jobctl.jobs import apply_pipeline


class FakeProvider:
    def chat(self, messages, **kwargs):
        return {"content": "{}"}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]


def test_background_runner_updates_file_db_from_worker_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "jobctl.db"
    conn = get_connection(db_path)
    runner = None
    try:
        store = BackgroundJobStore(conn)
        bus = AsyncEventBus()
        queue = bus.subscribe()
        runner = BackgroundJobRunner(store, bus, db_path=db_path)
        job_id = store.create_job("test", "threaded")

        future = runner.submit(job_id, lambda: 1, source="test", label="Threaded test")

        assert future.result(timeout=5) == 1
        assert store.get_job(job_id).state == "done"  # type: ignore[union-attr]
        events = []
        while not queue.empty():
            event = queue.get_nowait()
            if isinstance(event, JobLifecycleEvent):
                events.append(event)
        assert [(event.phase, event.label) for event in events] == [
            ("queued", "Threaded test"),
            ("running", "Threaded test"),
            ("done", "Threaded test"),
        ]
    finally:
        if runner is not None:
            runner.shutdown(wait=True)
        conn.close()


def test_background_runner_publishes_error_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "jobctl.db"
    conn = get_connection(db_path)
    runner = None
    try:
        store = BackgroundJobStore(conn)
        bus = AsyncEventBus()
        queue = bus.subscribe()
        runner = BackgroundJobRunner(store, bus, db_path=db_path)
        job_id = store.create_job("test", "failing")

        def fail():
            raise RuntimeError("boom")

        future = runner.submit(job_id, fail, source="test", label="Failing test")

        with pytest.raises(RuntimeError, match="boom"):
            future.result(timeout=5)
        assert store.get_job(job_id).state == "failed"  # type: ignore[union-attr]
        lifecycle = []
        while not queue.empty():
            event = queue.get_nowait()
            if isinstance(event, JobLifecycleEvent):
                lifecycle.append(event)
        assert [event.phase for event in lifecycle] == ["queued", "running", "error"]
        assert lifecycle[-1].message == "boom"
    finally:
        if runner is not None:
            runner.shutdown(wait=True)
        conn.close()


def test_start_apply_uses_worker_thread_connection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "jobctl.db"
    conn = get_connection(db_path)
    runner = None
    try:
        store = BackgroundJobStore(conn)
        bus = AsyncEventBus()
        runner = BackgroundJobRunner(store, bus, db_path=db_path)

        def fake_run_apply(worker_conn, *_args, **_kwargs):
            import time

            worker_conn.execute("SELECT 1").fetchone()
            time.sleep(0.1)
            return "app-1"

        monkeypatch.setattr(apply_pipeline, "run_apply", fake_run_apply)

        job_id = start_apply(
            conn=conn,
            provider=FakeProvider(),
            bus=bus,
            store=store,
            runner=runner,
            config=default_config(),
            url_or_text="Senior Engineer JD",
            db_path=db_path,
        )

        future = runner._futures[job_id]
        assert future.result(timeout=5) == {"app_id": "app-1"}
        assert store.get_job(job_id).state == "done"  # type: ignore[union-attr]
    finally:
        if runner is not None:
            runner.shutdown(wait=True)
        conn.close()


def test_start_apply_without_db_path_allows_worker_thread_db_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "jobctl.db"
    conn = get_connection(db_path)
    runner = None
    try:
        store = BackgroundJobStore(conn)
        bus = AsyncEventBus()
        runner = BackgroundJobRunner(store, bus, db_path=db_path)

        def fake_run_apply(worker_conn, *_args, **_kwargs):
            worker_conn.execute("SELECT 1").fetchone()
            return "app-2"

        monkeypatch.setattr(apply_pipeline, "run_apply", fake_run_apply)

        job_id = start_apply(
            conn=conn,
            provider=FakeProvider(),
            bus=bus,
            store=store,
            runner=runner,
            config=default_config(),
            url_or_text="Backend Engineer JD",
            db_path=None,
        )

        future = runner._futures[job_id]
        assert future.result(timeout=5) == {"app_id": "app-2"}
        assert store.get_job(job_id).state == "done"  # type: ignore[union-attr]
    finally:
        if runner is not None:
            runner.shutdown(wait=True)
        conn.close()
