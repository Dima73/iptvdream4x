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
	NAME = "SchurikTV"
	AUTH_TYPE = "Key"
	TVG_MAP = True

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://json.srv4you.net/epg-server"
		self.playlist_url = [
			"http://srv4you.net/pl/m3u/%s/pl.m3u" % username,
			"http://pl.is-a-player.com/ott/m3u/%s/playlist.m3u" % username
		]

	def start(self):
		self._downloadTvgMap()
		for idx, url in enumerate(self.playlist_url):
			try:
				self._parsePlaylist(self.readHttp(url).split(b'\n'))
				break
			except HTTPError as e:
				self.trace("HTTPError:", e, type(e), e.getcode())
				if e.code in (403, 404):
					if idx == len(self.playlist_url) - 1:
						raise APILoginFailed(e)
					continue
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
			cid = int(m.group(1))
		else:
			cid = hash(url)
			# self.trace("Failed to get cid from url", url)
		return Channel(cid, name, num, True), {'tvg': tvg, 'url': url, 'logo': logo}

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time is None:
			return url
		return url.replace('mpegts', 'timeshift_abs/%s' % time.strftime('%s'))
