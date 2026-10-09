# ClauVDA NVDA Add-on - Computer use input
# -*- coding: utf-8 -*-

"""Turn Claude's computer actions into real input through NVDA.

* Mouse motion and clicks go through :mod:`mouseHandler`, so NVDA also
  announces the object under the pointer and honours swapped mouse buttons.
* Key presses reuse :class:`keyboardHandler.KeyboardInputGesture`, so Claude's
  key names resolve exactly as NVDA resolves its own gestures.
* Text is typed with ``SendInput`` Unicode key events.

Claude names keys in the xdotool style of its reference environment
(``Return``, ``Page_Down``, ``ctrl+shift+t``); :func:`to_nvda_key_name` maps
them to NVDA names.

Everything here injects input and must run on NVDA's main thread.
"""

import struct
import time

import mouseHandler
import winUser
from keyboardHandler import VK_WIN, KeyboardInputGesture
from logHandler import log
from winBindings.user32 import INPUT, INPUT_TYPE, KEYBDINPUT, KEYEVENTF

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12  # Alt
_VK_LWIN = 0x5B

_MODIFIER_VK = {
    "shift": _VK_SHIFT,
    "ctrl": _VK_CONTROL,
    "control": _VK_CONTROL,
    "alt": _VK_MENU,
    "option": _VK_MENU,
    "super": _VK_LWIN,
    "win": _VK_LWIN,
    "windows": _VK_LWIN,
    "cmd": _VK_LWIN,
    "command": _VK_LWIN,
    "meta": _VK_LWIN,
}

_MODIFIER_NAME = {
    "ctrl": "control",
    "control": "control",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "super": "windows",
    "win": "windows",
    "windows": "windows",
    "cmd": "windows",
    "command": "windows",
    "meta": "windows",
}

# xdotool key names to NVDA key names. Single characters and function keys are
# handled generically.
_KEY_NAME = {
    "return": "enter",
    "enter": "enter",
    "kp_enter": "numpadEnter",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "escape": "escape",
    "esc": "escape",
    "up": "upArrow",
    "down": "downArrow",
    "left": "leftArrow",
    "right": "rightArrow",
    "page_up": "pageUp",
    "pageup": "pageUp",
    "prior": "pageUp",
    "page_down": "pageDown",
    "pagedown": "pageDown",
    "next": "pageDown",
    "home": "home",
    "end": "end",
    "insert": "insert",
    "menu": "applications",
    "apps": "applications",
    "caps_lock": "capsLock",
    "num_lock": "numLock",
    "scroll_lock": "scrollLock",
    "print": "printScreen",
    "printscreen": "printScreen",
    "sys_req": "printScreen",
    "pause": "pause",
    "minus": "-",
    "plus": "plus",
    "equal": "=",
    "period": ".",
    "comma": ",",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
    "bracketleft": "[",
    "bracketright": "]",
    "kp_add": "numpadPlus",
    "kp_subtract": "numpadMinus",
    "kp_multiply": "numpadMultiply",
    "kp_divide": "numpadDivide",
    "kp_decimal": "numpadDecimal",
}


def _map_key_part(part: str) -> str:
    lower = part.lower()
    if lower in _MODIFIER_NAME:
        return _MODIFIER_NAME[lower]
    if len(part) == 1:
        # NVDA resolves characters with the current keyboard layout.
        return part
    if lower in _KEY_NAME:
        return _KEY_NAME[lower]
    if lower.startswith("f") and lower[1:].isdigit():
        return lower
    if lower.startswith("kp_") and lower[3:].isdigit():
        return "numpad" + lower[3:]
    return lower


def to_nvda_key_name(combo: str) -> str:
    """Convert a Claude key combination (``ctrl+Page_Down``) to an NVDA gesture name."""
    combo = combo.strip()
    if combo.endswith("++") or combo == "+":
        # The main key is "+" itself, as in "ctrl++".
        parts = [p for p in combo[:-1].split("+") if p] + ["plus"]
    else:
        parts = [p for p in combo.split("+") if p]
    if not parts:
        raise ValueError("No key given")
    return "+".join(_map_key_part(p) for p in parts)


def _modifier_vks(text: str | None) -> list[int]:
    if not text:
        return []
    vks = []
    for name in text.replace(" ", "").split("+"):
        vk = _MODIFIER_VK.get(name.lower())
        if vk is not None:
            vks.append(vk)
    return vks


def _hold_modifiers(vks: list[int]) -> None:
    for vk in vks:
        winUser.keybd_event(vk, 0, 0, 0)


def _release_modifiers(vks: list[int]) -> None:
    for vk in reversed(vks):
        winUser.keybd_event(vk, 0, KEYEVENTF.KEYUP, 0)


def move_cursor(display, coordinate) -> None:
    """Move the pointer to a screenshot coordinate and let NVDA report the target."""
    screen_x, screen_y = display.to_screen(coordinate[0], coordinate[1])
    winUser.setCursorPos(screen_x, screen_y)
    try:
        mouseHandler.executeMouseMoveEvent(screen_x, screen_y)
    except Exception:
        log.debugWarning("executeMouseMoveEvent failed", exc_info=True)


def _move_if_given(display, coordinate) -> None:
    # The toolset makes the coordinate optional: without one, act where the
    # pointer already is.
    if coordinate is not None:
        move_cursor(display, coordinate)


def _primary_flags():
    return mouseHandler.getLogicalButtonFlags()


def click(display, coordinate, button: str, count: int = 1, modifiers: str | None = None) -> None:
    """Click ``count`` times with ``button`` at ``coordinate`` (or the pointer)."""
    _move_if_given(display, coordinate)
    vks = _modifier_vks(modifiers)
    _hold_modifiers(vks)
    try:
        for index in range(count):
            if button == "left":
                mouseHandler.doPrimaryClick()
            elif button == "right":
                mouseHandler.doSecondaryClick()
            else:
                mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_MIDDLEDOWN, 0, 0)
                mouseHandler.executeMouseEvent(winUser.MOUSEEVENTF_MIDDLEUP, 0, 0)
            if index < count - 1:
                time.sleep(0.05)
    finally:
        _release_modifiers(vks)


def mouse_down(display, coordinate=None) -> None:
    """Press and hold the primary button at ``coordinate`` (or the pointer)."""
    _move_if_given(display, coordinate)
    mouseHandler.executeMouseEvent(_primary_flags().primaryDown, 0, 0)


def mouse_up(display, coordinate=None) -> None:
    """Release the primary button at ``coordinate`` (or the pointer)."""
    _move_if_given(display, coordinate)
    mouseHandler.executeMouseEvent(_primary_flags().primaryUp, 0, 0)


def drag(display, start, end, modifiers: str | None = None) -> None:
    """Press at ``start``, move to ``end``, then release."""
    flags = _primary_flags()
    vks = _modifier_vks(modifiers)
    _hold_modifiers(vks)
    try:
        move_cursor(display, start)
        mouseHandler.executeMouseEvent(flags.primaryDown, 0, 0)
        time.sleep(0.05)
        move_cursor(display, end)
        time.sleep(0.05)
        mouseHandler.executeMouseEvent(flags.primaryUp, 0, 0)
    finally:
        _release_modifiers(vks)


def scroll(display, coordinate, direction: str, amount: int, modifiers: str | None = None) -> None:
    """Scroll ``amount`` wheel clicks at ``coordinate`` (or the pointer)."""
    if direction not in ("up", "down", "left", "right"):
        raise ValueError(f"Unknown scroll direction: {direction}")
    _move_if_given(display, coordinate)
    steps = max(1, int(amount)) * winUser.WHEEL_DELTA
    vks = _modifier_vks(modifiers)
    _hold_modifiers(vks)
    try:
        if direction == "up":
            mouseHandler.scrollMouseWheel(steps, True)
        elif direction == "down":
            mouseHandler.scrollMouseWheel(-steps, True)
        elif direction == "right":
            mouseHandler.scrollMouseWheel(steps, False)
        else:
            mouseHandler.scrollMouseWheel(-steps, False)
    finally:
        _release_modifiers(vks)


def type_text(text: str) -> None:
    """Type a Unicode string with SendInput Unicode key events."""
    if not text:
        return
    # UTF-16 code units, so characters outside the BMP go as surrogate pairs.
    encoded = text.encode("utf-16-le")
    code_units = struct.unpack(f"<{len(encoded) // 2}H", encoded)
    inputs = []
    for unit in code_units:
        for extra_flag in (0, KEYEVENTF.KEYUP):
            key_input = INPUT(type=INPUT_TYPE.KEYBOARD)
            key_input.ii.ki = KEYBDINPUT(wScan=unit, dwFlags=KEYEVENTF.UNICODE | extra_flag)
            inputs.append(key_input)
    winUser.SendInput(inputs)


def press_key(combo: str, repeat: int = 1) -> None:
    """Press a key or combination (``ctrl+s``) ``repeat`` times."""
    gesture = KeyboardInputGesture.fromName(to_nvda_key_name(combo))
    for index in range(max(1, min(int(repeat), 100))):
        if index:
            time.sleep(0.02)
        gesture.send()


def _resolve_modifier_vk(vk):
    # generalizedModifiers uses the VK_WIN sentinel for the Windows key; NVDA's
    # own send() maps it to VK_LWIN before injecting, so do the same.
    return winUser.VK_LWIN if vk == VK_WIN else vk


def key_combo_down(combo: str) -> KeyboardInputGesture:
    """Press and keep holding a key combination; returns the gesture to release."""
    gesture = KeyboardInputGesture.fromName(to_nvda_key_name(combo))
    for vk, extended in gesture.generalizedModifiers:
        winUser.keybd_event(_resolve_modifier_vk(vk), 0, extended, 0)
    winUser.keybd_event(gesture.vkCode, gesture.scanCode, gesture.isExtended, 0)
    return gesture


def key_combo_up(gesture: KeyboardInputGesture) -> None:
    """Release a combination pressed with :func:`key_combo_down`."""
    winUser.keybd_event(gesture.vkCode, gesture.scanCode, gesture.isExtended + KEYEVENTF.KEYUP, 0)
    for vk, extended in gesture.generalizedModifiers:
        winUser.keybd_event(_resolve_modifier_vk(vk), 0, extended + KEYEVENTF.KEYUP, 0)
