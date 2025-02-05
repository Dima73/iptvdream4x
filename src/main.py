# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#  Copyright (c) 2013 Alex Revetchi <alex.revetchi@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

# system imports
from datetime import datetime, timedelta
from time import time
from six.moves import urllib_parse
try:
	# noinspection PyUnresolvedReferences
	from typing import Callable, Optional, List, Tuple  # pylint: disable=unused-import
except ImportError:
	pass

try:
	from Plugins.Extensions.TMBD.plugin import TMBD
except:
	TMBD = None

try:
	from Screens import Standby
except:
	Standby = None

# enigma2 imports
from Components.Sources.List import List as ListSource
from Components.Sources.Boolean import Boolean
from Components.Sources.Event import Event
from Components.ActionMap import ActionMap, NumberActionMap
from Components.config import config, configfile
from Components.Label import Label
from Components.ScrollLabel import ScrollLabel
from Components.Slider import Slider
from Components.ServiceEventTracker import InfoBarBase
from Components.Input import Input
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.GUIComponent import GUIComponent
from Screens.InfoBarGenerics import InfoBarPlugins, InfoBarExtensions, \
	InfoBarNotifications, InfoBarAudioSelection, InfoBarSubtitleSupport, InfoBarSummary
from Screens.InfoBar import InfoBar
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Screens.InputBox import InputBox
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN, SCOPE_SKIN, SCOPE_SYSETC, SCOPE_CURRENT_PLUGIN

# ScreenSaver - not support DreamOS
availabilityScreenSaver = True
try:
	from Screens.InfoBarGenerics import InfoBarScreenSaver
except:
	try:
		from Screens.ScreenSaver import InfoBarScreenSaver
	except:
		availabilityScreenSaver = False
		class InfoBarScreenSaver():
			def __init__(self):
				pass

# enigma2 core imports
from enigma import eListboxPythonMultiContent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER, \
	eLabel, eSize, ePoint, getDesktop, eServiceReference, eActionMap
from skin import parseFont, parseColor

# plugin imports
from .layer import eTimer
from .common import NumberEnter
from .utils import trace, tdSec, secTd, syncTime, APIException, APIWrongPin, EPG, SetEvent, timeit
from .api.abstract_api import AbstractStream
from .loc import translate as _
from .common import ShowHideScreen, AutoAudioSelection, MainMenuScreen
from .standby import standbyNotifier
from .cache import LiveEpgWorker
from .lib.epg import EpgProgress
from .lib.tv import SortOrderSettings, Picon

SKIN_PATH = resolveFilename(SCOPE_SKIN, 'IPtvDream')
ENIGMA_CONF_PATH = resolveFilename(SCOPE_SYSETC, 'enigma2')
EPGMAP_PATH = resolveFilename(SCOPE_SYSETC, 'iptvdream')

rec_png = LoadPixmap(cached=True, path=SKIN_PATH + '/rec.png')
EPG_UPDATE_INTERVAL = 60  # Seconds, in channel list.
PROGRESS_TIMER = 1000*60  # Update progress in infobar.
PROGRESS_SIZE = 500
ARCHIVE_TIME_FIX = 5  # sec. When archive paused, we could miss some video

FHD = False
if getDesktop(0).size().width() >= 1920:
	FHD = True

def updateSource(self, *args):
	pass

class IPtvDreamStreamPlayer(
		ShowHideScreen, AutoAudioSelection, MainMenuScreen,
		InfoBarBase, InfoBarPlugins, InfoBarExtensions,
		InfoBarNotifications, InfoBarAudioSelection, InfoBarSubtitleSupport, InfoBarScreenSaver):
	"""
	:type channels: IPtvDreamChannels
	:type db: AbstractStream
	"""

	ALLOW_SUSPEND = True

	def __init__(self, session, db):
		super(IPtvDreamStreamPlayer, self).__init__(session)
		InfoBarBase.__init__(self, steal_current_service=True)
		InfoBarExtensions.__init__(self)
		InfoBarPlugins.__init__(self)
		InfoBarNotifications.__init__(self)
		InfoBarAudioSelection.__init__(self)
		InfoBarSubtitleSupport.__init__(self)
		self.seekstate = (0, 0, 0, ">")
		InfoBarScreenSaver.__init__(self)

		trace("start stream player: ",db.NAME)
		self.db = db
		from .manager import manager
		self.cfg = manager.getConfig(self.db.NAME)
		self.cid = None
		self.next = None
		self.alternativeNumber = config.plugins.IPtvDream.alternative_number_in_servicelist.value

		standbyNotifier.onStandbyChanged.append(self.standbyChanged)
		self.onClose.append(lambda: standbyNotifier.onStandbyChanged.remove(self.standbyChanged))

		self.channels = self.session.instantiateDialog(IPtvDreamChannels, self.db, self)
		self.openListServices = False
		self.zapTimer = eTimer()
		self.zapTimer.callback.append(self.zapTimerRun)
		self.zap_service = None
		self.zap_service_name = ""
		self.zap_service_running = None

		self.onFirstExecBegin.append(self.start)

		self.setTitle(self.db.NAME)
		self["channelName"] = Label("")
		# Epg widgets
		self["currentName"] = Label("")
		self["nextName"] = Label("")
		self["currentTime"] = Label("")
		self["nextTime"] = Label("")
		self["currentDuration"] = Label("")
		self["nextDuration"] = Label("")
		self["progressBar"] = Slider(0, PROGRESS_SIZE)
		# Buttons
		self["key_red"] = Label(_("Archive"))
		self["key_green"] = Label("")
		self["key_yellow"] = Label(_("Audio"))
		self["key_blue"] = Label(_("Extensions"))

		# TODO: think more
		self["archiveDate"] = Label("")
		self["inArchive"] = Boolean(False)
		try:
			self.ORIG_Event_Now = self.session.screen["Event_Now"]
		except:
			self.ORIG_Event_Now = None
		try:
			self.session.screen["Event_Now"] = Event()
			self.session.screen["Event_Now"].updateSource = updateSource
		except:
			pass

		self["picon"] = Pixmap()
		self._picon = Picon(self["picon"])

		self["provider"] = Pixmap()
		icon_path = resolveFilename(SCOPE_CURRENT_PLUGIN, 'Extensions/IPtvDream/logo/%s.png' % self.db.NAME)
		self.onFirstExecBegin.insert(0, lambda: self["provider"].instance.setPixmap(LoadPixmap(icon_path)))

		self.ok_open_servicelist = config.plugins.IPtvDream.keymap_type.value == "enigma" and config.plugins.IPtvDream.ok_open_servicelist.value

		if not self.ok_open_servicelist:
			self["actions"] = ActionMap(["IPtvDreamInfobarActions", "ColorActions", "OkCancelActions"], {
				"cancel": self.confirmExit,
				"closePlugin": self.exit,
				"openVideos": self.activatePiP,
				"red": self.showEpg,
				"green": self.runKeyGreen,
				"openServiceList": self.showList,
				"showIhfobar": self.prevToggleShow,
				"zapUp": self.previousChannel,
				"zapDown": self.nextChannel,
				"historyNext": self.historyNext,
				"historyBack": self.historyBack,
				"showEPGList": self.showEpg,
				})

			self["live_actions"] = ActionMap(["IPtvDreamLiveActions"], {
				"zapUp": self.previousChannel,
				"zapDown": self.nextChannel,
				}, -1)

			self["archive_actions"] = ActionMap(["IPtvDreamArchiveActions", "NumberActions"], {
				"exitArchive": self.exitArchive,
				"playpause": self.playPauseArchive,
				"play": lambda: self.playPauseArchive(True, False),
				"pause": lambda: self.playPauseArchive(False, True),
				"seekForward": self.archiveSeekFwd,
				"seekBackward": self.archiveSeekRwd,
				"1": lambda: self.jump(1),
				"3": lambda: self.jump(3),
				"4": lambda: self.jump(4),
				"6": lambda: self.jump(6),
				"7": lambda: self.jump(7),
				"9": lambda: self.jump(9),
				}, -1)
		else:
			self["actions"] = ActionMap(["IPtvDreamInfobarOkActions", "ColorActions", "OkCancelActions"], {
				"cancel": self.confirmExit,
				"closePlugin": self.exit,
				"openVideos": self.activatePiP,
				"ok": self.prewShowList,
				"red": self.showEpg,
				"green": self.runKeyGreen,
				"showIhfobar": self.prevToggleShow,
				"zapUp": self.previousChannel,
				"zapDown": self.nextChannel,
				"historyNext": self.historyNext,
				"historyBack": self.historyBack,
				"showEPGList": self.showEpg,
				})

			self["live_actions"] = ActionMap(["IPtvDreamLiveOkActions"], {
				"zapUp": self.previousChannel,
				"zapDown": self.nextChannel,
				}, -1)

			self["archive_actions"] = ActionMap(["IPtvDreamArchiveOkActions", "NumberActions"], {
				"exitArchive": self.exitArchive,
				"playpause": self.playPauseArchive,
				"play": lambda: self.playPauseArchive(True, False),
				"pause": lambda: self.playPauseArchive(False, True),
				"seekForward": self.archiveSeekFwd,
				"seekBackward": self.archiveSeekRwd,
				"leftShowIhfobar": self.leftShowIhfobar,
				"rightShowIhfobar": self.rightShowIhfobar,
				"1": lambda: self.jump(1),
				"3": lambda: self.jump(3),
				"4": lambda: self.jump(4),
				"6": lambda: self.jump(6),
				"7": lambda: self.jump(7),
				"9": lambda: self.jump(9),
				}, -1)


		self["number_actions"] = NumberActionMap(["NumberActions"], {
				"1": self.keyNumberGlobal,
				"2": self.keyNumberGlobal,
				"3": self.keyNumberGlobal,
				"4": self.keyNumberGlobal,
				"5": self.keyNumberGlobal,
				"6": self.keyNumberGlobal,
				"7": self.keyNumberGlobal,
				"8": self.keyNumberGlobal,
				"9": self.keyNumberGlobal,
				"0": self.keyNumberGlobal,
			})

		self.currentEpg = None
		self.play_service = False
		self.play_shift = ""
		self.epgTimer = eTimer()
		self.epgProgressTimer = eTimer()
		self.epgTimer.callback.append(self.epgEvent)
		self.epgProgressTimer.callback.append(self.epgUpdateProgress)

		self.archive_pause = None
		self.shift = 0

		self.waitMessageTimer = eTimer()
		self.waitMessageTimer.callback.append(self.showWaitMessage)

		self.waitScreenSaverTimer = eTimer()
		self.waitScreenSaverTimer.callback.append(self.ScreenSaverTimerStart)

		if InfoBar.instance is not None:
			try:
				self.servicelist = InfoBar.instance.servicelist
			except:
				self.servicelist = None
		else:
			self.servicelist = None
		slist = self.servicelist
		if slist:
			try:
				self.pipZapAvailable = slist.dopipzap
			except:
				self.pipZapAvailable = None


	def start(self):
		trace("player start")
		self.showList()

	def exit(self, ret=None):
		self.zapTimer.stop()
		self.zap_service = self.zap_service_running = None
		self.channels.saveQuery()
		self.session.deleteDialog(self.channels)
		try:
			if self.ORIG_Event_Now:
				self.session.screen["Event_Now"] = self.ORIG_Event_Now
		except:
			pass
		self.close(ret)

	def confirmExit(self):
		def cb(ret):
			if ret:
				self.exit()
		self.session.openWithCallback(cb, MessageBox, _("Exit plugin?"), MessageBox.TYPE_YESNO)

	def ScreenSaverTimerStart(self):
		global availabilityScreenSaver
		if not availabilityScreenSaver:
			return
		try:
			startTimer = int(config.usage.screen_saver.value)
		except:
			try:
				startTimer = int(config.usage.screenSaverStartTimer.value)
			except:
				if availabilityScreenSaver:
					availabilityScreenSaver = False
				return
		if not startTimer:
			return
		flag = self.shift != 0 and self.archive_pause is not None
		pip_show = hasattr(self, "session") and hasattr(self.session, "pipshown") and self.session.pipshown
		if hasattr(self, "screenSaverTimer"):
			if flag and not pip_show:
				trace("screenSaver timer start - min.=", startTimer)
				self.screenSaverTimer.startLongTimer(startTimer)
			else:
				self.screenSaverTimer.stop()

	def keypressScreenSaver(self, key, flag):
		if flag:
			if hasattr(self, "screensaver"):
				self.screensaver.hide()
				trace("screenSaver hide - key=", key)
			self.waitScreenSaverTimer.stop()
			self.waitScreenSaverTimer.start(200, True)
			eActionMap.getInstance() and eActionMap.getInstance().unbindAction('', self.keypressScreenSaver)

	def leftShowIhfobar(self):
		if self.shift and self.archive_pause:
			self.archiveSeekRwd()
		else:
			self.toggleShow()

	def rightShowIhfobar(self):
		if self.shift and self.archive_pause:
			self.archiveSeekFwd()
		else:
			self.toggleShow()

	def prevToggleShow(self):
		self.toggleShow()

	def prewShowList(self):
		try:
			if self["archive_actions"].enabled and self.shift and self.archive_pause and not self.play_shift:
				self.playPauseArchive(True, False)
				return
		except:
			pass
		if self.ok_open_servicelist:
			self.showList()

	def play(self, cid):
		trace("play cid =", cid)

		self.cid = cid
		self.session.nav.stopService()
		self.archive_pause = None
		if availabilityScreenSaver:
			self.waitScreenSaverTimer.stop()
			self.waitScreenSaverTimer.start(200, True)
		try:
			self.session.screen["Event_Now"].newEvent(None)
		except:
			pass
		self.play_service = False
		if cid is None:
			return

		if self.db.channels[cid].is_protected:
			trace("protected by api")
			code = self.cfg.parental_code.value
			if code:
				trace("using saved code")
				self.getUrl(code)
			else:
				self.enterPin()
		else:
			self.getUrl(None)

	def enterPin(self):
		self.session.openWithCallback(self.getUrl, InputBox, title=_("Enter protect password"),windowTitle=_("Channel Locked"), type=Input.PIN)

	def getUrl(self, pin):
		try:
			url = self.db.getStreamUrl(self.cid, pin, self.time())
		except APIWrongPin:
			self.session.openWithCallback(
					lambda ret: self.enterPin(), MessageBox, _("Wrong pin!"),
					MessageBox.TYPE_ERROR, timeout=10, enable_input=False)
			return
		except APIException as e:
			self.showError(_("Error while getting stream url:") + str(e))
			self.updateLabels()
			return

		self.playUrl(url)

	# Player

	def playUrl(self, url):
		cid = self.cid
		if self.cfg.use_hlsgw.value:
			url = "http://localhost:7001/url=%s" % urllib_parse.quote(url)
		trace("play", url)
		ref = eServiceReference(int(self.cfg.playerid.value), 0, url)
		ref.setName(self.db.channels[cid].name)
		ref.setData(1, 1)
		self.session.nav.playService(ref)
		self.play_service = True
		self.channels.current_cid = cid
		self.updateLabels()

	def updateLabels(self):
		cid = self.cid
		self["channelName"].setText("%d. %s" % ((self.channels.mode != 1 and self.alternativeNumber and self.db.channels[cid].alt_number) or self.db.channels[cid].number, self.db.channels[cid].name))
		self["key_green"].setText("")
		self._picon.setIcon(self.db.getPiconUrl(cid))
		self.epgEvent()

	def standbyChanged(self, sleep):
		if sleep:
			trace("entered standby")
			if self.shift and not self.archive_pause:
				self.playPauseArchive()
			else:
				self.session.nav.stopService()
		else:
			trace("exited standby")
			if self.shift:
				self.playPauseArchive()
			else:
				self.play(self.cid)

	# Archive

	def setArchiveShift(self, time_shift):
		self.shift = time_shift
		self.play_shift = ""
		self.archive_pause = None
		if time_shift:
			self["live_actions"].setEnabled(False)
			self["number_actions"].setEnabled(False)
			self["archive_actions"].setEnabled(True)
			self["inArchive"].setBoolean(True)
			self["key_red"].setText(_("Live"))
		else:
			self["archive_actions"].setEnabled(False)
			self["live_actions"].setEnabled(True)
			self["number_actions"].setEnabled(True)
			self["inArchive"].setBoolean(False)
			self["key_red"].setText(_("Archive"))

	def time(self):
		if self.shift:
			return syncTime() + secTd(self.shift)
		return None

	def archiveSeekFwd(self):
		try:
			self.session.openWithCallback(self.fwdJumpMinutes, InputBox, title=_("Forward in minutes"), text="5", type=Input.NUMBER)
		except:
			try:
				self.session.open(MessageBox, _("This image does not support correct operation of the number set!"), MessageBox.TYPE_ERROR, timeout=8)
			except:
				pass

	def archiveSeekRwd(self):
		try:
			self.session.openWithCallback(self.rwdJumpMinutes, InputBox, title=_("Back in minutes"), text="5", type=Input.NUMBER)
		except:
			try:
				self.session.open(MessageBox, _("This image does not support correct operation of the number set!"), MessageBox.TYPE_ERROR, timeout=8)
			except:
				pass

	def fwdJumpMinutes(self, minutes):
		try:
			minutes = int(minutes)
		except:
			minutes = 0
		return minutes and self.fwdJump(minutes * 60)

	def rwdJumpMinutes(self, minutes):
		try:
			minutes = int(minutes)
		except:
			minutes = 0
		return minutes and self.rwdJump(minutes * 60)

	def fwdJump(self, seconds):
		trace("fwdSeek", seconds)
		self.shift += seconds
		if self.shift > 0:
			self.setArchiveShift(0)
		self.play(self.cid)

	def rwdJump(self, seconds):
		trace("rwdSeek", seconds)
		self.shift -= seconds
		self.play(self.cid)

	def jump(self, n):
		try:
			t13 = config.seek.selfdefined_13.value
			t46 = config.seek.selfdefined_46.value
			t79 = config.seek.selfdefined_79.value
		except AttributeError:
			t13 = 15
			t46 = 60
			t79 = 300

		t = {1: -t13, 3: t13, 4: -t46, 6: t46, 7: -t79, 9: t79}[n]
		if t < 0:
			self.rwdJump(abs(t))
		else:
			self.fwdJump(abs(t))

	def playPauseArchive(self, play=True, pause=True):
		if self.archive_pause and play:
			# do unPause
			self.shift -= tdSec(syncTime()-self.archive_pause)-ARCHIVE_TIME_FIX
			self.archive_pause = None
			self.play(self.cid)
			self.unlockShow()
			#if availabilityScreenSaver:
			#	self.waitScreenSaverTimer.stop()
			#	self.waitScreenSaverTimer.start(200, True)
		elif pause:
			# do pause
			self.archive_pause = syncTime()
			# try to pause and freeze the picture, otherwise stop and show black screen
			service = self.session.nav.getCurrentService()
			pauseable = service and service.pause()
			if pauseable:
				pauseable.pause()
			else:
				self.session.nav.stopService()
			self.lockShow()
			# freeze epg labels
			self.epgTimer.stop()
			self.epgProgressTimer.stop()
			if availabilityScreenSaver:
				self.waitScreenSaverTimer.stop()
				self.waitScreenSaverTimer.start(200, True)

	def exitArchive(self):
		self.setArchiveShift(0)
		self.play(self.cid)

	# EPG

	def epgEvent(self):
		# first stop timers
		self.epgTimer.stop()
		self.epgProgressTimer.stop()
		self.currentEpg = None
		cid = self.cid
		this_time = syncTime() + secTd(self.shift)

		def setEpgCurrent():
			curr = self.db.channels[cid].epgCurrent(this_time)
			if not curr:
				return False
			self.currentEpg = curr
			self["currentName"].setText(curr.name)
			self["currentTime"].setText(curr.begin.strftime("%H:%M"))
			self["nextTime"].setText(curr.end.strftime("%H:%M"))
			try:
				self.epgTimer.start(curr.timeLeftMilliseconds(this_time) + 1000)
			except OverflowError as of:
				trace("Overflow error - retry 5 sec.", of)
				self["currentDuration"].setText("")
				self.epgTimer.start(5000)
			else:
				self["currentDuration"].setText(_("+%d min") % int(curr.timeLeft(this_time) / 60))
				self["progressBar"].setValue(curr.percent(this_time, PROGRESS_SIZE))
			self["progressBar"].show()
			self.epgProgressTimer.start(PROGRESS_TIMER)
			try:
				event = SetEvent(curr.begin_timestamp, curr.end_timestamp, curr.name, curr.description, self.shift)
				self.session.screen["Event_Now"].newEvent(event)
			except:
				pass
			if self.shift:
				self["archiveDate"].setText(curr.begin.strftime("%d.%m"))
				self["archiveDate"].show()
			else:
				self["archiveDate"].hide()
			if not self.db.channels[cid].has_archive:
				if self["key_red"].getText() != _("EPG"):
					self["key_red"].setText(_("EPG"))
			else:
				if not self.shift and not self.play_shift and self["key_green"].getText() != _("Pause"):
					self["key_green"].setText(_("Pause"))
			return True

		if not setEpgCurrent():
			try:
				self.db.loadDayEpg(cid, this_time)
			except APIException as e:
				trace("ERROR load epg failed! cid =", cid, bool(self.shift), e)
			if not setEpgCurrent():
				self["currentName"].setText("")
				self["currentTime"].setText("")
				self["nextTime"].setText("")
				self["currentDuration"].setText("")
				self["progressBar"].setValue(0)
				self["progressBar"].hide()

		def setEpgNext():
			e = self.db.channels[cid].epgNext(this_time)
			if not e:
				return False
			self['nextName'].setText(e.name)
			self['nextDuration'].setText(_("%d min") % int(e.duration() / 60))
			return True

		if not setEpgNext():
			try:
				self.db.loadDayEpg(cid, this_time)
			except APIException:
				trace("load epg next failed!")
			if not setEpgNext():
				self["nextName"].setText("")
				self["nextDuration"].setText("")

		self.serviceStarted()

	def epgUpdateProgress(self):
		if self.currentEpg:
			time = syncTime() + secTd(self.shift)
			try:
				self["currentDuration"].setText(_("+%d min") % int(self.currentEpg.timeLeft(time) / 60))
				self["progressBar"].setValue(self.currentEpg.percent(time, PROGRESS_SIZE))
			except:
				trace("Overflow error")
			self.epgProgressTimer.start(PROGRESS_TIMER)

	# Dialogs

	def showEpg(self):
		if self.cid:
			self.session.openWithCallback(self.programSelected, IPtvDreamEpg, self.db, self.cid, self.shift, self.channels.mode)

	def programSelected(self, cid=None, archive_time=None, zaptimer=None):
		if zaptimer is not None and cid is not None:
			try:
				minutes = int(zaptimer)
			except:
				return
			minutes = (minutes - int(time())) // 60
			self.zap_service_running = int(time()) + (minutes * 60)
			self.zap_service = self.channels.saved_state
			self.zap_service.name = self.db.channels[cid].name
			self.zapTimer.startLongTimer(minutes * 60)
		elif cid is not None and archive_time is not None:
			self.setArchiveShift(tdSec(archive_time-syncTime()))  # shift < 0
			self.play(cid)

	def zapTimerRun(self):
		if self.zap_service and self.cid and self.cid != self.zap_service.cid:
			self.channels.current_cid = self.zap_service.cid
			self.channels.history.append(self.zap_service)
			self.channels.saved_state = self.channels.history.now()
			self.zap_service_name = ""
			if not self.openListServices:
				self.channels.recoverState(self.zap_service, same=True)
			try:
				if Standby and Standby.inStandby:
					Standby.inStandby.Power()
			except:
				pass
			self.switchChannel(self.zap_service.cid)
			try:
				if Standby and Standby.inStandby is None:
					try:
						self.session.open(MessageBox, _("Zap to '%s'") % self.zap_service.name, MessageBox.TYPE_INFO, timeout=5)
					except:
						pass
				else:
					self.zap_service_name = self.zap_service.name
					self.waitMessageTimer.stop()
					self.waitMessageTimer.start(5000, True)
			except:
				pass
			self.zap_service = self.zap_service_running = None

	def showWaitMessage(self):
		if Standby and Standby.inStandby is None:
			try:
				self.session.open(MessageBox, _("Zap to '%s'") % self.zap_service_name, MessageBox.TYPE_INFO, timeout=10)
			except:
				pass

	def showList(self):
		self.channels.current_cid = self.cid
		self.session.execDialog(self.channels)
		self.channels.callback = self.listClosed
		self.openListServices = True

	def listClosed(self, cid=None, time=None, action=None):
		self.openListServices = False
		if availabilityScreenSaver:
			self.waitScreenSaverTimer.stop()
			self.waitScreenSaverTimer.start(200, True)
		if action is None:
			self.channelSelected(cid, time)
		elif isinstance(action, int):
			pass
		else:
			self.exit(action)

	def channelSelected(self, cid, time=None):
		if cid is None:
			return
		if time:
			self.programSelected(cid, time)
		elif cid != self.cid:
			self.switchChannel(cid)
		elif self.alternativeNumber and self.cid is not None:
			self["channelName"].setText("%d. %s" % ((self.channels.mode != 1 and self.alternativeNumber and self.db.channels[self.cid].alt_number) or self.db.channels[self.cid].number, self.db.channels[self.cid].name))

	def runKeyGreen(self):
		if self.play_service and self.currentEpg and self.cid and self.db.channels[self.cid].has_archive:
			if not self.shift and not self.archive_pause and not self.play_shift:
				self.playPauseLive(play=False, pause=True)
				return
			if self.shift == -38 and self.archive_pause and self.play_shift == "pause":
				def cb(entry=None):
					if entry is not None:
						if entry[1] == "play":
							self.playPauseLive(play=True, pause=False)
						elif entry[1] == "live":
							self["key_green"].setText("")
							self.setArchiveShift(0)
							self.play(self.cid)
				actions = [(_("Play"), "play"),(_("Live"), "live"),]
				self.session.openWithCallback(cb, ChoiceBox, _("Actions"), actions)

	def playPauseLive(self, play=True, pause=True):
		if self.archive_pause and play:
			self.shift -= tdSec(syncTime()-self.archive_pause)-ARCHIVE_TIME_FIX
			self.archive_pause = None
			self.play(self.cid)
			self.unlockShow()
			#if availabilityScreenSaver:
			#	self.waitScreenSaverTimer.stop()
			#	self.waitScreenSaverTimer.start(200, True)
			self.play_shift = "play"
			self["key_green"].setText("")
		elif pause:
			self.shift = -38
			self.setArchiveShift(self.shift)
			self.archive_pause = syncTime()
			self.playPauseArchive(play=False, pause=True)
			self.play_shift = "pause"
			self["key_green"].setText(_("Play"))

	def openSettings(self,answer=None):
		if answer is None:
			self.session.openWithCallback(self.openSettings, MessageBox, _("Open provider settings?"), default=False)
		elif answer:
			self.exit('settings')

	def createSummary(self):
		return InfoBarSummary

	# Channels

	def switchChannel(self, cid):
		# FIXME: zapping breaks archive shift
		trace("switch channel", self.cid)
		self.setArchiveShift(0)
		self.next = None
		self.play(cid)

	def nextChannel(self):
		if not self.shift and self.channels.mode:
			cid = self.channels.nextChannel()
			if cid:
				self.switchChannel(cid)

	def previousChannel(self):
		if not self.shift and self.channels.mode:
			cid = self.channels.prevChannel()
			if cid:
				self.switchChannel(cid)

	def historyNext(self):
		if not self.shift and self.channels.historyNext():
			cid = self.channels.getCurrent()
			if cid:
				self.switchChannel(cid)

	def historyBack(self):
		if not self.shift and self.channels.historyPrev():
			cid = self.channels.getCurrent()
			if cid:
				self.switchChannel(cid)

	def keyNumberGlobal(self, number):
		if number == 0:
			if self.next:
				self.historyNext()
				return
			next = self.channels.getCurrent()
			if self.channels.historyPrev():
				cid = self.channels.getCurrent()
				self.switchChannel(cid)
				self.next = next
		elif self.channels.mode:
			self.session.openWithCallback(self.numberEntered, NumberEnter, number)

	def numberEntered(self, num=None):
		trace("numberEntered", num)
		if num is not None and self.channels.goToNumber(num):
			cid = self.channels.getCurrent()
			self.switchChannel(cid)

	def showError(self, msg):
		self.session.open(MessageBox, _(msg), MessageBox.TYPE_ERROR, 5)

	def openServiceList(self):
		if self.pipZapAvailable is None:
			return
		try:
			if self.servicelist and self.servicelist.dopipzap:
				self.session.execDialog(self.servicelist)
		except:
			pass

	def activatePiP(self):
		if self.pipZapAvailable is None:
			return
		try:
			from Components.SystemInfo import SystemInfo
		except:
			return
		if SystemInfo.get("NumVideoDecoders", 1) > 1:
			if InfoBar.instance is not None:
				modeslist = []
				keyslist = []
				try:
					if InfoBar.pipShown(InfoBar.instance):
						slist = self.servicelist
						if slist:
							try:
								if slist.dopipzap:
									modeslist.append((_("Zap focus to main screen"), "pipzap"))
								else:
									modeslist.append((_("Zap focus to Picture in Picture"), "pipzap"))
								keyslist.append('red')
								if slist.dopipzap:
									modeslist.append((_("Open service list"), "openservicelist"))
									keyslist.append('yellow')
							except:
								pass
						modeslist.append((_("Move Picture in Picture"), "move"))
						keyslist.append('green')
						modeslist.append((_("Disable Picture in Picture"), "stop"))
						keyslist.append('blue')
					else:
						modeslist.append((_("Activate Picture in Picture"), "start"))
						keyslist.append('blue')
				except:
					return
				first_text = ""
				if len(keyslist) == 1:
					first_text = _("The cursor in the channel selector should be on the DVB service") + ".\n"
				dlg = self.session.openWithCallback(self.pipAnswerConfirmed, ChoiceBox, title= first_text + _("Choose action:"), list=modeslist, keys=keyslist)
				dlg.setTitle(_("Menu PiP"))

	def pipAnswerConfirmed(self, answer):
		answer = answer and answer[1]
		if answer is None:
			return
		if answer == "openservicelist":
			self.openServiceList()
		elif answer == "pipzap":
			try:
				InfoBar.togglePipzap(InfoBar.instance)
			except:
				pass
		elif answer == "move":
			if InfoBar.instance is not None:
				try:
					InfoBar.movePiP(InfoBar.instance)
				except:
					pass
		elif answer == "stop":
			if InfoBar.instance is not None:
				try:
					if InfoBar.pipShown(InfoBar.instance):
						slist = self.servicelist
						try:
							if slist and slist.dopipzap:
								slist.togglePipzap()
						except:
							pass
					if hasattr(self.session, "pip"):
						del self.session.pip
					self.session.pipshown = False
				except:
					pass
				if availabilityScreenSaver:
					self.waitScreenSaverTimer.stop()
					self.waitScreenSaverTimer.start(200, True)
		elif answer == "start":
			try:
				prev_playingrefGroup = self.session.nav.currentlyPlayingServiceOrGroup
				prev_playingref = self.session.nav.currentlyPlayingServiceReference
				if prev_playingref:
					self.session.nav.currentlyPlayingServiceOrGroup = None
					self.session.nav.currentlyPlayingServiceReference = None
				InfoBar.showPiP(InfoBar.instance)
				if prev_playingref:
					self.session.nav.currentlyPlayingServiceOrGroup = prev_playingrefGroup
					self.session.nav.currentlyPlayingServiceReference = prev_playingref
			except:
				return
			slist = self.servicelist
			if slist:
				try:
					if not slist.dopipzap and hasattr(self.session, "pip"):
						InfoBar.togglePipzap(InfoBar.instance)
				except:
					pass

	def nextPipService(self):
		if self.pipZapAvailable is None:
			return
		try:
			slist = self.servicelist
			if slist and slist.dopipzap:
				if slist.inBouquet():
					prev = slist.getCurrentSelection()
					if prev:
						prev = prev.toString()
						while True:
							if config.usage.quickzap_bouquet_change.value and slist.atEnd():
								slist.nextBouquet()
							else:
								slist.moveDown()
							cur = slist.getCurrentSelection()
							if not cur or (not (cur.flags & 64)) or cur.toString() == prev:
								break
				else:
					slist.moveDown()
				slist.zap(enable_pipzap=True)
		except:
			pass

	def prevPipService(self):
		if self.pipZapAvailable is None:
			return
		try:
			slist = self.servicelist
			if slist and slist.dopipzap:
				if slist.inBouquet():
					prev = slist.getCurrentSelection()
					if prev:
						prev = prev.toString()
						while True:
							if config.usage.quickzap_bouquet_change.value:
								if slist.atBegin():
									slist.prevBouquet()
							slist.moveUp()
							cur = slist.getCurrentSelection()
							if not cur or (not (cur.flags & 64)) or cur.toString() == prev:
								break
				else:
					slist.moveUp()
				slist.zap(enable_pipzap=True)
		except:
			pass

class ChannelList(MenuList):
	def __init__(self):
		MenuList.__init__(self, [], content=eListboxPythonMultiContent, enableWrapAround=True)
		self.list = []
		self.allindex = {}
		self.col = {}
		self.fontCalc = []

		self.pixmapProgressBar = None
		self.pixmapArchive = None
		self.listItemHeight = 28
		self.listItemWidth = 0
		self.l.setFont(0, parseFont("Regular;22", ((1, 1), (1, 1))))
		self.l.setFont(1, parseFont("Regular;18", ((1, 1), (1, 1))))
		self.l.setFont(2, parseFont("Regular;19", ((1, 1), (1, 1))))
		self.showEpgProgress = config.plugins.IPtvDream.show_event_progress_in_servicelist.value
		self.showNumber = config.plugins.IPtvDream.show_number_in_servicelist.value
		self.alternativeNumber = config.plugins.IPtvDream.alternative_number_in_servicelist.value
		self.channelsMode = 0
		self.highlight_cid = 0

		for x in [
				"colorEventProgressbar", "colorEventProgressbarSelected",
				"colorEventProgressbarBorder", "colorEventProgressbarBorderSelected",
				"colorServiceDescription", "colorServiceDescriptionSelected",
				"colorServicePlaying", "colorServicePlayingSelected"]:
			self.col[x] = None

	def postWidgetCreate(self, instance):
		trace("postWidgetCreate")
		MenuList.postWidgetCreate(self, instance)
		# Create eLabel instances, because we can't access eTextPara directly
		self.fontCalc = [eLabel(self.instance), eLabel(self.instance), eLabel(self.instance)]
		self.fontCalc[0].setFont(parseFont("Regular;22", ((1, 1), (1, 1))))
		self.fontCalc[1].setFont(parseFont("Regular;18", ((1, 1), (1, 1))))
		self.fontCalc[2].setFont(parseFont("Regular;19", ((1, 1), (1, 1))))

	def applySkin(self, desktop, parent):
		scale = ((1, 1), (1, 1))
		attribs = []
		if self.skinAttributes is not None:
			for (attrib, value) in self.skinAttributes:
				if attrib in (
						"colorEventProgressbar", "colorEventProgressbarSelected",
						"colorEventProgressbarBorder", "colorEventProgressbarBorderSelected",
						"colorServiceDescription", "colorServiceDescriptionSelected",
						"colorServicePlaying", "colorServicePlayingSelected"):
					self.col[attrib] = parseColor(value).argb()
				elif attrib == "picServiceEventProgressbar":
					pic = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, value))
					if pic:
						self.pixmapProgressBar = pic
				elif attrib == "picServiceArchive":
					pic = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, value))
					if pic:
						self.pixmapArchive = pic
				elif attrib == "serviceItemHeight":
					self.listItemHeight = int(value)
				elif attrib == "serviceNameFont":
					self.l.setFont(0, parseFont(value, scale))
					self.fontCalc[0].setFont(parseFont(value, scale))
				elif attrib == "serviceInfoFont":
					self.l.setFont(1, parseFont(value, scale))
					self.fontCalc[1].setFont(parseFont(value, scale))
				elif attrib == "serviceNumberFont":
					self.l.setFont(2, parseFont(value, scale))
					self.fontCalc[2].setFont(parseFont(value, scale))
				else:
					attribs.append((attrib, value))

		self.skinAttributes = attribs
		res = GUIComponent.applySkin(self, desktop, parent)

		self.l.setItemHeight(self.listItemHeight)
		self.listItemWidth = self.instance.size().width()
		for x in self.fontCalc:
			# resize and move away
			x.resize(eSize(self.listItemWidth, self.listItemHeight))
			x.move(ePoint(int(self.instance.size().width()+10), int(self.instance.size().height()+10)))
			x.setNoWrap(1)
		return res

	def setChannelsList(self, channels):
		self.setList(list(map(self.buildChannelEntry, channels)))
		# Create map from channel id to its allindex in list
		self.allindex = dict((entry[0][0].cid, i) for (i, entry) in enumerate(self.list))

	def updateChannel(self, cid, channel):
		try:
			index = self.allindex[cid]
		except KeyError:
			return
		#if self.channelsMode != 1 and self.alternativeNumber:
		#	channel[0][0].alt_number = self.list[index][0][0].alt_number
		self.list[index] = self.buildChannelEntry(channel)
		self.l.invalidateEntry(index)

	def updateChannelsProgress(self):
		if self.showEpgProgress:
			self.setList([self.buildChannelEntry(item[0]) for item in self.list])

	def moveEntryUp(self):
		index = self.getSelectedIndex()
		if index == 0:
			return
		self.list[index - 1], self.list[index] = self.list[index], self.list[index - 1]
		self.l.invalidateEntry(index - 1)
		self._updateIndexMap(index - 1)
		self.l.invalidateEntry(index)
		self._updateIndexMap(index)
		self.up()

	def moveEntryDown(self):
		index = self.getSelectedIndex()
		if index + 1 == len(self.list):
			return
		self.list[index], self.list[index + 1] = self.list[index + 1], self.list[index]
		self.l.invalidateEntry(index)
		self._updateIndexMap(index)
		self.l.invalidateEntry(index + 1)
		self._updateIndexMap(index + 1)
		self.down()

	def _updateIndexMap(self, i):
		cid = self.list[i][0][0].cid
		self.allindex[cid] = i

	def highlight(self, cid):
		self.highlight_cid = cid

	def setGroupList(self, groups):
		self.setList(list(map(self.buildGroupEntry, groups)))
		self.allindex = {}

	def calculateWidth(self, text, font):
		self.fontCalc[font].setText(text)
		return int(round(self.fontCalc[font].calculateSize().width()*1.1))

	def buildGroupEntry(self, group):
		return [
			group,
			(eListboxPythonMultiContent.TYPE_TEXT, 0, 0, self.listItemWidth, self.listItemHeight,
				0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, group.title)
		]

	def buildChannelEntry(self, entry):
		"""
		:type entry: Tuple[utils.Channel, utils.EPG]
		"""
		c, e = entry
		defaultFlag = RT_HALIGN_LEFT | RT_VALIGN_CENTER
		# Filling from left to right

		lst = [entry]
		xoffset = 1

		if self.showNumber:
			if FHD:
				xoffset += 85
			else:
				xoffset += 60
			text = self.channelsMode != 1 and self.alternativeNumber and str(c.alt_number) or str(c.number)
			lst.append(
				(eListboxPythonMultiContent.TYPE_TEXT, 0, 0, xoffset - 5, self.listItemHeight,
					2, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text))

		if self.pixmapArchive:
			width = self.pixmapArchive.size().width()
			height = self.pixmapArchive.size().height()
			if c.has_archive and e:
				lst.append(
					(eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,
						xoffset, (self.listItemHeight - height) // 2, width, height, self.pixmapArchive))
			xoffset += width + 5

		if self.showEpgProgress:
			width = 52
			height = 6
			if e:
				if (e.end_timestamp >= int(time())) or (abs(e.end_timestamp - int(time())) < 60):
					percent = e.percent(syncTime(), 100)
					lst.extend([
						(eListboxPythonMultiContent.TYPE_PROGRESS,
							xoffset + 1, (self.listItemHeight-height) // 2, width, height,
							percent, 0, self.col['colorEventProgressbar'], self.col['colorEventProgressbarSelected']),
						(eListboxPythonMultiContent.TYPE_PROGRESS,
							xoffset, (self.listItemHeight-height) // 2 - 1, width + 2, height + 2,
							0, 1, self.col['colorEventProgressbarBorder'], self.col['colorEventProgressbarBorderSelected'])
					])
			xoffset += width + 7

		text = str(c.name)
		width = self.calculateWidth(text, 0)
		if c.cid != self.highlight_cid:
			lst.append(
				(eListboxPythonMultiContent.TYPE_TEXT, xoffset, 0, width, self.listItemHeight,
					0, defaultFlag, text))
		else:
			lst.append(
				(eListboxPythonMultiContent.TYPE_TEXT, xoffset, 0, width, self.listItemHeight,
					0, defaultFlag, text, self.col['colorServicePlaying'], self.col['colorServicePlayingSelected']))
		xoffset += width + 10

		if e:
			text = '(%s)' % e.name
			lst.append(
				(eListboxPythonMultiContent.TYPE_TEXT, xoffset, 0, self.listItemWidth, self.listItemHeight,
					1, defaultFlag, text,
					self.col['colorServiceDescription'], self.col['colorServiceDescriptionSelected']))

		return lst


class History(object):
	def __init__(self, size):
		self._size = size
		self._history = []  # type: List[HistoryEntry]
		self._index = -1

	def isEmpty(self):
		return len(self._history) == 0

	def counts(self):
		return len(self._history)

	def replace(self, curr):
		add = None
		if self.counts() > 1:
			for s in self._history:
				if curr and curr == s.cid:
					add = s
					self._history.remove(s)
					break
			if add:
				self._history.append(add)
				#self._index = len(self._history) - 1

	def clear(self):
		if self.counts() > 1:
			self._history = self._history[-1:]
			self._index = 0
			return True
		return False

	def delCurrent(self, curr):
		if self.counts() > 1:
			for s in self._history:
				if curr and curr == s.cid:
					self._history.remove(s)
					self._index -= 1
					return True
		return False

	def append(self, val):
		#while len(self._history) > self._index + 1:
		#	self._history.pop()
		oldlst = self._history[:]
		for s in oldlst:
			if val.cid and val.cid == s.cid:
				oldlst.remove(s)
				self._index -= 1
				break
		self._history = oldlst
		self._history.append(val)
		if len(self._history) > self._size:
			self._history.pop(0)
		self._index = len(self._history) - 1

	def historyPrev(self):
		if self._index < 1:
			return None
		else:
			self._index -= 1
			return self._history[self._index]

	def historyNext(self):
		if self._index + 1 == len(self._history):
			return None
		else:
			self._index += 1
			return self._history[self._index]

	def now(self):
		if len(self._history):
			return self._history[self._index]
		else:
			return None

	def __repr__(self):
		return repr(list(map(str, self._history)))


class HistoryEntry(object):
	def __init__(self, mode, gid, gr_idx, cid, ch_idx):
		self.mode = mode
		self.gid, self.gr_idx = gid, gr_idx
		self.cid, self.ch_idx = cid, ch_idx

	def copy(self):
		return HistoryEntry(self.mode, self.gid, self.gr_idx, self.cid, self.ch_idx)

	def fromStr(self, s):
		self.mode, self.gid, self.gr_idx, self.cid, self.ch_idx = list(map(int, s.split(",")))

	def toStr(self):
		return ",".join(map(str, (self.mode, self.gid, self.gr_idx, self.cid, self.ch_idx)))

	def makeTuple(self):
		return self.mode, self.gid, self.gr_idx, self.cid, self.ch_idx

	def __repr__(self):
		return "HistoryEntry(%d, (%d, %d), (%d, %d))" % (self.mode, self.gid, self.gr_idx, self.cid, self.ch_idx)


class VerticalLayoutPart(object):
	"""
	Grow program name label while title does not fit, and shrink program description accordingly
	"""

	def __init__(self, screen, widgetsToMove):
		self._name_height = 0
		self._desc_top = 0
		self._desc_height = 0
		self._widgets_top = []
		self.name = screen["epgName"]
		self.desc = screen["epgDescription"]
		self.widgets = widgetsToMove
		screen.onLayoutFinish.append(self.initLayout)

	def initLayout(self):
		self._name_height = self.name.instance.size().height()
		self._desc_top = self.desc.instance.position().y()
		self._desc_height = self.desc.instance.size().height()
		self._widgets_top = [w.instance.position().y() for w in self.widgets]

	def updateLayout(self):
		height = min(self.name.instance.calculateSize().height(), self._name_height * 3)
		dh = height - self._name_height
		self.name.instance.resize(eSize(
			self.name.instance.size().width(), height))
		self.desc.instance.move(ePoint(
			self.desc.instance.position().x(), self._desc_top + dh))
		self.desc.instance.resize(eSize(
			self.desc.instance.size().width(), self._desc_height - dh))
		for w, y in zip(self.widgets, self._widgets_top):
			w.instance.move(ePoint(w.instance.position().x(), y + dh))


class IPtvDreamChannels(Screen):
	"""
	:type db: AbstractStream
	:type saved_state: Optional[HistoryEntry]
	"""

	GROUPS, ALL, GROUP, FAV, HISTORY = range(5)

	def __init__(self, session, db, player=None):
		Screen.__init__(self, session)

		trace("channels init")
		self.history = History(config.plugins.IPtvDream.numbers_history.value)
		self.db = db  # type: AbstractStream
		self.player = player
		from .manager import manager
		self.cfg = manager.getConfig(self.db.NAME)

		self["caption"] = Label(_("Channel Selection"))
		self["key_red"] = Label(_("All"))
		self["key_green"] = Label(_("Groups"))
		self["key_yellow"] = Label("")
		self["key_blue"] = Label(_("Favourites"))

		self.list = self["list"] = ChannelList()

		self["channelName"] = Label()
		self["epgName"] = Label()
		self["epgTime"] = Label()
		self["epgDescription"] = Label()
		self["epgNextTime"] = Label()
		self["epgNextName"] = Label()
		self["epgNextDescription"] = Label()

		self.current_event_info = ""
		self.current_cid = None
		self.alternativeNumber = config.plugins.IPtvDream.alternative_number_in_servicelist.value
		self["epgProgress"] = Slider(0, 100)
		self["progress"] = self._progress = EpgProgress()
		self._progress.onChanged.append(lambda value: self["epgProgress"].setValue(int(100 * value)))

		# auto resize some widgets
		self._info_part = VerticalLayoutPart(self, (self["epgTime"], self["epgProgress"]))

		self._worker = LiveEpgWorker(db)
		self._worker.onUpdate.append(self.updatePrograms)
		self.onClose.append(self._worker.destroy)

		def workerStandby(sleep):
			if sleep:
				self._worker.stop()
			else:
				self._worker.update()
		standbyNotifier.onStandbyChanged.append(workerStandby)
		self.onClose.append(lambda: standbyNotifier.onStandbyChanged.remove(workerStandby))

		self._progressTimer = eTimer()
		self._progressTimer.callback.append(self.updateProgramsProgress)
		self._progressTimer.start(1000 * 60 * 5)  # every 5 min

		self.waitTimer = eTimer()
		self.waitTimer.callback.append(self.zapTimerPrerare)
		self.dlg_actions = None

		self["actions"] = ActionMap(
			["OkCancelActions", "IPtvDreamChannelListActions"], {
				"cancel": self.exit,
				"ok": self.ok,
				"showAll": self.showAll,
				"showGroups": self.showGroups,
				"addFavourites": self.openHistory,
				"showFavourites": self.showFavourites,
				"contextMenu": self.showMenu,
				"showEPGList": self.showEpgList,
				"nextBouquet": self.nextGroup,
				"prevBouquet": self.prevGroup
			}, -1)

		self.list.onSelectionChanged.append(self.selectionChanged)
		self.onClose.append(lambda: self.list.onSelectionChanged.remove(self.selectionChanged))

		start_mode = manager.getStartMode()
		if start_mode == self.FAV and not self.db.selectFavourites():
			start_mode = self.GROUPS

		self.order_config = SortOrderSettings()
		self.mode = start_mode
		self.gid = None
		self.saved_state = None
		self.historyList = []
		self.edit_mode = False
		self.marked = False  # Whether current entry is marked (in edit mode)
		self["move_actions"] = ActionMap(
			["OkCancelActions", "DirectionActions", "IPtvDreamChannelListActions"], {
				"cancel": self.finishEditing,
				"ok": self.toggleMarkForMoving,
				"up": self.moveUp,
				"down": self.moveDown,
				"contextMenu": self.showMenu,
				"addFavourites": self.addRemoveFavourites,
			}, -1)
		self["move_actions"].setEnabled(False)

		self["packetExpire"] = Label()
		if self.db.packet_expire is not None:
			self["packetExpire"].setText(_("Payment expires: ") + self.db.packet_expire.strftime("%d.%m.%Y"))

		self.onLayoutFinish.append(self.fillList)
		self.onShown.append(self.start)

	def start(self):
		trace("Channels list shown")
		self.saved_state = None
		if not self.history.isEmpty():
			if self.history.counts() > 1:
				self["key_yellow"].setText(_("History"))
			else:
				self.historyList = []
			self.saved_state = self.history.now()
		else:
			self.historyList = []
			self["key_yellow"].setText("")

	def saveQuery(self):
		trace("save query")
		h = self.history.now()
		if h is not None:
			self.cfg.last_played.value = self.history.now().toStr()
		else:
			self.cfg.last_played.value = ""
		self.cfg.last_played.save()
		configfile.save()

	def createHistoryEntry(self):
		entry = self.getSelected()
		assert entry is not None
		return HistoryEntry(self.mode, self.gid, 0, entry.cid, self.list.getSelectedIndex())

	def recoverState(self, state, same=False):
		"""
		:param HistoryEntry state:
		"""
		self.mode, self.gid = state.mode, state.gid
		if self.mode == self.GROUPS:
			self.fillGroupsList()
			if same:
				self.list.moveToIndex(state.gr_idx)
			elif self.saved_state:
				self.list.moveToIndex(self.saved_state.gr_idx)
		else:
			self.fillList()
			if same:
				self.list.moveToIndex(state.ch_idx)
			elif self.saved_state:
				self.list.moveToIndex(self.saved_state.ch_idx)

	def exit(self):
		if self.saved_state is not None:
			self.recoverState(self.saved_state)
		self.close(None)

	def ok(self, time=None):
		entry = self.getSelected()
		if entry is None:
			return
		if self.mode == self.GROUPS:
			self.mode = self.GROUP
			self.gid = entry.gid
			self.fillList()
			self.list.moveToIndex(0)
		else:
			idx = self.list.getSelectedIndex()
			cid = entry.cid
			self.current_cid = cid
			if self.mode == self.HISTORY:
				self.history.replace(cid)
				self.openHistory()
			else:
				self.history.append(HistoryEntry(self.mode, self.gid, 0, cid, idx))
				self.saved_state = self.history.now()
			if self.history.counts() > 1:
				self["key_yellow"].setText(_("History"))
			else:
				self["key_yellow"].setText("")
			self.close(cid, time)

	@timeit
	def updateProgramsProgress(self):
		if self.mode != self.GROUPS:
			print("Updating list progressbars")
			self.list.updateChannelsProgress()

	def updatePrograms(self, data):
		# type: (List[Tuple[int, EPG]]) -> None
		if self.mode == self.GROUPS:
			return
		for (cid, epg) in data:
			if epg:
				try:
					channel = self.db.channels[cid]
				except KeyError:
					continue
				self.list.updateChannel(cid, (channel, epg))

	@timeit
	def setChannels(self, channels):
		self.list.setChannelsList((c, self._worker.get(c.cid)) for c in channels)

	def fillGroupsList(self):
		self.setTitle(" / ".join([self.db.NAME, _("Groups")]))
		groups = self.db.selectGroups()
		self.list.setGroupList(groups)
		self.list.moveToIndex(0)
		if self.gid is not None:
			for idx, g in enumerate(groups):
				if g.gid == self.gid:
					self.list.moveToIndex(idx)
					break
			else:
				self.gid = None

	def fillList(self):
		title = [self.db.NAME]
		order = self.order_config.getValue()
		self.list.channelsMode = self.mode
		if self.mode == self.GROUPS:
			self.fillGroupsList()
			title.append(_("Groups"))
		elif self.mode == self.GROUP:
			group = self.db.selectChannels(self.gid, sort_key=order)
			if group and self.alternativeNumber:
				num = 0
				for s in group:
					num += 1
					s.alt_number = num
					try:
						self.db.channels[s.cid].alt_number = num 
					except:
						pass
			self.setChannels(group)
			title.append(self.db.groups[self.gid].title)
		elif self.mode == self.ALL:
			self.setChannels(self.db.selectAll(sort_key=order))
			title.append(_("All channels"))
		elif self.mode == self.FAV:
			fav = self.db.selectFavourites()
			if fav and self.alternativeNumber:
				num = 0
				for s in fav:
					num += 1
					s.alt_number = num
			self.setChannels(fav)
			title.append(_("Favourites"))
		elif self.mode == self.HISTORY:
			his = self.historyList
			if his and self.alternativeNumber:
				num = 0
				for s in his:
					num += 1
					s.alt_number = num
			self.setChannels(his)
			title.append(_("History list"))
		self.setTitle(" / ".join(title))

	def selectionChanged(self):
		channel = self.getSelected()
		trace("selection =", channel)
		self.current_event_info = ""

		if self.mode == self.GROUPS or channel is None:
			self["channelName"].setText("")
			self.hideEpgLabels()
			self.hideEpgNextLabels()
		else:
			self["channelName"].setText(channel.name)
			self["channelName"].show()
			curr = self._worker.get(channel.cid)
			if curr:
				if curr.end_timestamp >= int(time()):
					try:
						duration_time = int(curr.timeLeft(syncTime()) / 60)
					except:
						duration_time = -1
					if duration_time >= 0 and duration_time < 1800:
						duration = not duration_time and _("%d min") % duration_time or _("+%d min") % duration_time
						self["epgTime"].setText("%s - %s (%s)" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M"), duration))
					else:
						self["epgTime"].setText("%s - %s" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M")))
					self._progress.setEpg(curr)
					self["epgProgress"].show()
				else:
					try:
						duration_time = int(curr.duration() / 60)
					except:
						duration_time = -1
					if duration_time >= 0 and duration_time < 1800:
						duration = _("%d min") % duration_time
						self["epgTime"].setText("%s - %s (%s)" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M"), duration))
					else:
						self["epgTime"].setText("%s - %s" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M")))
					self["epgProgress"].hide()
				self["epgTime"].show()
				self["epgName"].setText(curr.name)
				if curr.name:
					self.current_event_info = curr.name
				self["epgName"].show()
				self["epgDescription"].setText(curr.description)
				self["epgDescription"].show()
				self._info_part.updateLayout()
			else:
				self.hideEpgLabels()
			curr = self._worker.getNext(channel.cid)
			if curr:
				self["epgNextTime"].setText("%s - %s" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M")))
				self["epgNextName"].setText(curr.name)
				self["epgNextDescription"].setText(curr.description)
				self["epgNextName"].show()
				self["epgNextTime"].show()
				self["epgNextDescription"].show()
			else:
				self.hideEpgNextLabels()

	def hideEpgLabels(self):
		self["epgName"].hide()
		self["epgTime"].hide()
		self["epgProgress"].hide()
		self["epgDescription"].hide()

	def hideEpgNextLabels(self):
		self["epgNextName"].hide()
		self["epgNextTime"].hide()
		self["epgNextDescription"].hide()

	def showGroups(self):
		self.mode = self.GROUPS
		self.fillList()

	def showAll(self):
		channel = self.getCurrent()
		self.mode = self.ALL
		self.fillList()
		index = 0
		if channel is not None:
			idx = self.findChannelIndex(channel)
			if idx:
				index = idx
		self.list.moveToIndex(index)

	def showFavourites(self):
		self.mode = self.FAV
		self.fillList()
		self.list.moveToIndex(0)

	def npGroup(self, diff):
		if self.mode == self.GROUP:
			groups = self.db.selectGroups()
			for idx, g in enumerate(groups):
				if g.gid == self.gid:
					self.gid = groups[(idx + diff) % len(groups)].gid
					self.fillList()
					self.list.moveToIndex(0)
					break

	def nextGroup(self):
		self.npGroup(1)

	def prevGroup(self):
		self.npGroup(-1)

	def openHistory(self):
		self.historyList = []
		history = [entry.cid for entry in self.history._history]
		if len(history) > 1:
			for cid in reversed(history):
				try:
					self.historyList.append(self.db.channels[cid])
				except:
					trace("error history cid ", cid)
			if self.historyList:
				self.mode = self.HISTORY
				self.fillList()
				self.list.moveToIndex(0)
				if self.current_cid:
					idx = self.findChannelIndex(self.current_cid)
					if idx:
						self.list.moveToIndex(idx)
			elif self.mode == self.HISTORY:
				self.showGroups()

	def addRemoveFavourites(self):
		channel = self.getSelected()
		if not channel:
			return
		if self.mode == self.FAV:
			self.db.rmFav(channel.cid)
			self.showFavourites()
		elif self.mode != self.GROUPS:
			actions = [(_("Add last"), "last"), (_("Add first"), "first"),]
			def cb(entry=None):
				if entry is not None:
					self.db.addFav(channel.cid, entry[1] == "first" and True or False)
			self.session.openWithCallback(cb, ChoiceBox,_('Add "%s" to favourites') % channel.name, actions)

	def delHistoryCurrrent(self):
		channel = self.getSelected()
		if not channel:
			return
		if self.mode == self.HISTORY:
			if self.history.delCurrent(channel.cid):
				if self.history.counts() > 1:
					self.openHistory()
				else:
					if self.saved_state is not None:
						self.recoverState(self.saved_state)
					else:
						self.showGroups()
					self["key_yellow"].setText("")
					self.close(None)

	def clearHistoryList(self):
		channel = self.getSelected()
		if not channel:
			return
		if self.mode == self.HISTORY:
			if self.history.clear():
				if self.saved_state is not None:
					self.recoverState(self.saved_state)
				else:
					self.showGroups()
				self["key_yellow"].setText("")
				self.close(None)

	def showMenu(self):
		self.dlg_actions = None
		actions = []
		current = self.getSelected()
		if self.player and self.player.zap_service_running != None and self.player.zap_service != None:
			next = (self.player.zap_service_running - int(time())) // 60
			if next > 0:
				next = '+%s' % next
			actions += [(_("Stop zap timer for service '%s' (%s min)") % (self.player.zap_service.name, next), self.zapTimerStop)]
		if self.mode != self.GROUPS and self.player and current and (not self.player.zap_service or current.cid != self.player.zap_service.cid):
			actions += [(_("Start zap timer for service '%s'") % current.name, self.zapTimerPrerare)]
		if self.mode == self.HISTORY:
			if current:
				if TMBD and self.current_event_info:
					actions += [(_("Search in TMBD"), self.runTMBD)]
				if self.history.counts() > 1:
					curr = self.history.now()
					if curr and curr.cid != current.cid:
						actions += [(_('Delete "%s" from history list') % current.name, self.delHistoryCurrrent)]
					actions += [(_('Clear history list'), self.clearHistoryList)]
				if current.has_archive:
					actions += [(_('Open archive for "%s"') % current.name, self.showEpgList)]
		elif self.mode in [self.ALL, self.GROUP]:
			if current and TMBD and self.current_event_info:
				actions += [(_("Search in TMBD"), self.runTMBD)]
			if current and not self.db.isFavCid(current.cid):
				actions += [(_('Add "%s" to favourites') % current.name, self.addRemoveFavourites),]
			if current and current.has_archive:
				actions += [(_('Open archive for "%s"') % current.name, self.showEpgList)]
			if current and self.mode != self.GROUPS:
				order = config.plugins.IPtvDream.channel_order.value
				actions += [(_("Sort by number") + (order == "number" and " *" or ""), self.sortByNumber), (_("Sort by name") + (order == "name" and " *" or ""), self.sortByName),]
		elif self.mode == self.FAV:
			if current:
				curr = self.history.now()
				if TMBD and self.current_event_info:
					actions += [(_("Search in TMBD"), self.runTMBD)]
				if curr and curr.cid != current.cid:
					actions += [(_('Remove "%s" from favourites') % current.name, self.addRemoveFavourites),]
				if current.has_archive:
					actions += [(_('Open archive for "%s"') % current.name, self.showEpgList)]
				if curr and curr.mode == self.mode:
					if not self.edit_mode:
						actions += [(_("Enter edit mode"), self.confirmStartEditing)]
					else:
						actions += [(_("Exit edit mode"), self.notifyFinishEditing)]
		actions += [("-------------------------------", None)]
		actions += [(_("Open plugin settings"), self.openSettings)]
		if self.db.AUTH_TYPE:
			actions += [(_("Clear login data and exit"), self.clearLogin)]
		actions += [("-------------------------------", None)]
		if current and self.mode != self.GROUPS and self.player and not self.player.shift and self.player.cid and current.cid == self.player.cid:
			actions += [(_('Restart current service "%s"') % current.name, self.restartCurrentService)]

		def cb(entry=None):
			if entry is not None:
				func = entry[1]
				if func:
					self.dlg_actions = True
					func()
		if actions:
			self.session.openWithCallback(cb, ChoiceBox, _("Context menu"), actions)

	def restartCurrentService(self):
		def cb(answer=None):
			self.close(None)
			return
		try:
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		except:
			ref = self.session.nav.getCurrentlyPlayingServiceReference()
		if ref:
			self.session.openWithCallback(cb, MessageBox, _("Force restart service!"), MessageBox.TYPE_INFO, timeout=3)
			try:
				self.session.nav.playService(ref, checkParentalControl=False, forceRestart=True)
			except:
				self.session.nav.playService(ref, forceRestart=True)

	def zapTimerStop(self):
		if self.player:
			self.player.zapTimer.stop()
			self.player.zap_service = self.player.zap_service_running = None
			self.close(None, None, 0)

	def zapTimerEpgStart(self, min=None):
		if min:
			current = self.getSelected()
			if self.mode != self.GROUPS and current:
				try:
					minutes = int(min)
				except:
					return
				self.player.zap_service_running = int(time()) + (minutes * 60)
				self.player.zap_service = HistoryEntry(self.mode, self.gid, 0, current.cid, self.list.getSelectedIndex())
				self.player.zap_service.name = current.name
				self.player.zapTimer.startLongTimer(minutes * 60)
				self.close(None, None, minutes)

	def zapTimerStart(self, min=None):
		if min:
			current = self.getSelected()
			if self.mode != self.GROUPS and current:
				try:
					min = int(min)
				except:
					return
				else:
					if min == 0:
						return
				minutes = min * 60
				self.player.zap_service_running = int(time()) + minutes
				self.player.zap_service = HistoryEntry(self.mode, self.gid, 0, current.cid, self.list.getSelectedIndex())
				self.player.zap_service.name = current.name
				self.player.zapTimer.startLongTimer(minutes)
				self.close(None, None, minutes)

	def zapTimerPrerare(self):
		if self.dlg_actions:
			self.dlg_actions = None
			self.waitTimer.start(500, True)
			return
		if self.player:
			self.player.zapTimer.stop()
			self.player.zap_service = self.player.zap_service_running = None
			try:
				self.session.openWithCallback(self.zapTimerStart, InputBox, title=_("Zap to (min.)"), text="5", type=Input.NUMBER)
			except:
				try:
					self.session.open(MessageBox, _("This image does not support correct operation of the number set!"), MessageBox.TYPE_ERROR, timeout=8)
				except:
					pass

	def runTMBD(self):
		if TMBD and self.current_event_info:
			self.session.open(TMBD, self.current_event_info, False)

	def sortBy(self, what):
		channel = self.getSelected()
		if channel is None:
			return
		self.order_config.setValue(what)
		self.fillList()
		index = self.findChannelIndex(channel.cid)
		if index:
			self.list.moveToIndex(index)

	def sortByNumber(self):
		self.sortBy('number')

	def sortByName(self):
		self.sortBy('name')

	def confirmStartEditing(self):
		def cb(ret):
			if ret:
				self.startEditing()
		message = _(
			"In the editing mode you can reorder your favourites list. Quick help:\n"
			"- Select channel that you want to put to a new position.\n"
			"- Press OK to start moving the channel around with arrow buttons.\n"
			"- Press OK again to fix the position of the channel.\n"
			"- Press EXIT when done.\n"
			"Start editing mode?"
		)
		self.session.openWithCallback(cb, MessageBox, message, MessageBox.TYPE_YESNO)

	def startEditing(self):
		"""Start reordering of channels in the favourites list"""
		self.edit_mode = True
		self["actions"].setEnabled(False)
		self["move_actions"].setEnabled(True)

	def toggleMarkForMoving(self):
		if self.marked:
			self.marked = False
			self.list.highlight(None)
		else:
			self.marked = True
			channel = self.getSelected()
			if channel:
				self.list.highlight(channel.cid)

	def moveUp(self):
		if self.marked:
			self.list.moveEntryUp()
		else:
			self.list.up()

	def moveDown(self):
		if self.marked:
			self.list.moveEntryDown()
		else:
			self.list.down()

	def notifyFinishEditing(self):
		self.session.openWithCallback(
			lambda ret: self.finishEditing(),
			MessageBox, _("Exiting edit mode"), MessageBox.TYPE_INFO, enable_input=False, timeout=4)

	def finishEditing(self):
		self.edit_mode = False
		self["actions"].setEnabled(True)
		self["move_actions"].setEnabled(False)
		try:
			self.db.setFavourites([entry[0][0].cid for entry in self.list.list])
		except APIException as ex:
			self.session.open(
				MessageBox, "%s\n%s" % (_("Failed to save favourites list."), str(ex)), MessageBox.TYPE_ERROR)

	def showEpgList(self):
		channel = self.getSelected()
		if channel and self.modeChannels():
			self.session.openWithCallback(self.showEpgCB, IPtvDreamEpg, self.db, channel.cid, 0, self.mode)

	def showEpgCB(self, cid=None, archive_time=None, zaptimer=None):
		if zaptimer is not None and self.player:
			self.player.zapTimer.stop()
			self.player.zap_service = self.player.zap_service_running = None
			minutes = (int(zaptimer) - int(time())) // 60
			self.zapTimerEpgStart(minutes)
			return
		trace("selected program", cid, archive_time)
		if archive_time is not None:
			self.ok(archive_time)

	def getSelected(self):
		entry = self.list.getCurrent()
		trace("getSelected", entry and entry[0])
		if entry:
			if self.mode == self.GROUPS:
				try:
					return entry[0]
				except:
					return None
			else:
				try:
					return entry[0][0]
				except:
					return None
		return None

	def getCurrent(self):
		curr = self.history.now()
		if curr:
			return curr.cid
		return curr

	def modeChannels(self):
		return self.mode != self.GROUPS

	def nextChannel(self):
		self.list.down()
		if self.list.getCurrent():
			self.history.append(self.createHistoryEntry())
			self.saved_state = self.history.now()
			return self.getCurrent()
		return None

	def prevChannel(self):
		self.list.up()
		if self.list.getCurrent():
			self.history.append(self.createHistoryEntry())
			self.saved_state = self.history.now()
			return self.getCurrent()
		return None

	def historyNext(self):
		h = self.history.historyNext()
		if h is not None:
			self.saved_state = self.history.now()
			self.recoverState(h, True)
			return self.getCurrent()
		else:
			return None

	def historyPrev(self):
		h = self.history.historyPrev()
		if h is not None:
			self.saved_state = self.history.now()
			self.recoverState(h, True)
			return self.getCurrent()
		else:
			return None

	def findChannelIndex(self, cid):
		for i, entry in enumerate(self.list.list):
			channel = entry[0][0]
			if channel.cid == cid:
				return i
		return None

	def goToNumber(self, num):
		if self.alternativeNumber and self.mode != self.ALL:
			cid = self.db.findNumber(num)
			if cid is None:
				return None
			if len(self.list.list) >= num:
				self.list.moveToIndex(num - 1)
			else:
				return None
			self.history.append(self.createHistoryEntry())
			self.saved_state = self.history.now()
			return cid
		else:
			cid = self.db.findNumber(num)
			if cid is None:
				return None
			idx = self.findChannelIndex(cid)
			if idx is None:
				self.mode, self.gid = self.ALL, None
				self.fillList()
				idx = self.findChannelIndex(cid)
			self.list.moveToIndex(idx)
			self.history.append(self.createHistoryEntry())
			self.saved_state = self.history.now()
			return cid

	def openSettings(self,answer=None):
		if answer is None:
			self.session.openWithCallback(self.openSettings, MessageBox, _("Open provider settings?"), default=False)
		elif answer:
			self.close(None, None, 'settings')

	def clearLogin(self,answer=None):
		if answer is None:
			self.session.openWithCallback(self.clearLogin, MessageBox, _("Clear login data and exit") + "?", default=False)
		elif answer:
			self.close(None, None, 'clear_login')


class IPtvDreamEpg(Screen):
	def __init__(self, session, db, cid, shift, mode):
		Screen.__init__(self, session)

		self["caption"] = Label(_("EPG List"))
		self["btn_red"] = Pixmap()
		self["key_red"] = Label(_("Archive"))
		self["key_green"] = Label(_("Details"))
		self["list"] = self.list = ListSource()

		self["epgName"] = Label()
		self["epgDescription"] = Label()
		self["epgTime"] = Label()
		self["epgDuration"] = Label()

		self["epgProgress"] = Slider(0, 100)
		self["progress"] = self._progress = EpgProgress()
		self._progress.onChanged.append(lambda value: self["epgProgress"].setValue(int(100 * value)))

		# auto resize some widgets
		self._info_part = VerticalLayoutPart(self, (self["epgTime"], self["epgProgress"], self["epgDuration"]))

		self["packetExpire"] = Label()

		self["actions"] = ActionMap(
			["OkCancelActions", "IPtvDreamEpgListActions", "ColorActions"], {
				"cancel": self.close,
				"ok": self.archive,
				"up": self.up,
				"down": self.down,
				"pageUp": self.pageUp,
				"pageDown": self.pageDown,
				"nextDay": self.nextDay,
				"prevDay": self.prevDay,
				"green": self.showInfo,
				"contextMenu": self.showMenu,
				"showInfo": self.runTMBD,
				"red": self.archive
			}, -1)

		self.db = db  # type: AbstractStream
		self.cid = cid
		self.shift = shift
		self.curr = False
		self.day = 0
		self.mode = mode
		self.list.onSelectionChanged.append(self.updateLabels)
		self.onShown.append(self.start)

	def start(self):
		self.onShown.remove(self.start)
		self.fillList(True)

	def buildEpgEntry(self, entry):
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			pixmap = rec_png
		else:
			pixmap = None
		return entry, pixmap, entry.begin.strftime('%a'), entry.begin.strftime('%H:%M'), entry.name

	def fillList(self, init=False):
		if self.cid is None:
			return

		time = syncTime() + secTd(self.shift)
		d = time + timedelta(self.day)

		epg_list = []
		try:
			epg_list = self.db.getDayEpg(self.cid, datetime(d.year, d.month, d.day))
		except APIException as e:
			self.session.open(MessageBox, _("Can not load EPG:") + str(e), MessageBox.TYPE_ERROR, 5)
		self.list.setList(list(map(self.buildEpgEntry, epg_list)))
		self.list.setIndex(0)

		if init:
			self.setTitle("EPG / %s / %s %s" % (self.db.channels[self.cid].name, d.strftime("%d"), _(d.strftime("%b"))))
			for i, program in enumerate(epg_list):
				if program.isAt(time):
					self.list.setIndex(i)
					break

	def updateLabels(self):
		entry = self.list.getCurrent()
		if not entry:
			return

		entry = entry[0]
		self.setTitle("EPG / %s / %s %s" % (self.db.channels[self.cid].name, entry.begin.strftime("%d"), _(entry.begin.strftime("%b"))))
		self["epgName"].setText(entry.name)
		self["epgTime"].setText(entry.begin.strftime("%d.%m  %H:%M") + " - " + entry.end.strftime("%H:%M"))
		self["epgDescription"].setText(entry.description)
		self.curr = False
		live = ""
		if self.shift:
			t = syncTime() + secTd(self.shift)
			curr = entry.isAt(t)
			if not curr:
				t = syncTime()
				curr = entry.isAt(t)
				if curr:
					live = " (L)"
			else:
				self.curr = True
				live = " (A)"
		else:
			t = syncTime()
			curr = entry.isAt(t)
		if curr:
			self["epgDuration"].setText(_("+%d min") % int(entry.timeLeft(t) / 60) + live)
			self["epgProgress"].show()
		else:
			self["epgDuration"].setText(_("%d min") % int(entry.duration() / 60))
			self["epgProgress"].hide()
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			self["btn_red"].show()
			self["key_red"].show()
		else:
			self["btn_red"].hide()
			self["key_red"].hide()
		self._progress.setEpg(entry, self.curr and self.shift or 0)
		self._info_part.updateLayout()

	def archive(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			self.close(self.cid, entry.begin)

	def showMenu(self):
		actions = []
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		if entry.begin > syncTime():
			actions += [(_("Set zap time to '%s'") % entry.begin.strftime("%d.%m - %H:%M"), self.zapTimerPrerare)]

		def cb(action=None):
			if action is not None:
				func = action[1]
				if func:
					func()
		if actions:
			self.session.openWithCallback(cb, ChoiceBox, _("Context menu"), actions)

	def zapTimerPrerare(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		if entry.begin > syncTime():
			self.close(self.cid, None, entry.begin_timestamp)

	def runTMBD(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		if TMBD:
			eventname = entry[0].name
			if eventname:
				self.session.open(TMBD, eventname, False)
		else:
			self.showInfo()

	def showInfo(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		self.session.openWithCallback(self.infoClosed, IPtvDreamEpgInfo, self.db.channels[self.cid], entry, self.curr and self.shift or 0, self.mode)

	def infoClosed(self, time=None):
		if time is not None:
			self.close(self.cid, time)

	def up(self):
		idx = self.list.getIndex()
		if idx == 0:
			self.prevDay()
			self.list.setIndex(self.list.count() - 1)
		else:
			self.list.selectPrevious()

	def down(self):
		idx = self.list.getIndex()
		if idx == self.list.count() - 1 or self.list.count() == 0:
			self.nextDay()
		else:
			self.list.selectNext()

	def pageUp(self):
		idx = self.list.getIndex()
		if idx == 0:
			self.prevDay()
			self.list.setIndex(self.list.count() - 1)
		else:
			self.list.pageUp()

	def pageDown(self):
		idx = self.list.getIndex()
		if idx == self.list.count() - 1 or self.list.count() == 0:
			self.nextDay()
		else:
			self.list.pageDown()

	def nextDay(self):
		self.day += 1
		self.fillList()

	def prevDay(self):
		self.day -= 1
		self.fillList()


class IPtvDreamEpgInfo(Screen):
	def __init__(self, session, channel, entry, shift, mode):
		"""
		Screen to show information for single EPG entry
		:type entry: utils.EPG
		:type channel: utils.Channel
		"""
		Screen.__init__(self, session)
		self.entry = entry
		self.channel = channel
		self.shift = shift
		self.mode = mode

		self.setTitle("%d. %s" % ((self.mode != 1 and config.plugins.IPtvDream.alternative_number_in_servicelist.value and channel.alt_number) or channel.number, channel.name))

		self["epgName"] = Label(entry.name)
		self["epgDescription"] = ScrollLabel(entry.description or _("No detailed information"))
		self._main_part = VerticalLayoutPart(self, widgetsToMove=())

		self["epgTime"] = Label(entry.begin.strftime("%a %H:%M"))
		self["epgDate"] = Label(entry.begin.strftime("%d.%m.%Y"))
		self["epgDuration"] = Label()

		self["epgProgress"] = Slider(0, 100)
		self["progress"] = self._progress = EpgProgress()
		self._progress.onChanged.append(self.updateProgress)
		self.onLayoutFinish.append(self.initGui)

		self["btn_red"] = Pixmap()
		self["key_red"] = Label(_("Archive"))

		if not self.hasArchive():
			self["btn_red"].hide()
			self["key_red"].hide()

		self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions", "IPtvDreamChannelListActions"], {
			"cancel": self.close,
			"red": self.playArchive,
			"ok": self.close,
			"showEPGList": self.runTMBD,
			"up": self["epgDescription"].pageUp,
			"down": self["epgDescription"].pageDown
		}, -1)

	def initGui(self):
		self._main_part.updateLayout()
		self._progress.setEpg(self.entry, self.shift)

	def runTMBD(self):
		if TMBD:
			eventname = self.entry.name
			if eventname:
				self.session.open(TMBD, eventname, False)

	def hasArchive(self):
		return self.channel.has_archive and self.entry.begin < syncTime()

	def playArchive(self):
		if self.hasArchive():
			self.close(self.entry.begin)

	def updateProgress(self, value):
		if self.shift:
			t = syncTime() + secTd(self.shift)
		else:
			t = syncTime()
		if self.entry.isAt(t):
			self["epgDuration"].setText(_("+%d min") % int(self.entry.timeLeft(t) / 60))
			self["epgProgress"].show()
		else:
			self["epgDuration"].setText(_("%d min") % int(self.entry.duration() / 60))
			self["epgProgress"].hide()
		self["epgProgress"].setValue(int(100 * value))
