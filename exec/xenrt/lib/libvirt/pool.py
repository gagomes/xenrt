#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a libvirt pool.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt

class Pool(object):

    """A libvirt host pool."""
    def __init__(self, master):
        self.master = master
        if master:
            master.pool = self
        self.slaves = {}

    def populateSubclass(self, x):
        x.master = self.master
        x.slaves = self.slaves
        for h in x.getHosts():
            h.pool = x

    def listSlaves(self):
        """Return a list of names of slaves in this pool."""
        return [self.slaves[slave].getName() for slave in self.slaves]

    def getHosts(self):
        """Returns a list of ALL host objects in the pool"""
        hosts = self.slaves.values()
        hosts.append(self.master)
        return hosts

    def getSlaves(self):
        """Returns a list of slave host objects in the pool"""
        hosts = self.slaves.values()
        return hosts

    def getHost(self, uuid):
        """Return the host object for the given UUID"""
        hosts = self.getHosts()
        for h in hosts:
            if h.getMyHostUUID() == uuid:
                return h
        return None
