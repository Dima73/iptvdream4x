# -*- coding: utf-8 -*-
#  enigma2 iptv player
#
#  Copyright (c) 2018 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from __future__ import print_function

# system imports
import re
from six.moves.urllib_error import HTTPError
from json import loads as json_loads

# plugin imports
from .m3u import M3UProvider
from .abstract_api import JsonSettings
from ..utils import Channel, APIException, APILoginFailed, ConfInteger, str2u
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class OTTProvider(JsonSettings, M3UProvider):
	NAME = "ShuraTV"
	AUTH_TYPE = "Key"
	TVG_MAP = True

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://technic.cf/epg-1ott/"
		server = self.getLocalSettings()['server'].value
		self.playlist_url = "http://pl.tvshka.net/?uid=%s&srv=%s&type=halva" % (username, server)
		self._url_regexp = re.compile(r"https?://[\w.]+/~\w+/(\d+)/hls/.*\.m3u8")
		self.name_map = {}

	def start(self):
		try:
			self.name_map = json_loads(self.readHttp(self.site + "/channels_names"))['data']
		except IOError as e:
			self.trace("error!", e)
			raise APIException(e)

		self._downloadTvgMap()
		try:
			self._parsePlaylist(self.readHttp(self.playlist_url).split(b'\n'))
		except HTTPError as e:
			self.trace("HTTPError:", e, type(e), e.getcode())
			if e.code in (403, 404):
				raise APILoginFailed(e)
			else:
				raise APIException(e)
		except IOError as e:
			self.trace("IOError:", e, type(e))
			raise APIException(e)

	def setChannelsList(self):
		# Channels are downloaded during start, to allow handling login exceptions
		pass

	def makeChannel(self, num, name, url, tvg, logo, rec):
		if tvg is None:
			try:
				tvg = self.name_map[str2u(name)]
			except KeyError:
				pass
		m = self._url_regexp.match(url)
		if m:
			cid = int(m.group(1))
		else:
			cid = hash(url)
			self.trace("Failed to get cid from url", url)
		return Channel(cid, name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def getLocalSettings(self):
		settings = {
			'server': ConfInteger(_("Server"), 1, (0, 10000)),
		}
		return self._safeLoadSettings(settings)
