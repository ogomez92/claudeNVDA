# ClauVDA NVDA Add-on - Custom wx Event for Thread Communication
# -*- coding: utf-8 -*-

import wx

# Event ID for result events
EVT_RESULT_ID = wx.NewIdRef()

def EVT_RESULT(win, func):
    """Bind a result event handler."""
    win.Connect(-1, -1, EVT_RESULT_ID, func)

class ResultEvent(wx.PyEvent):
    """Event to carry result data from worker threads to UI."""

    def __init__(self, data=None):
        wx.PyEvent.__init__(self)
        self.SetEventType(EVT_RESULT_ID)
        self.data = data
