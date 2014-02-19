#!/usr/bin/python

import socket,sys,subprocess

MSGSIZE=80

domid = sys.argv[1]
p = subprocess.Popen(["xenstore-read", "/local/domain/%s/console/tc-port" % domid], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out,err = p.communicate()
tcpport = int(out.strip())
retlines = int(sys.argv[2])
cuthdlines = int(sys.argv[3])
totallines = retlines + cuthdlines

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(("localhost", tcpport))

cmd = sys.stdin.read()
s.send(cmd)
if retlines > 0:
    msg = ""
    while len(msg.splitlines()) < totallines + 1:
        msg += s.recv(MSGSIZE)

    print "\n".join(msg.splitlines()[cuthdlines:totallines])
