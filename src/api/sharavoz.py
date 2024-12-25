# -*- coding: utf-8 -*-
#  enigma2 iptv player
#
#  Copyright (c) 2020 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from __future__ import print_function

# system imports
from six.moves.urllib_error import HTTPError
from re import compile

# plugin imports
from .abstract_api import JsonSettings
from .m3u import M3UProvider
from ..utils import APIException, APILoginFailed, Channel
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class OTTProvider(JsonSettings, M3UProvider):
	NAME = "SharavozTV"
	AUTH_TYPE = "OTT ID"
	TVG_MAP = True

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://technic.cf/epg-sharovoz"
		self.playlist_url = "http://www.spr24.net/iptv/p/%s/Playlist.Kodi.m3u" % username
		self._url_regexp = compile(r"https?://[\w.]+/(\d+)/mpegts")

	def start(self):
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
		m = self._url_regexp.match(url)
		if m:
			try:
				cid = int(m.group(1))
			except:
				if tvg:
					try:
						cid = int(tvg)
					except:
						cid = hash(url)
				else:
					num
		else:
			cid = num
		return Channel(cid, name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time is None:
			return url
		return url.replace('mpegts', 'timeshift_abs-%s.ts' % time.strftime('%s'))
