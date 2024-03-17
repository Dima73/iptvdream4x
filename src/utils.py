# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2010 Alex Maystrenko <alexeytech@gmail.com>
#  Copyright (c) 2013 Alex Revetchi <alex.revetchi@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

try:
	from typing import List
except ImportError:
	pass

from sys import version_info
from functools import wraps
from datetime import datetime, timedelta
import time


def trace(*args):
	print("[IPtvDream]", *args)


if version_info.major <= 2:
	def u2str(s):
		# type: (unicode) -> str
		"""Convert unicode to str for display in enigma2 ui"""
		return s.encode('utf-8')

	def str2u(s):
		# type: (str) -> unicode
		"""Convert str to unicode"""
		return s.decode('utf-8')

	def b2str(s):
		# type: (str) -> str
		"""Python2 str is bytes"""
		return s
else:
	def u2str(s):
		# type: (str) -> str
		"""Python3 str is unicode"""
		return s

	def str2u(s):
		# type: (str) -> str
		"""Python3 str is unicode"""
		return s

	def b2str(s):
		# type: (bytes) -> str
		"""Convert bytes to string"""
		return s.decode('utf-8')


def timeit(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		t = time.time()
		result = f(*args, **kwargs)
		d = time.time() - t
		trace("timeit %s %.6f" % (f, d))
		return result
	return wrapper


def getHwAddr(ifname):
	from six import b
	try:
		import fcntl
		import socket
		import struct
	except ImportError:
		return '00:00:00:00:00:00'
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		info = fcntl.ioctl(s.fileno(), 0x8927, struct.pack('256s', b(ifname[:15])))
	except IOError:
		return '00:00:00:00:00:00'
	if version_info.major > 2:
		ordb = lambda x: x
	else:
		ordb = ord
	return ''.join(['%02x:' % ordb(char) for char in info[18:24]])[:-1]


global Timezone
Timezone = -time.timezone // 3600
trace("timezone is GMT", Timezone)


def tdSec(td):
	return int((td.days * 86400) + td.seconds)


def tdmSec(td):
	# Add +1. Timer should wait for next event until event happened exactly.
	# Otherwise inaccuracy in round may lead to mistake.
	return int(tdSec(td) * 1000) + 1


def secTd(sec):
	return timedelta(sec // 86400, sec % 86400)


def tupleTd(tup):
	return secTd(tup[0]*60*60 + tup[1]*60)


trace("resetting time delta !!!")
time_delta = secTd(0)


def setSyncTime(t):
	global time_delta
	time_delta = t - datetime.now()
	trace("set time delta to", tdSec(time_delta))


def syncTime():
	return datetime.now() + time_delta


def toTimestamp(t):
	return int(time.mktime(t.timetuple()))


def toDate(t):
	return t.year, t.month, t.day


class EPG(object):
	__slots__ = ('begin', 'end', 'end_timestamp', 'name', 'description')

	def __init__(self, begin, end, name, description=""):
		"""
		:param int begin: Program start time in unix timestamp
		:param int end: Program end time in unix timestamp
		:param str name: Program title, single line
		:param str description: detailed description, can be multi lined
		"""
		self.begin = datetime.fromtimestamp(begin)
		self.end = datetime.fromtimestamp(end)
		self.end_timestamp = int(end)
		self.name = name
		self.description = description

	def duration(self):
		return tdSec(self.end - self.begin)

	def timePass(self, t):
		return tdSec(t - self.begin)

	def timeLeft(self, t):
		return tdSec(self.end - t)

	def timeLeftMilliseconds(self, t):
		return tdmSec(self.end - t)

	def percent(self, t, size):
		try:
			return size * self.timePass(t) // self.duration()
		except ZeroDivisionError:
			return size

	def progress(self, t):
		try:
			return float(self.timePass(t)) / float(self.duration())
		except ZeroDivisionError:
			return 1.0

	def isAt(self, t):
		return self.begin <= t < self.end

	def __repr__(self):
		return "%s-%s|%s" % (self.begin.strftime("%H:%M"), self.end.strftime("%H:%M"), self.name)


class ConfEntry(object):
	def __init__(self, title):
		"""
		Base class for api configuration
		:type title: str
		"""
		self.title = title
		self.value = None

	def safeSetValue(self, value):
		"""Validate and set the value"""
		raise NotImplementedError()

	def to_json(self):
		"""
		Serialize configuration entry to json
		Used to display in web settings
		"""
		raise NotImplementedError()


class ConfInteger(ConfEntry):
	def __init__(self, title, value, limits):
		"""
		:type value: int
		:type limits: Tuple[int, int]
		"""
		super(ConfInteger, self).__init__(title)
		self.value = value
		self.limits = limits

	def safeSetValue(self, value):
		try:
			value = int(value)
		except ValueError:
			return
		if self.limits[0] <= value <= self.limits[1]:
			self.value = value

	def to_json(self):
		return {
			"type": "integer",
			"title": self.title,
			"value": self.value,
			"min": self.limits[0],
			"max": self.limits[1]
		}


class ConfString(ConfEntry):
	def __init__(self, title, value):
		"""
		:type value: str
		"""
		super(ConfString, self).__init__(title)
		self.value = value

	def safeSetValue(self, value):
		self.value = str(value)

	def to_json(self):
		return {
			"type": "string",
			"title": self.title,
			"value": self.value,
		}


class ConfSelection(ConfEntry):
	def __init__(self, title, value, choices):
		"""
		choices should be list of (value, description) tuples
		:type value: str
		:type choices: List[Tuple[str, str]]
		"""
		super(ConfSelection, self).__init__(title)
		self.value = value
		self.choices = choices

	def safeSetValue(self, value):
		if value in [c[0] for c in self.choices]:
			self.value = value

	def to_json(self):
		return {
			"type": "selection",
			"title": self.title,
			"value": self.value,
			"options": list({"value": c[0], "title": c[1]} for c in self.choices),
		}


class ConfBool(ConfEntry):
	def __init__(self, title, value):
		"""
		:type value: bool
		"""
		super(ConfBool, self).__init__(title)
		self.value = value

	def safeSetValue(self, value):
		self.value = bool(value)

	def to_json(self):
		return {
			"type": "bool",
			"title": self.title,
			"value": self.value,
		}


class EPGDB(object):
	def __init__(self):
		self.l = []
		self.days_start = {}
		self.last = 0

	# bisect copies from python library

	def bisect(self, x, lo=0, hi=None):
		if lo < 0:
			raise ValueError('lo must be non-negative')
		if hi is None:
			hi = len(self.l)
		while lo < hi:
			mid = (lo+hi)//2
			if x < self.l[mid][0]:
				hi = mid
			else:
				lo = mid+1
		return lo

	def bisect_left(self, x, lo=0, hi=None):
		if lo < 0:
			raise ValueError('lo must be non-negative')
		if hi is None:
			hi = len(self.l)
		while lo < hi:
			mid = (lo+hi)//2
			if self.l[mid][0] < x:
				lo = mid+1
			else:
				hi = mid
		return lo

	def findEpg(self, time):
		if time is None:
			time = syncTime()
			update = True
			e = self.atTime(time, self.last, update)
			if e is not None:
				return e
			e = self.atTime(time, self.last+1, update)
			if e is not None:
				return e
		else:
			update = False
		t = toTimestamp(time)
		i = self.bisect(t)
		return self.atTime(time, i, update)

	def atTime(self, time, i, update):
		if i == 0 or i-1 >= len(self.l):
			return None
		epg = self.l[i-1][1]
		if epg.begin <= time < epg.end:
			if update:
				self.last = i
			return i-1
		else:
			return None

	def checkHint(self, i, t):
		return i > 0 and (i == len(self.l) or t < self.l[i][0]) and (i == 0 or self.l[i-1][0] <= t)

	### Public methods

	def epgCurrent(self, time=None):
		i = self.findEpg(time)
		if i is not None:
			return self.l[i][1]
		else:
			return None

	def epgNext(self, time=None):
		i = self.findEpg(time)
		if (i is not None) and (i+1 < len(self.l)):
			epg = self.l[i][1]
			epgn = self.l[i+1][1]
			if epg.end == epgn.begin:
				return epgn
			else:
				return None
		else:
			return None

	def epgDay(self, date):
		# for apis that can't get correct range in getDayEpg
		try:
			t1 = self.days_start[toDate(date)]
		except KeyError:
			return []
		t2 = t1 + timedelta(1)
		i1 = self.bisect_left(toTimestamp(t1))
		i2 = self.bisect_left(toTimestamp(t2), lo=i1)
		return [x[1] for x in self.l[i1:i2]]  # FIXME: extra copy

	def addEpg(self, epg, hint=-1):
		t = toTimestamp(epg.begin)
		if self.checkHint(hint, t):
			i = hint
		else:
			i = self.bisect(t)
		if i > 0:
			prev = self.l[i-1][1]
			if prev.begin == epg.begin or prev.end > epg.begin:
				trace("EPG conflict!")
				self.l[i-1] = (t, epg)
				return i
		self.l.insert(i, (t, epg))
		if self.last >= i:
			self.last += 1
		return i+1

	def addEpgSorted(self, epg_list):
		hint = 0
		for e in epg_list:
			hint = self.addEpg(e, hint)

	def addEpgDay(self, date, epglist):
		self.days_start[toDate(date)] = date
		self.addEpgSorted(epglist)


class Group(object):
	__slots__ = ('gid', 'title', 'channels')

	def __init__(self, gid, title, channels):
		# type: (int, str, List[Channel]) -> None
		"""
		:param int gid: group id
		:param str title: title to display
		:param list[Channel] channels: list of channels
		"""
		self.gid = gid
		self.title = title
		self.channels = channels

	def __str__(self):
		return "Group(%d: %s)" % (self.gid, self.title)

	def __repr__(self):
		return self.__str__()

	def assertTypes(self):
		assert type(self.gid) == int
		assert type(self.title) == str
		assert type(self.channels) == list
		assert all(isinstance(c, Channel) for c in self.channels)


class Channel(EPGDB):
	def __init__(self, cid, name, number, has_archive=False, is_protected=False):
		# type: (int, str, int, bool, bool) -> None
		"""
		:param int cid: channel id
		:param str name: channel title
		:param int number: channel number
		:param bool has_archive:
		:param bool is_protected:
		"""
		EPGDB.__init__(self)
		self.cid = cid
		self.name = name
		self.number = number
		self.has_archive = has_archive
		self.is_protected = is_protected
		self.lastUpdateFailed = None
		self.alt_number = 0

	def __str__(self):
		return "Channel(%s: %s)" % (self.cid, self.name)

	def __repr__(self):
		return self.__str__()


class APIException(Exception):
	def __init__(self, msg):
		Exception.__init__(self, msg)


class APILoginFailed(APIException):
	def __init__(self, msg):
		APIException.__init__(self, msg)


class APIWrongPin(APIException):
	def __init__(self, msg):
		APIException.__init__(self, msg)
