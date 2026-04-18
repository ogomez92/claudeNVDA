# ClauVDA NVDA Add-on - Main Plugin
# -*- coding: utf-8 -*-

import os
import sys
import wx

import addonHandler
import globalPluginHandler
import config
import gui
import ui
import api
import speech
import speechViewer
import textInfos
from scriptHandler import script
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog
from gui import guiHelper, nvdaControls
from logHandler import log
from queueHandler import queueFunction, eventQueue
from eventHandler import FocusLossCancellableSpeechCommand

addonHandler.initTranslation()

from .consts import (
    DATA_DIR,
    LIBS_DIR,
    ADDON_DIR,
    NO_API_KEY_MSG,
    CLAUDE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
)
from .configspec import confSpecs, get_safe_conf
from . import apikeymanager
from . import videocapture

# Clear any conflicting modules that might be loaded from NVDA or other addons.
# NVDA or other addons can bundle older versions of these shared libraries.
_modules_to_clear = [
    key for key in list(sys.modules.keys())
    if key.startswith((
        "anthropic",
        "httpx",
        "httpcore",
        "h11",
        "pydantic",
        "pydantic_core",
        "typing_extensions",
        "annotated_types",
        "distro",
        "jiter",
        "boto3",
        "botocore",
        "jmespath",
    ))
]
for mod in _modules_to_clear:
    del sys.modules[mod]
for base_mod in ("typing_extensions", "annotated_types", "distro"):
    if base_mod in sys.modules:
        del sys.modules[base_mod]

# Add lib directory to path for anthropic (at the beginning for priority)
if LIBS_DIR in sys.path:
    sys.path.remove(LIBS_DIR)
sys.path.insert(0, LIBS_DIR)

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
    log.info(f"anthropic SDK loaded successfully from {LIBS_DIR}")
except Exception as e:
    ANTHROPIC_AVAILABLE = False
    import traceback
    log.error(f"anthropic import failed: {e}")
    log.error(f"Full traceback:\n{traceback.format_exc()}")
    log.warning("anthropic SDK not found. Bundled libraries may be missing or corrupted.")


def _resolve_bedrock_region(configured: str | None) -> str:
    """Pick the AWS region for Bedrock.

    Precedence: explicitly configured region > AWS_REGION env var >
    AWS_DEFAULT_REGION env var > hard-coded "us-east-2".
    """
    if configured and configured.strip():
        return configured.strip()
    for var in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        env_val = os.environ.get(var, "").strip()
        if env_val:
            return env_val
    return "us-east-2"


def _build_client():
    """Create an Anthropic client based on the configured auth provider."""
    if not ANTHROPIC_AVAILABLE:
        return None

    conf = get_safe_conf()
    provider = conf["authProvider"]
    key_manager = apikeymanager.get_manager(DATA_DIR)
    api_key = key_manager.get_api_key(provider)
    if not api_key:
        return None

    try:
        if provider == "bedrock":
            region = _resolve_bedrock_region(conf["bedrockRegion"])
            return anthropic.AnthropicBedrock(
                api_key=api_key,
                aws_region=region,
            )
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        log.error(f"Failed to create Anthropic client ({provider}): {e}")
        return None


class APIKeyDialog(wx.Dialog):
    """Dialog for entering the API key for a specific provider."""

    def __init__(self, parent, key_manager: apikeymanager.APIKeyManager, provider: str):
        self._provider = provider
        if provider == "bedrock":
            # Translators: Title of Bedrock key configuration dialog
            title = _("Amazon Bedrock API Key")
        else:
            # Translators: Title of Anthropic key configuration dialog
            title = _("Anthropic API Key")
        super().__init__(parent, title=title)
        self._key_manager = key_manager
        self._init_ui()
        self.CenterOnParent()

    def _init_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        if self._provider == "bedrock":
            # Translators: Instructions for getting a Bedrock bearer token
            instructions = _(
                "Enter your Amazon Bedrock API key (bearer token).\n"
                "Create one at: https://console.aws.amazon.com/bedrock/home#/api-keys"
            )
        else:
            # Translators: Instructions for getting an Anthropic API key
            instructions = _(
                "Enter your Anthropic API key.\n"
                "Get one at: https://console.anthropic.com/settings/keys"
            )
        instr_label = wx.StaticText(panel, label=instructions)
        sizer.Add(instr_label, 0, wx.ALL, 10)

        source = self._key_manager.get_key_source(self._provider)
        # Translators: Shows where API key is currently stored
        source_label = wx.StaticText(
            panel, label=_("Current key source: {source}").format(source=source)
        )
        sizer.Add(source_label, 0, wx.LEFT | wx.RIGHT, 10)

        key_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Label for API key input field
        key_label = wx.StaticText(panel, label=_("API &Key:"))
        key_sizer.Add(key_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        self._key_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD, size=(400, -1))
        current_key = self._key_manager.get_api_key(self._provider) or ""
        if current_key:
            self._key_text.SetValue("*" * 20)
        key_sizer.Add(self._key_text, 1, wx.EXPAND)

        sizer.Add(key_sizer, 0, wx.EXPAND | wx.ALL, 10)

        btn_sizer = wx.StdDialogButtonSizer()

        btn_ok = wx.Button(panel, wx.ID_OK)
        btn_ok.SetDefault()
        btn_sizer.AddButton(btn_ok)

        btn_cancel = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(btn_cancel)

        # Translators: Button to delete saved API key
        btn_delete = wx.Button(panel, label=_("&Delete Key"))
        btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
        sizer.Add(btn_delete, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        self.Fit()

        btn_ok.Bind(wx.EVT_BUTTON, self._on_ok)

    def _on_ok(self, event):
        key = self._key_text.GetValue().strip()
        if key and not key.startswith("*" * 10):
            if self._key_manager.save_api_key(self._provider, key):
                # Translators: Confirmation that API key was saved
                ui.message(_("API key saved"))
            else:
                # Translators: Error saving API key
                ui.message(_("Failed to save API key"))
        self.EndModal(wx.ID_OK)

    def _on_delete(self, event):
        if self._key_manager.delete_api_key(self._provider):
            # Translators: Confirmation that API key was deleted
            ui.message(_("API key deleted"))
            self._key_text.SetValue("")
        else:
            # Translators: Error deleting API key
            ui.message(_("Failed to delete API key"))


class ClauVDASettingsPanel(SettingsPanel):
    """Settings panel for ClauVDA add-on."""

    # Translators: Title of settings panel
    title = _("Claude AI")

    def makeSettings(self, settingsSizer):
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        # Auth provider selection
        # Translators: Label for auth provider selection
        self._provider_choice = sHelper.addLabeledControl(
            _("&API provider:"),
            wx.Choice,
            choices=[_("Anthropic (direct)"), _("Amazon Bedrock")],
        )
        current_provider = get_safe_conf()["authProvider"]
        self._provider_choice.SetSelection(1 if current_provider == "bedrock" else 0)

        # AWS region for Bedrock
        # Translators: Label for AWS region when using Bedrock
        self._region_text = sHelper.addLabeledControl(
            _("AWS &region (Bedrock only):"),
            wx.TextCtrl,
        )
        self._region_text.SetValue(get_safe_conf()["bedrockRegion"])

        # API Key buttons (one per provider)
        # Translators: Label for Anthropic API key configuration button
        self._anthropic_key_btn = sHelper.addItem(
            wx.Button(self, label=_("Configure &Anthropic API Key..."))
        )
        self._anthropic_key_btn.Bind(
            wx.EVT_BUTTON,
            lambda evt: self._open_key_dialog("anthropic"),
        )

        # Translators: Label for Bedrock API key configuration button
        self._bedrock_key_btn = sHelper.addItem(
            wx.Button(self, label=_("Configure &Bedrock API Key..."))
        )
        self._bedrock_key_btn.Bind(
            wx.EVT_BUTTON,
            lambda evt: self._open_key_dialog("bedrock"),
        )

        # Model selection
        model_choices = [m.name for m in CLAUDE_MODELS]
        # Translators: Label for default model selection
        self._model_choice = sHelper.addLabeledControl(
            _("Default &model:"),
            wx.Choice,
            choices=model_choices,
        )
        current_model = get_safe_conf()["model"]
        for i, m in enumerate(CLAUDE_MODELS):
            if m.id == current_model:
                self._model_choice.SetSelection(i)
                break

        # Bedrock model ID overrides (one text field per model)
        # Translators: Group label for per-model Bedrock IDs
        bedrock_group = wx.StaticBoxSizer(
            wx.VERTICAL, self, label=_("Bedrock model IDs")
        )
        bedrock_box = bedrock_group.GetStaticBox()
        bedrock_helper = guiHelper.BoxSizerHelper(self, sizer=bedrock_group)
        self._bedrock_id_fields: dict[str, wx.TextCtrl] = {}
        for m in CLAUDE_MODELS:
            field = bedrock_helper.addLabeledControl(
                # Translators: Label for the Bedrock ID of a specific model.
                # {name} is the human-readable model name.
                _("{name}:").format(name=m.name),
                wx.TextCtrl,
            )
            saved = get_safe_conf()["bedrockModelOverrides"][m.id]
            field.SetValue(saved if saved else m.bedrock_id)
            self._bedrock_id_fields[m.id] = field
        sHelper.addItem(bedrock_group)

        # Temperature
        # Translators: Label for temperature setting
        self._temp_spinner = sHelper.addLabeledControl(
            _("&Temperature (0-100):"),
            nvdaControls.SelectOnFocusSpinCtrl,
            min=0,
            max=100,
        )
        self._temp_spinner.SetValue(int(get_safe_conf()["temperature"] * 100))

        # Max output tokens
        # Translators: Label for max output tokens setting
        self._max_tokens_spinner = sHelper.addLabeledControl(
            _("Ma&x output tokens:"),
            nvdaControls.SelectOnFocusSpinCtrl,
            min=1,
            max=65536,
        )
        self._max_tokens_spinner.SetValue(get_safe_conf()["maxOutputTokens"])

        # Streaming
        # Translators: Checkbox for streaming responses
        self._stream_checkbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Stream responses"))
        )
        self._stream_checkbox.SetValue(get_safe_conf()["stream"])

        # Conversation mode
        # Translators: Checkbox for conversation mode
        self._convo_checkbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Conversation mode (include history)"))
        )
        self._convo_checkbox.SetValue(get_safe_conf()["conversationMode"])

        # Save system prompt
        # Translators: Checkbox for saving system prompt
        self._save_prompt_checkbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Remember system prompt"))
        )
        self._save_prompt_checkbox.SetValue(get_safe_conf()["saveSystemPrompt"])

        # Block escape
        # Translators: Checkbox for blocking escape key
        self._block_escape_checkbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Block Escape key in dialog"))
        )
        self._block_escape_checkbox.SetValue(get_safe_conf()["blockEscapeKey"])

        # Filter markdown
        # Translators: Checkbox for filtering markdown from responses
        self._filter_markdown_checkbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Filter markdown from responses"))
        )
        self._filter_markdown_checkbox.SetValue(get_safe_conf()["filterMarkdown"])

        # Video analysis prompt
        # Translators: Label for video analysis prompt text field
        video_prompt_label = wx.StaticText(self, label=_("&Video analysis prompt:"))
        sHelper.addItem(video_prompt_label)
        self._video_prompt_text = sHelper.addItem(
            wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 75))
        )
        # Translators: Default video analysis prompt sent to the AI model
        self._default_video_prompt = _("Describe this video in detail, but concise. Get as much information as you can and if there is any important text in the video read it.")
        saved_prompt = get_safe_conf()["videoPrompt"]
        self._video_prompt_text.SetValue(saved_prompt if saved_prompt else self._default_video_prompt)

        # Summarize selection prompt
        # Translators: Label for summarize selection prompt text field
        summarize_prompt_label = wx.StaticText(self, label=_("S&ummarize selection prompt:"))
        sHelper.addItem(summarize_prompt_label)
        self._summarize_prompt_text = sHelper.addItem(
            wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 75))
        )
        # Translators: Default prompt used when summarizing selected text with AI
        self._default_summarize_prompt = _("Summarize the key points of the following text in a clear and concise manner:")
        saved_summarize_prompt = get_safe_conf()["summarizePrompt"]
        self._summarize_prompt_text.SetValue(saved_summarize_prompt if saved_summarize_prompt else self._default_summarize_prompt)

        # Summarize last speech prompt
        # Translators: Label for summarize last speech prompt text field
        summarize_speech_prompt_label = wx.StaticText(self, label=_("Summarize last s&peech prompt:"))
        sHelper.addItem(summarize_speech_prompt_label)
        self._summarize_speech_prompt_text = sHelper.addItem(
            wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 75))
        )
        # Translators: Default prompt used when summarizing the last spoken text with AI
        self._default_summarize_speech_prompt = _("Summarize the following text concisely. Respond in the same language as the text:")
        saved_summarize_speech_prompt = get_safe_conf()["summarizeSpeechPrompt"]
        self._summarize_speech_prompt_text.SetValue(saved_summarize_speech_prompt if saved_summarize_speech_prompt else self._default_summarize_speech_prompt)

        # Feedback section
        # Translators: Label for feedback settings group
        feedback_group = wx.StaticBoxSizer(
            wx.VERTICAL, self, label=_("Sound Feedback")
        )
        feedback_box = feedback_group.GetStaticBox()
        feedback_helper = guiHelper.BoxSizerHelper(self, sizer=feedback_group)

        # Translators: Checkbox for request sent sound
        self._snd_sent_checkbox = feedback_helper.addItem(
            wx.CheckBox(feedback_box, label=_("Play sound when request &sent"))
        )
        self._snd_sent_checkbox.SetValue(
            get_safe_conf()["feedback"]["soundRequestSent"]
        )

        # Translators: Checkbox for response pending sound
        self._snd_pending_checkbox = feedback_helper.addItem(
            wx.CheckBox(feedback_box, label=_("Play sound while &waiting"))
        )
        self._snd_pending_checkbox.SetValue(
            get_safe_conf()["feedback"]["soundResponsePending"]
        )

        # Translators: Checkbox for response received sound
        self._snd_received_checkbox = feedback_helper.addItem(
            wx.CheckBox(feedback_box, label=_("Play sound when response &received"))
        )
        self._snd_received_checkbox.SetValue(
            get_safe_conf()["feedback"]["soundResponseReceived"]
        )

        sHelper.addItem(feedback_group)

    def _open_key_dialog(self, provider: str):
        key_manager = apikeymanager.get_manager(DATA_DIR)
        dlg = APIKeyDialog(self, key_manager, provider)
        dlg.ShowModal()
        dlg.Destroy()

    def onSave(self):
        # Auth provider
        get_safe_conf()["authProvider"] = (
            "bedrock" if self._provider_choice.GetSelection() == 1 else "anthropic"
        )
        get_safe_conf()["bedrockRegion"] = self._region_text.GetValue().strip() or "us-east-1"

        # Model
        model_idx = self._model_choice.GetSelection()
        if model_idx >= 0:
            get_safe_conf()["model"] = CLAUDE_MODELS[model_idx].id

        # Bedrock model ID overrides
        for model_id, field in self._bedrock_id_fields.items():
            get_safe_conf()["bedrockModelOverrides"][model_id] = field.GetValue().strip()

        # Parameters
        get_safe_conf()["temperature"] = self._temp_spinner.GetValue() / 100.0
        get_safe_conf()["maxOutputTokens"] = self._max_tokens_spinner.GetValue()
        get_safe_conf()["stream"] = self._stream_checkbox.GetValue()
        get_safe_conf()["conversationMode"] = self._convo_checkbox.GetValue()
        get_safe_conf()["saveSystemPrompt"] = self._save_prompt_checkbox.GetValue()
        get_safe_conf()["blockEscapeKey"] = self._block_escape_checkbox.GetValue()
        get_safe_conf()["filterMarkdown"] = self._filter_markdown_checkbox.GetValue()

        # Video prompt - store empty string if user left the localized default unchanged
        video_prompt_val = self._video_prompt_text.GetValue().strip()
        if video_prompt_val == self._default_video_prompt:
            get_safe_conf()["videoPrompt"] = ""
        else:
            get_safe_conf()["videoPrompt"] = video_prompt_val

        # Summarize prompt - store empty string if user left the localized default unchanged
        summarize_prompt_val = self._summarize_prompt_text.GetValue().strip()
        if summarize_prompt_val == self._default_summarize_prompt:
            get_safe_conf()["summarizePrompt"] = ""
        else:
            get_safe_conf()["summarizePrompt"] = summarize_prompt_val

        # Summarize speech prompt - store empty string if user left the localized default unchanged
        summarize_speech_prompt_val = self._summarize_speech_prompt_text.GetValue().strip()
        if summarize_speech_prompt_val == self._default_summarize_speech_prompt:
            get_safe_conf()["summarizeSpeechPrompt"] = ""
        else:
            get_safe_conf()["summarizeSpeechPrompt"] = summarize_speech_prompt_val

        # Feedback
        get_safe_conf()["feedback"]["soundRequestSent"] = (
            self._snd_sent_checkbox.GetValue()
        )
        get_safe_conf()["feedback"]["soundResponsePending"] = (
            self._snd_pending_checkbox.GetValue()
        )
        get_safe_conf()["feedback"]["soundResponseReceived"] = (
            self._snd_received_checkbox.GetValue()
        )


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    """Global plugin for Claude AI integration."""

    # Translators: Category for input gestures
    scriptCategory = _("Claude AI")

    def __init__(self):
        super().__init__()

        # Register configuration
        config.conf.spec["ClauVDA"] = confSpecs

        # Register settings panel
        NVDASettingsDialog.categoryClasses.append(ClauVDASettingsPanel)

        # Initialize API key manager
        self._key_manager = apikeymanager.get_manager(DATA_DIR)

        # Client instance (lazy loaded; refreshed when provider/key changes)
        self._client = None
        self._client_provider: str | None = None

        # Video capture instance
        self._video_capture = None

        # Speech history capture
        self._last_speech = None
        self._patch_speech()

        # Clean up old temporary files on startup
        self._cleanup_temp_files()

        # Create menu
        self._create_menu()

        log.info("ClauVDA add-on initialized")

    def _patch_speech(self):
        """Monkey-patch speech.speak to capture the last spoken text."""
        self._oldSpeak = speech.speech.speak

        def _mySpeak(sequence, *args, **kwargs):
            self._oldSpeak(sequence, *args, **kwargs)
            text = self._get_sequence_text(sequence)
            if text.strip():
                queueFunction(eventQueue, self._on_speech, sequence)

        speech.speech.speak = _mySpeak

    def _unpatch_speech(self):
        """Restore the original speech.speak."""
        speech.speech.speak = self._oldSpeak

    def _on_speech(self, sequence):
        """Store the last spoken sequence as text."""
        seq = [cmd for cmd in sequence if not isinstance(cmd, FocusLossCancellableSpeechCommand)]
        self._last_speech = self._get_sequence_text(seq)

    @staticmethod
    def _get_sequence_text(sequence):
        """Extract text from a speech sequence."""
        return speechViewer.SPEECH_ITEM_SEPARATOR.join(
            [x for x in sequence if isinstance(x, str)]
        )

    def _cleanup_temp_files(self):
        """Clean up old screenshot and video files on startup."""
        import glob

        patterns = [
            os.path.join(DATA_DIR, "screenshot_*.png"),
            os.path.join(DATA_DIR, "object_*.png"),
            os.path.join(DATA_DIR, "capture_*.mp4"),
            os.path.join(DATA_DIR, "frame_*.jpg"),
        ]

        deleted_count = 0
        for pattern in patterns:
            for filepath in glob.glob(pattern):
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception as e:
                    log.warning(f"Failed to delete temp file {filepath}: {e}")

        if deleted_count > 0:
            log.info(f"Cleaned up {deleted_count} temporary files from previous session")

    def terminate(self):
        """Clean up when add-on is disabled/NVDA exits."""
        # Restore original speech function
        self._unpatch_speech()

        # Stop video capture if running
        if self._video_capture and self._video_capture.is_recording:
            self._video_capture.stop()

        # Remove settings panel
        try:
            NVDASettingsDialog.categoryClasses.remove(ClauVDASettingsPanel)
        except ValueError:
            pass

        # Remove menu
        try:
            gui.mainFrame.sysTrayIcon.menu.Remove(self._menu_item)
        except Exception:
            pass

        log.info("ClauVDA add-on terminated")

    def _create_menu(self):
        """Create system tray menu item."""
        self._menu = wx.Menu()

        # Translators: Menu item to open Claude dialog
        dialog_item = self._menu.Append(wx.ID_ANY, _("Open Claude &Dialog...\tNVDA+G"))
        gui.mainFrame.sysTrayIcon.Bind(
            wx.EVT_MENU, self._on_show_dialog, dialog_item
        )

        self._menu.AppendSeparator()

        # Translators: Menu item to open settings
        settings_item = self._menu.Append(wx.ID_ANY, _("&Settings..."))
        gui.mainFrame.sysTrayIcon.Bind(
            wx.EVT_MENU, self._on_show_settings, settings_item
        )

        # Translators: Menu item to open API key page for active provider
        api_item = self._menu.Append(wx.ID_ANY, _("Get &API Key (web)..."))
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self._on_open_api_page, api_item)

        # Add to system tray
        # Translators: System tray menu item label
        self._menu_item = gui.mainFrame.sysTrayIcon.menu.Insert(
            2, wx.ID_ANY, _("&Claude"), self._menu
        )

    def _on_show_dialog(self, event):
        """Open the main Claude dialog."""
        self._show_dialog()

    def _on_show_settings(self, event):
        """Open settings panel."""
        wx.CallAfter(
            gui.mainFrame.popupSettingsDialog,
            NVDASettingsDialog,
            ClauVDASettingsPanel,
        )

    def _on_open_api_page(self, event):
        """Open API key page in browser for the active provider."""
        import webbrowser
        if get_safe_conf()["authProvider"] == "bedrock":
            webbrowser.open("https://console.aws.amazon.com/bedrock/home#/api-keys")
        else:
            webbrowser.open("https://console.anthropic.com/settings/keys")

    def _get_client(self):
        """Get or create the Anthropic client matching the configured provider."""
        provider = get_safe_conf()["authProvider"]
        if self._client is None or self._client_provider != provider:
            self._client = _build_client()
            self._client_provider = provider if self._client else None
        return self._client

    def _show_dialog(self):
        """Show the main Claude dialog."""
        if not ANTHROPIC_AVAILABLE:
            # Translators: Error when the bundled Anthropic SDK fails to load
            ui.message(
                _(
                    "Anthropic SDK failed to load. "
                    "Please reinstall the add-on."
                )
            )
            return

        client = self._get_client()
        if not client:
            ui.message(_(NO_API_KEY_MSG))
            return

        from . import maindialog

        # Check if dialog already open
        if (
            maindialog.addToSession
            and isinstance(maindialog.addToSession, maindialog.ClaudeDialog)
        ):
            maindialog.addToSession.Raise()
            maindialog.addToSession.SetFocus()
            return

        wx.CallAfter(self._open_dialog, client)

    def _open_dialog(self, client):
        """Open dialog on main thread."""
        from . import maindialog

        dlg = maindialog.ClaudeDialog(
            gui.mainFrame,
            client=client,
            conf_ref=config.conf,
        )
        dlg.Show()
        dlg.Raise()
        dlg.SetFocus()
        # Ensure the prompt field gets focus
        wx.CallAfter(dlg.focus_prompt)

    def _capture_screenshot(self, scale: float = 0.5) -> str | None:
        """Capture full screen and return path to image.

        Args:
            scale: Scale factor to reduce resolution (0.5 = half size)
        """
        try:
            # Add mss to path if available
            if LIBS_DIR not in sys.path:
                sys.path.insert(0, LIBS_DIR)

            import mss
            import datetime
            from PIL import Image

            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(DATA_DIR, f"screenshot_{now}.png")

            with mss.mss() as sct:
                # Capture primary monitor
                img = sct.grab(sct.monitors[1])
                # Convert to PIL Image
                pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")

                # Resize to reduce file size
                if scale < 1.0:
                    new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                    pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)

                # Save with compression
                pil_img.save(path, "PNG", optimize=True)

            return path
        except ImportError:
            log.warning("mss not available for screenshots")
            return None
        except Exception as e:
            log.error(f"Screenshot failed: {e}")
            return None

    def _capture_object(self, scale: float = 0.75) -> str | None:
        """Capture navigator object and return path to image.

        Args:
            scale: Scale factor to reduce resolution (0.75 = 75% size)
        """
        try:
            if LIBS_DIR not in sys.path:
                sys.path.insert(0, LIBS_DIR)

            import mss
            import datetime
            from PIL import Image

            nav = api.getNavigatorObject()
            if not nav or not nav.location:
                return None

            nav.scrollIntoView()
            loc = nav.location

            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(DATA_DIR, f"object_{now}.png")

            monitor = {
                "top": loc.top,
                "left": loc.left,
                "width": loc.width,
                "height": loc.height,
            }

            with mss.mss() as sct:
                img = sct.grab(monitor)
                pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")

                # Resize to reduce file size (only if image is large enough)
                if scale < 1.0 and pil_img.width > 100 and pil_img.height > 100:
                    new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                    pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)

                # Save with compression
                pil_img.save(path, "PNG", optimize=True)

            return path
        except ImportError as e:
            log.warning(f"Dependencies not available for object capture: {e}")
            return None
        except Exception as e:
            log.error(f"Object capture failed: {e}")
            return None

    @script(
        # Translators: Description for show dialog script
        description=_("Show Claude AI dialog"),
        gesture="kb:nvda+g",
    )
    def script_showDialog(self, gesture):
        self._show_dialog()

    @script(
        # Translators: Description for describe screen script
        description=_("Describe the entire screen using Claude"),
        gesture="kb:nvda+shift+e",
    )
    def script_describeScreen(self, gesture):
        if not ANTHROPIC_AVAILABLE:
            ui.message(_("Anthropic SDK not installed."))
            return

        client = self._get_client()
        if not client:
            ui.message(_(NO_API_KEY_MSG))
            return

        # Translators: Message while capturing screenshot
        ui.message(_("Capturing screen..."))

        path = self._capture_screenshot()
        if not path:
            # Translators: Error when screenshot fails
            ui.message(_("Failed to capture screenshot"))
            return

        from . import maindialog

        if maindialog.addToSession:
            maindialog.addToSession.add_images([path], prompt_type="screenshot")
        else:
            self._open_dialog(client)
            wx.CallLater(500, lambda: self._add_image_to_dialog(path, "screenshot"))

    def _add_image_to_dialog(self, path, prompt_type=None):
        from . import maindialog
        if maindialog.addToSession:
            maindialog.addToSession.add_images([path], prompt_type=prompt_type)

    @script(
        # Translators: Description for describe object script
        description=_("Describe the navigator object using Claude"),
        gesture="kb:nvda+shift+o",
    )
    def script_describeObject(self, gesture):
        if not ANTHROPIC_AVAILABLE:
            ui.message(_("Anthropic SDK not installed."))
            return

        client = self._get_client()
        if not client:
            ui.message(_(NO_API_KEY_MSG))
            return

        # Translators: Message while capturing object
        ui.message(_("Capturing object..."))

        path = self._capture_object()
        if not path:
            # Translators: Error when object capture fails
            ui.message(_("Failed to capture object"))
            return

        from . import maindialog

        if maindialog.addToSession:
            maindialog.addToSession.add_images([path], prompt_type="object")
        else:
            self._open_dialog(client)
            wx.CallLater(500, lambda: self._add_image_to_dialog(path, "object"))

    def _get_video_capture(self):
        """Get or create video capture instance."""
        if self._video_capture is None:
            self._video_capture = videocapture.VideoCapture(DATA_DIR)
        return self._video_capture

    def _analyze_video(self, video_path: str):
        """Extract frames from the video and send them to Claude as images."""
        import threading

        def do_analysis():
            try:
                client = self._get_client()
                if not client:
                    wx.CallAfter(ui.message, _(NO_API_KEY_MSG))
                    return

                # Translators: Message while extracting frames from the video
                wx.CallAfter(ui.message, _("Extracting frames..."))

                frame_paths = videocapture.extract_frames(video_path, DATA_DIR, max_frames=12)
                if not frame_paths:
                    # Translators: Error when frame extraction fails
                    wx.CallAfter(ui.message, _("Failed to extract frames from video"))
                    return

                # Translators: Message while analyzing video
                wx.CallAfter(ui.message, _("Analyzing video..."))

                from .mdfilter import filter_markdown

                model_id = get_safe_conf()["model"]
                provider = get_safe_conf()["authProvider"]
                from .consts import get_model_by_id
                model = get_model_by_id(model_id)
                resolved_id = model.resolve_id(provider) if model else model_id

                user_content = []
                for fp in frame_paths:
                    part = _encode_image_for_claude(fp)
                    if part:
                        user_content.append(part)

                prompt_text = get_safe_conf()["videoPrompt"] or _(
                    "Describe this video in detail, but concise. Get as much information "
                    "as you can and if there is any important text in the video read it."
                )
                frame_note = _(
                    "The following images are {count} frames sampled in order from a short screen recording."
                ).format(count=len(frame_paths))
                user_content.append({
                    "type": "text",
                    "text": f"{frame_note}\n\n{prompt_text}",
                })

                response = client.messages.create(
                    model=resolved_id,
                    max_tokens=get_safe_conf()["maxOutputTokens"],
                    messages=[{"role": "user", "content": user_content}],
                )

                result_text = _extract_text(response) or _("No response from AI")

                if get_safe_conf()["filterMarkdown"]:
                    result_text = filter_markdown(result_text)

                wx.CallAfter(ui.message, result_text)

                # Clean up frames + source video
                for fp in frame_paths:
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
                try:
                    os.remove(video_path)
                except Exception:
                    pass

            except Exception as e:
                log.error(f"Video analysis failed: {e}", exc_info=True)
                # Translators: Error during video analysis
                wx.CallAfter(
                    ui.message,
                    _("Video analysis failed: {error}").format(error=str(e))
                )

        thread = threading.Thread(target=do_analysis, daemon=True)
        thread.start()

    @script(
        # Translators: Description for video capture toggle script
        description=_("Start or stop video recording for Claude analysis"),
        gesture="kb:nvda+v",
    )
    def script_toggleVideoCapture(self, gesture):
        if not ANTHROPIC_AVAILABLE:
            ui.message(_("Anthropic SDK not installed."))
            return

        capture = self._get_video_capture()

        if not capture.is_available:
            # Translators: Error when video capture dependencies not available
            ui.message(_("Video capture not available. Missing dependencies."))
            return

        if capture.is_recording:
            # Stop recording
            # Translators: Message when stopping video recording
            ui.message(_("Stopping recording..."))
            video_path = capture.stop()

            if video_path:
                # Translators: Message when video saved successfully
                ui.message(_("Video saved. Sending to Claude for analysis..."))
                self._analyze_video(video_path)
            else:
                # Translators: Error when video save fails
                ui.message(_("Failed to save video"))
        else:
            # Start recording
            if capture.start():
                # Translators: Message when video recording starts
                ui.message(_("Recording started. Press NVDA+V again to stop."))
            else:
                # Translators: Error when video recording fails to start
                ui.message(_("Failed to start recording"))

    @script(
        # Translators: Description for summarize selection script
        description=_("Summarize selected text using Claude"),
        gesture="kb:nvda+shift+u",
    )
    def script_summarizeSelection(self, gesture):
        if not ANTHROPIC_AVAILABLE:
            ui.message(_("Anthropic SDK not installed."))
            return

        client = self._get_client()
        if not client:
            ui.message(_(NO_API_KEY_MSG))
            return

        # Get selected text via treeInterceptor (browse mode) or focus object
        obj = api.getFocusObject()
        treeInterceptor = obj.treeInterceptor
        try:
            if treeInterceptor and hasattr(treeInterceptor, "makeTextInfo"):
                info = treeInterceptor.makeTextInfo(textInfos.POSITION_SELECTION)
            else:
                info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
            selected_text = info.text
        except (RuntimeError, NotImplementedError):
            selected_text = None

        if not selected_text or not selected_text.strip():
            # Translators: Error when no text is selected for summarization
            ui.message(_("No text selected"))
            return

        # Translators: Message while summarizing text
        ui.message(_("Summarizing..."))

        self._run_summarize(
            client,
            get_safe_conf()["summarizePrompt"]
            or _("Summarize the key points of the following text in a clear and concise manner:"),
            selected_text,
        )

    @script(
        # Translators: Description for summarize last speech script
        description=_("Summarize the last spoken text using Claude"),
        gesture="kb:nvda+shift+h",
    )
    def script_summarizeLastSpeech(self, gesture):
        if not ANTHROPIC_AVAILABLE:
            ui.message(_("Anthropic SDK not installed."))
            return

        client = self._get_client()
        if not client:
            ui.message(_(NO_API_KEY_MSG))
            return

        last_text = self._last_speech
        if not last_text or not last_text.strip():
            # Translators: Error when no speech history is available
            ui.message(_("No speech history available"))
            return

        # Translators: Message while summarizing last speech
        ui.message(_("Summarizing..."))

        self._run_summarize(
            client,
            get_safe_conf()["summarizeSpeechPrompt"]
            or _("Summarize the following text concisely. Respond in the same language as the text:"),
            last_text,
        )

    def _run_summarize(self, client, prompt: str, text: str):
        """Run a one-shot summarization request on a background thread."""
        import threading
        from .consts import get_model_by_id
        from .mdfilter import filter_markdown

        model_id = get_safe_conf()["model"]
        provider = get_safe_conf()["authProvider"]
        model = get_model_by_id(model_id)
        resolved_id = model.resolve_id(provider) if model else model_id
        full_prompt = f"{prompt}\n\n{text}"

        def do_summarize():
            try:
                response = client.messages.create(
                    model=resolved_id,
                    max_tokens=get_safe_conf()["maxOutputTokens"],
                    messages=[{"role": "user", "content": full_prompt}],
                )
                result_text = _extract_text(response) or _("No response from AI")

                if get_safe_conf()["filterMarkdown"]:
                    result_text = filter_markdown(result_text)

                wx.CallAfter(ui.message, result_text)
            except Exception as e:
                log.error(f"Summarize failed: {e}", exc_info=True)
                # Translators: Error during text summarization
                wx.CallAfter(
                    ui.message,
                    _("Summarization failed: {error}").format(error=str(e)),
                )

        thread = threading.Thread(target=do_summarize, daemon=True)
        thread.start()


def _extract_text(response) -> str:
    """Join text blocks from a Claude Message response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _encode_image_for_claude(path: str) -> dict | None:
    """Encode an image file as an Anthropic image content block."""
    import base64
    try:
        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = mime_types.get(ext, "image/jpeg")
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
