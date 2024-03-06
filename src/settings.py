# -*- coding: utf-8 -*-
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
from io import BytesIO
from six import b
from collections import OrderedDict
from six.moves import urllib_parse
from json import loads as json_loads, dumps as json_dumps
from twisted.web.client import FileBodyProducer, Agent, Headers
from twisted.web._newclient import ResponseDone
from twisted.web.error import Error as WebError
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.defer import Deferred, CancelledError

# enigma2 imports
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.config import getConfigListEntry, \
		ConfigSearchText, ConfigInteger, ConfigSelection, ConfigYesNo, ConfigElement
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Components.Pixmap import Pixmap
from Components.Label import Label
from Components.Sources.Boolean import Boolean
from Tools.LoadPixmap import LoadPixmap

# plugin imports
from .dist import NAME, VERSION
from .utils import trace, ConfInteger, ConfSelection, ConfString, ConfBool, APIException
from .virtualkb import VirtualKeyBoard
from .common import ConfigNumberText
from .api.abstract_api import AbstractStream
from .loc import translate as _
from .common import safecb, fatalError, downloadPage

try:
	from typing import List, Tuple, Dict  # pylint: disable=unused-import
except ImportError:
	pass


class SettingsRepository(object):
	def __init__(self, db, authorized):
		"""
		:type db: AbstractStream
		:type authorized: bool
		"""
		self.db = db
		self.title = self.db.NAME
		self.authorized = authorized

		self._enigma_settings = {}
		self._local_settings = {}
		self._remote_settings = {}
		self._updateSettings()

	def _updateSettings(self):
		trace("Loading settings")
		self._enigma_settings = self._buildEnigmaSettings()
		self._local_settings = self.db.getLocalSettings()
		try:
			if self.authorized:
				self._remote_settings = self.db.getSettings()
		except APIException as e:
			trace("Failed to get settings", e)

	@staticmethod
	def makeConfEntry(title, element, key):
		return key, convertEnigmaConfigEntry(title, element)

	def _buildEnigmaSettings(self):
		"""Settings stored in enigma2"""
		from .manager import manager
		cfg = manager.getConfig(self.db.NAME)

		settings = OrderedDict()

		def appendEntry(title, name):
			settings['e2.%s' % name] = convertEnigmaConfigEntry(title, getattr(cfg, name))

		if not self.authorized:
			if self.db.AUTH_TYPE == "Login":
				appendEntry(_("Login"), 'login')
				appendEntry(_("Password"), 'password')
			elif self.db.AUTH_TYPE == "Key":
				appendEntry(_("Key"), 'login')

		appendEntry(_("Show in main menu"), 'in_menu')
		appendEntry(_("Show in extensions list"), 'in_extensions')
		appendEntry(_("Player ID"), 'playerid')
		appendEntry(_("Use HLS proxy"), 'use_hlsgw')

		return settings

	def getAllSettings(self):
		self._updateSettings()
		cfg_list = list(self._enigma_settings.items())
		cfg_list += list(self._local_settings.items())
		cfg_list += list(self._remote_settings.items())
		return cfg_list

	def saveValues(self, values):
		"""
		:type values: Dict[str, str]
		"""
		trace("Saving settings")

		from .manager import manager
		cfg = manager.getConfig(self.db.NAME)

		local_changes = {}
		remote_changes = {}

		for key, value in values.items():
			trace(key, '=', value)
			if key in self._enigma_settings:
				key = key[3:]
				element = getattr(cfg, key)  # type: ConfigElement
				element.value = value
				element.save()
			elif key in self._local_settings:
				local_changes[key] = value
			elif key in self._remote_settings:
				remote_changes[key] = value
			else:
				raise Exception("Unknown config element", key)

		manager.saveConfig()

		self.db.saveLocalSettings(local_changes)
		if self.authorized:
			self.db.pushSettings(remote_changes)

	def getConfigList(self):
		settings = self.getAllSettings()
		return [(v.title, convertConfEntry(v), k) for k, v in settings]

	def saveConfigList(self, cfg_list):
		"""
		:type cfg_list: List[Tuple[str, ConfigElement, str]]
		"""
		values = {key: entry.value for _, entry, key in cfg_list}
		self.saveValues(values)


def convertEnigmaConfigEntry(title, cfg):
	if isinstance(cfg, ConfigInteger):
		return ConfInteger(title, cfg.value, cfg.limits[0])
	elif isinstance(cfg, ConfigNumberText):
		return ConfString(title, cfg.value)
	elif isinstance(cfg, ConfigSelection):
		return ConfSelection(title, cfg.value, cfg.choices.choices)
	elif isinstance(cfg, ConfigYesNo):
		return ConfBool(title, cfg.value)
	else:
		trace("Unsupported config", (title, cfg))
		raise Exception("Unsupported config")


def convertConfEntry(conf):
	"""Convert plugin config class to enigma2 config"""
	if isinstance(conf, ConfInteger):
		return ConfigInteger(conf.value, limits=conf.limits)
	elif isinstance(conf, ConfString):
		return ConfigNumberText(default=conf.value)
	elif isinstance(conf, ConfSelection):
		return ConfigSelection(conf.choices, default=conf.value)
	elif isinstance(conf, ConfBool):
		return ConfigYesNo(conf.value)
	else:
		raise Exception("Unknown type in settings: " + str(type(conf)))


def getRequest(url):
	agent = Agent(reactor)
	d = agent.request(b'GET', b(url), headers=defaultHeaders())
	return d.addErrback(agentError).addCallback(readResponseBody)


def postRequest(url, body):
	agent = Agent(reactor)
	headers = defaultHeaders()
	headers.addRawHeader('Content-Type', 'application/json')
	d = agent.request(b'POST', b(url), headers=headers, bodyProducer=FileBodyProducer(BytesIO(b(body))))
	return d.addErrback(agentError).addCallback(readResponseBody)


def defaultHeaders():
	headers = Headers()
	headers.addRawHeader('User-Agent', 'IPtvDream-%s/%s' % (NAME, VERSION))
	return headers


def readResponseBody(response):
	trace("Response", response.code)
	# TODO: support redirects, this actually can be done with RedirectAgent
	if 200 <= response.code < 300:
		return readBody(response)
	else:
		raise HttpError(response.code, response.phrase)


def readBody(response):
	"""
	Copy-paste from twisted > 14.0.0
	Get full body from IResponse
	"""

	def cancel(deferred):
		abort = getattr(protocol.transport, "abortConnection", None)
		if abort is not None:
			abort()

	d = Deferred(cancel)
	protocol = _ReadBodyProtocol(response.code, response.phrase, d)
	response.deliverBody(protocol)
	return d


class _ReadBodyProtocol(Protocol):
	"""
	Copy-paste from twisted > 14.0.0
	Helper protocol for deliverBody
	"""

	def __init__(self, status, message, deferred):
		self.deferred = deferred
		self.status = status
		self.message = message
		self.dataBuffer = []

	def dataReceived(self, data):
		self.dataBuffer.append(data)

	def connectionLost(self, reason):
		"""
		Deliver the accumulated response bytes to the waiting L{Deferred}, if
		the response body has been completely received without error.
		"""
		if reason.check(ResponseDone):
			self.deferred.callback(b"".join(self.dataBuffer))
		else:
			self.deferred.errback(reason)


class HttpError(WebError):
	"""Bad HTTP response code"""


class AgentException(Exception):
	"""Twisted Agent exception"""


def agentError(err):
	"""Wrap twisted failure in AgentException"""
	raise AgentException(err.getErrorMessage())


class WebConfig(object):
	site = 'http://technic.cf/web/'

	def __init__(self, settings):
		self.settings = settings
		self.session = None
		self.key = None
		self.revision = None
		self.poll_defer = None
		self._run_defer = None
		self._error_count = 0

	def start(self):
		def cb(data):
			trace("received:", data)
			data = json_loads(data)
			self.key = data['key']
			self.session = data['secret']
			return data['key']

		self.revision = None
		items = []
		for k, v in self.settings:
			item = v.to_json()
			item['name'] = k
			items.append(item)
		trace(json_dumps(items))
		return postRequest(self.site + 'stb/new-session', json_dumps(items)).addCallback(cb)

	def isStarted(self):
		return self.session is not None

	def isLoggedIn(self):
		return self.isStarted() and self.revision is not None

	def _run(self):
		def eb(err):
			if err.check(CancelledError):
				trace("Poll canceled")
			elif err.check(HttpError):
				trace("Bad response", err.value)
				self.poll_defer.errback(err)
			else:
				trace("Poll error:", err.value)
				self._error_count += 1
				if self._error_count > 5:
					self.poll_defer.errback(err)
				else:
					self._run()  # retry

		def cb(data):
			trace("Poll result:", data)
			self._error_count = 0
			data = json_loads(data)
			self.revision = data['revision']
			self.poll_defer.callback(data)

		trace("Poll ...")
		if self.revision is None:
			# no revision has been received from the server, so we have initial values
			revision = 0
		else:
			revision = self.revision

		url = self.site + 'stb/poll?' + urllib_parse.urlencode({'sid': self.session, 'revision': revision})
		self._run_defer = getRequest(url)
		self._run_defer.addCallback(cb).addErrback(eb)

	def poll(self):
		if self.poll_defer:
			self.poll_defer.cancel()
		self.poll_defer = Deferred()
		self._run()
		return self.poll_defer

	def stop(self):
		trace("Delete session ...")
		d = getRequest(self.site + 'stb/del-session?' + urllib_parse.urlencode({'sid': self.session}))
		if self._run_defer:
			self._run_defer.cancel()
		self.session = None
		self.key = None
		return d


class IPtvDreamWebConfig(Screen):
	def __init__(self, session, web_config, settings_repository):
		"""
		:type web_config: WebConfig
		:type settings_repository: SettingsRepository
		"""
		trace("Web config open")

		Screen.__init__(self, session)

		self.settings_repository = settings_repository
		self.web_config = web_config
		self.site = self.web_config.site.replace('http://', 'https://')
		self.onFirstExecBegin.append(self.start)
		self._wantCallbacks = None

		self.setTitle(_("Configuration of %s") % settings_repository.title)
		self["header"] = Label(_("Connecting to server..."))
		self["image"] = Pixmap()
		self["label"] = Label()

		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
			"red": self.cancel,
			"yellow": self.logout,
			"cancel": self.cancel
		}, -2)

	@staticmethod
	def makeQrUrl(url):
		params = urllib_parse.urlencode({'data': url, 'size': '200x200', 'ecc': 'M'})
		return "http://api.qrserver.com/v1/create-qr-code/?" + params

	def showCode(self, data):
		path = '/tmp/qrcode.png'

		def setPixmap(ret):
			self["image"].instance.setPixmap(LoadPixmap(path))

		self["header"].setText(_("Scan QR code or visit url below"))
		self["label"].setText("Go to %s\nCode: %s" % (self.site, data.encode('utf-8')))
		downloadPage(self.makeQrUrl(self.site + "?c=%s" % data), path).addCallback(setPixmap)

	def start(self):
		# FIXME: handle errors
		if self.web_config.isStarted():
			if self.web_config.isLoggedIn():
				self.waitForChanges()
			else:
				self.keyReceived(self.web_config.key)
		else:
			self.web_config.start().addCallback(self.keyReceived).addErrback(self.error).addErrback(fatalError)

	@safecb
	def keyReceived(self, key):
		trace("Obtained key:", key)
		self.showCode(key)
		self.web_config.poll().addCallback(self.newSettingsReceived).addErrback(self.error).addErrback(fatalError)

	@safecb
	def newSettingsReceived(self, data):
		trace("Obtained settings:", data)
		if data['revision'] == 0:
			# revision zero indicates that user has logged in
			self.waitForChanges()
		else:
			values = {s['name']: s['value'] for s in data['values']}
			try:
				self.settings_repository.saveValues(values)
				self.close(True)
			except APIException as ex:
				self.session.openWithCallback(
					lambda ret: self.close(False),
					MessageBox, _("Failed to save settings") + "\n%s" % str(ex), MessageBox.TYPE_ERROR)

	def waitForChanges(self):
		self.web_config.poll().addCallback(self.newSettingsReceived).addErrback(self.error).addErrback(fatalError)
		# ui
		self["header"].setText(_("Waiting for changes to be entered"))
		self["image"].hide()
		self["label"].hide()

	def logout(self):
		# TODO: implement
		pass

	def cancel(self):
		trace("Closing web Settings")
		self.close(False)

	@safecb
	def error(self, err):
		trace("Web settings error:", err)
		e = err.trap(CancelledError, AgentException, WebError)
		if e in (AgentException, WebError):
			self.session.openWithCallback(
				lambda ret: self.close(False),
				MessageBox, _("Web settings error") + "\n%s" % str(err.getErrorMessage()), MessageBox.TYPE_ERROR)
		else:
			trace("Cancelled")
			self.close(False)


class IPtvDreamWebConfigWaiting(Screen):
	def __init__(self, session):
		"""
		:type config_repository: SettingsRepository
		"""
		Screen.__init__(self, session)
		self["text"] = Label(_("Waiting for changes made in the web interface..."))
		self["key_red"] = Label(_("Exit"))
		self["key_green"] = Label(_("Generate new code"))

		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
			"cancel": self.cancel,
			"red": self.cancel,
			"green": self.generateNewCode,
		}, -2)

	def cancel(self):
		self.close()

	def generateNewCode(self):
		self.close()


class IPtvDreamConfig(ConfigListScreen, Screen):
	def __init__(self, session, config_repository):
		"""
		:type config_repository: SettingsRepository
		"""
		Screen.__init__(self, session)
		trace("Config open")

		self["actions"] = ActionMap(["SetupActions", "ColorActions"], {
			"green": self.keySave,
			"red": self.keyCancel,
			"yellow": self.logout,
			"cancel": self.keyCancel
		}, -2)

		self["actions_kbd"] = ActionMap(["ColorActions"], {
			"blue": self.openKeyboard
		}, -2)
		self["actions_kbd"].setEnabled(False)

		self["key_red"] = Label(_("Cancel"))
		self["key_green"] = Label(_("OK"))
		self["key_yellow"] = Label(_("Logout"))
		self["key_blue"] = Label(_("Keyboard"))
		self["Keyboard"] = Boolean(False)

		self.config_repository = config_repository
		cfg_list = config_repository.getConfigList()
		ConfigListScreen.__init__(self, cfg_list, session)

		self.setTitle(_("Configuration of %s") % config_repository.title)
		self["config"].onSelectionChanged.append(self.showHideKeyboardButton)

	def showHideKeyboardButton(self):
		c = self["config"].getCurrent()
		if c and isinstance(c[1], (ConfigSearchText, ConfigNumberText)):
			self["actions_kbd"].setEnabled(True)
			self["Keyboard"].boolean = True
			self["key_blue"].show()
		else:
			self["actions_kbd"].setEnabled(False)
			self["Keyboard"].boolean = False
			self["key_blue"].hide()

	def openKeyboard(self):
		c = self["config"].getCurrent()
		try:
			def keyTextCallback(callback=None):
				if callback is not None:
					self["config"].getCurrent()[1].setValue(callback)
					self["config"].invalidate(self["config"].getCurrent())
		except:
			raise Exception("Callback save method error")
		try:
			cb = self.VirtualKeyBoardCallback
		except AttributeError:
			try:
				cb = self.keyTextCallback
			except AttributeError:
				try:
					cb = keyTextCallback
				except:
					raise Exception("Callback method not found")
					return
		self.session.openWithCallback(cb, VirtualKeyBoard, c[0], c[1].getValue(), ['en_EN'])

	def keySave(self):
		trace("Save config")
		if not self["config"].isChanged():
			self.close(False)
			return

		try:
			self.config_repository.saveConfigList(self["config"].list)
			self.close(True)
		except APIException as ex:
			self.session.openWithCallback(
				lambda ret: self.close(False),
				MessageBox, _("Failed to save settings") + "\n%s" % str(ex), MessageBox.TYPE_ERROR)

	def logout(self,answer=None):
		if answer is None:
			self.session.openWithCallback(self.logout, MessageBox, _("Logout")+ "?", default=False)
		elif answer:
			self.close(None)
