# -*- coding: utf-8 -*-
#
# Simple HTTP Live Streaming gateway.
# References: http://tools.ietf.org/html/draft-pantos-http-live-streaming-08
#
# Copyright (C) 2015  Alex Revetchi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import print_function
import socket
from six.moves import urllib_request, urllib_parse
from time import sleep
from datetime import datetime
from six.moves.BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from six.moves.socketserver import ThreadingMixIn
import logging
from logging.handlers import RotatingFileHandler
from sys import version_info

py3 = False
if version_info[0] >= 3:
	py3 = True

SUPPORTED_VERSION = 3
USER_AGENT = "hlsgw/0.1"
PORT_NUMBER = 7001


def getBestBitrate(variants, bitrate=0):
	"""return the (uri, dict) of the best matching playlist"""
	_, best = min((abs(int(x[1][0].split('=')[1]) - bitrate), x) for x in variants)
	return best[0]


def readM3U8Chunks(URL, duration=30, chunk_size=1024*4):
	req = urllib_request.Request(url=URL, headers={'User-Agent': USER_AGENT})
	conn = urllib_request.urlopen(url=req, timeout=60)
	while True:
		data = conn.read(chunk_size)
		if data:
			yield data
		else:
			return


def isM3U8Valid(conn):
	"""make sure file is an m3u, and returns the encoding to use."""
	base_url = conn.url.split('?')[0]
	mime = conn.headers.get('Content-Type', '').split(';')[0].lower()
	if mime == 'application/vnd.apple.mpegurl':
		enc = 'utf8'
	elif mime == 'audio/mpegurl':
		enc = 'iso-8859-1'
	elif base_url.endswith('.m3u8'):
		enc = 'utf8'
	elif base_url.endswith('.m3u'):
		enc = 'iso-8859-1'
	else:
		raise Exception("Stream MIME type or file extension not recognized")
	if py3:
		line = conn.readline().decode(enc).rstrip('\r\n')
	else:
		line = conn.readline().rstrip('\r\n')
	if line != '#EXTM3U':
		raise Exception("Stream is not in M3U format: %s" % line)
	return enc


def getM3U8Lines_iterator(url):
	req = urllib_request.Request(url=url, headers={'User-Agent': USER_AGENT})
	con = urllib_request.urlopen(url=req, timeout=10)
	enc = isM3U8Valid(con)
	if py3:
		lines = con.read().decode(enc)
		for l in lines.splitlines():
			if l.startswith('#EXT') or not l.startswith('#'):
				yield l.rstrip('\r\n')
	else:
		for l in con:
			if l.startswith('#EXT') or not l.startswith('#'):
				yield l.rstrip('\r\n').decode(enc)


def parseM3U8Tag(line):
	if ':' not in line:
		return line, []
	tag, attribstr = line.split(':', 1)
	attribs = []
	last = 0
	quote = False
	for i, c in enumerate(attribstr+','):
		if c == '"':
			quote = not quote
		if quote:
			continue
		if c == ',':
			attribs.append(attribstr[last:i])
			last = i+1
	return tag, attribs


def parseM3U8KeyValue(attribs, known_keys=None):
	d = {}
	for item in attribs:
		k, v = item.split('=', 1)
		k = k.strip()
		v = v.strip().strip('"')
		if known_keys is not None and k not in known_keys:
			raise ValueError("unknown attribute %s" % k)
		d[k] = v
	return d


def getM3U8MediaList(url):
	seq = 0
	duration = 5
	targetduration = 5
	for line in getM3U8Lines_iterator(url):
		if line.startswith('#EXT'):
			tag, attribs = parseM3U8Tag(line)
			if tag == '#EXTINF':
				duration = float(attribs[0])
			elif tag == '#EXT-X-TARGETDURATION':
				targetduration = int(attribs[0])
			elif tag == '#EXT-X-MEDIA-SEQUENCE':
				seq = int(attribs[0])
			elif tag == '#EXT-X-ENDLIST':
				assert not attribs
				yield None
				return
			elif tag == '#EXT-X-VERSION':
				assert len(attribs) == 1
				if int(attribs[0]) > SUPPORTED_VERSION:
					log.warn(
						"file version %s exceeds supported version %d; some things might be broken",
						attribs[0], SUPPORTED_VERSION)
			else:
				pass
		else:
			seq += 1
			yield (seq, duration, targetduration, line)


def serveHLS(url, write_cb, bitrate=0):
	variants = []
	variant = None
	for line in getM3U8Lines_iterator(url):
		if line.startswith('#EXT'):
			tag, attribs = parseM3U8Tag(line)
			if tag == '#EXT-X-STREAM-INF':
				variant = [v for v in attribs if v.startswith('BANDWIDTH')]
		elif variant:
			variants.append((line, variant))
			variant = None

	root_url = url

	last_seq = -1
	targetduration = 5
	media_bytes_total = 0
	buffering_needed = False

	while True:
		if bitrate:
			bitrate -= (bitrate // 10)
		if len(variants):
			url = urllib_parse.urljoin(root_url, getBestBitrate(variants, bitrate))

		media_start_time = datetime.now()
		media_bytes_total = 0
		if py3:
			data = b''
		else:
			data = ''
		for media in list(getM3U8MediaList(url)):
			if media is None:
				continue
			seq, duration, targetduration, media_url = media
			if seq > last_seq:
				for chunk in readM3U8Chunks(urllib_parse.urljoin(url, media_url), targetduration or duration):
					data += chunk
					media_bytes_total += len(chunk)
					if buffering_needed and len(data) < 15000000 // 8:
						continue
					write_cb(data)
					if py3:
						data = b''
					else:
						data = ''
					buffering_needed = False
				if data:
					write_cb(data)
					if py3:
						data = b''
					else:
						data = ''
				last_seq = seq
				changed = 1
		if len(variants):
			bitrate = int((media_bytes_total*8) // (datetime.now() - media_start_time).total_seconds())
		if changed == 1:
			# initial minimum reload delay
			delta = (datetime.now() - media_start_time).total_seconds()
			if delta < duration:
				sleep(duration - delta)
			else:
				buffering_needed = True
		elif changed == 0:
			# first attempt
			sleep(targetduration*0.5)
		elif changed == -1:
			# second attempt
			sleep(targetduration*1.5)
		else:
			# third attempt and beyond
			sleep(targetduration*3.0)
		changed -= 1


class HlsHandler(BaseHTTPRequestHandler):
	"""This class will handles any incoming request from the browser"""

	def do_GET(self):
		"""Handler for the GET requests"""
		try:
			url = urllib_parse.unquote(self.path)
			n = url.find('url=')
			if n == -1 or not len(url[n+4:]):
				self.send_response(404)
				self.end_headers()
				log.warn("No hls url found")
				return

			url = url[n+4:]
			self.send_response(200)
			self.send_header('Content-type', "video/mp2t")
			self.end_headers()

			log.debug("Serving HLS url %s", url)
			serveHLS(url, self.wfile.write)
			log.debug("Serving HLS ended")
		except Exception:  # pylint: disable=broad-except
			log.exception("Serving HLS ended with exception")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
	"""Handle requests in a separate thread."""


def serve():
	try:
		socket.setdefaulttimeout(30)
		server = HTTPServer(('127.0.0.1', PORT_NUMBER), HlsHandler)
		log.info('Started hls gateway on port %d', PORT_NUMBER)
		server.serve_forever(poll_interval=3)
	except KeyboardInterrupt:
		log.info('^C received, shutting down hls gateway')
		server.socket.close()


if __name__ == '__main__':
	log = logging.getLogger('hlsgw')
	log.setLevel(logging.DEBUG)
	log.addHandler(RotatingFileHandler('/tmp/hlsgw.log', maxBytes=10 * 1024))
	try:
		serve()
	except Exception:  # pylint: disable=broad-except
		log.exception("exception in main")
