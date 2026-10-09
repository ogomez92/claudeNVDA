# ClauVDA NVDA Add-on - Computer use speech capture
# -*- coding: utf-8 -*-

"""Record what NVDA speaks, for the screen-reader testing mode.

A handler on ``speech.extensions.filter_speechSequence`` sees every sequence
just before it reaches the synthesizer, which is exactly what a blind user
hears. It records the text while a capture window is open and always returns
the sequence unchanged.
"""

import threading

from logHandler import log
from speech.extensions import filter_speechSequence

_lock = threading.Lock()
_buffer: list[str] = []
_capturing = False
_registered = False


def _filter_speech(speech_sequence, **kwargs):
    if _capturing:
        text = " ".join(item for item in speech_sequence if isinstance(item, str)).strip()
        if text:
            with _lock:
                _buffer.append(text)
    return speech_sequence


def register() -> None:
    """Start listening to NVDA's speech (idempotent)."""
    global _registered
    if not _registered:
        filter_speechSequence.register(_filter_speech)
        _registered = True


def unregister() -> None:
    """Stop listening to NVDA's speech."""
    global _registered, _capturing
    _capturing = False
    if _registered:
        try:
            filter_speechSequence.unregister(_filter_speech)
        except Exception:
            log.debugWarning("Could not unregister the speech filter", exc_info=True)
        _registered = False


def begin_capture() -> None:
    """Open a capture window, discarding anything captured before."""
    global _capturing
    with _lock:
        _buffer.clear()
    _capturing = True


def end_capture() -> str:
    """Close the capture window and return what NVDA spoke while it was open."""
    global _capturing
    _capturing = False
    with _lock:
        text = "\n".join(_buffer)
        _buffer.clear()
    return text


def is_capturing() -> bool:
    """Whether a capture window is open.

    The add-on's own announcements are suppressed meanwhile, so they are not
    reported to Claude as if the application had said them.
    """
    return _capturing
