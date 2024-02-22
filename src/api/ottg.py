# -*- coding: utf-8 -*-
#  enigma2 iptv player
#
#  Copyright (c) 2019 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from __future__ import print_function

# system imports
from six.moves.urllib_parse import urlencode
import re

# plugin imports
from .abstract_api import JsonSettings
from .m3u import M3UProvider
from ..utils import APILoginFailed, Channel, ConfSelection
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class OTTProvider(JsonSettings, M3UProvider):
	NAME = "glanzTV"
	AUTH_TYPE = "Login"

	TVG_MAP = True

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://technic.cf/epg-iptvxone/"
		s = self.getLocalSettings()
		self._format = s['format'].value
		self.playlist_url = "http://pl.ottg.tv/get.php?" + urlencode({
			'username': self.username, 'password': self.password,
			'type': 'm3u', 'output': self._format, 'censored': s['censored'].value,
		})
		self._url_regexp = re.compile(r"ch_id=(\d+)")

	def start(self):
		pass

	def makeChannel(self, num, name, url, tvg, logo, rec):
		m = self._url_regexp.search(url)
		if m:
			cid = int(m.group(1))
		else:
			cid = hash(url)
			self.trace("Failed to get cid from url", url)
		return Channel(cid, name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def getLocalSettings(self):
		return self._safeLoadSettings({
			'format': ConfSelection(_("Stream format"), 'ts', [('ts', "MPEG-TS"), ('hls', "HLS")]),
			'censored': ConfSelection(_("Playlist"), '0', [('0', "Lite"), ('1', "Full")]),
		})

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time is None:
			return url
		if self._format == "hls":
			return url.replace('video.m3u8', 'video-timeshift_abs-%s.m3u8' % time.strftime('%s'))
		else:
			return url.replace('mpegts', 'timeshift_abs/%s' % time.strftime('%s'))
