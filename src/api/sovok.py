# -*- coding: utf-8 -*-
#  enigma2 iptv player
#
#  Copyright (c) 2010 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from __future__ import print_function

from datetime import datetime

from .abstract_api import OfflineFavourites
from ..utils import Channel, Group, APIWrongPin, EPG, u2str


class OTTProvider(OfflineFavourites):
	NAME = "SovokTV"
	site = "http://api.sovok.tv/v2.3/json"
	icons_url = "http://sovok.tv"

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.icons = {}

	def authorize(self):
		self.trace("Authorization of username = %s" % self.username)
		params = {"login": self.username, "pass": self.password}
		reply = self.getJsonData(self.site + '/login?', params, fromauth=True)

		self.parseAccount(reply['account'])
		self.trace("Packet expire: %s" % self.packet_expire)
		self.sid = True

	def parseAccount(self, account):
		for s in account['services']:
			expire = datetime.fromtimestamp(int(s['expire']))
			if self.packet_expire is None:
				self.packet_expire = expire
			else:
				self.packet_expire = min(expire, self.packet_expire)

	def setChannelsList(self):
		data = self.getJsonData(self.site + "/channel_list?", {})
		number = 0
		for g in data['groups']:
			gid = int(g['id'])
			channels = []
			for c in g['channels']:
				cid = int(c['id'])
				number += 1
				channel = Channel(
					cid, u2str(c['name']), number,
					bool(int(c['have_archive'])), bool(int(c['protected']))
				)
				self.channels[cid] = channel
				self.icons[cid] = u2str(c['icon'])
				channels.append(channel)
			self.groups[gid] = Group(gid, u2str(g['name']), channels)

	def getStreamUrl(self, cid, pin, time=None):
		params = {"cid": cid}
		if time:
			params["gmt"] = time.strftime("%s")
		if pin:
			params["protect_code"] = pin
		data = self.getJsonData(self.site + "/get_url?", params)
		url = u2str(data['url']).split(' ')[0].replace('http/ts://', 'http://')
		if url == "protected":
			raise APIWrongPin("")
		return url

	def getChannelsEpg(self, cids):
		data = self.getJsonData(self.site + "/epg_next2?", {"cids": ",".join(map(str, cids))})
		for e in data['epg']:
			yield int(e['chid']), [EPG(
				int(e['start']), int(e['end']),
				u2str(e['progname']), u2str(e['description']))]

	def getDayEpg(self, cid, date):
		data = self.getJsonData(self.site + "/epg?", {'cid': cid, 'day': date.strftime("%d%m%y")})
		for e in data['epg']:
			yield EPG(
				int(e['ut_start']), int(e['ut_end']),
				u2str(e['progname']), u2str(e['description']))

	def getPiconUrl(self, cid):
		url = self.icons[cid]
		if url:
			return self.icons_url + url
		return ""
