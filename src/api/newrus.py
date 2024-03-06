# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2013 Alex Revetchi <revetski@gmail.com>
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from datetime import datetime

from .abstract_api import AbstractAPI, AbstractStream, MODE_STREAM
from ..utils import Group, Channel, EPG, APIWrongPin, u2str


class NewrusAPI(AbstractAPI):
	PROVIDER = ""
	NUMBER_PASS = True
	site = "http://iptv.new-rus.tv:8501/api/json"

	def __init__(self, username, password):
		AbstractAPI.__init__(self, username, password)
		self.sid_name = None

	def start(self):
		self.authorize()

	def authorize(self):
		self.trace("Username is", self.username)

		params = {"login": self.username, "pass": self.password, "settings": "all"}
		response = self.getJsonData(self.site + "/login.php?", params, fromauth=True)

		self.sid = response['sid']
		self.sid_name = response['sid_name']
		self.parseSettings(response['settings'])
		self.parseAccount(response['account'])

	def parseAccount(self, account):
		self.packet_expire = datetime.strptime(account['packet_expire'].split()[0], "%Y-%m-%d")

	def parseSettings(self, settings):
		# TODO: implement me
		pass

	def getJsonData(self, url, params, name='', fromauth=False):
		if not fromauth:
			params.update({self.sid_name: self.sid})
		return super(NewrusAPI, self).getJsonData(url, params, fromauth=fromauth)


class OTTProvider(AbstractStream, NewrusAPI):
	NAME = "NewrusTV"
	MODE = MODE_STREAM
	HAS_PIN = True

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)

	def setChannelsList(self):
		data = self.getJsonData(self.site + "/channel_list.php?", {})
		num = 0
		for g in data['groups']:
			gid = int(g['id'])
			channels = []
			for c in g['channels']:
				num += 1
				cid = int(c['id'])
				channel = Channel(
					cid, u2str(c['name']), num,
					bool(c['have_archive']), bool(c['protected']))
				self.channels[cid] = channel
				channels.append(channel)
			self.groups[gid] = Group(gid, u2str(g['name']), channels)

	def getStreamUrl(self, cid, pin, time=None):
		params = {"cid": cid}
		if pin:
			params["protect_code"] = pin
		if time:
			params["gmt"] = time.strftime("%s")
		data = self.getJsonData(self.site + "/get_url.php?", params)
		url = u2str(data["url"])
		if url == "protected":
			raise APIWrongPin("Access denied")
		return url

	@staticmethod
	def parseProgram(txt):
		ret = txt.split('\n', 1)
		if len(ret) == 1:
			ret.append("")
		return ret

	def getChannelsEpg(self, cids):
		data = self.getJsonData(self.site + "/channel_list.php?", {})
		for g in data["groups"]:
			for c in g["channels"]:
				cid = int(c["id"])
				name, description = self.parseProgram(u2str(c['epg_progname']))
				if name:
					yield cid, [EPG(int(c['epg_start']), int(c['epg_end']), name, description)]

	def getDayEpg(self, cid, date):
		params = {"cid": cid, "day": date.strftime("%d%m%y")}
		data = self.getJsonData(self.site + "/epg.php?", params)
		for program in data['epg']:
			name, description = self.parseProgram(u2str(program['progname']))
			yield EPG(program['ut_start'], program['ut_end'], name, description)

	def getSettings(self):
		return self.settings

	def pushSettings(self, settings):
		# FIXME: implement me
		for s in settings:
			params = {"var": s[0], "val": s[1]}
		self.getData(self.site + "/settings_set.php?", params)
