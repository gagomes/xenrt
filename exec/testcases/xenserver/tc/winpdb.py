#
# XenRT: Custom test case (Python) file.
#
# To run this test case you will need to:
#
# 1. Create a sequence file.
# 2. Reference this class in the sequence file.
# 3. Submit a job using the sequence.

#import socket, re, string, time, traceback, sys, random, copy, math
import sys, os
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli
from xenrt.lazylog import log

class TCWinPDB(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        """Do setup tasks in prepare"""
        
        xenrt.TEC().logverbose("Find default host.")
        self.host = self.getDefaultHost()
        self.guest0 = self.getGuest("myVM0")
        self.guest1 = self.getGuest("myVM1")
    
    def run(self, arglist=None):
        """Do testing tasks in run"""
        
        xenrt.TEC().logverbose("Importing WinPDB libs.")
        #install rpdb2 to enable WinPDB remote debugging session.
        #os.system("scp xenrtd@10.102.127.11:~/debugger_test/rpdb2.py /tmp/")
        os.system("wget https://winpdb.googlecode.com/hg/rpdb2.py -O /tmp/rpdb2.py")
        sys.path.append(r"/tmp")
        import rpdb2
        xenrt.TEC().logverbose("Import done. Trying wait remote debugger.")
        rpdb2.start_embedded_debugger('abc', fAllowRemote = True)
        log("Hello, world!")
        log("My host name is %s" % self.host.getName())
        
        a = 10
        b = 0
        log("print a + b = %d" % a + b);
        log("print a - b = %d" % a - b);
        log("print a / b = %d" % a / b);
        
        # you can SSH to a guest by doing:
        ret = self.guest0.execguest("ls")
        
        # or to a host by doing:
        ret = self.host.execdom0("ls")
        
