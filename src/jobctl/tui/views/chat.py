"""Chat view — scrollable message log + multi-line input with slash commands.

Implements T18 as a testable stub: an echo-bot handler validates the
``AsyncEventBus`` round-trip by publishing both the user turn and the echoed
assistant turn as :class:`AgentDoneEvent`. Slash commands (``/mode``,
``/quit``, ``/help``) are intercepted locally before forwarding to the bus.
The LangGraph-powered handler is wired in T22/T27; until then the echo bot
keeps the view usable in the TUI.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog

from jobctl.core.events import (
    AgentDoneEvent,
    AgentToolCallEvent,
    AgentTokenEvent,
    AsyncEventBus,
    ConfirmationRequestedEvent,
    JobctlEvent,
)
from jobctl.llm.base import Message


@dataclass
class _PendingStreamMessage:
    """Mutable scratchpad used while assembling streamed agent tokens."""

    buffer: str = ""
    widget: Any | None = None


class ChatView(Vertical):
    """Chat panel with RichLog message history and Input prompt."""

    # The chat Input emits ``Input.Submitted`` on Enter; we deliberately
    # avoid a screen-level ``enter`` binding so other inline widgets (file
    # picker, multi-select, confirm card) can handle Enter themselves.
    BINDINGS: list = []

    DEFAULT_CSS = """
    ChatView {
        layout: vertical;
        height: 1fr;
    }
    ChatView #chat-log {
        height: 1fr;
        background: #181825;
        color: #cdd6f4;
        padding: 1 2;
    }
    ChatView #chat-input {
        height: 3;
        border: solid #45475a;
        background: #1e1e2e;
        color: #cdd6f4;
    }
    ChatView #chat-input:focus {
        border: solid #89b4fa;
    }
    """

    def __init__(self, bus: AsyncEventBus | None = None, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._explicit_bus = bus
        self._subscription: asyncio.Queue[JobctlEvent] | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._stream = _PendingStreamMessage()

    @property
    def bus(self) -> AsyncEventBus:
        if self._explicit_bus is not None:
            return self._explicit_bus
        app = self.app
        if hasattr(app, "bus") and isinstance(app.bus, AsyncEventBus):  # type: ignore[attr-defined]
            return app.bus  # type: ignore[attr-defined]
        raise RuntimeError("ChatView requires an AsyncEventBus on the app.")

    def compose(self) -> ComposeResult:
        yield Vertical(
            RichLog(id="chat-log", wrap=True, markup=True, highlight=False),
            Input(id="chat-input", placeholder="Type a message and press Enter…"),
        )

    def on_mount(self) -> None:
        self._subscription = self.bus.subscribe()
        self._pump_task = asyncio.create_task(self._pump_events())
        log = self.query_one("#chat-log", RichLog)
        log.write(
            Markdown(
                "**Chat view** — type a message and press `Enter` to send. "
                "Try `/help` for available slash commands."
            )
        )
        self.query_one("#chat-input", Input).focus()
        self._restore_session_history()

    def _restore_session_history(self) -> None:
        app = self.app
        conn = getattr(app, "conn", None)
        session_id = getattr(app, "session_id", None)
        if conn is None or not session_id:
            return
        try:
            from jobctl.agent.session import load_session
        except Exception:  # pragma: no cover - agent deps may be missing in tests
            return
        try:
            saved = load_session(conn, session_id)
        except Exception:  # pragma: no cover - table may be absent in smoke tests
            return
        if saved is None:
            return
        log = self.query_one("#chat-log", RichLog)
        for message in saved.get("messages") or []:
            role = message.get("role")
            content = message.get("content")
            if not role or not content:
                continue
            log.write(Markdown(f"**{role}:** {content}"))

    def _persist_session(self, extra_message: Message | None = None) -> None:
        app = self.app
        conn = getattr(app, "conn", None)
        session_id = getattr(app, "session_id", None)
        if conn is None or not session_id:
            return
        try:
            from jobctl.agent.session import load_session, save_session
            from jobctl.agent.state import new_state
        except Exception:  # pragma: no cover - agent deps may be missing in tests
            return
        try:
            state = load_session(conn, session_id) or new_state(session_id)
            if extra_message is not None:
                messages = list(state.get("messages") or [])
                messages.append(extra_message)
                state["messages"] = messages
            save_session(conn, state)
        except Exception:  # pragma: no cover - best-effort persistence
            return

    def on_unmount(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            self._pump_task = None
        if self._subscription is not None:
            self.bus.unsubscribe(self._subscription)
            self._subscription = None

    def _handle_pending_slash_if_any(self) -> None:
        app = self.app
        pending = getattr(app, "pending_slash", None)
        if not pending:
            return
        try:
            delattr(app, "pending_slash")
        except AttributeError:  # pragma: no cover - defensive
            pass
        self._handle_submission(str(pending))

    def _handle_pending_chat_message_if_any(self) -> None:
        app = self.app
        pending = getattr(app, "pending_chat_message", None)
        if not pending:
            return
        app.pending_chat_message = None
        self._handle_submission(str(pending))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        event.stop()
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._handle_submission(text)

    def action_submit_message(self) -> None:
        editor = self.query_one("#chat-input", Input)
        text = editor.value.strip()
        if not text:
            return
        editor.value = ""
        self._handle_submission(text)

    def _handle_submission(self, text: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(Markdown(f"**you:** {text}"))

        if text.startswith("/"):
            handled = self._handle_slash_command(text)
            if handled:
                return

        user_message = Message(role="user", content=text)
        self._persist_session(extra_message=user_message)

        runner = self._resolve_runner()
        if runner is not None:
            asyncio.create_task(self._run_agent(runner, text))
            return

        self.bus.publish(AgentDoneEvent(role="user", content=text))
        reply = self._echo_reply(text)
        self._persist_session(extra_message=Message(role="assistant", content=reply))
        self.bus.publish(AgentDoneEvent(role="assistant", content=reply))

    def _resolve_runner(self):
        app = self.app
        runner = getattr(app, "agent_runner", None)
        return runner

    async def _run_agent(self, runner, user_message: str) -> None:
        try:
            await runner.submit(user_message)
        except Exception as exc:  # noqa: BLE001 - surfaced to the log
            log = self.query_one("#chat-log", RichLog)
            log.write(Markdown(f"_agent run failed: {exc}_"))

    def _echo_reply(self, text: str) -> str:
        return f"echo: {text}"

    def _handle_slash_command(self, raw: str) -> bool:
        command, _, rest = raw[1:].partition(" ")
        command = command.strip().lower()
        rest = rest.strip()

        if command == "quit":
            self.app.exit()
            return True
        if command == "help":
            from jobctl.tui.widgets.help_overlay import KeybindingHelpOverlay

            self.app.push_screen(KeybindingHelpOverlay())
            return True
        if command == "mode":
            log = self.query_one("#chat-log", RichLog)
            app = self.app
            current = getattr(app, "agent_mode", "chat")
            if not rest:
                log.write(Markdown(f"_current mode: **{current}**_"))
                return True
            setattr(app, "agent_mode", rest)
            log.write(Markdown(f"_mode set to **{rest}**_"))
            return True
        if command in {"chat", "graph", "tracker", "apply", "curate", "settings"}:
            show_view = getattr(self.app, "show_view", None)
            if show_view is None:
                log = self.query_one("#chat-log", RichLog)
                log.write(Markdown("_view navigation is unavailable in this app_"))
                return True
            show_view(command)
            return True
        if command == "report":
            self._render_report(rest or "summary")
            return True
        return False

    def _render_report(self, kind: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        conn = getattr(self.app, "conn", None)
        if conn is None:
            log.write(Markdown("_reports require a project database_"))
            return
        try:
            from jobctl.agent.coverage import analyze_coverage
        except Exception as exc:  # pragma: no cover - defensive
            log.write(Markdown(f"_could not load coverage helpers: {exc}_"))
            return
        try:
            coverage = analyze_coverage(conn)
        except Exception as exc:
            log.write(Markdown(f"_analyze_coverage failed: {exc}_"))
            return

        kind = kind.lower()
        if kind == "coverage":
            missing = ", ".join(coverage.get("missing_sections") or []) or "(none)"
            lines = [
                "### Coverage report",
                f"- roles: **{coverage.get('roles_count', 0)}**",
                f"- skills: **{coverage.get('skills_count', 0)}**",
                f"- achievements: **{coverage.get('achievements_count', 0)}**",
                f"- education present: **{coverage.get('has_education', False)}**",
                f"- stories present: **{coverage.get('has_stories', False)}**",
                f"- missing sections: _{missing}_",
            ]
            log.write(Markdown("\n".join(lines)))
            return

        if kind == "summary":
            lines = ["### Graph summary"]
            for key in (
                "roles_count",
                "skills_count",
                "achievements_count",
                "has_education",
                "has_stories",
            ):
                lines.append(f"- {key}: **{coverage.get(key)}**")
            log.write(Markdown("\n".join(lines)))
            return

        log.write(Markdown(f"_unknown /report target `{kind}`; try `coverage` or `summary`._"))

    async def _pump_events(self) -> None:
        assert self._subscription is not None
        queue = self._subscription
        try:
            while True:
                event = await queue.get()
                self._render_event(event)
        except asyncio.CancelledError:  # pragma: no cover - cancellation path
            raise

    def _render_event(self, event: JobctlEvent) -> None:
        log = self.query_one("#chat-log", RichLog)
        if isinstance(event, AgentTokenEvent):
            self._stream.buffer += event.token
            if self._stream.widget is None:
                from jobctl.tui.widgets.streaming_message import StreamingMessage

                container = self.query_one(Vertical)
                self._stream.widget = StreamingMessage()
                container.mount(self._stream.widget, before=self.query_one("#chat-input"))
            self._stream.widget.append(event.token)
            return
        if isinstance(event, AgentDoneEvent):
            if event.role == "user":
                return
            content = event.content
            if self._stream.buffer:
                content = content or self._stream.buffer
                if self._stream.widget is not None:
                    self._stream.widget.remove()
                self._stream = _PendingStreamMessage()
            log.write(Markdown(f"**{event.role}:** {content}"))
            return
        if isinstance(event, AgentToolCallEvent):
            pretty_args = ", ".join(f"{k}={v!r}" for k, v in event.args.items())
            log.write(Markdown(f"_tool call: `{event.name}({pretty_args})`_"))
            return
        if isinstance(event, ConfirmationRequestedEvent):
            container = self.query_one(Vertical)
            widget: Any
            if event.kind == "file_pick" or event.kind == "file_pick_resume":
                from jobctl.tui.widgets.file_picker import FilePicker

                widget = FilePicker(event, bus=self.bus)
            elif event.kind == "multi_select":
                from jobctl.tui.widgets.multi_select import MultiSelectList

                items = list(event.payload.get("items") or [])
                widget = MultiSelectList(event, items, bus=self.bus)
            else:
                from jobctl.tui.widgets.confirm_card import InlineConfirmCard

                widget = InlineConfirmCard(event, bus=self.bus)
            container.mount(widget, before=self.query_one("#chat-input"))
            return


__all__ = ["ChatView"]
