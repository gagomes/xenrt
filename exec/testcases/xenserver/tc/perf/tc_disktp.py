import xenrt
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
import math
import os.path
import random

class TestSpace(object):
    d_order = []  # [iterated slower,...,iterated faster]
    
    def filter(self,filters,dimensions):
        #return dict(map(lambda k:(k,filter(filters[k],dimensions[k]) if filters and k in filters else dimensions[k]),dimensions))
        return dict(map(lambda k:(k,(filters and k in filters) and filter(filters[k],dimensions[k]) or dimensions[k]),dimensions))
        
    # return known dimensions, optionally with range subsets
    def getDimensions(self, filters=None): #each dimension is a pair rangename:[range]
        return self.filter(filters,{})

    @xenrt.irregularName
    def getD_order(self):
        dimensions = self.getDimensions()
        #ignore any dimension without points
        return filter(lambda d:len(dimensions[d])>0, self.d_order)

    # return the product of the dimensions as individual points
    def getPoints(self,dimensions):
        result = [[]]
        d_order = self.getD_order()
        for d in d_order:
            result=[x+[y] for x in result for y in dimensions[d]]
        return result

    # return the dimensions that changed between 2 points
    def getDiffDimensions(self, point1, point2):
        coords = self.getDiffCoordinates(point1, point2)
        return map(lambda (d,p1,p2):d, coords)

    # return tuples with dimension,coordinates that changed between 2 points
    def getDiffCoordinates(self, point1, point2):
        result = []
        d_order = self.getD_order()
        if point1:
            for i in range(len(d_order)):
                #result+= [(d_order[i],point1[i],point2[i])] if point1[i]!=point2[i] else []
                result+= (point1[i]!=point2[i]) and [(d_order[i],point1[i],point2[i])] or []
        else:
            for i in range(len(d_order)):
                result+= [(d_order[i],None,point2[i])]
        return result

    def getLeftMostCoordinates(self,coords,p1,p2):
        d_order = self.getD_order()
        #xsversions event needs to be triggered if a dimension to its left has changed
        #(but not if a dimension to its right has changed)
        #this is a quick idea to get this done. we should think some better way, maybe
        #setting a flag on the dimensions on the dimension list in a more general way
        max_d_idx_in_coords=-1
        try: xsversions_idx=d_order.index("XSVERSIONS")
        except: xsversions_idx=-1
        for d,pi,pj in coords:
            if max_d_idx_in_coords<d_order.index(d):
                max_d_idx_in_coords=d_order.index(d)
        if max_d_idx_in_coords < xsversions_idx:
            #we must add the xsversions event at the end
            coords=coords.append(("XSVERSIONS",p1[xsversions_idx],p2[xsversions_idx]))
        return coords

    # try some function up to x times
    def tryupto(self, fun, times=5):
        for i in range(times):
            try:
                return fun()                
            except:
                if i<times-1:
                    pass
                else: # re-raise the exception if the last attempt doesn't succeed
                    raise
        #we should never reach this line
        return None

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
    def __init__(self,experiment):
        self.experiment = experiment

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
    def start(self, host):
        pass
    def stop(self, host):
        pass

# the dimensions here are used when installing a VM
class VMConfig(TestSpace):

    windistros = ['w2k3eesp2','w2k3eesp2-64','winxpsp3','ws08sp2x86','ws08sp2-x64','win7sp1-x86','win7sp1-x64'] #vistaeesp2, vistaeesp2-x86, w2k3eesp2, w2k3eesp2-x64, w2k3sesp2, win7sp1-x64, win7sp1-x86, winxpsp3, ws08-x86, ws08-x64, ws08r2sp1-x64, ws08sp2-x86, ws08sp2-x64
    posixdistros = ['centos56','ubuntu1004','solaris10u9']
    distros = windistros + posixdistros
    
    #valid ranges of each dimension
    VMTYPES = ['debian60', 'winxpsp3', 'win7sp1-x86'] #['win7sp1-x86'] #['winxpsp3-vanilla.img'] #['winxpsp3'] #['centos5'] #['winxpsp3'] #[ 'WIN7', 'WIN7SP2', 'WINXPSP3', 'WIN2K8', 'WIN8', 'UBUNTU1004' ]
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

# the dimensions here are used when installing a host
class HostConfig(TestSpace):
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
    QEMUNOUSB = [ True, False ]
    DEFAULTSR = [ "ext", "lvm", "nfs" ]
    d_order = ['XENSCHED','HWCPUS','HWRAM','XSVERSIONS','IOMMU','NUMA','DOM0RAM','DEFAULTSR']
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
              'QEMUNOUSB':self.QEMUNOUSB,
              'DEFAULTSR':self.DEFAULTSR
            }
        )
    #obj_state: #default values:
    xsversion = 'TRUNK'


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

class GuestEvent(object):
    # dict: ip -> ...
    events = {}
    UDP_IP = socket.gethostbyname(socket.gethostname())
    UDP_PORT = 5000
    script_filename = "udp_send.py"
    stop_filename = "udp_send.stop"

    def __init__(self,experiment):
        self.experiment = experiment
        thread.start_new_thread(self.listen,())

    def reset(self):
        events = {}

    def listen(self):
        sock = socket.socket( socket.AF_INET, # Internet
                              socket.SOCK_DGRAM ) # UDP
        bound=False
        while not bound:
            try:
                sock.bind( (self.UDP_IP,self.UDP_PORT) )
                bound=True
            except Exception, e:
                xenrt.TEC().logverbose("GuestEvent: binding to %s:%s: %s" % (self.UDP_IP,self.UDP_PORT,e))
                self.UDP_PORT = random.randint(5000,50000)
        xenrt.TEC().logverbose("GuestEvent: bound to %s:%s" % (self.UDP_IP,self.UDP_PORT))

        while True:
            try:
                msg, (guest_ip, guest_port) = sock.recvfrom( 16)#, socket.MSG_DONTWAIT ) # buffer size is smallest possible to fit one msg only
                if not self.events.has_key(guest_ip):
                    xenrt.TEC().logverbose("GuestEvent: received guest_ip, guest_port, message: %s, %s, %s" % (guest_ip, guest_port, msg))
                    self.events[guest_ip]=msg
                    guest = self.experiment.ip_to_guest[guest_ip]
                    #if guest.windows:
                    #    i=0
                    #    done=False
                    #    while not done and i < 5:
                    #        time.sleep(1)
                    #        try:
                    #            guest.xmlrpcWriteFile("c:\\%s" % self.stop_filename, "")
                    #            done=True
                    #        except Exception, e:
                    #            xenrt.TEC().logverbose("GuestEvent: while writing %s: %s" % (self.stop_filename, e))
                    #        i=i+1
                    #else:#todo: posix guest
                    #    pass
            except Exception, e:
                xenrt.TEC().logverbose("GuestEvent: listen: %s" % e)
                time.sleep(0.1)
 
    def receive(self, guest, timeout=400):
        if self.events.has_key(guest.mainip):
            xenrt.TEC().logverbose("GuestEvent: already received event from ip %s" % guest.mainip)
            return True
        start = xenrt.util.timenow() 
        done = False
        i=1
        while not done and (start+timeout > xenrt.util.timenow()):
            if math.log(i,2) % 1 == 0.0:#back-off printing of i 
                xenrt.TEC().logverbose("GuestEvent: checking if event has been received...")
            if self.events.has_key(guest.mainip):
                done = True
            time.sleep(0.1)
            i=i+1
        if not done:
            xenrt.TEC().logverbose("GuestEvent: timeout!")
        return done

    #install send script in the guest
    def installSendScript(self,guest):
        script="""
import socket
import time
import os.path

controller_ip = "%s"
controller_udp_port = %s
i=0
while not os.path.isfile("%s%s") and i<20:
    msg = "LOGIN_END+MSG%%s" %% i
    print "sending to (%%s:%%s):%%s" %% (controller_ip,controller_udp_port,msg)
    try:
        s = socket.socket( socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(msg, (controller_ip, controller_udp_port))
    except Exception, e:
        print "exception %%s" %% e
    time.sleep(0.5)
    i=i+1
"""
        if guest.windows: 
            script = script % (self.UDP_IP, self.UDP_PORT,"c:\\",self.stop_filename)
            script_path = "c:\\%s" % self.script_filename
            guest.xmlrpcWriteFile(script_path, script)
            #start the script whenever windows login finished
            guest.winRegAdd("HKCU",#"HKLM", 
                "software\\microsoft\\windows\\currentversion\\run",
                "guestevent",
                "SZ",
                "python %s" % script_path)
        else:#todo:posix guest
            pass
 
class Measurement(object):
    #save the experiment running this measurement in order to access context
    def __init__(self,experiment):
        self.experiment = experiment

    firstline = True
    log_filename = "measurements"
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
            header = str(['TIMESTAMP',measurements_header]+self.experiment.getD_order())
            self.experiment.tc.log(self.log_filename, header)
            self.firstline = False
        timestamp = ("%sZ"%datetime.datetime.utcnow()).replace(" ","T")
        line = str([timestamp,measurements]+coord)
        self.experiment.tc.log(self.log_filename, line)
        xenrt.TEC().logverbose("%s.log: %s" % (self.log_filename,line))
        
    def start(self,coord):
        pass
    def stop(self,coord):
        return None

# An experiment is a measurement on a subset
# of all possible configurations and loads.
class Experiment(TestSpace):

    RUNS = range(1,6)
    pool_config = PoolConfig()
    host_config = HostConfig()
    vm_config = VMConfig()
    guests = {}
    hosts = []
    tc = None

    #save the tc running this experiment in order to access xenrt context
    def __init__(self,tc):
        self.tc = tc
        #self.measurement = Measurement(self)
        self.vm_load = VMLoad(self) # no load by default
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
                    print traceback.print_exc()
                    #raise #raise e #temporarily for debugging purposes
                except xenrt.XRTError, e:
                    xenrt.TEC().logverbose("Experiment.do_%s(%s):%s" % (d,p2,e))
                    #xenrt raised an error
                    #continue???
                    print traceback.print_exc()                    
                    #raise #raise e #temporarily for debugging purposes
                except Exception, e: #ignore everything else
                    xenrt.TEC().logverbose("EXC: Experiment.do_%s(%s):%s" % (d,p2,e))
                    print traceback.print_exc()                    
                    #raise #raise e #temporarily for debugging purposes

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
    def stop(self,coord):
        #write down final elapsed time just after event
        now = time.time ()
        diff = now - self.times[''.join(map(str,coord))]
        self.log(coord,diff)
        return diff

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

class HostLoadGatherPerformanceStatus(HostLoad):
    script = "(cd /root; sh ./gather-performance-status.sh %s)"
    def prepare(self,host):
        host.execdom0("(cd /root; wget 'http://confluence.uk.xensource.com/download/attachments/69043187/gather-performance-status.sh' -O gather-performance-status.sh)")        
    def start(self, host):
        script_start = self.script % "start xensource"
        host.execdom0(script_start)
    def stop(self, host):
        #need to wait 5.5mins in order to make sure we have at least one run
        #of the rrd_updates and xentrace inside the script in dom0
        time.sleep(330)
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

 
#in this experiment, vm_start is part of the preparation
#and what is measured are attributes when the vm is running
class Experiment_vmrun(Experiment):
# optimize the time necessary to measure the
# space of configurations by going through directions that
# are quicker to explore (eg. increasing number of VMs first, and
# only then reinstalling hosts with different configurations)
    #d_order = ['DOM0RAM','XSVERSIONS','VMS']
    d_order = ['RUNS','VMTYPES','VMRAM','MACHINES','DOM0RAM','DEFAULTSR','XENSCHED','DOM0DISKSCHED','QEMUNOUSB','VMPARAMS','VMLOAD','XSVERSIONS','VMS']
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
        ds['XENSCHED'] = self.tc.XENSCHED
        ds['VMPARAMS'] = self.tc.VMPARAMS
        ds['VMRAM'] = self.tc.VMRAM
        ds['DOM0DISKSCHED'] = self.tc.DOM0DISKSCHED
        ds['QEMUNOUSB'] = self.tc.QEMUNOUSB
        ds['DEFAULTSR'] = self.tc.DEFAULTSR
        ds['VMDISKS'] = self.tc.VMDISKS
        ds['VMLOAD'] = self.tc.VMLOAD
        return ds

    def __init__(self,tc):
        Experiment.__init__(self,tc)
        self.measurement_1 = Measurement_elapsedtime(self)
        self.vm_load_1 = VMLoad(self)
        self.host_load_perf_stats = HostLoadGatherPerformanceStatus(self)
        self.host_load_sar = HostLoadSar(self)
        self.guest_event = GuestEvent(self)
        self.ip_to_guest = {}

    #updated in do_VMTYPES()
    distro = "None"
    vmparams = []
    vmram = None
    dom0disksched = None
    qemunousb = False
    defaultsr = "ext"
    vmdisks = []

    #this event handles change of values of dimension XSVERSIONS
    #value: contains the value in this dimension that needs be handled
    #coord: contains all the values in all dimensions (current point being visited)
    def do_XSVERSIONS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS value=[%s]" % value)

        def install_pool():
            urlpref = xenrt.TEC().lookup("FORCE_HTTP_FETCH", "")
            urlsuffix = value.replace("-","/").lower()
            url = "%s/usr/groups/xen/carbon/%s" % (urlpref, urlsuffix)
            product_version = value.split("-")[0] #"Boston"

            def setInputDir(url):
                xenrt.TEC().config.setVariable("INPUTDIR",url) #"%s/usr/groups/xen/carbon/boston/50762"%urlpref)
                xenrt.TEC().setInputDir(url) #"%s/usr/groups/xen/carbon/boston/50762"%urlpref)
                xenrt.GEC().filemanager = xenrt.filemanager.getFileManager()
                #sanity check: does this url exist?
                bash_cmd = "wget --server-response %s 2>&1|grep HTTP/|gawk '{print $2}'" % url
                p = subprocess.Popen(bash_cmd,shell=True,stdout=subprocess.PIPE)
                http_code = p.stdout.read().strip()
                inputdir_ok = not ("404" in http_code)
                if inputdir_ok:
                    xenrt.TEC().logverbose("http_code=%s: found INPUTDIR at %s" % (http_code,url))
                else:
                    xenrt.TEC().logverbose("http_code=%s: did not find INPUTDIR at %s" % (http_code,url))
                return inputdir_ok

            inputdir_ok = setInputDir(url)
            if not inputdir_ok:
                xenrt.TEC().logverbose("INPUTDIR %s doesn't exist. Trying trunk instead..." % url)
                #try again, using trunk instead of the product name
                url = url.replace(product_version.lower(),"trunk") 
                inputdir_ok = setInputDir(url)
                if not inputdir_ok:
                    xenrt.TEC().logverbose("INPUTDIR %s doesn't exist! Giving up..." % url)
                    raise xenrt.XRTError("%s doesn't exist" % url)

            xenrt.TEC().config.setVariable("PRODUCT_VERSION",product_version)

            if self.defaultsr in ["lvm","ext"]:
                localsr = self.defaultsr
                sharedsr = ""
            else:
                localsr = "ext"
                sharedsr = '<storage type="%s" name="%ssr" default="true"/>' % (self.defaultsr,self.defaultsr)
            seq = "<pool><host installsr=\"%s\"/>%s</pool>" % (localsr,sharedsr)
            #seq = "<pool><host/></pool>"
            pool_xmlnode = xml.dom.minidom.parseString(seq)
            prepare = PrepareNode(pool_xmlnode, pool_xmlnode, {}) 
            prepare.runThis()

            def set_dom0disksched(host,dom0disksched):
                if dom0disksched:
                    host.execdom0("echo %s > /sys/block/sda/queue/scheduler" % dom0disksched)
           
            def remove_usb_support_in_qemu(host,qemunousb):
                if qemunousb:
                    #this sed works in xs6.0+ only
                    host.execdom0('sed -i \'s/if is_sdk/qemu_args.remove("-usb")\\n\\tqemu_args.remove("-usbdevice")\\n\\tqemu_args.remove("tablet")\\n\\tif is_sdk/\' /opt/xensource/libexec/qemu-dm-wrapper') 
                    #this sed works in xs5.6sp2- only
                    host.execdom0('sed -i \'s/sys.argv\[2:\]$/sys.argv\[2:\]\\nqemu_args.remove("-usb")\\nqemu_args.remove("-usbdevice")\\nqemu_args.remove("tablet")\\n/\' /opt/xensource/libexec/qemu-dm-wrapper')
   
            host = self.tc.getDefaultHost()
            set_dom0disksched(host,self.dom0disksched) 
            remove_usb_support_in_qemu(host,self.qemunousb)

        def install_model_guest():
            pool = self.tc.getDefaultPool()
            host = self.tc.getDefaultHost()
            cli = host.getCLIInstance()
            defaultSR = pool.master.lookupDefaultSR()
            vm_template = xenrt.lib.xenserver.getTemplate(host, self.distro, arch=None)

            xenrt.TEC().logverbose("Installing VM for experiment...")
            vm_name="VM-DENSITY-%s" % self.distro #xenrt.randomGuestName()
            host_guests = host.listGuests()

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

                #self.guest_event.installSendScript(g0)
                #g0.shutdown()

            else:
                #model vm not found in host, install it from scratch
                #g0 = host.guestFactory()(vm_name, vm_template, host=host)
                #g0.createGuestFromTemplate(vm_template, defaultSR)

                if self.distro.endswith(".img"):
                    #import vm from image
                    #self.tc.importVMFromRefBase(host, imagefilename, vmname, sruuid, template="NO_TEMPLATE"):
                    #g0 = self.tc.importVMFromRefBase(host, "winxpsp3-vanilla.img", "winxpsp3-vanilla", defaultSR)
                    g0 = self.tc.importVMFromRefBase(host, self.distro, vm_name, defaultSR)
                    for (gp_name,gp_value) in self.vmparams:
                        g0.paramSet(gp_name,gp_value)
                    self.tc.putVMonNetwork(g0)

                elif self.distro[0]=="w": #windows iso image for installation
                    g0=xenrt.lib.xenserver.guest.createVM(host,vm_name,self.distro,vifs=xenrt.lib.xenserver.Guest.DEFAULT,disks=self.vmdisks,memory=self.vmram,guestparams=self.vmparams,postinstall=['installDrivers'])
                    #g0.install(host,isoname=xenrt.DEFAULT,distro=self.distro,sr=defaultSR)
                    #g0.check()
                    #g0.installDrivers()
                    ##g0.installTools()
                    
                else: #non-windows iso image for installation
                    xenrt.TEC().logverbose("felipef verbose: installing non-windows VM (g0)")
                    g0=xenrt.lib.xenserver.guest.createVM(host,vm_name,self.distro,disks=self.vmdisks,memory=self.vmram)
                    #g0.install(host,isoname=xenrt.DEFAULT,distro=self.distro,sr=defaultSR, repository="cdrom",method="CDROM")
                    
                g0.check()
                g0.xmlrpcExec("netsh firewall set opmode disable")
                self.guest_event.installSendScript(g0)

                g0.reboot()
                #time for idle VM to flush any post-install pending tasks,
                #we do not want to clone these pending tasks into other VMs
                xenrt.TEC().logverbose("waiting idle VM to flush any post-install pending tasks...")
                time.sleep(300)

                g0.shutdown()

            return g0

        def install_guests():
            # 2. install guests in the pool
            self.guest_event.reset()
            g0 = self.tryupto(install_model_guest,times=3)
            for i in self.getDimensions()['VMS']:
                xenrt.TEC().logverbose("felipef verbose: cloning g0 to g")
                g = g0.cloneVM() #name=("%s-%i" % (vm_name,i)))
                #xenrt.TEC().registry.guestPut(g.getName(),g)
                self.guests[i] = g
                ##start vm
                #g.start()

        self.tryupto(install_pool)
        install_guests()

        #wait until all vms are 'running' (for some definition of 'running')
        #wait(60) #please do proper wait for vm events
        if self.tc.PERFSTATS:
            #start gather_performance_status.sh
            host = self.tc.getDefaultHost()
            self.host_load_perf_stats.prepare(host)
            self.host_load_perf_stats.start(host)
            self.host_load_sar.start(host)

    def do_XSVERSIONS_end(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XSVERSIONS_end value=[%s]" % value)
        if self.tc.PERFSTATS:
            #stop gather_performance_status.sh
            host = self.tc.getDefaultHost()
            self.host_load_perf_stats.stop(host)
            self.host_load_sar.stop(host)

    def do_VMLOAD(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMLOAD value=[%s]" % value)
        vmload_classname = "VMLoad_%s" % value 
        self.vm_load_1 = globals()[vmload_classname](self)

    def do_XENSCHED(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: XENSCHED value=[%s]" % value)

    def do_DOM0DISKSCHED(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DOM0DISKSCHED value=[%s]" % value)
        self.dom0disksched = value

    def do_QEMUNOUSB(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: QEMUNOUSB value=[%s]" % value)
        self.qemunousb = value

    def do_DEFAULTSR(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: DEFAULTSR value=[%s]" % value)
        self.defaultsr = value

    def do_VMTYPES(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMTYPES value=[%s]" % value)
        self.distro = value

    def do_VMPARAMS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMPARAMS value=[%s]" % str(value))
        self.vmparams = value

    def do_VMDISKS(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMDISKS value=[%s]" % str(value))
        self.vmdisks = value

    def do_VMRAM(self, value, coord):
        xenrt.TEC().logverbose("DEBUG: VMRAM value=[%s]" % str(value))
        self.vmram = value

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
        # change dom0 ram and reboot host
        xenrt.TEC().config.setVariable("OPTION_DOM0_MEM", value)

    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        #TODO: add a is_initial_value parameter sent by the framework,
        #so that it is not necessary to guess what the first possible value is
        #in the checks below

        if value == 1:
            self.do_VMS_ERR_load_failed = False
        if self.do_VMS_ERR_load_failed:
            return #ignore this dimension

        guest = self.guests[value]
            
        #vm is already running, do some load on it and measure

        #only measure at the initial value or if the base measurement
        #still exists to compare against
        if value == 1 or self.measurement_1.base_measurement:
            xenrt.TEC().logverbose("DEBUG: VMS value=[%s]" % value)

            self.measurement_1.start(coord)

            #guest.start() #vm-start + automatic login
            #guest.check()

            #cli = guest.host.getCLIInstance()
            guest.host.execdom0("xe vm-start uuid=%s" % guest.uuid)
            vifname, bridge, mac, c = guest.vifs[0]
            if not self.measurement_1.base_measurement:
                timeout = 300
            else:
                timeout = 300 + self.measurement_1.base_measurement * self.tc.THRESHOLD
            guest.mainip = guest.getHost().arpwatch(bridge, mac, timeout=timeout)
            self.ip_to_guest[guest.mainip] = guest
            #guest.waitforxmlrpc(300, desc="Daemon", sleeptime=1, reallyImpatient=False)
            received_event = self.guest_event.receive(guest,timeout)
            if not received_event:
                raise xenrt.XRTFailure("did not receive login event for vm %s (ip %s)" % (guest,guest.mainip))

            #and then measure the load, eg. time for login to finish
            result = self.measurement_1.stop(coord)

            #run vm load on vm $value without stopping, eg. cpu loop
            try:
                self.tryupto(lambda: self.vm_load_1.start(guest),times=3)
                #self.vm_load_1.stop(guest)
                pass
            except: #flag this important problem
                self.do_VMS_ERR_load_failed = True
                xenrt.TEC().logverbose("======> VM load failed to start for VM %s! Aborting this sequence of VMs!" % value)
                raise #re-raise the exception
        
            #store the initial base measurement value to compare against later
            #when detecting if latest measurement is too different
            if value == 1:
                self.measurement_1.base_measurement = result
                xenrt.TEC().logverbose("Base measurement: %s" % (self.measurement_1.base_measurement))
            else:
                #is the current measurement 10x higher than the initial one?
                if result > self.tc.THRESHOLD * self.measurement_1.base_measurement:
                    #stop measuring remaining VMs until base measurement is made again
                    self.measurement_1.base_measurement = None

class Experiment_disktp(Experiment_vmrun):
    #d_order = ['RUNS','VMTYPES','MACHINES','DOM0RAM','XENSCHED','VMPARAMS','XSVERSIONS','VMS']
    d_order = ['VMDISKS','VMTYPES','DOM0RAM','VMRAM','XSVERSIONS','VMS']
    def getDimensions(self, filters=None):
        #return dict(
            #Experiment.getDimensions(self,{'XSVERSIONS':(lambda x:x in self.tc.XSVERSIONS)}).items()
        #)
        ds = Experiment.getDimensions(self)
        ds['XSVERSIONS'] = self.tc.XSVERSIONS
#        ds['MACHINES'] = self.tc.MACHINES
        ds['VMS'] = self.tc.VMS
#        ds['RUNS'] = self.tc.RUNS
        ds['VMTYPES'] = self.tc.VMTYPES
        ds['DOM0RAM'] = self.tc.DOM0RAM
#        ds['XENSCHED'] = self.tc.XENSCHED
#        ds['VMPARAMS'] = self.tc.VMPARAMS
        ds['VMDISKS'] = self.tc.VMDISKS
        ds['VMRAM'] = self.tc.VMRAM
        return ds

    def __init__(self,tc):
        Experiment.__init__(self,tc)
        self.measurement_1 = Measurement_elapsedtime(self)
        self.vm_load_1 = VMLoad_cpu_loop(self)
        self.guest_event = GuestEvent(self)
        self.ip_to_guest = {}

    #updated in do_VMTYPES()
    distro = "None"
    vmparams = []
    vmdisks = []
    vmram = None 

    #this event handles change of values of dimension VMS
    def do_VMS(self, value, coord):
        #TODO: add a is_initial_value parameter sent by the framework,
        #so that it is not necessary to guess what the first possible value is
        #in the checks below

        if value == 1:
            self.do_VMS_ERR_load_failed = False
        if self.do_VMS_ERR_load_failed:
            return #ignore this dimension

        guest = self.guests[value]
            
        #vm is already running, do some load on it and measure

        #only measure at the initial value or if the base measurement
        #still exists to compare against
        if value == 1 or self.measurement_1.base_measurement:
            xenrt.TEC().logverbose("DEBUG: VMS value=[%s]" % value)

            self.measurement_1.start(coord)

            #guest.start() #vm-start + automatic login
            #guest.check()

            #cli = guest.host.getCLIInstance()
            guest.host.execdom0("xe vm-start uuid=%s" % guest.uuid)
            vifname, bridge, mac, c = guest.vifs[0]
            if not self.measurement_1.base_measurement:
                timeout = 300
            else:
                timeout = 300 + self.measurement_1.base_measurement * self.tc.THRESHOLD
            guest.mainip = guest.getHost().arpwatch(bridge, mac, timeout=timeout)
            self.ip_to_guest[guest.mainip] = guest
            #guest.waitforxmlrpc(300, desc="Daemon", sleeptime=1, reallyImpatient=False)
            received_event = self.guest_event.receive(guest)
            if not received_event:
                raise xenrt.XRTFailure("did not receive login event for vm %s (ip %s)" % (guest,guest.mainip))

            #and then measure the load, eg. time for login to finish
            result = self.measurement_1.stop(coord)

            #run vm load on vm $value without stopping, eg. cpu loop
            try:
                #self.tryupto(lambda: self.vm_load_1.start(guest),times=3)
                #self.vm_load_1.stop(guest)
                pass
            except: #flag this important problem
                self.do_VMS_ERR_load_failed = True
                xenrt.TEC().logverbose("======> VM load failed to start for VM %s! Aborting this sequence of VMs!" % value)
                raise #re-raise the exception
        
            #store the initial base measurement value to compare against later
            #when detecting if latest measurement is too different
            if value == 1:
                self.measurement_1.base_measurement = result
                xenrt.TEC().logverbose("Base measurement: %s" % (self.measurement_1.base_measurement))
            else:
                #is the current measurement 10x higher than the initial one?
                if result > self.tc.THRESHOLD * self.measurement_1.base_measurement:
                    #stop measuring remaining VMs until base measurement is made again
                    self.measurement_1.base_measurement = None



class TCDiskThroughput(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDiskThroughput")

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

        #xenrt requires these flags to install windows vms automatically
        xenrt.TEC().value("ENABLE_CITRIXCERT",True)
        xenrt.TEC().value("ALWAYS_TEST_SIGN",True)
        xenrt.Config().setVariable("ENABLE_CITRIXCERT",True)
        xenrt.Config().setVariable("ALWAYS_TEST_SIGN",True)

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
        self.QEMUNOUSB = None
        self.DEFAULTSR = None
        self.VMLOAD = None
        self.PERFSTATS = None

        #populate unset values preferrably from command line
        def setprm(key,default=None): 
            if not getattr(self, key): #if not yet set
                setattr(self, key, eval(str(xenrt.TEC().lookup(key,default))))
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
        setprm("QEMUNOUSB")
        setprm("DEFAULTSR")
        setprm("VMLOAD")
        setprm("PERFSTATS")

        #populate remaining unset values from sequence
        self.parse(arglist)

        #populate remaining unset values with defaults
        setprm("VMS",default=range(1,160))
        setprm("XSVERSIONS",default=['Tampa-latest']) #== trunk-latest
        setprm("RUNS",default=range(1,6)) #5 runs
        setprm("MACHINES",default=[xenrt.TEC().lookup("RESOURCE_HOST_0",None)])
        setprm("VMTYPES",default=['win7sp1-x86'])
        setprm("THRESHOLD",default=20.0)
        setprm("DOM0RAM",default=['752'])
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
        setprm("QEMUNOUSB",default=[]) #do not remove usb support in vms
        setprm("DEFAULTSR",default=["ext"]) #ext allows more density of vms (think provisioning) than lvm (thick provisioning)
        setprm("VMLOAD",default=[]) #no vm load by default
        setprm("PERFSTATS",default=False)

        #print resulting parameters
        xenrt.TEC().logverbose("run: VMS=%s" % self.VMS)
        xenrt.TEC().logverbose("run: XSVERSIONS=%s" % self.XSVERSIONS)
        xenrt.TEC().logverbose("run: RUNS=%s" % self.RUNS)
        xenrt.TEC().logverbose("run: MACHINES=%s" % self.MACHINES)
        xenrt.TEC().logverbose("run: VMTYPES=%s" % self.VMTYPES)
        xenrt.TEC().logverbose("run: THRESHOLD=%s" % self.THRESHOLD)
        xenrt.TEC().logverbose("run: DOM0RAM=%s" % self.DOM0RAM)
        xenrt.TEC().logverbose("run: XENSCHED=%s" % self.XENSCHED)
        xenrt.TEC().logverbose("run: VMPARAMS=%s" % self.VMPARAMS)
        xenrt.TEC().logverbose("run: EXPERIMENT=%s" % self.EXPERIMENT)
        xenrt.TEC().logverbose("run: VMDISKS=%s" % self.VMDISKS)
        xenrt.TEC().logverbose("run: VMRAM=%s" % self.VMRAM)
        xenrt.TEC().logverbose("run: DOM0DISKSCHED=%s" % self.DOM0DISKSCHED)
        xenrt.TEC().logverbose("run: QEMUNOUSB=%s" % self.QEMUNOUSB)
        xenrt.TEC().logverbose("run: DEFAULTSR=%s" % self.DEFAULTSR)
        xenrt.TEC().logverbose("run: VMLOAD=%s" % self.VMLOAD)
        xenrt.TEC().logverbose("run: PERFSTATS=%s" % self.PERFSTATS)

        #other default initializations for xenrt
        xenrt.TEC().config.setVariable("ENABLE_CITRIXCERT",True)
        xenrt.TEC().config.setVariable("ALWAYS_TEST_SIGN",True)

        experiment_classname = "Experiment_%s" % self.EXPERIMENT
        experiment = globals()[experiment_classname](self)
        experiment.start(arglist)

    def postRun(self):
        pass
        #self.finishUp()

