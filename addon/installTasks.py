# ClauVDA NVDA Add-on - Installation Tasks
# -*- coding: utf-8 -*-
"""
This module runs during add-on installation and uninstallation.
"""

import os
from logHandler import log


def onInstall():
	"""Called when the add-on is installed."""
	log.info("ClauVDA add-on installed")


def onUninstall():
	"""Called when the add-on is uninstalled."""
	log.info("ClauVDA add-on uninstalled")

	# Clean up configuration
	try:
		import config

		if "ClauVDA" in config.conf:
			del config.conf["ClauVDA"]
	except Exception as e:
		log.warning(f"Could not clean up config: {e}")

	# Clean up data directory
	try:
		import globalVars
		import shutil

		data_dir = os.path.join(globalVars.appArgs.configPath, "ClauVDA")
		if os.path.exists(data_dir):
			# Ask user if they want to keep their data
			import gui
			import wx

			result = gui.messageBox(
				"Do you want to delete your ClauVDA add-on data?\n"
				"(API key and conversation history)",
				"ClauVDA Add-on Uninstall",
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
			)

			if result == wx.YES:
				shutil.rmtree(data_dir)
				log.info("ClauVDA data directory deleted")
	except Exception as e:
		log.warning(f"Could not clean up data: {e}")
