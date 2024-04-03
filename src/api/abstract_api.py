# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2010 Alex Maystrenko <alexeytech@gmail.com>
#  Copyright (c) 2013 Alex Revetchi   <alex.revetchi@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from __future__ import print_function

import socket
import zlib
from six.moves import http_cookiejar, urllib_request, urllib_parse
from json import loads as json_loads
from os import path as os_path
from datetime import datetime
try:
	from typing import Dict  # pylint: disable=unused-import
except ImportError:
	pass

from ..utils import getHwAddr, Group, Channel, APIException, APILoginFailed, EPG, u2str
from ..dist import VERSION

MODE_STREAM = 0
MODE_VIDEOS = 1


def renameDict(d, keys):
	for new, old in keys:
		d[new] = d.pop(old)


class AbstractAPI(object):
	MODE = MODE_STREAM
	PROVIDER = "free"
	NAME = "example"
	TITLE = None
	NEXT_API = None
	NUMBER_PASS = False
	HAS_PIN = False
	USE_SEEK = True
	AUTH_TYPE = "Login"

	def __init__(self, username, password):
		# type: (str, str) -> None
		self.username = username
		self.password = password
		self.sid = None
		self.packet_expire = None
		self.settings = {}

		socket.setdefaulttimeout(10)
		self.uuid = getHwAddr('eth0')
		self.cookiejar = http_cookiejar.CookieJar()
		self.urlopener = urllib_request.build_opener(urllib_request.HTTPCookieProcessor(self.cookiejar))
		self.urlopener.addheaders = [
					('User-Agent', 'IPtvDream/%s %s' % (VERSION, self.NAME)),
					#('User-Agent', 'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'),
					('Connection', 'Keep-Alive'),
					('Accept', 'application/json, text/javascript, */*'),
					('Accept-Encoding', 'gzip, deflate')]

	def start(self):
		"""Functions that runs on start, and needs exception handling"""
		pass

	def getToken(self, code):
		"""Authorization method for AUTH_TYPE = 'Token'"""
		pass

	def authorize(self):
		"""Perform authorization, used when session expired"""
		pass

	def getSettings(self):
		"""
		Return setting that can be access after start
		:rtype: Dict[str, utils.ConfEntry]
		"""
		return {}

	def pushSettings(self, settings):
		"""
		Push settings to server for key to value dict
		:type settings: typing.Dict[str, str]
		"""
		pass

	def getLocalSettings(self):
		"""
		Return settings that are stored locally and don't require authorization
		:rtype: Dict[str, utils.ConfEntry]
		"""
		return {}

	def saveLocalSettings(self, settings):
		"""Save local settings"""
		pass

	def readHttp(self, request):
		o = self.urlopener.open(request)
		enc = o.headers.get('Content-Encoding')
		if enc and 'gzip' in enc:
			reply = zlib.decompress(o.read(), 16+zlib.MAX_WBITS)
			return reply
		else:
			return o.read()

	def getData(self, url, params, name='', fromauth=None):
		if not self.sid and not fromauth:
			self.cookiejar.clear()
			self.authorize()
		elif fromauth:
			self.cookiejar.clear()

		try:
			request = url + urllib_parse.urlencode(params)
			self.trace("Getting %s (%s)" % (name, request))
			reply = self.readHttp(request)
		except IOError as e:
			self.sid = None
			raise APIException(e)
		return reply

	def getJsonData(self, url, params, name='', fromauth=None):
		reauthOnError = True
		if not self.sid and not fromauth:
			reauthOnError = False
			self.cookiejar.clear()
			self.authorize()
		elif fromauth:
			self.cookiejar.clear()

		try:
			request = url + urllib_parse.urlencode(params)
			self.trace("Getting %s" % name, url, request)
			reply = self.readHttp(request)
		except IOError as e:
			self.sid = None
			raise APIException(e)
		try:
			json = json_loads(reply)
		except Exception as e:
			self.sid = None
			raise APIException("Failed to parse json response: %s" % str(e))
		if 'error' in json:
			self.sid = None
			self.cookiejar.clear()
			if reauthOnError and not fromauth:
				return self.getJsonData(url, params, name)
			error = json['error']
			if str(error['code']) in ['ACC_WRONG', 'AСС_EMPTY']:
				raise APILoginFailed(str(error['code']) + ": " + u2str(error['message']))
			else:
				raise APIException(str(error['code']) + ": " + u2str(error['message']))
		self.trace("getJsonData ok")
		return json

	def _resolveConfigurationFile(self, file_name):
		try:
			from Tools.Directories import resolveFilename, SCOPE_SYSETC
			return resolveFilename(SCOPE_SYSETC, 'iptvdream/%s' % file_name)
		except ImportError:
			self.trace("error: cant locate configuration files")
			return "/tmp/%s" % file_name

	def trace(self, *args):
		"""Use for API debug"""
		print("[IPtvDream] %s: %s" % (self.NAME, " ".join(map(str, args))))


class AbstractStream(AbstractAPI):
	SERVICE = 1
	URL_DYNAMIC = True
	Sort_N = 0
	Sort_AZ = 1
	SORT = ('number', 'name')

	def __init__(self, username, password):
		super(AbstractStream, self).__init__(username, password)
		self.channels = {}  # type: Dict[int, Channel]
		self.groups = {}  # type: Dict[int, Group]
		self.favourites = []
		self.got_favourites = False

	def setChannelsList(self):
		pass

	def isFavCid(self, cid):
		return self.favourites.count(cid)

	def addFav(self, cid):
		if not self.favourites.count(cid):
			self.favourites.append(cid)
			self.uploadFavourites(self.favourites)

	def rmFav(self, cid):
		if cid in self.favourites:
			self.favourites.remove(cid)
			self.uploadFavourites(self.favourites)

	def setFavourites(self, favourites):
		self.favourites = favourites
		self.uploadFavourites(self.favourites)

	def loadDayEpg(self, cid, date):
		date = datetime(date.year, date.month, date.day)
		self.channels[cid].addEpgDay(date, list(self.getDayEpg(cid, date)))

	def getPiconName(self, cid):
		"""You can return reference to cid or to channel name, anything you want ;)"""
		return "%s:%s:" % (self.NAME, cid)

	# Return lists for GUI

	def selectGroups(self):
		return list(self.groups.values())

	def selectAll(self, sort_key=Sort_N):
		attr = self.SORT[sort_key]
		return sorted(list(self.channels.values()), key=lambda c: getattr(c, attr))

	def selectChannels(self, gid, sort_key=Sort_N):
		attr = self.SORT[sort_key]
		return sorted(self.groups[gid].channels, key=lambda c: getattr(c, attr))

	def selectFavourites(self):
		if not self.got_favourites:
			keys = set(self.channels.keys())
			favourites = self.getFavourites()
			self.favourites = [cid for cid in favourites if cid in keys]
			self.got_favourites = True
		return [self.channels[cid] for cid in self.favourites]

	def findNumber(self, number):
		from six import iteritems
		for cid, ch in iteritems(self.channels):
			if ch.number == number:
				return cid
		return None

	# To be implemented in a derived class

	def setTimeShift(self, time_shift):
		return

	def getStreamUrl(self, cid, pin, time=None):
		"""
		:param int cid: channel id
		:param str|None pin: if channel is protected then is not None
		:param datetime|None time: If specified then get stream from archive
		:rtype: str
		"""
		return ""

	def getChannelsEpg(self, cids):
		"""
		:param list[int] cids: list of channel ids
		:rtype: list[(int, list[EPG])]
		"""
		return []

	def getDayEpg(self, cid, date):
		"""
		:param int cid: channel id
		:param datetime date: day
		:rtype: list[EPG]
		"""
		return []

	def getFavourites(self):
		"""
		:rtype: list[int]
		"""
		return []

	def uploadFavourites(self, current):
		"""
		:param list[int] current: list of current favourites
		"""
		pass

	def getPiconUrl(self, cid):
		""" Return url to channel icon """
		return ""


class OfflineFavourites(AbstractStream):
	def __init__(self, username, password):
		super(OfflineFavourites, self).__init__(username, password)
		self._favorites_file = self._resolveConfigurationFile('%s.txt' % self.NAME)

	def getFavourites(self):
		if not os_path.isfile(self._favorites_file):
			return []
		with open(self._favorites_file) as f:
			data = f.read().strip()
			if not data:
				return []
			return [int(c) for c in data.split(',')]

	def uploadFavourites(self, current):
		try:
			with open(self._favorites_file, 'w') as f:
				f.write(','.join(map(str, current)))
		except Exception as e:
			raise APIException(str(e))


class JsonSettings(AbstractAPI):
	def __init__(self, username, password):
		super(JsonSettings, self).__init__(username, password)
		self._settings_file = self._resolveConfigurationFile('%s.json' % self.NAME)

	def _loadSettings(self):
		"""Read json from settings file without verification"""
		from json import load as json_load
		if not os_path.isfile(self._settings_file):
			return {}
		with open(self._settings_file) as f:
			return json_load(f) or {}

	def _safeLoadSettings(self, defaults):
		"""Update defaults with verified values loaded from json"""
		for k, v in self._loadSettings().items():
			try:
				defaults[k].safeSetValue(str(v))
			except KeyError:
				continue
		return defaults

	def _saveSettings(self, settings):
		"""Dump settings dictionary to file"""
		from json import dump as json_dump
		try:
			with open(self._settings_file, 'w') as f:
				json_dump(settings, f)
		except Exception as e:
			raise APIException(str(e))

	def saveLocalSettings(self, settings):
		data = self._loadSettings()
		data.update(settings)
		self._saveSettings(data)
