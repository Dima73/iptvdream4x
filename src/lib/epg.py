# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

# enigma2 imports
from Components.Sources.Source import Source

# system imports
try:
	# noinspection PyUnresolvedReferences
	from typing import Callable, Optional, List  # pylint: disable=unused-import
except ImportError:
	pass

# plugin imports
from ..utils import syncTime, EPG, secTd
from ..layer import eTimer


class EpgProgress(Source):
	def __init__(self):
		super(EpgProgress, self).__init__()
		self._epg = None
		self._shift = 0
		self._timer = eTimer()
		self._timer.callback.append(self.updateProgress)
		self.onChanged = []  # type: List[Callable[[float],None]]

	def setEpg(self, epg, shift=0):
		# type: (Optional[EPG]) -> None
		self._epg = epg
		self._shift = shift
		if self._epg is not None and self._epg.duration() > 0:
			self._timer.start(1000)
			self.updateProgress()
		else:
			self._timer.stop()

	def getProgress(self):
		# type: () -> float
		if self._shift:
			return self._epg.progress(syncTime() + secTd(self._shift))
		return self._epg.progress(syncTime())

	def updateProgress(self):
		for f in self.onChanged:
			f(self.getProgress())

	def doSuspend(self, suspend):
		if suspend:
			self._timer.stop()
		else:
			self._timer.start(1000)
			self.updateProgress()

	def destroy(self):
		self._timer.callback.remove(self.updateProgress)
		super(EpgProgress, self).destroy()
