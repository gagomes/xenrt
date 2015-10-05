import xenrt, sys
import testcases.xenserver.tc.perf.loginvsi.libloginvsi as libloginvsi
import libperf
import string, time, re, random, math
import traceback
import datetime
from xenrt.seq import PrepareNode
import xml.dom.minidom
import subprocess
import socket
import time
import thread
import threading
from threading import Thread
import resource
import math
import os.path
import random
import urllib2, shutil, os, os.path
import xmlrpclib
import XenAPI
try:
    import libvirt
except:
    sys.stderr.write("WARNING: Could not import libvirt classes\n")

class Util(object):
    # try some function up to x times
    def tryupto(self, fun, times=5,sleep=0):
        for i in range(times):
            try:
                return fun()
            except Exception, e:
                if i<times-1:
                    xenrt.TEC().logverbose("tryupto: exception %s" % e)
                    xenrt.TEC().logverbose(traceback.format_exc())
                    pass
                else: # re-raise the exception if the last attempt doesn't succeed
                    raise
            if sleep>0:
                xenrt.TEC().logverbose("tryupto: sleeping %s seconds" % sleep)
                time.sleep(sleep)
        raise xenrt.XRTError("tryupto: we should never reach this line")

    def download(self,url,filename=None):
        xenrt.TEC().logverbose("downloading %s->%s" % (url,filename))
        req=urllib2.urlopen(url)
        if filename:
            if not os.path.exists(os.path.dirname(filename)):
                os.mkdir(os.path.dirname(filename))
            fp=open(filename,'wb')
            shutil.copyfileobj(req,fp,65536) # large files can be copied efficiently
            fp.close()
            return None
        else:
            return req.read()

    def sendToDom0(self,url,host,dom0_filepath):
        xenrt.TEC().logverbose("sending to dom0: %s->%s:%s" % (url,host,dom0_filepath))
        tmpfile=xenrt.TEC().tempFile()
        xenrt.getHTTP(url,tmpfile)
        try:
            sftp = host.sftpClient()
            sftp.copyTo(tmpfile,dom0_filepath)
        finally:
            sftp.close()

class TestSpace(Util):
    d_order = []  # [iterated slower,...,iterated faster]
    
    def filter(self,filters,dimensions):
        #return dict(map(lambda k:(k,filter(filters[k],dimensions[k]) if filters and k in filters else dimensions[k]),dimensions))
        return dict(map(lambda k:(k,(filters and k in filters) and filter(filters[k],dimensions[k]) or dimensions[k]),dimensions))
        
    # return known dimensions, optionally with range subsets
    def getDimensions(self, filters=None): #each dimension is a pair rangename:[range]
        return self.filter(filters,{})

    def getdOrder(self):
        dimensions = self.getDimensions()
        #ignore any dimension without points
        return filter(lambda d:len(dimensions[d])>0, self.d_order)

    # return the product of the dimensions as individual points
    def getPoints(self,dimensions):
        result = [[]]
        d_order = self.getdOrder()
        xenrt.TEC().logverbose("d_order = %s" % (d_order,))
        for d in d_order:
            dims = dimensions[d]
            xenrt.TEC().logverbose("dims.type = %s, dims = %s" % (type(dims).__name__, dims))
            result=[x+[y] for x in result for y in dims]
            #xenrt.TEC().logverbose("result = %s" % (result,))
        return result

    # return the dimensions that changed between 2 points
    def getDiffDimensions(self, point1, point2):
        coords = self.getDiffCoordinates(point1, point2)
        return map(lambda (d,p1,p2):d, coords)

    # return tuples with dimension,coordinates that changed between 2 points
    def getDiffCoordinates(self, point1, point2):
        result = []
        d_order = self.getdOrder()
        if point1:
            for i in range(len(d_order)):
                #result+= [(d_order[i],point1[i],point2[i])] if point1[i]!=point2[i] else []
                result+= (point1[i]!=point2[i]) and [(d_order[i],point1[i],point2[i])] or []
        else:
            for i in range(len(d_order)):
                result+= [(d_order[i],None,point2[i])]
        return result

    def getLeftMostCoordinates(self,coords,p1,p2):
        d_order = self.getdOrder()
        #xsversions event needs to be triggered if a dimension to its left has changed
        #(but not if only a dimension to its right has changed)
        #this is a quick idea to get this done. we should think some better way, maybe
        #setting a flag on the dimensions on the dimension list in a more general way
        xenrt.TEC().logverbose("d_order=%s,coords=%s,p1=%s,p2=%s"%(d_order,coords,p1,p2))
        max_d_idx_in_coords=-1
        try: xsversions_idx=d_order.index("XSVERSIONS")
        except: xsversions_idx=-1
        xsversions_coords=-1
        for i in range(len(coords)):
            d,pi,pj = coords[i]
            if max_d_idx_in_coords<d_order.index(d):
                if max_d_idx_in_coords>-1 and max_d_idx_in_coords<xsversions_idx and d_order.index(d)>xsversions_idx:
                    xsversions_coords=i
                max_d_idx_in_coords=d_order.index(d)
        xenrt.TEC().logverbose("max_d_idx=%s,xsversions_idx=%s,xsversions_coords=%s" % (max_d_idx_in_coords,xsversions_idx,xsversions_coords))
        if xsversions_coords>=0:
            #we must add the xsversions event at the correct location
            coords.insert(xsversions_coords,("XSVERSIONS",p1[xsversions_idx],p2[xsversions_idx]))
        xenrt.TEC().logverbose("coords=%s" % coords)
        return coords

    #def idx(self, col, hd=self.d_order):
    #    i = 0
    #    for h in hd:
    #        if h==col:
    #            return i
    #        else:
    #            i = i + 1
    #    raise Exception("no header")

# the dimensions here are used when running an experiment with VMs
class VMLoad(TestSpace):
    #valid ranges of each dimension
    VMLOADS = []
    d_order = ['VMLOADS']
    def getDimensions(self, filters=None):
        return { 'VMLOADS':[] }

    #save the experiment running this load in order to access context
    def __init__(self,experiment,params):
        self.experiment = experiment
        self.params = params
    def install(self, guest):
        pass
    def start(self, guest):
        pass
    def stop(self, guest):
        pass

# the dimensions here are used when running an experiment
class HostLoad(TestSpace):
    #valid ranges of each dimension
    HOSTLOADS = []
    d_order = ['HOSTLOADS']
    def getDimensions(self, filters=None):
        return { 'HOSTLOADS':[] }
    #save the experiment running this load in order to access context
    def __init__(self,experiment):
        self.experiment = experiment
    def install(self, host):
        pass
    def start(self, host):
        pass
    def stop(self, host):
        pass

# the dimensions here are used when installing a VM
class VMConfig(TestSpace):

    windistros = ['w2k3eesp2','w2k3eesp2-64','winxpsp3','ws08sp2x86','ws08sp2-x64','win7sp1-x86','win7sp1-x64','win8-x86','win8-x64'] #vistaeesp2, vistaeesp2-x86, w2k3eesp2, w2k3eesp2-x64, w2k3sesp2, win7sp1-x64, win7sp1-x86, winxpsp3, ws08-x86, ws08-x64, ws08r2sp1-x64, ws08sp2-x86, ws08sp2-x64
    posixdistros = ['centos56','ubuntu1004','solaris10u9']
    distros = windistros + posixdistros
    
    #valid ranges of each dimension
    VMTYPES = ['winxpsp3', 'win7sp1-x86', 'win8-x86'] #['winxpsp3', 'win7sp1-x86'] #['win7sp1-x86'] #['winxpsp3-vanilla.img'] #['winxpsp3'] #['centos5'] #['winxpsp3'] #[ 'WIN7', 'WIN7SP2', 'WINXPSP3', 'WIN2K8', 'WIN8', 'UBUNTU1004' ]
    VBDS = [1, 7]
    VIFS = [1, 7]
    VMPARAMS = [("platform:viridian","true"),("platform:viridian","false")] #apic,nx,acpi
    VMRAM = [256,512,1024,2048,16384,65536]
    d_order = ['VMTYPES','VBDS','VIFS','VMPARAMS','VMRAM']
    def getDimensions(self, filters=None):
        return self.filter(filters,
            { 'VMTYPES':self.VMTYPES,
              'VBDS':self.VBDS,
              'VIFS':self.VIFS,
              'VMPARAMS':self.VMPARAMS,
              'VMRAM':self.VMRAM
            }
        )
    #obj state: #default values:
    vmtype = 'WIN7SP2'
    #save the experiment running this load in order to access context
    def __init__(self,experiment):
        self.experiment = experiment
    def add(self, vm):
        pass
    def post_clone(self, vms):
        pass

# the dimensions here are used when installing a host
class HostConfig(HostLoad):
    #valid ranges of each dimension:

    #select hardware available from hardware lab
    HWCPUS = [ 1, 2, 4, 8, 16, 32, 64, 128 ]
    HWRAM   = [ 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024] #GiB

    # select available software/config
    XSVERSIONS = [ 'george', 'mnr', 'cowley', 'oxford', 'boston', 'tampa', 'trunk' ]
    IOMMU = [ True, False ]
    NUMA  = [ True, False ]
    DOM0RAM = ['2940', '752'] #see http://confluence/display/ring3/Increasing+dom0+memory
    XENSCHED = ['credit2','credit']
    DOM0DISKSCHED = ['noop','anticipatory','deadline','cfq'] #/sys/block/sda/queue/scheduler
    QEMUPARAMS = [ ["nousb","nochild"], []]
    DEFAULTSR = [ "ext", "lvm", "nfs" ]
    d_order = ['XENSCHED','HWCPUS','HWRAM','XSVERSIONS','IOMMU','NUMA','DOM0RAM','DEFAULTSR']
    #obj_state: #default values:
    xsversion = 'TRUNK'
    def getDimensions(self, filters=None):
        return self.filter(filters,
            { 'XSVERSIONS':self.XSVERSIONS,
              'HWCPUS':self.HWCPUS,
              'IOMMU':self.IOMMU,
              'NUMA':self.NUMA,
              'HWRAM':self.HWRAM,
              'DOM0RAM':self.DOM0RAM,
              'XENSCHED':self.XENSCHED,
              'DOM0DISKSCHED':self.DOM0DISKSCHED,
              'QEMUPARAMS':self.QEMUPARAMS,
              'DEFAULTSR':self.DEFAULTSR
            }
        )
    #save the experiment running this load in order to access context
    def __init__(self,experiment):
        self.experiment = experiment
    def install(self, host):
        pass
    def start(self, host):
        pass
    def stop(self, host):
        pass

# the dimensions here are used when installing a pool
class PoolConfig(TestSpace):
    #valid ranges of each dimension:
    HOSTS = range(1,32)
    VMS = range(1,60)
    d_order = ['HOSTS'] # VMS out for now
    def getDimensions(self, filters=None):
        return self.filter(filters,
            {'HOSTS':self.HOSTS,
             'VMS':self.VMS
            }
        )

    #obj_state: #default values:
    hosts = 1

class XapiEvent(Util):
    events = {}
    in_loop = False
    def __init__(self,experiment):
        self.experiment = experiment
        self.host = self.experiment.tc.getDefaultHost()
        thread.start_new_thread(self.listen,())
        xenrt.TEC().logverbose("XapiEvent: finished __init__")

    def reset(self):
        self.events = {}

    def getSession(self):
        session = self.host.getAPISession(secure=False)
        xenrt.TEC().logverbose("XapiEvent: session=%s" % session)
        return session

    def listen(self):
        while True:
            try: #work around ca-80933
 
                session = self.tryupto(self.getSession, times=5, sleep=5) 
                try:
                    self.processEvents(session)
                #except Exception, e:
                #    xenrt.TEC().logverbose("XapiEvent: listen except: %s" % e)
                #    raise
                finally:
                    self.host.logoutAPISession(session)

            except Exception, e:
                xenrt.TEC().logverbose("XapiEvent.listen: Exception: %s" % e)

    def hasEvent(self, vm, key, value):
        found = False
        if vm in self.events:
            if key in self.events[vm]:
                found = (self.events[vm][key] == value)
        return found

    def waitFor(self, vm, key, value):
        xenrt.TEC().logverbose("XapiEvent: waiting for event on vm=%s,key=%s,value=%s" % (vm,key,value))
        if not self.in_loop:
            raise xenrt.XRTFailure("XapiEvent: waitFor: XapiEvent not listening: not in loop")
        found = False
        while not found:
            found = self.hasEvent(vm,key,value)
            if not found:
                time.sleep(0.1)
        xenrt.TEC().logverbose("found event vm=%s,key=%s,value=%s" % (vm,key,value))

    def processVm(self, session, vm, snapshot):
        if True: #snapshot['power_state'] == "Running":
            xenrt.TEC().logverbose("xapi-event: vm_uuid=%s(%s),power_state=%s,current_operations=%s" % (snapshot['uuid'],snapshot['name_label'],snapshot['power_state'],snapshot["current_operations"].values()))
            self.events[snapshot['uuid']]=snapshot

    def processEvents(self, session):
        xenrt.TEC().logverbose("START:XapiEvent.processEvents")

        def register():
            xenrt.TEC().logverbose("registering for events")
            session.xenapi.event.register(["VM","pool"])
            # look at current state
            all_vms = session.xenapi.VM.get_all_records()
            for vm in all_vms.keys():
                self.processVm(session, vm, all_vms[vm])
 
        register()
        self.complete = False
        while not self.complete:
            # Event loop
            try:
                self.in_loop = True
                xenrt.TEC().logverbose("calling event.next()")
                socket.setdefaulttimeout(600.0) # xapi should return from event.next every 30s at most with a pool event.
                evs = session.xenapi.event.next()
                for event in evs:
                    xenrt.TEC().logverbose("received event op='%s' class='%s' ref='%s'" % (event['operation'], event['class'], event['ref']))
                    if event['class'] == 'vm' and event['operation'] == 'mod':
                        self.processVm(session, event['ref'], event['snapshot'])
                        continue
 
            except XenAPI.Failure, e:
                xenrt.TEC().logverbose("** exception: e = [%s]" % e)
                xenrt.TEC().logverbose("** exception: e.details = [%s]" % e.details)
                if len(e.details) > 0 and e.details[0] == 'EVENTS_LOST':
                    xenrt.TEC().logverbose("** Caught EVENTS_LOST")
                    session.xenapi.event.unregister(["VM","pool"])
                    register()
                else:
                    xenrt.TEC().logverbose("** Non-EVENTS_LOST 'failure' exception: %s" % traceback.format_exc())
                    xenrt.TEC().logverbose("** re-registering anyway")
                    session.xenapi.event.unregister(["VM","pool"])
                    register()
            except:
                xenrt.TEC().logverbose("** fatal exception: %s" % traceback.format_exc())
                self.complete = True
                self.error = True

        self.in_loop = False
        xenrt.TEC().logverbose("END:XapiEvent.processEvents")



class VirtEvent(Util):
    guest_state = {}

    def __init__(self, experiment):
        self.experiment = experiment
        self.host = self.experiment.tc.getDefaultHost()
        thread.start_new_thread(self.listen,())
        xenrt.TEC().logverbose("VirtEvent: finished __init__")

    @classmethod
    def isSupported(cls, experiment):
        return experiment.tc.getDefaultHost().__class__ not in [xenrt.lib.esx.ESXHost]

    def listen(self):
        while True:
            try: #work around ca-80933
 
                virConn = self.tryupto(self.host._openVirConn, times=5, sleep=5) 
                try:
                    self.processEvents(virConn)
                #except Exception, e:
                #    xenrt.TEC().logverbose("XapiEvent: listen except: %s" % e)
                #    raise
                finally:
                    virConn.close()

            except:
                import traceback
                xenrt.TEC().logverbose("VirtEvent.listen: Exception: %s" % traceback.format_exc())


    def reset(self):
        self.guest_state = {}

    def callback(self, virConn, virDomain, event, detail, data):
        if self.complete:
            return
        try:
            state = None
            if event == libvirt.VIR_DOMAIN_EVENT_STARTED:
                state = "UP"
            elif event == libvirt.VIR_DOMAIN_EVENT_SUSPENDED:
                state = "SUSPENDED"
            elif event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
                state = "UP"
            elif event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
                state = "DOWN"
            elif event == libvirt.VIR_DOMAIN_EVENT_SHUTDOWN:
                state = "DOWN"

            xenrt.TEC().logverbose("VirtEvent: received event" + ((", new state is %s" % state) if state else ""))
            if state:
                self.guest_state[virDomain.UUIDString()] = state
        except:
            xenrt.TEC().logverbose("** fatal exception: %s" % traceback.format_exc())
            self.complete = True
            self.error = True

    def processEvents(self, virConn):
        xenrt.TEC().logverbose("START:VirtEvent.processEvents")

        def register():
            xenrt.TEC().logverbose("VirtEvent: registering for events")
            self.eventsID = virConn.domainEventRegister(self.callback, None)
            # look at current state
            for guestName in self.host.listGuests():
                guest = self.host.guestFactory()(guestName, host=self.host)
                guest.virDomain = guest.virConn.lookupByName(guest.name)
                self.guest_state[guest.getUUID()] = guest.getState()
 
        register()
        self.complete = False
        self.in_loop = True
        while not self.complete:
            time.sleep(1)

        self.in_loop = False

        xenrt.TEC().logverbose("END:VirtEvent.processEvents")

    def hasEvent(self, vm, key, value):
        if key == "power_state":
            if vm in self.guest_state:
                return (value == "Running" and self.guest_state[vm] == "UP") or \
                       (value == "Halted" and self.guest_state[vm] == "DOWN")
        else:
            raise xenrt.XRTError("VirtEvent doesn't know about %s events" % key)

    def waitFor(self, vm, key, value):
        xenrt.TEC().logverbose("VirtEvent: waiting for event on vm=%s,key=%s,value=%s" % (vm,key,value))
        if not self.in_loop:
            raise xenrt.XRTFailure("VirtEvent: waitFor: VirtEvent not listening: not in loop")
        found = False
        while not found:
            found = self.hasEvent(vm,key,value)
            if not found:
                time.sleep(0.1)
        xenrt.TEC().logverbose("found event vm=%s,key=%s,value=%s" % (vm,key,value))

class DummyEvent(Util):
    def __init__(self, experiment):
        self.experiment = experiment
        self.host = self.experiment.tc.getDefaultHost()

    def reset(self):
        self.guest_state = {}

    def hasEvent(self, vmuuid, key, value):
        guestname = self.host.virConn.lookupByUUIDString(vmuuid).name()
        guest = self.host.guests[guestname]
        if key == "power_state":
            gueststate = guest.getState()
            return (value == "Running" and gueststate == "UP") or \
                   (value == "Halted" and gueststate == "DOWN")
        else:
            raise xenrt.XRTError("DummyEvent doesn't know about %s events" % key)

    def waitFor(self, vmuuid, key, value):
        xenrt.TEC().logverbose("DummyEvent: waiting for event on vm=%s,key=%s,value=%s" % (vmuuid,key,value))
        found = False
        while not found:
            found = self.hasEvent(vmuuid,key,value)
            if not found:
                # we run the risk of flooding the server with "get guest info" requests
                # this makes for relatively poor granularity but there's not much we can do
                time.sleep(0.5)
        xenrt.TEC().logverbose("found event vm=%s,key=%s,value=%s" % (vmuuid,key,value))

@xenrt.irregularName
def APIEvent(experiment):
    lib = xenrt.productLib(host=experiment.tc.getDefaultHost())
    xenrt.TEC().logverbose("lib=%s" % (lib,))
    if lib == xenrt.lib.xenserver:
        xenrt.TEC().logverbose("Using xapi event listener")
        return XapiEvent(experiment)
    elif lib == xenrt.lib.esx or lib == xenrt.lib.kvm:
        if VirtEvent.isSupported(experiment):
            xenrt.TEC().logverbose("Using libvirt event listener")
            return VirtEvent(experiment)

    xenrt.TEC().logverbose("Using dummy event listener")
    return DummyEvent(experiment)


class GuestEvent(object):
    # dict: ip -> ...
    events = {}
    INET = socket.AF_INET
    UDP_IP = socket.gethostbyname(socket.gethostname())
    UDP_PORT = 5000
    EVENT = None

    def __init__(self,experiment):
        if not self.EVENT:
            self.log("Abstract class!")
        self.experiment = experiment

        self.INET = socket.AF_INET
        if xenrt.TEC().lookup("USE_GUEST_IPV6", False):
            self.INET = socket.AF_INET6

        if self.INET == socket.AF_INET6:
            import netifaces
            ifs = netifaces.ifaddresses('eth0')
            xenrt.TEC().logverbose("interfaces(eth0)=%s" % (ifs,))
            self.UDP_IP = filter(lambda x: not x['addr'].startswith('fe80'), ifs[netifaces.AF_INET6])[0]['addr']

        xenrt.TEC().logverbose("UDP_IP=%s" % (self.UDP_IP,))

        thread.start_new_thread(self.listen,())

    def script_filename(self):
        return self.__class__.__name__+"_udp_send.py"
    def stop_filename(self):
        return self.__class__.__name__+"_udp_send.stop"
    def log(self,msg):
        xenrt.TEC().logverbose("%s: %s" % (self.__class__.__name__, msg))

    def reset(self):
        self.events = {}

    def stop_guest(self, guest):
        if guest.windows:
            i=0
            done=False
            while not done:
                try:
                    guest.xmlrpcWriteFile("c:\\%s" % self.stop_filename(), "")
                    done=True
                except Exception, e:
                    xenrt.TEC().logverbose("GuestEvent:(i=%s) while writing %s: %s" % (i,self.stop_filename, e))
                time.sleep(600)
                i=i+1
        else:#todo: posix guest
            pass

    def listen(self):
        sock = socket.socket( self.INET,          # IPv4/6
                              socket.SOCK_DGRAM ) # UDP
        bound=False
        while not bound:
            try:
                sock.bind( (self.UDP_IP,self.UDP_PORT) )
                bound=True
            except Exception, e:
                self.log("binding to %s:%s: %s" % (self.UDP_IP,self.UDP_PORT,e))
                self.UDP_PORT = random.randint(5000,50000)
        self.log("bound to %s:%s" % (self.UDP_IP,self.UDP_PORT))

        while True:
            try:
                if xenrt.TEC().lookup("USE_GUEST_IPV6", False):
                    msg, (guest_ip, guest_port, foo, bar) = sock.recvfrom( 16)#, socket.MSG_DONTWAIT ) # buffer size is smallest possible to fit one msg only
                    # pad ipv6 with missing 0s so that it matches the one returned by guests via xenrt
                    guest_ip = ":".join(map(lambda i: i.zfill(4), guest_ip.split(":")))
                else:
                    msg, (guest_ip, guest_port) = sock.recvfrom( 16)#, socket.MSG_DONTWAIT ) # buffer size is smallest possible to fit one msg only
                if not self.events.has_key(guest_ip):
                    guest_name="n/a"
                    if self.experiment.ip_to_guest.has_key(guest_ip):
                        guest=self.experiment.ip_to_guest[guest_ip]
                        guest_name=guest.getName()
                    self.log("for %s: received guest_ip, guest_port, message: %s, %s, %s" % (guest_name, guest_ip, guest_port, msg))
                    self.events[guest_ip]=msg
                    guest = self.experiment.ip_to_guest[guest_ip]
                    #thread.start_new_thread(self.stop_guest,(guest,))

            except Exception, e:
                self.log("listen: %s" % (e,))
                time.sleep(0.1)

    def hasIp(self, ips,mainip):
        if self.events.has_key(mainip):
            return True
        for ip in ips:
            if self.events.has_key(ip):
                return True
        return False

    def findVifsIps(self, guest):
        guest_vifs=[(nic,vbridge,mac,ip) for (nic,(mac,ip,vbridge)) in guest.getVIFs().items()]
        guest_vifs.sort()
        self.log("Event: %s, Found VIFs: %s" % (self.EVENT,guest_vifs))
        guest_ips = map(lambda (nic, vbridge, mac, ip):ip, guest_vifs)
        self.log("Event: %s, Found IPs: %s" % (self.EVENT,guest_ips))
        return (guest_vifs,guest_ips)

    def receive(self, guest, timeout=400):
        (guest_vifs,guest_ips)=([],[]) #self.findVifsIps(guest)
        if self.hasIp(guest_ips,guest.mainip):
            self.log("already received event %s from ip %s,%s" % (self.EVENT,guest.mainip,guest_ips))
            return True
        start = xenrt.util.timenow() 
        done = False
        i=1
        while not done and (start+timeout > xenrt.util.timenow()):
            if math.log(i,2) % 1 == 0.0:#back-off printing of i 
                self.log("checking if event %s has been received from %s,%s..." % (self.EVENT,guest.mainip,guest_ips))
            if None in guest_ips and (i/50.0) % 1 == 0.0:#try every 5s
                #refresh ip information if any guest ip is unknown and we are still trying to find the event
                (guest_vifs,guest_ips)=self.findVifsIps(guest)
            if self.hasIp(guest_ips,guest.mainip):
                done = True
            time.sleep(0.1)
            i=i+1
        if not done:
            self.log("timeout!")
        return done

    #install send script in the guest
    def installSendScript(self,guest):
        script="""
import socket
import time
import os.path

%s

controller_ip = "%s"
controller_udp_port = %s
i=0
while not os.path.isfile("%s%s") and i<600000:
    msg = "%s+MSG%%s" %% i
    print "sending to (%%s:%%s):%%s" %% (controller_ip,controller_udp_port,msg)
    try:
        s = socket.socket( %s, socket.SOCK_DGRAM)
        %s
        s.sendto(msg, (controller_ip, controller_udp_port))
    except Exception, e:
        print "exception %%s" %% e
    time.sleep(3.0)
    i=i+1
"""
        if xenrt.TEC().lookup("USE_GUEST_IPV6", False):
            afinet = "socket.AF_INET6"
            if guest.windows:
                get_ipv6_fn = """
import subprocess
ipv6 = False
while not ipv6:
    print "not found local ipv6 yet"
    for line in subprocess.check_output("ipconfig").split("\\r\\n"):
        print line
        if "  IPv6 Address" in line:
            ipv6 = line.split(": ")[1]
            print "found local ipv6 %s" % (ipv6,)
"""
            else:
                get_ipv6_fn = """
import subprocess
ipv6 = False
while not ipv6:
    print "not found local ipv6 yet"
    for line in subprocess.check_output("ifconfig").split("\\n"):
        print line
        if "HWaddr" in line:
            macx=map(lambda x:x.strip(), line.split("HWaddr ")[1].split(":"))
            print macx
            ipv6_6 = "fe%s" % (macx[3],)
            ipv6_7 = "%s%s" % (macx[4],macx[5])
        if "inet6 addr:" in line and "Scope:Global" in line:
            _ipv6 = line.split("/")[0].split(": ")[1]
            _ipv6x = map(lambda i: i.zfill(4), _ipv6.split(":"))
            print _ipv6x
            if _ipv6x[6]==ipv6_6 and _ipv6x[7]==ipv6_7:
                ipv6=_ipv6
                print "found local ipv6 %s" % (ipv6,)
                break
"""
            bind_ipv6_fn = "s.bind((ipv6,0))"
        else:
            afinet = "socket.AF_INET"
            get_ipv6_fn = ""
            bind_ipv6_fn = ""

        if guest.windows: 
            script = script % (get_ipv6_fn, self.UDP_IP, self.UDP_PORT,"c:\\",self.stop_filename(), self.EVENT, afinet, bind_ipv6_fn)
            script_path = "c:\\%s" % self.script_filename()
            guest.xmlrpcWriteFile(script_path, script)
            self.addEventTrigger(guest,script_path)
        else:#posix guest
            script = script % (get_ipv6_fn, self.UDP_IP, self.UDP_PORT,"/",self.stop_filename(), self.EVENT, afinet, bind_ipv6_fn)
            script_path = "/%s" % self.script_filename()
            sf = xenrt.TEC().tempFile()
            file(sf, "w").write(script)
            sftp = guest.sftpClient()
            sftp.copyTo(sf, script_path)
            self.addEventTrigger(guest,script_path)

    def addEventTrigger(self,guest,script_path):
        raise xenrt.XRTError("Unimplemented")

class GuestEvent_VMReady(GuestEvent):
    EVENT = "vmready" #vm is ready to log in
    def addEventTrigger(self,guest,script_path):
        self.log("guest.distro=%s" % guest.distro)
        if "win7" in guest.distro or "win8" in guest.distro:
            script_path="c:\\%s" % self.script_filename()
            add_startup_autoit_path="c:\\add_startup_vmready.au3"
            add_startup_autoit="""
Run(@ComSpec & " /c gpedit.msc", "", @SW_HIDE)
WinWait ("Local Group Policy Editor")
WinActivate ("Local Group Policy Editor")
WinWaitActive ("Local Group Policy Editor")
; local security settings
sleep (30000)
Send ("w")
sleep (30000)
send ("{RIGHT}")
sleep (30000)
send ("si")
sleep (30000)
send ("{TAB}")
sleep (30000)
send ("{ENTER}")
sleep (30000)
send ("{TAB}")
sleep (30000)
send ("d")
sleep (30000)
send ("%s")
sleep (5000)
send ("{ENTER}")
sleep (5000)
send ("{ENTER}")
sleep (2250)
Winclose ("Local Group Policy Editor")
""" % script_path
            if "win8" in guest.distro:
                add_startup_autoit = """
send ("{LWIN}")
sleep (4500)
""" + add_startup_autoit
            guest.xmlrpcWriteFile(add_startup_autoit_path, add_startup_autoit)
            autoit3=guest.installAutoIt()
            #autoit3_src=self.experiment.tc.getPathToDistFile(subdir="support-files/AutoIt3.exe")
            #autoit3_dst="c:\\AutoIt3.exe"
            #guest.xmlrpcSendFile(autoit3_src, autoit3_dst)
            guest.xmlrpcExec("\"%s\" %s" % (autoit3,add_startup_autoit_path))

#HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\Scripts\Startup\0
#        def regadd2(k,v,id="",ty="SZ"):
#            guest.winRegAdd("HKLM", 
#                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Group Policy\\State\\Machine\\Scripts\\Startup\\0\\"+id,
#                k,ty,v)
#        regadd2("GPO_ID","LocalGPO")
#        regadd2("SOM_ID","Local")
#        regadd2("FileSysPath","C:\\Windows\\System32\\GroupPolicy\\Machine")
#        regadd2("DisplayName","Local Group Policy")
#        regadd2("GPOName","Local Group Policy")
#        regadd2("PSScriptOrder",1,ty="DWORD")
#        regadd2("Script",script_path,id="0")
#        regadd2("Parameters","",id="0")
#        regadd2("ExecTime",0,ty="DWORD",id="0")
#        #regadd2("IsPowershell",0,ty="DWORD",id="0")

class GuestEvent_VMLogin(GuestEvent):
    EVENT = "vmlogin" #vm has finished login
    def addEventTrigger(self,guest,script_path):
        if guest.windows:
            #start the script whenever windows login finished
            guest.winRegAdd("HKCU", 
                "software\\microsoft\\windows\\currentversion\\run",
                "guestevent",
                "SZ",
                "python %s" % script_path)
        else: #posix guest
            #call script when guest starts
            # Escape / in script_path
            script_path = script_path.replace('/', '\\/')
            guest.execguest("sed -i 's/exit 0//g' /etc/rc.local")
            guest.execguest("echo 'nohup python %s &' >> /etc/rc.local" % (script_path,))
 
class Measurement(Util):

    #save the experiment running this measurement in order to access context
    def __init__(self,experiment):
        self.experiment = experiment
        self.log_filename = "measurements_" + self.__class__.__name__

    firstline = True
    base_measurement = None

    #log the result of an experiment measurement
    # measurements: a list of produced measurements
    # measurements_header: a list of measurement names
    def log(self,coord,measurements,measurements_header=['MEASUREMENT']):
        if not isinstance(measurements, list): #make sure measurements is a list
            measurements=[measurements]
        if len(measurements)!=len(measurements_header):
            raise xenrt.XRTError("len(measurements)!=len(measurements_header): measurements=%s, measurements_header=%s" % (measurements,measurements_header))
        if self.firstline: # write header before
            header = str(['TIMESTAMP',measurements_header]+self.experiment.getdOrder())
            self.experiment.tc.log(self.log_filename, header)
            self.firstline = False
        timestamp = ("%sZ"%datetime.datetime.utcnow()).replace(" ","T")
        line = str([timestamp,measurements]+coord)
        self.experiment.tc.log(self.log_filename, line)
        xenrt.TEC().logverbose("%s.log: %s" % (self.log_filename,line))
        
    def start(self,coord):
        pass
    def stop(self,coord,guest):
        return None
    def finalize(self):
        pass

# An experiment is a measurement on a subset
# of all possible configurations and loads.
class Experiment(TestSpace):

    RUNS = range(1,6)
    pool_config = PoolConfig()
    host_config = HostConfig(None)
    vm_config = VMConfig(None)
    vm_configs = []
    guests = {}
    hosts = []
    tc = None

    #save the tc running this experiment in order to access xenrt context
    def __init__(self,tc):
        self.tc = tc
        #self.measurement = Measurement(self)
        self.vm_load = VMLoad(self,[]) # no load by default
        self.host_load = HostLoad(self) # no load by default

    #go through each point in the testspace, and raise events
    #when a value of a dimension changes
    def start(self, arglist=None):
        dimensions = self.getDimensions()
        points = self.getPoints(dimensions)

        def call_event(coords):
            #try to call method $dimension in this object passing coords as args
            for d,p1,p2 in coords:
                try:
                    if p1:
                        try:#optional method called when dimension ends
                            getattr(self,("do_"+d+"_end"))(
                                p1, #previous value handled in this dimension
                                points[i] #current point being visited
                            )
                        except AttributeError, e:
                            pass #ignore method if not present
                    if p2:#this method always called for each coord that changed
                        getattr(self,("do_"+d))(
                            p2,       #value in this dimension that needs be handled
                            points[i] #current multi-dimensional point being visited
                        )
                except xenrt.XRTFailure, e:
                    xenrt.TEC().logverbose("Experiment.do_%s(%s):%s" % (d,p2,e))
                    #this coord failed.
                    #log this but continue
                    #print traceback.print_exc()
                    xenrt.TEC().logverbose(traceback.format_exc())
                    raise e
                except xenrt.XRTError, e:
                    xenrt.TEC().logverbose("Experiment.do_%s(%s):%s" % (d,p2,e))
                    #xenrt raised an error
                    #continue???
                    #print traceback.print_exc()
                    xenrt.TEC().logverbose(traceback.format_exc())
                    raise e
                except Exception, e: #ignore everything else
                    xenrt.TEC().logverbose("EXC: Experiment.do_%s(%s):%s" % (d,p2,e))
                    #print traceback.print_exc()
                    xenrt.TEC().logverbose(traceback.format_exc())
                    raise e

        for i in range(len(points)):
            #initial transition should call all events
            if i==0: 
                coords=self.getDiffCoordinates(None,points[i])
                call_event(coords)
            #normal point
            if i>0:
                #coords whose value changed between last and current point
                coords=self.getDiffCoordinates(points[i-1],points[i])
                #coords that are to the left of the coords whose value changed
                coords=self.getLeftMostCoordinates(coords,points[i-1],points[i])
                call_event(coords)
            #final transition should call all events
            if i==len(points)-1: 
                coords=self.getDiffCoordinates(None,points[i])
                coords=map(lambda (d,p1,p2):(d,p2,p1), coords)
                call_event(coords)

    #default Experiment tests all possible combinations
    d_order = pool_config.d_order + host_config.d_order + vm_config.d_order
    def getDimensions(self, filters=None):
        return dict(
            self.pool_config.getDimensions({'HOSTS':(lambda x:x==2)}).items() +
            self.host_config.getDimensions({'RAM':(lambda x:x==64)}).items() +
            self.vm_config.getDimensions(filters).items() +
            self.vm_load.getDimensions(filters).items() +
            self.host_load.getDimensions(filters).items() +
            { 'RUNS': self.RUNS }.items()
        )

class Measurement_elapsedtime(Measurement):
    times = {}
    def start(self,coord):
        #write down initial timestamp just before event
        self.times[''.join(map(str,coord))] = time.time ()
    def stop(self,coord,guest):
        #write down final elapsed time just after event
        now = time.time ()
        diff = now - self.times[''.join(map(str,coord))]
        self.log(coord,diff)
        return diff

class Measurement_vmlogintime(Measurement_elapsedtime):
    pass

class Measurement_vmreadytime(Measurement_elapsedtime):
    pass

class Measurement_vmstarttime(Measurement_elapsedtime):
    pass

class Measurement_pingvm(Measurement):
    def start(self,coord):
        pass
    def stop(self,coord,guest):
        def ping():
            #ping vm 100 times from dom0
            ping_out = guest.host.execdom0("ping -c 100 -n %s" % guest.mainip)
            xenrt.TEC().logverbose("ping_out=%s" % ping_out)
            avg=0.0 #default avg
            for line in ping_out.splitlines():
                n = re.search(".*?, (.*?) received,.*",line)
                if n != None:
                    received = int(n.group(1))
                    if received < 100:
                        raise xenrt.XRTError("measurement_pingvm: ignoring results: received <100 responses: %s" % received) 
                m = re.search("rtt min/avg/max/mdev = (.*?)/(.*?)/(.*?)/(.*?) ms",line)
                if m != None:
                    avg=float(m.group(2))
                    self.log(coord,avg)
            return avg
        return self.tryupto(ping,times=10)

class Measurement_dd(Measurement):
    def start(self,coord):
        pass
    def stop(self,coord,guest):
        def dd(hd):
            xrtstart = xenrt.util.timenow()
            dd_out = guest.xmlrpcExec("echo starttime=%%TIME%%\n"
                                      "C:\\dd.exe if=/dev/zero of=\\\\?\\Device\\Harddisk%s\Partition0 bs=8k count=16384\n" #100MiB
                                      "echo endtime=%%TIME%%\n" % hd,returndata=True,timeout=900)
            xrtend = xenrt.util.timenow()
            xrtdiff = xrtend - xrtstart
            gstart,gend,gdiff = 0,0,-1
            try:
                s=re.search("starttime=(.*?)\n",dd_out).group(1).strip().split(":")
                e=re.search("endtime=(.*?)\n",dd_out).group(1).strip().split(":")
                gstart=float(s[0])*3600+float(s[1])*60+float(s[2])
                gend=float(e[0])*3600+float(e[1])*60+float(e[2])
                gdiff=gend-gstart
                if gdiff<0:
                    gdiff+=86400
            except: pass
            xenrt.TEC().logverbose("dd_out(hd=%s,xrttimediff=%s,guesttimediff=%s)=%s" % (hd,xrtdiff,gdiff,dd_out))
            return gdiff
        t = dd(1)+dd(2)
        #t+= dd(0) #this erases drive c:\
        self.log(coord,t)
        return t

class Measurement_loginvsi(Measurement):
    def start(self,coord):
        pass
    def stop(self,coord,guest):
        pass
    def finalize(self):
        for vm in self.experiment.tc.VMS:
            guest = self.experiment.guests[vm]
            # location of where to store this job's loginvsi results for this guest
            vsilog_dir="%s/%s" % (self.experiment.tc.tec.getLogdir(),guest.getName())
            os.mkdir(vsilog_dir)
            script="(cd %s; smbget -d 9 -Rr 'smb://Administrator:xensource@%s/loginvsi/_VSI_Logfiles/$$$/Results')" % (vsilog_dir,guest.mainip)
            xenrt.TEC().logverbose(script)
            try:
                import commands
                r=commands.getstatusoutput(script)
                if r[0]==0: #ran cmd successfully
                    xenrt.TEC().logverbose(r[1])
                    for root, folders, files in os.walk(vsilog_dir): 
                        for f in files:
                            #add all fetched files to the xenrt log
                            guest.addExtraLogFile(root+f)
                else:
                    xenrt.TEC().logverbose("error while executing smbget: %s" % (r,))
            except Exception, e:
                xenrt.TEC().logverbose("while smbgetting vsi logs: %s" % e)
        killrdplogons="%s %s" % (
            self.experiment.tc.getPathToDistFile(subdir="support-files/killpchildren.sh"),
            os.getpid())
        try:
            import commands
            r=commands.getstatusoutput(killrdplogons)
            if r[0]==0: #ran cmd successfully
                xenrt.TEC().logverbose(r[1])
            else:
                xenrt.TEC().logverbose("error while executing killpchildren: %s" % (r,))
        except Exception, e:
            xenrt.TEC().logverbose("during killpchildren: %s" % e)


    def rdplogon(self):
        xenrt.TEC().logverbose("Starting rdplogon stage...")
        #rdplogon src code at git clone /usr/groups/perfeng/lib/rdplogon-1.7.1 
        rdplogon=self.experiment.tc.getPathToDistFile(subdir="support-files/rdplogon")
        interval=30 #TODO: make this time configurable

        def rdplogon_thread(self, idx):
            vm=self.experiment.tc.VMS[idx]
            guest = self.experiment.guests[vm]
            delay=idx*interval
            xenrt.TEC().logverbose("DEBUG: rdplogon_thread: VM=%s, delay=%s" % (guest.getName(),delay))
            #wait a specific amount of time before starting the vm login, just as loginvsi does
            time.sleep(delay)
            script="%s -u Administrator -p xensource %s" % (rdplogon,guest.mainip)
            xenrt.TEC().logverbose("%s: %s" % (guest.getName(),script))
            try:
                import commands
                r=commands.getstatusoutput(script)
                if r[0]==0: #ran cmd successfully
                    xenrt.TEC().logverbose(r[1])
                else:
                    xenrt.TEC().logverbose("error while executing rdplogon: %s" % (r,))
            except Exception, e:
                xenrt.TEC().logverbose("during rdplogon vsi: %s" % e)

        self.rdplogon_threads = []
        #start all the rdplogon threads
        for idx in range(len(self.experiment.tc.VMS)):
            vm=self.experiment.tc.VMS[idx]
            guest = self.experiment.guests[vm]
            vmt = xenrt.XRTThread(target=rdplogon_thread, args=(self,idx),name=("Thread-rdplogon-%s"%guest.getName()))
            vmt.start()
            self.rdplogon_threads.append(vmt)

        #wait until all rdplogon processes are running
        xenrt.TEC().logverbose("waiting until all rdplogon processes are running")
        vms=len(self.experiment.tc.VMS)
        time.sleep(vms*interval)

        #wait until the last thread has finished first loginvsi loop at least
        xenrt.TEC().logverbose("waiting for last rdplogon thread to finish first loginvsi loop")
        time.sleep(600) #TODO: instead of waiting an ad-hoc time, smbget vm's share every minute or so and probe for the vsimax file

class Measurement_loginvsi41(Measurement_loginvsi):
    def start(self,coord):
        pass
    def stop(self,coord,guest):
        pass
    def finalize(self):
        for vm in self.experiment.tc.VMS:
            guest = self.experiment.guests[vm]
            # location of where to store this job's loginvsi results for this guest
            vsilog_dir="%s/%s" % (self.experiment.tc.tec.getLogdir(),guest.getName())
            os.mkdir(vsilog_dir)
            script="(cd %s; smbget -d 9 -Rr 'smb://Administrator:xensource@%s/VSIShare/_VSI_Logfiles/test/Results')" % (vsilog_dir,guest.mainip)
            xenrt.TEC().logverbose(script)
            try:
                import commands
                r=commands.getstatusoutput(script)
                if r[0]==0: #ran cmd successfully
                    xenrt.TEC().logverbose(r[1])
                    for root, folders, files in os.walk(vsilog_dir): 
                        for f in files:
                            #add all fetched files to the xenrt log
                            guest.addExtraLogFile(root+f)
                else:
                    xenrt.TEC().logverbose("error while executing smbget: %s" % (r,))
            except Exception, e:
                xenrt.TEC().logverbose("while smbgetting vsi logs: %s" % e)
        killrdplogons="%s %s" % (
            self.experiment.tc.getPathToDistFile(subdir="support-files/killpchildren.sh"),
            os.getpid())
        try:
            import commands
            r=commands.getstatusoutput(killrdplogons)
            if r[0]==0: #ran cmd successfully
                xenrt.TEC().logverbose(r[1])
            else:
                xenrt.TEC().logverbose("error while executing killpchildren: %s" % (r,))
        except Exception, e:
            xenrt.TEC().logverbose("during killpchildren: %s" % e)

class Measurement_loginvsi_rds(Measurement_loginvsi):

    #def finalize(self):
        #for vm in self.experiment.tc.VMS:
            #guest = self.experiment.guests[vm]
            #for i in range(self.experiment.loadsPerVM):
                #vsilog_dir="%s/%s/%03d" % (self.experiment.tc.tec.getLogdir(),guest.getName(), i)
            ## location of where to store this job's loginvsi results for this guest
            
                #if not os.path.exists(vsilog_dir):
                    #os.makedirs(vsilog_dir)
                
                #script="(cd %s; smbget -d 9 -Rr 'smb://Administrator:xensource@%s/loginvsi_%03d/_VSI_Logfiles/$$$/Results')" % (vsilog_dir, guest.mainip, i)
                #xenrt.TEC().logverbose(script)
                #try:
                    #import commands
                    #r=commands.getstatusoutput(script)
                    #if r[0]==0: #ran cmd successfully
                        #xenrt.TEC().logverbose(r[1])
                        #for root, folders, files in os.walk(vsilog_dir): 
                            #for f in files:
                                ##add all fetched files to the xenrt log
                                #guest.addExtraLogFile(root+f)
                    #else:
                        #xenrt.TEC().logverbose("error while executing smbget: %s" % (r,))
                #except Exception, e:
                    #xenrt.TEC().logverbose("while smbgetting vsi logs: %s" % e)
        #killrdplogons="%s %s" % (
            #self.experiment.tc.getPathToDistFile(subdir="support-files/killpchildren.sh"),
            #os.getpid())
        #try:
            #import commands
            #r=commands.getstatusoutput(killrdplogons)
            #if r[0]==0: #ran cmd successfully
                #xenrt.TEC().logverbose(r[1])
            #else:
                #xenrt.TEC().logverbose("error while executing killpchildren: %s" % (r,))
        #except Exception, e:
            #xenrt.TEC().logverbose("during killpchildren: %s" % e)

    def rdplogon(self):
        xenrt.TEC().logverbose("Starting rdplogon stage...")
        #rdplogon src code at git clone /usr/groups/perfeng/lib/rdplogon-1.7.1 
        rdplogon=self.experiment.tc.getPathToDistFile(subdir="support-files/rdplogon")
        interval=30 #TODO: make this time configurable

        def rdplogon_thread(self, idx, cid):
            guest = self.experiment.guests[idx]
            delay=cid * interval
            xenrt.TEC().logverbose("DEBUG: rdplogon_thread: VM=%s, user=%03d, delay=%d" % (guest.getName(), cid, delay))
            #wait a specific amount of time before starting the vm login, just as loginvsi does
            xenrt.sleep(delay)
            script="%s -u xenrttester%03d -p Xensource1! %s" % (rdplogon, cid, guest.mainip)
            xenrt.TEC().logverbose("%s, %03d: %s" % (guest.getName(), cid, script))
            try:
                import commands
                r=commands.getstatusoutput(script)
                if r[0]==0: #ran cmd successfully
                    xenrt.TEC().logverbose(r[1])
                else:
                    xenrt.TEC().logverbose("error while executing rdplogon: %s" % (r,))
            except Exception, e:
                xenrt.TEC().logverbose("during rdplogon vsi: %s" % e)

        self.rdplogon_threads = []
        #start all the rdplogon threads
        for idx in self.experiment.tc.VMS:
            guest = self.experiment.guests[idx]
            for i in range(self.experiment.loadsPerVM):
                vmt = xenrt.XRTThread(target=rdplogon_thread, args=(self,idx,i),name=("Thread-rdplogon-%s-%03d" % (guest.getName(), i)))
                vmt.start()
                self.rdplogon_threads.append(vmt)

        #wait until all rdplogon processes are running
        xenrt.TEC().logverbose("waiting until all rdplogon processes are running")
        vms=len(self.experiment.tc.VMS)
        xenrt.sleep(vms*interval*self.experiment.loadsPerVM)

        #wait until the last thread has finished first loginvsi loop at least
        xenrt.TEC().logverbose("waiting for last rdplogon thread to finish first loginvsi loop")
        xenrt.sleep(600) #enough time for the last active session to produce lots of results

class VMConfig_xenpong(VMConfig):
    cdir = "c:\\xenpong"

    # copy xenpong binary to a guest
    # c.f. https://confluence.uk.xensource.com/display/engp/XenPong
    def add(self,guest):
        url="http://10.81.2.194:8080/job/XenPong/lastSuccessfulBuild/artifact/xenpong.tar"
        tar = xenrt.TEC().getFile(url,url)
        rd = xenrt.TEC().tempDir()
        xenrt.util.command("tar -xf %s -C %s" % (tar, rd))
        guest.xmlrpcExec("mkdir %s" % self.cdir)
        guest.xmlrpcSendRecursive(rd, self.cdir)
        guest.xmlrpcExec("dir %s" % self.cdir)
        v1 = guest.winRegLookup("HKLM", "SYSTEM\\ControlSet001\\services\\xenbus\\Parameters", "SupportedClasses")
        v1.append('PONG')
        xenrt.TEC().logverbose("writing v1=%s" % v1)
        guest.winRegAdd("HKLM", "SYSTEM\\ControlSet001\\services\\xenbus\\Parameters", "SupportedClasses", "MULTI_SZ", v1)
        v2 = guest.winRegLookup("HKLM", "SYSTEM\\ControlSet001\\services\\xenbus\\Parameters", "SyntheticClasses")
        v2.append('PONG')
        xenrt.TEC().logverbose("writing v2=%s" % v2)
        guest.winRegAdd("HKLM", "SYSTEM\\ControlSet001\\services\\xenbus\\Parameters", "SyntheticClasses", "MULTI_SZ", v2)

    # enable xenpong in one guest and vmping in dom0
    def post_clone(self,guests):
        g = guests[guests.keys()[0]].cloneVM() # clone first guest in the list
        tardir="xenpong\\x86" # todo: use x64 in 64-bit win vms instead of x86
        g.start()
        g.waitforxmlrpc(600, desc="Daemon", sleeptime=10, reallyImpatient=False)
        g.installCitrixCertificate()
        try: #todo: understand why this line is returning error 1 even though it installs xenpong fine
            g.xmlrpcExec("%s\\%s\\dpinst.exe /sw" % (self.cdir,tardir),timeout=600)
            #g is now permanently listening for vmping from dom0
        except Exception, e:
            xenrt.TEC().logverbose("exception installing xenpong: %s" % e)
        gdomid = g.getDomid()

        #vmping
        url="http://www.uk.xensource.com/~marcusg/harusplutter/vmping/vmping"
        vmping="/usr/bin/vmping"
        g.host.execdom0("wget '%s' -O %s" % (url,vmping))
        g.host.execdom0("chmod 755 %s" % vmping)
        vmpinglog="/tmp/vmping-%s.log" % gdomid
        g.host.execdom0("nohup %s %s >%s 2>&1 &" % (vmping,gdomid,vmpinglog))
        g.host.addExtraLogFile(vmpinglog)

class Experiment_vmstart(Experiment):
# optimize the time necessary to measure the
# space of configurations by going through directions that
# are quicker to explore (eg. increasing number of VMs first, and
# only then reinstalling hosts with different configurations)
    #d_order = ['DOM0RAM','XSVERSIONS','VMS']
    d_order = ['XSVERSIONS','VMS']
    def getDimensions(self, filters=None):
        return dict(
            Experiment.getDimensions(self,{'XSVERSIONS':(lambda x:x=='trunk')}).items()
        )

    def __init__(self,tc):
        Experiment.__init__(self,tc)
        self.measurement_1 = Measurement_elapsedtime(self)

    #this event handles change of values of dimension XSVERSIONS
    #value: contains the value in this dimension that needs be handled
    #coord: contains all the values in all dimensions (current point being visited)
    def do_XSVERSIONS(self, value, coord):
        print "DEBUG: XSVERSIONS value=[%s]" % value
        # 1. reinstall pool with $new_value version of xenserver
        # for each h in self.hosts: self.pool.install_host(...)
        for g in self.guests:
            try:
                self.guests[g].shutdown(force=True)
            except:
                pass
            self.guests[g].uninstall()
        self.guests.clear()

        # 2. reinstall guests in the pool
        # self.guests.append( self.pool.install_guest(...) )

        pool = self.tc.getDefaultPool()
        host = self.tc.getDefaultHost()
        cli = host.getCLIInstance()
        defaultSR = pool.master.lookupDefaultSR()

        xenrt.TEC().logverbose("Installing VM for experiment...")
        vm_name="VM-%s" % xenrt.randomGuestName()
        vm_template = "Windows XP SP3 (32-bit)"
        #templates = host.getTemplate("debian")
        #args=[]
        #args.append("new-name-label=%s" % (vm_name))
        #args.append("sr-uuid=%s" % defaultSR)
        #args.append("template-name=%s" % (vm_template))
        #vm_uuid = cli.execute("vm-install",string.join(args),timeout=3600).strip()
        #template = xenrt.lib.xenserver.getTemplate(self, "other")
        g0 = host.guestFactory()(vm_name, vm_template, host=host)
        g0.createGuestFromTemplate(vm_template, defaultSR)
        for i in self.getDimensions()['VMS']:
            g = g0.cloneVM() #name=("%s-%i" % (vm_name,i)))
            self.guests[i] = g

    #this event handles change of values of dimension DOM0RAM
    def do_DOM0RAM(self, value, coord):
        print "DEBUG: DOM0RAM value=[%s]" % value
        # change dom0 ram and reboot host

    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        print "DEBUG: VMS value=[%s]" % value
        self.measurement_1.start(coord)
        self.guests[value].start()      # start VM index $value
        self.measurement_1.stop(coord)


# the dimensions here are used when running an experiment with VMs
class VMLoad_cpu_loop(VMLoad):
    #valid ranges of each dimension
    VMLOADS = []
    d_order = ['VMLOADS']
    def getDimensions(self, filters=None):
        return { 'VMLOADS':[] }
    def start(self, guest):
        script = "start python -c \"while True: pass\"" 
        if guest.windows:
            #windows disk activity
            xenrt.TEC().logverbose("VMLoad_cpu_loop.start():guest is windows")
            #sysInfo = guest.xmlrpcExec("systeminfo", returndata=True)
            guest.xmlrpcExec(script)
        else:
            #posix disk activity
            xenrt.TEC().logverbose("VMLoad_cpu_loop.start():guest is POSIX")
            guest.execguest(script)

class VMLoad_loginvsi_nordp(VMLoad):
    pyfile = os.path.expanduser("~/xenrt.git/exec/testcases/xenserver/tc/perf/loginvsi/installloginvsitarget.py")
    #pypath = "c:\\"+pyfile
    pypath = "c:\\install-loginvsi-target.py"

    def __init__(self,experiment,params):
        VMLoad.__init__(self,experiment,params)

    def patchStartOption(self, guest, guestid = -1):
        # In case of pool test, some VMs need to be idle while others running loginvsi.
        if len(self.experiment.vmalloc) > 0 and guestid >= 0 and len(self.experiment.loginvsiexclude) > 0:
            for (hostname, vmlist) in self.experiment.vmalloc.items():
                if guestid in vmlist:
                    for i in self.experiment.loginvsiexclude:
                        if hostname == self.experiment.tc.tec.gec.registry.hostGet("RESOURCE_HOST_%u" % i).getName():
                            xenrt.TEC().logverbose("DEBUG: Guest<%s> %s is excluded from login vsi run." %(str(guestid), guest.name))
                            return
                    break

        #start load at login time
        script_path = self.pypath+" runonly" 
        guest.winRegAdd("HKCU",#"HKLM", 
            "software\\microsoft\\windows\\currentversion\\run",
            "vsiloginload",
            "SZ",
            "python %s" % script_path)
        
    def install(self, guest):
        if guest.windows:
            #http://www.loginvsi.com/documentation/v3/performing-tests/workloads
            #VSI,Light,Medium,MediumNoFlash,Heavy,Multimedia,Core,Core + VSITimers,Workload mashup
            workload="Medium" #default loginvsi load
            if len(self.params)>0:
                workload = self.params[0]
            xenrt.TEC().logverbose("loginvsi workload = %s" % workload)
            urlpref = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
            url = "%s/performance/support-files/loginvsi/" % (urlpref)
            loginvsipath = url + "3.VSI35-TargetSetup.zip"
            if self.experiment.distro.startswith("win8") or self.experiment.distro.startswith("ws12"):
                loginvsipath = url + "3.VSI35-TargetSetup_win8.zip"
            pyparams = url + "off2k7.zip " + url + "2.config.xml " + url + "0.dotnet2-setup.exe " + loginvsipath + " " + url + "LoginVSI.lic workload:" + workload
            pycode = file(self.pyfile, "r").read()
            guest.xmlrpcWriteFile(self.pypath, pycode) 
            time.sleep(20)
            script = "python "+self.pypath+" "+pyparams
            guest.xmlrpcExec(script,timeout=7200)

            #if post_clone_guest is required, this will be done in it.
            if not self.experiment.xdsupport:
                self.patchStartOption(guest)
            #the loginvsi locallogon key is not necessary anymore:
            #- it's already being called from install-loginvsi-target.py
            #- it blocks loginvsi sometimes because it fails to find drive g:/ due to a windows race condition during windows login
            #guest.winRegDel("HKCU", 
            #    "software\\microsoft\\windows\\currentversion\\run",
            #    "Locallogon")

    def start(self, guest):
        pass
        #if guest.windows:
        #    script = "start python "+self.pypath+" runonly"
        #    guest.xmlrpcExec(script)

class VMLoad_loginvsi(VMLoad_loginvsi_nordp):
    def __init__(self,experiment,params):
        VMLoad_loginvsi_nordp.__init__(self,experiment,params)
        self.experiment.measurement_loginvsi = globals()["Measurement_loginvsi"](experiment)
        xenrt.TEC().logverbose("created measurement_loginvsi: %s" % self.experiment.measurement_loginvsi)

    def start(self, guest):
        pass

    def patchStartOption(self, guest, guestid = -1):
        #do not login Administrator automatically after boot, leave it to the rdplogon stage
        guest.winRegAdd("HKLM",
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
            "AutoAdminLogon",
            "SZ",
            "0")
        VMLoad_loginvsi_nordp.patchStartOption(self, guest, guestid)

    def install(self, guest):
        #install vsilogin
        VMLoad_loginvsi_nordp.install(self, guest)

class VMLoad_loginvsi41(VMLoad_loginvsi):
    def __init__(self,experiment,params):
        VMLoad_loginvsi_nordp.__init__(self,experiment,params)
        self.experiment.measurement_loginvsi = globals()["Measurement_loginvsi41"](experiment)
        xenrt.TEC().logverbose("created measurement_loginvsi41: %s" % self.experiment.measurement_loginvsi)

    def install(self, guest):
        #install vsilogin41
        vsi = libloginvsi.LoginVSI(guest, guest)
        vsi.installLoginVSI()

class VMLoad_loginvsi_rds(VMLoad_loginvsi):
    pyfile = os.path.expanduser("~/xenrt.git/exec/testcases/xenserver/tc/perf/loginvsi/installloginvsitargetrds.py")
    
    def __init__(self,experiment,params):
        VMLoad.__init__(self,experiment,params)
        self.experiment.measurement_loginvsi = globals()["Measurement_loginvsi_rds"](experiment)
        xenrt.TEC().logverbose("created measurement_loginvsi_rds: %s" % self.experiment.measurement_loginvsi)
    
    def start(self, guest):
        pass
    
    def patchStartOption(self, guest, guestid = -1):
        # start load at login time
        # xmlrpc is not working for RDC/TS connections.
        # RDS requires multiple users which are not Admin.

        # This is required for LoginVSI in RDS env.
        guest.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\Terminal Server", "IAT", "DWORD", 1)
        # This is to disable UAC without prompting UAC window.
        guest.winRegAdd("HKLM", "SOFTWARE\\Microsoft\Windows\\CurrentVersion\\Policies\\System", "EnableLUA", "DWORD", 0)
        au3exe = guest.installAutoIt()
        au3name = "C:\\runasadmin.au3"
        au3contents = """sleep (10000)
send ("{LWIN}")
sleep (1000)
send ("cmd")
sleep (3000)
send ("{APPSKEY}")
sleep (2000)
send ("a")
sleep (3000)
send ("python %s runonly %%USERNAME%%")
sleep (1000)
send ("{ENTER}")
""" % (self.pypath)
        if self.experiment.windowsVersion == self.experiment.VER_WS2012:
            au3contents = """sleep (10000)
send ("{LWIN}")
sleep (1000)
send ("cmd")
sleep (3000)
send ("{APPSKEY}")
sleep (2000)
send ("{RIGHT}")
sleep (500)
send ("{RIGHT}")
sleep (500)
send ("{RIGHT}")
sleep (500)
send ("{ENTER}")
sleep (3000)
send ("python %s runonly %%USERNAME%%")
sleep (1000)
send ("{ENTER}")
""" % (self.pypath)
        guest.xmlrpcWriteFile(au3name, au3contents)
        guest.winRegAdd("HKLM", "software\\microsoft\\windows\\currentversion\\run", "vsiloginload", "SZ", "%s %s" % (au3exe, au3name))

    def install(self, guest):
        #install vsilogin
        VMLoad_loginvsi.install(self, guest)

class HostLoadGatherPerformanceStatus(HostLoad):
    script = "(cd /root; sh ./gather-performance-status.sh %s)"
    def prepare(self,host):
        host.execdom0("(cd /root; wget 'http://www.uk.xensource.com/~marcusg/xenrt/gather-performance-status.sh' -O gather-performance-status.sh)")
    def start(self, host):
        script_start = self.script % "start xensource"
        host.execdom0(script_start)
    def stop(self, host):
        #wait enough time to make sure we have collected enough perf stats
        #of the rrd_updates and xentrace inside the script in dom0
        time.sleep(60*60) #should be at least 5.5mins so that rrds are collected
        script_stop = self.script % "stop"
        out = host.execdom0(script_stop)
        xenrt.TEC().logverbose("%s: %s" % (script_stop,out))
        try: 
            logfile=re.search("include (.*?) in the",out).groups(0)[0]
            host.addExtraLogFile("/root/%s" % logfile) 
        except Exception, e: 
            xenrt.TEC().logverbose("exception gathering performance status:%s" % e)
       
class HostLoadSar(HostLoad):
    def start(self,host):
        #collect sar statistics once a minute instead of once every 10mins
        host.execdom0("sed -i 's/10 /1 /' /etc/cron.d/sysstat") 
    def stop(self,host):
        logfile = "/root/sar.log"
        host.execdom0("sar > %s 2>&1" % logfile)
        host.addExtraLogFile(logfile)

class HostLoadSetDom0Vcpus(HostLoad):
    base_dom0dir = "/root/"
    base_url = "http://www.uk.xensource.com/~marcusg/xenrt/rok-dynamic-dom0-vcpus/"
    script1 = "set_max_dom0_vcpus.sh"
    script_xpin = "exclusive-pin.sh"
    def install(self,host):
        url_script1 = self.base_url + self.script1
        dom0dir_script1 = self.base_dom0dir + self.script1
        self.sendToDom0(url_script1,host,dom0dir_script1)
        host.execdom0("sed -i 's/reboot/#reboot/' %s" % dom0dir_script1)
        host.execdom0(dom0dir_script1) # todo: need to send n.vcpus param, otherwise maxcpus is used
        #host.reboot()
    def start(self,host,pin=""): 
        #pin={'','pin','xpin'}, xpin=exclusive pin of dom0 vcpus.
        if "nopin" in pin:
            #not pinning is the default behavior
            pass
        elif "xpin" in pin:
            dom0dir_script_xpin = self.base_dom0dir + self.script_xpin
            self.sendToDom0(self.base_url+self.script_xpin, host, dom0dir_script_xpin)
            #persistent xpin, so that vms not yet started will use the pin settings as expected
            host.execdom0(dom0dir_script_xpin+" -p")
        elif "pin" in pin:
            n_vcpus_in_dom0=int(host.execdom0("ls -d /sys/devices/system/cpu/cpu* | wc -l").strip())
            for i in range(n_vcpus_in_dom0):
                host.execdom0("xl vcpu-pin 0 %s %s" % (i,i))
        else:
            raise xenrt.XRTFailure("HostLoadSetDom0Vcpus: unknown pin method: %s" % pin)

class HostLoadDynDom0Vcpus(HostLoadSetDom0Vcpus):
    script2 = "balancer"
    def install(self,host):
        url_script1 = self.base_url + self.script1
        url_script2 = self.base_url + self.script2
        dom0dir_script1 = self.base_dom0dir + self.script1
        dom0dir_script2 = self.base_dom0dir + self.script2
        self.sendToDom0(url_script1,host,dom0dir_script1)
        host.execdom0("sed -i 's/reboot/#reboot/' %s" % dom0dir_script1)
        self.sendToDom0(url_script2,host,dom0dir_script2)
        host.execdom0(dom0dir_script1)
        #host.reboot()
    def start(self,host,pin=""):
        dom0dir_script2 = self.base_dom0dir + self.script2
        dom0initialcpunr=pin.replace("dyncpunr=","").split(":")[0] #eg. dyncpunr=12:xpin
        host.execdom0("xl vcpu-set 0 %s" % dom0initialcpunr)
        time.sleep(10)
        #run balancer script in background
        opt=None
        if "nopin" in pin:
            opt="-n"
        elif "xpin" in pin:
            opt="-x"
        elif "pin" in pin:
            opt="-p"
        else:
            raise xenrt.XRTFailure("HostLoadDynDom0Vcpus: unknown pin method: %s" % pin)
        dom0dir_bg_script2 = "nohup %s >/tmp/dynvcpus %s 2>&1 &" % (dom0dir_script2,opt)
        host.execdom0(dom0dir_bg_script2)

#IntelliCache on dom0 ramdisk
class HostConfigIntelliRAM(HostConfig):
    def install(self,host):
        #give dom0 lots of memory (e.g.: 7 GiB) ==> use DOM0RAM for now
        host.execdom0("/opt/xensource/libexec/xen-cmdline --set-xen dom0_mem=%sM" % (self.experiment.dom0ram))
        #change the default ramdisk size to 512MiB
        host.execdom0("/opt/xensource/libexec/xen-cmdline --set-dom0 ramdisk_size=524288")
        # needs reboot now
    def start(self,host):
        #RAID up 10(?) of the ramdisk devices into a single device (i.e. size=5GB):
        host.execdom0("mdadm --create /dev/md1 --level=0 --raid-devices=10 /dev/ram[0-9]")
        #create an SR:
        sr_uuid = host.execdom0("xe sr-create type=ext name-label=dom0ram device-config:device=/dev/md1").strip()
        #Enable IntelliCache on the host, using that SR:
        #host.disable()
        host.execdom0("xe host-disable")
        #host.enableCaching(sruuid)
        host.execdom0("xe host-enable-local-storage-caching sr-uuid=%s" % sr_uuid)  
        #host.enable()
        host.execdom0("xe host-enable")
        #Configure the VM's VDIs to be cached:
        #    #either do something like this, for each VM:
        #        #for vdi in map(guest.getDiskVDIUUID,guest.listDiskDevices()):
        #            #self.host.genParamSet("vdi",vdi,"allow-caching","true")
        #            #self.host.genParamSet("vdi",vdi,"on-boot","reset")
        #    #or do one big bash command for them all, like this:
        #        #for vdi in $(xe vdi-list sr-uuid=$MYRAMSR name-label=win7-local\ 0 --minimal |sed 's/,/ /g'); do echo vdi=$vdi; xe vdi-param-set uuid=$vdi allow-caching=true on-boot=reset; done
        #(Note that you won't be able to start 100VMs because dom0 memory is so large)
        out=host.execdom0('IFS=","; for vm in $(xe vm-list is-control-domain=false --minimal); do for vdi in $(xe vbd-list vm-uuid=$vm device=hda|grep vdi-uuid|awk \'{print $4}\'); do echo "vm=$vm -> vdi=$vdi"; xe vdi-param-set uuid=$vdi allow-caching=true on-boot=reset; done;  done') 
        xenrt.TEC().logverbose("intelliram vdi-set: %s" % out)

class HostConfigIntelliCache(HostConfig):
    def start(self,host,use_ssd=False):
        # If this is a pool, we should enable intelli-cache on all hosts.
        pool = host.pool
        hosts = [host]
        if host.pool:
            hosts = host.pool.getHosts()
            
        for h in hosts:
            #Enable IntelliCache on the host, using that SR:
            cacheDisk = xenrt.TEC().lookup("INTELLICACHE_DISK", None) # must be an ext SR
            xenrt.TEC().logverbose("intellicache disk = %s" % (cacheDisk,))
            h.execdom0("xe host-disable uuid=%s" % h.getMyHostUUID())
            h.enableCaching()
            h.execdom0("xe host-enable uuid=%s" % h.getMyHostUUID())

        out=host.execdom0('IFS=","; for vm in $(xe vm-list is-control-domain=false --minimal); do for vdi in $(xe vbd-list vm-uuid=$vm device=hda|grep vdi-uuid|awk \'{print $4}\') $(xe vbd-list vm-uuid=$vm device=xvda|grep vdi-uuid|awk \'{print $4}\'); do echo "vm=$vm -> vdi=$vdi"; xe vdi-param-set uuid=$vdi allow-caching=true on-boot=reset; done;  done') 
        xenrt.TEC().logverbose("intellicache vdi-set: %s" % out)
    
#in this experiment, vm_start is part of the preparation
#and what is measured are attributes when the vm is running
class Experiment_vmrun(Experiment):
# optimize the time necessary to measure the
# space of configurations by going through directions that
# are quicker to explore (eg. increasing number of VMs first, and
# only then reinstalling hosts with different configurations)
    #d_order = ['DOM0RAM','XSVERSIONS','VMS']
    d_order = ['RUNS','XDSUPPORT','POSTCLONEWORKER','VMTYPES','VMRAM','MACHINES','DOM0RAM','DOM0PARAMS','XENOPSPARAMS','DEFAULTSR','XENPARAMS','DOM0DISKSCHED','QEMUPARAMS','VMPARAMS','VMDISKS','VMVIFS','VMVCPUS','VMLOADS','VMPOSTINSTALL','HOSTVMMAP','LOGINVSIEXCLUDE','XENTRACE','VMCOOLOFF','XSVERSIONS','VMS']

    def getDimensions(self, filters=None):
        #return dict(
            #Experiment.getDimensions(self,{'XSVERSIONS':(lambda x:x in self.tc.XSVERSIONS)}).items()
        #)
        ds = Experiment.getDimensions(self)
        ds['XSVERSIONS'] = self.tc.XSVERSIONS
        ds['MACHINES'] = self.tc.MACHINES
        ds['VMS'] = self.tc.VMS
        ds['RUNS'] = self.tc.RUNS
        ds['VMTYPES'] = self.tc.VMTYPES
        ds['DOM0RAM'] = self.tc.DOM0RAM
        ds['VMPARAMS'] = self.tc.VMPARAMS
        ds['VMRAM'] = self.tc.VMRAM
        ds['DOM0DISKSCHED'] = self.tc.DOM0DISKSCHED
        ds['QEMUPARAMS'] = self.tc.QEMUPARAMS
        ds['DEFAULTSR'] = self.tc.DEFAULTSR
        ds['VMDISKS'] = self.tc.VMDISKS
        ds['VMLOADS'] = self.tc.VMLOADS
        ds['VMVIFS'] = self.tc.VMVIFS
        ds['VMPOSTINSTALL'] =self.tc.VMPOSTINSTALL
        ds['DOM0PARAMS'] = self.tc.DOM0PARAMS
        ds['XENPARAMS'] = self.tc.XENPARAMS
        ds['XENOPSPARAMS'] = self.tc.XENOPSPARAMS
        ds['VMVCPUS'] = self.tc.VMVCPUS
        ds['XDSUPPORT'] = self.tc.XDSUPPORT
        ds['POSTCLONEWORKER'] = self.tc.POSTCLONEWORKER
        ds['HOSTVMMAP'] = self.tc.HOSTVMMAP
        ds['LOGINVSIEXCLUDE'] = self.tc.LOGINVSIEXCLUDE
        ds['VMCOOLOFF'] = self.tc.VMCOOLOFF
        ds['XENTRACE'] = self.tc.XENTRACE
        return ds

    def __init__(self,tc):
        Experiment.__init__(self,tc)
        measure_classname = "Measurement_%s" % tc.MEASURE
        self.measurement_1 = globals()[measure_classname](self)
        #self.measurement_1 = Measurement_elapsedtime(self)
        self.measurement_vmstarttime=Measurement_vmstarttime(self)
        self.measurement_vmreadytime=Measurement_vmreadytime(self)
        self.measurement_loginvsi=None
        self.vm_load_1 = VMLoad(self,[])
        self.host_load_perf_stats = HostLoadGatherPerformanceStatus(self)
        self.host_load_sar = HostLoadSar(self)
        self.host_load_set_dom0_vcpus = HostLoadSetDom0Vcpus(self)
        self.host_load_dyn_dom0_vcpus = HostLoadDynDom0Vcpus(self)
        self.host_config_intelli_ram = HostConfigIntelliRAM(self)
        self.host_config_intelli_cache = HostConfigIntelliCache(self)
        self.guest_events = {
            GuestEvent_VMLogin.EVENT:GuestEvent_VMLogin(self)}
        self.ip_to_guest = {}
        self.vmalloc = {}
        self.vm_configs = []

    #updated in do_VMTYPES()
    distro = "None"
    arch = "x86-32"
    vmparams = []
    vmram = None
    dom0disksched = None
    qemuparams = []
    defaultsr = "ext"
    vmdisks = []
    vmvifs = []
    vmpostinstall = []
    dom0params = []
    xenopsparams = []
    xenparams = ""
    vmcron = ""
    dom0ram = None
    vmvcpus = None
    vm_cores_per_socket = None
    xdsupport = None
    numpostcloneworker = 0
    hostvmmap = []
    loginvsiexclude = []
    vmcooloff = "0"
    xentrace = []
    vlans = 0
    

    #this event handles change of values of dimension XSVERSIONS
    #value: contains the value in this dimension that needs be handled
    #coord: contains all the values in all dimensions (current point being visited)
    def do_XSVERSIONS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS value=[%s]" % value)

        def install_pool():
            #xenrt_params = xml.dom.minidom.parseString("<variables><PRODUCT_VERSION>Boston</PRODUCT_VERSION><INSTALL_SR_TYPE>ext</INSTALL_SR_TYPE><PREPARE_WORKERS>1</PREPARE_WORKERS></variables>")
            #xenrt.TEC().config.parseXMLNode(xenrt_params)
            #xenrt.Config().setVariable("INPUTDIR","%s/usr/groups/xen/carbon/boston/50762"%urlpref)
            #xenrt.TEC().value("_THREAD_LOCAL_INPUTDIR","%s/usr/groups/xen/carbon/boston/50762"%urlpref)
            #xenrt.TEC().config.setVariable("_THREAD_LOCAL_INPUTDIR","%s/usr/groups/xen/carbon/boston/50762"%urlpref)
            #xenrt.TEC().value("OPTION_APPLY_LICENSE",False)
            #xenrt.TEC().value("PRODUCT_VERSION",product_version)
            #version = "%s/usr/groups/xen/carbon/boston/50762" % urlpref
            #self.gec.filemanager.setInputDir(version)
            #print "TEC().config=%s" % xenrt.TEC().config
            

            inputdir=xenrt.TEC().lookup("INPUTDIR",None)
            if inputdir and inputdir[:1]=="/":       # does it exist and is an absolute path?
                url = inputdir   # then use it
            else:                                    # else compute url from xsversion
                urlsuffix = value #.lower() # eg. "trunk-ring0/54990"
                url = "/usr/groups/xen/carbon/%s" % (urlsuffix)
            product_version = (value.split("/")[0]).capitalize() #"Boston"
            url = url.rstrip("/") + "/"
            xenrt.TEC().logverbose("url=%s" % (url,))

            def setInputDir(url):
                xenrt.TEC().logverbose("setting config.variable inputdir...")
                xenrt.TEC().config.setVariable("INPUTDIR",url) #"%s/usr/groups/xen/carbon/boston/50762"%urlpref)
                xenrt.TEC().logverbose("setting inputdir...")
                xenrt.TEC().setInputDir(url) #"%s/usr/groups/xen/carbon/boston/50762"%urlpref)
                xenrt.GEC().filemanager = xenrt.filemanager.getFileManager()
                #sanity check: does this url exist?
                inputdir_ok = xenrt.GEC().filemanager.fileExists(url)
                if inputdir_ok:
                    xenrt.TEC().logverbose("found INPUTDIR at %s" % (url))
                else:
                    xenrt.TEC().logverbose("did not find INPUTDIR at %s" % (url))
                return inputdir_ok

            inputdir_ok = setInputDir(url)
            if not inputdir_ok:
                xenrt.TEC().logverbose("INPUTDIR %s doesn't exist. Trying trunk instead..." % url)
                #try again, using trunk instead of the product name
                ps = product_version.lower().split("-")
                if len(ps) > 1:
                    pv="trunk-%s" % ps[1]
                else:
                    pv="trunk"
                url = url.replace(product_version.lower(),pv) 
                inputdir_ok = setInputDir(url)
                if not inputdir_ok:
                    xenrt.TEC().logverbose("INPUTDIR %s doesn't exist! Giving up..." % url)
                    raise xenrt.XRTError("%s doesn't exist" % url)

            #Xenrt only knows specific product versions
            if not xenrt.TEC().lookup("PRODUCT_VERSION", None):
                xenrt_product_version = product_version.split("-")[0] # ignore suffixes like -ring0, -ring3 etc
                if xenrt_product_version in ["Sanibel"]:#xenrt doesn't know about sanibel
                    xenrt_product_version = "Boston"
                if xenrt_product_version.lower() in ["trunk","venice","clearwater"]:#xenrt doesn't know about trunk
                    xenrt_product_version = "Tampa"
                xenrt.TEC().config.setVariable("PRODUCT_VERSION",xenrt_product_version)
                xenrt.TEC().logverbose("Setting PRODUCT_VERSION=%s" % xenrt_product_version)
            xenrt.TEC().logverbose("Using PRODUCT_VERSION=%s" % xenrt.TEC().lookup("PRODUCT_VERSION", None))

            networkcfg = ""
            for dom0param in self.dom0params:
                if "vlan" in dom0param:
                    # "vlan:X" = create X vlans in the host
                    vlan_params = dom0param.split("=")
                    self.vlans = 0
                    if len(vlan_params) > 1:
                        self.vlans = int(vlan_params[1])
            for i in range(0, self.vlans):
              networkcfg += '<VLAN network="VR%02u" />' % (i+1)

            name_defaultsr = "%ssr" % (self.defaultsr,)
            if self.defaultsr in ["lvm","ext"] or self.defaultsr.startswith("ext:"):
                localsr = self.defaultsr.split(":")[0] #ignore : and anything after it
                sharedsr = ""
            else:
                localsr = "ext"
                options = self.defaultsr.split(":")[1:2] # eg. thin in lvmoiscsi:thin
                if len(options) == 0:
                  options = ""
                else:
                  options = 'options="%s"' % (options[0],)
                sharedsr = '<storage type="%s" name="%s" %s/>' % (self.defaultsr, name_defaultsr, options)

                #in the SCALE cluster, we prefer to use the reserved 10Gb network in NSEC
                hn = xenrt.TEC().lookup("MACHINE", "WARNING: NO MACHINE NAME")
                if "xrtuk-08-" in hn:
                    xenrt.TEC().logverbose("%s: xrtuk-08-* host detected, using NSEC+jumbo network configuration" % hn)
                    sharedsr = '<storage type="%s" name="%s" jumbo="true" network="NSEC"/>' % (self.defaultsr, name_defaultsr)
                    networkcfg = """<NETWORK><PHYSICAL network="NPRI"><NIC /><MANAGEMENT /><VMS />%s</PHYSICAL><PHYSICAL network="NSEC"><NIC /><STORAGE /></PHYSICAL></NETWORK>"""
                else:
                    xenrt.TEC().logverbose("%s: xrtuk-08-* host NOT detected, using default network configuration" % hn)
                    if self.vlans > 0:
                        networkcfg = '<NETWORK><PHYSICAL network="NPRI"><NIC/><MANAGEMENT /><VMS />%s</PHYSICAL></NETWORK>' % (networkcfg,)

            seq = "<pool><host installsr=\"%s\">%s%s</host></pool>" % (localsr,sharedsr, networkcfg)
            #seq = "<pool><host/></pool>"
            xenrt.TEC().logverbose("sequence=%s" % (seq,))
            pool_xmlnode = xml.dom.minidom.parseString(seq)
            prepare = PrepareNode(pool_xmlnode, pool_xmlnode, {}) 
            prepare.runThis()

            if "ram" in self.defaultsr:
                #build an sr on dom0 ram
                pass

            def set_dom0disksched(host,dom0disksched):
                if dom0disksched:
                    host.execdom0("echo %s > /sys/block/sda/queue/scheduler" % dom0disksched)

            def patch_qemu_wrapper(host,qemuparams):
                if "nousb" in qemuparams:
                    #this sed works in xs6.0+ only
                    host.execdom0('sed -i \'s/if is_sdk/qemu_args.remove("-usb")\\n\\tqemu_args.remove("-usbdevice")\\n\\tqemu_args.remove("tablet")\\n\\tif is_sdk/\' /opt/xensource/libexec/qemu-dm-wrapper') 
                    #this sed works in xs5.6sp2- only
                    host.execdom0('sed -i \'s/sys.argv\[2:\]$/sys.argv\[2:\]\\nqemu_args.remove("-usb")\\nqemu_args.remove("-usbdevice")\\nqemu_args.remove("tablet")\\n/\' /opt/xensource/libexec/qemu-dm-wrapper')
                if "nochild" in qemuparams:
                    host.execdom0('sed -i \'s/if is_sdk/qemu_args.append("-priv")\\n\\tif is_sdk/\' /opt/xensource/libexec/qemu-dm-wrapper') 
                    #this sed works in xs5.6sp2- only
                    host.execdom0('sed -i \'s/sys.argv\[2:\]$/sys.argv\[2:\]\\nqemu_args.append("-priv")\\n/\' /opt/xensource/libexec/qemu-dm-wrapper')


            host = self.tc.getDefaultHost()

            if self.vlans > 0:
                #create any extra VLANs in the host
                host.createNetworkTopology(networkcfg)


            host.defaultsr = name_defaultsr # hack: because esx doesn't have a pool class to set up the defaultsr when creating the host via sequence above with 'default' option in <storage>
            if isinstance(host, xenrt.lib.xenserver.Host):
                pool = self.tc.getDefaultPool()
                sr_uuid = host.parseListForUUID("sr-list", "name-label", name_defaultsr)
                xenrt.TEC().logverbose("pool=%s, name_defaultsr='%s', sr_uuid='%s'" % (pool, name_defaultsr, sr_uuid))
                if sr_uuid:
                    if pool:
                        pool.setPoolParam("default-SR", sr_uuid)
                    else:
                        pool_uuid = host.minimalList("pool-list")[0]
                        host.genParamSet("pool", pool_uuid, "default-SR", sr_uuid)

                set_dom0disksched(host,self.dom0disksched) 
                patch_qemu_wrapper(host,self.qemuparams)

                # If given a defaultsr like ext:/dev/sdb, create and ext SR on
                # /dev/sdb and make it the default SR
                if self.defaultsr.startswith("ext:"):
                    device = self.defaultsr[4:]

                    # Remove any existing SRs on the device
                    uuids = host.minimalList("pbd-list",
                                             args="params=sr-uuid "
                                                  "device-config:device=%s" % device)
                    for uuid in uuids:
                        host.forgetSR(uuids[0])

                    diskname = host.execdom0("basename `readlink -f %s`" % device).strip()
                    sr = xenrt.lib.xenserver.EXTStorageRepository(host, 'SR-%s' % diskname)
                    sr.create(device)
                    host.pool.setPoolParam("default-SR", sr.uuid)

            # 1. reinstall pool with $value version of xenserver
            # for each h in self.hosts: self.pool.install_host(...)
            #for g in self.guests:
            #    try:
            #        self.guests[g].shutdown(force=True)
            #    except:
            #        pass
            #    self.guests[g].uninstall()
            #    self.guests.clear()
            reboot = False
            host= self.tc.getDefaultHost()
            if self.xenparams != "":
                xenrt.TEC().logverbose("XSVERSIONS: setting xenparams=%s" % self.xenparams)
                host.execdom0("/opt/xensource/libexec/xen-cmdline --set-xen %s" % self.xenparams)
                reboot=True
            ##change default scheduler in xen
            #xenrt.TEC().logverbose("XSVERSIONS: coord=%s" % str(coord))
            #host = self.tc.getDefaultHost()
            #sched = "credit"
            #if "credit2" in str(coord):
            #    sched = "credit2"
            #schedparam = "sched=%s" % sched
            #xenrt.TEC().logverbose("XSVERSIONS: using sched=%s" % sched) 
            #host.execdom0("sed -i 's/xen.gz /xen.gz %s /g' /boot/extlinux.conf" % schedparam)
            #host.execdom0("/sbin/reboot")
            #time.sleep(450)
            ##double-check we have the expected scheduler passed to xen during boot
            #xencmdline = host.execdom0("xeninfo xen-commandline")
            #if not (schedparam in xencmdline):
            #    raise xenrt.XRTFailure("%s not in xen-commandline %s" % (schedparam,xencmdline))

            dom0cpunr=None
            for dom0param in self.dom0params:
                if "dyncpunr" in dom0param:
                    self.host_load_dyn_dom0_vcpus.install(host)
                    reboot=True
                elif "cpunr" in dom0param: #eg. "cpunr=4:nopin"
                    dom0cpunr=dom0param.replace("cpunr=","").split(":")[0]
                    ##host.execdom0("sed -i 's/dom0_max_vcpus=.* /dom0_max_vcpus=%s /g' /boot/extlinux.conf" % dom0cpunr)
                    ##host.execdom0("sed -i 's/NR_DOMAIN0_VCPUS=.*$/NR_DOMAIN0_VCPUS=%s/' /etc/sysconfig/unplug-vcpus" % dom0cpunr)
                    ###host.execdom0("service unplug-vcpus start")
                    if "all" in dom0cpunr:
                        #use as many vcpus in dom0 as pcpus in the host
                        self.host_load_set_dom0_vcpus.install(host)
                    else:
                        #we have a specific number for vcpus, let's use it
                        host.execdom0('echo "NR_DOMAIN0_VCPUS=%s" > /etc/sysconfig/unplug-vcpus' % dom0cpunr)
                        host.execdom0('/opt/xensource/libexec/xen-cmdline --set-xen dom0_max_vcpus=%s' % dom0cpunr)
                    reboot=True
                elif "intelliram" in dom0param:
                    self.host_config_intelli_ram.install(host)
                    reboot=True
                elif "netbackend" in dom0param:
                    #eg. netbackend bridge, netbackend vswitch
                    netbackend = dom0param.replace("netbackend=","")
                    host.execdom0("xe-switch-network-backend %s" % netbackend)
                    reboot=True
                elif "tunevcpus" in dom0param:
                    tunevcpus = dom0param.replace("tunevcpus=","")
                    try:
                        xenrt.TEC().logverbose("Trying to use /etc/init.d/tune-vcpus...")
                        out=host.execdom0("/etc/init.d/tune-vcpus stop")
                        xenrt.TEC().logverbose(out)
                        out=host.execdom0("/etc/init.d/tune-vcpus start %s" % tunevcpus)
                        xenrt.TEC().logverbose(out)
                    except Exception, e:
                        xenrt.TEC().logverbose("/etc/init.d/tune-vcpus failed: %s" % e)
                        xenrt.TEC().logverbose("Trying to use host-cpu-tune...")
                        out=host.execdom0("%s set %s" % (host._findXenBinary("host-cpu-tune"), tunevcpus))
                        xenrt.TEC().logverbose(out)
                    reboot=True 

            for xenopsparam in self.xenopsparams: 
                if "=" in xenopsparam:
                    xn=xenopsparam.split("=")
                    k=xn[0]
                    v=xn[1]
                    #replace k=v in xenopsd.conf and remove the comments if necessary
                    host.execdom0("sed -i 's/^\(# \)*\(%s\).*/\\2=%s/' /etc/xenopsd.conf" % (k,v))
                    xenrt.TEC().logverbose(host.execdom0("cat /etc/xenopsd.conf"))
                    reboot=True

            if reboot:
                host.reboot()

            #no reboot can occur for these parameters or the change  can or will be lost
            dom0cpuweight=None
            for dom0param in self.dom0params:
                if "cpuweight" in dom0param:
                    dom0cpuweight=dom0param.replace("cpuweight=","")
                    #change default scheduler weight in dom0
                    #dom0uuid = host.getMyDomain0UUID()
                    #hostname = host.i_hostname
                    #xenrt.TEC().logverbose("maxcpuweight: I_HOSTNAME=%s" % hostname)
                    #dom0 = host.guestFactory()("Control domain on host: %s" % hostname, None)
                    #dom0.existing(host)
                    #dom0.paramSet("VCPUs-params:weight", dom0cpuweight) #doesn't work in dom0
                    host.execdom0("/opt/xensource/debug/xenops sched_domain -domid 0 -weight %s" % dom0cpuweight) #alternative: valid until next reboot only
                elif "modprobe" in dom0param:
                    modprobe=dom0param.replace("modprobe=","")
                    out=host.execdom0("/sbin/modprobe %s" % modprobe)
                    xenrt.TEC().logverbose(out)
                    lsmod=host.execdom0("/sbin/lsmod")
                    if modprobe not in lsmod:
                        raise xenrt.XRTFailure("%s not in lsmod: %s" % (modprobe,lsmod))
                elif "service" in dom0param:
                    service=dom0param.replace("service=","")
                    out=host.execdom0("/etc/init.d/%s" % service) # eg. iptables stop
                    xenrt.TEC().logverbose(out)
                elif "sh" in dom0param:
                    sh=dom0param.replace("sh=","")
                    out=host.execdom0(sh) # anything
                    xenrt.TEC().logverbose(out)

            #double-check settings
            for dom0param in self.dom0params:
                if "cpuweight" in dom0param:           
                    dom0sched=host.execdom0("/opt/xensource/debug/xenops sched_get -domid 0").strip() # eg.256 0
                    (w,c)=dom0sched.split() #weight,cap
                    if dom0cpuweight!=w:
                        raise xenrt.XRTFailure("dom0cpuweight: %s!=%s" % (dom0cpuweight,w))
                elif "dyncpunr" in dom0param:
                    pass
                elif "cpunr" in dom0param:
                    _dom0cpunr=host.execdom0("cat /proc/cpuinfo|grep processor|wc -l").strip()
                    if str(dom0cpunr)!=str(_dom0cpunr):
                        raise xenrt.XRTFailure("dom0cpunr: %s!=%s" % (dom0cpunr,_dom0cpunr))

            if isinstance(host, xenrt.lib.xenserver.Host):
                #double-check dom0 ram settings
                dom0_uuid = host.execdom0("xe vm-list is-control-domain=true --minimal").strip()
                mem_static_max = host.execdom0("xe vm-param-get uuid=%s param-name=memory-static-max" % dom0_uuid).strip()
                mem_actual = host.execdom0("xe vm-param-get uuid=%s param-name=memory-actual" % dom0_uuid).strip()
                if mem_static_max != mem_actual:
                    raise xenrt.XRTFailure("dom0 mem_static_max=%s != mem_actual=%s" % (mem_static_max,mem_actual))
                mem_dyn_min = host.execdom0("xe vm-param-get uuid=%s param-name=memory-dynamic-min" % dom0_uuid).strip()
                if mem_static_max != mem_dyn_min:
                    raise xenrt.XRTFailure("dom0 mem_static_max=%s != mem_dyn_min=%s" % (mem_static_max,mem_dyn_min))
                if self.dom0ram == None: #if none provided, use actual
                    self.dom0ram = int(mem_actual) / 1024 / 1024
                xenrt.TEC().logverbose("dom0ram=%s, mem_static_max=%s, mem_actual=%s, mem_dyn_min=%s" % (self.dom0ram,mem_static_max,mem_actual,mem_dyn_min))
                dom0ram_bytes_max = (self.dom0ram+256)*1024*1024
                dom0ram_bytes_min = (self.dom0ram-256)*1024*1024
                if int(mem_actual) < int(dom0ram_bytes_min) or int(mem_actual) > int(dom0ram_bytes_max):
                    raise xenrt.XRTFailure("mem_actual %s not in expected dom0ram range %s -- %s" % (mem_actual,dom0ram_bytes_min,dom0ram_bytes_max))

            #double-check we have the expected scheduler passed to xen during boot
            if self.xenparams != "":
                xencmdline = host.execdom0("xeninfo xen-commandline")
                if not (self.xenparams in xencmdline):
                    raise xenrt.XRTFailure("%s not in xen-commandline %s" % (self.xenparams,xencmdline))

        def install_model_guest():

            pool = self.tc.getDefaultPool()
            host = self.tc.getDefaultHost()
            if pool is not None:
                defaultSR = pool.master.lookupDefaultSR()
            else:
                defaultSR = host.lookupDefaultSR()
            vm_template = host.getTemplate(self.distro, arch=None)

            xenrt.TEC().logverbose("Installing VM for experiment...")
            vm_name="VM-DENSITY-%s" % self.distro #xenrt.randomGuestName()
            host_guests = host.listGuests()

            lib = xenrt.productLib(host=host)
            xenrt.TEC().logverbose("lib=%s" % (lib,))

            #seq = "<vm name=\"%s\"><distro>%s</distro></vm>" % (vm_name,self.distro)
            #guest_xmlnode = xml.dom.minidom.parseString(seq)
            #prepare = PrepareNode(guest_xmlnode, guess_xmlnode, {})
            #prepare.handleVMNode(node, {})

            if vm_name in host_guests:
                #model vm already installed in host: reuse it
                g0 = host.guestFactory()(vm_name, None)
                g0.existing(host)
                xenrt.TEC().logverbose("Found existing guest: %s" % (vm_name))
                #xenrt.TEC().registry.guestPut(vm_name, g0)

                #for ge in self.guest_events.values(): ge.installSendScript(g0)
                #g0.shutdown()

            else:
                #model vm not found in host, install it from scratch
                #g0 = host.guestFactory()(vm_name, vm_template, host=host)
                #g0.createGuestFromTemplate(vm_template, defaultSR)
                use_ipv6 = xenrt.TEC().lookup("USE_GUEST_IPV6", False)

                if self.distro.endswith(".img"):
                    #import vm from image
                    #self.tc.importVMFromRefBase(host, imagefilename, vmname, sruuid, template="NO_TEMPLATE"):
                    #g0 = self.tc.importVMFromRefBase(host, "winxpsp3-vanilla.img", "winxpsp3-vanilla", defaultSR)
                    g0 = self.tc.importVMFromRefBase(host, self.distro, vm_name, defaultSR)
                    for (gp_name,gp_value) in self.vmparams:
                        g0.paramSet(gp_name,gp_value)
                    self.tc.putVMonNetwork(g0)

                elif self.distro[0]=="w": #windows iso image for installation

                    postinstall=[]
                    if "nopvdrivers" not in self.vmpostinstall:
                        postinstall+=['installDrivers']
                    g0=lib.guest.createVM(host,vm_name,self.distro,vifs=self.vmvifs,disks=self.vmdisks,vcpus=self.vmvcpus,corespersocket=self.vm_cores_per_socket,memory=self.vmram,guestparams=self.vmparams,postinstall=postinstall,sr=defaultSR,arch=self.arch,use_ipv6=use_ipv6)
                    #g0.install(host,isoname=xenrt.DEFAULT,distro=self.distro,sr=defaultSR)
                    #g0.check()
                    #g0.installDrivers()
                    ##g0.installTools()

                else: #non-windows iso image for installation
                    postinstall=[]
                    if "convertHVMtoPV" in self.vmpostinstall:
                        postinstall+=['convertHVMtoPV']
                    g0=lib.guest.createVM(host,vm_name,self.distro,vifs=self.vmvifs,disks=self.vmdisks,vcpus=self.vmvcpus,corespersocket=self.vm_cores_per_socket,memory=self.vmram,guestparams=self.vmparams,postinstall=postinstall,sr=defaultSR,arch=self.arch,use_ipv6=use_ipv6)
                    #g0.install(host,isoname=xenrt.DEFAULT,distro=self.distro,sr=defaultSR, repository="cdrom",method="CDROM")

                g0.check()

                if self.distro[0]=="w":
                    g0.xmlrpcExec("netsh firewall set opmode disable")

                if self.measurement_loginvsi:
                    self.guest_events[GuestEvent_VMReady.EVENT] = GuestEvent_VMReady(self)
                for ge in self.guest_events.values(): ge.installSendScript(g0)

                g0.reboot()
                #time for idle VM to flush any post-install pending tasks,
                #we do not want to clone these pending tasks into other VMs
                xenrt.TEC().logverbose("waiting idle VM to flush any post-install pending tasks...")

                if self.distro[0]=="w":
                    for pi in self.vmpostinstall:
                        xenrt.TEC().logverbose("executing vmpostinstall action=%s" % pi)
                        if "xdtailor" in pi:
                            g0.xenDesktopTailor()
                        if "enabledotnet35" in pi and self.distro.startswith('win8'):
                            g0.changeCD(self.distro + ".iso")
                            # sleep to wait until iso is mounted.
                            xenrt.sleep(5, log=False)
                            g0.xmlrpcExec('DISM /Online /Enable-Feature /FeatureName:NetFx3 /All /LimitAccess /Source:d:\sources\sxs')
                        if "pvdrvnorsc" in pi:
                            #disable rsc in the windows pv driver
                            g0.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters", "ReceiverMaximumProtocol", "DWORD",0)
                        if "nowinupd" in pi:
                            #g0.xmlrpcExec('net stop wuauserv')#this raises an error 2 in windows; also, no need for this since we are shutting down the vm next 
                            g0.xmlrpcExec('sc config wuauserv start= disabled')
                        if "nosysbkp" in pi:
                            g0.xmlrpcExec('powershell -Command Disable-ComputerRestore -drive "C:\\"')
                        if "net2flush" in pi:
                            g0.xmlrpcExec('C:\\Windows\\Microsoft.NET\\Framework\\v2.0.50727\\ngen.exe executeQueuedItems')
                        if "net4flush" in pi:
                            g0.xmlrpcExec('c:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\ngen.exe executequeueditems')
                        if "noagent" in pi:
                            g0.xmlrpcExec('sc config xensvc start= disabled')
                            g0.enlightenedDrivers = False
                        if "others" in pi:
                            g0.xmlrpcExec('sc config sppsvc start= disabled')
                            g0.xmlrpcExec('sc config wdisystemhost start= disabled')
                            g0.xmlrpcExec('sc config bits start= disabled')
                            g0.xmlrpcExec('sc config sessionenv start= disabled')
                            g0.xmlrpcExec('sc config sens start= disabled')
                            g0.xmlrpcExec('sc config ikeext start= disabled')
                            g0.xmlrpcExec('sc config certpropsvc start= disabled')
                            g0.xmlrpcExec('sc config iphlpsvc start= disabled')
                            g0.xmlrpcExec('sc config browser start= disabled')
                            g0.xmlrpcExec('sc config lanmanserver start= disabled')
                            g0.xmlrpcExec('sc config lanmanworkstation start= disabled')
                        if "xenpong" in pi:
                            self.vm_configs.append(VMConfig_xenpong(self))
                        if "optimise" == pi:
                            optcmd="optimize-win-guest.cmd"
                            opturl="http://www.uk.xensource.com/~marcusg/xenrt/%s" % optcmd
                            optfile = xenrt.TEC().getFile(opturl,opturl)
                            cpath = "c:\\%s" % optcmd
                            g0.xmlrpcSendFile(optfile, cpath)
                            out=g0.xmlrpcExec(cpath)
                            xenrt.TEC().logverbose("%s output: %s" % (optcmd, out))
                        if "pvsoptimise" == pi:
                            urlperf = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
                            pvsexe = "TargetOSOptimizer.exe"
                            pvsurl = "%s/performance/support-files/%s" % (urlperf, pvsexe)
                            xenrt.TEC().logverbose("pvsoptimise url = %s" % pvsurl)
                            pvsfile = xenrt.TEC().getFile(pvsurl,pvsurl)
                            cpath = "c:\\%s" % pvsexe
                            g0.xmlrpcSendFile(pvsfile, cpath)
                            out=g0.xmlrpcExec("%s /s" % cpath)
                            xenrt.TEC().logverbose("%s output: %s" % (cpath, out))

                try:    
                    self.post_install_model_guest(g0)
                except Exception, e:
                    xenrt.TEC().logverbose("post_install_model_guest: %s" % e)

                # install any necessary vm load to be started later
                self.tryupto(lambda: self.vm_load_1.install(g0),times=3)
                # add any necessary configuration/drivers to be installed/started later
                for vc in self.vm_configs:
                    vc.add(g0)

                time.sleep(30)

                if "postbootstorm" not in self.vmcooloff or "postvmtemplate" in self.vmcooloff:
                    cooloff = float(self.vmcooloff.split(":")[0])
                    xenrt.TEC().logverbose("Waiting %s seconds for the template VM to cool off." % cooloff)
                    time.sleep(cooloff)

                xenrt.TEC().logverbose("Creating model guest is done. Shutting down the VM.")
                g0.shutdown()

                # post-install post-shutdown
                if isinstance(host, xenrt.lib.xenserver.Host):
                    if self.distro[0]=="w":
                        for pi in self.vmpostinstall:
                            xenrt.TEC().logverbose("executing vmpostshutdown action=%s" % pi)
                            if "nousb" in pi:
                                # These commands are mutually exclusive and was changed in build 69008
                                # Old command
                                g0.host.execdom0("xe vm-param-set uuid=%s platform:nousb=true" % g0.uuid)
                                # New command
                                g0.host.execdom0("xe vm-param-set uuid=%s platform:usb=false" % g0.uuid)
                                g0.host.execdom0("xe vm-param-set uuid=%s platform:usb_tablet=false" % g0.uuid)
                            if "noparallel" in pi:
                                g0.host.execdom0("xe vm-param-set uuid=%s platform:parallel=none" % g0.uuid)
                            if "noserial" in pi:
                                g0.host.execdom0("xe vm-param-set uuid=%s other-config:hvm_serial=none" % g0.uuid)
                            if "nocdrom" in pi:
                                vbds = g0.listVBDUUIDs("CD")
                                for vbd in vbds:
                                    g0.host.execdom0("xe vbd-destroy uuid=%s" % vbd)

            return g0

        def post_clone_guest(guests):

            for vc in self.vm_configs:
                vc.post_clone(guests)

            if not self.xdsupport:
                return
            
            vms = guests.items()
            if self.numpostcloneworker and self.numpostcloneworker > 0:
                l = len(vms) / self.numpostcloneworker
                r = len(vms) % self.numpostcloneworker
                tasks = []
                i = 0
                while i < len(vms):
                    tmp = l
                    if (r > 0):
                        tmp += 1
                        r -= 1
                    tasks.append(xenrt.PTask(post_clone_worker, vms[i:i+tmp]))
                    i += tmp
                xenrt.pfarm(tasks)
            else:
                for guest in vms:
                    post_clone_func(guest)
        
        def post_clone_worker(*args):
            for guest in args[0]:
                post_clone_func(guest)

        def post_clone_func(guestitem):
            def createVBDGuest(guest, sr, size, name="Disk"):
                cli = guest.getCLIInstance()
                vdi = string.strip(cli.execute("vdi-create", "name-label=%s type=user sr-uuid=%s virtual-size=%s" % (name, sr, str(size)), compat=False))
                vbd = string.strip(cli.execute("vbd-create", "vdi-uuid=%s vm-uuid=%s device=autodetect" % (vdi, guest.uuid), compat=False))
                return (vdi, vbd)

            (key, guest) = guestitem
            guestturnedon = False
            try:
                if self.xdsupport == "MCS":
                    sr = guest.host.lookupDefaultSR()
                    
                    # Creating identitydisk
                    xenrt.TEC().logverbose("creating identity disk on sr %s" % sr)
                    createVBDGuest(guest, sr, 10 * 2**20, "IdentityDisk")[0]
                    xenrt.TEC().logverbose("creating PVD on sr %s" % sr)
                    createVBDGuest(guest, sr, 10 * 2**30, "PVD")

                    guest.start()
                    guestturnedon = True
                    guest.waitforxmlrpc(300, desc="Daemon", sleeptime=1, reallyImpatient=False)
                    diskpartScrName = "C:\\dp.txt"
                    diskpartScr = """
SELECT DISK 1
CREATE PARTITION PRIMARY
ASSIGN LETTER=E
SELECT DISK 2
CREATE PARTITION PRIMARY
ASSIGN LETTER=F
EXIT
"""
                    prepareMCSDisksName = "C:\\mcs.bat"
                    # using ping to give some sleep.
                    prepareMCSDisks = """
diskpart /s %s
PING 1.1.1.1 -n 5 > NUL
FORMAT E: /Q /FS:NTFS /Y
PING 1.1.1.1 -n 5 > NUL
FORMAT F: /Q /FS:NTFS /Y
PING 1.1.1.1 -n 5 > NUL
""" % (diskpartScrName)
                    # Attach disks and format them
                    guest.xmlrpcWriteFile(diskpartScrName, diskpartScr)
                    guest.xmlrpcWriteFile(prepareMCSDisksName, prepareMCSDisks)
                    guest.xmlrpcExec(prepareMCSDisksName)

                    # Creating general identity file.
                    stem = "E:\\CTXSOSID.INI"
                    password = "password123"
                    stemText = ("""[Identity]
HostName=%s
MachinePassword=%s
""" % (guest.name, password)).replace("\n", "\\r\\n")
                    guest.xmlrpcWriteFile(stem, stemText)

                elif self.xdsupport == "PVS":
                    pass
            except Exception,e:
                xenrt.TEC().logverbose("post_clone_func() for %s: %s" % (guest.name, e))
            finally:
                # Set loginvsi test enabled.
                if guest.windows and "loginvsi" in self.vm_load_1.__class__.__name__:
                    if not guestturnedon:
                        guest.start()
                        guestturnedon = True

                    self.vm_load_1.patchStartOption(guest, key)

                if guestturnedon:
                    guest.shutdown()
            return
        
        def get_install_SRs():
            pool = self.tc.getDefaultPool()
            host = self.tc.getDefaultHost()
            hosts = [host]
            if pool is not None:
                host = pool.master
                hosts = pool.getHosts()
               
            default_sr_uuid = host.lookupDefaultSR()
            if self.defaultsr is None: # We'll use type of default SR
                self.defaultsr = host.getSRParam(uuid=default_sr_uuid, param='type')
            
            def get_install_SR_for_host(h):
                SRs = [sr for sr in h.getSRs() if self.defaultsr == h.getSRParam(uuid=sr, param='type')]
                if len(SRs) == 0:
                    xenrt.TEC().logverbose("For host %s there are no SRs of type %s" % (h.getName(), self.defaultsr))
                    raise xenrt.XRTError("host doesn't have an %s SR" % self.defaultsr)
                if default_sr_uuid in SRs:
                    return default_sr_uuid
                else:
                    return SRs[0]
                
            return dict([(h.getName(), get_install_SR_for_host(h)) for h in hosts])

        def get_host_name_by_id(h):
            return self.tc.tec.gec.registry.hostGet("RESOURCE_HOST_%u" % h).getName()
        
        def install_guests_in_a_pool(g0):
            pool = self.tc.getDefaultPool()
            host = self.tc.getDefaultHost()
            if pool is not None:
                host = pool.master

            disks = g0.listDiskDevices()
            disks.sort()
            orig_sr_uuid = host.getVDISR(g0.getDiskVDIUUID(disks[0]))
            
            default_sr_uuid = host.lookupDefaultSR()
            if orig_sr_uuid != default_sr_uuid:
                xenrt.TEC().logverbose("Model guest %s is not installed on default SR" % g0.getName())

            host_SRs = get_install_SRs()
            
            def clone_VMs(g0, g_list, h_name):
                for i in g_list:
                    g = g0.cloneVM() #name=("%s-%i" % (vm_name,i)))
                    #xenrt.TEC().registry.guestPut(g.getName(),g)
                    self.guests[i] = g
                    if h_name: # We've to bring up VM on the given host
                        self.host_vm_map[h_name].add(i)
            
            def allocate_guests_to_hosts():
                all_vms = self.getDimensions()['VMS']
                alloc = {}
                for (h, n) in self.hostvmmap:
                    h_name = get_host_name_by_id(h)
                    alloc[h_name] = all_vms[:n]  # take n VMs
                    all_vms = all_vms[n:] # drop n VMs
                return alloc
            
            all_vms = set(self.getDimensions()['VMS'])
            allocated_vms = set()
            self.vmalloc = allocate_guests_to_hosts()
            for (h_name, g_list) in self.vmalloc.items():
                if len(g_list) == 0: continue
                
                sr_uuid = host_SRs[h_name]
                if sr_uuid == orig_sr_uuid: # We can simply clone
                    clone_VMs(g0, g_list, h_name)
                else:
                    g1 = g0.copyVM(sruuid=sr_uuid)
                    self.guests[g_list[0]] = g1
                    self.host_vm_map[h_name].add(g_list[0])
                    clone_VMs(g1, g_list[1:], h_name) 
                allocated_vms.update(set(g_list))

            # Some VMs may not have a specified host to start on (hostvmmap could be [])
            clone_VMs(g0, (all_vms - allocated_vms), "")
            return

        def install_guests_in_a_host(g0):
            if self.vlans > 0:
                # xenserver-specific vlan code
                cli = g0.host.getCLIInstance()
                s = cli.execute("pif-list", "params=network-uuid,VLAN")
                xenrt.TEC().logverbose("pif-list=%s" % (s,))
                all_network_uuids = map(lambda kv:(kv[0].split(":")[1].strip(),kv[1].split(":")[1].strip()), filter(lambda el:len(el)>1, map(lambda vs:vs.split("\n"),s.split("\n\n\n"))))
                xenrt.TEC().logverbose("all_network_uuids=%s" % (all_network_uuids,))

                # only those network uuids with a vlan
                network_uuids = map(lambda (v,n):n, filter(lambda (vlan,network_uuid): vlan<>"-1", all_network_uuids))
                xenrt.TEC().logverbose("network_uuids with vlan=%s" % (network_uuids,))

            # We'll do the installation on default SR
            for i in self.getDimensions()['VMS']:
                g = g0.cloneVM() #name=("%s-%i" % (vm_name,i)))
                #xenrt.TEC().registry.guestPut(g.getName(),g)
                self.guests[i] = g
                if self.vlans > 0:
                    # assign networks to clones in round-robin fashion
                    network_uuid = network_uuids[ i % len(network_uuids) ]
                    g.removeAllVIFs()
                    g.createVIF(bridge=network_uuid)

            return

        def install_guests():
            
            for ge in self.guest_events.values(): ge.reset()
            self.xapi_event.reset()
            g0 = self.tryupto(install_model_guest,times=3)
            
            # This might be a pool.
            pool = self.tc.getDefaultPool()
            host = self.tc.getDefaultHost()
            hosts = [host]
            if pool is not None:
                hosts = pool.getHosts()
                host = pool.master
            
            # self.host_vm_map is populated while installing (cloning) VMs
            # We refer to it when starting VMs to decide on which host the VM should start
            if len(self.hostvmmap) == 0:
                # This value could be empty. In that case we'll let xapi choose the host
                self.host_vm_map = dict()
            else:
                self.host_vm_map = dict([(get_host_name_by_id(h), set()) 
                                         for (h,n) in self.hostvmmap])
                
            if len(hosts) > 1: # This must be pool
                install_guests_in_a_pool(g0)
            else:
                install_guests_in_a_host(g0)

            # Execute post clone procedure that cannot be handled during clone procedure.
            post_clone_guest(self.guests)

            return

        def existingHost(hostname):
            """Return a host object for an existing host."""
            host = None
            # A host is by definition a physical machine.
            machine = xenrt.PhysicalHost(hostname)
            # Start logging the serial console.
            self.tc.tec.gec.startLogger(machine)
            # Start at the top of the inheritance tree.
            place = xenrt.GenericHost(machine)
        
            place.findPassword()
            place.checkVersion()
            host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
            place.populateSubclass(host)
        
            host.existing()
            
            return host

        def existingPool(mastername):
            """Return a pool object for an existing pool"""
            master = existingHost(mastername)
            pool = xenrt.lib.xenserver.poolFactory(master.productVersion)(master)
            xenrt.TEC().logverbose("Created pool object: %s" % (pool))
            try:
                pool.existing()
            except:
                traceback.print_exc(file=sys.stdout) 
                raise 
            return (pool,master)

        if self.tc.EXISTINGHOST: 
            # The "prepare" in sequence file might have installed the host/pool.
            # if so, we'll give preference to host/pool from the registry.
            master = self.tc.tec.gec.registry.hostGet("RESOURCE_HOST_0")
            pool = self.tc.tec.gec.registry.poolGet("RESOURCE_POOL_0")
            if pool is not None:
                master = pool.master
            if master is not None:
                self.tc.EXISTINGHOST = master.getName()
            
            xenrt.TEC().logverbose("======== USING EXISTING HOST %s ========" % self.tc.EXISTINGHOST)
            hostname = self.tc.EXISTINGHOST
            (pool,master) = existingPool(hostname)
            xenrt.TEC().logverbose("pool,master=%s,%s" % (pool,master))
            self.tc.tec.gec.registry.poolPut("RESOURCE_POOL_0", pool)
            self.tc.tec.gec.registry.hostPut("RESOURCE_HOST_0", master)
            self.tc.tec.gec.registry.hostPut(hostname, master)
        else: 
            self.tryupto(install_pool)

        self.xapi_event = APIEvent(self)
        install_guests()

        host = self.tc.getDefaultHost()
        #start host loads just before the guests start up
        for dom0param in self.dom0params:
            if "dyncpunr" in dom0param:
                self.host_load_dyn_dom0_vcpus.start(host,pin=dom0param)
            elif "cpunr" in dom0param:
                self.host_load_set_dom0_vcpus.start(host,pin=dom0param)
            elif "intelliram" in dom0param:
                self.host_config_intelli_ram.start(host)
            elif "intellicache" in dom0param:
                self.host_config_intelli_cache.start(host)
            elif "intellicachessd" in dom0param:
                self.host_config_intelli_cache.start(host, use_ssd=True)
        #print the vcpu state in dom0
        self.print_vcpu_list(host)

        #wait until all vms are 'running' (for some definition of 'running')
        #wait(60) #please do proper wait for vm events
        if self.tc.PERFSTATS:
            #start gather_performance_status.sh
            self.host_load_perf_stats.prepare(host)
            self.host_load_perf_stats.start(host)
            self.host_load_sar.start(host)

    def post_install_model_guest(self,guest):
        pass

    def print_vcpu_list(self,host):
        try:
            xl=host.execdom0("xl vcpu-list")
            xenrt.TEC().logverbose("xl vcpu-list ==> %s" % xl)
        except:
            pass

    def do_XSVERSIONS_end(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS_end value=[%s]" % value)
        host = self.tc.getDefaultHost()
        if self.tc.PERFSTATS:
            #stop gather_performance_status.sh
            self.host_load_perf_stats.stop(host)
            self.host_load_sar.stop(host)

        #collect loginvsi measurements if available
        xenrt.TEC().logverbose("finalize: measurement_loginvsi: %s" % (self.measurement_loginvsi,))
        if self.measurement_loginvsi: 
            self.measurement_loginvsi.finalize()

        #print the vcpu state in dom0
        self.print_vcpu_list(host)

    def do_VMLOADS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMLOADS value=[%s]" % value)
        vmload_args = value.split(":")
        vmload_classname = "VMLoad_%s" % vmload_args[0]
        self.vm_load_1 = globals()[vmload_classname](self,vmload_args[1:])

    def do_DOM0DISKSCHED(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DOM0DISKSCHED value=[%s]" % value)
        self.dom0disksched = value

    def do_QEMUPARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: QEMUPARAMS value=[%s]" % value)
        self.qemuparams = value

    def do_DEFAULTSR(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DEFAULTSR value=[%s]" % value)
        self.defaultsr = value

    def do_VMTYPES(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMTYPES value=[%s]" % value)
        values = value.split(":")  # eg. win7sp1:x86-64
        self.distro = values[0]
        if "x64" in self.distro:
            self.arch="x86-64"
        if len(values) > 1:
            self.arch=values[1]
        xenrt.TEC().logverbose("DEBUG: distro,arch=[%s],[%s]" % (self.distro, self.arch))

    def do_VMPARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMPARAMS value=[%s]" % str(value))
        self.vmparams = value

    def do_VMPOSTINSTALL(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMPOSTINSTALL value=[%s]" % str(value))
        self.vmpostinstall = value

    def do_VMDISKS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMDISKS value=[%s]" % str(value))
        self.vmdisks = value

    def do_VMVIFS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMVIFS value=[%s]" % str(value))
        self.vmvifs = value

    def do_VMVCPUS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMVCPUS value=[%s]" % str(value))
        xs = value.split(":")
        vcpus_per_vm = int(xs[0])
        if len(xs)>1:
            vm_cores_per_socket = int(xs[1])
        else:
            vm_cores_per_socket = None
        self.vmvcpus = vcpus_per_vm
        self.vm_cores_per_socket = vm_cores_per_socket

    def do_VMRAM(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMRAM value=[%s]" % str(value))
        self.vmram = value

    def do_VMCOOLOFF(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMCOOLOFF value=[%s]" % str(value))
        self.vmcooloff = value

    def do_XDSUPPORT(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XDSUPPORT value=[%s]" % str(value))
        self.xdsupport = value

    def do_LOGINVSIEXCLUDE(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: LOGINVSIEXCLUDE value=[%s]" % str(value))
        self.loginvsiexclude = value

    def do_POSTCLONEWORKER(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: POSTCLONEWORKER value=[%s]" % str(value))
        self.numpostcloneworker = value

    def do_HOSTVMMAP(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: HOSTVMMAP value=[%s]" % str(value))
        self.hostvmmap = value # [(HOST_ID, NUM_VMs)]

    def do_MACHINES(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: MACHINES value=[%s]" % value)

        if isinstance(value, list):
            #value contains more than one hostname
            n = len(value)
            for i in range(n):
                xenrt.TEC().config.setVariable("RESOURCE_HOST_%u" % i,value[i])
        else:
            n = 1
            xenrt.TEC().config.setVariable("RESOURCE_HOST_0",value)

        #go through each resource hosts and loads config
        config = xenrt.TEC().config
        for i in range(n):
            hostname = config.lookup("RESOURCE_HOST_%u" % (i), None)
            if not hostname: break
            hcfbase = config.lookup("MACHINE_CONFIGS", None)
            if hcfbase:
                hcf = "%s/%s.xml" % (hcfbase, hostname)
                if os.path.exists(hcf):
                    config.readFromFile(hcf, path=["HOST_CONFIGS", hostname])

            powerctltype = xenrt.TEC().lookupHost(hostname,"POWER_CONTROL","---")
            xenrt.TEC().logverbose("powerctltype for %s=%s" % (hostname,powerctltype))
            #xenrt.TEC().config.setVariable("POWER_CONTROL","APCPDU")        

    def do_RUNS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: RUNS value=[%s]" % value)

    #this event handles change of values of dimension DOM0RAM
    def do_DOM0RAM(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DOM0RAM value=[%s]" % value)
        # change dom0 ram in MB and reboot host
        xenrt.TEC().config.setVariable("OPTION_DOM0_MEM", ("%sM,max:%sM" % (value, value)))
        self.dom0ram=value

    def do_DOM0PARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DOM0PARAMS value=[%s]" % value)
        self.dom0params=value
        #d0memsettarget = 'nod0memtarget' not in self.dom0params
        #xenrt.TEC().logverbose("OPT_DOM0MEM_SET_TARGET=%s" % d0memsettarget)
        #xenrt.TEC().config.setVariable("OPT_DOM0MEM_SET_TARGET", d0memsettarget)

    def do_XENOPSPARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XENOPSPARAMS value=[%s]" % value)
        self.xenopsparams=value

    def do_XENPARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XENPARAMS value=[%s]" % value)
        self.xenparams=value

    def do_XENTRACE(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XENTRACE value=[%s]" % value)
        self.xentrace=value

    def do_COLLECT_XENTRACE(self, value):
        filename = "/root/xentrace-vm-%d" % value
        gfilename = "%s.gz" % filename
        guest = self.guests[value]
        guest.host.execdom0("nohup sh -c 'xentrace -D -e 0x0002f000 -T 5 %s && nice -n 2 gzip %s' > /dev/null 2>&1 < /dev/null &" % (filename, filename))
        guest.host.addExtraLogFile(gfilename)

    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMS value=[%s]" % str(value))
        #TODO: add a is_initial_value parameter sent by the framework,
        #so that it is not necessary to guess what the first possible value is
        #in the checks below

        if value in self.xentrace:
            self.do_COLLECT_XENTRACE(value)

        if value == 1:
            self.do_VMS_ERR_load_failed = False
        if self.do_VMS_ERR_load_failed:
            return #ignore this dimension

        guest = self.guests[value]

        def get_vm_host_name(i):
            h_name = ""
            for (h, g_l) in self.host_vm_map.items():
                if i in g_l:
                    h_name = h
                    break
            return h_name
            
        #vm is already running, do some load on it and measure

        #only measure at the initial value or if the base measurement
        #still exists to compare against
        if value == self.tc.VMS[:1][0] or self.measurement_1.base_measurement:

            self.measurement_1.start(coord)
            self.measurement_vmstarttime.start(coord)
            self.measurement_vmreadytime.start(coord)

            def vmstart_thread(self, guest, coord):
                #cli = guest.host.getCLIInstance()
                #do not use guest.start(), it contains several time.sleep that we don't want
                #Should the vm-start on a specific host ?

                if isinstance(guest.host, xenrt.lib.xenserver.Host):
                    #xenserver
                    if get_vm_host_name(value):
                        guest.host.execdom0("xe vm-start uuid=%s on=%s" % (guest.uuid, get_vm_host_name(value)),
                                            timeout=900+30*self.tc.THRESHOLD)
                    else:
                        guest.host.execdom0("xe vm-start uuid=%s" % guest.uuid, timeout=900+30*self.tc.THRESHOLD)

                else:
                    #not xenserver
                    guest.lifecycleOperation("vm-start")

                self.xapi_event.waitFor(guest.uuid,"power_state","Running")

                #vmstart finished
                result = self.measurement_vmstarttime.stop(coord,guest)

            vmstart_t = xenrt.XRTThread(target=vmstart_thread, args=(self,guest,coord),name=("Thread-vmstart-%s"%value))
            vmstart_t.start()

            #we are not waiting for vmstart to finish, continue until vmlogin finished

            vifname, bridge, mac, c = guest.vifs[0]
            if not self.measurement_1.base_measurement:
                timeout = 600
            else:
                timeout = 600 + self.measurement_1.base_measurement * self.tc.THRESHOLD
            if guest.use_ipv6:
                guest.mainip = guest.getIPv6AutoConfAddress(vifname)
                #normalise ipv6 with 0s
                guest.mainip = ":".join(map(lambda i: i.zfill(4), guest.mainip.split(":")))
            else:
                guest.mainip = guest.getHost().arpwatch(bridge, mac, timeout=timeout)
            self.ip_to_guest[guest.mainip] = guest
            #guest.waitforxmlrpc(300, desc="Daemon", sleeptime=1, reallyImpatient=False)

            if (self.measurement_loginvsi):
                received_event = self.guest_events[GuestEvent_VMReady.EVENT].receive(guest,timeout)
                #vm is ready to log in
                if not received_event:
                    msg = "DEBUG: =======> did not receive %s for vm %s (ip %s)" % (GuestEvent_VMReady.EVENT,guest,guest.mainip)
                    raise xenrt.XRTFailure(msg)
                else:
                    result = self.measurement_vmreadytime.stop(coord,guest)
            else:
                received_event = self.guest_events[GuestEvent_VMLogin.EVENT].receive(guest,timeout)
                #vm has finished logging in
                if not received_event:
                    msg = "DEBUG: =======> did not receive %s for vm %s (ip %s)" % (GuestEvent_VMLogin.EVENT,guest,guest.mainip)
                    raise xenrt.XRTFailure(msg)
                else:
                    result = self.measurement_1.stop(coord,guest)

            #run vm load on vm $value without stopping, eg. cpu loop
            try:
                self.tryupto(lambda: self.vm_load_1.start(guest),times=3)
                #self.vm_load_1.stop(guest)
                pass
            except: #flag this important problem
                self.do_VMS_ERR_load_failed = True
                xenrt.TEC().logverbose("======> VM load failed to start for VM %s! Aborting this sequence of VMs!" % value)
                raise #re-raise the exception

            #vmstart_t.join(3600)

            #store the initial base measurement value to compare against later
            #when detecting if latest measurement is too different
            if value == self.tc.VMS[:1][0]:
                self.measurement_1.base_measurement = result
                xenrt.TEC().logverbose("Base measurement: %s" % (self.measurement_1.base_measurement))
            else:
                #is the current measurement over the maximum time threshold of the experiment?
                if result > 20000 and result > self.tc.THRESHOLD * self.measurement_1.base_measurement:
                    #stop measuring remaining VMs until base measurement is made again
                    self.measurement_1.base_measurement = None
                    xenrt.TEC().logverbose("DEBUG: ==============> VMS: measurement threshold reached: stopping measuring remaining VMs until base measurement is made again")


#this class adds an threaded wrapper around do_VMS, where each thread starts
#after a defined amount of time independently if the previous VM has finished booting
class Experiment_vmrun_cron(Experiment_vmrun):

    d_order = Experiment_vmrun.d_order[:1]+['VMCRON']+Experiment_vmrun.d_order[1:]
    def getDimensions(self, filters=None):
        ds = Experiment_vmrun.getDimensions(self)
        ds['VMCRON']=self.tc.VMCRON
        return ds

    def do_VMCRON(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMCRON value=[%s]" % str(value))
        self.vmcron = value

    vmstart_threads = []

    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        def wait_wrap(self, period, value, coord):
            delay=period*value 
            xenrt.TEC().logverbose("DEBUG: vmrun_cron: delay=%s, VMS value=[%s]" % (delay,str(value)))
            time.sleep(delay)
            Experiment_vmrun.do_VMS(self, value, coord)
            xenrt.TEC().logverbose("DEBUG: vmrun_cron_end: delay=%s, VMS value=[%s]" % (delay,str(value)))

        # self.vmcron ==> "period[:optional number of vms window][:waitvmstart]"
        vmcron_params = self.vmcron.split(":")
        period=int(vmcron_params[0])
        window=0
        if len(vmcron_params)>1:
            window=int(vmcron_params[1])
        waitvmstart="waitvmstart" in self.vmcron

        xenrt.TEC().logverbose("DEBUG: vmrun_cron: period=%s, VMS value=[%s]" % (period,str(value)))
        if value == self.tc.VMS[:1][0]: #is it the first vm?
            #we need to wait base_measurement from the 1st vm before allowing the other vms to start in parallel
            Experiment_vmrun.do_VMS(self, value, coord)
        else:
            vmt = xenrt.XRTThread(target=wait_wrap, args=(self,period,value,coord),name=("Thread-VM-%s"%value))
 
            # wait for the vms in the vms window to finish booting
            #threads_to_wait = []
            #if window>0: threads_to_wait = self.vmstart_threads[(-window):]
            #xenrt.TEC().logverbose("DEBUG: vmrun_cron: VM=%s: waiting for %s threads: %s" % (value,len(threads_to_wait),threads_to_wait))
            #for tw in threads_to_wait:
            #    xenrt.TEC().logverbose("DEBUG: vmrun_cron: VM=%s: waiting thread %s" % (value,tw))
            #    tw.join(period * value)

            # block until less than <window> vms are in the running state
            if window>0:
                xenrt.TEC().logverbose("DEBUG: vmcron: waiting for at most %s VMs starting..." % window)
                n_running=window
                last_n_running=0
                while n_running >= window:
                    n_running=0
                    for t in self.vmstart_threads:
                        if waitvmstart:# wait until vm thread has reached power_state=running
                            tname = t.getName()
                            vm = int(tname.split("-")[2])
                            guest = self.guests[vm]
                            current_ops=[]
                            if guest.uuid in self.xapi_event.events:
                                if "current_operations" in self.xapi_event.events[guest.uuid]:
                                    current_ops = self.xapi_event.events[guest.uuid]["current_operations"].values()
                            if t.isAlive() and self.xapi_event.hasEvent(guest.uuid,"power_state","Halted"): # and ("start" in current_ops):
                                #vm state is after vm-start but before power_state is running (ie. as yellow icon in xencenter)
                                n_running+=1
                        else:#default: wait until vm thread has finished    
                            if t.isAlive():
                                n_running+=1
                    if last_n_running != n_running:
                        xenrt.TEC().logverbose("DEBUG: vmcron: n. other VMs starting=%s" % n_running)
                        last_n_running = n_running 
                    time.sleep(0.1)

            vmt.daemon = True # kills this thread automatically if main thread exits
            vmt.start()
            self.vmstart_threads.append(vmt)

    #def do_VMS_end(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMS_end value=[%s]" % value)
        xenrt.TEC().logverbose("DEBUG: VMS_end self.tc.VMS[-1:][0]=[%s]" % self.tc.VMS[-1:][0])
        if value==self.tc.VMS[-1:][0]: #is it the last VM?

            xenrt.TEC().logverbose("DEBUG: VMS_end value=[%s]: waiting on all threads" % value)
            #wait on all existing vmstart threads
            timeout = period * value
            if timeout<3600: timeout=3600
            for vmt in self.vmstart_threads:
                vmt.join(timeout)
            self.vmstart_threads = []

            if "postbootstorm" in self.vmcooloff:
                cooloff = float(self.vmcooloff.split(":")[0])
                xenrt.TEC().logverbose("Waiting %s seconds after vm bootstorm for vms to cool off." % cooloff)
                time.sleep(cooloff)

            #login vms manually when using 2-stage loginvsi
            xenrt.TEC().logverbose("DEBUG: vm_load_1.__class__.__name__ = %s" % self.vm_load_1.__class__.__name__)
            if "VMLoad_loginvsi" in self.vm_load_1.__class__.__name__: #is it a loginvsi load?
                xenrt.TEC().logverbose("rdplogon: measurement_loginvsi: %s" % (self.measurement_loginvsi,))
                if self.measurement_loginvsi:
                    self.measurement_loginvsi.rdplogon()


class Experiment_vmrun_rds(Experiment_vmrun_cron):
    
    d_order = ['LOADSPERVM'] + Experiment_vmrun_cron.d_order

    loadsPerVM = 0

    VER_WS2008 = 0
    VER_WS2008R2 = 1
    VER_WS2012 = 2
    
    VER_WIN32 = 0
    VER_WIN64 = 16
    
    windowsVersion = 0
    windowsArch = 0
    
    userPassword = "Xensource1!"
    
    def __init__(self,tc):
        Experiment.__init__(self,tc)
        measure_classname = "Measurement_%s" % tc.MEASURE
        self.measurement_1 = globals()[measure_classname](self)
        #self.measurement_1 = Measurement_elapsedtime(self)
        #self.measurement_vmstarttime=Measurement_vmstarttime(self)
        #self.measurement_vmreadytime=Measurement_vmreadytime(self)
        #self.measurement_loginvsi=None
        #self.vm_load_1 = VMLoad(self)
        # RDS does not use Guest Event
        self.guest_events = {}
        self.ip_to_guest = {}
        self.vmalloc = {}
    
    def getDimensions(self, filters=None):
        ds = Experiment_vmrun_cron.getDimensions(self)
        ds['LOADSPERVM'] = self.tc.LOADSPERVM
        return ds

    def do_VMTYPES(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMTYPES value=[%s]" % value)
        self.distro = value

        if "ws08r2" in self.distro:
            self.windowsVersion = self.VER_WS2008R2
        elif "ws12" in self.distro:
            self.windowsVersion = self.VER_WS2012
        else:
            self.windowsVersion = self.VER_WS2008

        if "x64" in self.distro:
            self.windowsArch = self.VER_WIN64

    def do_LOADSPERVM(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: LOADSPERVM value=[%s]" % str(value))
        self.loadsPerVM = value

    def installModelGuest(self):
        host = self.tc.getDefaultHost()
        if not host:
            pool = self.tc.getDefaultPool()
            if pool:
                host = pool.master
        
        master = self.tc.getGuest("RDSVM_" + self.distro)
        if master:
            return master
        vm = host.createGenericWindowsGuest(name="RDSVM_" + self.distro, distro=self.distro, vcpus=self.vmvcpus,memory=self.vmram)
        vm.preCloneTailor()
        vm.xenDesktopTailor()
        vm.shutdown()

        vm.start()
        xenrt.TEC().logverbose("Start installing terminal service.")
        rc = 0
        if self.windowsVersion == self.VER_WS2008:
            rc = vm.xmlrpcExec("servermanagercmd -install TS-TERMINAL-SERVER", returnerror=False, returnrc=True, timeout = 600)
            if rc == 3010:
                vm.reboot()
            elif rc != 0:
                raise xenrt.XRTError("Failed to install Terminal Service on RDS VM.")
        elif self.windowsVersion == self.VER_WS2008R2:
            rc = vm.xmlrpcExec("servermanagercmd -install RDS-RD-Server", returnerror=False, returnrc=True, timeout = 600)
            if rc == 3010:
                vm.reboot()
            elif rc != 0:
                raise xenrt.XRTError("Failed to install Remote Desktop Server on RDS VM.")
        elif self.windowsVersion == self.VER_WS2012:
            rc = vm.xmlrpcExec("powershell install-windowsfeature -Name RDS-RD-Server", returnerror=False, returnrc=True, timeout = 600)
            if rc != 0:
                raise xenrt.XRTError("Failed to install Remote Desktop Server on RDS VM.")
            vm.reboot()
            # give sometime to fully boot up.
            xenrt.sleep(60)
            
            # By default, this is blocked in WS2012.
            # This has to be set AFTER TS is up, otherwise TS will back this up and set back to default.
            vm.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp", "UserAuthentication", "DWORD", 0)

            # LoginVSI requires .Net 3.5.
            # WS2012 does not have it by default.
            vm.changeCD(self.distro + ".iso")
            # sleep to wait until iso is mounted.
            xenrt.sleep(5, log=False)
            vm.xmlrpcExec('DISM /Online /Enable-Feature /FeatureName:NetFx3 /All /LimitAccess /Source:d:\sources\sxs')

        # disable IE ESC for ADMIN
        vm.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Active Setup\\Installed Components\\{A509B1A7-37EF-4b3f-8CFC-4F3A74704073}", "IsInstalled", "DWORD", 0)
        # disable IE ESC for USERS
        vm.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Active Setup\\Installed Components\\{A509B1A8-37EF-4b3f-8CFC-4F3A74704073}", "IsInstalled", "DWORD", 0)

        # create users
        xenrt.TEC().logverbose("Start creating users for tests.")
        #self.users = {}
        #self.users[vm] = []
        for i in range(self.loadsPerVM):
            username = "xenrttester%03d" % (i)
            try:
                vm.xmlrpcExec("net user %s %s /add" % (username, self.userPassword), returnerror=False, returnrc=True)
                vm.xmlrpcExec("net localgroup Administrators %s /add" % (username), returnerror=False, returnrc=True)
                #self.users[vm].append(username)
            except:
                xenrt.TEC().logverbose("Failed to create user %s on server %s." % (username, vm))
                raise

        xenrt.TEC().logverbose("DEBUG: VMLOAD class name: " + self.vm_load_1.__class__.__name__)
        #self.tryupto(lambda: self.vm_load_1.install(vm),times=3)
        self.vm_load_1.install(vm)
        
        vm.shutdown()

        xenrt.TEC().logverbose("Creating model %s done." % (vm.getName()))
        return vm

    def installGuests(self):
        # for ge in self.guest_events.values(): ge.reset()
        # self.xapi_event.reset()
        # g0 = self.tryupto(install_model_guest,times=3)
        
        # This might be a pool.
        #pool = self.tc.getDefaultPool()
        #host = self.tc.getDefaultHost()
        
        model = None
        for i in self.getDimensions()['VMS']:
            if model:
                xenrt.TEC().logverbose("Creating a VM by copying from the model guest.")
                self.guests[i] = model.copyVM()
            else:
                xenrt.TEC().logverbose("No existing VM found.")
                model = self.installModelGuest()
                self.guests[i] = model

        xenrt.TEC().logverbose("DEBUG: Guests creation done.")


    def do_XSVERSIONS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS value=[%s]" % str(value))
        
        # Login VSI with RDS always uses prepared host from sequence file.
        master = self.tc.tec.gec.registry.hostGet("RESOURCE_HOST_0")
        pool = self.tc.tec.gec.registry.poolGet("RESOURCE_POOL_0")
        if pool is not None:
            master = pool.master
        if master is not None:
            self.tc.EXISTINGHOST = master.getName()
        
        hostname = self.tc.EXISTINGHOST
        #(pool,master) = existingPool(hostname)
        xenrt.TEC().logverbose("pool,master=%s,%s" % (pool,master))
        #self.tc.tec.gec.registry.poolPut("RESOURCE_POOL_0", pool)
        #self.tc.tec.gec.registry.hostPut("RESOURCE_HOST_0", master)
        #self.tc.tec.gec.registry.hostPut(hostname, master)
        
        #self.xapi_event = XapiEvent(self)
        self.installGuests()
        
        #Starting All vms. 
        #Starting VM does not start LoginVSI.
        xenrt.TEC().logverbose("DEBUG: Starting all guests.")
        for g in self.guests.values():
            g.start()
        
        # Give some times to servers settled down.
        xenrt.sleep(60)
        
        xenrt.TEC().logverbose("DEBUG: vm_load_1.__class__.__name__ = %s" % self.vm_load_1.__class__.__name__)
        if "VMLoad_loginvsi" in self.vm_load_1.__class__.__name__: #is it a loginvsi load?
            xenrt.TEC().logverbose("rdplogon: measurement_loginvsi: %s" % (self.measurement_loginvsi.__class__.__name__))
            if self.measurement_loginvsi:
                self.measurement_loginvsi.rdplogon()

    def do_XSVERSIONS_end(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS_end value=[%s]" % value)
        host = self.tc.getDefaultHost()
        if self.tc.PERFSTATS:
            #stop gather_performance_status.sh
            self.host_load_perf_stats.stop(host)
            self.host_load_sar.stop(host)
        if "VMLoad_loginvsi" in self.vm_load_1.__class__.__name__: #is it a loginvsi load?
            xenrt.TEC().logverbose("finalize: measurement_loginvsi: %s" % (self.measurement_loginvsi.__class__.__name__))
            if self.measurement_loginvsi:
                self.measurement_loginvsi.finalize()

        #print the vcpu state in dom0
        self.print_vcpu_list(host)
    
    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMS value=[%s]" % str(value))
        #do nothing.


class TCVMDensity(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVMDensity")
        #there's a thread for each vm, and in large scalability tests we may run
        #out of memory in the controller if there's not enough stack for all the threads
        resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        #reduces the memory used by each thread, there's a process limit of 3GB for all thread stacks in 32-bit kernels
        threading.stack_size(1048576)


    def prepare(self, arglist=None):
        # Parse generic arguments
        #self.parseArgs(arglist)
        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "pool_config":
                self.pool_config = l[1]
            elif l[0] == "host_config":
                self.host_config = l[1]
            elif l[0] == "vm_config":
                self.vm_config = l[1]
            elif l[0] == "vm_load":
                self.vm_load = l[1]
            elif l[0] == "host_load":
                self.host_load = l[1]
            elif l[0] == "measurement":
                self.measurement = l[1]

    def parse(self, arglist=None):
        if not isinstance(arglist, list): return
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if not getattr(self, l[0]): #if not yet set
                if len(l) < 2:
                    setattr(self, l[0], True)
                else:
                    setattr(self, l[0], eval(l[1]))
            
    def run(self, arglist=None):

        #self.VMTYPES = ['win7sp1-x86', 'winxpsp3', 'win7sp1-x64', 'ws08sp2-x86']
        #self.RUNS = range(1,6)
        #self.VMS = range(1,128)
        ##machine = xenrt.TEC().lookup("MACHINE", "")
        ##xenrt.TEC().logverbose("machine=%s" % machine)
        #self.MACHINES = ['q8']
        #self.XSVERSIONS = ['Tampa-latest','MNR-31188','Cowley-39567','Boston-50762']
        ### eg.: XSBUILDS   = ['Boston-123', 'Boston-456', 'Cowley-345', 'Trunk-979']
        ### eg.: XSVERSIONS = ['boston', 'cowley', 'trunk']        
        ##self.XSVERSIONS = list(set(map(lambda x:(x.split("-")[0]).lower(), XSBUILDS)))

        self.VMTYPES = None
        self.RUNS = None
        self.VMS = None
        self.MACHINES = None
        self.XSVERSIONS = None
        self.THRESHOLD = None
        self.DOM0RAM = None
        self.XENSCHED = None
        self.VMPARAMS = None
        self.EXPERIMENT = None
        self.VMDISKS = None
        self.VMRAM = None
        self.DOM0DISKSCHED = None
        self.QEMUPARAMS = None
        self.DEFAULTSR = None
        self.VMLOADS = None
        self.PERFSTATS = None
        self.VMVIFS = None
        self.VMPOSTINSTALL = None
        self.MEASURE = None
        self.VMCRON = None
        self.DOM0PARAMS = None
        self.XENPARAMS = None
        self.XENOPSPARAMS = None
        self.VMVCPUS = None
        self.EXISTINGHOST = None
        self.XDSUPPORT = None
        self.POSTCLONEWORKER = None
        self.HOSTVMMAP = None  # HOSTVMMAP :: [[(HOST_ID, NUM_VMs)]] ;; type HOST_ID = unsigned int ;; type NUM_VMs = unsigned int
                               # host = tc.getHost("RESOURCE_HOST_%d" % HOST_ID) 
        self.LOGINVSIEXCLUDE = None
        self.VMCOOLOFF = None
        self.LOADSPERVM = None
        self.XENTRACE = None

        inputdir=xenrt.TEC().lookup("INPUTDIR",None)
        def is_valid_inputdir(url):
            return (url is not None) and (len(url) >= 30)
        if is_valid_inputdir(inputdir):
            self.XSVERSIONS=["/".join(str(inputdir).split("/")[-2:])]
            xenrt.TEC().logverbose("init: INPUTDIR=%s => XSVERSIONS=%s" % (inputdir,self.XSVERSIONS))

        #populate unset values preferrably from command line
        def setprm(key,default=None):
            s = str(xenrt.TEC().lookup(key,default))
            if s == "":
                value = s
            else:
                value = eval(s)
            tv = type(value).__name__
            td = type(default).__name__
            reset = False
            if default:
                if td == "list" and td <> tv:
                    # eg. value is string but should be list (because default is list)
                    value = eval(str(value))
                    reset = True
            if not getattr(self, key) or reset: #if not yet set or type needs updating
                setattr(self, key, value)

        setprm("VMS")
        setprm("XSVERSIONS")
        setprm("RUNS")
        setprm("VMTYPES")
        setprm("THRESHOLD")
        setprm("DOM0RAM")
        setprm("XENSCHED")
        setprm("VMPARAMS")
        setprm("EXPERIMENT")
        setprm("VMDISKS")
        setprm("VMRAM")
        setprm("DOM0DISKSCHED")
        setprm("QEMUPARAMS")
        setprm("DEFAULTSR")
        setprm("VMLOADS")
        setprm("PERFSTATS")
        setprm("VMVIFS")
        setprm("VMPOSTINSTALL")
        setprm("MEASURE")
        setprm("VMCRON")
        setprm("DOM0PARAMS")
        setprm("XENPARAMS")
        setprm("XENOPSPARAMS")
        setprm("VMVCPUS")
        setprm("EXISTINGHOST")
        setprm("XDSUPPORT")
        setprm("LOGINVSIEXCLUDE")
        setprm("VMCOOLOFF")
        setprm("LOADSPERVM")
        setprm("XENTRACE")

        #populate remaining unset values from sequence
        self.parse(arglist)

        #populate remaining unset values with defaults
        setprm("VMS",default=range(1,261))
        setprm("XSVERSIONS",default=["trunk/latest"])
        setprm("RUNS",default=range(1,6)) #5 runs
        setprm("MACHINES",default=[xenrt.TEC().lookup("RESOURCE_HOST_0",None)])
        setprm("VMTYPES",default=['win7sp1-x86'])
        setprm("THRESHOLD",default=20.0)
        setprm("DOM0RAM",default=[])
        setprm("XENSCHED",default=['credit'])
        setprm("VMPARAMS",default=[])
        setprm("EXPERIMENT",default="")
        setprm("VMDISKS",default=[])#use default during VM installation
        #eg.:3 disks in the vm:
        #[("0",1,False),#rootdisk: resize in KiB
        #("1",2,True),# disk 1, 2GiB, format
        #("2",1,True)]# disk 2, 1GiB, format
        setprm("VMRAM",default=[]) #None=use the default vmram in vm template
        setprm("DOM0DISKSCHED",default=[]) #None=use the default disk cheduler for /sys/block/sda/queue/scheduler
        setprm("QEMUPARAMS",default=[[]]) #do not remove usb support in vms
        setprm("DEFAULTSR",default=["ext"]) #ext allows more density of vms (think provisioning) than lvm (thick provisioning)
        setprm("VMLOADS",default=[]) #no vm load by default
        setprm("PERFSTATS",default=False)
        setprm("VMVIFS",default=[xenrt.lib.xenserver.Guest.DEFAULT])
        setprm("VMPOSTINSTALL",default=[[]])
        setprm("MEASURE",default='"vmlogintime"')
        setprm("VMCRON",default=[])#by default, do not thread-start vms every x secs
        setprm("DOM0PARAMS",default=[[]])
        setprm("XENPARAMS",default=[])
        setprm("XENOPSPARAMS",default=[[]])
        setprm("VMVCPUS",default=[])
        setprm("EXISTINGHOST",default=None)
        setprm("XDSUPPORT", default=[])
        setprm("POSTCLONEWORKER", default=[0])
        setprm("HOSTVMMAP",default=[[]])
        setprm("LOGINVSIEXCLUDE", default=[[]])
        setprm("VMCOOLOFF", default=["0"]) # no cool-off time by default for the template vm
        setprm("LOADSPERVM", default=[0]) # sessions to run loginvsi per RDS vm
        setprm("XENTRACE", default=[])

        #print resulting parameters
        def ty(x):
            return "%s, type = %s" % (x, type(x).__name__)

        xenrt.TEC().logverbose("run: VMS=%s" % ty(self.VMS))
        xenrt.TEC().logverbose("run: XSVERSIONS=%s" % ty(self.XSVERSIONS))
        xenrt.TEC().logverbose("run: RUNS=%s" % ty(self.RUNS))
        xenrt.TEC().logverbose("run: MACHINES=%s" % ty(self.MACHINES))
        xenrt.TEC().logverbose("run: VMTYPES=%s" % ty(self.VMTYPES))
        xenrt.TEC().logverbose("run: THRESHOLD=%s" % ty(self.THRESHOLD))
        xenrt.TEC().logverbose("run: DOM0RAM=%s" % ty(self.DOM0RAM))
        xenrt.TEC().logverbose("run: XENSCHED=%s" % ty(self.XENSCHED))
        xenrt.TEC().logverbose("run: VMPARAMS=%s" % ty(self.VMPARAMS))
        xenrt.TEC().logverbose("run: EXPERIMENT=%s" % ty(self.EXPERIMENT))
        xenrt.TEC().logverbose("run: VMDISKS=%s" % ty(self.VMDISKS))
        xenrt.TEC().logverbose("run: VMRAM=%s" % ty(self.VMRAM))
        xenrt.TEC().logverbose("run: DOM0DISKSCHED=%s" % ty(self.DOM0DISKSCHED))
        xenrt.TEC().logverbose("run: QEMUPARAMS=%s" % ty(self.QEMUPARAMS))
        xenrt.TEC().logverbose("run: DEFAULTSR=%s" % ty(self.DEFAULTSR))
        xenrt.TEC().logverbose("run: VMLOADS=%s" % ty(self.VMLOADS))
        xenrt.TEC().logverbose("run: PERFSTATS=%s" % ty(self.PERFSTATS))
        xenrt.TEC().logverbose("run: VMVIFS=%s" % ty(self.VMVIFS))
        xenrt.TEC().logverbose("run: VMPOSTINSTALL=%s" % ty(self.VMPOSTINSTALL))
        xenrt.TEC().logverbose("run: MEASURE=%s" % ty(self.MEASURE))
        xenrt.TEC().logverbose("run: VMCRON=%s" % ty(self.VMCRON))
        xenrt.TEC().logverbose("run: DOM0PARAMS=%s" % ty(self.DOM0PARAMS))
        xenrt.TEC().logverbose("run: XENPARAMS=%s" % ty(self.XENPARAMS))
        xenrt.TEC().logverbose("run: XENOPSPARAMS=%s" % ty(self.XENOPSPARAMS))
        xenrt.TEC().logverbose("run: VMVCPUS=%s" % ty(self.VMVCPUS))
        xenrt.TEC().logverbose("run: EXISTINGHOST=%s" % ty(self.EXISTINGHOST))
        xenrt.TEC().logverbose("run: XDSUPPORT=%s" % ty(self.XDSUPPORT))
        xenrt.TEC().logverbose("run: POSTCLONEWORKER=%s" % ty(self.POSTCLONEWORKER))
        xenrt.TEC().logverbose("run: HOSTVMMAP=%s" % ty(self.HOSTVMMAP))
        xenrt.TEC().logverbose("run: LOGINVSIEXCLUDE=%s" % ty(self.LOGINVSIEXCLUDE))
        xenrt.TEC().logverbose("run: VMCOOLOFF=%s" % ty(self.VMCOOLOFF))
        xenrt.TEC().logverbose("run: LOADSPERVM=%s" % ty(self.LOADSPERVM))
        xenrt.TEC().logverbose("run: XENTRACE=%s" % ty(self.XENTRACE))

        experiment_classname = "Experiment_%s" % self.EXPERIMENT
        experiment = globals()[experiment_classname](self)
        #experiment_class = eval(experiment_classname)(self)
        #experiment = Experiment_vmrun(self)
        #experiment = Experiment_vbdscal(self)
        experiment.start(arglist)

    def postRun(self):
        pass
        #self.finishUp()

