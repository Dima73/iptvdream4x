#!/usr/bin/env python

"""Test that plugin auto update is working"""

from __future__ import print_function

import subprocess
import os
import json
import re
from datetime import datetime
import time
import shutil
from sys import version_info

VERSION_FILE = 'src/dist.py'
PKG_TMP = "/tmp/packages"
PKG_DEPLOY = "/var/www/html/iptvdream4x/packages"
SERVER_HOSTNAME = "technic.cf"


def modifyVersion(func):
	newVer = None
	with open(VERSION_FILE, 'r') as f:
		lines = f.readlines()
		r = re.compile(r'^\s*VERSION\s*=\s*"(.*)"$')
		for i, line in enumerate(lines):
			m = r.match(line)
			if m:
				ver = m.group(1)
				print("Found version", ver)
				ver = list(map(int, ver.split('.')))
				newVer = func(ver)
				lines[i] = 'VERSION = "%s"' % '.'.join(map(str, newVer))
				print("Set to", lines[i])

	with open(VERSION_FILE, 'w') as f:
		f.writelines(lines)
	return newVer


def enableHostAlias(server, ip=None):
	assert len(server) and (ip is None or len(ip))
	lines = []
	with open("/etc/hosts", 'r') as f:
		for line in f:
			if re.search(r'\s+%s\s+' % server, line) is None:
				lines.append(line)

	if ip is not None:
		lines.append("%s %s\n" % (ip, server))

	with open("hosts.tmp", 'w') as f:
		f.writelines(lines)
	shutil.move("hosts.tmp", "/etc/hosts")
	print("Set alias for %s = %s" % (server, ip))


def test():
	print("Starting update-test scenario, resetting", VERSION_FILE)
	subprocess.check_call(['git', 'checkout', '--', VERSION_FILE])

	def bumpRc(ver):
		return ver[:2] + [90]
	newVer = modifyVersion(bumpRc)

	print("Starting make\n" + "-" * 15)
	buildStartTime = datetime.now()
	subprocess.check_call(['make', 'package', 'PACKAGEDIR=%s' % PKG_TMP, 'PYTHON=python%d' % version_info.major])
	print("-" * 15)

	with open('info.json') as f:
		data = json.load(f)
		packageName = data['name']

	newVerStr = '.'.join(map(str, newVer))
	package = os.path.join(PKG_TMP, '%s_%s_all.ipk' % (packageName, newVerStr))
	assert os.path.isfile(package)
	assert os.path.getctime(package) >= time.mktime(buildStartTime.timetuple())

	print("Installing package")
	subprocess.check_call(['opkg', 'install', package])

	print("Bump version minor")

	def bumpMinor(ver):
		return ver[0], ver[1] + 1
	testVer = modifyVersion(bumpMinor)
	testVerStr = '.'.join(map(str, testVer))

	print("Starting make\n" + "-" * 15)
	subprocess.check_call(['make', 'clean'])
	subprocess.check_call(['make', 'package', 'PACKAGEDIR=%s' % PKG_DEPLOY, 'PYTHON=python%d' % version_info.major])
	print("-" * 15)

	print("Writing hosts alias on box")
	enableHostAlias(SERVER_HOSTNAME, '127.0.0.1')

	print("Launching enigma2")
	os.environ['ENIGMA_DEBUG_LVL'] = '5'
	enigma2 = subprocess.Popen(["enigma2"])
	devNull = open('/dev/null', 'w')
	for _ in range(100):
		exitcode = subprocess.call(['xdotool', 'getwindowfocus'], stderr=devNull)
		if exitcode == 0:
			print("enigma2 started!")
			break
		else:
			time.sleep(0.1)
	else:
		raise Exception("Failed to get enigma2 window")
	print()
	time.sleep(1)

	print("Sending control sequences")
	if version_info.major <= 2:
		keys = ['Escape', 'space', 'Down', 'Down', 'Return', 'Down', 'Down', 'Return']
	else:
		keys = ['Escape', 'space'] + ['Down'] * 3 + ['Return'] + ['Down'] * 5 + ['Return']
	for key in keys:
		print("Send key", key)
		subprocess.check_call(['xdotool', 'key', key])

	for _ in range(100):
		if enigma2.poll() is None:
			time.sleep(0.1)
		else:
			print("enigma2 terminated!")
			break
	else:
		raise Exception("Failed to wait for enigma2")
	print()

	foundVerStr = None
	output = subprocess.check_output(['opkg', 'status', packageName])
	if version_info.major > 2:
		output = output.decode('utf-8')
	for line in output.splitlines():
		if line.startswith("Version:"):
			foundVerStr = line.split(":")[1].strip()
			break
	print("Current version in box is", foundVerStr)
	assert foundVerStr == testVerStr, "Found %s expected %s" % (foundVerStr, testVerStr)

	print("Test finished OK")
	enableHostAlias(SERVER_HOSTNAME, None)


if __name__ == "__main__":
	test()
