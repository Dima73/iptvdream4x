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
from json import loads as json_loads

# plugin imports
from .m3u import M3UProvider
from .abstract_api import JsonSettings
from ..utils import APIException, Channel, ConfSelection, ConfString, str2u, syncTime
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class Playlist(JsonSettings, M3UProvider):
	NAME = "M3U-Playlist"
	PLAY_LIST = "playlist.m3u"
	TVG_MAP = True

	def __init__(self, username, password):
		super(Playlist, self).__init__(username, password)
		s = self.getLocalSettings()
		self.site = s['epg_url'].value
		self._m3u_from = s['from'].value
		self.playlist_url = s['playlist_url'].value
		self._archive_url = s['archive_url'].value
		self.archive_tag = s['archive'].value
		self.playlist_name = s['playlist_name'].value
		self.playlist = self.PLAY_LIST
		self.name_map = {}

	def start(self):
		try:
			self.name_map = json_loads(self.readHttp(self.site + "/channels_names"))['data']
		except (IOError, ValueError) as e:
			self.trace("error!", e)
			self.name_map = {}
			#if not "technic.cf" in self.site:
			#	raise APIException(e)
			#else:
			#	self.name_map = {}

	def setChannelsList(self):
		self._downloadTvgMap()
		try:
			if self._m3u_from == 'file':
				m3u = self._locatePlaylist()
				with open(m3u, 'rb') as f:
					self._parsePlaylist(f.readlines())
			elif self._m3u_from == 'url':
				try:
					lines = self.readHttp(self.playlist_url).split(b'\n')
				except (IOError, ValueError) as e:
					self.trace("error!", e, type(e))
					raise APIException(e)
				self._parsePlaylist(lines)
			else:
				raise Exception(_("Bad paramenter %s") % self._m3u_from)
		except IOError as e:
			self.trace("error!", e, type(e))
			raise APIException(e)

	def makeChannel(self, num, name, url, tvg, logo, rec):
		if tvg is None:
			try:
				tvg = self.name_map[str2u(name)]
			except KeyError:
				pass
		if self.archive_tag == 'tagged':
			archive = name.endswith('(A)') or rec
		else:
			archive = True
		cid = self._m3u_from == 'file' and hash(url) or num
		return Channel(cid, name, num, archive), {'tvg': tvg, 'url': url, 'logo': logo}

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if self._archive_url == 'default':
			if time:
				url += '?utc=%s&lutc=%s' % (time.strftime('%s'), syncTime().strftime('%s'))
			return url
		elif self._archive_url == 'flusonic':
			if time is None:
				return url
			return url.replace('video.m3u8', 'video-timeshift_abs-%s.m3u8' % time.strftime('%s'))
		else:
			raise Exception("Unknown archive_url")

	def getLocalSettings(self):
		settings = {
			'from': ConfSelection(_("Get playlist"), 'file', [
				('file', _("from playlist.m3u file")), ('url', _("from url")),
			]),
			'playlist_url': ConfString(_("Playlist url"), ""),
			'archive': ConfSelection(_("Enable archive"), 'all', [
				('all', _("All channels")), ('tagged', _("Marked channels (A)"))
			]),
			'archive_url': ConfSelection(_("Archive url type"), 'default', [
				('default', _("Default")), ('flusonic', "Flusonic"),
			]),
			'epg_url': ConfString(_("EPG-json url"), "http://technic.cf/epg-soveni"),
			'playlist_name': ConfString(_("Playlist name (only EN language)"), ""),
		}
		return self._safeLoadSettings(settings)


def getOTTProviders():
	yield Playlist
	for i in range(1, 10):
		class Provider(Playlist):
			NAME = "M3U-Playlist-%d" % i
			PLAY_LIST = "playlist_%d.m3u" % i
		yield Provider
