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
from six.moves.urllib_error import URLError
from six.moves import urllib_parse
from hashlib import md5
from json import loads as json_loads

# plugin imports
from .abstract_api import JsonSettings, OfflineFavourites
from ..utils import APIException, APILoginFailed, Channel, Group, EPG, u2str

try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text

class OTTProvider(OfflineFavourites, JsonSettings):
	NAME = "TvTeam"
	AUTH_TYPE = "Login"

	def __init__(self, username, password):
		super(OTTProvider, self).__init__(username, password)
		self.site = "http://tvteam.eu/api/?"
		self.channels_data = {}
		self._tokens = []

	def start(self):
		self.authorize()

	def authorize(self):
		self.trace("Username", self.username)
		self.sid = None
		self._tokens = []
		response = self._getJson(self.site, {'userLogin': self.username, 'userPasswd': md5(self.password.encode('utf-8')).hexdigest(),}, reauth=False)
		self.sid = response['sessionId']
		self.trace("Session", self.sid)

	def _getJson(self, url, params, reauth=True):
		if self.sid is not None:
			params['sessionId'] = self.sid
		try:
			self.trace(url, params.get('apiAction', 'AUTH'))
			self.trace(url + urllib_parse.urlencode(params))
			reply = self.readHttp(url + urllib_parse.urlencode(params))
		except URLError as e:
			self.trace("URLError:", e)
			raise APIException(e)
		except IOError as e:
			self.trace("IOError:", e)
			raise APIException(e)
		try:
			json = json_loads(reply)
		except Exception as e:
			raise APIException(_("Failed to parse json: %s") % str(e))

		if json['status'] != 1:
			if reauth:
				self.authorize()
				return self._getJson(url, params, reauth=False)
			else:
				raise APIException(u2str(json['error']))
		return json['data']

	def setChannelsList(self):
		data = self._getJson(self.site, {'apiAction': 'getUserChannels', 'resultType': 'tree',})
		number = 0
		favorites = False
		try:
			for g in data['userChannelsTree']:
				gid = int(g['groupId'])
				channels = []
				if gid > 0 and not favorites:
					favorites = True
					number = 0
				for c in g['channelsList']:
					cid = int(c['channelId'])
					number += 1
					channel = Channel(cid, u2str(c['channelName']), number, int(c['archiveLen']) > 0, bool(int(c['isPorno'])))
					self.channels[cid] = channel
					self.channels_data[cid] = {'logo': u2str(c['channelLogo']), 'url': u2str(c['liveLink']),}
					channels.append(channel)
				self.groups[gid] = Group(gid, u2str(g['groupName']), channels)
		except Exception as e:
			self.trace("Failed to parse: %s" % str(e))

	def getStreamUrl(self, cid, pin, time=None):
		if self.channels[cid].is_protected:
			try:
				self._getJson(self.site, {'apiAction': 'pornoPinCodeValidation', 'pornoPinCode': pin})
			except APIException as e:
				raise APILoginFailed(str(e))

		if not self._tokens:
			data = self._getJson(self.site, {'apiAction': 'getRandomTokens', 'cnt': 30,})
			self._tokens = [u2str(t) for t in data['tokens']]
		token = self._tokens.pop()

		url = self.channels_data[cid]['url']
		if time is None:
			return url + "?token=%s" % token
		return url + "?token=%s&utc=%s" % (token, time.strftime('%s'))

	def getDayEpg(self, cid, date):
		data = self._getJson(self.site, {'apiAction': 'getTvProgram', 'channelId': cid,})
		try:
			return [EPG(int(e['prStartSec']), int(e['prStopSec']), u2str(e['prTitle']), u2str(e['prSubTitle'])) for e in data['tvProgram']]
		except Exception as e:
			self.trace("Failed to parse: %s" % str(e))
			return []

	def getChannelsEpg(self, cids):
		data = self._getJson(self.site, {'apiAction': 'getCurrentPrograms'})
		try:
			for cid, ps in data['currentPrograms'].items():
				yield (int(cid), [EPG(int(e['prStartSec']), int(e['prStopSec']), u2str(e['prTitle'])) for e in ps])
		except Exception as e:
			self.trace("Failed to parse: %s" % str(e))

	def getPiconUrl(self, cid):
		picon_url = self.channels_data[cid]['logo']
		if picon_url:
			return picon_url.replace('tv.team', 'tvteam.eu')
		return picon_url
