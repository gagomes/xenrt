import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log
from pysphere import VIServer

class Pysphere(xenrt.TestCase):
    
    def run(self, arglist=None):
        """Do testing tasks in run"""
        
        server = VIServer()
        server.connect("vcenter-rdm-01.ad.xensource.com", "administrator", "xenROOT1")
        
        xenrt.TEC().logverbose(server.get_server_type())
        xenrt.TEC().logverbose(server.get_api_version())
        
        vmlist = server.get_registered_vms()
        xenrt.TEC().logverbose(vmlist)
        
        server.disconnect()
