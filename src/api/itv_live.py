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
from six.moves import urllib_parse
import zlib
from json import loads as json_loads, dumps as json_dumps

# plugin imports
from .abstract_api import OfflineFavourites
from ..utils import syncTime, APIException, APILoginFailed, EPG, Channel, Group, u2str

try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text

class OTTProvider(OfflineFavourites):
	NAME = "ITVLive"
	AUTH_TYPE = "Key"

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://api.itv.live"
		self.channels_data = {}

	def start(self):
		self.channels = {}
		self.groups = {}
		self.channels_data = {}

		data = self._getJson(self.site + '/data/%s' % self.username, {})
		for number, ch in enumerate(data['channels']):
			group = u2str(ch['cat_name'])
			gid = int(ch['cat_id'])
			try:
				g = self.groups[gid]
			except KeyError:
				g = self.groups[gid] = Group(gid, group, [])

			cid = int(ch['ch_id'][2:])
			c = Channel(cid, u2str(ch['channel_name']), number, bool(int(ch['rec'])), False)
			self.channels[cid] = c
			self.channels_data[cid] = {
				'url': u2str(ch['ch_url']),
				'logo': u2str(ch['logo_url']),
				'id': ch['ch_id_epg'],
			}
			g.channels.append(c)

	def _getJson(self, url, params):
		self.trace(url)
		try:
			reply = self.readHttp(url + urllib_parse.urlencode(params))
		except IOError as e:
			raise APIException(e)
		try:
			json = json_loads(reply)
		except Exception as e:
			raise APIException(_("Failed to parse json: %s") % str(e))
		# self.trace(json)
		return json

	def getStreamUrl(self, cid, pin, time=None):
		url = self.channels_data[cid]['url']
		if time is None:
			return url
		return url.replace('video.m3u8', 'video-timeshift_abs-%s.m3u8' % time.strftime('%s'))

	def getChannelsEpg(self, cids):
		req = '/epg/{"chid": [%s]}/1' % ",".join(
			'"%d:%s"' % (cid, self.channels_data[cid]['id']) for cid in cids)
		data = self._getJson(self.site + urllib_parse.quote(req, safe='/:",'), {})

		for e in data['res']:
			yield int(e['id']), [EPG(
				int(e['startTime']), int(e['stopTime']), u2str(e['title']), u2str(e['desc'])
			)]

	def getDayEpg(self, cid, date):
		data = self._getJson(self.site + '/epg/%s/%s' % (self.channels_data[cid]['id'], date.strftime('%Y-%m-%d')), {})
		return [EPG(int(e['startTime']), int(e['stopTime']), u2str(e['title'])) for e in data['res']]

	def getPiconUrl(self, cid):
		return self.channels_data[cid]['logo']
