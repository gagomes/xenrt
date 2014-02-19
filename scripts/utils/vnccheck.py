#!/usr/bin/env python
#
# Script to check if VNC is running on a given port and host.
#
# Usage: vnccheck <host> <port>
#
# vnccheck returns 0 if VNC is running at the specified location and a non-zero error otherwise.

import sys
import socket
import re

# How long to wait for a banner on an open port.
TIMEOUT=5

try:
	if len(sys.argv) != 3:
		print "Usage: vnccheck <host> <port>"
		sys.exit(2)

	host = sys.argv[1]
	port = int(sys.argv[2])
except ValueError:
	print "Usage: vnccheck <host> <port>"
	sys.exit(2)

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
	s.connect((host, port))
	s.settimeout(TIMEOUT)
	reply = s.recv(4096)
	s.close()
except socket.error:
	# Assume this meant connection refused.
	sys.exit(1)
except socket.timeout:
	sys.exit(1)
except Exception, e:
	print "Error: " + str(e)
	sys.exit(2)

# Check for banner.
if re.search("RFB", reply):
	sys.exit(0)
else:
	sys.exit(1)
