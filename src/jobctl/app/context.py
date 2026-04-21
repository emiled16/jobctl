"""Application runtime dependency container."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobctl.config import JobctlConfig
from jobctl.core.events import AsyncEventBus
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.llm.base import LLMProvider
from jobctl.rag.store import VectorStore


@dataclass
class JobctlContext:
    project_root: Path
    db_path: Path
    config: JobctlConfig
    conn: sqlite3.Connection
    provider: LLMProvider
    vector_store: VectorStore
    bus: AsyncEventBus
    job_store: BackgroundJobStore
    job_runner: BackgroundJobRunner
    session_factory: Any | None = None

    def close(self) -> None:
        self.vector_store.close()
        self.conn.close()
