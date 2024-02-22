from __future__ import print_function

# import this first to install e2reactor
from .e2init import getSession

from twisted.trial import unittest
from twisted.internet import task, reactor

from ..mock_api import MockApi as OTTProvider


class TestChannelsScreen(unittest.TestCase):
	def setUp(self):
		getSession()
		import src.manager

	def test_sort_mode(self):
		from src.main import IPtvDreamChannels

		session = getSession()

		db = OTTProvider("", "")
		db.start()
		db.setChannelsList()

		dlg = session.open(
			IPtvDreamChannels,
			db,
			None
		)  # type: IPtvDreamChannels
		dlg.showAll()
		dlg.sortByName()
		dlg.sortByNumber()

	def test_favourites_ordering(self):
		from src.main import IPtvDreamChannels

		session = getSession()

		db = OTTProvider("", "")
		db.start()
		db.setChannelsList()

		dlg = session.open(
			IPtvDreamChannels,
			db,
			None
		)  # type: IPtvDreamChannels

		dlg.showAll()
		dlg.addRemoveFavourites()
		dlg.moveDown()
		dlg.addRemoveFavourites()
		dlg.moveDown()
		dlg.addRemoveFavourites()
		dlg.showFavourites()
		assert len(dlg.list.list) == 3

		favs = db.selectFavourites()
		print("Before:", favs)
		assert len(favs) == 3

		dlg.startEditing()
		dlg.toggleMarkForMoving()
		dlg.moveUp()
		dlg.finishEditing()

		new_favs = db.selectFavourites()
		print("After:", favs)
		print("After:", new_favs)
		assert favs[0] == new_favs[0]
		assert favs[1] == new_favs[2]
		assert favs[2] == new_favs[1]


class TestEpgScreen(unittest.TestCase):
	def setUp(self):
		getSession()
		import src.manager

	def test_info_screen(self):
		from datetime import datetime, timedelta
		from src.main import IPtvDreamEpgInfo
		from src.utils import Channel, EPG, toTimestamp

		session = getSession()

		t = datetime.now()
		dlg = session.open(
			IPtvDreamEpgInfo,
			Channel(1, "Channel Name", 10, True, False),
			EPG(
				toTimestamp(t), toTimestamp(t + timedelta(minutes=40)),
				"Program name",
				"Program description. " * 5
			)
		)
		print("openned screen", dlg)
		return task.deferLater(reactor, 1, dlg.close)

	def test_arrow_navigation(self):
		from src.main import IPtvDreamEpg

		session = getSession()

		db = OTTProvider("", "")
		db.start()
		db.setChannelsList()

		dlg = session.open(
			IPtvDreamEpg,
			db, db.selectAll()[0].cid, 0
		)

		dlg.up()
		dlg.down()
		dlg.pageUp()
		dlg.pageDown()
		dlg.nextDay()
		dlg.prevDay()
		return task.deferLater(reactor, 1, dlg.close)


if __name__ == "__main__":
	from unittest import main
	main()
