#
# XenRT: Custom test case (Python) file.
#
# To run this test case you will need to:
#
# 1. Create a sequence file.
# 2. Reference this class in the sequence file.
# 3. Submit a job using the sequence.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log
import subprocess
class TCMyTestCase(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        """Do setup tasks in prepare"""
        
        self.host0 = self.getHost("RESOURCE_HOST_0")
        #self.host1 = self.getHost("RESOURCE_HOST_0")
        #self.guest0 = self.getGuest("myVM0")
        #self.guest1 = self.getGuest("myVM1")
        self.fooint = 234
        self.string = "String"
        self.dict = {1:'a', 2:'b'}
        self.list = ["1", 'b' , 23]
    
    def run(self, arglist=None):
        """Do testing tasks in run"""
        
        xenrt.TEC().logverbose("Hello, world!")
        #log("My host0 name is %s" % self.host0.getName())
                
        # you can SSH to a guest by doing:
        #ret = self.guest0.execguest("ls")
        
        # or to a host by doing:
        #ret = self.host0.execdom0("ls")
        
