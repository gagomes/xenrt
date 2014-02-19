#!/usr/bin/python

# Return 5MB of garbage to any client that connects to us

# Usage: returngarbage.py <port>

import sys, SocketServer, random

class GarbageHandler(SocketServer.BaseRequestHandler ):
    def setup(self):
        print self.client_address, 'connected'

    def handle(self):
        print "sending garbage..."
        for i in range(5*1024*1024):
            self.request.send(chr(random.randint(0, 255)))

    def finish(self):
        print self.client_address, 'disconnected'

port = int(sys.argv[1])
server = SocketServer.ThreadingTCPServer(('', port), GarbageHandler)
server.serve_forever()

