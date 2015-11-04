#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test-wide data storage
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, threading
import xenrt

__all__ = ["Registry"]

class Registry(object):
    """Test-wide data storage"""
    def __init__(self):
        self.data = {}
        self.mylock = threading.Lock()

    def dump(self):
        xenrt.TEC().logverbose(self.data)

    def getDeploymentRecord(self):
        # TODO consider clouds
        ret = {"hosts":[], "vms": [], "templates": [], "pools": []}

        # First check hosts that are specifed by hostname
        tmpHostnameList = []
        for h in self.hostList():
            if not h.startswith("RESOURCE_HOST_"):
                if not h in tmpHostnameList:
                    ret['hosts'].append(self.hostGet(h).getDeploymentRecord())
                    tmpHostnameList.append(h)
                else:
                    xenrt.TEC().warning('There are two registry entries for hostname key: %s' % (h))
        # Nowe check hosts that are held in the registry against RESOURCE_HOST_ keys
        for h in self.hostList():
            if h.startswith("RESOURCE_HOST_") and not self.hostGet(h).getName() in tmpHostnameList:
                ret['hosts'].append(self.hostGet(h).getDeploymentRecord())
                tmpHostnameList.append(self.hostGet(h).getName())

        # Add guests
        for g in self.guestList():
            if self.guestGet(g).isTemplate:
                ret['templates'].append(self.guestGet(g).getDeploymentRecord())
            else:
                ret['vms'].append(self.guestGet(g).getDeploymentRecord())

        for p in self.poolGetAll():
            ret['pools'].append(p.getDeploymentRecord())
        return ret

    # Generic operations
    def write(self, path, value):
        xenrt.TEC().logverbose("Storing object of type %s at path %s" % (value.__class__.__name__, path))
        self.mylock.acquire()
        try:
            self.data[path] = value
        finally:
            self.mylock.release()

    def read(self, path):
        self.mylock.acquire()
        try:
            if self.data.has_key(path):
                r = self.data[path]
            else:
                r = None
        finally:
            self.mylock.release()
        return r

    def delete(self, path):
        self.mylock.acquire()
        try:
            if self.data.has_key(path):
                del self.data[path]
        finally:
            self.mylock.release()

    def addToList(self, path, value):
        self.mylock.acquire()
        try:
            if not self.data.has_key(path):
                self.data[path] = []
            if not value in self.data[path]:
                self.data[path].append(value)
        finally:
            self.mylock.release()
        
    def deleteFromList(self, path, value):
        self.mylock.acquire()
        try:
            if self.data.has_key(path):
                self.data[path].remove(value)
        finally:
            self.mylock.release()        

    def objGetAll(self, objType):
        self.mylock.acquire()
        objs = []
        try:
            for k in self.data.keys():
                if k.startswith("/xenrt/specific/%s/" % objType):
                    objs.append(self.data[k])
        finally:
            self.mylock.release()
        return objs

    def objPut(self, objType, tag, obj):
        path = "/xenrt/specific/%s/%s" % (objType, tag)
        self.write(path, obj)
    
    def objGet(self, objType, tag):
        path = "/xenrt/specific/%s/%s" % (objType, tag)
        return self.read(path)
    
    def objDelete(self, objType, tag):
        path = "/xenrt/specific/%s/%s" % (objType, tag)
        self.delete(path)
   
    def objGetDefault(self, objType):
        for k in sorted(self.data.keys()): 
            if k.startswith("/xenrt/specific/%s/" % objType):
                return self.read(k)
        raise Exception("No object found of type %s" % objType)

    # Specific operations
    def hostPut(self, tag, host):
        """Store a host object using a string tag"""
        path = "/xenrt/specific/host/%s" % (tag)
        self.write(path, host)
        self.addToList("/xenrt/specific/hostlist", tag)

    def hostGet(self, tag):
        """Look up a host object by string tag"""
        path = "/xenrt/specific/host/%s" % (tag)
        h = self.read(path)
        if not h and tag == "RESOURCE_HOST_DEFAULT":
            h = self.hostGet("RESOURCE_HOST_0")
        return h

    def hostDelete(self, tag):
        path = "/xenrt/specific/host/%s" % (tag)
        self.delete(path)
        self.deleteFromList("/xenrt/specific/hostlist", tag)

    def hostReplace(self, oldHost, newHost):
        """Try and find oldHost, and replace it with newHost"""
        for hn in list(self.hostList()):
            h = self.hostGet(hn)
            if not h:
                raise xenrt.XRTError("Cannot find old host object")
            if h == oldHost:
                self.hostDelete(hn)
                self.hostPut(hn, newHost)

    def hostList(self):
        if not self.data.has_key("/xenrt/specific/hostlist"):
            return []
        return self.data["/xenrt/specific/hostlist"]

    def hostFind(self, hostName):
        hosts = self.hostList()
        found = []
        for host in hosts:
            possibleHost = self.hostGet(host)
            if hostName == possibleHost.getName() or hostName == possibleHost.getIP():
                found.append(possibleHost)
        return found
    
    def guestLookup(self, vcpus=None, 
                          memory=None,
                          distro=None,
                          arch=None,
                          method=None,
                          disksize=None,
                          varch=None):
        """Fetch guests satisfying resource criteria"""
        guestlist = []
        for guest in self.guestList():
            guestlist.append(guest)
            config = self.configGet(guest)
            if vcpus:
                if config.has_key("vcpus"):
                    if not config["vcpus"] == vcpus:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            if memory:
                if config.has_key("memory"):
                    if not config["memory"] == memory:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            if distro:
                if config.has_key("distro"):
                    if not config["distro"] == distro:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            if arch:
                if config.has_key("arch"):
                    if not config["arch"] == arch:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            if method:
                if config.has_key("method"):
                    if not config["method"] == method:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            if disksize:
                if config.has_key("disksize"):
                    if not config["disksize"] == disksize:
                        guestlist.remove(guest)
                        continue
                else:
                    guestlist.remove(guest)
                    continue
            # varch argument is ignored for now...
        return guestlist

    def configPut(self, tag, vcpus=None, 
                             memory=None,
                             distro=None,
                             arch=None,
                             method=None,
                             disksize=None,
                             varch=None):
        """Store a guest configuration using a string tag"""
        path = "/xenrt/specific/configuration/%s" % (tag)
        if vcpus:
            self.write(path + "/vcpus", vcpus)
        if memory:
            self.write(path + "/memory", memory)
        if distro:
            self.write(path + "/distro", distro)
        if arch:
            self.write(path + "/arch", arch)
        if method:
            self.write(path + "/method", method)
        if disksize:
            self.write(path + "/disksize", disksize)
        if varch:
            self.write(path + "/varch", varch)

    def configGet(self, tag):
        """Look up a guest configuration by string tag"""
        config = {}
        path = "/xenrt/specific/configuration/%s" % (tag)
        vcpus = self.read(path + "/vcpus")
        memory = self.read(path + "/memory")
        distro = self.read(path + "/distro")
        arch = self.read(path + "/arch")
        method = self.read(path + "/method")
        disksize = self.read(path + "/disksize")
        varch = self.read(path = "/varch")
        if vcpus:
            config["vcpus"] = vcpus
        if memory:
            config["memory"] = memory
        if distro:
            config["distro"] = distro
        if arch:
            config["arch"] = arch
        if method:
            config["method"] = method
        if disksize:
            config["disksize"] = disksize
        if varch:
            config["varch"] = varch
        return config

    def guestPut(self, tag, guest):
        """Store a guest object using a string tag"""
        path = "/xenrt/specific/guest/%s" % (tag)
        self.write(path, guest)
        self.addToList("/xenrt/specific/guestlist", tag)

    def guestGet(self, tag):
        """Look up a guest object by string tag"""
        path = "/xenrt/specific/guest/%s" % (tag)
        return self.read(path)

    def guestDelete(self, tag):
        path = "/xenrt/specific/guest/%s" % (tag)
        self.delete(path)
        self.deleteFromList("/xenrt/specific/guestlist", tag)

    def guestList(self):
        if not self.data.has_key("/xenrt/specific/guestlist"):
            return []
        return self.data["/xenrt/specific/guestlist"]
    
    def bitsPut(self, tag, filename):
        """Store a local path to a set of Xen bits"""
        path = "/xenrt/specific/bits/%s" % (tag)
        self.write(path, filename)

    def bitsGet(self, tag):
        """Look up a local path to a set of Xen bits"""
        path = "/xenrt/specific/bits/%s" % (tag)
        return self.read(path)

    def bitsDelete(self, tag):
        path = "/xenrt/specific/bits/%s" % (tag)
        self.delete(path)
        
    def buildPut(self, tag, build):
        """Store a build object using a string tag"""
        path = "/xenrt/specific/build/%s" % (tag)
        self.write(path, build)

    def buildGet(self, tag):
        """Look up a build object by string tag"""
        path = "/xenrt/specific/build/%s" % (tag)
        return self.read(path)

    def buildDelete(self, tag):
        path = "/xenrt/specific/build/%s" % (tag)
        self.delete(path)

    def buildServerPut(self, tag, buildserver):
        """Store a build server object using a string tag"""
        path = "/xenrt/specific/buildserver/%s" % (tag)
        self.write(path, buildserver)

    def buildServerGet(self, tag):
        """Look up a build server object by string tag"""
        path = "/xenrt/specific/buildserver/%s" % (tag)
        return self.read(path)

    def buildServerDelete(self, tag):
        path = "/xenrt/specific/buildserver/%s" % (tag)
        self.delete(path)

    def poolPut(self, tag, pool):
        """Store a pool object using a string tag"""
        path = "/xenrt/specific/pool/%s" % (tag)
        self.write(path, pool)

    def poolGet(self, tag):
        """Look up a pool object by string tag"""
        path = "/xenrt/specific/pool/%s" % (tag)
        return self.read(path)

    def poolGetAll(self):
        """Get all pool objects"""
        return self.objGetAll("pool")

    def poolDelete(self, tag):
        path = "/xenrt/specific/pool/%s" % (tag)
        self.delete(path)

    def poolReplace(self, oldPool, newPool):
        """Try and find oldPool, and replace it with newPool"""
        i = 0
        while True:
            p = self.poolGet("RESOURCE_POOL_%u" % (i))
            if not p:
                raise xenrt.XRTError("Cannot find old pool object")
            if p == oldPool:
                self.poolDelete("RESOURCE_POOL_%u" % (i))
                self.poolPut("RESOURCE_POOL_%u" % (i), newPool)
                break
            i += 1

    def resourcePut(self, tag, resource):
        """Store a pool object using a string tag"""
        path = "/xenrt/specific/resource/%s" % (tag)
        self.write(path, resource)

    def resourceGet(self, tag):
        """Look up a pool object by string tag"""
        path = "/xenrt/specific/resource/%s" % (tag)
        return self.read(path)

    def resourceDelete(self, tag):
        path = "/xenrt/specific/resource/%s" % (tag)
        self.delete(path)

    def toolstackPut(self, tag, resource):
        self.objPut("toolstack", tag, resource)

    def toolstackGet(self, tag):
        return self.objGet("toolstack", tag)

    def toolstackDelete(self, tag):
        self.objDelete("toolstack", tag)

    def toolstackGetDefault(self):
        return self.objGetDefault("toolstack")

    def toolstackGetAll(self):
        return self.objGetAll("toolstack")

    def instancePut(self, tag, resource):
        self.objPut("instance", tag, resource)

    def instanceGet(self, tag):
        return self.objGet("instance", tag)

    def instanceDelete(self, tag):
        self.objDelete("instance", tag)

    def instanceGetAll(self):
        return self.objGetAll("instance")

    def vlanPut(self, tag, resource):
        self.objPut("vlan", tag, resource)

    def vlanGet(self, tag):
        return self.objGet("vlan", tag)

    def vlanDelete(self, tag):
        self.objDelete("vlan", tag)

    def vlanGetAll(self):
        return self.objGetAll("vlan")

    def centralResourcePut(self, id, res):
        self.objPut("centralresource", id, res)

    def centralResourceGet(self, id):
        return self.objGet("centralresource", id)

    def centralResourceDelete(self, tag):
        self.objDelete("centralresource", id)

    def centralResourceGetAll(self):
        return self.objGetAll("centralresource")
