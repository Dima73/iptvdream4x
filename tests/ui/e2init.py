# -*- coding: utf-8 -*-

""" Minimal code to start enigma2 and copy of Session class defined in mytest.py """

from __future__ import print_function

# Setup enigma2 core module
import enigma
import eConsoleImpl
import eBaseImpl
enigma.eTimer = eBaseImpl.eTimer
enigma.eSocketNotifier = eBaseImpl.eSocketNotifier
enigma.eConsoleAppContainer = eConsoleImpl.eConsoleAppContainer

# Install enigma2 mainloop
import e2reactor
e2reactor.install()

from Screens.InfoBar import InfoBar
from Screens.SimpleSummary import SimpleSummary	

from skin import readSkin
from Screens.SessionGlobals import SessionGlobals

from Components.PluginComponent import plugins
from Plugins.Plugin import PluginDescriptor

class Session:
	def __init__(self, desktop = None, summary_desktop = None, navigation = None):
		self.desktop = desktop
		self.summary_desktop = summary_desktop
		self.nav = navigation
		self.delay_timer = enigma.eTimer()
		self.delay_timer.callback.append(self.processDelay)

		self.current_dialog = None

		self.dialog_stack = [ ]
		self.summary_stack = [ ]
		self.summary = None

		self.in_exec = False

		self.screen = SessionGlobals(self)

		for p in plugins.getPlugins(PluginDescriptor.WHERE_SESSIONSTART):
			try:
				p(reason=0, session=self)
			except:
				print("Plugin raised exception at WHERE_SESSIONSTART")
				import traceback
				traceback.print_exc()

	def processDelay(self):
		callback = self.current_dialog.callback

		retval = self.current_dialog.returnValue

		if self.current_dialog.isTmp:
			self.current_dialog.doClose()
#			dump(self.current_dialog)
			del self.current_dialog
		else:
			del self.current_dialog.callback

		self.popCurrent()
		if callback is not None:
			callback(*retval)

	def execBegin(self, first=True, do_show = True):
		assert not self.in_exec
		self.in_exec = True
		c = self.current_dialog

		# when this is an execbegin after a execend of a "higher" dialog,
		# popSummary already did the right thing.
		if first:
			self.instantiateSummaryDialog(c)

		c.saveKeyboardMode()
		c.execBegin()

		# when execBegin opened a new dialog, don't bother showing the old one.
		if c == self.current_dialog and do_show:
			c.show()

	def execEnd(self, last=True):
		assert self.in_exec
		self.in_exec = False

		self.current_dialog.execEnd()
		self.current_dialog.restoreKeyboardMode()
		self.current_dialog.hide()

		if last and self.summary:
			self.current_dialog.removeSummary(self.summary)
			self.popSummary()

	def instantiateDialog(self, screen, *arguments, **kwargs):
		return self.doInstantiateDialog(screen, arguments, kwargs, self.desktop)

	def deleteDialog(self, screen):
		screen.hide()
		screen.doClose()

	def instantiateSummaryDialog(self, screen, **kwargs):
		if self.summary_desktop is not None:
			self.pushSummary()
			summary = screen.createSummary() or SimpleSummary
			arguments = (screen,)
			self.summary = self.doInstantiateDialog(summary, arguments, kwargs, self.summary_desktop)
			self.summary.show()
			screen.addSummary(self.summary)

	def doInstantiateDialog(self, screen, arguments, kwargs, desktop):
		# create dialog
		dlg = screen(self, *arguments, **kwargs)
		if dlg is None:
			return
		# read skin data
		readSkin(dlg, None, dlg.skinName, desktop)
		# create GUI view of this dialog
		dlg.setDesktop(desktop)
		dlg.applySkin()
		return dlg

	def pushCurrent(self):
		if self.current_dialog is not None:
			self.dialog_stack.append((self.current_dialog, self.current_dialog.shown))
			self.execEnd(last=False)

	def popCurrent(self):
		if self.dialog_stack:
			(self.current_dialog, do_show) = self.dialog_stack.pop()
			self.execBegin(first=False, do_show=do_show)
		else:
			self.current_dialog = None

	def execDialog(self, dialog):
		self.pushCurrent()
		self.current_dialog = dialog
		self.current_dialog.isTmp = False
		self.current_dialog.callback = None # would cause re-entrancy problems.
		self.execBegin()

	def openWithCallback(self, callback, screen, *arguments, **kwargs):
		dlg = self.open(screen, *arguments, **kwargs)
		dlg.callback = callback
		return dlg

	def open(self, screen, *arguments, **kwargs):
		if self.dialog_stack and not self.in_exec:
			raise RuntimeError("modal open are allowed only from a screen which is modal!")
			# ...unless it's the very first screen.

		self.pushCurrent()
		dlg = self.current_dialog = self.instantiateDialog(screen, *arguments, **kwargs)
		dlg.isTmp = True
		dlg.callback = None
		self.execBegin()
		return dlg

	def close(self, screen, *retval):
		if not self.in_exec:
			print("close after exec!")
			return

		# be sure that the close is for the right dialog!
		# if it's not, you probably closed after another dialog
		# was opened. this can happen if you open a dialog
		# onExecBegin, and forget to do this only once.
		# after close of the top dialog, the underlying will
		# gain focus again (for a short time), thus triggering
		# the onExec, which opens the dialog again, closing the loop.
		assert screen == self.current_dialog

		self.current_dialog.returnValue = retval
		self.delay_timer.start(0, 1)
		self.execEnd()

	def pushSummary(self):
		if self.summary:
			self.summary.hide()
			self.summary_stack.append(self.summary)
			self.summary = None

	def popSummary(self):
		if self.summary:
			self.summary.doClose()
		self.summary = self.summary_stack and self.summary_stack.pop()
		if self.summary:
			self.summary.show()


_session = None


def getSession():
	global _session
	if _session is not None:
		return _session

	print("===== Init Session! =====")
	from Components.SetupDevices import InitSetupDevices
	InitSetupDevices()
	# import InfoBar to ensure correct import order

	from Components.config import config, ConfigYesNo, ConfigInteger, NoSave, ConfigSubsection, ConfigText
	from Components.ParentalControl import InitParentalControl
	InitParentalControl()
	from Navigation import Navigation

	# config
	config.misc.standbyCounter = NoSave(ConfigInteger(default=0)) # number of standby
	config.misc.RestartUI = ConfigYesNo(default=False) # detect user interface restart
	config.misc.prev_wakeup_time = ConfigInteger(default=0)
	#config.misc.prev_wakeup_time_type is only valid when wakeup_time is not 0
	config.misc.prev_wakeup_time_type = ConfigInteger(default=0)
	# 0 = RecordTimer, 1 = ZapTimer, 2 = Plugins, 3 = WakeupTimer

	# atv
	config.osd = ConfigSubsection()
	config.osd.language = ConfigText(default="US")
	config.crash = ConfigSubsection()
	config.crash.debugActionMaps = ConfigYesNo(default=False)
	config.crash.debugKeyboards = ConfigYesNo(default=False)
	config.crash.debugRemoteControls = ConfigYesNo(default=False)
	config.crash.debugScreens = ConfigYesNo(default=False)
	config.plugins = ConfigSubsection()

	try:
		from Components.StackTrace import StackTracePrinter
		StackTracePrinterInst = StackTracePrinter()
	except ImportError:
		StackTracePrinterInst = None

	from Components.UsageConfig import InitUsageConfig
	InitUsageConfig()
	if StackTracePrinterInst:
		StackTracePrinterInst.deactivate()

	try:
		# openATV
		from skin import loadSkinData
		loadSkinData(enigma.getDesktop(0))
	except ImportError:
		# openPLi
		from skin import InitSkins
		InitSkins()

	from Screens.Screen import Screen
	from Screens.Globals import Globals
	Screen.global_screen = Globals()
	_session = Session(enigma.getDesktop(0), enigma.getDesktop(1), Navigation())

	return _session
