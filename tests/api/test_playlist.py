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

from . import ott_provider
from src.api.playlist import getOTTProviders

OTTProvider = next(getOTTProviders())


class Test(ott_provider.TestOTTProvider):
	ProviderClass = OTTProvider

	def bench_m3u_parser(self):
		prov = OTTProvider("", "")
		prov._downloadTvgMap()

		def parse():
			m3u = prov._locatePlaylist()
			with open(m3u, 'rb') as f:
				prov._parsePlaylist(f.readlines())

		import timeit
		from math import sqrt
		K = 3
		N = 30
		t = timeit.repeat(parse, number=N, repeat=K)
		ta = sum(t) / K
		mse = sqrt(sum((t1 - ta)**2 for t1 in t) / K)
		print("TIME %f ± %f per loop" % (max(t) / N, mse / N))


if __name__ == "__main__":
	from unittest import main
	main()
