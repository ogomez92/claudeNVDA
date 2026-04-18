# ClauVDA NVDA Add-on - Main Dialog
# -*- coding: utf-8 -*-

import os
import sys
import threading
import base64
import time
import wx
import winsound

import addonHandler
import config
import ui
import braille
import speech
from logHandler import log
from gui import guiHelper

addonHandler.initTranslation()

from .consts import (
    DATA_DIR,
    LIBS_DIR,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_SCREENSHOT_PROMPT,
    DEFAULT_OBJECT_PROMPT,
    CLAUDE_MODELS,
    get_model_by_id,
    get_model_choices,
    SND_CHAT_REQUEST_SENT,
    SND_CHAT_RESPONSE_PENDING,
    SND_CHAT_RESPONSE_RECEIVED,
)
from .configspec import get_safe_conf
from .resultevent import EVT_RESULT, ResultEvent
from .mdfilter import filter_markdown
from . import videocapture

# Add lib directory to path for anthropic
if LIBS_DIR not in sys.path:
    sys.path.insert(0, LIBS_DIR)

try:
    import anthropic  # noqa: F401
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    log.warning("anthropic SDK not available. Bundled libraries may be missing or corrupted.")

# Global reference to active dialog for adding images
addToSession = None

# Configuration reference
conf = None


# Supported video formats — for each we extract still frames.
SUPPORTED_VIDEO_EXTS = {".mp4", ".mpeg", ".mpg", ".mov", ".avi", ".webm", ".wmv", ".flv", ".3gp", ".3gpp"}

# Image MIME types accepted by Claude.
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class HistoryBlock:
    """Represents a message in the conversation history."""

    def __init__(self, role: str, text: str = "", images: list = None, videos: list = None):
        self.role = role  # "user" or "assistant"
        self.text = text
        self.images = images or []  # list of image paths (model sees base64 at send time)
        # For ClauVDA we don't keep uploaded-file references; videos are flattened to frame image paths.
        self.video_frames = videos or []
        self.focused = False


def _encode_image(path: str) -> dict | None:
    """Read an image file and return an Anthropic image content block."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lower()
        media_type = IMAGE_MIME_TYPES.get(ext, "image/jpeg")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
    except Exception as e:
        log.error(f"Error encoding image {path}: {e}")
        return None


def _response_text(response) -> str:
    """Extract plain text from a Claude Message response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


class CompletionThread(threading.Thread):
    """Background thread for Anthropic API calls."""

    def __init__(
        self,
        notify_window,
        client,
        model_id: str,
        messages: list,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        stream: bool = True,
    ):
        threading.Thread.__init__(self, daemon=True)
        self._notify_window = notify_window
        self._client = client
        self._model_id = model_id
        self._messages = messages
        self._system_prompt = system_prompt or None
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._stream = stream
        self._stop_event = threading.Event()

    def _build_kwargs(self):
        kwargs = {
            "model": self._model_id,
            "messages": self._messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt
        return kwargs

    def _safe_post_event(self, data):
        """Safely post event to window, handling case where window is destroyed."""
        try:
            if self._notify_window and not self._stop_event.is_set():
                wx.PostEvent(self._notify_window, ResultEvent(data))
        except RuntimeError:
            # Window was destroyed
            pass

    def run(self):
        try:
            if self._stream:
                self._run_streaming()
            else:
                self._run_sync()
        except Exception as e:
            log.error(f"Anthropic API error: {e}", exc_info=True)
            self._safe_post_event({"error": str(e)})

    def _run_streaming(self):
        response_text = ""
        try:
            with self._client.messages.stream(**self._build_kwargs()) as stream:
                for delta in stream.text_stream:
                    if self._stop_event.is_set():
                        break
                    if delta:
                        response_text += delta
                        self._safe_post_event({"chunk": delta, "done": False})

            self._safe_post_event({"text": response_text, "done": True})
        except Exception as e:
            log.error(f"Streaming error: {e}", exc_info=True)
            self._safe_post_event({"error": str(e)})

    def _run_sync(self):
        try:
            response = self._client.messages.create(**self._build_kwargs())
            self._safe_post_event({"text": _response_text(response), "done": True})
        except Exception as e:
            log.error(f"Sync error: {e}", exc_info=True)
            self._safe_post_event({"error": str(e)})

    def stop(self):
        self._stop_event.set()


class ClaudeDialog(wx.Dialog):
    """Main dialog for interacting with Claude."""

    def __init__(self, parent, client, conf_ref):
        global addToSession, conf
        conf = conf_ref

        # Translators: Title of the main Claude dialog
        title = _("Claude AI")
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )

        self._client = client
        self._conf = conf_ref
        self._history: list[HistoryBlock] = []
        self._current_thread: CompletionThread | None = None
        self._pending_images: list[str] = []  # Paths to images to send
        self._pending_videos: list[str] = []  # Paths to videos to send
        self._pending_video_frames: list[str] = []  # Extracted frame paths ready to send

        # For double-press detection on Alt+number keys
        self._last_message_key: int | None = None
        self._last_message_key_time: float = 0.0
        self._DOUBLE_PRESS_THRESHOLD = 0.5  # seconds

        # Track streaming state for speech
        self._received_streaming_chunks = False

        # Track current prompt type for saving (screenshot, object, or None)
        self._current_prompt_type: str | None = None

        self._init_ui()
        self._bind_events()

        # Only expose the dialog globally after it's fully initialized
        addToSession = self

        self.SetSize((800, 600))
        self.CenterOnParent()

    def focus_prompt(self):
        """Focus the prompt text field and raise the dialog."""
        try:
            self.Raise()
            self.SetFocus()
            self._prompt_text.SetFocus()
        except RuntimeError:
            # Dialog may have been destroyed
            pass

    def _init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Model selection
        model_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Label for model selection dropdown
        model_label = wx.StaticText(panel, label=_("M&odel:"))
        model_sizer.Add(model_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        model_choices = [m.name for m in CLAUDE_MODELS]
        self._model_choice = wx.Choice(panel, choices=model_choices)

        # Set default model
        current_model = get_safe_conf()["model"]
        for i, m in enumerate(CLAUDE_MODELS):
            if m.id == current_model:
                self._model_choice.SetSelection(i)
                break
        else:
            self._model_choice.SetSelection(0)

        model_sizer.Add(self._model_choice, 1, wx.EXPAND)
        main_sizer.Add(model_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # System prompt
        # Translators: Label for system prompt section
        system_label = wx.StaticText(panel, label=_("S&ystem prompt:"))
        main_sizer.Add(system_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._system_text = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE,
            size=(-1, 60),
        )
        # If saveSystemPrompt is enabled, use the saved value (even if blank)
        # Otherwise, use the default system prompt
        if get_safe_conf()["saveSystemPrompt"]:
            self._system_text.SetValue(get_safe_conf()["customSystemPrompt"])
        else:
            self._system_text.SetValue(DEFAULT_SYSTEM_PROMPT)
        main_sizer.Add(self._system_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Messages display
        # Translators: Label for conversation messages
        messages_label = wx.StaticText(panel, label=_("&Messages:"))
        main_sizer.Add(messages_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._history_text = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        main_sizer.Add(self._history_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Prompt input
        # Translators: Label for user prompt input
        prompt_label = wx.StaticText(panel, label=_("&Prompt:"))
        main_sizer.Add(prompt_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._prompt_text = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE,
            size=(-1, 80),
        )
        main_sizer.Add(self._prompt_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Image indicator
        self._image_label = wx.StaticText(panel, label="")
        main_sizer.Add(self._image_label, 0, wx.LEFT | wx.RIGHT, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Translators: Button to send message
        self._send_btn = wx.Button(panel, label=_("&Send"))
        self._send_btn.SetDefault()
        button_sizer.Add(self._send_btn, 0, wx.RIGHT, 5)

        # Translators: Button to attach image
        self._image_btn = wx.Button(panel, label=_("Attach &Image..."))
        button_sizer.Add(self._image_btn, 0, wx.RIGHT, 5)

        # Translators: Button to attach video
        self._video_btn = wx.Button(panel, label=_("Attach &Video..."))
        button_sizer.Add(self._video_btn, 0, wx.RIGHT, 5)

        # Translators: Button to clear conversation
        self._clear_btn = wx.Button(panel, label=_("&Clear"))
        button_sizer.Add(self._clear_btn, 0, wx.RIGHT, 5)

        # Translators: Button to copy last response
        self._copy_btn = wx.Button(panel, label=_("C&opy Response"))
        button_sizer.Add(self._copy_btn, 0, wx.RIGHT, 5)

        button_sizer.AddStretchSpacer()

        # Translators: Button to close dialog
        self._close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        button_sizer.Add(self._close_btn, 0)

        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(main_sizer)

    def _bind_events(self):
        self._send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        self._image_btn.Bind(wx.EVT_BUTTON, self._on_attach_image)
        self._video_btn.Bind(wx.EVT_BUTTON, self._on_attach_video)
        self._clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        self._copy_btn.Bind(wx.EVT_BUTTON, self._on_copy_response)
        self._close_btn.Bind(wx.EVT_BUTTON, self._on_close)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        EVT_RESULT(self, self._on_result)

    def _on_key(self, event):
        key = event.GetKeyCode()

        # Ctrl+Enter to send
        if key == wx.WXK_RETURN and event.ControlDown():
            self._on_send(None)
            return

        # Escape to close (if not blocked)
        if key == wx.WXK_ESCAPE:
            if not get_safe_conf()["blockEscapeKey"]:
                self._on_close(None)
                return

        # Alt+1 through Alt+0 to read/copy messages
        if event.AltDown() and not event.ControlDown() and not event.ShiftDown():
            # Check for number keys (0-9)
            # wx.WXK_NUMPAD0-9 for numpad, ord('0')-ord('9') for main keyboard
            message_index = None

            if ord('1') <= key <= ord('9'):
                message_index = key - ord('1')  # 0-8 for keys 1-9
            elif key == ord('0'):
                message_index = 9  # 9 for key 0 (10th message)
            elif wx.WXK_NUMPAD1 <= key <= wx.WXK_NUMPAD9:
                message_index = key - wx.WXK_NUMPAD1  # 0-8 for numpad 1-9
            elif key == wx.WXK_NUMPAD0:
                message_index = 9  # 9 for numpad 0 (10th message)

            if message_index is not None:
                current_time = time.time()
                is_double_press = (
                    self._last_message_key == key and
                    (current_time - self._last_message_key_time) < self._DOUBLE_PRESS_THRESHOLD
                )

                if is_double_press:
                    # Double press - copy to clipboard
                    self._copy_message_by_index(message_index)
                    self._last_message_key = None
                    self._last_message_key_time = 0.0
                else:
                    # Single press - read message
                    self._read_message_by_index(message_index)
                    self._last_message_key = key
                    self._last_message_key_time = current_time
                return

        event.Skip()

    def _format_message(self, block: HistoryBlock) -> str:
        """Format a single message for reading or copying."""
        text = block.text or ""
        if get_safe_conf()["filterMarkdown"]:
            text = filter_markdown(text)

        # Translators: Label for user messages when reading history
        # Translators: Label for Claude messages when reading history
        role_label = _("You") if block.role == "user" else _("Claude")
        return _("{role}: {text}").format(role=role_label, text=text)

    def _read_message_by_index(self, index: int):
        """Read the message at the given index (0 = most recent)."""
        if not self._history:
            # Translators: Message when there are no messages in history
            ui.message(_("No messages in history"))
            return

        # Get messages in reverse order (most recent first)
        reversed_history = list(reversed(self._history))

        if index >= len(reversed_history):
            # Translators: Message when requested message doesn't exist
            ui.message(_("Message {num} not available. Only {total} message(s) in history.").format(
                num=index + 1,
                total=len(reversed_history)
            ))
            return

        block = reversed_history[index]
        message_text = self._format_message(block)

        if message_text.strip():
            self._speak_long_text(message_text)
        else:
            # Translators: Message when the selected message is empty
            ui.message(_("Message {num} is empty").format(num=index + 1))

    def _copy_message_by_index(self, index: int):
        """Copy the message at the given index to clipboard."""
        import api as nvda_api

        if not self._history:
            # Translators: Message when there are no messages to copy
            ui.message(_("No messages to copy"))
            return

        # Get messages in reverse order (most recent first)
        reversed_history = list(reversed(self._history))

        if index >= len(reversed_history):
            # Translators: Message when requested message for copying doesn't exist
            ui.message(_("Message {num} not available. Only {total} message(s) in history.").format(
                num=index + 1,
                total=len(reversed_history)
            ))
            return

        block = reversed_history[index]
        # For copying, just copy the text content without the role label
        text = block.text or ""
        if get_safe_conf()["filterMarkdown"]:
            text = filter_markdown(text)

        if text.strip():
            nvda_api.copyToClip(text)
            # Translators: Message when a message is copied to clipboard
            ui.message(_("Message {num} copied to clipboard").format(num=index + 1))
        else:
            # Translators: Message when the selected message is empty and cannot be copied
            ui.message(_("Message {num} is empty, nothing to copy").format(num=index + 1))

    def _on_send(self, event):
        prompt = self._prompt_text.GetValue().strip()
        if (
            not prompt
            and not self._pending_images
            and not self._pending_videos
            and not self._pending_video_frames
        ):
            return

        # Extract frames from any pending videos first
        if self._pending_videos:
            self._send_btn.Disable()
            self._video_btn.Disable()
            # Translators: Message while extracting frames from videos
            ui.message(_("Extracting video frames..."))
            threading.Thread(
                target=self._extract_videos_and_send,
                args=(prompt,),
                daemon=True,
            ).start()
            return

        # Get selected model
        model_idx = self._model_choice.GetSelection()
        model = CLAUDE_MODELS[model_idx]
        provider = get_safe_conf()["authProvider"]
        resolved_id = model.resolve_id(provider)

        # Collect conversation history as Anthropic messages
        messages = []

        if get_safe_conf()["conversationMode"]:
            for block in self._history:
                content_parts = []
                for img_path in block.images:
                    if isinstance(img_path, str):
                        part = _encode_image(img_path)
                        if part:
                            content_parts.append(part)
                for frame_path in block.video_frames:
                    if isinstance(frame_path, str):
                        part = _encode_image(frame_path)
                        if part:
                            content_parts.append(part)
                if block.text:
                    content_parts.append({"type": "text", "text": block.text})

                if content_parts:
                    messages.append({"role": block.role, "content": content_parts})

        # Build current message content
        current_parts = []
        for img_path in self._pending_images:
            part = _encode_image(img_path)
            if part:
                current_parts.append(part)
        for frame_path in self._pending_video_frames:
            part = _encode_image(frame_path)
            if part:
                current_parts.append(part)
        if prompt:
            current_parts.append({"type": "text", "text": prompt})

        if not current_parts:
            # Nothing to actually send
            self._send_btn.Enable()
            return

        messages.append({"role": "user", "content": current_parts})

        # Add to history
        user_block = HistoryBlock(
            "user",
            prompt,
            self._pending_images.copy(),
            self._pending_video_frames.copy(),
        )
        self._history.append(user_block)
        self._update_history_display()

        # Save prompt if we have a prompt type (screenshot or object)
        if self._current_prompt_type and prompt:
            if self._current_prompt_type == "screenshot":
                get_safe_conf()["screenshotPrompt"] = prompt
            elif self._current_prompt_type == "object":
                get_safe_conf()["objectPrompt"] = prompt
            # Reset prompt type after saving
            self._current_prompt_type = None
            # Save config
            try:
                config.conf.save()
            except Exception:
                pass

        # Clear inputs
        self._prompt_text.SetValue("")
        self._pending_images.clear()
        self._pending_video_frames.clear()
        self._update_attachment_label()

        # Disable send button
        self._send_btn.Disable()

        # Play send sound
        if get_safe_conf()["feedback"]["soundRequestSent"]:
            self._play_sound(SND_CHAT_REQUEST_SENT)

        system_prompt = self._system_text.GetValue().strip()

        # Start completion thread
        self._current_thread = CompletionThread(
            notify_window=self,
            client=self._client,
            model_id=resolved_id,
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=min(get_safe_conf()["maxOutputTokens"], model.max_output_tokens),
            temperature=get_safe_conf()["temperature"],
            stream=get_safe_conf()["stream"],
        )
        self._current_thread.start()

        # Start pending sound
        if get_safe_conf()["feedback"]["soundResponsePending"]:
            self._play_sound(SND_CHAT_RESPONSE_PENDING, loop=True)

    def _on_result(self, event):
        data = event.data

        if "error" in data:
            # Stop pending sound
            winsound.PlaySound(None, winsound.SND_PURGE)

            # Translators: Error message prefix
            error_msg = _("Error: {error}").format(error=data["error"])
            ui.message(error_msg)
            self._send_btn.Enable()
            self._received_streaming_chunks = False
            return

        if "chunk" in data and not data.get("done"):
            # Streaming chunk - append to history display
            if self._history and self._history[-1].role == "assistant":
                self._history[-1].text += data["chunk"]
            else:
                self._history.append(HistoryBlock("assistant", data["chunk"]))
            self._update_history_display()

            # Speak streaming chunk immediately
            if get_safe_conf()["feedback"]["speechResponseReceived"]:
                chunk_text = data["chunk"]
                if chunk_text:
                    # Apply markdown filter if enabled
                    if get_safe_conf()["filterMarkdown"]:
                        chunk_text = filter_markdown(chunk_text)
                    if chunk_text.strip():  # Only speak non-empty chunks
                        self._speak_long_text(chunk_text)

            # Track that we received streaming chunks
            self._received_streaming_chunks = True
            return

        if data.get("done"):
            # Stop pending sound
            winsound.PlaySound(None, winsound.SND_PURGE)

            # Final response
            was_streaming = getattr(self, '_received_streaming_chunks', False)
            if "text" in data:
                if self._history and self._history[-1].role == "assistant":
                    # Already accumulated from streaming
                    pass
                else:
                    self._history.append(HistoryBlock("assistant", data["text"]))

            self._update_history_display()
            self._send_btn.Enable()

            # Play received sound
            if get_safe_conf()["feedback"]["soundResponseReceived"]:
                self._play_sound(SND_CHAT_RESPONSE_RECEIVED)

            # Announce response (only if not streaming, since we already spoke chunks)
            if get_safe_conf()["feedback"]["speechResponseReceived"] and not was_streaming:
                response_text = self._history[-1].text if self._history else ""
                if response_text:
                    # Apply markdown filter if enabled
                    if get_safe_conf()["filterMarkdown"]:
                        response_text = filter_markdown(response_text)
                    # Split into paragraphs to avoid speech synth buffer limits
                    self._speak_long_text(response_text)

            # Update braille
            if get_safe_conf()["feedback"]["brailleAutoFocus"]:
                response_text = self._history[-1].text if self._history else ""
                if response_text:
                    # Apply markdown filter if enabled
                    if get_safe_conf()["filterMarkdown"]:
                        response_text = filter_markdown(response_text)
                    braille.handler.message(response_text)

            # Reset streaming flag for next request
            self._received_streaming_chunks = False

    def _update_history_display(self):
        """Update the history text control."""
        lines = []
        for block in self._history:
            # Translators: Label for user messages in history
            role_label = _("You") if block.role == "user" else _("Claude")
            text = block.text or ""

            # Apply markdown filter to assistant responses if enabled
            if block.role == "assistant" and get_safe_conf()["filterMarkdown"]:
                text = filter_markdown(text)

            # Build attachment indicators
            attachments = []
            if block.images:
                # Translators: Indicator for attached images
                attachments.append(_("{count} image(s)").format(count=len(block.images)))
            if block.video_frames:
                # Translators: Indicator for attached video frames
                attachments.append(_("{count} video frame(s)").format(count=len(block.video_frames)))

            if attachments:
                attachment_text = ", ".join(attachments)
                text = f"[{attachment_text}] {text}"

            lines.append(f"{role_label}: {text}")
            lines.append("")

        self._history_text.SetValue("\n".join(lines))
        # Scroll to end
        self._history_text.SetInsertionPointEnd()

    def _on_attach_image(self, event):
        # Translators: Title of image file selection dialog
        dlg = wx.FileDialog(
            self,
            _("Select Image"),
            wildcard=_("Image files (*.png;*.jpg;*.jpeg;*.gif;*.webp)|*.png;*.jpg;*.jpeg;*.gif;*.webp"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        )

        if dlg.ShowModal() == wx.ID_OK:
            paths = dlg.GetPaths()
            self._pending_images.extend(paths)
            self._update_attachment_label()

        dlg.Destroy()

    def _on_attach_video(self, event):
        extensions = ";".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTS)
        # Translators: Title of video file selection dialog
        dlg = wx.FileDialog(
            self,
            _("Select Video"),
            wildcard=_("Video files ({ext})|{ext}").format(ext=extensions),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        )

        if dlg.ShowModal() == wx.ID_OK:
            paths = dlg.GetPaths()
            self._pending_videos.extend(paths)
            self._update_attachment_label()

        dlg.Destroy()

    def _update_attachment_label(self):
        parts = []
        if self._pending_images:
            # Translators: Label showing number of attached images
            parts.append(_("{count} image(s)").format(count=len(self._pending_images)))
        if self._pending_videos:
            # Translators: Label showing number of videos queued for frame extraction
            parts.append(_("{count} video(s) queued").format(count=len(self._pending_videos)))
        if self._pending_video_frames:
            # Translators: Label showing number of extracted video frames ready to send
            parts.append(_("{count} video frame(s) ready").format(count=len(self._pending_video_frames)))

        if parts:
            self._image_label.SetLabel(", ".join(parts) + _(" attached"))
        else:
            self._image_label.SetLabel("")

    # Keep old name for compatibility
    def _update_image_label(self):
        self._update_attachment_label()

    def _extract_videos_and_send(self, prompt: str):
        """Extract frames from pending videos (background thread), then trigger send."""
        try:
            for video_path in self._pending_videos:
                frame_paths = videocapture.extract_frames(video_path, DATA_DIR, max_frames=12)
                if not frame_paths:
                    wx.CallAfter(
                        ui.message,
                        _("Frame extraction failed: {path}").format(
                            path=os.path.basename(video_path)
                        ),
                    )
                    continue
                self._pending_video_frames.extend(frame_paths)

            self._pending_videos.clear()

            wx.CallAfter(self._update_attachment_label)
            wx.CallAfter(self._video_btn.Enable)
            wx.CallAfter(self._do_send_with_videos, prompt)

        except Exception as e:
            log.error(f"Frame extraction failed: {e}", exc_info=True)
            wx.CallAfter(
                ui.message,
                _("Frame extraction failed: {error}").format(error=str(e)),
            )
            wx.CallAfter(self._send_btn.Enable)
            wx.CallAfter(self._video_btn.Enable)

    def _do_send_with_videos(self, prompt: str):
        """Continue sending after video frames have been extracted."""
        self._prompt_text.SetValue(prompt)
        self._on_send(None)

    def _on_clear(self, event):
        self._history.clear()
        self._pending_images.clear()
        self._pending_videos.clear()
        self._pending_video_frames.clear()
        self._update_history_display()
        self._update_attachment_label()
        self._prompt_text.SetFocus()
        # Translators: Message when conversation is cleared
        ui.message(_("Conversation cleared"))

    def _on_copy_response(self, event):
        if self._history:
            # Find last assistant response
            for block in reversed(self._history):
                if block.role == "assistant" and block.text:
                    import api
                    api.copyToClip(block.text)
                    # Translators: Message when response is copied
                    ui.message(_("Response copied to clipboard"))
                    return

        # Translators: Message when there's no response to copy
        ui.message(_("No response to copy"))

    def _on_close(self, event):
        global addToSession
        addToSession = None

        # Stop any running thread
        if self._current_thread and self._current_thread.is_alive():
            self._current_thread.stop()

        # Stop sounds
        winsound.PlaySound(None, winsound.SND_PURGE)

        # Save system prompt if enabled
        if get_safe_conf()["saveSystemPrompt"]:
            get_safe_conf()["customSystemPrompt"] = self._system_text.GetValue()
            # Trigger config save to persist changes
            try:
                import config
                config.conf.save()
            except Exception:
                pass

        self.Destroy()

    def _speak_long_text(self, text: str):
        """Speak text split into paragraphs to avoid speech synth buffer limits."""
        # Split on double newlines (paragraphs) or single newlines for long text
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        if not paragraphs:
            return
        for paragraph in paragraphs:
            speech.speakText(paragraph)

    def _play_sound(self, path: str, loop: bool = False):
        """Play a sound file."""
        if not os.path.exists(path):
            return
        flags = winsound.SND_ASYNC
        if loop:
            flags |= winsound.SND_LOOP
        try:
            winsound.PlaySound(path, flags)
        except Exception:
            pass

    def add_images(self, paths: list[str], prompt_type: str | None = None):
        """Add images from external source (e.g., screenshot).

        Args:
            paths: List of image file paths to add
            prompt_type: Type of prompt to use - "screenshot", "object", or None
        """
        self._pending_images.extend(paths)
        self._update_attachment_label()

        # Track prompt type for saving later
        self._current_prompt_type = prompt_type

        # Pre-fill prompt if empty and we have a prompt type
        if prompt_type and not self._prompt_text.GetValue().strip():
            if prompt_type == "screenshot":
                saved_prompt = get_safe_conf()["screenshotPrompt"]
                default_prompt = DEFAULT_SCREENSHOT_PROMPT
            elif prompt_type == "object":
                saved_prompt = get_safe_conf()["objectPrompt"]
                default_prompt = DEFAULT_OBJECT_PROMPT
            else:
                saved_prompt = ""
                default_prompt = ""

            # Use saved prompt if available, otherwise use default
            prompt_to_use = saved_prompt if saved_prompt else default_prompt
            if prompt_to_use:
                self._prompt_text.SetValue(prompt_to_use)

        if not self.IsShown():
            self.Show()
        self.Raise()
        self._prompt_text.SetFocus()

    def add_videos(self, paths: list[str]):
        """Add videos from external source (e.g., screen recording)."""
        self._pending_videos.extend(paths)
        self._update_attachment_label()
        if not self.IsShown():
            self.Show()
        self.Raise()
        self._prompt_text.SetFocus()
