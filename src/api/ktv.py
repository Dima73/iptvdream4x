# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
# Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.

from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import md5

from .abstract_api import AbstractAPI, OfflineFavourites
from ..utils import toDate, EPG, Channel, Group, APIWrongPin
try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class KartinaAPI(AbstractAPI):
	PROVIDER = ""
	NUMBER_PASS = True

	site = ""

	def __init__(self, username, password):
		super(KartinaAPI, self).__init__(username, password)
		self.softid = "dev-test-000"
		self.uuid = md5(self.uuid.encode('utf-8')).hexdigest()

	def start(self):
		self.authorize()
		self.getJsonData(self.site + "/settings_set?", {'var': 'stream_standard', 'val': 'http_h264'})
		self.getSettings()

	def authorize(self):
		self.trace("Authorization of username = %s" % self.username)
		params = {
			"login": self.username, "pass": self.password,
			"softid": self.softid, "cli_serial": self.uuid,
		}
		reply = self.getJsonData(self.site + '/login?', params, fromauth=True)
		self.parseAccount(reply['account'])
		self.trace("Packet expire: %s" % self.packet_expire)
		self.sid = True

	def parseAccount(self, account):
		self.packet_expire = datetime.fromtimestamp(int(account['packet_expire']))

	def parseSettings(self, data):
		from ..utils import ConfSelection
		d = data['bitrate']
		self.settings['bitrate'] = ConfSelection(
			title=_("Bitrate"), value=str(d['value']), choices=[
				(str(n['val']), n['title'].encode('utf-8')) for n in d['names']
			])
		d = data['stream_server']
		self.settings['stream_server'] = ConfSelection(
			title=_("Stream server"), value=str(d['value']), choices=[
				(str(s['ip']), s['descr'].encode('utf-8')) for s in d['list']
			])
		d = data['stream_standard']
		self.settings['stream_standard'] = ConfSelection(
			title=_("Stream format"), value=str(d['value']), choices=[
				(str(s['value']), s['title'].encode('utf-8')) for s in d['list']
			])


class KtvStream(OfflineFavourites, KartinaAPI):
	HAS_PIN = True
	icons_url = ""

	def __init__(self, username, password):
		super(KtvStream, self).__init__(username, password)
		self.day_ends = defaultdict(dict)
		self.icons = {}

	@staticmethod
	def parseName(txt):
		ret = txt.split('\n', 1)
		if len(ret) == 1:
			ret.append("")
		return ret

	def setTimeShift(self, time_shift):
		self.getJsonData(self.site, {"var": "timeshift", "val": time_shift})

	def setChannelsList(self):
		data = self.getJsonData(self.site + "/channel_list?", {})
		# number = 0
		for g in data['groups']:
			gid = int(g['id'])
			channels = []
			for c in g['channels']:
				cid = int(c['id'])
				channel = Channel(
					cid, c['name'].encode('utf-8'), cid,
					bool(int(c.get('have_archive', 0))), bool(int(c.get('protected', 0)))
				)
				self.channels[cid] = channel
				self.icons[cid] = c['icon'].encode('utf-8')
				channels.append(channel)
			self.groups[gid] = Group(gid, g['name'].encode('utf-8'), channels)

	def getStreamUrl(self, cid, pin, time=None):
		params = {"cid": cid}
		if time:
			params["gmt"] = time.strftime("%s")
		if pin:
			params["protect_code"] = pin
		data = self.getJsonData(self.site + "/get_url?", params)
		url = data['url'].encode('utf-8').split(' ')[0].replace('http/ts://', 'http://')
		if url == "protected":
			raise APIWrongPin("")
		return url

	def getChannelsEpg(self, cids):
		params = {"cids": ",".join(map(str, cids)), "epg": 3}
		data = self.getJsonData(self.site + "/epg_current?", params, "getting epg of cids = %s" % cids)
		for channel in data['epg']:
			cid = int(channel['cid'])
			programs = []
			e = None
			for p in channel['epg']:
				t = int(p['ts'])
				name, desc = self.parseName(p['progname'].encode('utf-8'))
				if e is not None:
					t_start, name, desc = e  # pylint: disable=unpacking-non-sequence
					programs.append(EPG(t_start, t, name, desc))
				e = (t, name, desc)
			yield cid, programs

	def getDayEpg(self, cid, date):
		date = datetime(date.year, date.month, date.day)
		try:
			t_end = self.day_ends[cid][toDate(date)]
		except KeyError:
			programs = list(self._getDayEpg(cid, date + timedelta(1)))
			try:
				t_end, _, _ = programs[0]
				self.day_ends[cid][toDate(date)] = t_end
			except IndexError:
				t_end = None

		programs = list(self._getDayEpg(cid, date))
		try:
			t_start, _, _ = programs[0]
			self.day_ends[cid][date - timedelta(1)] = t_start
		except IndexError:
			pass

		for (i, p) in enumerate(programs[1:]):
			t, name, desc = programs[i]  # p is programs[i+1]
			e = EPG(t, p[0], name, desc)
			yield e
		if t_end is not None and len(programs) > 0:
			t, name, desc = programs[-1]
			yield EPG(t, t_end, name, desc)

	def _getDayEpg(self, cid, date):
		params = {"day": date.strftime("%d%m%y"), "cid": cid}
		data = self.getJsonData(self.site + "/epg?", params, "day EPG %s for channel %s" % (params['day'], cid))
		for program in data['epg']:
			t = int(program['ut_start'])
			name, desc = self.parseName(program['progname'].encode("utf-8"))
			yield (t, name, desc)

	def getPiconUrl(self, cid):
		url = self.icons[cid]
		if url:
			return self.icons_url + url
		return ""

	def getSettings(self):
		if not self.settings:
			data = self.getJsonData(self.site + "/settings?", {"var": "all"})
			self.parseSettings(data['settings'])
		return self.settings

	def pushSettings(self, settings):
		for k, v in settings.items():
			self.getJsonData(self.site + "/settings_set?", {"var": k, "val": v})
