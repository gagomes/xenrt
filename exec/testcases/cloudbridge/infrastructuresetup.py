import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log

class _CloudBridge(xenrt.TestCase):

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.authServers = []
        self.domain = ""

    def prepare(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()

        if "ADDOMAIN" in args.keys():
            self.domain = args["AUTHSERVER"]
        else:
            self.domain = "xenrt" + "".join(random.sample("abcdefghijklmnopqrstuvwxyz",8)) + ".com"

        if "AUTHSERVER" in args.keys():
            authServerNames = args["AUTHSERVER"].strip().split(",")

        for authServerName in authServerNames:
            authServer = self.getGuest(authServerName)
            authServer = xenrt.ActiveDirectoryServer(authServer, domainname=self.domain)
            self.authServers.append(authServer)

    def run(self, arglist=None):
        pass
