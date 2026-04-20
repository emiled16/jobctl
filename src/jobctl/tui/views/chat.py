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
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import RichLog, TextArea

from jobctl.core.events import (
    AgentDoneEvent,
    AgentToolCallEvent,
    AgentTokenEvent,
    AsyncEventBus,
    ConfirmationRequestedEvent,
    JobctlEvent,
)
from jobctl.llm.base import Message

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from jobctl.tui.app import JobctlApp


@dataclass
class _PendingStreamMessage:
    """Mutable scratchpad used while assembling streamed agent tokens."""

    buffer: str = ""
    line_index: int | None = None


class ChatView(Screen):
    """Chat screen with RichLog message history and TextArea input."""

    BINDINGS = [
        Binding("ctrl+enter", "submit_message", "Send", show=False),
    ]

    DEFAULT_CSS = """
    ChatView {
        layout: vertical;
    }
    ChatView #chat-log {
        height: 1fr;
        background: #181825;
        color: #cdd6f4;
        padding: 1 2;
    }
    ChatView #chat-input {
        height: 6;
        border: solid #45475a;
        background: #1e1e2e;
    }
    """

    def __init__(self, bus: AsyncEventBus | None = None) -> None:
        super().__init__()
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
            TextArea(id="chat-input"),
        )

    def on_mount(self) -> None:
        self._subscription = self.bus.subscribe()
        self._pump_task = asyncio.create_task(self._pump_events())
        log = self.query_one("#chat-log", RichLog)
        log.write(
            Markdown(
                "**Chat view** — type a message and press `Ctrl+Enter` "
                "to send. Try `/help` for available slash commands."
            )
        )
        self._restore_session_history()
        self._handle_pending_slash_if_any()
        self._handle_pending_chat_message_if_any()

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

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not event.shift:
            editor = self.query_one("#chat-input", TextArea)
            if editor.has_focus:
                event.stop()
                self.action_submit_message()

    def action_submit_message(self) -> None:
        editor = self.query_one("#chat-input", TextArea)
        text = editor.text.strip()
        if not text:
            return
        editor.text = ""
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
        self.bus.publish(AgentDoneEvent(role="user", content=text))
        reply = self._echo_reply(text)
        self._persist_session(extra_message=Message(role="assistant", content=reply))
        self.bus.publish(AgentDoneEvent(role="assistant", content=reply))

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
        return False

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
            log.write(event.token)
            return
        if isinstance(event, AgentDoneEvent):
            if event.role == "user":
                return
            if self._stream.buffer:
                log.write("\n")
                self._stream = _PendingStreamMessage()
            log.write(Markdown(f"**{event.role}:** {event.content}"))
            return
        if isinstance(event, AgentToolCallEvent):
            pretty_args = ", ".join(f"{k}={v!r}" for k, v in event.args.items())
            log.write(Markdown(f"_tool call: `{event.name}({pretty_args})`_"))
            return
        if isinstance(event, ConfirmationRequestedEvent):
            from jobctl.tui.widgets.confirm_card import InlineConfirmCard

            card = InlineConfirmCard(event, bus=self.bus)
            container = self.query_one(Vertical)
            container.mount(card, before=self.query_one("#chat-input"))
            return


__all__ = ["ChatView"]
