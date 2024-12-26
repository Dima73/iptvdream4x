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
from six.moves.urllib_error import HTTPError
from six.moves import urllib_parse
from json import loads as json_loads

# plugin imports
from .abstract_api import JsonSettings
from .m3u import M3UProvider
from ..utils import APIException, APILoginFailed, Channel, u2str

try:
	from ..loc import translate as _
except ImportError:
	def _(text):
		return text


class IpStreamOne(JsonSettings, M3UProvider):
	NAME = "IpStreamOne"
	AUTH_TYPE = "Token"
	TVG_MAP = True

	token_page = "https://ipstream.one"

	def __init__(self, username, password):
		super(IpStreamOne, self).__init__(username, password)
		self._token = password

		self.site = "http://technic.cf/epg-ipstream/"
		self.token_api = "http://ipstream.one/api/iptvdream-apiH4s.php?"
		self.playlist_url = "http://www.ipstream.one/iptv/m3u_plus-%s"

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

	def getToken(self, code):
		data = self._getJson(self.token_api, {'k': code})
		if data['status'] == '1':
			self._token = "%s-%s" % (u2str(data['user']), u2str(data['password']))
			return self._token
		else:
			self._token = None
			raise APILoginFailed(_("Invalid key"))

	def start(self):
		self._downloadTvgMap()
		try:
			self._parsePlaylist(self.readHttp(self.playlist_url % self._token).split(b'\n'))
		except HTTPError as e:
			self.trace("HTTPError:", e, type(e), e.getcode())
			if e.code in (403, 404):
				raise APILoginFailed(e)
			else:
				raise APIException(e)
		except IOError as e:
			self.trace("IOError:", e, type(e))
			raise APIException(e)

	def makeChannel(self, num, name, url, tvg, logo, rec):
		return Channel(hash(url), name, num, rec), {'tvg': tvg, 'url': url, 'logo': logo}

	def setChannelsList(self):
		# Channels are downloaded during start, to allow handling login exceptions
		pass


class SharaClub(IpStreamOne):
	NAME = "SharaClub"

	token_page = "https://shara.club"

	def __init__(self, username, password):
		super(SharaClub, self).__init__(username, password)
		self.token_api = "http://list.playtv.pro/api/iptvdream-apiFd7.php?"
		self.playlist_url = "http://list.playtv.pro/tv-m3u8/%s"


def getOTTProviders():
	return (IpStreamOne, SharaClub)
