# -*- coding: utf-8 -*-
#
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2018 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

# system imports
import os
from time import mktime

try:
	from typing import Optional
except ImportError:
	pass

# enigma2 imports
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.InputBox import InputBox
from Screens.ChoiceBox import ChoiceBox
from Screens.MinuteInput import MinuteInput
from Components.ConfigList import ConfigListScreen
from Components.config import config, configfile, ConfigSubsection, ConfigSubDict,\
	ConfigText, ConfigYesNo, ConfigSelection, ConfigInteger, ConfigClock
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Input import Input
from Components.Sources.List import List
from Tools.Directories import resolveFilename, SCOPE_CURRENT_PLUGIN, SCOPE_SKIN
from Tools.Import import my_import
from Tools.LoadPixmap import LoadPixmap
from enigma import getDesktop
from skin import loadSkin

# plugin imports
from .dist import VERSION
from .provision import pluginConfig
from .common import ConfigNumberText
from .utils import trace, APIException, APILoginFailed
from .loc import translate as _
from .settings import IPtvDreamConfig, IPtvDreamWebConfig, SettingsRepository, WebConfig
from .main import IPtvDreamStreamPlayer, IPtvDreamChannels

PLAYERS = [("1", "enigma2 TS (1:)"), ("4097", "Gstreamer/ServiceHisilicon (4097:)"), ("5002", "exteplayer3 (5002:)")]
KEYMAPS = [("enigma", "enigma"), ("neutrino", "neutrino")]
# 4097:0:1:0:0:0:0:0:0:1:URL:NAME (buffering enabled)
# 4097:0:1:0:0:0:0:0:0:3:URL:NAME (progressive download and buffering enabled)
BUFFERING = [("0", _("no")), ("1", _("yes - only Gstreamer (4097:)")), ("3", _("yes and progressive download - only Gstreamer (hard drive is required /hdd/movie)"))]
pluginConfig.keymap_type = ConfigSelection(KEYMAPS)
pluginConfig.show_event_progress_in_servicelist = ConfigYesNo(default=True)
pluginConfig.show_number_in_servicelist = ConfigYesNo(default=False)
pluginConfig.alternative_number_in_servicelist = ConfigYesNo(default=False)
pluginConfig.ok_open_servicelist = ConfigYesNo(default=False)
pluginConfig.numbers_history = ConfigInteger(10, (1, 30))
pluginConfig.default_start_time_archive = ConfigClock(default=mktime((1970, 1, 1, 2, 0, 0, 0, 0, 0))) # 02:00


class TimeInput(ConfigListScreen, Screen):
	skin = """<screen name="TimeInput" position="center,center" size="400,200" title="Time input">
		<ePixmap pixmap="buttons/red.png" position="10,0" size="140,40" alphatest="on"/>
		<ePixmap pixmap="buttons/green.png" position="250,0" size="140,40" alphatest="on"/>
		<widget source="key_red" render="Label" position="10,0" zPosition="1" size="140,40" font="Regular;19" halign="center" valign="center" transparent="1"/>
		<widget source="key_green" render="Label" position="250,0" zPosition="1" size="140,40" font="Regular;19" halign="center" valign="center" transparent="1"/>
		<widget name="config" position="10,40" size="380,150"/>
	</screen>"""
	def __init__(self, session, config_time):
		self.timeinput_time = config_time
		Screen.__init__(self, session)
		self.setTitle(_("Time input"))
		self["key_red"] = Label(_("Cancel"))
		self["key_green"] = Label(_("OK"))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"],
		{
			"ok": self.keySave,
			"green": self.keySave,
			"red": self.keyCancel,
			"cancel": self.keyCancel,
		}, -2)
		self.list = []
		ConfigListScreen.__init__(self, self.list)
		self.createSetup(self["config"])

	def createSetup(self, configlist):
		self.list = [(_("Time"), self.timeinput_time),]
		configlist.list = self.list
		configlist.l.setList(self.list)

	def keyPageDown(self):
		sel = self["config"].getCurrent()
		if sel and sel[1] == self.timeinput_time:
			self.timeinput_time.decrement()
			self["config"].invalidateCurrent()

	def keyPageUp(self):
		sel = self["config"].getCurrent()
		if sel and sel[1] == self.timeinput_time:
			self.timeinput_time.increment()
			self["config"].invalidateCurrent()

	def keySave(self):
		self.timeinput_time.save()
		self.close((True, None))

	def keyCancel(self):
		self.timeinput_time.cancel()
		self.close((False,))

class SkinManager(object):
	SKIN_FILE = 'iptvdream.xml'

	def __init__(self):
		self.skins = []
		skins_dir = resolveFilename(SCOPE_SKIN, '.')
		for p in os.listdir(skins_dir):
			if os.path.isfile(os.path.join(skins_dir, p, self.SKIN_FILE)):
				self.skins.append(p)

		desktop = getDesktop(0)
		if desktop.size().width() >= 1920:
			default = 'IPtvDreamFHD'
		else:
			default = 'IPtvDream'
		assert default in self.skins
		pluginConfig.skin = ConfigSelection(self.skins, default=default)

	def load(self):
		skin = pluginConfig.skin.value
		loadSkin(os.path.join(skin, self.SKIN_FILE))

	def current(self):
		return pluginConfig.skin.value

	def setSkin(self, skin):
		pluginConfig.skin.value = skin
		pluginConfig.skin.save()


skinManager = SkinManager()
skinManager.load()


class PluginStarter(Screen):
	def __init__(self, session, name, task=None, use_web=False):
		trace("Starting provider", name)

		Screen.__init__(self, session)
		self.cfg = manager.getConfig(name)
		self.apiClass = manager.getApi(name)
		self.time_out = _("timed out")
		self.task = task
		if use_web:
			self.web_factory = WebConfigFactory(session)
		else:
			self.web_factory = None
		self.db = None

		try:
			self.last_service = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		except:
			self.last_service = self.session.nav.getCurrentlyPlayingServiceReference()
		self.onClose.append(self.restoreService)
		self.session.nav.stopService()

		self.onFirstExecBegin.append(self.start)

	def start(self):
		if self.apiClass.AUTH_TYPE and self.cfg.login.value == '':
			self.login()
		else:
			self.auth()

	def auth(self):
		trace("auth")
		self.db = self.apiClass(self.cfg.login.value, self.cfg.password.value)
		try:
			self.db.start()
			if self.task == 'settings':
				self.task = None
				self.openSettings(True)
			else:
				self.run()
			return
		except APILoginFailed as e:
			cb = lambda ret: self.login()
			message = _("Authorization error") + "\n" + str(e)
		except APIException as e:
			if self.task == 'settings':
				self.task = None
				cb = lambda ret: self.login()
			else:
				cb = lambda ret: self.exit()
			name_e = str(e)
			if self.time_out in name_e:
				name_e = self.time_out
			message = _("Start of %s failed") % self.db.NAME + "\n" + name_e
		self.session.openWithCallback(cb, MessageBox, message, MessageBox.TYPE_ERROR)

	def login(self):
		self.db = self.apiClass(self.cfg.login.value, self.cfg.password.value)
		self.task = None
		self.openSettings(False)

	def run(self):
		try:
			self.db.setChannelsList()
		except APIException as e:
			trace(e)
			name_e = str(e)
			if self.time_out in name_e:
				name_e = self.time_out
			self.session.openWithCallback(lambda ret: self.exit(), MessageBox, name_e, MessageBox.TYPE_ERROR)
		else:
			self.session.openWithCallback(self.finished, IPtvDreamStreamPlayer, self.db)

	def finished(self, ret):
		if ret == 'settings':
			self.openSettings(True)
		elif ret == 'clear_login':
			self.clearLogin()
			self.exit()
		else:
			self.exit()

	def openSettings(self, authorized):
		"""
		:type authorized: bool
		"""

		def cb(changed=False):
			# FIXME: very hacky return code
			if changed is None:
				self.clearLogin()
				self.start()
				return
			else:
				if changed:
					self.auth()
				else:
					self.exit()

		sr = SettingsRepository(self.db, authorized)
		if self.web_factory:
			self.web_factory.open(cb, authorized, sr)
		else:
			self.session.openWithCallback(cb, IPtvDreamConfig, sr)

	def clearLogin(self):
		self.cfg.login.value = ''
		self.cfg.password.value = ''
		manager.saveConfig()

	def exit(self):
		if self.web_factory:
			self.web_factory.stop()
		self.close()

	def compatibleSkin(self):
		SUPPORTED_SKINS = ['BlueMetalFHD']
		current = config.skin.primary_skin.value
		return any(current.find(s) > -1 for s in SUPPORTED_SKINS) or skinManager.current() != 'IPtvDream'

	def restoreService(self):
		self.session.nav.playService(self.last_service)


class TokenPluginStarter(PluginStarter):
	def start(self):
		self.db = self.apiClass(self.cfg.login.value, self.cfg.password.value)
		if self.cfg.password.value == '':
			self.askToken()
		else:
			self.auth()

	def auth(self):
		try:
			self.db.start()
			if self.task == 'settings':
				self.task = None
				self.openSettings(True)
			else:
				self.run()
			return
		except APILoginFailed as e:
			cb = lambda ret: self.askToken()
			message = _("We need to authenticate your device") + "\n" + str(e)
		except APIException as e:
			cb = lambda ret: self.exit()
			message = _("Start of %s failed") % self.db.NAME + "\n" + str(e)
		self.session.openWithCallback(cb, MessageBox, message, MessageBox.TYPE_ERROR)

	def askToken(self):
		""" Ask user for pin code and obtain a token"""
		self.session.openWithCallback(
			self._codeEntered, InputBox, title=_("Please go to %s and generate pin code") % self.apiClass.token_page,
			windowTitle=_("Input pin"), type=Input.NUMBER)

	def _codeEntered(self, code):
		if code is None:
			return self.exit()
		try:
			token = self.db.getToken(code)
			self._saveToken(token)
			return self.auth()
		except APILoginFailed as e:
			cb = lambda ret: self.askToken()
			message = _("Failed to authentificate your device") + "\n" + str(e)
		except APIException as e:
			cb = lambda ret: self.exit()
			message = _("Start of %s failed") % self.db.NAME + "\n" + str(e)
		self._saveToken(None)
		self.session.openWithCallback(cb, MessageBox, message, MessageBox.TYPE_ERROR)

	def _saveToken(self, token):
		if token is None:
			token = ''
		assert isinstance(token, str)
		self.cfg.password.value = token
		self.cfg.password.save()
		manager.saveConfig()


class WebConfigFactory(object):
	def __init__(self, session):
		"""
		:type session: mytest.Session
		"""
		self.session = session
		self._authorized = None
		self._instance = None

	def open(self, callback, authorized, repository):
		"""
		If authorized value is not changed we can use same web settings session
		We may want to add support for updating settings list on the server without creating new session later
		:type callback: (Optional[bool]) -> None
		:type authorized: bool
		:type repository: SettingsRepository
		"""
		valid = self._instance is not None and self._instance.isStarted() \
			and self._authorized is not None and self._authorized == authorized

		if not valid:
			if self._instance is not None:
				self._instance.stop()
			self._instance = WebConfig(repository.getAllSettings())
			self._authorized = authorized

		self.session.openWithCallback(callback, IPtvDreamWebConfig, self._instance, repository)

	def stop(self):
		"""
		End web settings session
		"""
		if self._instance is not None:
			self._instance.stop()
		self._instance = None


class Manager(object):
	def __init__(self):
		pluginConfig.max_playlists = ConfigInteger(0, (0, 9))
		self.max_playlists = pluginConfig.max_playlists.value

		# FIXME: spaghetti code warning
		self.start_mode_choices = [
			(str(IPtvDreamChannels.GROUPS), _("Groups")),
			(str(IPtvDreamChannels.FAV), _("Favourites when not empty")),
		]
		pluginConfig.start_mode = ConfigSelection(self.start_mode_choices)

		self.enabled = {}
		self.apiDict = {}
		self.config = config.IPtvDream = ConfigSubDict()
		self.onConfigChanged = []
		self.initList()

	def initList(self):
		api_provider = 'OTTProvider'
		api_function = 'getOTTProviders'
		prefix = 'Plugins.Extensions.IPtvDream.api'
		api_path = resolveFilename(SCOPE_CURRENT_PLUGIN, 'Extensions/IPtvDream/api')

		self.apiDict = {}
		seen = set()

		for f in os.listdir(api_path):
			if f.endswith('.py'):
				f = f[:-3]
			#elif f.endswith('.pyc') or f.endswith('.pyo'):
			#	f = f[:-4]
			else:
				continue
			if f in seen:
				continue
			seen.add(f)

			try:
				def process(provider):
					name = provider.NAME
					if self.isIgnored(name):
						trace("Ignore", name)
						return
					self.apiDict[name] = provider
					self.config[name] = ConfigSubsection()
					self.config[name].login = ConfigNumberText()
					self.config[name].password = ConfigNumberText()
					self.config[name].parental_code = ConfigNumberText()
					self.config[name].in_menu = ConfigYesNo(default=False)
					self.config[name].in_extensions = ConfigYesNo(default=False)
					self.config[name].playerid = ConfigSelection(PLAYERS, default="4097")
					self.config[name].use_hlsgw = ConfigYesNo(default=False)
					self.config[name].buffering = ConfigSelection(BUFFERING, default="0")
					self.config[name].last_played = ConfigText()
					self.config[name].playlist_name = ConfigText()

				trace("Loading module", f)
				module = my_import('%s.%s' % (prefix, f))
				if hasattr(module, api_function):
					for p in getattr(module, api_function)():
						process(p)
				elif hasattr(module, api_provider):
					process(getattr(module, api_provider))

			except Exception:  # pylint: disable=broad-except
				trace("Exception")
				import traceback
				traceback.print_exc()
				continue

		trace("Config generated for", self.config.keys())

	def isIgnored(self, name):
		try:
			return name.startswith('M3U-Playlist-') and int(name[-1]) > self.max_playlists
		except:
			return True

	def getNumberChoices(self):
		return [(str(n) if n else _('off'), n) for n in range(10)]

	def setPlaylistNumber(self, n):
		pluginConfig.max_playlists.value = n
		pluginConfig.max_playlists.save()

	def getStartModeChoices(self):
		return [(title, value) for value, title in self.start_mode_choices]

	def getStartMode(self):
		return int(pluginConfig.start_mode.value)

	def setStartMode(self, mode):
		pluginConfig.start_mode.value = mode
		pluginConfig.start_mode.save()

	def getList(self):
		return sorted(
			({'name': v.NAME, 'title': v.TITLE} for v in self.apiDict.values()),
			key=lambda item: item['name'].lower())

	def getApi(self, name):
		return self.apiDict[name]

	def getStarterClass(self, name):
		if self.getApi(name).AUTH_TYPE == 'Token':
			return TokenPluginStarter
		return PluginStarter

	def getConfig(self, name):
		return self.config[name]

	def saveConfig(self):
		self.config.save()
		configfile.save()
		for f in self.onConfigChanged:
			f()


manager = Manager()


class IPtvDreamManager(Screen):
	def __init__(self, session, hlsgw=None):
		Screen.__init__(self, session)
		self.setTitle(_("IPtvDream %s. Providers list:") % VERSION)
		self.hlsgw = hlsgw
		self["key_red"] = Label(_("Exit"))
		self["key_green"] = Label(_("Setup"))
		#self["key_yellow"] = Label(_("Web Setup"))
		self["key_yellow"] = Label()
		self["key_blue"] = Label(_("Menu"))
		self["actions"] = ActionMap(
				["OkCancelActions", "ColorActions"], {
					"cancel": self.cancel,
					"ok": self.ok,
					"green": self.setup,
					"yellow": self.webSetup,
					"red": self.cancel,
					"blue": self.showMenu,
				}, -1)
		self.list = self["list"] = List()
		self.onFirstExecBegin.append(self.start)

	def start(self):
		self.list.setList([self.makeEntry(x) for x in manager.getList()])

	def makeEntry(self, entry):
		prefix = resolveFilename(SCOPE_CURRENT_PLUGIN, 'Extensions/IPtvDream')
		pixmap = LoadPixmap(os.path.join(prefix, 'logo/%s.png' % entry['name']))
		name = entry['name']
		alt_name = manager.getConfig(entry['name']).playlist_name.value
		if alt_name:
			name = alt_name + " (%s)" % entry['name']
		return entry, pixmap, name

	def getSelected(self):
		sel = self.list.getCurrent()
		if sel is not None:
			return sel[0]
		else:
			return None

	def ok(self):
		entry = self.getSelected()
		if entry is not None:
			if self.hlsgw:
				self.hlsgw(manager.getConfig(entry['name']).use_hlsgw.value)
			self.startPlugin(entry['name'])

	def setup(self):
		entry = self.getSelected()
		if entry is not None:
			self.startPlugin(entry['name'], 'settings', False)

	def webSetup(self):
		entry = self.getSelected()
		if entry is not None:
			pass
			#self.startPlugin(entry['name'], 'settings', True)

	def startPlugin(self, name, task=None, use_web=False):
		self.session.open(manager.getStarterClass(name), name, task, use_web)

	def cancel(self):
		self.close()

	def showMenu(self):

		def cb(entry=None):
			if entry is not None:
				func = entry[1]
				if func:
					func()

		actions = [
			(_("Choose keymap"), self.selectKeymap),
			(_("Choose skin"), self.selectSkin),
			(_("Additional playlists number"), self.selectPlaylistNumber),
			(_("Start mode"), self.selectStartMode),
			(_("Show event-progress in servicelist") + _(": current (%s)") % (pluginConfig.show_event_progress_in_servicelist.value and _("yes") or _("no")), self.selectProgressMode),
			(_("Show number service in servicelist") + _(": current (%s)") % (pluginConfig.show_number_in_servicelist.value and _("yes") or _("no")), self.selectNumberMode),
		]
		#if pluginConfig.show_number_in_servicelist.value:
		actions += [(_("Alternative numbering mode") + _(": current (%s)") % (pluginConfig.alternative_number_in_servicelist.value and _("yes") or _("no")), self.alternativeNumberMode,)]
		actions += [(_("Count history (1 - off/max - 30)") + _(": current (%s)") % pluginConfig.numbers_history.value, self.numbersHistoryMode,)]
		if pluginConfig.keymap_type.value == "enigma":
			actions += [(_("Enable OK for servicelist") + _(": current (%s)") % (pluginConfig.ok_open_servicelist.value and _("yes") or _("no")), self.okShowServicelistMode,)]
		actions += [(_("Default recordings start time for archive"), self.setArchiveTime,)]
		self.session.openWithCallback(cb, ChoiceBox, _("Context menu"), actions)

	def setArchiveTime(self):
		dlg = self.session.openWithCallback(self.TimeInputClosed, TimeInput, pluginConfig.default_start_time_archive)
		#dlg.setTitle(_("Default recording start time for archive"))

	def TimeInputClosed(self, ret):
		if len(ret) > 1 and ret[0]:
			pass

	def okShowServicelistMode(self):
		pluginConfig.ok_open_servicelist.value = not pluginConfig.ok_open_servicelist.value
		pluginConfig.ok_open_servicelist.save()

	def selectProgressMode(self):
		pluginConfig.show_event_progress_in_servicelist.value = not pluginConfig.show_event_progress_in_servicelist.value
		pluginConfig.show_event_progress_in_servicelist.save()

	def selectNumberMode(self):
		pluginConfig.show_number_in_servicelist.value = not pluginConfig.show_number_in_servicelist.value
		pluginConfig.show_number_in_servicelist.save()

	def alternativeNumberMode(self):
		pluginConfig.alternative_number_in_servicelist.value = not pluginConfig.alternative_number_in_servicelist.value
		pluginConfig.alternative_number_in_servicelist.save()

	def numbersHistoryMode(self):
		def cb(num):
			if num is not None and num and num < 31:
				pluginConfig.numbers_history.value = num
				pluginConfig.numbers_history.save()
		self.session.openWithCallback(cb, MinuteInput,basemins=pluginConfig.numbers_history.value)

	def selectKeymap(self):
		def cb(selected):
			if selected is not None:
				self.applyKeymap(selected[0])
		self.session.openWithCallback(cb, ChoiceBox, title=_("Select keymap style") + _(": current (%s)") % pluginConfig.keymap_type.value, list=KEYMAPS)

	def applyKeymap(self, style):
		plugin_path = resolveFilename(SCOPE_CURRENT_PLUGIN, 'Extensions/IPtvDream')
		link = os.path.join(plugin_path, 'keymap.xml')
		try:
			os.remove(link)
		except (OSError, IOError) as e:
			trace(e)
		try:
			os.symlink('keymap_%s.xml' % style, link)
		except OSError as e:
			trace(e)
			import errno
			if e.errno == errno.EPROTO:  # ignore virtual machine related error
				import shutil
				shutil.copy(os.path.join(plugin_path, 'keymap_%s.xml' % style), link)
			else:
				raise e

		pluginConfig.keymap_type.value = style
		pluginConfig.keymap_type.save()
		configfile.save()

		self.session.openWithCallback(self.restart, MessageBox, _("Restart enigma2 to apply keymap changes?"), MessageBox.TYPE_YESNO)

	def selectSkin(self):
		def cb(selected):
			if selected is not None:
				skinManager.setSkin(selected[1])
				self.session.openWithCallback(self.restart, MessageBox, _("Restart enigma2 to apply skin changes?"), MessageBox.TYPE_YESNO)
		desktop = getDesktop(0).size().width() >= 1920 and "(FHD)" or "(HD)"
		self.session.openWithCallback(cb, ChoiceBox, title=_("Select skin") + desktop + _(": current (%s)") % skinManager.current(), list=[(s, s) for s in skinManager.skins])

	def selectPlaylistNumber(self):
		def cb(selected):
			if selected is not None:
				manager.setPlaylistNumber(selected[1])
				self.session.openWithCallback(self.restart, MessageBox, _("Restart enigma2 to apply changes?"), MessageBox.TYPE_YESNO)
		self.session.openWithCallback(cb, ChoiceBox, title=_("Select playlist number") + _(": current (%s)") % pluginConfig.max_playlists.value, list=manager.getNumberChoices(), selection=pluginConfig.max_playlists.value)

	def selectStartMode(self):
		def cb(selected):
			if selected is not None:
				manager.setStartMode(selected[1])

		self.session.openWithCallback(cb, ChoiceBox, title=_("Select start mode") + _(": current (%s)") % (pluginConfig.start_mode.value == "3" and _("Favourites when not empty") or _("Groups")), list=manager.getStartModeChoices())

	def restart(self, ret):
		if ret:
			from Screens.Standby import TryQuitMainloop
			self.session.open(TryQuitMainloop, retvalue=3)


class DaemonHelper(object):
	def __init__(self, program):
		from Components.Console import Console
		self.program = program
		self._console = Console()

	def start(self):
		self._console.ePopen('%s start' % self.program, self._finished)

	def stop(self):
		self._console.ePopen('%s stop' % self.program, self._finished)

	def waitstart(self):
		self._console.ePopen('sleep 2 && %s start' % self.program, self._finished)

	def _finished(self, output, exitcode, extra_args=None):
		trace("%s exitcode %d\n%s" % (self.program, exitcode, output.strip()))


class Runner(object):
	def __init__(self):
		self._running = False
		self.hlsgw = DaemonHelper("/usr/bin/hlsgwd.sh")

	def runPlugin(self, session, name):
		if not self._running:
			self._running = True
			self.hlsgw.start()
			#if manager.getConfig(name).use_hlsgw.value:
			#	self.hlsgw.start()
			session.openWithCallback(self.closed, manager.getStarterClass(name), name)
		else:
			self.showWarning(session)

	def runManager(self, session):
		if not self._running:
			self._running = True
			self.hlsgw.start()
			session.openWithCallback(self.closed, IPtvDreamManager)
			#session.openWithCallback(self.closed, IPtvDreamManager, self.hlsgwStopStart)
		else:
			self.showWarning(session)

	def hlsgwStopStart(self, start=False):
		self.hlsgw.stop()
		if start:
			self.hlsgw.waitstart()

	def closed(self, *args):
		self.hlsgw.stop()
		self._running = False

	def showWarning(self, session):
		assert self._running
		session.open(MessageBox, _("IPtvDream plugin is already running!"), MessageBox.TYPE_ERROR)


runner = Runner()
