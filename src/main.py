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
from six.moves import urllib_parse
try:
	# noinspection PyUnresolvedReferences
	from typing import Callable, Optional, List, Tuple  # pylint: disable=unused-import
except ImportError:
	pass

# enigma2 imports
from Components.Sources.List import List as ListSource
from Components.Sources.Boolean import Boolean
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
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.MinuteInput import MinuteInput
from Screens.ChoiceBox import ChoiceBox
from Screens.InputBox import InputBox
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN, SCOPE_SKIN, SCOPE_SYSETC, SCOPE_CURRENT_PLUGIN

# enigma2 core imports
from enigma import eListboxPythonMultiContent, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER, \
	eLabel, eSize, ePoint
from enigma import eServiceReference
from skin import parseFont, parseColor

# plugin imports
from .layer import eTimer
from .common import NumberEnter
from .utils import trace, tdSec, secTd, syncTime, APIException, APIWrongPin, EPG, timeit
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


class IPtvDreamStreamPlayer(
		ShowHideScreen, AutoAudioSelection, MainMenuScreen,
		InfoBarBase, InfoBarPlugins, InfoBarExtensions,
		InfoBarNotifications, InfoBarAudioSelection, InfoBarSubtitleSupport):
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

		trace("start stream player")
		self.db = db
		from .manager import manager
		self.cfg = manager.getConfig(self.db.NAME)
		self.cid = None

		standbyNotifier.onStandbyChanged.append(self.standbyChanged)
		self.onClose.append(lambda: standbyNotifier.onStandbyChanged.remove(self.standbyChanged))

		self.channels = self.session.instantiateDialog(IPtvDreamChannels, self.db, self)
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
		self["key_green"] = Label(_("Settings"))
		self["key_yellow"] = Label(_("Audio"))
		self["key_blue"] = Label(_("Extensions"))

		# TODO: think more
		self["archiveDate"] = Label("")
		self["inArchive"] = Boolean(False)

		self["picon"] = Pixmap()
		self._picon = Picon(self["picon"])

		self["provider"] = Pixmap()
		icon_path = resolveFilename(SCOPE_CURRENT_PLUGIN, 'Extensions/IPtvDream/logo/%s.png' % self.db.NAME)
		self.onFirstExecBegin.insert(0, lambda: self["provider"].instance.setPixmap(LoadPixmap(icon_path)))

		# TODO: ActionMap add help.
		self["actions"] = ActionMap(["IPtvDreamInfobarActions", "ColorActions", "OkCancelActions"], {
				"cancel": self.confirmExit,
				"closePlugin": self.exit,
				"openVideos": self.openVod,
				"red": self.showEpg,
				"green": self.openSettings,
				"openServiceList": self.showList,
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
		self.epgTimer = eTimer()
		self.epgProgressTimer = eTimer()
		self.epgTimer.callback.append(self.epgEvent)
		self.epgProgressTimer.callback.append(self.epgUpdateProgress)

		self.archive_pause = None
		self.shift = 0

	# Init and destroy

	def start(self):
		trace("player start")
		self.showList()

	def exit(self, ret=None):
		self.channels.saveQuery()
		self.session.deleteDialog(self.channels)
		self.close(ret)

	def confirmExit(self):
		def cb(ret):
			if ret:
				self.exit()
		self.session.openWithCallback(cb, MessageBox, _("Exit plugin?"), MessageBox.TYPE_YESNO)

	# Play

	def play(self, cid):
		trace("play cid =", cid)

		self.cid = cid
		self.session.nav.stopService()
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
		self.session.openWithCallback(
				self.getUrl, InputBox, title=_("Enter protect password"),
				windowTitle=_("Channel Locked"), type=Input.PIN)

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
		self.updateLabels()

	def updateLabels(self):
		cid = self.cid
		self["channelName"].setText("%d. %s" % (self.db.channels[cid].number, self.db.channels[cid].name))
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
		if time_shift:
			self.archive_pause = None
			self["live_actions"].setEnabled(False)
			self["number_actions"].setEnabled(False)
			self["archive_actions"].setEnabled(True)
			self["inArchive"].setBoolean(True)
		else:
			self["archive_actions"].setEnabled(False)
			self["live_actions"].setEnabled(True)
			self["number_actions"].setEnabled(True)
			self["inArchive"].setBoolean(False)

	def time(self):
		if self.shift:
			return syncTime() + secTd(self.shift)
		return None

	def archiveSeekFwd(self):
		self.session.openWithCallback(self.fwdJumpMinutes, MinuteInput)

	def archiveSeekRwd(self):
		self.session.openWithCallback(self.rwdJumpMinutes, MinuteInput)

	def fwdJumpMinutes(self, minutes):
		return self.fwdJump(minutes * 60)

	def rwdJumpMinutes(self, minutes):
		return self.rwdJump(minutes * 60)

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

	def exitArchive(self):
		self.setArchiveShift(0)
		self.play(self.cid)

	# EPG

	def epgEvent(self):
		# first stop timers
		self.epgTimer.stop()
		self.epgProgressTimer.stop()
		cid = self.cid
		time = syncTime() + secTd(self.shift)

		def setEpgCurrent():
			curr = self.db.channels[cid].epgCurrent(time)
			if not curr:
				return False

			self.currentEpg = curr
			self["currentName"].setText(curr.name)
			self["currentTime"].setText(curr.begin.strftime("%H:%M"))
			self["nextTime"].setText(curr.end.strftime("%H:%M"))
			self.epgTimer.start(curr.timeLeftMilliseconds(time) + 1000)
			self["currentDuration"].setText("+%d min" % (curr.timeLeft(time) / 60))
			self["progressBar"].setValue(curr.percent(time, PROGRESS_SIZE))
			self.epgProgressTimer.start(PROGRESS_TIMER)
			if self.shift:
				self["archiveDate"].setText(curr.begin.strftime("%d.%m"))
				self["archiveDate"].show()
			else:
				self["archiveDate"].hide()
			return True

		if not setEpgCurrent():
			try:
				self.db.loadDayEpg(cid, time)
			except APIException as e:
				trace("ERROR load epg failed! cid =", cid, bool(self.shift), e)
			if not setEpgCurrent():
				self["currentName"].setText('')
				self["currentTime"].setText('')
				self["nextTime"].setText('')
				self["currentDuration"].setText('')
				self["progressBar"].setValue(0)

		def setEpgNext():
			e = self.db.channels[cid].epgNext(time)
			if not e:
				return False
			self['nextName'].setText(e.name)
			self['nextDuration'].setText("%d min" % (e.duration() / 60))
			return True

		if not setEpgNext():
			try:
				self.db.loadDayEpg(cid, time)
			except APIException:
				trace("load epg next failed!")
			if not setEpgNext():
				self["nextName"].setText('')
				self["nextDuration"].setText('')

		self.serviceStarted()

	def epgUpdateProgress(self):
		time = syncTime() + secTd(self.shift)
		self["currentDuration"].setText("+%d min" % (self.currentEpg.timeLeft(time) / 60))
		self["progressBar"].setValue(self.currentEpg.percent(time, PROGRESS_SIZE))
		self.epgProgressTimer.start(PROGRESS_TIMER)

	# Dialogs

	def showEpg(self):
		self.session.openWithCallback(self.programSelected, IPtvDreamEpg, self.db, self.cid, self.shift)

	def programSelected(self, cid=None, time=None):
		if cid is not None and time is not None:
			self.setArchiveShift(tdSec(time-syncTime()))  # shift < 0
			self.play(cid)

	def showList(self):
		self.session.execDialog(self.channels)
		self.channels.callback = self.listClosed

	def listClosed(self, cid=None, time=None, action=None):
		if action is None:
			self.channelSelected(cid, time)
		else:
			self.exit(action)

	def channelSelected(self, cid, time=None):
		if cid is None:
			return
		if time:
			self.programSelected(cid, time)
		elif cid != self.cid:
			self.switchChannel(cid)

	def openSettings(self):
		self.exit('settings')

	def openVod(self):
		self.exit('vod')

	def createSummary(self):
		return InfoBarSummary

	# Channels

	def switchChannel(self, cid):
		# FIXME: zapping breaks archive shift
		trace("switch channel", self.cid)
		self.setArchiveShift(0)
		self.play(cid)

	def nextChannel(self):
		cid = self.channels.nextChannel()
		self.switchChannel(cid)

	def previousChannel(self):
		cid = self.channels.prevChannel()
		self.switchChannel(cid)

	def historyNext(self):
		if self.channels.historyNext():
			cid = self.channels.getCurrent()
			self.switchChannel(cid)

	def historyBack(self):
		if self.channels.historyPrev():
			cid = self.channels.getCurrent()
			self.switchChannel(cid)

	def keyNumberGlobal(self, number):
		self.session.openWithCallback(self.numberEntered, NumberEnter, number)

	def numberEntered(self, num=None):
		trace("numberEntered", num)
		if num is not None and self.channels.goToNumber(num):
			cid = self.channels.getCurrent()
			self.switchChannel(cid)

	# Errors

	def showError(self, msg):
		self.session.open(MessageBox, msg, MessageBox.TYPE_ERROR, 5)


class ChannelList(MenuList):
	def __init__(self):
		MenuList.__init__(self, [], content=eListboxPythonMultiContent, enableWrapAround=True)
		self.list = []
		self.index = {}
		self.col = {}
		self.fontCalc = []

		self.pixmapProgressBar = None
		self.pixmapArchive = None
		self.listItemHeight = 28
		self.listItemWidth = 0
		self.l.setFont(0, parseFont("Regular;22", ((1, 1), (1, 1))))
		self.l.setFont(1, parseFont("Regular;18", ((1, 1), (1, 1))))
		self.l.setFont(2, parseFont("Regular;20", ((1, 1), (1, 1))))
		self.showEpgProgress = config.usage.show_event_progress_in_servicelist.value
		self.num = 0
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
		self.fontCalc[2].setFont(parseFont("Regular;20", ((1, 1), (1, 1))))

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

	def setEnumerated(self, enumerated):
		if enumerated:
			self.num = 1
		else:
			self.num = 0

	def setChannelsList(self, channels):
		self.setList(list(map(self.buildChannelEntry, channels)))
		# Create map from channel id to its index in list
		self.index = dict((entry[0][0].cid, i) for (i, entry) in enumerate(self.list))
		if self.num:
			self.num = 1

	def updateChannel(self, cid, channel):
		try:
			index = self.index[cid]
		except KeyError:
			return
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
		self.index[cid] = i

	def highlight(self, cid):
		self.highlight_cid = cid

	def setGroupList(self, groups):
		self.setList(list(map(self.buildGroupEntry, groups)))
		self.index = {}

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

		if self.num:
			xoffset += 55
			text = str(c.number)
			lst.append(
				(eListboxPythonMultiContent.TYPE_TEXT, 0, 0, xoffset-5, self.listItemHeight,
					2, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text))

		if self.pixmapArchive:
			width = self.pixmapArchive.size().width()
			height = self.pixmapArchive.size().height()
			if c.has_archive:
				lst.append(
					(eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,
						xoffset, (self.listItemHeight - height) / 2, width, height, self.pixmapArchive))
			xoffset += width+5

		if self.showEpgProgress:
			width = 52
			height = 6
			if e:
				percent = e.percent(syncTime(), 100)
				lst.extend([
					(eListboxPythonMultiContent.TYPE_PROGRESS,
						xoffset+1, (self.listItemHeight-height)/2, width, height,
						percent, 0, self.col['colorEventProgressbar'], self.col['colorEventProgressbarSelected']),
					(eListboxPythonMultiContent.TYPE_PROGRESS,
						xoffset, (self.listItemHeight-height)/2 - 1, width+2, height+2,
						0, 1, self.col['colorEventProgressbarBorder'], self.col['colorEventProgressbarBorderSelected'])
				])
			xoffset += width+7

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
		xoffset += width+10

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

	def append(self, val):
		while len(self._history) > self._index + 1:
			self._history.pop()
		self._history.append(val)
		if len(self._history) > self._size:
			self._history.pop(0)
		else:
			self._index += 1

	def historyPrev(self):
		if self._index < 1:
			return None
		else:
			self._index -= 1
			return self._history[self._index]

	def historyNext(self):
		if self._index+1 == len(self._history):
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

	GROUPS, ALL, GROUP, FAV = range(4)

	def __init__(self, session, db, player_ref):
		Screen.__init__(self, session)

		trace("channels init")
		self.history = History(10)
		self.db = db  # type: AbstractStream
		self.player_ref = player_ref
		from .manager import manager
		self.cfg = manager.getConfig(self.db.NAME)

		self["caption"] = Label(_("Channel Selection"))
		self["key_red"] = Label(_("All"))
		self["key_green"] = Label(_("Groups"))
		self["key_yellow"] = Label(_("Add"))
		self["key_blue"] = Label(_("Favourites"))

		self.list = self["list"] = ChannelList()

		self["channelName"] = Label()
		self["epgName"] = Label()
		self["epgTime"] = Label()
		self["epgDescription"] = Label()
		self["epgNextTime"] = Label()
		self["epgNextName"] = Label()
		self["epgNextDescription"] = Label()

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

		self["actions"] = ActionMap(
			["OkCancelActions", "IPtvDreamChannelListActions"], {
				"cancel": self.exit,
				"ok": self.ok,
				"showAll": self.showAll,
				"showGroups": self.showGroups,
				"addFavourites": self.addRemoveFavourites,
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
		if not self.history.isEmpty():
			self.saved_state = self.history.now().copy()
		else:
			self.saved_state = None

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

	def recoverState(self, state):
		"""
		:param HistoryEntry state:
		"""
		self.mode, self.gid = state.mode, state.gid
		if self.mode == self.GROUPS:
			self.fillGroupsList()
			self.list.moveToIndex(self.saved_state.gr_idx)
		else:
			self.fillList()
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
			self.history.append(HistoryEntry(self.mode, self.gid, 0, cid, idx))
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
		if self.gid is not None:
			for idx, g in enumerate(groups):
				if g.gid == self.gid:
					self.list.moveToIndex(idx)
					break
			else:
				self.gid = None

	def fillList(self):
		title = [self.db.NAME]
		# Highlight is used for edit mode
		# self.list.highlight(self.player_ref.cid)
		order = self.order_config.getValue()

		if self.mode == self.GROUPS:
			self.fillGroupsList()
			title.append(_("Groups"))
		elif self.mode == self.GROUP:
			self.setChannels(self.db.selectChannels(self.gid, sort_key=order))
			title.append(self.db.groups[self.gid].title)
		elif self.mode == self.ALL:
			self.setChannels(self.db.selectAll(sort_key=order))
			title.append(_("All channels"))
		elif self.mode == self.FAV:
			self.setChannels(self.db.selectFavourites())
			title.append(_("Favourites"))

		self.setTitle(" / ".join(title))
		if self.mode == self.FAV:
			self["key_yellow"].setText(_("Remove"))
		else:
			self["key_yellow"].setText(_("Add"))

	def selectionChanged(self):
		channel = self.getSelected()
		trace("selection =", channel)

		if self.mode == self.GROUPS or channel is None:
			self["channelName"].setText("")
			self.hideEpgLabels()
			self.hideEpgNextLabels()
		else:
			self["channelName"].setText(channel.name)
			self["channelName"].show()
			curr = self._worker.get(channel.cid)
			if curr:
				self["epgTime"].setText("%s - %s" % (curr.begin.strftime("%H:%M"), curr.end.strftime("%H:%M")))
				self["epgName"].setText(curr.name)
				self["epgName"].show()
				self["epgTime"].show()
				self["epgDescription"].setText(curr.description)
				self["epgDescription"].show()
				self._progress.setEpg(curr)
				self["epgProgress"].show()
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
		self.mode = self.ALL
		self.fillList()

	def showFavourites(self):
		self.mode = self.FAV
		self.fillList()

	def npGroup(self, diff):
		if self.mode == self.GROUP:
			groups = self.db.selectGroups()
			for idx, g in enumerate(groups):
				if g.gid == self.gid:
					self.gid = groups[(idx + diff) % len(groups)].gid
					self.fillList()
					break

	def nextGroup(self):
		self.npGroup(1)

	def prevGroup(self):
		self.npGroup(-1)

	def addRemoveFavourites(self):
		channel = self.getSelected()
		if not channel:
			return
		if self.mode == self.FAV:
			self.db.rmFav(channel.cid)
			self.showFavourites()
		elif self.mode != self.GROUPS:
			self.db.addFav(channel.cid)

	def showMenu(self):
		actions = []
		current = self.getSelected()
		if self.mode in [self.ALL, self.GROUP]:
			actions += [
				(_("Sort by number"), self.sortByNumber),
				(_("Sort by name"), self.sortByName),
			]
			if current:
				actions += [
					(_('Add "%s" to favourites') % current.name, self.addRemoveFavourites),
				]
				if current.has_archive:
					actions += [(_('Open archive for "%s"') % current.name, self.showEpgList)]
		if self.mode == self.FAV:
			if current:
				actions += [
					(_('Remove "%s" from favourites') % current.name, self.addRemoveFavourites),
				]
				if current.has_archive:
					actions += [(_('Open archive for "%s"') % current.name, self.showEpgList)]
				if not self.edit_mode:
					actions += [(_("Enter edit mode"), self.confirmStartEditing)]
				else:
					actions += [(_("Exit edit mode"), self.notifyFinishEditing)]
		actions += [(_("Open plugin settings"), self.openSettings)]
		if self.db.AUTH_TYPE:
			actions += [(_("Clear login data and exit"), self.clearLogin)]

		def cb(entry=None):
			if entry is not None:
				func = entry[1]
				func()
		if actions:
			self.session.openWithCallback(cb, ChoiceBox, _("Context menu"), actions)

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
		self.session.openWithCallback(cb, MessageBox, _(message), MessageBox.TYPE_YESNO)

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
			MessageBox, _("Exiting edit mode"), MessageBox.TYPE_INFO, timeout=5)

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
			self.session.openWithCallback(self.showEpgCB, IPtvDreamEpg, self.db, channel.cid, 0)

	def showEpgCB(self, cid=None, time=None):
		trace("selected program", cid, time)
		if time is not None:
			self.ok(time)

	def getSelected(self):
		entry = self.list.getCurrent()
		trace("getSelected", entry and entry[0])
		if entry:
			if self.mode == self.GROUPS:
				return entry[0]
			else:
				return entry[0][0]
		return None

	def getCurrent(self):
		return self.history.now().cid

	def modeChannels(self):
		return self.mode != self.GROUPS

	def nextChannel(self):
		self.list.down()
		self.history.append(self.createHistoryEntry())
		return self.getCurrent()

	def prevChannel(self):
		self.list.up()
		self.history.append(self.createHistoryEntry())
		return self.getCurrent()

	def historyNext(self):
		h = self.history.historyNext()
		if h is not None:
			self.recoverState(h)
			return self.getCurrent()
		else:
			return None

	def historyPrev(self):
		h = self.history.historyPrev()
		if h is not None:
			self.recoverState(h)
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
		return cid

	def openSettings(self):
		self.close(None, None, 'settings')

	def clearLogin(self):
		self.close(None, None, 'clear_login')


class IPtvDreamEpg(Screen):
	def __init__(self, session, db, cid, shift):
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
				"showInfo": self.showInfo,
				"red": self.archive
			}, -1)

		self.db = db  # type: AbstractStream
		self.cid = cid
		self.shift = shift
		self.day = 0
		self.list.onSelectionChanged.append(self.updateLabels)
		self.onShown.append(self.start)

	def start(self):
		self.onShown.remove(self.start)
		self.fillList()

	def buildEpgEntry(self, entry):
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			pixmap = rec_png
		else:
			pixmap = None
		return entry, pixmap, entry.begin.strftime('%a'), entry.begin.strftime('%H:%M'), entry.name

	def fillList(self):
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
		self.setTitle("EPG / %s / %s %s" % (self.db.channels[self.cid].name, d.strftime("%d"), _(d.strftime("%b"))))
		self.list.setIndex(0)

		if self.day == 0:
			for i, program in enumerate(epg_list):
				if program.isAt(time):
					self.list.setIndex(i)
					break

	def updateLabels(self):
		entry = self.list.getCurrent()
		if not entry:
			return

		entry = entry[0]
		self["epgName"].setText(entry.name)
		self["epgTime"].setText(entry.begin.strftime("%d.%m %H:%M"))
		self["epgDescription"].setText(entry.description)
		self["epgDuration"].setText("%s min" % (entry.duration() / 60))
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			self["btn_red"].show()
			self["key_red"].show()
		else:
			self["btn_red"].hide()
			self["key_red"].hide()
		self._progress.setEpg(entry)
		self._info_part.updateLayout()

	def archive(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		if self.db.channels[self.cid].has_archive and entry.begin < syncTime():
			self.close(self.cid, entry.begin)

	def showInfo(self):
		entry = self.list.getCurrent()
		if not entry:
			return
		entry = entry[0]
		self.session.openWithCallback(self.infoClosed, IPtvDreamEpgInfo, self.db.channels[self.cid], entry)

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
	def __init__(self, session, channel, entry):
		"""
		Screen to show information for single EPG entry
		:type entry: utils.EPG
		:type channel: utils.Channel
		"""
		Screen.__init__(self, session)
		self.entry = entry
		self.channel = channel

		self.setTitle("%d. %s" % (channel.number, channel.name))

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

		self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions"], {
			"cancel": self.close,
			"red": self.playArchive,
			"ok": self.close,
			"up": self["epgDescription"].pageUp,
			"down": self["epgDescription"].pageDown
		}, -1)

	def initGui(self):
		self._main_part.updateLayout()
		self._progress.setEpg(self.entry)

	def hasArchive(self):
		return self.channel.has_archive and self.entry.begin < syncTime()

	def playArchive(self):
		if self.hasArchive():
			self.close(self.entry.begin)

	def updateProgress(self, value):
		t = syncTime()
		if self.entry.isAt(t):
			self["epgDuration"].setText("+%s min" % (self.entry.timeLeft(t) / 60))
		else:
			self["epgDuration"].setText("%s min" % (self.entry.duration() / 60))
		self["epgProgress"].setValue(int(100 * value))

# gettext HACK:
# [_("Jan"), _("Feb"), _("Mar"), _("Apr"), _("May"), _("Jun"), _("Jul"), _("Aug"), _("Sep"), _("Oct"), _("Nov") ]
