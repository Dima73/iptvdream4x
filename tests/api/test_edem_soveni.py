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
from src.api.edem_soveni import OTTProvider


class Test(ott_provider.TestOTTProvider):
    ProviderClass = OTTProvider


if __name__ == "__main__":
    from unittest import main
    main()
