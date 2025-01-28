# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2010 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Common utils for enigma2 plugin, not directly related to iptv logic"""

from __future__ import print_function

from functools import wraps
from six import b
from twisted.web.client import downloadPage as _downloadPage

from Components.config import ConfigText
from Components.Sources.StaticText import StaticText
from Components.ActionMap import ActionMap, NumberActionMap
from Components.config import config
from Components.Label import Label
from Components.ServiceEventTracker import ServiceEventTracker
from Screens.Screen import Screen
from enigma import iPlayableService

from .layer import eTimer
from .utils import trace
from .loc import translate as _
# provide it from common file
from .updater import fatalError


def safecb(callback):
	@wraps(callback)
	def wrapper(obj, data):
		try:
			obj._wantCallbacks
		except AttributeError:
			trace("IGNORE late callback")
			return None
		return callback(obj, data)
	return wrapper


class DownloadException(Exception):
	"""Twisted download exception"""
	def __init__(self, message):
		time_out = _("timed out")
		message = _(message)
		Exception.__init__(self, message)


def downloadError(err):
	"""Wrap twisted download failure in DownloadException"""
	raise DownloadException(err.getErrorMessage())


def downloadPage(url, path):
	try:
		return _downloadPage(b(url), path).addErrback(downloadError)
	except:
		return None


class ConfigNumberText(ConfigText):
	def __init__(self, default=''):
		ConfigText.__init__(self, default, fixed_size=False)
		self.setUseableChars('0123456789')

	# override, do not show input dialog
	def onSelect(self, session):
		self.allmarked = (self.value != "")

	def handleKey(self, key, callback=None):
		self.timeout()  # Allow to input next key immediately
		return super(ConfigNumberText, self).handleKey(key)


class StaticTextService(StaticText):
	service = property(StaticText.getText, StaticText.setText)


# Reimplementation of InfoBarShowHide
class ShowHideScreen(Screen):
	STATE_HIDDEN = 0
	STATE_SHOWN = 1

	def __init__(self, session):
		super(ShowHideScreen, self).__init__(session)
		self.__state = self.STATE_SHOWN

		self["ShowHideActions"] = ActionMap(["InfobarShowHideActions"], {
						"toggleShow": self.toggleShow,
						"hide": self.hide,
				}, 1)  # lower prio to make it possible to override ok and cancel..

		self.hideTimer = eTimer()
		self.hideTimer.callback.append(self.doTimerHide)
		self.hideTimer.start(5000, True)

		self.onShow.append(self.__onShow)
		self.onHide.append(self.__onHide)
		self.__locked = 0

	def serviceStarted(self):
		if self.execing:
			if config.usage.show_infobar_on_zap.value:
				self.doShow()

	def __onShow(self):
		self.__state = self.STATE_SHOWN
		self.startHideTimer()

	def startHideTimer(self):
		if self.__state == self.STATE_SHOWN:
			idx = config.usage.infobar_timeout.index
			if idx:
				self.hideTimer.start(idx*1000, True)

	def __onHide(self):
		self.__state = self.STATE_HIDDEN

	def doShow(self):
		self.show()
		self.startHideTimer()

	def doTimerHide(self):
		self.hideTimer.stop()
		if self.__state == self.STATE_SHOWN:
			self.hide()

	def toggleShow(self):
		if self.__state == self.STATE_SHOWN:
			self.hide()
			self.hideTimer.stop()
		elif self.__state == self.STATE_HIDDEN:
			self.show()

	def lockShow(self):
		self.__locked = self.__locked + 1
		if self.execing:
			self.show()
			self.hideTimer.stop()

	def unlockShow(self):
		self.__locked = self.__locked - 1
		if self.execing:
			self.startHideTimer()


# Reimplementation of InfoBarMenu
class MainMenuScreen(Screen):
	""" Handles a menu action, to open the (main) menu """
	def __init__(self, session):
		super(MainMenuScreen, self).__init__(session)
		self["MenuActions"] = ActionMap(["IPtvDreamMenuActions"],
		{
			"mainMenu": self.mainMenu,
		})
		self.session.infobar = None

	def mainMenu(self):
		try:
			try:
				from Screens.Menu import mdom, MainMenu
				trace("[IPtvDream] loading mainmenu XML...")
				menu = mdom.getroot()
				assert menu.tag == "menu", "root element in menu must be 'menu'!"
				self.session.infobar = self
				self.session.openWithCallback(self.mainMenuClosed, MainMenu, menu)
			except:
				from Screens.Menu import Menu, findMenu
				menu = findMenu("mainmenu")
				if not menu:
					trace("[IPtvDream] Incompatible tag mainmenu")
				else:
					self.session.openWithCallback(self.mainMenuClosed, Menu, menu)
		except Exception as e:
			trace("[IPtvDream] Incompatible menu:", e)

	def mainMenuClosed(self, *val):
		self.session.infobar = None


class AutoAudioSelection(Screen):
	def __init__(self, session):
		super(AutoAudioSelection, self).__init__(session)
		self.__ev_tracker = ServiceEventTracker(screen=self, eventmap={
						iPlayableService.evUpdatedInfo: self.audioSelect,
						iPlayableService.evStart: self.audioClear
				})
		self.audio_selected = False

	def audioSelect(self):
		if self.audio_selected:
			return
		trace("[IPtvDream] audioSelect")
		self.audio_selected = True
		service = self.session.nav.getCurrentService()
		audio = service and service.audioTracks()
		n = audio and audio.getNumberOfTracks() or 0
		if n > 0:
			selected_audio = audio.getCurrentTrack()
			for x in range(n):
				language = audio.getTrackInfo(x).getLanguage()
				trace("audio scan language:", x, language)
				if language.find('rus') > -1 and x != selected_audio:
					audio.selectTrack(x)
					break

	def audioClear(self):
		trace("[IPtvDream] audioClear")
		self.audio_selected = False


class NumberEnter(Screen):
	TIMEOUT = 1800
	NEXT_TIMEOUT = 2300

	def __init__(self, session, number):
		Screen.__init__(self, session)
		self.skinName = "NumberZap"  # TODO own skin

		self["channel"] = Label(_("Channel:"))
		self["number"] = Label(str(number))

		self["actions"] = NumberActionMap(["SetupActions"], {
				"cancel": self.exit,
				"ok": self.keyOK,
				"1": self.keyNumberGlobal,
				"2": self.keyNumberGlobal,
				"3": self.keyNumberGlobal,
				"4": self.keyNumberGlobal,
				"5": self.keyNumberGlobal,
				"6": self.keyNumberGlobal,
				"7": self.keyNumberGlobal,
				"8": self.keyNumberGlobal,
				"9": self.keyNumberGlobal,
				"0": self.keyNumberGlobal
		})

		self.timer = eTimer()
		self.timer.callback.append(self.keyOK)
		self.timer.start(self.TIMEOUT)

	def exit(self):
		self.timer.stop()
		self.close(None)

	def keyOK(self):
		self.timer.stop()
		self.close(int(self["number"].text))

	def keyNumberGlobal(self, number):
		self.timer.stop()
		self.timer.start(self.NEXT_TIMEOUT)
		self["number"].text += str(number)
		if len(self["number"].text) > 5:
			self.keyOK()
