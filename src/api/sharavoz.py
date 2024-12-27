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
from six.moves import urllib_parse
from six.moves.urllib_error import HTTPError
from re import compile
from time import mktime, time
from json import loads as json_loads

# plugin imports
from .abstract_api import JsonSettings
from .m3u import M3UProvider
from ..utils import APIException, APILoginFailed, Channel, ConfSelection
from ..utils import u2str, str2u, b2str, syncTime, APIException, APILoginFailed, EPG, Channel, Group
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
		s = self.getLocalSettings()
		self.site = s['site'].value
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
					cid = num
		else:
			cid = num
		return Channel(cid, name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def _getJson(self, url, params):
		try:
			self.trace(url)
			reply = self.readHttp(url + urllib_parse.urlencode(params))
		except IOError as e:
			raise APIException(e)
		try:
			json = json_loads(reply)
		except Exception as e:
			raise APIException(_("Failed to parse json: %s") % str(e))
		return json

	def getDayEpg(self, cid, date):
		if self.site == "http://technic.cf/epg-sharovoz":
			params = {"id": self.channels_data[cid]['tvg'], "day": date.strftime("%Y.%m.%d")}
			data = self.getJsonData(self.site + "/epg_day?", params)
			return [EPG(int(e['begin']), int(e['end']), u2str(e['title']), u2str(e['description'])) for e in data['data']]
		else:
			data = self._getJson(self.site + "/program?epg=%s&date=%s" % (self.channels_data[cid]['tvg'], date.strftime("%Y-%m-%d")), {})
			if data and "epg_data" in data:
				return [EPG(e['time'], e['time_to'], u2str(e['name']), u2str(e['descr'])) for e in data["epg_data"]]

	def getChannelsEpg(self, cids):
		if self.site == "http://technic.cf/epg-sharovoz":
			t = mktime(syncTime().timetuple())
			tvgs = set(self.channels_data[cid]['tvg'] or 0 for cid in cids)
			data = self.getJsonData(self.site + "/epg_list?", {"time": int(t), "ids": ",".join(map(str, tvgs)),})
			for c in data['data']:
				tvg = c['channel_id']
				try:
					cids = self.tvg_ids[tvg]
				except:
					continue
				for cid in cids:
					yield cid, [EPG(int(e['begin']), int(e['end']), u2str(e['title']), u2str(e['description'])) for e in c['programs']]
		else:
			tvgs = set(self.channels_data[cid]['tvg'] or 0 for cid in cids)
			date = syncTime().strftime("%Y-%m-%d")
			t = int(time())
			for tvg in tvgs:
				data = self._getJson(self.site + "/program?epg=%s&date=%s" % (tvg, date), {})
				if data and "epg_data" in data:
					yield tvg, [EPG(e['time'], e['time_to'], u2str(e['name']), u2str(e['descr'])) for e in data["epg_data"] if (e['time'] <= t and e['time_to'] >= t)]

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time is None:
			return url
		return url.replace('mpegts', 'timeshift_abs-%s.ts' % time.strftime('%s'))

	def getLocalSettings(self):
		settings = {
			"site": ConfSelection(_("EPG url"), "http://technic.cf/epg-sharovoz", [
				("http://technic.cf/epg-sharovoz", "technic.cf/epg-sharovoz"), ("http://api.program.spr24.net/api", "spr24.net/api"),
			]),}
		return self._safeLoadSettings(settings)
