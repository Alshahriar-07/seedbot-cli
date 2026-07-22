"""Agent loop: lets the model act on the project through the tool engine.

Two tool-calling paths share one loop:

* **Native** (preferred): providers that support function/tool calling get
  the registry's JSON schemas via ``stream_chat_with_tools`` and stream back
  :class:`ToolCallEvent`s. History records the calls structurally
  (``Message.tool_calls`` / role=="tool" results) so each provider can
  serialize them to its own wire format.
* **Text protocol** (fallback): the model emits a fenced block

      ```tool
      {"tool": "read_file", "args": {"path": "main.py"}}
      ```

  which the loop regex-parses; results are fed back as a ``[TOOL RESULTS]``
  user message. Used when the provider has no native support or its first
  native attempt fails (the session then downgrades once and stays there).

Either way the loop is: detect calls → execute through the permission gate →
feed results back → ask again, until the model answers with no tool calls
(the final response) or the step budget runs out. Malformed calls are not
fatal: the parse error is fed back so the model can correct itself, and
consecutive failures are bounded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .chat import ChatEngine, ChatError
from .identity import build_system_prompt
from .models import AppConfig, Message, ToolCallRecord
from .project import detect_project
from .providers import provider_label
from .providers.base import TextDelta, ToolCallEvent, ToolSpec
from ..tools import PermissionError_, PermissionManager, ToolError, get_tool, tool_manifest
from ..tools.base import ToolResult, tool_specs
from ..utils.logger import get_logger

_log = get_logger("agent")

# Hard bounds so a confused model can never loop forever.
MAX_STEPS = 15
_MAX_CONSECUTIVE_FAILURES = 3
_MAX_CALLS_PER_STEP = 8

_TOOL_BLOCK = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)

_AGENT_PREAMBLE = (
    "\n\nYou are in AGENT MODE with access to the user's project at {workspace} "
    "(permission mode: {mode})."
)

_TEXT_PROTOCOL_INSTRUCTIONS = (
    " To use a tool, emit a fenced block exactly like:\n"
    '```tool\n{{"tool": "<name>", "args": {{...}}}}\n```\n'
    "Rules: any number of tool blocks per reply; results arrive in the next "
    "message as [TOOL RESULTS]; when the task is complete, reply WITHOUT tool "
    "blocks — that is your final answer. Never invent tool results. If a call "
    "fails, read the error and correct your next call.\n\n"
    "Available tools:\n{manifest}"
)

_NATIVE_INSTRUCTIONS = (
    " Use the provided tools to inspect and change the project. Rules: tool "
    "results arrive as tool messages; when the task is complete, answer "
    "WITHOUT calling tools — that is your final answer. Never invent tool "
    "results. If a call fails, read the error and correct your next call. "
    "Prefer editing existing files over rewriting them."
)

_DESKTOP_PROMPT_HEADER = (
    "\n\nCOMPUTER ENGINE is available: you can control this computer, but you "
    "are the PLANNER, not the hands. A deterministic engine does the work; you "
    "only decide WHAT to do. Rules:\n"
    "1. You NEVER produce coordinates, keystrokes, click sequences, or wait "
    "loops. You choose a skill (computer_run) or a semantic UI action "
    "(ui_click, ui_type, …) and describe the target in words — the engine "
    "resolves it, executes it, verifies the result, and recovers from failures "
    "on its own.\n"
    "2. Prefer a named skill from the catalog below; it already knows the full "
    "procedure. Use the ui_* actions only for UI a skill doesn't cover.\n"
    "3. Read computer_state instead of re-inspecting the screen — the engine "
    "remembers the focused app, pointer, clipboard, terminal directory, "
    "current project, and recent actions for you.\n"
    "4. Each tool result already reflects VERIFIED reality (the engine checked "
    "before reporting). Trust it; never claim success it didn't confirm.\n"
    "5. Call the engine again only when it reports failure with a replan hint, "
    "or when computer_see shows unexpected UI. Some actions need the user's "
    "confirmation and may be denied — respect denials, do not retry them.\n\n"
    "Available skills:\n"
)


def _desktop_prompt_section(max_level) -> str:
    """The Computer Engine prompt block, including the live skill catalog."""
    try:
        from ..computer.skills import REGISTRY
        from ..computer import catalog as _catalog  # noqa: F401 — populate registry

        manifest = REGISTRY.manifest(max_level=max_level)
    except Exception:
        manifest = "(catalog unavailable)"
    return _DESKTOP_PROMPT_HEADER + (manifest or "(no skills at this level)")


@dataclass(slots=True)
class ToolCall:
    """One parsed tool invocation from the model's reply."""

    tool: str
    args: dict
    error: str = ""  # parse/validation error, fed back to the model
    call_id: str = ""  # provider call id ("" for text-protocol calls)


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Extract tool calls from a model reply (malformed ones carry .error)."""
    calls: list[ToolCall] = []
    for match in _TOOL_BLOCK.finditer(text):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            calls.append(ToolCall("", {}, error=f"Invalid JSON in tool block: {exc}"))
            continue
        if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
            calls.append(
                ToolCall("", {}, error='Tool block must be {"tool": "<name>", "args": {...}}.')
            )
            continue
        args = data.get("args") or {}
        if not isinstance(args, dict):
            calls.append(ToolCall(data["tool"], {}, error='"args" must be a JSON object.'))
            continue
        calls.append(ToolCall(data["tool"].strip().lower(), args))
    return calls


def strip_tool_blocks(text: str) -> str:
    """Reply text with the tool blocks removed (what the user should see)."""
    return _TOOL_BLOCK.sub("", text).strip()


def _downgrade_for_text(messages: list[Message]) -> list[Message]:
    """Render native-era history into text-protocol form.

    Providers' plain ``stream_chat``/``to_api()`` never learned the tool
    roles, so before any text-protocol request: assistant ``tool_calls``
    become appended ```` ```tool ```` blocks, and consecutive role=="tool"
    results merge into one ``[TOOL RESULTS]`` user message.
    """
    out: list[Message] = []
    pending_results: list[str] = []

    def flush_results() -> None:
        if pending_results:
            out.append(
                Message(
                    role="user",
                    content="[TOOL RESULTS]\n" + "\n\n".join(pending_results),
                )
            )
            pending_results.clear()

    for message in messages:
        if message.role == "tool":
            pending_results.append(f"{message.tool_name} -> {message.content}")
            continue
        flush_results()
        if message.role == "assistant" and message.tool_calls:
            blocks = "\n".join(
                "```tool\n"
                + json.dumps(
                    {"tool": call.name, "args": call.arguments}, ensure_ascii=False
                )
                + "\n```"
                for call in message.tool_calls
            )
            content = (message.content + "\n" + blocks).strip()
            out.append(
                Message(role="assistant", content=content, images=message.images)
            )
        else:
            out.append(message)
    flush_results()
    return out


class AgentEngine(ChatEngine):
    """ChatEngine that runs the detect → execute → validate → retry loop.

    ``on_event(kind, detail)`` reports progress ('call', 'result', 'error',
    'limit') so the UI can narrate tool activity without this module
    importing any UI code.
    """

    def __init__(
        self,
        config: AppConfig,
        permissions: PermissionManager,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(config)
        self.permissions = permissions
        self._on_event = on_event or (lambda kind, detail: None)
        # Native tool calling: None = untried, False = fell back to the text
        # protocol for this session, True = at least one native step worked.
        self._native: bool | None = None
        self.messages[0] = Message(role="system", content=self._system_prompt())

    def _system_prompt(self) -> str:
        desktop_section = ""
        if self._desktop_active():
            desktop_section = _desktop_prompt_section(self.permissions.level)

        # Build Seed Code identity + agent instructions
        base_identity = build_system_prompt(
            provider_label(self.config.provider),
            self.config.model or "unspecified"
        )
        preamble = _AGENT_PREAMBLE.format(
            workspace=self.permissions.workspace,
            mode=self.permissions.mode.label,
        )
        if self._native_active():
            # The API carries the tool schemas; no manifest needed.
            instructions = _NATIVE_INSTRUCTIONS
        else:
            instructions = _TEXT_PROTOCOL_INSTRUCTIONS.format(
                manifest=tool_manifest(self._groups())
            )
        return (
            base_identity
            + preamble
            + instructions
            + desktop_section
            + self._project_context()
        )

    def _project_context(self) -> str:
        """Ambient project summary; detection must never break construction."""
        try:
            info = detect_project(self.permissions.workspace)
            return f"\n\nPROJECT CONTEXT:\n{info.summary}" if info.summary else ""
        except Exception:
            _log.exception("project detection failed")
            return ""

    def _groups(self) -> tuple[str, ...]:
        return ("core", "desktop") if self._desktop_active() else ("core",)

    def _desktop_active(self) -> bool:
        """Desktop tools are advertised only when enabled AND runnable here."""
        desktop = self.permissions.desktop
        if desktop is None or not desktop.enabled:
            return False
        from ..computer import is_available

        return is_available()[0]

    def _native_active(self) -> bool:
        """Whether this session should use native tool calling right now."""
        if self._native is False:
            return False
        try:
            from .providers import get_provider

            return get_provider(self.config.provider).supports_tools(self.config)
        except Exception:
            return False

    def refresh_system_prompt(self) -> None:
        """Re-render the system prompt (after a permission-mode change)."""
        self.messages[0] = Message(role="system", content=self._system_prompt())

    # --- one whole agent turn ------------------------------------------------
    def run_turn(self, user_text: str) -> str:
        """Run the full agent loop for one user request; returns final text.

        Raises :class:`ChatError` only when the provider itself fails; tool
        failures are fed back to the model as retryable results.
        """
        self.add_user(user_text)
        failures = 0

        step = 0
        while step < MAX_STEPS:
            step += 1
            if self._native_active():
                outcome, payload = self._native_step(failures)
                if outcome == "fallback":
                    # Downgrade once for the session and retry the SAME step
                    # through the text protocol.
                    _log.warning("native tool calling failed; falling back to text protocol")
                    self._native = False
                    self.refresh_system_prompt()
                    step -= 1
                    continue
            else:
                outcome, payload = self._text_step(failures)

            if outcome == "final":
                return payload or "Done."
            failures = failures + 1 if outcome == "failed" else 0

        self._on_event("limit", f"step budget ({MAX_STEPS}) reached")
        return (
            "I hit the agent step limit before finishing. Progress so far is "
            "applied; ask me to continue to keep going."
        )

    # --- native path ---------------------------------------------------------
    def _native_step(self, failures: int) -> tuple[str, str | None]:
        """One step over the native tool-calling API.

        Returns ("final", text) | ("ok", None) | ("failed", None) |
        ("fallback", None).
        """
        specs = [ToolSpec(**s) for s in tool_specs(self._groups())]
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        try:
            for event in self.stream_reply_events(specs):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                elif isinstance(event, ToolCallEvent):
                    calls.append(
                        ToolCall(
                            tool=(event.name or "").strip().lower(),
                            args=event.arguments,
                            error=event.error,
                            call_id=event.id,
                        )
                    )
        except ChatError as exc:
            if self._native is None:
                # Never succeeded natively — treat any failure on the first
                # attempt as "tools unsupported" and fall back gracefully.
                _log.info("first native step failed (%s)", exc)
                return ("fallback", None)
            self.drop_last_user()
            raise

        reply = "".join(text_parts)

        if not calls:
            # Belt-and-braces: some models emit the TEXT protocol even when
            # given native tools — honour it rather than ending the turn.
            text_calls = parse_tool_calls(reply)
            if not text_calls:
                self._native = True
                self.add_assistant(reply)
                final = reply.strip()
                return ("final", final if final else "Done.")
            self._native = True
            return self._execute_text_style(reply, text_calls, failures)

        self._native = True
        executed = calls[:_MAX_CALLS_PER_STEP]
        deferred = calls[_MAX_CALLS_PER_STEP:]

        self.messages.append(
            Message(
                role="assistant",
                content=reply,
                tool_calls=[
                    ToolCallRecord(id=c.call_id, name=c.tool, arguments=c.args)
                    for c in calls
                ],
            )
        )
        shown = reply.strip()
        if shown:
            self._on_event("say", shown)

        results, step_failed = self._execute_calls(executed)
        images = self._drain_images()
        for call, result_text in zip(executed, results):
            self.messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=call.call_id,
                    tool_name=call.tool,
                    images=images,
                )
            )
            images = []  # attach pending screenshots to the first result only
        # Every issued call id must be answered (strict APIs 400 otherwise).
        for call in deferred:
            self.messages.append(
                Message(
                    role="tool",
                    content=(
                        f"(not executed: only the first {_MAX_CALLS_PER_STEP} tool "
                        "calls run per step; issue this again next step)"
                    ),
                    tool_call_id=call.call_id,
                    tool_name=call.tool,
                )
            )

        if self._limit_reached(step_failed, failures):
            # Fold the nudge into the last tool result rather than adding a
            # user turn — strict APIs require every tool_use answered by
            # tool_results in one block, with no interleaved user text.
            last = self.messages[-1]
            last.content += (
                "\n\n[SYSTEM] Multiple consecutive steps failed. Stop calling "
                "tools and summarise the problem for the user."
            )
        _log.info("agent native step: %d call(s), failed=%s", len(calls), step_failed)
        return ("failed" if step_failed else "ok", None)

    # --- text-protocol path --------------------------------------------------
    def _text_step(self, failures: int) -> tuple[str, str | None]:
        """One step over the text protocol (fenced ```tool blocks)."""
        # Providers' plain path never learned the tool roles; render any
        # native-era messages into text form for this request.
        original = self.messages
        self.messages = _downgrade_for_text(original)
        try:
            reply = "".join(self.stream_reply())
        except ChatError:
            self.messages = original
            self.drop_last_user()
            raise
        self.messages = original

        calls = parse_tool_calls(reply)
        if not calls:
            self.add_assistant(reply)
            final = reply.strip()
            # Some models complete tool work without emitting a summary line.
            # Return a minimal acknowledgement so the UI never shows "(no response)".
            return ("final", final if final else "Done.")

        return self._execute_text_style(reply, calls, failures)

    def _execute_text_style(
        self, reply: str, calls: list[ToolCall], failures: int
    ) -> tuple[str, str | None]:
        """Execute calls and append text-protocol style feedback messages."""
        self.add_assistant(reply)
        shown = strip_tool_blocks(reply)
        if shown:
            self._on_event("say", shown)

        results, step_failed = self._execute_calls(calls[:_MAX_CALLS_PER_STEP])
        if len(calls) > _MAX_CALLS_PER_STEP:
            results.append(
                f"(only the first {_MAX_CALLS_PER_STEP} tool calls were run; "
                "issue the rest next step)"
            )

        if self._limit_reached(step_failed, failures):
            results.append(
                "[SYSTEM] Multiple consecutive steps failed. Stop calling tools "
                "and summarise the problem for the user."
            )

        feedback = "[TOOL RESULTS]\n" + "\n\n".join(results)
        _log.info("agent text step: %d call(s), failed=%s", len(calls), step_failed)
        self.messages.append(
            Message(role="user", content=feedback, images=self._drain_images())
        )
        return ("failed" if step_failed else "ok", None)

    def _limit_reached(self, step_failed: bool, failures: int) -> bool:
        """True when this failure crosses the consecutive-failure bound."""
        if not step_failed:
            return False
        if failures + 1 >= _MAX_CONSECUTIVE_FAILURES:
            self._on_event("limit", "too many consecutive tool failures")
            return True
        return False

    def _drain_images(self) -> list[str]:
        """Pending desktop screenshots — attached only for vision providers.

        Screenshots are queued by desktop_see/desktop_screenshot; when the
        active provider cannot take images they are simply dropped (the UIA
        text snapshot in the tool result carries the information instead).
        """
        desktop = self.permissions.desktop
        if desktop is None or not desktop.pending_images:
            return []
        images = list(desktop.pending_images)
        desktop.pending_images.clear()
        try:
            from .providers import get_provider

            if get_provider(self.config.provider).supports_images(self.config):
                return images
        except Exception:  # provider lookup must never break the loop
            pass
        return []

    def _execute_calls(self, calls: list[ToolCall]) -> tuple[list[str], bool]:
        """Execute parsed calls; returns (results-for-model, any_failed)."""
        results: list[str] = []
        any_failed = False
        for call in calls:
            if call.error:
                any_failed = True
                results.append(f"[ERROR] {call.error}")
                self._on_event("error", call.error)
                continue
            label = f"{call.tool}({json.dumps(call.args, ensure_ascii=False)[:120]})"
            self._on_event("call", label)
            try:
                result = get_tool(call.tool).run(self.permissions, call.args)
            except (ToolError, PermissionError_) as exc:
                result = ToolResult(False, str(exc))
            except Exception as exc:  # a tool bug must not kill the loop
                _log.exception("tool crashed: %s", call.tool)
                result = ToolResult(False, f"Tool crashed: {exc}")
            if not result.ok:
                any_failed = True
            self._on_event("result" if result.ok else "error", result.output[:200])
            results.append(f"{call.tool} -> {result.for_model()}")
        return results, any_failed
