#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenRT description of the xapi object model
#
# Copyright (c) 2009 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import inspect, re, copy, tempfile, string
import xenrt
from xenrt.lib.xenserver.call import *

class Context(object):

    def __init__(self, pool):
        self.pool = pool
        self.entities = {}
        self.cache = {}
        self.classes = dict(inspect.getmembers(inspect.getmodule(self), inspect.isclass))
        self.entities["Pool"] = Pool(self.pool, self)

    def prepare(self, environment):
        """Create the necessary entities for this Context
           to conform to environment."""
        for entity in environment:
            xenrt.TEC().logverbose("Preparing a '%s'." % (entity))
            if not entity in self.entities:                 
                if not entity in self.classes:
                    xenrt.TEC().logverbose("No concept of a '%s' exists, using default." % (entity)) 
                    entityclass = self.classes["Default"]
                    self.entities[entity] = entityclass(self, entity)
                else:
                    entityclass = self.classes[entity]
                    xenrt.TEC().logverbose("Preparing all dependencies of '%s'." % (entity))
                    self.prepare(entityclass.DEPENDS)
                    self.entities[entity] = entityclass(self)
            else:
                xenrt.TEC().logverbose("A '%s' already exists." % (entity))

    def cleanup(self, entities):
        """Remove all the specified entities from this Context."""
        xenrt.TEC().logverbose("Cleaning %s." % (entities))
        # We sometimes have entities == self.entities so it's 
        # best to take a copy of whatever we're cleaning up.
        entities = copy.copy(entities)
        for entityname in entities:
            if entityname in self.entities:
                entity = self.entities[entityname]        
    
                xenrt.TEC().logverbose("Destroying entities which depend on %s." % (entityname))
                dependents = filter(lambda x:entityname in self.entities[x].DEPENDS, self.entities)
                self.cleanup(dependents)

                xenrt.TEC().logverbose("Destroying entities which taint %s." % (entityname))
                tainters = filter(lambda x:entityname in self.entities[x].TAINTS, self.entities)
                self.cleanup(tainters)

                if entityname in self.entities:
                    xenrt.TEC().logverbose("Destroying %s." % (entityname))
                    try: 
                        entity.destroy()
                    except Exception, e: 
                        xenrt.TEC().logverbose("Exception destroying %s: %s" % (entityname, e))

                    xenrt.TEC().logverbose("Purging '%s' from cache." % (entityname))
                    for entry in self.cache.keys():
                        if re.search("(^|=)%s" % (entityname), entry):
                            del self.cache[entry]                

                    xenrt.TEC().logverbose("Removing '%s' from context." % (entityname))
                    if self.entities.has_key(entityname):
                        del self.entities[entityname]
    
                    xenrt.TEC().logverbose("Destroying entities which are tainted by '%s'." % (entityname))
                    self.cleanup(entity.TAINTS)

                if not "Pool" in self.entities:
                    self.entities["Pool"] = Pool(self.pool, self)
                if not "Host" in self.entities:
                    self.entities["Host"] = Host(self.pool.master, self)

    def evaluate(self, expression):
        """Evaluate parameter strings at runtime."""
        xenrt.TEC().logverbose("Evaluating: %s" % (expression))
        if type(expression) == type(""):
            if not expression in self.cache:
                evaluated = expression
                for e in self.entities:
                    if re.search("(^|=|,)%s.getHandle\(\)" % (e), evaluated):
                        evaluated = re.sub("%s.getHandle\(\)" % (e),
                                             self.entities[e].getHandle(),
                                             evaluated)
                    if re.search("(^|=|,)%s.getUUID\(\)" % (e), evaluated):
                        evaluated = re.sub("(^|=|,)%s.getUUID\(\)" % (e),
                                           "\\g<1>%s" % (self.entities[e].getUUID()),
                                             evaluated)
                    matches = re.findall("(?:^|=|:|,)%s\.([\w\.]+)" % (e), evaluated)
                    for m in matches:
                        value = str(reduce(getattr, m.split("."), self.entities[e]))
                        evaluated = re.sub("%s.%s" % (e, m), value, evaluated)
                self.cache[expression] = evaluated
            xenrt.TEC().logverbose("'%s' -> '%s'" % (expression, self.cache[expression]))
            return self.cache[expression]
        elif type(expression) == type({}):
            for key in expression:
                expression[key] = self.evaluate(expression[key])
            return expression
        elif type(expression) == type([]):
            return map(self.evaluate, expression)
        else:
            xenrt.TEC().logverbose("-> '%s'" % (expression))
            return expression
            
class _Entity(object):
    """Superclass for creating various XenServer entities.
       See subclasses for examples."""

    NAME = ""
    DEPENDS = []
    TAINTS = []

    OKEY = "X"
    OVAL = "X"

    def _apicall(self, apiargs, root=True):
        if apiargs: 
            if not apiargs.has_key("context"):
                apiargs["context"] = self.context
            call = APICall(**apiargs)
            if root:
                subject = xenrt.ActiveDirectoryServer.Local("root", xenrt.TEC().lookup("ROOT_PASSWORD"))
            else: 
                currenthost, currentsubject = self.context.cache["current"]
                for hostname in self.context.cache["credentials"]:
                    if hostname == currenthost:
                        for name in self.context.cache["credentials"][hostname]:
                            if name == currentsubject.name:
                                subject = self.context.cache["credentials"][hostname][name]["subject"]
            return call.call(self.context.pool.master, subject)

    def __init__(self, context):
        self.context = context                
        self.ref = None
        self.uuid = None
        self.handle = None
        self.create()
        try:
            apiargs = {"operation" : "xenapi.%s.set_other_config" % (self.NAME),
                       "parameters": [self.getHandle(), {self.OKEY:self.OVAL}]}
            self._apicall(apiargs)
        except:
            pass

    def create(self):
        pass

    def destroy(self):
        pass

    def get(self, entity):
        return self.context.entities[entity]

    def getUUID(self): 
        if not self.uuid:
            apiargs = {"operation" : "xenapi.%s.get_uuid" % (self.NAME),
                       "parameters": [self.handle]}
            self.uuid = self._apicall(apiargs)
        return self.uuid

    def getHandle(self): 
        if not self.handle:
            apiargs = {"operation" : "xenapi.%s.get_by_uuid" % (self.NAME),
                       "parameters": [self.uuid]}
            self.handle = self._apicall(apiargs)
        return self.handle

class Pool(_Entity):

    NAME = "pool"

    def __init__(self, pool, context):
        self.context = context
        self.ref = pool
        self.uuid = None
        self.handle = None
        self.create()
        apiargs = {"operation" : "xenapi.%s.set_other_config" % (self.NAME),
                   "parameters": [self.getHandle(), {self.OKEY:self.OVAL}]}
        self._apicall(apiargs)

    def create(self):
        self.uuid = self.ref.getUUID()
        self.context.entities["Host"] = Host(self.ref.master, self.context)
        self.context.entities["Master"] = self.context.entities["Host"]
        self.slaves = self.ref.getSlaves()
        for i in range(len(self.slaves)):
            self.context.entities["Slave-%s" % (i)] = Host(self.slaves[i], self.context)

    def destroy(self):
        xenrt.TEC().logverbose("Implicity destroying all non-host entities.")
        for entity in self.context.entities.keys():
            if not isinstance(self.context.entities[entity], Pool):
                if not isinstance(self.context.entities[entity], Host):
                    self.context.cleanup([entity])
        xenrt.TEC().logverbose("Destroying all hosts.")
        for entity in self.context.entities.keys():
            if isinstance(self.context.entities[entity], Host):
                self.context.entities[entity].reset()
        xenrt.TEC().logverbose("Clearing cache after pool reset.")
        self.context.cache.clear()     
        for slave in self.slaves:
            self.context.pool.addHost(slave, force=True)
        
class Host(_Entity):

    NAME = "host" 

    def __init__(self, host, context):
        self.context = context                
        self.ref = host
        self.uuid = None
        self.handle = None
        self.live = True
        self.create()
        apiargs = {"operation" : "xenapi.%s.set_other_config" % (self.NAME),
                   "parameters": [self.getHandle(), {self.OKEY:self.OVAL}]}
        self._apicall(apiargs)

    def create(self):
        self.handle = self.ref.getHandle()

    def destroy(self):
        self.context.cleanup(["Pool"])

    def reset(self):
        if self.live:
            try: self.ref.execdom0("/etc/init.d/xapi stop")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("rm -f /var/xapi/state.db*")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("rm -f /etc/firstboot.d/state/*")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("rm -f /etc/firstboot.d/data/host.conf")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("rm -f /etc/firstboot.d/05-filesystem-summarise")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("echo master > /etc/xensource/pool.conf")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("/etc/init.d/xapi start")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try: self.ref.execdom0("/etc/init.d/firstboot restart")
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
                try: self.ref.execdom0("rm -f /etc/firstboot.d/state/*")
                except Exception, e:
                    xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
                try: self.ref.execdom0("rm -f /etc/firstboot.d/data/host.conf")
                except Exception, e:
                    xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
                xenrt.TEC().logverbose("Rebooting host...")
                self.ref.reboot()

            try:
                if isinstance(self.ref, xenrt.lib.xenserver.ClearwaterHost):
                    self.ref.execdom0("xe host-apply-edition edition=free")
                else:
                    (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")
                    self.ref.execdom0("xe host-apply-edition edition=platinum license-server-address=%s license-server-port=%s" % (addr, port))
            except Exception, e:
                xenrt.TEC().logverbose("Host reset exception: %s" % (str(e)))
            try:
                self.ref.waitForEnabled(300)            
            except:
                self.ref.enable()
                self.ref.waitForEnabled(300)            
            self.live = False

class Default(_Entity): 

    def __init__(self, context, name):
        self.NAME = name
        _Entity.__init__(self, context)

    def create(self):
        apiargs = {}
        apiargs["operation"] = "xenapi.%s.get_all" % (self.NAME)
        all = self._apicall(apiargs)
        if all: self.handle = all[0]

class HAPool(_Entity):

    NAME = "pool"

    def create(self):
        self.ref = self.get("Pool").ref
        self.uuid = self.get("Pool").getUUID()
        self.target = self.get("Host").ref.createGenericLinuxGuest()
        self.get("Host").ref.execdom0("iptables -F OUTPUT")
        iqn = self.target.installLinuxISCSITarget()
        self.target.createISCSITargetLun(0, 1024)
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % (iqn, self.target.getIP()))
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.get("Master").ref, "iscsi")
        self.sr.create(lun=lun, subtype="lvm", findSCSIID=True)
        self.ref.enableHA()

    def destroy(self):
        try: self.ref.disableHA()
        except Exception, e:
            xenrt.TEC().logverbose("HAPool reset exception: %s" % (str(e)))
        try: self.sr.forget()
        except Exception, e:
            xenrt.TEC().logverbose("HAPool reset exception: %s" % (str(e)))
        try: self.get("Host").ref.execdom0("service open-iscsi stop")
        except Exception, e:
            xenrt.TEC().logverbose("HAPool reset exception: %s" % (str(e)))
        try: self.target.shutdown()
        except Exception, e:
            xenrt.TEC().logverbose("HAPool reset exception: %s" % (str(e)))
        try: self.target.uninstall()
        except Exception, e:
            xenrt.TEC().logverbose("HAPool reset exception: %s" % (str(e)))

class DisabledHAPool(HAPool):

    def create(self):
        HAPool.create(self)
        self.ref.disableHA()

class EmergencyPool(_Entity):

    NAME = "pool"

    TAINTS = ["Pool"] 

    def create(self):
        self.ref = self.get("Pool").ref
        self.uuid = self.get("Pool").getUUID()
        self.get("Master").ref.execdom0("service xapi stop")

class KirkwoodPool(_Entity):

    NAME = "pool"
    DEPENDS = ["Kirkwood"]

    def create(self):
        self.ref = self.get("Pool").ref
        self.uuid = self.get("Pool").getUUID()
        self.ref.initialiseWLB("%s:%d" % (self.get("Kirkwood").ref.ip,
                                          self.get("Kirkwood").ref.port),
                                          self.get("Kirkwood").USERNAME,
                                          self.get("Kirkwood").PASSWORD)
        self.ref.enableWLB()

    def destroy(self):
        try: self.ref.disableWLB()
        except: pass

class DisabledHost(_Entity):

    NAME = "host"

    TAINTS = ["Host"]

    def create(self):
        self.ref = self.get("Host").ref
        self.uuid = self.get("Host").getUUID()
        self.ref.disable()
        #shutdown vms, since host-reboot in older versions require vms to be shutdown
        cli=self.get("Host").ref.getCLIInstance()
        try:
          cli.execute("vm-shutdown --force",args = "uuid=%s" %(self.get("VM").getUUID()))
        except: pass
    
    def destroy(self):
        self.ref.enable() #disabled host should always be re-enabled
        #restart vms so that other cases don't get affected
        cli=self.get("Host").ref.getCLIInstance()
        try:
          cli.execute("vm-start",args = "uuid=%s" %(self.get("VM").getUUID()))
          self.get("VM").ref.pretendToHaveXenTools()
          time.sleep(10)
        except: pass

class FreeHost(_Entity):

    NAME = "host"

    def create(self):
        self.ref = self.get("Host").ref
        self.uuid = self.get("Host").getUUID()
        cli = self.ref.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getUUID()))
        args.append("edition=free")
        cli.execute("host-apply-edition", string.join(args))

    def destroy(self):
        cli = self.ref.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getUUID()))
        args.append("edition=platinum")
        cli.execute("host-apply-edition", string.join(args))

class Kirkwood(_Entity):

    USERNAME = "root"
    PASSWORD = xenrt.TEC().lookup("ROOT_PASSWORD")

    DEPENDS = ["VM"]

    def __init__(self, context):
        self.context = context
        self.ref = xenrt.lib.createFakeKirkwood()
        self.ref.recommendations[self.get("VM").getUUID()] = [{"HostUuid":self.get("Host").getUUID(),
                                                               "RecommendationId":"0",
                                                               "ZeroScoreReason":"None"}]

class HostBackup(_Entity):

    def create(self):
        self.filename = xenrt.TEC().tempFile()
        xenrt.command("rm -f %s" % (self.filename)) 
        self.get("Host").ref.backup(self.filename)

class Patch(_Entity):

    NAME = "pool_patch"

    def create(self):
        cli = self.get("Host").ref.getCLIInstance()
        filename = self.get("Host").ref.getTestHotfix(1)
        self.get("Host").ref.addHotfixFistFile(filename)
        self.uuid = cli.execute("patch-upload", "file-name=%s" % (filename)).strip()

    def destroy(self):
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("patch-destroy", "uuid=%s" % (self.getUUID()))

class Crashdump(_Entity):

    NAME = "crashdump"

    def create(self):
        return #TODO
        host = self.get("Host").ref
        try: 
            host.execdom0("sleep 5 && echo c > /proc/sysrq-trigger &", timeout=30)
        except: 
            pass
        host.waitForSSH(1200)
        self.uuid = host.parseListForUUID("host-crashdump-list", "host-uuid", host.getMyHostUUID())

class VM(_Entity):

    NAME = "VM"

    TAINTS = ["SR"]

    STATE = "UP"
    MEM = 32

    def create(self):
        host = self.get("Host").ref
        
        xenrt.TEC().logverbose("Checking that reader.iso SR hasn't been removed")
        if len(host.getSRs(type = "iso")) <= 1: # tools ISO will always be there
            if getattr(self.context, "isoSRNfsLocation", None) and self.context.isoSRNfsLocation:
                xenrt.TEC().logverbose("Re-creating ISO SR that contains reader.iso")
                host.createISOSR(xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC"))
            else:
                xenrt.TEC().logverbose("Couldn't restore ISO SR that contains reader.iso because self.context.isoSRNfsLocation wasn't set")

        self.ref = host.createGenericEmptyGuest(memory=self.MEM)
        
        # just use random linux iso
        self.ref.changeCD("centos58_x86-64_xenrtinst.iso")
        self.ref.setState(self.STATE)
        if self.STATE == "UP":
            self.ref.pretendToHaveXenTools()
            time.sleep(10) 
        self.uuid = self.ref.getUUID()

    def destroy(self):
        try: self.ref.shutdown(force=True)
        except: pass
        try:  self.ref.uninstall()
        except: pass

class HaltedVM(VM):

    STATE = "DOWN"

class Template(HaltedVM):

    def create(self):
        HaltedVM.create(self)
        self.ref.paramSet("is-a-template", "true")

    def destroy(self):
        self.ref.paramSet("is-a-template", "false")
        HaltedVM.destroy(self)       

class PausedVM(VM):

    STATE = "PAUSED"

class Snapshot(_Entity):

    NAME = "VM"
    DEPENDS = ["VM"]
    TAINTS = ["VM"]

    def create(self):
        self.uuid = self.get("VM").ref.snapshot()    

class ExportedVM(_Entity):

    DEPENDS = ["HaltedVM"]

    def __init__(self, context):
        self.context = context
        self.create()

    def create(self):
        self.image = xenrt.TEC().tempFile() 
        self.get("HaltedVM").ref.exportVM(self.image)

    def destroy(self):
        self.get("Host").execdom0("rm -f %s" % (self.image))

class SuspendedVM(VM):

    def create(self):
        VM.create(self)
        self.ref.setState("SUSPENDED")

class VBD(_Entity):

    NAME = "VBD"
    DEPENDS = ["VM"]
    TAINTS = ["VM"]

    SIZE = 1024

    def create(self): 
        self.vm = self.get(self.DEPENDS[0])
        self.uuid = self.vm.ref.createDisk(sizebytes=self.SIZE, returnVBD=True)
            
#adding OffVBD for VBD.set_mode
class OffVBD(VBD):
 
     DEPENDS = ["HaltedVM"]
     TAINTS = ["HaltedVM"]
     
class UnpluggedVBD(VBD):

    def create(self):
        VBD.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("vbd-unplug --force", "uuid=%s" % (self.getUUID()))

class PausedVBD(VBD):

    def create(self):
        VBD.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("vbd-pause", "uuid=%s" % (self.getUUID()))

class RemoveableVBD(_Entity):

    NAME = "VBD"
    DEPENDS = ["VM", "ISOVDI"]
    TAINTS = ["VM"]

    def create(self):
        self.get("VM").ref.changeCD(self.get("ISOVDI").ISO)
        vmuuid = self.get("VM").getUUID()
        #adding type=CD to ensure only removable VBD gets selected
        self.uuid = self.get("Host").ref.parseListForUUID("vbd-list", "vm-uuid", vmuuid,"type=CD")
        #vm-cd-remove will not work if vbd is still attached to VM. Shutting down the vm 
        #ensures that this is not the case. It's doesnt affect the other api/cli commands using RemoveableVBD
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("vm-shutdown --force",args = "uuid=%s" %(self.get("VM").ref.uuid))
        

class EmptyVBD(RemoveableVBD):

    def create(self):
        RemoveableVBD.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("vbd-eject", "uuid=%s" % (self.getUUID()))

class VDI(_Entity):

    NAME = "VDI"
    DEPENDS = ["NFSSR"]
    TAINTS = ["NFSSR"]

    SIZE = 1024

    def create(self):
        sruuid = self.get("NFSSR").getUUID()
        self.uuid = self.get("Host").ref.createVDI(self.SIZE, sruuid)

    def destroy(self):
        self.get("Host").ref.destroyVDI(self.uuid)
        
#adding SuspendVDI for VM.set_suspend_VDI
class SuspendVDI(_Entity):
 
    NAME="VDI"
    DEPENDS=["VM"]
    TAINTS=["VM"]
    
    def create(self):
        cli=self.get("Host").ref.getCLIInstance()
        cli.execute("vm-suspend --force",args = "uuid=%s" %(self.get("VM").ref.uuid))
        self.uuid=self.get("Host").ref.genParamGet("vm",self.get("VM").ref.uuid,"suspend-VDI-uuid")

    def destroy(self):
        self.get("Host").ref.destroyVDI(self.uuid)

class ISOVDI(_Entity):

    NAME = "VDI"

    ISO = "xs-tools.iso"

    def create(self):
        self.uuid = self.get("Host").ref.parseListForUUID("vdi-list", "name-label", self.ISO)

class VIF(_Entity):

    NAME = "VIF"
    DEPENDS = ["VM", "Network"]
    TAINTS = ["VM", "VLAN"]

    PLUG = True        

    def create(self):
        nwuuid = self.get("Network").getUUID()    
        bridge = self.get("Host").ref.genParamGet("network", nwuuid, "bridge")
        vif = self.get("VM").ref.createVIF(bridge=bridge, plug=self.PLUG)
        self.uuid = self.get("VM").ref.getVIFUUID(vif)
        domid = self.get("VM").ref.getDomid()
        self.get("Host").ref.xenstoreWrite("/xapi/%s/hotplug/vif/2/hotplug" % (domid), "")

class RemoveableVIF(VIF):

    def create(self):
        VIF.create(self)
        domid = self.get("VM").ref.getDomid()
        self.get("Host").ref.xenstoreRm("/xapi/%s/hotplug/vif/0/hotplug" % (domid))

class UnpluggedVIF(VIF):

    PLUG = False

class Network(_Entity):

    NAME = "network"

    def create(self):
        self.uuid = self.get("Host").ref.createNetwork()

    def destroy(self):
        #adding code to ensure bonds on the network are deleted before an attempt to destroy
        #network is made
        pifs=self.get("Host").ref.genParamGet("network",self.getUUID(),"PIF-uuids")
        if pifs:
          bond=self.get("Host").ref.genParamGet("pif",pifs,"bond-master-of")
          cli=self.get("Host").ref.getCLIInstance()
          if xenrt.isUUID(bond):
            cli.execute("bond-destroy",args ="uuid=%s" %(bond))
            time.sleep(120)
          else: # if not a bond, check whether there is a vlan
            vlan=cli.execute("vlan-list", args ="untagged-PIF=%s" %(pifs),minimal=True)
            if xenrt.isUUID(vlan):
              cli.execute("vlan-destroy", args ="uuid=%s" %(vlan))
              
        self.get("Host").ref.removeNetwork(nwuuid=self.getUUID())

class Bond(_Entity):

    NAME = "Bond"

    def create(self):      
        self.context.cleanup(["VLAN"])
        # Ensure we select two PIFs on the same network! CA-63028
        nics = self.get("Host").ref.listSecondaryNICs(network="NPRI")
        nics = [0] + nics
        pifs = map(self.get("Host").ref.getNICPIF, nics)
        # including code to ensure existing bonds (if any) gets deleted
        bond=self.get("Host").ref.genParamGet("pif", pifs[0], "bond-slave-of")
        if xenrt.isUUID(bond):
          self.get("Host").ref.removeBond(bond,management=True)
        bridge, device = self.get("Host").ref.createBond(pifs[0:2])
        self.uuid = self.get("Host").ref.genParamGet("pif", pifs[0], "bond-slave-of")
        pifuuid = self.get("Host").ref.parseListForUUID("pif-list", "bond-master-of", self.uuid)

    def destroy(self):
        self.get("Host").ref.removeBond(self.getUUID(),management=True)
        
#adding LacpBond for Bond.set_property
class LacpBond(Bond):

    def create(self):
       Bond.create(self)
       cli=self.get("Host").ref.getCLIInstance()
       cli.execute("bond-set-mode",args = "uuid=%s mode=lacp" %(self.uuid))
       pifs = self.get("Host").ref.genParamGet("bond",self.uuid , "slaves").split("; ")
       self.get("Host").ref._setPifsForLacp(pifs)
       

class PIF(_Entity):

    NAME = "PIF"    

    def create(self):
        interface = self.get("Host").ref.getDefaultInterface()
        self.uuid = self.get("Host").ref.getPIFUUID(interface,requirePhysical=True)

class SecondaryPIFNPRI(_Entity):

    NAME = "PIF"

    def create(self):
        nicid = self.get("Host").ref.listSecondaryNICs(network="NPRI")[0]
        interface = self.get("Host").ref.getSecondaryNIC(nicid)
        self.uuid = self.get("Host").ref.getPIFUUID(interface,requirePhysical=True)

class SecondaryPIF(_Entity):

    NAME = "PIF"

    def create(self):
        interface = self.get("Host").ref.getSecondaryNIC(1)
        self.uuid = self.get("Host").ref.getPIFUUID(interface,requirePhysical=True)        

class VLAN(_Entity):

    NAME = "VLAN"
    DEPENDS = ["Network", "PIF"]
    TAINTS = ["Network", "PIF"]

    VLAN = 888

    def create(self):
        self.context.cleanup(["Bond"])
        nwuuid = self.get("Network").getUUID()
        pifuuid = self.get("PIF").getUUID()
        vlanpif = self.get("Host").ref.createVLAN(self.VLAN, nwuuid, "", pifuuid)
        self.uuid = self.get("Host").ref.parseListForUUID("vlan-list", "untagged-PIF", vlanpif)

    def destroy(self):
        self.get("Host").ref.removeVLAN(self.VLAN)

class SR(_Entity):

    NAME = "SR"

    def create(self):
        self.uuid = self.get("Host").ref.createFileSR(createVDI=False)

    def destroy(self): 
        self.get("Host").ref.destroyFileSR(self.getUUID(),False)

class BareSR(SR):
    
    def create(self):
        SR.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        pbds = self.get("Host").ref.minimalList("pbd-list", 
                                                "uuid", 
                                                "sr-uuid=%s" % (self.getUUID()))
        for pbd in pbds:
            self.location = self.get("Host").ref.genParamGet("pbd", pbd, 
                                                             "device-config", "location")
            cli.execute("pbd-unplug", "uuid=%s" % (pbd))
            cli.execute("pbd-destroy", "uuid=%s" % (pbd))            

class NFSSR(SR):

    SRLABEL = "RBACTestSR"

    def create(self):
        srclass = xenrt.lib.xenserver.host.NFSStorageRepository
        self.ref = srclass(self.get("Host").ref, self.SRLABEL)
        self.ref.create()
        self.uuid = self.ref.uuid

    def destroy(self):
        #adding code to ensure SR is empty (vdi-copy creates vdi on SR)
        vdis=self.get("Host").ref.genParamGet("sr",self.uuid,"VDIs")
        if not vdis=='':
            vdis=vdis.split("; ")
            cli = self.get("Host").ref.getCLIInstance()
            for vdi in vdis:
              try: 
                cli.execute("vdi-destroy", args="uuid=%s" %(vdi))
              except: pass
        self.ref.destroy()

class SM(_Entity):
    
    NAME = "SM"

    def create(self):
        self.uuid = self.get("Host").ref.parseListForUUID("sm-list", "type", "lvm")        

class PBD(_Entity):

    NAME = "PBD"
    DEPENDS = ["NFSSR"]
    TAINTS = ["NFSSR"]

    def create(self):
        sruuid = self.get("NFSSR").getUUID()
        self.uuid = self.get("Host").ref.parseListForUUID("pbd-list", "sr-uuid", sruuid)

class UnpluggedPBD(PBD):
 
    TAINTS = ["NFSSR"]
   
    def create(self):
        PBD.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (self.getUUID()))

class Console(_Entity):

    NAME = "console"
    DEPENDS = ["VM"]

    def create(self):
        vmuuid = self.context.entities["VM"].getUUID()
        self.uuid = self.get("Host").ref.parseListForUUID("console-list", "vm-uuid", vmuuid)

class CPU(_Entity):

    NAME = "host_cpu"

    def create(self):
        self.uuid = self.get("Host").ref.parseListForUUID("host-cpu-list", 
                                                            "host-uuid",
                                                            self.get("Host").getUUID())

class Message(_Entity):

    NAME = "message"
    DEPENDS = ["VM"]

    def create(self):
        self.uuid = self.get("Host").ref.minimalList("message-list", "uuid")[0]

class Blob(_Entity):

    NAME = "blob"

    def create(self):
        apiargs = {"operation" : "xenapi.blob.create",
                   "parameters": [""]}
        self.handle = self._apicall(apiargs)

    def destroy(self):
        apiargs = {"operation" : "xenapi.blob.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)

class Task(_Entity):

    NAME = "task"

    def create(self):
        apiargs = {"operation" : "xenapi.task.create",
                   "parameters": ["X", "X"]}
        self.handle = self._apicall(apiargs, root=False)

    def destroy(self):
        apiargs = {"operation" : "xenapi.task.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)

class Session(_Entity):

    NAME = "session"

    def create(self):
        hostname = self.get("Host").ref.getMyHostName()
        for x in self.context.cache["credentials"]:
            for y in self.context.cache["credentials"][x]:
                for z in self.context.cache["credentials"][x][y]:
                    if z == "API":
                        self.handle = self.context.cache["credentials"][x][y][z]._session

    def destroy(self):
        if self.context.cache.has_key("credentials"):
            del self.context.cache["credentials"]

class TempFile(_Entity):

    def __init__(self, context):
        self.ref = xenrt.TEC().tempFile()
        xenrt.command("rm -f %s" % (self.ref))

    def destroy(self):
        xenrt.command("rm -f %s" % (self.ref))

class TempDir(_Entity):

    def __init__(self, context):
        self.ref = xenrt.TEC().tempFile()

    def destroy(self):
        xenrt.command("rm -f %s" % (self.ref))

class RemoteTempFile(_Entity):

    def __init__(self, context):
        self.context = context
        self.ref = self.get("Host").ref.execdom0("mktemp /tmp/").strip()

    def destroy(self):
        self.get("Host").ref.execdom0("rm -rf %s" % (self.ref))

class RemoteTempDir(_Entity):

    def __init__(self, context):
        self.context = context
        self.ref = self.get("Host").ref.execdom0("mktemp -d").strip()
        self.get("Host").ref.execdom0("rm -rf %s" % (self.ref))

    def destroy(self):
        self.get("Host").ref.execdom0("rm -rf %s" % (self.ref))

class Subject(_Entity):

    NAME = "subject"

    def create(self):
        apiargs = {"operation" : "xenapi.subject.create",
                   "parameters": [{"subject_identifier":xenrt.randomGuestName()}]}
        self.handle = self._apicall(apiargs)

    def destroy(self):
        apiargs = {"operation" : "xenapi.subject.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)

class RoleSubject(Subject):

    DEPENDS = ["Role"]

    def create(self):
        Subject.create(self)
        cli = self.get("Host").ref.getCLIInstance()
        cli.execute("subject-role-add", "uuid=%s role-uuid=%s" % \
                    (self.getUUID(), self.get("Role").getUUID()))

class Role(_Entity):

    NAME = "role"

    def create(self):
        apiargs = {"operation" : "xenapi.role.get_by_name_label",
                   "parameters": ["read-only"]}
        self.handle = self._apicall(apiargs)[0]

class User(_Entity):

    NAME = "user"

    def create(self):
        self.name = xenrt.randomGuestName()
        apiargs = {"operation" : "xenapi.user.create",
                   "parameters": [{"short_name":self.name[:4], "fullname":self.name, "other-config":{}}]}
        self.handle = self._apicall(apiargs)

    def destroy(self):
        apiargs = {"operation" : "xenapi.user.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)
       
class Secret(_Entity):

    NAME = "secret" 

    def create(self):
        apiargs = {"operation" : "xenapi.secret.create",
                   "parameters": [{"value":"xenrtvalue"}]}
        self.handle = self._apicall(apiargs)

    def destroy(self):
        apiargs = {"operation" : "xenapi.secret.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)

class VMPP(_Entity):

    NAME = "VMPP"

    def create(self):
        apiargs = {"operation" : "xenapi.VMPP.create",
                   "parameters" : [{"name_label": "vmpprbac",
                                    "name_description": "rbacvmpp",
                                    "backup_type": "snapshot",
                                    "backup_frequency" : "weekly",
                                    "backup_schedule" : {}}]}
        self.handle = self._apicall(apiargs)

    def destroy(self):
        vms = self._apicall({"operation": "xenapi.VMPP.get_VMs",
                             "parameters": [self.getHandle()]})
        for vm in vms:
            self._apicall({"operation": "xenapi.VM.set_protection_policy",
                           "parameters": [vm, 'OpaqueRef:NULL']})
        apiargs = {"operation" : "xenapi.VMPP.destroy",
                   "parameters": [self.getHandle()]}
        self._apicall(apiargs)
        
@xenrt.irregularName  
class GPU_group(_Entity):

    NAME="GPU_group"
    
    def create(self):
        apiargs = {"operation" : "xenapi.GPU_group.create",
                   "parameters" : ['gpu_grouprbac']}
        self.handle = self._apicall(apiargs)
    
    def destroy(self):
    
        try:
          apiargs = {"operation" : "xenapi.GPU_group.destroy",
                     "parameters": [self.getHandle()]}
          self._apicall(apiargs)
        except:
          pass

class VGPU(_Entity):
    
    NAME="VGPU"
    DEPENDS=["HaltedVM","GPU_group"]
    TAINTS=["HaltedVM","GPU_group"] 
    
    def create(self):
        apiargs = {"operation" : "xenapi.VGPU.create",
                   "parameters" : [self.get("HaltedVM").getHandle(),self.get("GPU_group").getHandle()]}
        self.handle = self._apicall(apiargs)
    def destroy(self):
        try:
          apiargs = {"operation" : "xenapi.VGPU.destroy",
                     "parameters": [self.getHandle()]}
          self._apicall(apiargs)
        except:
          pass
       
@xenrt.irregularName
class VBD_metrics(_Entity):

    NAME = "VBD_metrics"
    DEPENDS = ["VBD"]
    
    def create(self):
        apiargs = {}
        apiargs["operation"] = "xenapi.%s.get_all" % (self.NAME)
        all = self._apicall(apiargs)
        if all: self.handle = all[0]
    
@xenrt.irregularName
class VIF_metrics(_Entity):

    NAME = "VIF_metrics"
    DEPENDS = ["VIF"]
    
    def create(self):
        apiargs = {}
        apiargs["operation"] = "xenapi.%s.get_all" % (self.NAME)
        all = self._apicall(apiargs)
        if all: self.handle = all[0]

class Appliance (_Entity):

    NAME = "Appliance"
    
    def create(self):
        host = self.get("Host").ref
        cli = host.getCLIInstance()
        self.uuid = cli.execute('appliance-create', 'name-label=tmpappl01', strip=True)
        self.ref = None

    def destroy(self):
        host = self.get("Host").ref
        cli = host.getCLIInstance()
        try:
            cli.execute('appliance-destroy', 'uuid=%s' % self.uuid, strip=True)
        except:
            pass
        self.uuid = None
