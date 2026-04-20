"""Apply view: picks the active application, shows JD + evaluation, renders PDFs.

This is the T17 port of the v1 ``MaterialRenderApp`` into a Textual Screen
that lives inside :class:`jobctl.tui.app.JobctlApp`. It keeps the section
picker, YAML preview, template selection, and PDF render trigger. A top
panel shows the active ``ExtractedJD`` (company, role, score) and a
two-column strengths/gaps panel reads from ``FitEvaluation``. Render and
cover-letter generation are triggered via workers that publish
:class:`jobctl.core.events.ApplyProgressEvent` so no user-facing call
blocks the UI. T43 expands this with editable YAML and an Open-PDF button.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, ProgressBar, Select, Static, TextArea

from jobctl.core.events import ApplyProgressEvent, AsyncEventBus
from jobctl.llm.base import LLMProvider


@dataclass
class ApplicationRow:
    id: str
    company: str
    role: str
    score: float | None
    location: str | None
    resume_yaml_path: str | None
    resume_pdf_path: str | None
    cover_letter_yaml_path: str | None
    jd_raw: str | None
    jd_structured: dict[str, Any] | None
    evaluation_structured: dict[str, Any] | None


def _load_applications(conn: sqlite3.Connection) -> list[ApplicationRow]:
    rows = conn.execute(
        """
        SELECT id, company, role, fit_score, location, resume_yaml_path,
               resume_pdf_path, cover_letter_yaml_path, jd_raw, jd_structured,
               evaluation_structured
        FROM applications
        ORDER BY updated_at DESC
        """
    ).fetchall()
    result: list[ApplicationRow] = []
    for row in rows:
        result.append(
            ApplicationRow(
                id=row["id"],
                company=row["company"],
                role=row["role"],
                score=row["fit_score"],
                location=row["location"],
                resume_yaml_path=row["resume_yaml_path"],
                resume_pdf_path=row["resume_pdf_path"],
                cover_letter_yaml_path=row["cover_letter_yaml_path"],
                jd_raw=row["jd_raw"],
                jd_structured=_maybe_json(row["jd_structured"]),
                evaluation_structured=_maybe_json(row["evaluation_structured"]),
            )
        )
    return result


def _maybe_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


class ApplyView(Vertical):
    BINDINGS = [
        Binding("p", "render_pdf", "Render PDF"),
        Binding("o", "open_pdf", "Open PDF"),
        Binding("s", "save_yaml", "Save YAML"),
        Binding("c", "generate_cover", "Cover letter"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    ApplyView { height: 1fr; }
    #apply-header { padding: 0 1; color: #a6adc8; }
    #apply-body { height: 1fr; }
    #apply-left { width: 40%; padding: 1; }
    #apply-right { width: 1fr; padding: 1; }
    #apply-progress { margin-top: 1; display: none; }
    #apply-status { margin-top: 1; color: #a6e3a1; }
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: LLMProvider,
        bus: AsyncEventBus,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.conn = conn
        self.provider = provider
        self.bus = bus
        self._applications: list[ApplicationRow] = []
        self.current_app_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Label("Apply", id="apply-title")
        yield Static("", id="apply-header")
        yield Select([], id="apply-select", allow_blank=True, prompt="No applications yet")
        with Horizontal(id="apply-body"):
            with Vertical(id="apply-left"):
                yield Label("Job description")
                yield Static("", id="apply-jd")
            with Vertical(id="apply-right"):
                yield Label("Evaluation")
                yield Static("", id="apply-evaluation")
                yield Label("Resume YAML")
                yield TextArea(id="apply-yaml")
        yield Horizontal(
            Button("Render PDF", id="apply-render", variant="primary"),
            Button("Open PDF", id="apply-open"),
            Button("Save YAML", id="apply-save"),
            Button("Generate cover letter", id="apply-cover"),
            Button("Refresh", id="apply-refresh"),
            id="apply-actions",
        )
        yield ProgressBar(total=100, id="apply-progress", show_eta=False)
        yield Static("", id="apply-status")

    def on_mount(self) -> None:
        self._refresh_applications()
        self._queue = self.bus.subscribe()
        self.run_worker(self._pump_progress(), exclusive=False)

    async def _pump_progress(self) -> None:
        while True:
            event = await self._queue.get()
            if isinstance(event, ApplyProgressEvent):
                self._set_status(f"{event.step}: {event.message}")
                bar = self.query_one("#apply-progress", ProgressBar)
                bar.display = True
                # Advance a little on each progress event.
                bar.progress = min(100, (bar.progress or 0) + 15)

    def _refresh_applications(self) -> None:
        self._applications = _load_applications(self.conn)
        select = self.query_one("#apply-select", Select)
        options = [
            (f"{a.company} — {a.role}", a.id) for a in self._applications
        ] or [("(no applications)", "")]
        select.set_options(options)
        if self._applications:
            select.value = self._applications[0].id
            self._load_current(self._applications[0].id)
        else:
            self._load_current(None)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "apply-select" and event.value:
            self._load_current(str(event.value))

    def _load_current(self, app_id: str | None) -> None:
        self.current_app_id = app_id
        header = self.query_one("#apply-header", Static)
        jd = self.query_one("#apply-jd", Static)
        evaluation = self.query_one("#apply-evaluation", Static)
        yaml_area = self.query_one("#apply-yaml", TextArea)

        if app_id is None:
            header.update("No applications yet.")
            jd.update("")
            evaluation.update("")
            yaml_area.text = ""
            return

        row = next((a for a in self._applications if a.id == app_id), None)
        if row is None:
            return
        score = f"{row.score:.1f}" if row.score is not None else "—"
        header.update(f"{row.company}  |  {row.role}  |  score {score}")
        jd.update(row.jd_raw or "(no JD stored)")
        evaluation.update(_format_evaluation(row.evaluation_structured))

        if row.resume_yaml_path and Path(row.resume_yaml_path).exists():
            yaml_area.text = Path(row.resume_yaml_path).read_text(encoding="utf-8")
        else:
            yaml_area.text = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-render":
            self.action_render_pdf()
        elif event.button.id == "apply-open":
            self.action_open_pdf()
        elif event.button.id == "apply-save":
            self.action_save_yaml()
        elif event.button.id == "apply-cover":
            self.action_generate_cover()
        elif event.button.id == "apply-refresh":
            self.action_refresh()

    def action_refresh(self) -> None:
        self._refresh_applications()
        self._set_status("Applications refreshed.")

    def _current_row(self) -> ApplicationRow | None:
        if self.current_app_id is None:
            return None
        return next(
            (a for a in self._applications if a.id == self.current_app_id), None
        )

    def action_save_yaml(self) -> None:
        row = self._current_row()
        if row is None or not row.resume_yaml_path:
            self._set_status("No resume YAML path for this application.")
            return
        yaml_area = self.query_one("#apply-yaml", TextArea)
        target = Path(row.resume_yaml_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml_area.text, encoding="utf-8")
        self._set_status(f"Saved YAML to {target}")

    def action_render_pdf(self) -> None:
        row = self._current_row()
        if row is None or not row.resume_yaml_path:
            self._set_status("Save a resume YAML first (press 's').")
            return

        self.bus.publish(
            ApplyProgressEvent(
                step="render_pdf",
                message="rendering",
                job_id=row.id,
            )
        )

        def _render() -> str:
            from jobctl.generation.renderer import output_pdf_path, render_pdf

            yaml_path = Path(row.resume_yaml_path)
            pdf_path = render_pdf(
                yaml_path,
                getattr(self.app.config, "default_template", None),  # type: ignore[attr-defined]
                output_pdf_path(yaml_path),
            )
            return str(pdf_path)

        async def _do_render() -> None:
            try:
                pdf_path = await self.app.run_in_thread(_render)  # type: ignore[attr-defined]
            except AttributeError:
                # Older Textual versions: fall back to running in executor.
                import asyncio

                pdf_path = await asyncio.get_event_loop().run_in_executor(
                    None, _render
                )
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Render failed: {exc}")
                return
            self._set_status(f"Rendered {pdf_path}")
            self.bus.publish(
                ApplyProgressEvent(
                    step="render_pdf", message="done", job_id=row.id
                )
            )

        self.run_worker(_do_render(), exclusive=False)

    def action_open_pdf(self) -> None:
        row = self._current_row()
        if row is None or not row.resume_pdf_path:
            self._set_status("No PDF rendered yet.")
            return
        import subprocess
        import sys

        pdf = Path(row.resume_pdf_path)
        if not pdf.exists():
            self._set_status(f"PDF not found: {pdf}")
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(pdf)])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(pdf)])
            else:
                subprocess.Popen(["cmd", "/c", "start", "", str(pdf)], shell=True)
            self._set_status(f"Opened {pdf}")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Open failed: {exc}")

    def action_generate_cover(self) -> None:
        if self.current_app_id is None:
            return
        self._set_status("Cover-letter generation queued.")
        self.bus.publish(
            ApplyProgressEvent(
                step="generate_cover", message="queued", job_id=self.current_app_id
            )
        )

    def _set_status(self, message: str) -> None:
        self.query_one("#apply-status", Static).update(message)


def _format_evaluation(evaluation: dict[str, Any] | None) -> str:
    if not evaluation:
        return "(no evaluation)"
    strengths = evaluation.get("matching_strengths") or []
    gaps = evaluation.get("gaps") or []
    summary = evaluation.get("summary") or ""
    lines = [summary, ""]
    lines.append("Strengths:")
    for item in strengths[:8]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Gaps:")
    for item in gaps[:8]:
        lines.append(f"- {item}")
    return "\n".join(lines)
