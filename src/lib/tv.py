# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

""" Helper classes and functions for iptv streaming """

from __future__ import print_function

from collections import deque
from os import mkdir, listdir, path as os_path
from twisted.internet.defer import Deferred, succeed, CancelledError

from Components.AVSwitch import AVSwitch
from Components.config import config, ConfigSelection
from enigma import eBackgroundFileEraser, ePicLoad

from ..loc import translate as _
from ..layer import enigma2Qt
from ..api.abstract_api import AbstractStream
from ..utils import trace
from ..common import fatalError, downloadPage, DownloadException


class SortOrderSettings(object):
	def __init__(self):
		self.choices = {
			AbstractStream.Sort_N: ('number', _('by number')),
			AbstractStream.Sort_AZ: ('name', _('by name')),
		}
		self.c = config.plugins.IPtvDream.channel_order = ConfigSelection(list(self.choices.values()))

	def toStr(self, value):
		return self.choices[value][0]

	def fromStr(self, s):
		return dict((v[0], k) for k, v in self.choices.items())[s]

	def getValue(self):
		return self.fromStr(self.c.value)

	def setValue(self, value):
		if isinstance(value, int):
			value = self.toStr(value)
		self.c.value = value
		self.c.save()


PICON_PATH = '/tmp/IPtvDream/'


class PiconCache(object):
	CACHE_SIZE = 50

	def __init__(self):
		self.picons = {}
		self.defers = {}
		self.requests = deque()
		self.trace("init")
		try:
			if not os_path.exists(PICON_PATH):
				mkdir(PICON_PATH)
			else:
				for f in listdir(PICON_PATH):
					self._onLoad(None, f, loaded=False)
		except IOError as e:
			self.trace(e)

	def get(self, url):
		f = url.split('/')[-1]
		try:
			p = self.picons[f]
			self.trace("return", url)
			return succeed(p)
		except KeyError:
			return self.load(url, f)

	def load(self, url, f):
		self.trace("load", url)
		try:
			d, consumers = self.defers[f]
			consumers.append(Deferred())
		except KeyError:
			d = downloadPage(url, PICON_PATH + f)
			d.addCallback(self._onLoad, f).addErrback(self._onError, f)
			consumers = [Deferred()]
			self.defers[f] = (d, consumers)
		return consumers[-1]

	def _onLoad(self, result, f, loaded=True):
		pixmap = PICON_PATH + f
		self.picons[f] = pixmap
		self.requests.append(f)
		if loaded:
			d, consumers = self.defers.pop(f)
			for consumer in consumers:
				consumer.callback(pixmap)
			del d
		if len(self.requests) >= self.CACHE_SIZE:
			self.trace("wipe cache", self.requests)
			for _i in range(self.CACHE_SIZE // 2):
				fname = self.requests.popleft()
				del self.picons[fname]
				eBackgroundFileEraser.getInstance().erase(PICON_PATH + fname)

	def _onError(self, err, f):
		self.trace(err)
		_, consumers = self.defers.pop(f)
		for consumer in consumers:
			consumer.errback(err)

	@staticmethod
	def trace(*args):
		print("[IPtvDream] PiconCache", ' '.join(map(str, args)))


cache = PiconCache()


class Picon(object):
	def __init__(self, pixmap):
		self.pixmap = pixmap
		self.d = None
		self.picload = ePicLoad()
		if enigma2Qt:
			self._connection = self.picload.PictureData.connect(self._paint)
		else:
			self.picload.PictureData.get().append(self._paint)

	def setIcon(self, url):
		self.pixmap.instance.setPixmap(None)
		if self.d:
			self.d.cancel()
		if not url:
			return
		self.d = cache.get(url)
		self.d.addCallback(self._onReady).addErrback(self._onFail).addErrback(fatalError)

	def _onReady(self, file_name):
		sc = AVSwitch().getFramebufferScale()
		trace(sc)
		self.picload.setPara((
			self.pixmap.instance.size().width(),
			self.pixmap.instance.size().height(),
			sc[0], sc[1], False, 1, "#00000000"))
		self.picload.startDecode(file_name)

	def _paint(self, picInfo=None):
		trace(picInfo)
		ptr = self.picload.getData()
		if ptr is not None:
			self.pixmap.instance.setPixmap(ptr.__deref__())

	def _onFail(self, err):
		e = err.trap(DownloadException, CancelledError)
		if e == CancelledError:
			trace("download cancelled")
		else:
			trace(e)
