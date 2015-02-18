# XenRT: Test harness for Xen and the XenServer product family
#
# Docker feature tests.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

#import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lib.xenserver.docker import *

class TCSanityTest(xenrt.TestCase):

    def prepare(self, arglist=None):

        args = self.parseArgsKeyValue(arglist) 
        self.distro = args.get("coreosdistro", "coreos-alpha") 

        # Obtain the pool object to retrieve its hosts. 
        self.pool = self.getDefaultPool() 
        xenrt.TEC().logverbose("self.pool: %s" % self.pool) 
        if self.pool is None: 
            self.host = self.getDefaultHost() 
        else: 
            self.host = self.pool.master 

        # Obtain the CoreOS guest object. 
        self.coreos = self.getGuest(self.distro)

    def run(self, arglist=None):

        pass
