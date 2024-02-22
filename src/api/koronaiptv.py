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
from six.moves.urllib_error import HTTPError

# plugin imports
from .m3u import M3UProvider
from .abstract_api import JsonSettings
from ..utils import APIException, APILoginFailed, Channel, Group, ConfSelection, b2str, str2u
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class Korona(JsonSettings, M3UProvider):
	AUTH_TYPE = "Login"
	TVG_MAP = True

	def __init__(self, username, password):
		super(Korona, self).__init__(username, password)
		self.site = "http://technic.cf/epg-korona/"
		self.playlist = ""
		s = self.getLocalSettings()
		self.playlist_url = "http://pl.korona-tv.top/%s/%s/%s/%s/tv.m3u" % (
			s['server'].value, s['quality'].value, username, password)

	def setChannelsList(self):
		# Channels are downloaded during start, to allow handling login exceptions
		pass

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

	def _parsePlaylist(self, lines):
		# Copy of M3U class with some modifications
		self.tvg_ids = {}
		group_names = {}
		num = 0

		name = ""
		group = "Unknown"
		logo = ""
		archive = False
		tvg = None
		cid = None

		import re
		tvg_regexp = re.compile('#EXTINF:.*tvg-id="([^"]*)"')
		group_regexp = re.compile('#EXTINF:.*group-title="([^"]*)"')
		logo_regexp = re.compile('#EXTINF:.*tvg-logo="([^"]*)"')
		archive_regexp = re.compile('#EXTINF:.*catchup-days="([^"]*)"')
		cid_regexp = re.compile('#EXTINF:.*CUID="([^"]*)"')

		for line in lines:
			line = b2str(line)
			if line.startswith("#EXTINF:"):
				name = line.strip().split(',')[1]
				m = tvg_regexp.match(line)
				if m:
					if self.tvg_map:
						k = str2u(m.group(1))
						try:
							tvg = self.tvg_map[k]
						except KeyError:
							tvg = None
							self.trace("unknown tvg-id", k)
					else:
						tvg = int(m.group(1))
				else:
					tvg = None
				m = group_regexp.match(line)
				if m:
					group = m.group(1)
				else:
					group = "Unknown"
				m = logo_regexp.match(line)
				if m:
					logo = m.group(1)
				else:
					logo = ""
				m = archive_regexp.match(line)
				if m:
					archive = True
				else:
					archive = False
				m = cid_regexp.match(line)
				if m:
					cid = int(m.group(1))
				else:
					cid = None
			elif line.startswith("#EXTGRP:"):
				group = line.strip().split(':')[1]
			elif line.startswith("#"):
				continue
			elif not line.strip():
				continue
			else:
				url = line.strip()
				assert url.find("://") > 0, "line: " + url
				try:
					gid = group_names[group]
					g = self.groups[gid]
				except KeyError:
					gid = len(group_names)
					group_names[group] = gid
					g = self.groups[gid] = Group(gid, group.decode('utf-8').capitalize().encode('utf-8'), [])

				num += 1
				if cid is None:
					cid = hash(url)
				c = Channel(cid, name, num, archive)
				self.channels[cid] = c
				g.channels.append(c)

				self.channels_data[cid] = {'tvg': tvg, 'url': url, 'logo': logo}
				if tvg is not None:
					try:
						self.tvg_ids[tvg].append(cid)
					except KeyError:
						self.tvg_ids[tvg] = [cid]

		self.trace("Loaded {} channels".format(len(self.channels)))

	def getLocalSettings(self):
		settings = {
			'server': ConfSelection(
				_("Server"), '1',
				[('1', "Server 1"), ('2', "Server 2"), ('3', "Server 3")]
			),
			'quality': ConfSelection(
				_("Quality"), 'hi',
				[('hi', _("High")), ('lo', _("Low"))]
			),
		}
		return self._safeLoadSettings(settings)


class OTTProvider(Korona):
	NAME = "KoronaTV"
