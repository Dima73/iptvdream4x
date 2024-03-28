# -*- coding: utf-8 -*-
# enigma2 IPtvDream player framework
#
#  Copyright (c) 2018 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

# enigma2 imports
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.Standby import TryQuitMainloop
from Tools.BoundFunction import boundFunction

# plugin imports
from .dist import NAME, TITLE
try:
	from .loc import translate as _
except ImportError:
	def _(text):
		return text

try:
	from .server import startApiProxy
	startApiProxy()
except Exception as e:
	print("[IPtvDream] Can't start server", e)


def checkUpdate(session, callback):
	try:
		from .updater import UpdaterScreen
	except ImportError as e:
		print("[IPtvDream] critical error!")
		import traceback
		traceback.print_exc()
		return session.open(MessageBox, _("IPtvDream critical error") + "\n" + str(e), MessageBox.TYPE_ERROR)

	def reboot(ret):
		session.open(TryQuitMainloop, retvalue=3)

	def run(updated):
		if updated:
			print("[IPtvDream] restart after update")
			return session.openWithCallback(
					reboot, MessageBox, _("Restarting enigma2 after IPtvDream update..."),
					MessageBox.TYPE_INFO, timeout=3)
		else:
			callback()

	session.openWithCallback(run, UpdaterScreen)


def provision(session, run):
	from .provision import ProvisionScreen
	if ProvisionScreen.provisionRequired():
		session.openWithCallback(run, ProvisionScreen)
	else:
		run()


def pluginRun(name, session, **kwargs):
	def run():
		from .manager import runner
		runner.runPlugin(session, name)
	#checkUpdate(session, lambda: provision(session, run))
	provision(session, run)


def managerRun(session, **kwargs):
	def run():
		from .manager import runner
		runner.runManager(session)
	#checkUpdate(session, lambda: provision(session, run))
	provision(session, run)


def makeMenuEntry(name, playlist_name, menuid):
	if menuid == "mainmenu":
		# title, function, id, priority
		return [(playlist_name or name, boundFunction(pluginRun, name), "iptvdream_%s" % name, -1)]
	else:
		return []


def makeExtensionsFunc(name):
	return lambda session, **kwargs: pluginRun(name, session, **kwargs)


def Plugins(path, **kwargs):
	plugins = []
	try:
		from .manager import manager
		for p in manager.getList():
			name = p['name']
			if manager.getConfig(name).in_menu.value:
				plugins += [
					PluginDescriptor(
						name=p['name'], description="IPtvDream plugin by technic", icon="%s.png" % name,
						where=PluginDescriptor.WHERE_MENU, fnc=boundFunction(makeMenuEntry, name, manager.getConfig(name).playlist_name.value))
				]
			if manager.getConfig(name).in_extensions.value:
				plugins += [
					PluginDescriptor(
						name=manager.getConfig(name).playlist_name.value or p['name'], description="IPtvDream plugin by technic", icon="%s.png" % name,
						where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=makeExtensionsFunc(name))
				]
	except Exception as e:
		print("[IPtvDream] error loading plugins:", e)

	if NAME == 'all':
		plugins += [
			PluginDescriptor(
				name="IPtvDream", description=_("Show all iptv providers"),
				where=PluginDescriptor.WHERE_PLUGINMENU, fnc=managerRun, icon="IPtvDream.png")
		]
	else:
		plugins += [
			PluginDescriptor(
				name=TITLE, description="IPtvDream plugin by technic", icon="logo/%s.png" % NAME,
				where=PluginDescriptor.WHERE_PLUGINMENU, fnc=boundFunction(pluginRun, NAME)),
		]

	return plugins
