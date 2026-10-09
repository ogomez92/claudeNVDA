# ClauVDA NVDA Add-on - Computer use agent loop
# -*- coding: utf-8 -*-

"""Run Claude's computer use loop on a background thread.

A :class:`Session` sends the user's request and a screenshot to Claude, runs
the actions Claude asks for through :mod:`inputhandler`, and returns the
results until Claude is done. In screen-reader testing mode it also records
what NVDA speaks after each action and reports it back, so Claude can judge the
interface the way a blind user hears it.

Network calls run on the worker thread; screen capture and input injection are
marshalled onto NVDA's main thread.

The conversation is append-only: earlier turns are never edited, because the
current models reject (or silently drop) their earlier thinking once anything
before it changes. Old screenshots are cleared server-side with context
editing instead.
"""

import base64
import threading
import time

import addonHandler
import wx
import winUser
from logHandler import log

from .. import apirequest
from . import inputhandler, speechcapture
from .screen import Display

addonHandler.initTranslation()

MODE_ASSIST = "assist"
MODE_TESTING = "testing"

TOOLSET = "computer"
TOOLSET_TYPE = "computer_toolset_20260801"
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"
THINKING_UPDATES_BETA = "thinking-display-updates-2026-08-18"

# Once the conversation passes this many input tokens, the results of all but
# the most recent actions are cleared on the server, at least this many at a
# time so each clearing is worth the cache write it causes.
_CLEAR_TRIGGER_TOKENS = 50000
_CLEAR_AT_LEAST_TOKENS = 10000

# Members whose result already shows the screen, or doesn't change it.
_NO_SCREENSHOT_AFTER = frozenset({"screenshot", "zoom", "cursor_position"})

# Fixed strings Claude reads, so not translated.
_NOT_EXECUTED = "Not executed: an earlier computer action in this turn failed."
_CUT_OFF = "Not executed: your response was cut off before this action was complete."
_INTERRUPTED_NOTE = "This part of the response was interrupted before it finished."

# Prompts that steer the model. Deliberately NOT translated: a translated
# instruction would change the model's behaviour per locale.
_BASE_PROMPT = """You are operating a Windows computer on behalf of a blind user who \
uses the NVDA screen reader. You see screenshots of the whole desktop and act through the \
computer tools.

Important guidance:
- Coordinates are in the pixel space of the screenshots you receive.
- Prefer the keyboard (Tab, Shift+Tab, arrow keys, Enter, Space and standard Windows \
shortcuts) over the mouse whenever practical. It is more reliable and matches how the \
user works.
- Before your first action, and whenever your plan changes, write one short sentence \
saying what you are about to do. The user hears these sentences instead of seeing the \
screen, so keep them brief and concrete.
- After acting, check the next screenshot to confirm the action had the effect you \
intended before continuing. If it did not, adjust and try again.
- If text or a control is too small to read, zoom into that region.
- Do not take destructive or consequential actions (deleting data, sending messages, \
making purchases, changing system settings or agreeing to terms) unless the user \
explicitly asked for them. When in doubt, stop and explain what you would do instead.
- When the task is complete, stop acting and give a short plain-language summary of what \
you did and the final state of the screen."""

_ASSIST_PROMPT = """You are helping the user with a specific task on their screen, such \
as reaching or operating a control they are stuck on. Complete the request efficiently, \
verify the result on screen, then report what happened."""

_TESTING_PROMPT = """You are acting as a screen-reader accessibility tester. Each action \
result includes the exact text NVDA announced because of that action, after \
"NVDA announced:". Treat that text as what a blind user would hear.

Navigate primarily with the keyboard. As you go, evaluate the accessibility of the \
interface: do controls have accessible names? Are roles and states announced (button, \
checkbox checked or not checked, expanded or collapsed, and so on)? Is the focus order \
logical? Do images have meaningful text alternatives? Are errors and status changes \
announced? When you have finished exploring, produce a clear, structured accessibility \
report: what works well, and each issue you found with the element involved and exactly \
what NVDA did or did not announce."""


def system_prompt(mode: str) -> str:
    return "\n\n".join((_BASE_PROMPT, _TESTING_PROMPT if mode == MODE_TESTING else _ASSIST_PROMPT))


# The running or paused session, so a global gesture can pause or stop it.
_active_session = None


def stop_active_session() -> bool:
    """Stop any active session (running or paused). Returns whether one existed."""
    session = _active_session
    if session is not None and (session.is_running() or session.is_paused()):
        session.stop()
        return True
    return False


def pause_active_session() -> bool:
    """Ask a running session to pause, keeping its context. Returns whether one was running."""
    session = _active_session
    if session is not None and session.is_running():
        session.pause()
        return True
    return False


def is_session_paused() -> bool:
    session = _active_session
    return session is not None and session.is_paused()


class Session:
    """One computer use conversation with Claude.

    :param report: ``report(kind, text)``, called from the worker thread with
        progress. ``kind`` is ``"assistant"`` (Claude's reply), ``"progress"``
        (a note written between actions), ``"action"``, ``"status"``,
        ``"error"``, ``"paused"``, ``"finished"`` (done, but a follow-up can
        continue the conversation) or ``"done"`` (the session is discarded).
    :param settings: a snapshot of the ``computerUse`` config section.
    """

    def __init__(self, prompt: str, mode: str, report, client, model, settings: dict):
        self._prompt = prompt
        self._mode = mode
        self._report = report
        self._client = client
        self._model = model
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = None
        self._running = False
        self._paused = False
        # Built on the first run, then kept across pauses and follow-ups.
        self._messages = None
        self._pending_prompt = ""

        self._effort = settings["effort"]
        self._max_steps = settings["maxSteps"]
        self._max_tokens = min(settings["maxTokens"], model.max_output_tokens)
        self._action_delay = settings["actionDelay"] / 1000.0
        self._speech_settle_delay = settings["speechSettleDelay"] / 1000.0
        self._keep_actions = settings["keepActions"]
        self._enable_zoom = settings["enableZoom"]
        # The screenshot size is fixed for the whole conversation: Claude's
        # coordinates refer to it.
        self._display = Display(settings["maxScreenshotEdge"])

    # -- lifecycle ---------------------------------------------------------

    def _start_thread(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="ClauVDAComputerUse", daemon=True)
        self._thread.start()

    def start(self) -> None:
        speechcapture.register()
        self._start_thread()

    def stop(self) -> None:
        """End the session for good. Works while running or paused."""
        self._stop.set()
        # Wake any interruptible sleep so a running turn returns promptly.
        self._pause.set()
        if self._paused and not self._running:
            self._finish()

    def pause(self) -> None:
        """Pause at the next safe point, keeping the conversation."""
        self._pause.set()

    def resume(self, guidance: str = "") -> None:
        """Resume a paused session, optionally with new guidance for Claude."""
        if not self._paused or self._stop.is_set():
            return
        guidance = (guidance or "").strip()
        if guidance:
            self._add_user_content([{"type": "text", "text": guidance}])
        elif self._messages and self._messages[-1]["role"] == "assistant":
            # The request must end with a user turn.
            self._add_user_content([{"type": "text", "text": "Continue."}])
        self._pause.clear()
        self._paused = False
        self._start_thread()

    def can_continue(self) -> bool:
        """Whether the task ended but its conversation can take a follow-up."""
        return (
            not self._running
            and not self._paused
            and not self._stop.is_set()
            and self._messages is not None
        )

    def continue_task(self, prompt: str) -> None:
        """Send a follow-up request to a finished task, keeping its context."""
        prompt = (prompt or "").strip()
        if not prompt or not self.can_continue():
            return
        self._pending_prompt = prompt
        self._start_thread()

    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def _add_user_content(self, blocks: list) -> None:
        """Add to the trailing user turn (not sent yet), or open a new one.

        User text goes after the tool results of the same user turn, never
        inside a tool result, so Claude treats it as the user speaking.
        """
        last = self._messages[-1] if self._messages else None
        if last is not None and last["role"] == "user" and isinstance(last["content"], list):
            last["content"].extend(blocks)
        else:
            self._messages.append({"role": "user", "content": blocks})

    # -- threading helpers -------------------------------------------------

    def _run_on_main(self, func, *args):
        """Run ``func`` on NVDA's main thread and return its result."""
        if wx.IsMainThread():
            return func(*args)
        holder = {}
        done = threading.Event()

        def wrapper():
            try:
                holder["result"] = func(*args)
            except Exception as error:  # re-raised on the worker thread
                holder["error"] = error
            finally:
                done.set()

        wx.CallAfter(wrapper)
        done.wait()
        if "error" in holder:
            raise holder["error"]
        return holder.get("result")

    def _sleep(self, seconds: float) -> None:
        """Sleep, waking early on stop or pause."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._stop.is_set() and not self._pause.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    # -- the loop ----------------------------------------------------------

    def _run(self) -> None:
        global _active_session
        _active_session = self
        try:
            outcome = self._loop()
        except Exception as error:
            log.error("ClauVDA computer use session failed", exc_info=True)
            # Translators: Reported when computer use fails unexpectedly
            self._report("error", _("Something went wrong: {error}").format(error=error))
            outcome = "failed"
        self._running = False
        if self._stop.is_set() or outcome == "failed":
            self._finish()
        elif outcome == "paused":
            # Keep the session so the user can add guidance and resume.
            self._paused = True
            self._report(
                "paused",
                # Translators: Announced when a computer use task is paused
                _("Paused. Type any new guidance for Claude in the dialog, then press Resume to continue."),
            )
        else:
            self._complete_task()

    def _complete_task(self) -> None:
        """End the run but keep the conversation for follow-up requests."""
        global _active_session
        self._paused = False
        if _active_session is self:
            _active_session = None
        self._report(
            "finished",
            # Translators: Announced when a computer use task is complete
            _("Finished. Type a follow-up request and press Continue, or press New task to start over."),
        )

    def _finish(self) -> None:
        """End the session for good."""
        global _active_session
        self._running = False
        self._paused = False
        if _active_session is self:
            _active_session = None
        # Translators: Announced when a computer use session ends
        self._report("done", _("Finished."))

    def _loop(self) -> str:
        """Prepare the next user turn, then run turns. Returns the outcome."""
        if self._messages is None:
            # Open with the request and a screenshot, text first: that improves
            # targeting. Give the target window a moment to come forward.
            self._sleep(0.2)
            shot = self._image_block(self._run_on_main(self._display.capture))
            self._messages = [{"role": "user", "content": [{"type": "text", "text": self._prompt}, shot]}]
        elif self._pending_prompt:
            # A follow-up: the screen may have changed since the task ended.
            self._sleep(0.2)
            shot = self._image_block(self._run_on_main(self._display.capture))
            self._add_user_content([{"type": "text", "text": self._pending_prompt}, shot])
            self._pending_prompt = ""
        # Translators: Announced when computer use starts working
        self._report("status", _("Working…"))
        return self._run_turns()

    def _request_kwargs(self) -> dict:
        toolset = {"type": TOOLSET_TYPE}
        if not self._enable_zoom:
            toolset["configs"] = {"zoom": {"enabled": False}}
        betas = [CONTEXT_MANAGEMENT_BETA]
        kwargs = {
            "model": self._model.resolve_id("anthropic"),
            "max_tokens": self._max_tokens,
            "system": system_prompt(self._mode),
            "tools": [toolset],
            "messages": self._messages,
            "output_config": {"effort": self._effort},
            # Each turn reads the previous turn's prefix from cache.
            "cache_control": {"type": "ephemeral"},
            "context_management": {
                "edits": [
                    {
                        "type": "clear_tool_uses_20250919",
                        "trigger": {"type": "input_tokens", "value": _CLEAR_TRIGGER_TOKENS},
                        "keep": {"type": "tool_uses", "value": self._keep_actions},
                        "clear_at_least": {"type": "input_tokens", "value": _CLEAR_AT_LEAST_TOKENS},
                    }
                ]
            },
        }
        if self._model.progress_updates:
            # Notes written between actions come back as thinking blocks that
            # are empty unless asked for as updates.
            kwargs["thinking"] = {"type": "adaptive", "display": "updates"}
            betas.append(THINKING_UPDATES_BETA)
        kwargs["betas"] = betas
        return kwargs

    def _create_message(self):
        """Stream one turn (large max_tokens needs streaming); None if stopped."""
        with self._client.beta.messages.stream(**self._request_kwargs()) as stream:
            for _event in stream:
                if self._stop.is_set():
                    return None
            return stream.get_final_message()

    def _run_turns(self) -> str:
        import anthropic

        for _step in range(self._max_steps):
            if self._stop.is_set():
                # Translators: Announced when the user stops a computer use task
                self._report("status", _("Stopped."))
                return "stopped"
            if self._pause.is_set():
                # Only pause between turns, where the conversation ends on a
                # complete user turn and stays valid.
                return "paused"
            try:
                response = self._create_message()
            except anthropic.APIError as error:
                log.warning(f"Computer use request failed: {error}")
                # Translators: Reported when a computer use request fails; the task can be resumed
                self._report("error", _("Claude API error: {error}").format(error=error))
                # The conversation is unchanged, so the turn can be retried.
                return "paused"
            if response is None:
                self._report("status", _("Stopped."))
                return "stopped"

            self._messages.append({"role": "assistant", "content": response.content})
            if apirequest.is_refusal(response):
                self._report("error", apirequest.refusal_message())
                return "finished"
            if response.stop_reason == "pause_turn":
                continue
            cut_off = response.stop_reason in ("max_tokens", "model_context_window_exceeded")
            # Run the whole batch even if a pause arrived mid-turn: every
            # tool_use needs its tool_result for the conversation to stay valid.
            results = self._handle_response(response, cut_off)
            if results:
                self._messages.append({"role": "user", "content": results})
            if self._stop.is_set():
                self._report("status", _("Stopped."))
                return "stopped"
            if cut_off:
                self._report(
                    "status",
                    # Translators: Reported when Claude's computer use turn hit its token limit
                    _(
                        "Claude's reply was cut off. Raise the maximum tokens per step in the "
                        "Claude AI settings, or press Resume to let it try again."
                    ),
                )
                return "paused"
            if not results:
                return "finished"

        # Translators: Reported when a computer use task reaches its step limit
        self._report("status", _("Reached the maximum number of steps."))
        # The conversation ends on a complete user turn, so the user can resume
        # with a fresh step budget instead of losing the task.
        return "paused"

    def _handle_response(self, response, cut_off: bool) -> list:
        """Report Claude's notes, run the requested actions in order, return results."""
        results = []
        failed = False
        last_executed = None
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "thinking":
                # Under display "updates", a thinking block with text is a
                # progress note; reasoning itself stays hidden.
                note = (getattr(block, "thinking", "") or "").strip()
                if note and note != _INTERRUPTED_NOTE:
                    self._report("progress", note)
            elif block_type == "text":
                text = block.text.strip()
                if text:
                    self._report("assistant", text)
            elif block_type == "tool_use":
                result = {"type": "tool_result", "tool_use_id": block.id, "toolset_name": TOOLSET}
                if cut_off:
                    result.update(content=_CUT_OFF, is_error=True)
                elif failed or self._stop.is_set():
                    result.update(content=_NOT_EXECUTED, is_error=True)
                elif getattr(block, "toolset_name", None) != TOOLSET:
                    result.update(content=f"Error: unknown tool {block.name}", is_error=True)
                    failed = True
                else:
                    try:
                        result["content"] = self._run_action(block.name, block.input or {})
                        last_executed = block.name
                    except Exception as error:
                        log.debugWarning("Computer use action failed", exc_info=True)
                        # Translators: Reported when an action Claude asked for could not run
                        self._report("error", _("Action failed: {error}").format(error=error))
                        result.update(content=f"Error: {error}", is_error=True)
                        failed = True
                results.append(result)
        if results and not failed and not cut_off and last_executed not in (None, *_NO_SCREENSHOT_AFTER):
            # Claude usually ends a batch with a screenshot; when it didn't,
            # show it the result of its last action.
            last = results[-1]
            if isinstance(last.get("content"), str):
                last["content"] = [{"type": "text", "text": last["content"]}]
            last["content"].append(self._image_block(self._run_on_main(self._display.capture)))
        return results

    # -- actions -----------------------------------------------------------

    def _image_block(self, png: bytes) -> dict:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode("ascii"),
            },
        }

    def _perform(self, func) -> str:
        """Run an input action on the main thread and describe its outcome."""
        testing = self._mode == MODE_TESTING
        if testing:
            speechcapture.begin_capture()
        try:
            self._run_on_main(func)
            self._sleep(self._action_delay)
            if testing:
                self._sleep(self._speech_settle_delay)
        finally:
            spoken = speechcapture.end_capture().strip() if testing else None
        if testing:
            return "OK. NVDA announced: " + (spoken or "(nothing was spoken)")
        return "OK"

    def _run_action(self, name: str, inp: dict):
        self._report("action", _describe_action(name, inp))
        display = self._display
        if name == "screenshot":
            return [self._image_block(self._run_on_main(display.capture))]
        if name == "zoom":
            return [self._image_block(self._run_on_main(display.capture_region, inp["region"]))]
        if name == "cursor_position":
            x, y = display.to_image(*self._run_on_main(winUser.getCursorPos))
            return f"X={x}, Y={y}"
        if name == "wait":
            self._sleep(min(float(inp.get("duration", 1)), 300.0))
            return "OK"
        coordinate = inp.get("coordinate")
        modifiers = inp.get("text")
        if name in ("left_click", "right_click", "middle_click"):
            button = name.split("_")[0]
            return self._perform(lambda: inputhandler.click(display, coordinate, button, 1, modifiers))
        if name in ("double_click", "triple_click"):
            count = 2 if name == "double_click" else 3
            return self._perform(lambda: inputhandler.click(display, coordinate, "left", count, modifiers))
        if name == "mouse_move":
            return self._perform(lambda: inputhandler.move_cursor(display, inp["coordinate"]))
        if name == "left_click_drag":
            start = inp["start_coordinate"]
            return self._perform(lambda: inputhandler.drag(display, start, inp["coordinate"], modifiers))
        if name == "left_mouse_down":
            return self._perform(lambda: inputhandler.mouse_down(display, coordinate))
        if name == "left_mouse_up":
            return self._perform(lambda: inputhandler.mouse_up(display, coordinate))
        if name == "scroll":
            direction = inp.get("scroll_direction", "down")
            amount = inp.get("scroll_amount", 3)
            return self._perform(
                lambda: inputhandler.scroll(display, coordinate, direction, amount, modifiers)
            )
        if name == "key":
            repeat = inp.get("repeat", 1)
            return self._perform(lambda: inputhandler.press_key(inp["text"], repeat))
        if name == "type":
            return self._perform(lambda: inputhandler.type_text(inp["text"]))
        if name == "hold_key":
            return self._hold_key(inp["text"], min(float(inp.get("duration", 1)), 300.0))
        raise ValueError(f"Unsupported computer action: {name}")

    def _hold_key(self, combo: str, duration: float) -> str:
        testing = self._mode == MODE_TESTING
        if testing:
            speechcapture.begin_capture()
        try:
            gesture = self._run_on_main(inputhandler.key_combo_down, combo)
            try:
                self._sleep(duration)
            finally:
                self._run_on_main(inputhandler.key_combo_up, gesture)
            self._sleep(self._action_delay)
            if testing:
                self._sleep(self._speech_settle_delay)
        finally:
            spoken = speechcapture.end_capture().strip() if testing else None
        if testing:
            return "OK. NVDA announced: " + (spoken or "(nothing was spoken)")
        return "OK"


def _describe_action(name: str, inp: dict) -> str:
    """A short, translated description of an action for the activity log."""
    coordinate = inp.get("coordinate")
    if name == "screenshot":
        # Translators: Activity log entry: Claude took a screenshot
        return _("Taking a screenshot")
    if name == "zoom":
        # Translators: Activity log entry: Claude zoomed into part of the screen
        return _("Zooming in to read detail")
    if name == "wait":
        # Translators: Activity log entry: Claude waited
        return _("Waiting")
    if name == "cursor_position":
        # Translators: Activity log entry: Claude checked the pointer position
        return _("Checking the pointer position")
    if name == "type":
        # Translators: Activity log entry: Claude typed text. {text} is the text
        return _("Typing: {text}").format(text=inp.get("text", ""))
    if name == "key":
        # Translators: Activity log entry: Claude pressed keys. {keys} is the key combination
        return _("Pressing {keys}").format(keys=inp.get("text", ""))
    if name == "hold_key":
        # Translators: Activity log entry: Claude held keys. {keys} is the key combination
        return _("Holding {keys}").format(keys=inp.get("text", ""))
    if name == "scroll":
        directions = {
            # Translators: Scroll direction, used in "Scrolling {direction}"
            "up": _("up"),
            # Translators: Scroll direction, used in "Scrolling {direction}"
            "down": _("down"),
            # Translators: Scroll direction, used in "Scrolling {direction}"
            "left": _("left"),
            # Translators: Scroll direction, used in "Scrolling {direction}"
            "right": _("right"),
        }
        direction = inp.get("scroll_direction", "")
        # Translators: Activity log entry: Claude scrolled. {direction} is up, down, left or right
        return _("Scrolling {direction}").format(direction=directions.get(direction, direction))
    if name in ("left_click", "double_click", "triple_click") and coordinate:
        # Translators: Activity log entry: Claude clicked. {x} and {y} are coordinates
        return _("Clicking at {x}, {y}").format(x=coordinate[0], y=coordinate[1])
    if name in ("left_click", "double_click", "triple_click"):
        # Translators: Activity log entry: Claude clicked where the pointer already was
        return _("Clicking")
    if name == "right_click":
        # Translators: Activity log entry: Claude right-clicked
        return _("Right-clicking")
    if name == "middle_click":
        # Translators: Activity log entry: Claude middle-clicked
        return _("Middle-clicking")
    if name == "mouse_move" and coordinate:
        # Translators: Activity log entry: Claude moved the pointer. {x} and {y} are coordinates
        return _("Moving the pointer to {x}, {y}").format(x=coordinate[0], y=coordinate[1])
    if name in ("left_click_drag", "left_mouse_down", "left_mouse_up"):
        # Translators: Activity log entry: Claude dragged with the mouse
        return _("Dragging")
    # Translators: Activity log entry for any other action. {action} is its name
    return _("Performing action: {action}").format(action=name)
