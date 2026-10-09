# ClauVDA NVDA Add-on - Computer use
# -*- coding: utf-8 -*-

"""Let Claude operate the desktop through screenshots, mouse and keyboard.

Claude sees screenshots of the whole desktop and asks for actions through the
computer toolset (``computer_toolset_20260801``). The actions run through
NVDA's own mouse and keyboard facilities, and in screen-reader testing mode
Claude also hears what NVDA said after each action.

Needs NVDA 2026.1 or later (64-bit), because input injection uses
``winBindings``.
"""
