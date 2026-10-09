# ClauVDA NVDA Add-on - Computer use dialog
# -*- coding: utf-8 -*-

"""The computer use dialog.

The dialog is modeless so Claude acts on the application the user was in, not
on the dialog. On Start, focus goes back to that window and progress is
announced with :func:`ui.message`, so the user doesn't need to keep the dialog
focused.
"""

import addonHandler
import gui
import ui
import winUser
import wx
from gui import guiHelper
from gui.message import MessageDialog, ReturnCode
from logHandler import log

from . import agent, speechcapture

addonHandler.initTranslation()


class ComputerUseDialog(wx.Dialog):
    """Modeless dialog for typing a request and following Claude's work."""

    _instance = None

    @classmethod
    def run(cls, target_hwnd: int, client, model, settings: dict) -> None:
        """Show the dialog, remembering the window Claude should act on."""
        if cls._instance is None:
            cls._instance = cls(gui.mainFrame)
        inst = cls._instance
        inst._target_hwnd = target_hwnd
        inst._client = client
        inst._model = model
        inst._settings = settings
        inst._bring_to_front(inst.prompt_ctrl)

    @classmethod
    def surface(cls) -> None:
        """Bring an open dialog to the front without changing its target window."""
        inst = cls._instance
        if inst is not None and not inst._destroyed:
            inst._bring_to_front(inst.prompt_ctrl)

    @classmethod
    def close_instance(cls) -> None:
        """Destroy the dialog when the add-on is unloaded."""
        inst = cls._instance
        cls._instance = None
        if inst is not None:
            inst._destroyed = True
            try:
                inst.Destroy()
            except RuntimeError:
                pass

    def __init__(self, parent):
        # Translators: Title of the computer use dialog
        super().__init__(parent, title=_("Claude Computer Use"))
        self._target_hwnd = 0
        self._client = None
        self._model = None
        self._settings = {}
        self._session = None
        # Set once the widgets are gone, so callbacks from a session that is
        # still stopping don't touch destroyed controls.
        self._destroyed = False
        self._build_ui()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Escape closes the dialog from any control.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.CentreOnScreen()

    def _bring_to_front(self, control) -> None:
        # prePopup brings NVDA's own window forward first, which lets the
        # dialog take the foreground from another application reliably.
        main_frame = gui.mainFrame
        if main_frame is not None:
            main_frame.prePopup()
        try:
            self.Show()
            self.Raise()
            control.SetFocus()
        finally:
            if main_frame is not None:
                main_frame.postPopup()

    def _on_char_hook(self, evt) -> None:
        if evt.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            evt.Skip()

    def _build_ui(self) -> None:
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

        # Translators: Label for the field where the user types the computer use request
        self.prompt_ctrl = helper.addLabeledControl(
            _("&What would you like Claude to do?"),
            wx.TextCtrl,
            style=wx.TE_MULTILINE,
            size=(560, 90),
        )

        # Translators: Example requests shown under the computer use request field
        hint = _(
            "Examples. Assistant: \"I'm stuck on this website, please tick the "
            "'I agree' checkbox and press Continue.\" Screen-reader testing: "
            "\"Tab through this form and tell me whether every field is announced with a label.\""
        )
        hint_label = wx.StaticText(self, label=hint)
        hint_label.Wrap(560)
        helper.addItem(hint_label)

        self.mode_radio = helper.addItem(
            wx.RadioBox(
                self,
                # Translators: Label for the computer use mode selector
                label=_("&Mode"),
                choices=[
                    # Translators: The computer use assistant mode
                    _("Assistant: do a task on my screen"),
                    # Translators: The computer use screen-reader testing mode
                    _("Screen-reader testing: check accessibility with NVDA's speech"),
                ],
                majorDimension=1,
                style=wx.RA_SPECIFY_COLS,
            )
        )

        # Translators: Label for the read-only log of Claude's computer use activity
        self.transcript_ctrl = helper.addLabeledControl(
            _("&Activity"),
            wx.TextCtrl,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            size=(560, 200),
        )

        button_helper = guiHelper.ButtonHelper(wx.HORIZONTAL)
        # Translators: Button that starts a computer use task
        self.start_button = button_helper.addButton(self, label=_("&Start"))
        # Translators: Button that stops a running computer use task
        self.stop_button = button_helper.addButton(self, label=_("Sto&p"))
        # Translators: Button that discards a finished computer use conversation
        self.new_button = button_helper.addButton(self, label=_("&New task"))
        # Translators: Button that closes the computer use dialog
        self.close_button = button_helper.addButton(self, label=_("&Close"))
        helper.addItem(button_helper.sizer)

        self.start_button.Bind(wx.EVT_BUTTON, self._on_start)
        self.stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
        self.new_button.Bind(wx.EVT_BUTTON, self._on_new_task)
        self.close_button.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
        self.start_button.SetDefault()
        self.stop_button.Enable(False)
        self.new_button.Enable(False)

        main_sizer.Add(helper.sizer, flag=wx.ALL | wx.EXPAND, border=guiHelper.BORDER_FOR_DIALOGS)
        self.SetSizerAndFit(main_sizer)

    # -- actions -----------------------------------------------------------

    def _focus_target_window(self) -> None:
        """Give focus back to the user's window, so Claude acts on it."""
        if self._target_hwnd:
            try:
                winUser.setForegroundWindow(self._target_hwnd)
            except Exception:
                log.debugWarning("Could not restore the target window", exc_info=True)

    def _on_start(self, evt) -> None:
        # While paused, Start resumes with the typed text as guidance; once a
        # task finished, it sends the text as a follow-up in the same context.
        if self._session is not None and self._session.is_paused():
            self._resume()
            return
        prompt = self.prompt_ctrl.GetValue().strip()
        if not prompt:
            # Translators: Announced when the computer use request is empty
            ui.message(_("Please type what you would like Claude to do."))
            self.prompt_ctrl.SetFocus()
            return
        if self._session is not None and self._session.can_continue():
            self._continue(prompt)
            return
        mode = agent.MODE_TESTING if self.mode_radio.GetSelection() == 1 else agent.MODE_ASSIST
        self._focus_target_window()
        self._session = agent.Session(prompt, mode, self._report, self._client, self._model, self._settings)
        self._set_state("running")
        # Translators: Activity log line when a computer use task starts
        self._append(_("Starting."))
        self._session.start()

    def _resume(self) -> None:
        guidance = self.prompt_ctrl.GetValue().strip()
        self._focus_target_window()
        self._set_state("running")
        # Translators: Activity log line when a paused computer use task resumes
        self._append(_("Resuming."))
        self.prompt_ctrl.SetValue("")
        self._session.resume(guidance)

    def _continue(self, prompt: str) -> None:
        self._focus_target_window()
        self._set_state("running")
        # Translators: Activity log line when a follow-up computer use request starts
        self._append(_("Continuing."))
        self.prompt_ctrl.SetValue("")
        self._session.continue_task(prompt)

    def _on_new_task(self, evt) -> None:
        self._session = None
        self._set_state("idle")
        self.prompt_ctrl.SetValue("")
        # Translators: Announced when a finished computer use conversation is discarded
        message = _("New task. The previous conversation was discarded.")
        self._append(message)
        ui.message(message)
        self.prompt_ctrl.SetFocus()

    def _on_stop(self, evt) -> None:
        if self._session is not None and (self._session.is_running() or self._session.is_paused()):
            self._session.stop()
            # Translators: Activity log line when the user stops a computer use task
            self._append(_("Stopping."))

    def _on_close(self, evt) -> None:
        if self._session is not None and (self._session.is_running() or self._session.is_paused()):
            answer = MessageDialog.confirm(
                # Translators: Confirmation when closing the dialog while a computer use task runs
                _("A task is still running. Stop it and close?"),
                # Translators: Title of a computer use message box
                _("Claude Computer Use"),
                parent=self,
            )
            if answer != ReturnCode.OK:
                if evt.CanVeto():
                    evt.Veto()
                return
            self._session.stop()
        self._destroyed = True
        ComputerUseDialog._instance = None
        self.Destroy()

    # -- session callbacks (from the worker thread) ------------------------

    def _report(self, kind: str, text: str) -> None:
        wx.CallAfter(self._on_report, kind, text)

    def _on_report(self, kind: str, text: str) -> None:
        if self._destroyed:
            return
        labels = {
            # Translators: Activity log prefix for Claude's reply
            "assistant": _("Claude"),
            # Translators: Activity log prefix for a note Claude wrote between actions
            "progress": _("Claude"),
            # Translators: Activity log prefix for an action Claude performed
            "action": _("Action"),
            # Translators: Activity log prefix for a status update
            "status": _("Status"),
            # Translators: Activity log prefix for an error
            "error": _("Error"),
            "paused": _("Status"),
            "finished": _("Status"),
        }
        label = labels.get(kind)
        self._append(f"{label}: {text}" if label else text)
        # Speak progress so the user can follow along from their own window.
        # Not while NVDA's speech is being recorded for a test, or Claude would
        # hear the add-on's own announcements as the application's.
        if kind != "action" and not speechcapture.is_capturing():
            ui.message(text)
        if kind == "paused":
            self._set_state("paused")
            self.prompt_ctrl.SetValue("")
            self._bring_to_front(self.prompt_ctrl)
        elif kind == "finished":
            self._set_state("done")
            self.prompt_ctrl.SetValue("")
            self._bring_to_front(self.prompt_ctrl)
        elif kind == "done":
            self._session = None
            self._set_state("idle")
            self._bring_to_front(self.transcript_ctrl)

    # -- helpers -----------------------------------------------------------

    def _append(self, text: str) -> None:
        self.transcript_ctrl.AppendText(text + "\n")

    def _set_state(self, state: str) -> None:
        """Update the controls for "idle", "running", "paused" or "done"."""
        running = state == "running"
        self.start_button.Enable(not running)
        self.stop_button.Enable(running or state == "paused")
        self.new_button.Enable(state == "done")
        self.prompt_ctrl.Enable(not running)
        # The mode is fixed once a conversation exists.
        self.mode_radio.Enable(state == "idle")
        if state == "paused":
            # Translators: Button that resumes a paused computer use task
            label = _("&Resume")
        elif state == "done":
            # Translators: Button that sends a follow-up once a computer use task finished
            label = _("C&ontinue")
        else:
            label = _("&Start")
        self.start_button.SetLabel(label)
        self.Layout()
