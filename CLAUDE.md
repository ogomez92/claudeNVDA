# NVDA Add-on Development Guide

This document contains patterns, classes, and best practices for developing NVDA add-ons, compiled from analysis of production add-ons and verified against the NVDA source tree.

## Tracked NVDA Source

Every API in this guide was checked against this NVDA commit. Re-verify against a newer one before trusting the guide on it.

| | |
| :--- | :--- |
| Repository | `C:\Users\Nitropc\code\nvda\nvda` (`https://github.com/nvaccess/nvda`, branch `master`) |
| Commit | `c22a509337c0b94ac5459ab2a749eeeb9cb06116` (2026-10-01, "Fix Modern Word comment reporting…", #20894) |
| `git describe` | `release-2026.3beta3-28-gc22a50933` |
| Source version | `2027.1` dev (`source/buildVersion.py`), `addonAPIVersion.BACK_COMPAT_TO = (2027, 1, 0)` |
| Latest stable | `2026.2`; `2026.3` is in beta (`BACK_COMPAT_TO = (2026, 1, 0)` on both) |
| Last verified | 2026-10-04 |

**Updating this guide to a newer NVDA commit:**

```sh
# Git Bash
cd /c/Users/Nitropc/code/nvda/nvda
git pull
OLD=c22a509337c0b94ac5459ab2a749eeeb9cb06116
git log --oneline $OLD..HEAD                                  # what landed
git diff $OLD..HEAD -- user_docs/en/changes.md                # read every "Changes for Developers",
                                                              # "API Breaking Changes" and "Deprecations" entry
git diff $OLD..HEAD -- source/addonAPIVersion.py source/buildVersion.py pyproject.toml
git diff $OLD..HEAD -- projectDocs/dev/developerGuide/developerGuide.md
git diff --stat $OLD..HEAD -- source/ui.py source/api.py source/scriptHandler.py source/addonHandler \
    source/globalPluginHandler.py source/appModuleHandler.py source/synthDriverHandler.py \
    source/gui/settingsDialogs.py source/gui/message.py source/gui/guiHelper.py source/gui/nvdaControls.py \
    source/speech source/braille source/config source/keyboardHandler.py source/touchHandler.py
```

Then update the table above and the [API Change Log](#nvda-api-change-log-for-add-on-authors) at the end of this file.

## Environment

- **Python Version:** 3.13, 64-bit. NVDA 2026.2 bundles 3.13.13; 2026.3 and the 2027.1 dev branch bundle 3.13.15. The add-on cannot choose it. (`addonAPIVersion.py` plans a Python 3.14 upgrade for 2027.1, but at the tracked commit `pyproject.toml` still pins `>=3.13,<3.14`.)
- **Architecture:** NVDA is 64-bit only since 2026.1. Any DLL, `.pyd` or wheel you bundle must be **x64** (`cp313-win_amd64`). 32-bit DLLs cannot be loaded into NVDA's process.
- **Platform:** Windows 10 or 11 (Windows 8.1, 32-bit Windows and Windows 10 on ARM are not supported since 2026.1)
- **Framework:** wxPython for GUI. 2026.x ships wxPython 4.2.4. 2027.1 ships **4.3.1** (wxWidgets 3.3.3), where APIs that wxWidgets deprecated in 3.0 no longer exist.
- **NVDA Log Files:** `%tmp%\nvda.log` (current session), `%tmp%\nvda-old.log` (previous session)
- **Other APIs you can use that might not be covered here:** .engine folder
- **Public API rule:** anything prefixed with `_` (or living under an `_`-prefixed module) is private and may vanish in any release. Import symbols from the module that **defines** them, never from a module that merely re-imports them (see the developer guide, "Stability of transitive imports"). Bundle your own pip dependencies rather than relying on NVDA's copies. wxPython is the exception.

> **Development Tip:** After making changes, have the user restart NVDA, then check `%tmp%\nvda.log` for errors. If NVDA crashes on startup, the previous log at `%tmp%\nvda-old.log` contains the crash information.

---

## Add-on Directory Structure

```
AddonName/
├── manifest.ini                    # Required - add-on metadata
├── installTasks.py                 # Optional - install/uninstall hooks
├── globalPlugins/                  # Optional - global functionality
│   └── pluginName/
│       ├── __init__.py             # Main plugin module
│       └── submodules.py           # Additional modules
├── appModules/                     # Optional - app-specific modules
│   └── appname.py                  # Named after target application
├── synthDrivers/                   # Optional - speech synthesizers
│   └── drivername.py
├── brailleDisplayDrivers/          # Optional - braille display drivers
│   └── drivername.py
├── visionEnhancementProviders/     # Optional - vision providers
│   └── providername.py
├── speechDicts/                    # Optional - speech dictionaries (declared in manifest)
│   └── pronunciation.dic
├── brailleTables/                  # Optional - braille tables (declared in manifest)
│   └── mytable.utb
├── locale/                         # Optional - translations
│   └── [lang_code]/
│       ├── LC_MESSAGES/
│       │   ├── nvda.po             # Source translations
│       │   └── nvda.mo             # Compiled translations
│       ├── symbols-<name>.dic      # Optional - symbol dictionaries (declared in manifest)
│       └── manifest.ini            # Language-specific metadata
└── doc/                            # Optional - documentation
    └── [lang_code]/
        └── readme.html
```

NVDA adds an enabled add-on's `appModules`, `brailleDisplayDrivers`, `globalPlugins`, `synthDrivers` and `visionEnhancementProviders` folders to the matching package path (`addonHandler/packaging.py`). It does not auto-load any other folder.

---

## manifest.ini Format

```ini
name = addonName
summary = "Short description"
description = """Longer description
can span multiple lines"""
author = "Author Name <email@example.com>"
url = https://github.com/user/addon
version = 1.0.0
changelog = """Changes in this version (Markdown allowed)"""
docFileName = readme.html
minimumNVDAVersion = 2026.1
lastTestedNVDAVersion = 2026.3
updateChannel = None
```

Fields NVDA validates (`addonHandler.AddonManifest.configspec`): `name`, `summary`, `author` and `version` are required. `description`, `changelog` (since 2026.1), `url`, `docFileName`, `minimumNVDAVersion` and `lastTestedNVDAVersion` are optional. There are also the optional `[brailleTables]`, `[symbolDictionaries]` and `[speechDictionaries]` sections. `updateChannel` is not in NVDA's spec. The add-on template's build writes it, and NVDA ignores it.

### Choosing minimumNVDAVersion / lastTestedNVDAVersion

An add-on loads only if `lastTestedNVDAVersion >= addonAPIVersion.BACK_COMPAT_TO` and `minimumNVDAVersion <= the running NVDA version`. Versions are `YYYY.major` or `YYYY.major.minor`.

| Target | `minimumNVDAVersion` | `lastTestedNVDAVersion` |
| :--- | :--- | :--- |
| NVDA 2026.1 – 2026.3 (current stable line, `BACK_COMPAT_TO = 2026.1`) | `2026.1` (first 64-bit / Python 3.13 release) | `2026.3` |
| NVDA 2027.1 (API-breaking release, `BACK_COMPAT_TO = 2027.1`) | `2026.1` if the code still runs on 2026.x, otherwise `2027.1` | `2027.1` (required, or NVDA 2027.1 disables the add-on) |

Use `minimumNVDAVersion = 2026.2` or later only if you call something added in that release. For example, `log.debug(..., redactSecrets=True)` needs 2026.2, and `config.configSections.registerSection` and `gui.message.HtmlMessageDialog` need 2026.3. The Add-on Store accepts only values listed in [nvdaAPIVersions.json](https://github.com/nvaccess/addon-datastore-transform/blob/main/nvdaAPIVersions.json).

---

## Core Classes

### GlobalPlugin (globalPluginHandler.GlobalPlugin)

Extends NVDA globally. Use for features that work across all applications.

```python
import globalPluginHandler
import addonHandler
import scriptHandler
import config
import ui
import wx
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog

addonHandler.initTranslation()

# Config specification
confspec = {
    "enabled": "boolean(default=True)",
    "volume": "integer(default=50, min=0, max=100)",
    "mode": 'string(default="auto")',
}

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Category for input gestures dialog
    scriptCategory = _("My Add-on")

    def __init__(self):
        super().__init__()
        # Register config
        config.conf.spec["myAddon"] = confspec
        # Register settings panel
        NVDASettingsDialog.categoryClasses.append(MySettingsPanel)
        # Initialize state
        self.enabled = config.conf["myAddon"]["enabled"]

    def terminate(self):
        """Called when NVDA exits or add-on is disabled"""
        # Unregister settings panel
        NVDASettingsDialog.categoryClasses.remove(MySettingsPanel)
        # Save any state
        config.conf["myAddon"]["enabled"] = self.enabled

    @scriptHandler.script(
        description=_("Toggle feature on/off"),
        gesture="kb:NVDA+shift+f"
    )
    def script_toggleFeature(self, gesture):
        self.enabled = not self.enabled
        state = _("enabled") if self.enabled else _("disabled")
        ui.message(_("Feature {state}").format(state=state))
```

### AppModule (appModuleHandler.AppModule)

Targets specific applications. The module filename must match the application's executable name.

```python
# File: appModules/notepad.py (targets notepad.exe)
import appModuleHandler
import scriptHandler
import api
import ui
import controlTypes

class AppModule(appModuleHandler.AppModule):
    scriptCategory = _("Notepad Enhancements")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lastLine = ""

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        """Add custom overlay classes to specific controls"""
        if obj.role == controlTypes.Role.EDITABLETEXT:
            clsList.insert(0, EnhancedTextArea)

    @scriptHandler.script(
        description=_("Announce line count"),
        gesture="kb:control+shift+l"
    )
    def script_announceLineCount(self, gesture):
        obj = api.getFocusObject()
        if hasattr(obj, 'value') and obj.value:
            lines = obj.value.count('\n') + 1
            ui.message(_("{count} lines").format(count=lines))
```

### SynthDriver (synthDriverHandler.SynthDriver)

Provides text-to-speech synthesis.

```python
import synthDriverHandler
from synthDriverHandler import VoiceInfo, synthIndexReached, synthDoneSpeaking
from autoSettingsUtils.driverSetting import BooleanDriverSetting, NumericDriverSetting
from speech.commands import IndexCommand

class SynthDriver(synthDriverHandler.SynthDriver):
    name = "mySynth"
    description = "My Custom Synthesizer"

    supportedSettings = (
        synthDriverHandler.SynthDriver.VoiceSetting(),
        synthDriverHandler.SynthDriver.RateSetting(),
        synthDriverHandler.SynthDriver.PitchSetting(),
        synthDriverHandler.SynthDriver.VolumeSetting(),
        # (id, displayNameWithAccelerator, availableInSettingsRing, ...)
        BooleanDriverSetting("enhancedMode", _("&Enhanced mode"), False),
        NumericDriverSetting("quality", _("&Quality"), False, minStep=1),
    )
    # Speech commands this synth handles; others are stripped before speak()
    supportedCommands = frozenset({IndexCommand})
    # Must be declared, and must actually be fired, or say-all stalls
    supportedNotifications = frozenset({synthIndexReached, synthDoneSpeaking})

    @classmethod
    def check(cls):
        """Return True if synth is available"""
        return True  # Check for required DLLs/dependencies (64-bit only!)

    def __init__(self):
        super().__init__()
        # Initialize synthesizer

    def speak(self, speechSequence):
        """Process and speak the given speech sequence"""
        for item in speechSequence:
            if isinstance(item, str):
                pass  # Queue text
            elif isinstance(item, IndexCommand):
                pass  # When audio reaches it: synthIndexReached.notify(synth=self, index=item.index)
        # When all audio has played: synthDoneSpeaking.notify(synth=self)

    def cancel(self):
        """Stop speaking"""
        pass

    def _get_availableVoices(self):
        """Return dict of available voices"""
        return {
            "voice1": VoiceInfo("voice1", _("Voice 1")),
            "voice2": VoiceInfo("voice2", _("Voice 2")),
        }
```

---

## Common NVDA API Imports

```python
# Core modules
import addonHandler          # Add-on management, translations
import globalPluginHandler   # GlobalPlugin base class
import appModuleHandler      # AppModule base class
import scriptHandler         # Script decorator and utilities
import config                # Configuration management
import ui                    # User interface (message, browse)
import api                   # NVDA API (focus, navigator, clipboard)
import speech                # Speech output (speech.Spri for priorities)
import braille               # Braille output (a package since 2026.3; braille.handler is still here)
import tones                 # Audio feedback (beeps)
import nvwave                # Play .wav files
import core                  # Core NVDA functions (restart)
import queueHandler          # Queue operations
import globalVars            # Global variables
import controlTypes          # Control types and states

# UI modules
import gui                   # GUI utilities
from gui import guiHelper    # Layout helpers
from gui import nvdaControls # NVDA-specific controls
from gui.message import MessageDialog, DialogType, ReturnCode  # Message boxes (replaces gui.messageBox)
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog
# Use gui.mainFrame at call time; "from gui import mainFrame" captures None if imported before the GUI starts

# Object handling
from NVDAObjects import NVDAObject
from NVDAObjects.behaviors import Notification

# Script handling
from scriptHandler import script
from globalCommands import SCRCAT_CONFIG, SCRCAT_SPEECH

# Extension points (register in __init__, unregister in terminate)
from speech.extensions import filter_speechSequence, pre_speech
import config                # config.post_configProfileSwitch, config.post_configSave, ...

# Logging
from logHandler import log
```

### Moved / renamed modules to import from their new location

| Old import | Import instead | Since |
| :--- | :--- | :--- |
| `braille.BrailleDisplayDriver` | `braille.display.driver.BrailleDisplayDriver` | 2026.3 (old path warns) |
| `braille.BrailleDisplayGesture` | `braille.display.gesture.BrailleDisplayGesture` (set `cellIndexes`, not `routingIndex`) | 2026.3 |
| `braille.Region` / `TextRegion` | `braille.regions.base.Region` / `TextRegion` | 2026.3 |
| `braille.NVDAObjectRegion` | `braille.regions.NVDAObject.NVDAObjectRegion` | 2026.3 |
| `braille.pre_writeCells`, `braille.displayChanged`, `braille.decide_enabled`, … | `braille.extensions.*` | 2026.3 |
| `braille.BrailleMode`, `braille.TetherTo` | `config.configFlags.BrailleMode`, `config.configFlags.TetherTo` | 2026.3 |
| `brailleInput.handler`, `brailleInput.BrailleInputGesture` | `braille.input.handler`, `braille.input.gesture.BrailleInputGesture` | 2026.3 |
| `speechDictHandler.SpeechDictEntry` / `SpeechDict`, `ENTRY_TYPE_*` | `speechDictHandler.types.SpeechDictEntry` / `SpeechDict` / `EntryType` | 2026.2 |
| `touchTracker.action_*`, `touchHandler.touchModeLabels` | `touchTracker.TouchAction`, `touchHandler.TouchMode` | 2026.3 |
| `gui.messageBox(...)`, `gui.runScriptModalDialog(...)` | `gui.message.MessageDialog` (see [Message Dialogs](#message-dialogs)) | deprecated since 2025.1 |
| `ui.browseableMessage` HTML constants (`HTMLDLG_*`, …) | `gui.message.HtmlMessageDialog` | 2026.3 |
| `config.conf["vision"]["screenCurtain"]` | `config.conf["screenCurtain"]` | 2026.1 |
| `winKernel.GENERIC_READ`, `PROCESS_QUERY_INFORMATION`, … | `winBindings.kernel32.GENERIC.READ`, `winBindings.kernel32.PROCESS.QUERY_INFORMATION` | 2027.1 |
| `winUser.user32`, `winKernel.kernel32`, `shellapi.shell32`, … | `winBindings.user32.dll`, `winBindings.kernel32.dll`, `winBindings.shell32.dll` | 2026.1 |

The full list is in [NVDA API Change Log](#nvda-api-change-log-for-add-on-authors).

---

## Generating User Interfaces

### Settings Panel (Integrates into NVDA Settings)

```python
from gui.settingsDialogs import SettingsPanel
from gui import guiHelper, nvdaControls
import wx
import config

class MySettingsPanel(SettingsPanel):
    title = _("My Add-on")

    def makeSettings(self, settingsSizer):
        # Create helper for layout
        sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        # Checkbox
        self.enabledCheckbox = sHelper.addItem(
            wx.CheckBox(self, label=_("&Enable feature"))
        )
        self.enabledCheckbox.SetValue(config.conf["myAddon"]["enabled"])

        # Text input with label
        self.nameEdit = sHelper.addLabeledControl(
            _("&Name:"),
            wx.TextCtrl
        )
        self.nameEdit.SetValue(config.conf["myAddon"]["name"])

        # Spin control for numbers
        self.volumeSpinner = sHelper.addLabeledControl(
            _("&Volume:"),
            nvdaControls.SelectOnFocusSpinCtrl,
            min=0,
            max=100
        )
        self.volumeSpinner.SetValue(config.conf["myAddon"]["volume"])

        # Choice/dropdown
        self.modeChoice = sHelper.addLabeledControl(
            _("&Mode:"),
            wx.Choice,
            choices=[_("Auto"), _("Manual"), _("Disabled")]
        )
        self.modeChoice.SetSelection(0)

        # Checklist box
        self.optionsList = sHelper.addLabeledControl(
            _("&Options:"),
            nvdaControls.CustomCheckListBox,
            choices=[_("Option 1"), _("Option 2"), _("Option 3")]
        )
        self.optionsList.CheckedItems = [0, 2]  # Check items 0 and 2

        # Grouped settings with StaticBoxSizer
        groupLabel = _("Advanced Settings")
        groupSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=groupLabel)
        groupBox = groupSizer.GetStaticBox()
        groupHelper = guiHelper.BoxSizerHelper(self, sizer=groupSizer)

        self.advancedCheck = groupHelper.addItem(
            wx.CheckBox(groupBox, label=_("Advanced &option"))
        )

        sHelper.addItem(groupSizer)

        # Button
        self.configButton = sHelper.addItem(
            wx.Button(self, label=_("&Configure..."))
        )
        self.configButton.Bind(wx.EVT_BUTTON, self.onConfigButton)

    def onConfigButton(self, evt):
        # Open custom dialog
        dlg = MyCustomDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def onSave(self):
        """Called when user clicks OK"""
        config.conf["myAddon"]["enabled"] = self.enabledCheckbox.GetValue()
        config.conf["myAddon"]["name"] = self.nameEdit.GetValue()
        config.conf["myAddon"]["volume"] = self.volumeSpinner.GetValue()
```

### Custom Dialog

```python
class MyCustomDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Custom Settings"))
        self.InitUI()
        self.CenterOnParent()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Form layout with FlexGridSizer
        fgs = wx.FlexGridSizer(3, 2, 10, 10)  # rows, cols, vgap, hgap

        lblName = wx.StaticText(panel, label=_("Name:"))
        self.txtName = wx.TextCtrl(panel)

        lblValue = wx.StaticText(panel, label=_("Value:"))
        self.txtValue = wx.TextCtrl(panel)

        fgs.AddMany([
            lblName, (self.txtName, 1, wx.EXPAND),
            lblValue, (self.txtValue, 1, wx.EXPAND),
        ])
        fgs.AddGrowableCol(1, 1)

        vbox.Add(fgs, proportion=1, flag=wx.ALL | wx.EXPAND, border=10)

        # Standard dialog buttons
        btnsizer = wx.StdDialogButtonSizer()
        btnOK = wx.Button(panel, wx.ID_OK)
        btnOK.SetDefault()
        btnsizer.AddButton(btnOK)
        btnsizer.AddButton(wx.Button(panel, wx.ID_CANCEL))
        btnsizer.Realize()

        vbox.Add(btnsizer, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        self.Fit()
```

### Context Menus

```python
def onContextMenu(self, event):
    menu = wx.Menu()

    # Add menu items
    copyId = wx.NewIdRef()
    menu.Append(copyId, _("&Copy"))
    self.Bind(wx.EVT_MENU, self.onCopy, id=copyId)

    pasteId = wx.NewIdRef()
    menu.Append(pasteId, _("&Paste"))
    self.Bind(wx.EVT_MENU, self.onPaste, id=pasteId)

    menu.AppendSeparator()

    # Standard IDs
    menu.Append(wx.ID_SELECTALL)

    self.PopupMenu(menu)
    menu.Destroy()
```

### Opening Dialogs from Scripts

```python
@scriptHandler.script(description=_("Open settings"), gesture="kb:NVDA+shift+s")
def script_openSettings(self, gesture):
    # Must use wx.CallAfter for thread safety
    wx.CallAfter(self._showSettings)

def _showSettings(self):
    gui.mainFrame.popupSettingsDialog(NVDASettingsDialog, MySettingsPanel)
```

### Message Dialogs

`gui.messageBox` and `gui.runScriptModalDialog` are deprecated and log a `DeprecationWarning`. Use `gui.message.MessageDialog` instead (`source/gui/message.py`):

```python
from gui.message import MessageDialog, DialogType, ReturnCode, DefaultButtonSet

# One-liners: thread safe and blocking, so you can call them from a script or a background thread
MessageDialog.alert(_("Download finished"), _("My Add-on"))
if MessageDialog.confirm(_("Delete all items?"), _("My Add-on")) == ReturnCode.OK:
    ...
answer = MessageDialog.ask(_("Save changes?"), _("My Add-on"))  # ReturnCode.YES / NO / CANCEL

# Non-blocking with callbacks, created on the GUI thread
def _show():
    dlg = MessageDialog(
        gui.mainFrame,
        _("Something went wrong."),
        _("My Add-on"),
        dialogType=DialogType.ERROR,          # STANDARD / WARNING / ERROR (sets icon and sound)
        buttons=DefaultButtonSet.OK_CANCEL,   # OK_CANCEL, YES_NO, YES_NO_CANCEL, SAVE_NO_CANCEL
    )
    dlg.addButton(ReturnCode.CUSTOM_1, _("&Retry"), callback=lambda payload: retry())  # CUSTOM_1..CUSTOM_5
    dlg.Show()                                # or dlg.ShowModal() -> ReturnCode
wx.CallAfter(_show)
```

`gui.message.HtmlMessageDialog` (2026.3+) renders a full HTML document in a `wx.html2.WebView`. For a simple read-only text or HTML window, `ui.browseableMessage(text, title, isHtml=False, closeButton=False, copyButton=False)` is still the simplest option. Its HTML is sanitised with `nh3`.

---

## Managing Keystrokes and Gestures

### Using @script Decorator (Recommended)

```python
from scriptHandler import script

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("My Add-on")

    # Simple gesture
    @script(
        description=_("Announce current time"),
        gesture="kb:NVDA+t"
    )
    def script_announceTime(self, gesture):
        import datetime
        ui.message(datetime.datetime.now().strftime("%H:%M"))

    # Multiple gestures (desktop + laptop)
    @script(
        description=_("Next item"),
        gestures=[
            "kb:control+windows+numpad6",
            "kb(laptop):control+windows+pagedown"
        ]
    )
    def script_nextItem(self, gesture):
        # Implementation
        pass

    # Touch gesture
    @script(
        description=_("Toggle feature"),
        gesture="ts:4finger_double_tap",
        speakOnDemand=True
    )
    def script_toggleViaTouch(self, gesture):
        pass

    # No default gesture (user configurable)
    @script(
        description=_("Custom action"),
        category=SCRCAT_CONFIG  # Use standard NVDA category
    )
    def script_customAction(self, gesture):
        pass
```

### Using __gestures Dictionary

```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def script_action1(self, gesture):
        ui.message("Action 1")

    def script_action2(self, gesture):
        ui.message("Action 2")

    # Map gestures to script names (without "script_" prefix)
    __gestures = {
        "kb:NVDA+1": "action1",
        "kb:NVDA+2": "action2",
        "kb:control+shift+a": "action1",
    }
```

### Dynamic Gesture Binding

```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self.layerActive = False

        # Gestures for layer mode
        self._layerGestures = {
            "kb:1": "layerAction1",
            "kb:2": "layerAction2",
            "kb:escape": "exitLayer",
        }

    @script(description=_("Enter command layer"), gesture="kb:NVDA+l")
    def script_enterLayer(self, gesture):
        if self.layerActive:
            return
        self.layerActive = True
        self.bindGestures(self._layerGestures)
        tones.beep(400, 50)
        ui.message(_("Layer activated"))

    def script_exitLayer(self, gesture):
        self.layerActive = False
        self.clearGestureBindings()
        self.bindGestures(self.__gestures)
        ui.message(_("Layer deactivated"))

    def script_layerAction1(self, gesture):
        ui.message("Action 1")
        self.script_exitLayer(gesture)
```

### Script Repeat Count (Double/Triple Press)

```python
@script(description=_("Single/double press action"), gesture="kb:NVDA+r")
def script_repeatAction(self, gesture):
    repeatCount = scriptHandler.getLastScriptRepeatCount()
    if repeatCount == 0:
        ui.message(_("Single press"))
    elif repeatCount == 1:
        ui.message(_("Double press"))
    elif repeatCount == 2:
        ui.message(_("Triple press"))
```

### Sending Keystrokes Programmatically

```python
from keyboardHandler import KeyboardInputGesture

def sendKey(self, keyName):
    """Send a keyboard gesture"""
    KeyboardInputGesture.fromName(keyName).send()

# Examples:
self.sendKey("windows+h")      # Win+H
self.sendKey("control+c")      # Ctrl+C
self.sendKey("alt+tab")        # Alt+Tab
```

From 2027.1, `fromName` treats the one non-modifier key as the main key wherever it appears, so `"alt+b+control"` is the same as `"alt+control+b"`. It raises `ValueError` for an empty name, an unknown key name, or more than one non-modifier key. Earlier versions failed silently or picked the last key.

### Gesture Identifier Syntax

Key names come from `source/vkCodes.py` and are case-insensitive in gesture strings.

```
Keyboard gestures:
  kb:key                       - Any keyboard layout
  kb(laptop):key               - Laptop keyboard only
  kb(desktop):key              - Desktop keyboard only

Modifiers:
  NVDA, control, shift, alt, windows
  leftControl, rightControl, leftShift, rightShift, leftAlt, rightAlt, leftWindows, rightWindows
  (there is no "ctrl"/"lctrl" - use "control"/"leftControl")

Keys:
  a-z, 0-9, f1-f24
  space, enter, escape, tab, backspace, delete, insert, applications
  home, end, pageUp, pageDown
  upArrow, downArrow, leftArrow, rightArrow
  numpad0-numpad9, numpadEnter, numpadPlus, numpadMinus, numpadDivide, numpadMultiply,
  numpadDecimal, numpadInsert, numpadDelete
  capsLock, numLock, scrollLock, printScreen, pause
  volumeUp, volumeDown, volumeMute, mediaPlayPause, mediaNextTrack, mediaPrevTrack

Touch gestures (source/touchHandler.py, touchTracker.TouchAction):
  ts:tap, ts:2finger_tap, ts:3finger_tap, ts:4finger_tap
  ts:double_tap, ts:2finger_double_tap, ts:triple_tap, ts:quadruple_tap
  ts:tapAndHold, ts:hold, ts:flickLeft, ts:flickRight, ts:flickUp, ts:flickDown
  ts:pinchIn, ts:pinchOut
  ts:hold+tap, ts:2finger_hold+flickUp - keep finger(s) held while performing another gesture
  ts:2finger_double_flickUp    - order: [hold+][Nfinger_][double_|triple_][edge_]action
  ts(object):flickDown         - Mode-specific: modes are "text", "object", "browse"
                                 (touchHandler.TouchMode; add-ons may append custom
                                 mode strings to touchHandler.availableTouchModes)
  2026.3+:
  ts:flickRightThenLeft        - Two-flick sequences: flick<A>Then<B> for any two
                                 directions (e.g. flickUpThenDown, flickLeftThenUp)
  ts:left_flickRight           - Edge gestures: left_/right_/top_/bottom_ prefix, only
                                 when the user enables config.conf["touch"]["edgeGestures"]
```

---

## Localization

### Setting Up Translations

```python
# At the TOP of your module, before other imports that use _()
import addonHandler
addonHandler.initTranslation()

# Now _() function is available
from scriptHandler import script

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Translators: Category name shown in input gestures
    scriptCategory = _("My Add-on")

    @script(
        # Translators: Description for toggle feature script
        description=_("Toggle the feature on or off")
    )
    def script_toggle(self, gesture):
        # Translators: Message when feature is enabled
        ui.message(_("Feature enabled"))
```

### Using the Translation Function

```python
# Simple string
message = _("Hello, world!")

# String with formatting (use .format() AFTER _())
# Correct:
message = _("Found {count} items").format(count=5)
# WRONG - f-strings cannot be extracted:
# message = _(f"Found {count} items")

# Multi-line strings
description = _("""This is a long description
that spans multiple lines.""")
```

### Handling Plurals with ngettext

`addonHandler.initTranslation()` puts the add-on's `_`, `ngettext`, `pgettext` and `npgettext` into the calling module's globals. **Do not** write `from gettext import ngettext`. That replaces the add-on's version with the standard library one, which always returns the English string.

```python
import addonHandler
addonHandler.initTranslation()   # provides _, ngettext, pgettext, npgettext

# Context-disambiguated strings: pgettext(context, message)
label = pgettext("menu", "Open")

def announceCount(self, count):
    # Translators: Singular/plural for item count
    message = ngettext(
        "{count} item",      # Singular
        "{count} items",     # Plural
        count                # Number to check
    ).format(count=count)
    ui.message(message)

# For time durations
def announceTime(self, hours, minutes):
    parts = []
    if hours > 0:
        # Translators: Hours in time display
        parts.append(ngettext(
            "{hours} hour",
            "{hours} hours",
            hours
        ).format(hours=hours))

    # Translators: Minutes in time display
    parts.append(ngettext(
        "{minutes} minute",
        "{minutes} minutes",
        minutes
    ).format(minutes=minutes))

    ui.message(", ".join(parts))
```

### Translator Comments

```python
# Place comment IMMEDIATELY before the translated string

# Translators: Button label for starting the process
label = _("Start")

# Translators: This message appears when no items are found
# in the search results list
message = _("No items found")

@script(
    # Translators: Description shown in NVDA's input gestures dialog
    # for the command that reads the current selection
    description=_("Read selection")
)
def script_readSelection(self, gesture):
    pass
```

### Locale Folder Structure

```
locale/
├── en/
│   ├── LC_MESSAGES/
│   │   ├── nvda.po          # English translations (source)
│   │   └── nvda.mo          # Compiled binary
│   └── manifest.ini         # English add-on description
├── es/
│   ├── LC_MESSAGES/
│   │   ├── nvda.po
│   │   └── nvda.mo
│   └── manifest.ini
└── fr/
    └── ...
```

### Sample .po File

```
# Language: Spanish
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: es\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

#. Translators: Add-on summary
msgid "My Add-on"
msgstr "Mi Complemento"

#. Translators: Message when feature is enabled
msgid "Feature enabled"
msgstr "Característica habilitada"

#. Translators: Singular/plural for item count
#, python-brace-format
msgid "{count} item"
msgid_plural "{count} items"
msgstr[0] "{count} elemento"
msgstr[1] "{count} elementos"
```

---

## Dependency Management

### Bundling Dependencies

Bundle every pip package you need, even one NVDA already ships (such as `requests` or `comtypes`). NVDA's copies may be upgraded, downgraded or removed in any release. Compiled packages must be built for **CPython 3.13, 64-bit Windows** (`cp313-win_amd64` wheels), e.g. `uv pip install --python-version 3.13 --python-platform x86_64-pc-windows-msvc --target lib <pkg>`. Pure-Python packages work as-is. Since 2026.1, NVDA no longer ships `typing_extensions` and no longer bundles the Universal C Runtime.

Place dependencies in a `lib/` folder within your plugin:

```
globalPlugins/
└── myPlugin/
    ├── __init__.py
    └── lib/
        ├── requests/
        ├── urllib3/
        └── other_package/
```

### Adding Bundled Libraries to Path

```python
import os
import sys

# Get path to lib directory
addon_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(addon_dir, "lib")

# Add to path if not already there
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)  # Insert at beginning for priority

# Now import bundled libraries
import requests
```

### Optional Dependencies with Fallback

```python
import os
import sys

addon_dir = os.path.dirname(__file__)
sys.path.insert(0, addon_dir)

# Try to import optional dependency
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        if not PSUTIL_AVAILABLE:
            log.warning("psutil not available, some features disabled")

    @script(description=_("Show CPU usage"))
    def script_showCPU(self, gesture):
        if not PSUTIL_AVAILABLE:
            ui.message(_("Feature unavailable - psutil not installed"))
            return

        cpu = psutil.cpu_percent()
        ui.message(_("{percent}% CPU").format(percent=cpu))
```

### Temporary Path Manipulation

```python
# Add path, import, then remove
addon_dir = os.path.dirname(__file__)
sys.path.append(addon_dir)

from mysubmodule import something

# Clean up immediately
del sys.path[-1]
```

### installTasks.py for Setup

```python
# installTasks.py - runs during add-on installation

from logHandler import log
import os
import shutil

def onInstall():
    """Called when add-on is installed"""
    log.info("My Add-on installed")

    # Check for required files
    addon_dir = os.path.dirname(__file__)
    required_file = os.path.join(addon_dir, "data", "config.json")

    if not os.path.exists(required_file):
        from gui.message import MessageDialog
        MessageDialog.alert(
            _("Required configuration file not found. Please configure the add-on."),
            _("Setup Required"),
        )

def onUninstall():
    """Called on the NVDA restart after the user removed the add-on.
    Runs before the GUI and most components start, so it cannot ask the user anything."""
    log.info("My Add-on uninstalled")

    # Clean up config
    import config
    if "myAddon" in config.conf.spec:
        del config.conf.spec["myAddon"]
```

Notes from the developer guide:

- In `onInstall`, the add-on folder still has a `.pendingInstall` suffix. It is loaded for real only after NVDA restarts. If `onInstall` raises, the install fails and the folder is cleaned up.
- Keep `installTasks.py` light. Do not import your own `.pyd`/DLLs from it, because a loaded DLL can stop the folder from being deleted.
- Do not depend on other add-ons being present or initialised.
- Inside `installTasks.py`, the builtin `_` is NVDA's own catalogue. Call `addonHandler.initTranslation()` at the top so your strings are translated with the add-on's catalogue.

### Handling Module Conflicts

```python
# When another add-on might have a different version of a library
conflicting_libs = ["typing_extensions", "pydantic"]
original_modules = {}

# Save and remove conflicting modules
for lib in conflicting_libs:
    if lib in sys.modules:
        original_modules[lib] = sys.modules[lib]
        del sys.modules[lib]

try:
    # Import our version
    from .lib import pydantic
finally:
    # Restore original modules for other add-ons
    for lib, module in original_modules.items():
        sys.modules[lib] = module
```

---

## Configuration Management

### Config Specification Syntax

```python
confspec = {
    # Boolean with default
    "enabled": "boolean(default=True)",

    # Integer with range
    "volume": "integer(default=50, min=0, max=100)",

    # String with default
    "name": 'string(default="User")',

    # Empty string default
    "apiKey": 'string(default="")',

    # Choice from options
    "mode": 'option("auto", "manual", "disabled", default="auto")',

    # List (as string)
    "items": 'string(default="")',

    # Nested configuration
    "advanced": {
        "debug": "boolean(default=False)",
        "timeout": "integer(default=30, min=1, max=300)",
    },
}

# Register in __init__
config.conf.spec["myAddon"] = confspec
```

### Persistent config sections (NVDA 2026.3+)

`config.conf.spec[...] = ...` has to run every session before you read the section, and it only lasts for that session. Since 2026.3, `config.configSections.registerSection` stores the spec in a YAML file in the user config directory (`NVDAState.WritePaths.nvdaCustomSectionsFile`). NVDA loads it at every startup, so the section exists before any plugin runs, and profiles validate it correctly. Registering writes the file, and the section becomes active on the **next** NVDA start, so call it from `installTasks.onInstall`:

```python
# installTasks.py
def onInstall():
    from config.configSections import registerSection
    registerSection(
        "myAddon",
        {"enabled": "boolean(default=True)", "volume": "integer(default=50, min=0, max=100)"},
        isBaseOnly=False,   # True: lives only in the base config, never overridden by profiles
    )

def onUninstall():
    from config.configSections import unregisterSection
    unregisterSection("myAddon")
```

If you also support NVDA 2026.1 or 2026.2, keep the `config.conf.spec["myAddon"] = confspec` line in `__init__` as a fallback. Assigning the same spec again is harmless.

### Config extension points

```python
config.post_configProfileSwitch.register(self._onProfileSwitch)  # re-read cached values here
config.pre_configSave.register(self._beforeSave)
config.post_configSave.register(self._afterSave)
config.post_configReset.register(self._onReset)
# ...and .unregister(...) each one in terminate()
```

2026.2 added key-path helper methods on `config.conf`. They need `min`/`max` in the spec for the range-based ones:

```python
config.conf.getConfigValue("myAddon", "volume")                       # -> 50
config.conf.setConfigValue(75, "myAddon", "volume")                   # value first
config.conf.valueToPercentage("myAddon", "volume")                    # -> 0..100
config.conf.percentageToValue("myAddon", "volume", percentage=25)     # -> float
config.conf.clampedIncrementAndUpdateConfig("myAddon", "volume", step=5)  # clamped to min/max
```

### Reading and Writing Config

```python
# Read values
enabled = config.conf["myAddon"]["enabled"]
volume = config.conf["myAddon"]["volume"]
debug = config.conf["myAddon"]["advanced"]["debug"]

# Write values
config.conf["myAddon"]["enabled"] = False
config.conf["myAddon"]["volume"] = 75

# Force save
config.conf.save()
```

---

## Event Handling

### Common Events in GlobalPlugin

```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def event_gainFocus(self, obj, nextHandler):
        """Called when any object gains focus"""
        # Process the focus change
        log.debug(f"Focus: {obj.name}, Role: {obj.role}")

        # ALWAYS call nextHandler to allow other handlers to run
        nextHandler()

    def event_foreground(self, obj, nextHandler):
        """Called when a new window comes to foreground"""
        log.debug(f"Foreground: {obj.name}")
        nextHandler()

    def event_nameChange(self, obj, nextHandler):
        """Called when an object's name changes"""
        nextHandler()

    def event_valueChange(self, obj, nextHandler):
        """Called when an object's value changes"""
        nextHandler()
```

### Common Events in AppModule

```python
class AppModule(appModuleHandler.AppModule):
    def event_NVDAObject_init(self, obj):
        """Modify object properties during initialization"""
        # Fix button names
        if obj.role == controlTypes.Role.BUTTON:
            if obj.name == "\ue8bb":  # Unicode icon
                obj.name = _("Close")

    def event_gainFocus(self, obj, nextHandler):
        """App-specific focus handling"""
        nextHandler()

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        """Add custom overlay classes"""
        if obj.role == controlTypes.Role.LISTITEM:
            clsList.insert(0, EnhancedListItem)
```

### Overlay Classes for Custom Behavior

```python
from NVDAObjects.UIA import UIA

class EnhancedListItem(UIA):
    """Custom behavior for list items"""

    def initOverlayClass(self):
        """Called when overlay is applied"""
        # Add dynamic gestures
        self.bindGesture("kb:enter", "activate")
        self.bindGesture("kb:delete", "remove")

    def script_activate(self, gesture):
        self.doAction()
        ui.message(_("Activated"))

    def script_remove(self, gesture):
        ui.message(_("Item removed"))

    __gestures = {
        "kb:space": "activate",
        "kb:f2": "rename",
    }
```

---

## Hooking Into an Application

NVDA never reads pixels; it reads an accessibility tree that the application publishes. Everything an add-on does to an app — renaming buttons, reaching a list nobody can focus, reading a message the user never navigated to — is done by walking that tree. This section covers how NVDA attaches to a process, how to find elements inside it reliably, and how to explore an app while developing.

### The accessibility stack

| API | Used by | NVDAObject base class |
| :--- | :--- | :--- |
| MSAA / IAccessible (`oleacc`) | Win32, older apps | `NVDAObjects.IAccessible.IAccessible` |
| IAccessible2 | Chromium, Electron, WebView2, Firefox, LibreOffice | `NVDAObjects.IAccessible.ia2Web.Ia2Web` |
| UI Automation | WinUI/UWP, modern Win32, Office | `NVDAObjects.UIA.UIA` |
| Java Access Bridge | Swing/AWT | `NVDAObjects.JAB.JAB` |
| Display model / offscreen text | apps with no API at all | `NVDAObjects.window.DisplayModelEditableText` |

NVDA picks the API per window and wraps each element in an `NVDAObject`. Which base class you get decides which extra properties exist, so check before relying on one:

```python
from NVDAObjects.IAccessible.ia2Web import Ia2Web
from NVDAObjects.UIA import UIA

isinstance(obj, Ia2Web)   # web content: obj.IA2Attributes is available
isinstance(obj, UIA)      # obj.UIAAutomationId, obj.UIAElement are available
```

Web-based desktop apps (WhatsApp, Discord, Teams, VS Code, Spotify) expose **IAccessible2**, which puts the DOM within reach: `obj.IA2Attributes` is a dict carrying the underlying element's `tag`, `class`, `id` and `xml-roles` (its ARIA role). Those are far more stable identifiers than names, roles or tree positions.

### Attaching to a process

An app module is bound by executable name — `appModules/notepad.py` handles `notepad.exe`. When the process name does not match the module name, or one product ships several executables, register it explicitly from a global plugin:

```python
import appModuleHandler
import globalPluginHandler

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        # WhatsApp Desktop runs as WhatsApp.Root, hosting WebView2 child processes
        appModuleHandler.registerExecutableWithAppModule("WhatsApp", "whatsapp_root")
        appModuleHandler.registerExecutableWithAppModule("WhatsApp.Root", "whatsapp_root")

    def terminate(self):
        appModuleHandler.unregisterExecutable("WhatsApp")
        appModuleHandler.unregisterExecutable("WhatsApp.Root")
        super().terminate()
```

Modules inside `appModules/` whose names are not executables (`wh_utils.py`, `wh_messages.py`) are never auto-loaded; they are plain helpers imported relatively: `from .wh_utils import find_element`.

**Check for a built-in app module first** (`nvda/source/appModules/<name>.py`). NVDA puts the add-on's `appModules` folder first on the package path, so an add-on module with the same name **replaces** the built-in one. For example, NVDA 2026.x ships `appModules/whatsapp_root.py`, which sets `disableBrowseModeByDefault = True`. To keep the built-in behaviour, subclass it:

```python
from nvdaBuiltin.appModules.whatsapp_root import AppModule as BuiltinAppModule

class AppModule(BuiltinAppModule):
    ...
```

Hosted apps: for apps running inside `javaw.exe`, `wwahost.exe` or `msedgewebview2.exe`, the module name is the hosted app's name, as reported by `AppModule.appName`, not the host's name. For `wwahost` apps, subclass the built-in module: `from nvdaBuiltin.appModules.wwahost import *` and then `class AppModule(AppModule): ...`. A WebView2 app opens in browse mode by default. Set the class attribute `disableBrowseModeByDefault = True` to start in focus mode.

Once attached, three hooks shape what the user perceives:

```python
class AppModule(appModuleHandler.AppModule):
    def event_NVDAObject_init(self, obj):
        """Runs as each object is created. Cheap tweaks only - it runs constantly."""
        if obj.role == controlTypes.Role.SECTION:
            obj.role = controlTypes.Role.PANE      # stop NVDA announcing layout noise
        if obj.name:
            obj.name = obj.name.replace("", _("Close"))  # icon-font glyph

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        """Give matching objects extra behaviour: scripts, properties, events."""
        # IA2Attributes only exists on IAccessible objects - UIA objects would raise AttributeError
        if "menu-item" in ia2_attr(obj, "class"):
            clsList.insert(0, MyMenuItem)

    def event_gainFocus(self, obj, nextHandler):
        """App-wide focus policy. Always call nextHandler()."""
        nextHandler()
```

Speech can also be filtered without touching objects at all:

```python
from speech.extensions import filter_speechSequence

def _filter(sequence):
    return [item for item in sequence
            if not (isinstance(item, str) and "For more options" in item)]

filter_speechSequence.register(_filter)      # in __init__
filter_speechSequence.unregister(_filter)    # in terminate()
```

Other speech extension points in `speech.extensions`: `pre_speech` (observe what is about to be spoken; from 2027.1 handlers can also accept an `originalSpeechSequence` keyword holding the sequence before filtering), `pre_speechQueued`, `speechCanceled`, `pre_speechCanceled` and `post_speechPaused`. Since 2026.3, handlers may register or unregister handlers while the extension point is being notified.

### Walking the tree

```python
import api

focus = api.getFocusObject()          # deepest focused element
ancestors = api.getFocusAncestors()   # root -> ... -> parent of focus
fg = api.getForegroundObject()        # foreground window
nav = api.getNavigatorObject()

obj.parent, obj.firstChild, obj.lastChild, obj.next, obj.previous
obj.children                          # materialises every child at once
obj.simpleParent, obj.simpleFirstChild  # same tree with layout objects removed
```

Objects are created on demand and described by `obj.role`, `obj.states`, `obj.name`, `obj.value`, `obj.location`, `obj.windowClassName`, `obj.windowHandle`. Two NVDAObjects for the same element are different Python instances; compare them with `==`, which uses the underlying element identity.

### Identifying elements reliably

Absolute paths ("child 3 of child 4") break on the app's next render. Prefer, in order:

1. **Stable app markers** — `obj.IA2Attributes["id"]`, a semantic class the app assigns (`focusable-list-item`), `obj.UIAAutomationId`.
2. **ARIA semantics** — `obj.IA2Attributes["xml-roles"]` (`row`, `grid`, `application`, `log`), which survive restyling.
3. **Role plus geometry** — `obj.role` with `obj.location` (e.g. "the list whose left edge is under 450px" for a sidebar).
4. **Names** — last resort: they are localised and change with the interface language.

```python
def ia2_attr(obj, key, default=""):
    try:
        return obj.IA2Attributes.get(key, default) or default
    except Exception:
        return default
```

Wrap every property access. Elements vanish mid-walk and raise `COMError`, and an exception escaping an event handler or script is a broken add-on for the user.

### Budget every scan

Each property read is a cross-process COM call. A few hundred objects cost a few tenths of a second; tens of thousands freeze NVDA. So:

- **Start from a landmark**, not the document root: climb from `api.getFocusObject()` to the container you need, and fall back to a wider scan only when focus is elsewhere.
- **Prune subtrees you know are irrelevant** (a `grid` you do not care about, zero-sized nodes).
- **Stop descending at a hit** when the thing you collect never nests inside itself.
- **Cap depth and node count**, so a pathological tree cannot lock up the UI.
- **Cache the result with a short TTL**, and invalidate it on focus change.

```python
_TTL = 3.0

def _recent_items(self, force=False):
    now = time.monotonic()
    if not force and self._items and now - self._items_time < _TTL:
        return self._items
    self._items = self._scan()
    self._items_time = now
    return self._items
```

### Worked example: reading a virtualised message list

WhatsApp Desktop (WebView2) renders only the messages near the viewport, marks every navigable message with the CSS class `focusable-list-item`, and keeps the open conversation in `div#main`, beside a chat list that is an ARIA `grid`. That is enough to read the last N messages without moving focus:

```python
MESSAGE_ITEM_CLASS = "focusable-list-item"
CHAT_PANE_ID = "main"

def find_chat_pane(obj):
    # 1. Cheap path: we are probably inside the conversation already.
    current = obj
    for _ in range(30):
        if current is None:
            return None
        if ia2_attr(current, "id") == CHAT_PANE_ID:
            return current
        if current.role == controlTypes.Role.DOCUMENT:
            break
        current = current.parent
    # 2. Fallback: scan the document, pruning the chat list grid (~100 objects).
    stack, visited = [(document_of(obj), 0)], 0
    while stack and visited < 3000:
        node, depth = stack.pop()
        visited += 1
        if ia2_attr(node, "id") == CHAT_PANE_ID:
            return node
        if depth >= 16 or ia2_attr(node, "xml-roles") == "grid":
            continue
        for child in reversed(node.children or []):
            stack.append((child, depth + 1))
    return None

def collect_message_items(pane):
    # Depth first: document order is chronological order, newest last.
    items, stack, visited = [], [(pane, 0)], 0
    while stack and visited < 800:
        node, depth = stack.pop()
        visited += 1
        if MESSAGE_ITEM_CLASS in ia2_attr(node, "class"):
            items.append(node)      # messages never nest: end this branch
            continue
        if depth < 16:
            for child in reversed(node.children or []):
                stack.append((child, depth + 1))
    return items
```

Each item's `name` is the whole bubble ("Ana Hello there 21:53 Read"), so a script can speak `items[-n].name` directly. Binding one script to ten gestures keeps that to a single function:

```python
@script(
    description=_("Read one of the last ten messages (1 is the newest, 0 the tenth)"),
    gestures=["kb:alt+" + key for key in "1234567890"],
)
def script_readRecentMessage(self, gesture):
    key = getattr(gesture, "mainKeyName", None)   # "1".."0"; None for non-keyboard gestures
    position = "1234567890".find(key) if key else 0
    if position < 0:
        gesture.send()                            # not ours: let the app have it
        return
    items = self._recent_items()
    if position >= len(items):
        ui.message(_("Only {count} messages loaded").format(count=len(items)))
        return
    ui.message(items[-(position + 1)].name)
```

Note `gesture.send()`: an app module script shadows the application's own shortcut, so pass the keystroke through whenever your feature does not apply to the current context.

Two behaviours worth knowing when binding a range of keys to one script:

- `scriptHandler.getLastScriptRepeatCount()` counts repeats of the **script**, not of the gesture, so `alt+1` followed by `alt+2` registers as a double press. Track `(key, time.monotonic())` yourself for per-key double-press behaviour.
- Whatever the app virtualises is invisible to you. "The last ten messages" really means "the last ten rendered", so report the shortfall rather than pretending the list is complete.

### Exploring an app while developing

Inside NVDA:

- **Python console** (`NVDA+ctrl+z`): snapshot variables `focus`, `focusAnc`, `fg`, `nav`, `caretObj`, `caretPos`, `review`, `mouse` and `brlRegions`. Pre-imported modules are `api`, `appModules`, `braille`, `config`, `controlTypes`, `globalPlugins`, `log`, `queueHandler`, `speech`, `textInfos`, `vision`, `os`, `sys` and `wx`. Walk the tree live: `focus.parent.children`, `focus.IA2Attributes`, `[c.name for c in nav.children]`.
- **Developer info** (`NVDA+F1`): logs `obj.devInfo` for the navigator object — class list, role, states, IA2 attributes, window handle. The fastest way to learn what an element actually is.
- **Log** (NVDA menu → Tools → View log, or `%tmp%\nvda.log`): `from logHandler import log; log.info(...)`, with the log level set to Debug while developing.
- **Reload plugins** (`NVDA+ctrl+F3`) picks up edited app modules and global plugins without restarting NVDA. It does not reliably reload helper modules that were already imported — restart NVDA when in doubt.
- A throwaway script on a spare gesture that dumps a subtree to the log beats guessing.

Outside NVDA — useful to script an investigation, diff a tree between app versions, or capture a structure while someone else drives the app:

- Windows SDK tools: **`inspect.exe`** (UIA and MSAA), **AccEvent**, and **accProbe** for IAccessible2.
- Or drive the same COM interfaces NVDA uses from a standalone Python script (`pip install comtypes`). `AccessibleObjectFromWindow` returns the MSAA root of a window, and `QueryService` on any object returns `IAccessible2`, whose `attributes` string carries the DOM `tag`, `class`, `id` and `xml-roles`:

```python
import ctypes
from ctypes import POINTER, byref, c_long
from comtypes import IUnknown, GUID, COMMETHOD, HRESULT
from comtypes.automation import VARIANT
from comtypes.client import GetModule

GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible

IID_IA2 = GUID('{E89F726E-C4F4-4c19-BB19-B647D7FA8478}')

class IServiceProvider(IUnknown):
    _iid_ = GUID('{6d5140c1-7436-11ce-8034-00aa006009fa}')
    _methods_ = [COMMETHOD([], HRESULT, 'QueryService',
                           (['in'], POINTER(GUID), 'guidService'),
                           (['in'], POINTER(GUID), 'riid'),
                           (['out'], POINTER(POINTER(IUnknown)), 'obj'))]

class IAccessible2(IAccessible):
    _iid_ = IID_IA2
    # 18 vtable slots in IDL order; only get_attributes gets called, the others
    # merely need the right arity: nRelations, relation, relations, role,
    # scrollTo, scrollToPoint, groupPosition, states, extendedRole,
    # localizedExtendedRole, nExtendedStates, extendedStates,
    # localizedExtendedStates, uniqueID, windowHandle, indexInParent, locale,
    # attributes.
    _methods_ = [...]

def attributes(acc):
    sp = acc.QueryInterface(IServiceProvider)
    ia2 = sp.QueryService(IID_IA2, IID_IA2).QueryInterface(IAccessible2)
    raw = ia2.get_attributes() or ""
    return dict(part.split(":", 1) for part in raw.split(";") if ":" in part)

def children(acc):
    n = acc.accChildCount
    arr, got = (VARIANT * n)(), c_long()
    ctypes.oledll.oleacc.AccessibleChildren(acc, 0, n, arr, byref(got))
    return [v.value for v in arr[:got.value] if v.value is not None]

def root_of_window(hwnd):
    p = POINTER(IAccessible)()
    ctypes.oledll.oleacc.AccessibleObjectFromWindow(
        hwnd, 0, byref(IAccessible._iid_), byref(p))
    return p
```

For a Chromium or WebView2 app the web content is **not** under the app's own top-level window: enumerate the windows of the helper process (`msedgewebview2.exe`, or `<app>.exe --type=renderer`) and use the `Chrome_RenderWidgetHostHWND` child of `Chrome_WidgetWin_1`. `EnumWindows` + `GetClassNameW` + `GetWindowThreadProcessId` is enough to find it.

Chromium enables accessibility lazily, so keep NVDA running while investigating or the tree will be empty or partial. And expect paths to shift between runs: identify elements by their attributes, never by index.

---

## Threading and Async Operations

### Background Operations

```python
import threading
import wx

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    @script(description=_("Fetch data"))
    def script_fetchData(self, gesture):
        ui.message(_("Fetching..."))

        def doFetch():
            try:
                # Long-running operation
                result = self._performFetch()
                # Update UI on main thread
                wx.CallAfter(self._onFetchComplete, result)
            except Exception as e:
                wx.CallAfter(self._onFetchError, str(e))

        thread = threading.Thread(target=doFetch, daemon=True)
        thread.start()

    def _onFetchComplete(self, result):
        ui.message(_("Fetch complete: {result}").format(result=result))

    def _onFetchError(self, error):
        ui.message(_("Fetch failed: {error}").format(error=error))
```

### Using wx.Timer

```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self.timer = wx.Timer()
        self.timer.Bind(wx.EVT_TIMER, self.onTimer)

    def startMonitoring(self):
        self.timer.Start(1000)  # Every 1000ms

    def stopMonitoring(self):
        self.timer.Stop()

    def onTimer(self, event):
        # Periodic check
        self.checkStatus()

    def terminate(self):
        self.timer.Stop()
```

---

## Best Practices and Tips

### General Tips

1. **Always call `addonHandler.initTranslation()` early** - Before any imports that might use `_()`

2. **Always call `nextHandler()` in event handlers** - Allows other plugins to process events

3. **Use `wx.CallAfter()` for UI operations from threads** - wxPython is not thread-safe

4. **Register and unregister settings panels** - In `__init__` and `terminate`

5. **Use type hints** - Python 3.13 supports modern type hints

6. **Log appropriately** - Use `log.debug()`, `log.info()`, `log.warning()`, `log.error()`

### Accessibility Tips

1. **Provide good script descriptions** - They appear in NVDA's input gestures dialog

2. **Use `ui.message()` for important feedback** - Works with both speech and braille

3. **Support both keyboard layouts** - Desktop (numpad) and laptop layouts

4. **Test with screen reader** - Actually use NVDA to test your add-on

### Code Organization

```python
# Recommended file structure for complex add-ons
globalPlugins/
└── myAddon/
    ├── __init__.py      # GlobalPlugin class, minimal imports
    ├── gui.py           # Settings panels and dialogs
    ├── config.py        # Configuration handling
    ├── utils.py         # Utility functions
    ├── api.py           # External API interactions
    └── lib/             # Bundled dependencies
```

### Error Handling

```python
from logHandler import log

def safeOperation(self):
    try:
        result = self.riskyOperation()
        return result
    except SpecificError as e:
        log.warning(f"Expected error: {e}")
        ui.message(_("Operation failed"))
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        ui.message(_("An error occurred"))
```

### Testing Your Add-on

1. Place add-on folder in NVDA's `addons` directory, or put plugin folders (`globalPlugins`, `appModules`, …) in the user config `scratchpad` folder after enabling "Enable loading custom code from Developer Scratchpad directory" in Settings → Advanced
2. Restart NVDA, or press `NVDA+control+F3` to reload plugins
3. Check NVDA log (NVDA+N, then Tools > View Log, or `%tmp%\nvda.log`) for errors and `DeprecationWarning`s
4. Test all gestures and features
5. Test with different NVDA settings (speech, braille, etc.)

### Debugging

```python
from logHandler import log

# Different log levels
log.debug("Detailed debug info")      # Only in debug mode
log.info("General information")        # Normal operation
log.warning("Warning message")         # Potential issues
log.error("Error message")             # Errors
log.error("Error with trace", exc_info=True)  # Include stack trace
log.exception("Inside an except block")        # Same, shorter
log.debugWarning("Dev-only warning")           # Only shown at debug level
log.info(f"Clipboard: {text}", redactSecrets=True)  # 2026.2+: mask detected secrets (tokens, passwords)

# Quick audio feedback for debugging
import tones
tones.beep(440, 100)  # Frequency Hz, duration ms
```

---

## Quick Reference

### Announcing Messages

```python
import ui

from speech.priorities import Spri   # also importable as speech.Spri

ui.message("Text to speak")                            # Speech + braille
ui.message("Text", speechPriority=Spri.NOW)            # Interrupt current speech, then resume it
ui.message("Text", speechPriority=Spri.NEXT)           # Speak after the current utterance
ui.message("Spoken", brailleText="Brailled")           # Different braille text
ui.reviewMessage("Text")                               # Braille only if tethered to review
ui.browseableMessage("Long text", _("Title"), copyButton=True, closeButton=True)  # Read-only window
speech.speakMessage("Direct speech")                   # Speech only
braille.handler.message("Braille")                     # Braille only (braille.handler may be None very early in startup)
```

### Accessing Objects

```python
import api

focus = api.getFocusObject()          # Currently focused object
nav = api.getNavigatorObject()        # Navigator object
fg = api.getForegroundObject()        # Foreground window
desktop = api.getDesktopObject()      # Desktop
```

### Clipboard

```python
import api

api.copyToClip("Text to copy")                 # Copy to clipboard, returns bool
api.copyToClip("Text to copy", notify=True)    # ...and announce "Copied to clipboard: <text>"
text = api.getClipData()                       # Get clipboard text
```

### Playing Sounds

```python
import tones
import nvwave

tones.beep(440, 100)                  # Simple beep
nvwave.playWaveFile("path/to/file.wav")  # Play WAV file
```

### Restarting NVDA

```python
import core

core.restart()                        # Restart NVDA
core.restart(disableAddons=True)      # Restart without add-ons
core.callLater(500, func, *args)      # Run func on the main thread after 500 ms
```

---

## NVDA API Change Log for Add-on Authors

These are the changes that matter to add-ons. They are extracted from `user_docs/en/changes.md` (the "Changes for Developers" sections) at the [tracked commit](#tracked-nvda-source). Only add-on-relevant entries are kept: build-tool bumps and internal driver refactors are left out. When you move the tracked commit, add the new entries at the top of this section.

### 2027.1 (dev, master at `c22a5093`) — **Add-on API breaking release**

- `BACK_COMPAT_TO = 2027.1`: every add-on must set `lastTestedNVDAVersion = 2027.1` or it is disabled.
- wxPython 4.3.1 (wxWidgets 3.3.3). APIs that wxWidgets deprecated in 3.0 have been removed. Re-test every dialog.
- Planned (not yet in the source tree at this commit): Python 3.14 (see `addonAPIVersion.py`).
- `keyboardHandler.KeyboardInputGesture.fromName`: the non-modifier key is the main key wherever it appears. It raises `ValueError` on unknown, empty or multi-main-key names.
- `speech.extensions.pre_speech` handlers may accept an `originalSpeechSequence=` keyword (the sequence before filtering).
- Removed: `gui.nvdaControls.CustomCheckListBox.notifyIAccessible`, `config.isAppX`, `gui.blockAction.Context.WINDOWS_STORE_VERSION`, `winKernel.PROCESS_ALL_ACCESS` / `PROCESS_VM_OPERATION` / `PROCESS_VM_READ` / `PROCESS_VM_WRITE`.
- `hwIo.base.IoBase.write` raises `OSError` on failure instead of returning silently.
- Deprecated: `winKernel.DUPLICATE_SAME_ACCESS`, `GENERIC_READ` / `GENERIC_WRITE`, `PROCESS_QUERY_INFORMATION` / `PROCESS_TERMINATE`. Use `winBindings.kernel32.DUPLICATE.SAME_ACCESS`, `GENERIC.READ` / `GENERIC.WRITE` and `PROCESS.QUERY_INFORMATION` / `PROCESS.TERMINATE` instead. `NVDAObjects.UIA.wordDocument.getCommentInfoFromPosition` / `getPresentableCommentInfoFromPosition` are also deprecated.

### 2026.3 (beta)

- Python 3.13.15. comtypes 1.4.16, pywin32 312, requests 2.34.2.
- **New:** `config.configSections.registerSection(name, spec, isBaseOnly=False)` and `unregisterSection(name)` register persistent config sections from `installTasks` (see [Persistent config sections](#persistent-config-sections-nvda-20263)).
- **New:** `gui.message.HtmlMessageDialog` displays a full HTML document in a WebView. Navigating to `nvda-action://<name>` URLs triggers actions; register them with `registerAction(name, handler)`. `MessageDialog` gained the `_createMessageControl` and `_wrapMessageControl` hooks.
- **`braille` is now a package** (`braille.constants`, `.labels`, `.formatting`, `.regions`, `.display`, `.buffers`, `.brailleHandler`, `.extensions`), and `brailleInput` moved to `braille.input`. The old `braille.X` / `brailleInput.X` names still work but log deprecation warnings. The [Moved / renamed modules](#moved--renamed-modules-to-import-from-their-new-location) table lists the common ones, and `changes.md` has the full table.
- `braille.BrailleDisplayGesture.cellIndexes` (list) replaces `routingIndex`, and multi-cell gestures use the id `"multiRouting"` (`BrailleDisplayGesture.idForCellCount(n)`).
- Touch: two-flick sequences (`flickRightThenLeft`, …) and edge gestures (`left_`, `right_`, `top_`, `bottom_` prefixes). `touchTracker.TouchAction`, `touchTracker.TouchEdge` and `touchHandler.TouchMode` enums replace the `action_*` constants and `touchModeLabels`. Add-ons may append custom mode names to `touchHandler.availableTouchModes`.
- Extension points: handlers may now (un)register handlers while the point is being notified.
- `inputCore.decide_handleRawKey` handlers receive an `injected=` keyword (True for software-injected keys).
- `vision.handler.extensionPoints.post_mathNavigation` was added. `mathPres.interactWithMathMl` takes an optional `sourceObj`.
- `OffsetsTextInfo` supports `textInfos.UNIT_SENTENCE` (via ICU). `locationHelper.RectLTWH` / `RectLTRB` gained `.union(...)`.
- `louisHelper` is the only braille translation entry point. `louisHelper.TranslationMode`, `louisHelper.Typeform` and `louisHelper.backTranslate` were added.
- `languageHandler.windowsLCIDToLocaleName` now uses Windows' names, so some locales change (e.g. `zh_CN` instead of `zh_CHS`, `sr_LATN_CS` instead of `sr_SP`).
- New `hwIo.ble` (Bluetooth LE): a `Scanner` with a `deviceDiscovered` extension point, a `Ble` I/O class and `findDeviceByAddress`.
- Deprecated: the `ui.URL_MK_UNIFORM` / `DIALOG_OPTIONS` / `HTMLDLG_*` constants (use `HtmlMessageDialog`), `languageHandler.LCIDS_TO_TRANSLATED_LOCALES`, `OffsetsTextInfo.useUniscribe` (use `charSegFlag` / `wordSegFlag`), the `braille.wordWrap` config key (now `braille.textWrap`), `brailleInput.LOUIS_DOTS_IO_START` and `brailleDisplayDrivers.freedomScientific.RoutingGesture`.

### 2026.2 (current stable)

- Python 3.13.13.
- `log.<level>(..., redactSecrets=True)` masks secrets. There is also a new `DEBUG_UNREDACTED` log level.
- `config.conf.getConfigValue` / `setConfigValue` / `valueToPercentage` / `percentageToValue` / `clampedIncrementAndUpdateConfig` were added. `braille.handler.autoScroll` was added.
- `browseMode.BrowseModeDocumentTreeInterceptor` subclasses should override `_toggleScreenLayout` rather than `script_toggleScreenLayout`.
- `UIA.UIA._getUIACacheablePropertyValue_handlesCOMErrors(..., onError=...)` was added.
- Deprecated: the `speechDictHandler.ENTRY_TYPE_*` constants (use `speechDictHandler.types.EntryType`). `SpeechDictEntry` and `SpeechDict` moved to `speechDictHandler.types`. `speechDictHandler.dictionaries` and `dictTypes` are deprecated with no replacement.

### 2026.1 — **Add-on API breaking release** (`BACK_COMPAT_TO = 2026.1`)

- **NVDA is 64-bit, Python 3.13.** Every bundled DLL or `.pyd` must be x64. `typing_extensions` was removed, and the UCRT is no longer bundled.
- Manifest: new `changelog` key (Markdown).
- wxPython 4.2.4, comtypes 1.4.13.
- `api.fakeNVDAObjectClasses` and `api.isFakeNVDAObject(obj)` were added.
- `TextInfo.collapse()` and `OffsetsTextInfo.move()` behaviour fixes (they could previously move to the wrong place).
- `NVDAHelper.localLib` is a module now. Use `NVDAHelper.localLib.dll` for the `CDLL`.
- `copyrightYears` and `url` moved from `versionInfo` to `buildVersion`.
- Removed: the `[documentFormatting][reportSpellingErrors]` key (use `reportSpellingErrors2`), `speech.speech.IDT_TONE_DURATION` (use `getIndentToneDuration()`), `gui.nvdaControls.TabbableScrolledPanel` (use `wx.lib.scrolledpanel.ScrolledPanel`), `NVDAObjects.window.GhostWindowFromHungWindow`, `UIAHandler.autoSelectDetectionAvailable`, `winVersion.isFullScreenMagnificationAvailable`, `comInterfaces.MathPlayer` / `mathPres.mathPlayer`, `GeneralSettingsPanel.LOG_LEVELS` (use `config.configFlags.LoggingLevel`) and several `appModules.explorer` classes.
- `config.conf["vision"]["screenCurtain"]` became `config.conf["screenCurtain"]`. The `visionEnhancementProviders.screenCurtain` module became the `screenCurtain` package, and its symbols are private.
- SAPI: `sapi4` was removed (use `sapi4_32`). `sapi5` is now 64-bit SAPI 5, and `sapi5_32` is the 32-bit one.
- The `ftdi2` module became the `ftd2xx` package, with renamed functions and enums.
- Win32 bindings moved to `winBindings.*` (`user32`, `kernel32`, `gdi32`, `shell32`, `advapi32`, `setupapi`, `cfgmgr32`, `hid`, `bthprops`, `crypt32`, `mmeapi`). The old locations in `winUser`, `winKernel`, `winGDI`, `shellapi`, `hwPortUtils`, `nvwave` and `updateCheck` are deprecated.
- Deprecated: `addonHandler.BUNDLE_EXTENSION` / `NVDA_ADDON_PROG_ID` (now in `config.registry`), `addonHandler.stateFilename` (use `STATE_FILENAME`), `AddonsState.fromPickledDict` (use `fromDict`), and `winVersion.WIN81`.

### Older deprecations still present (they can be removed in any API-breaking release)

- `gui.messageBox`, `gui.message.messageBox`, `gui.runScriptModalDialog` and `gui.nvdaControls.MessageDialog` were deprecated in 2025.1: use `gui.message.MessageDialog`.
- Importing `SettingsPanel`, `AutoSettingsMixin` or `ExecAndPump` from `gui` logs a warning. Import them from `gui.settingsDialogs` (and `systemUtils` for `ExecAndPump`).
