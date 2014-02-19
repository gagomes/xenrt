#!/usr/bin/python

import re, sys, string, socket

host = "127.0.0.1"

def usage(fd):
    fd.write("Usage: %s <:display> <key>\n" % (sys.argv[0]))

def buf2h(buf):
    return ord(buf[3]) + (ord(buf[2]) << 8) + (ord(buf[1]) << 16) + (ord(buf[0]) << 24)

def buf2hs(buf):
    return ord(buf[1]) + (ord(buf[0]) << 8)

def h2buf(n):
    return chr(n>>24) + chr((n>>16)&255) + chr((n>>8)&255) + chr(n&255)

def sendkey(s, keycode, modcode=None):
    if modcode:
        s.send("\x04\x01\x00\x00")
        s.send(h2buf(modcode))
    s.send("\x04\x01\x00\x00")
    s.send(h2buf(keycode))
    s.send("\x04\x00\x00\x00")
    s.send(h2buf(keycode))
    if modcode:
        s.send("\x04\x00\x00\x00")
        s.send(h2buf(modcode))

if len(sys.argv) < 3:
    usage(sys.stderr)
    sys.exit(1)

r = re.match(r":(\d+)", sys.argv[1])
if not r:
    usage(sys.stderr)
    sys.exit(1)

display = int(r.group(1))
port = 5900 + display

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((host, port))

# Protocol version
proto = s.recv(12)
sys.stderr.write("Server is: %s\n" % (proto.strip()))
s.send("RFB 003.003\n")

# Security type
sec = buf2h(s.recv(4))
sys.stderr.write("Security type: %u\n" % (sec))
if sec == 0:
    len = buf2h(s.recv(4))
    error = s.recv(len)
    sys.stderr.write("Error: %s\n" % (error.strip()))
    s.close()
    sys.exit(1)
if sec > 1:
    sys.stderr.write("Server requires authentication\n")
    s.close()
    sys.exit(1)

# Initialisation
s.send("\x01")
w = buf2hs(s.recv(2))
h = buf2hs(s.recv(2))
data = s.recv(16)
len = buf2h(s.recv(4))
name = s.recv(len)
sys.stderr.write("Frame buffer %u x %u\n" % (w, h))
sys.stderr.write("Display name: %s\n" % (name.strip()))

# Send the key(s)
for arg in sys.argv[2:]:
    ks = string.split(arg, "/")
    ks.append("None")
    sendkey(s, eval(ks[0]), eval(ks[1]))

s.close()

