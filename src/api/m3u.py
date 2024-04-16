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
import os
import re
from time import mktime
from json import loads as json_loads

# plugin imports
from .abstract_api import OfflineFavourites
from ..utils import u2str, str2u, b2str, syncTime, APIException, EPG, Channel, Group
from ..loc import translate as _

class M3UProvider(OfflineFavourites):
	NAME = "M3U"
	AUTH_TYPE = ""

	TVG_MAP = False  # True if tvg-id are non-numerical and we need to get map from server

	def __init__(self, username, password):
		super(M3UProvider, self).__init__(username, password)
		# Override site and playlist in derived class
		self.site = ""
		self.playlist = "default.m3u"
		self.playlist_url = ""
		self.channels = {}
		self.groups = {}
		# map from channel ids in playlist to epg server ids
		self.channels_data = {}
		# map from xmltv keys to epg server ids
		self.tvg_map = {}
		# map from epg server ids to channel ids
		self.tvg_ids = {}
		self._domain = ''
		self._key = ''
		# regexp to extract channel id
		self._url_regexp = re.compile(r"https?://[\w.]+/iptv/\w+/(\d+)/index.m3u8")

	def _locatePlaylist(self):
		"""Returns path to the playlist file"""
		try:
			from Tools.Directories import resolveFilename, SCOPE_SYSETC
			path = resolveFilename(SCOPE_SYSETC, 'iptvdream')
		except ImportError:
			path = 'playlists'

		m3u8 = os.path.join(path, self.playlist)
		if not os.path.exists(m3u8):
			raise APIException(_("%s playlist not found! Please copy your playlist to %s.") % (self.NAME, m3u8))
		return m3u8

	def _extractKeyFromPlaylist(self, url_regexp):
		"""
		Extracts domain and key information from m3u playlist
		:param url_regexp: pattern obtained by re.compile() containing domain and key groups
		"""
		m3u8 = self._locatePlaylist()
		with open(m3u8) as f:
			for line in f:
				line = line.strip()
				m = url_regexp.match(line)
				if m:
					self._domain = m.group(1)
					self._key = m.group(2)
					self.trace("found domain and key in user playlist")
					break
		if not (self._domain and self._key):
			raise APIException(_("Failed to parse %s playlist located at %s.") % (self.NAME, m3u8))

	def start(self):
		url_regexp = re.compile(r"https?://([\w.]+)/iptv/(\w+)/\d+/index.m3u8")
		self._extractKeyFromPlaylist(url_regexp)

	def setChannelsList(self):
		self._downloadTvgMap()
		try:
			self._parsePlaylist(self.readHttp(self.playlist_url).split(b'\n'))
		except IOError as e:
			self.trace("error!", e, type(e))
			#raise APIException(e)

	def _downloadTvgMap(self):
		self.tvg_map = {}
		if self.TVG_MAP:
			try:
				self.tvg_map = json_loads(self.readHttp(self.site + "/channels"))['data']
			except IOError as e:
				self.trace("error!", e)
				self.tvg_map = {}
				#if not "technic.cf" in self.site:
				#	raise APIException(e)
				#else:
				#	self.tvg_map = {}

	def makeChannel(self, num, name, url, tvg, logo, rec):
		"""
		Return tuple (Channel instance, internal data) based on parameters extracted from playlist
		"""
		m = self._url_regexp.match(url)
		if m:
			cid = int(m.group(1))
		else:
			cid = hash(url)
			self.trace("Failed to get cid from url", url)
		url = url.replace("localhost", self._domain).replace("00000000000000", self._key)
		return Channel(cid, name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def _parsePlaylist(self, lines):
		group_names = {}
		num = 0

		name = ""
		group = "Unknown"
		logo = ""
		tvg = None
		rec = False

		tvg_regexp = re.compile('#EXTINF:.*tvg-id="([^"]*)"')
		group_regexp = re.compile('#EXTINF:.*group-title="([^"]*)"')
		logo_regexp = re.compile('#EXTINF:.*tvg-logo="([^"]*)"')
		rec_regexp = re.compile('#EXTINF:.*tvg-rec="([^"]*)"')
		catchup_regexp = re.compile('#EXTINF:.*catchup-days="([^"]*)"')
		timeshift_regexp = re.compile('#EXTINF:.*timeshift="([^"]*)"')

		import codecs
		if lines:
			if lines[0].startswith(codecs.BOM_UTF8):
				self.trace("Discard BOM_UTF8")
				lines[0] = lines[0][3:]

		for line in lines:
			line = b2str(line)
			if line.startswith("#EXTINF:"):
				name = line.split(',')[1].strip()
				m = tvg_regexp.match(line)
				if m:
					if self.tvg_map:
						k = str2u(m.group(1))
						try:
							tvg = self.tvg_map[k]
						except KeyError:
							tvg = None
							# self.trace("unknown tvg-id", k)
					else:
						try:
							tvg = int(m.group(1))
						except:
							tvg = None
				else:
					tvg = None
				m = group_regexp.match(line)
				if m:
					group = m.group(1)
				m = logo_regexp.match(line)
				if m:
					logo = m.group(1)
				else:
					logo = ""
				m = rec_regexp.match(line)
				if m:
					rec = m.group(1) != "0"
				else:
					m = catchup_regexp.match(line)
					if m:
						rec = m.group(1) != "0"
					else:
						m = timeshift_regexp.match(line)
						if m:
							try:
								rec = m.group(1) != "0"
							except:
								rec = False
						else:
							rec = False
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
					g = self.groups[gid] = Group(gid, group, [])

				num += 1
				c, d = self.makeChannel(num, name, url, tvg, logo, rec)
				cid = c.cid
				self.channels[cid] = c
				g.channels.append(c)
				self.channels_data[cid] = d

				# reset
				group = "Unknown"

		# Create inverse mapping from tvg to cid, required for epg_list
		self.tvg_ids = {}
		for cid, data in self.channels_data.items():
			tvg = data['tvg']
			if tvg is not None:
				try:
					self.tvg_ids[tvg].append(cid)
				except KeyError:
					self.tvg_ids[tvg] = [cid]

		self.trace("Loaded {} channels".format(len(self.channels)))

	def _markProtected(self, group_regexp):
		for g in self.groups.values():
			if group_regexp.search(g.title) is not None:
				for c in g.channels:
					c.is_protected = True

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time:
			url += '?utc=%s&lutc=%s' % (time.strftime('%s'), syncTime().strftime('%s'))
		return url

	def getDayEpg(self, cid, date):
		params = {"id": self.channels_data[cid]['tvg'], "day": date.strftime("%Y.%m.%d")}
		data = self.getJsonData(self.site + "/epg_day?", params)
		return [EPG(
			int(e['begin']), int(e['end']),
			u2str(e['title']), u2str(e['description'])) for e in data['data']]

	def getChannelsEpg(self, cids):
		t = mktime(syncTime().timetuple())
		tvgs = set(self.channels_data[cid]['tvg'] or 0 for cid in cids)
		data = self.getJsonData(self.site + "/epg_list?", {
			"time": int(t),
			"ids": ",".join(map(str, tvgs)),
		})

		for c in data['data']:
			tvg = c['channel_id']
			try:
				cids = self.tvg_ids[tvg]
			except KeyError:
				# self.trace("Unknown teleguide id", tvg)
				continue
			for cid in cids:
				yield cid, [EPG(
					int(e['begin']), int(e['end']), u2str(e['title']),
					u2str(e['description'])) for e in c['programs']]

	def getPiconUrl(self, cid):
		return self.channels_data[cid]['logo']
