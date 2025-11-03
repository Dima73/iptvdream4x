# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Installs dependencies to the box"""

from __future__ import print_function

import os
import sys

py3 = False
if sys.version_info[0] >= 3:
	py3 = True

from Screens.MessageBox import MessageBox
from Components.Console import Console
from Components.config import config, ConfigInteger, ConfigSubsection

try:
	from .loc import translate as _
except ImportError as e:
	def _(text):
		return text

from .layer import enigma2Qt

pluginConfig = config.plugins.IPtvDream = ConfigSubsection()

# Revision of applied provision (setup) tasks
pluginConfig.provision_r = ConfigInteger(0)


def trace(*args):
	print("[IPtvDream] Provision:", *args)


def commandExists(command):
	"""
	:param str command: executable
	:return bool: check that executable exists in $PATH
	"""
	return any(os.access(os.path.join(path, command), os.X_OK) for path in os.environ["PATH"].split(os.pathsep))


class ConsoleTask(object):
	def __init__(self, cmd):
		self.cmd = cmd
		self.console = Console()

	def run(self, callback):
		def finished(result, retval, extra_args=None):
			callback((result, retval))
		self.console.ePopen(self.cmd, finished)


class ScreenTask(object):
	def __init__(self, session, screen, *args, **kwargs):
		self.session = session
		self.screen = screen
		self.args = args
		self.kwargs = kwargs

	def run(self, callback):
		def closed(ret):
			trace("Screen closed", ret)
			callback(ret)
		self.session.openWithCallback(closed, self.screen, *self.args, **self.kwargs)


class ProvisionScreen(MessageBox):
	def __init__(self, session):
		MessageBox.__init__(self, session, _("Setup"), MessageBox.TYPE_INFO, enable_input=False)
		self.errors = []
		self.onShown.append(self.start)

	@classmethod
	def provisionRequired(cls):
		return pluginConfig.provision_r.value < cls.REVISION

	@classmethod
	def updateRevision(cls):
		pluginConfig.provision_r.value = cls.REVISION
		pluginConfig.provision_r.save()

	# We use generators magic below

	def start(self):
		self.onShown.remove(self.start)

		trace("start setup")
		gen = self.taskGenerator()

		def runNext(result):
			try:
				gen.send(result).run(callback=runNext)
			except StopIteration:
				return
		return runNext(None)

	REVISION = 1  # Increase when you change provision tasks

	def taskGenerator(self):
		errors = 0

		self["text"].setText(_("Updating package list, please wait ..."))
		result, retval = yield ConsoleTask("opkg update")
		if retval != 0:
			errors += 1
			yield ScreenTask(self.session, MessageBox, _("Failed to update package list!") + " (ret=%d)\n%s" % (retval, result), MessageBox.TYPE_WARNING, timeout=5)

		self["text"].setText(_("Checking depends"))
		install_list = []

		try:
			import json
		except ImportError as e:
			trace(e)
			install_list.append("python-json")

		try:
			import subprocess
		except ImportError as e:
			trace(e)
			install_list.append("python-subprocess")

		try:
			import six
		except ImportError as e:
			trace(e)
			if not py3:
				install_list.append("python-six")
			else:
				install_list.append("python3-six")

		if not enigma2Qt and not commandExists("exteplayer3"):
			install_list.append("exteplayer3")

		for pkg in install_list:
			self["text"].setText(_("Installing %s") % pkg)
			result, retval = yield ConsoleTask("opkg install %s" % pkg)
			if retval != 0:
				errors += 1
				yield ScreenTask(self.session, MessageBox, _("Failed to install %s!") % pkg + " (ret=%d)\n%s" % (retval, result), MessageBox.TYPE_WARNING, timeout=5)
		if not enigma2Qt:
			try:
				from Plugins.SystemPlugins.ServiceApp import serviceapp_client
			except ImportError as e:
				trace(e)
				self["text"].setText(_("Installing %s") % "eServiceApp")
				result, retval = yield ConsoleTask("opkg install enigma2-plugin-systemplugins-serviceapp")
				if retval != 0:
					result, retval = yield ConsoleTask("opkg install enigma2-plugin-extensions-serviceapp")
					if retval != 0:
						errors += 1
						yield ScreenTask(self.session, MessageBox, _("Failed to install %s!") % "eServiceApp" + " (ret=%d)\n%s" % (retval, result), MessageBox.TYPE_WARNING, timeout=5)

		self["text"].setText(_("Finished!"))
		if errors == 0:
			yield ScreenTask(self.session, MessageBox, _("Setup finished without errors."), MessageBox.TYPE_INFO, timeout=5)
		else:
			yield ScreenTask(self.session, MessageBox, _("Setup finished with %d errors.") % errors, MessageBox.TYPE_WARNING)

		self.updateRevision()
		trace("Finished.")
		self.close()
