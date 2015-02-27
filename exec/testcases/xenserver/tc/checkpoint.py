#
# XenRT: Test harness for Xen and the XenServer product family.
#
# Testcases for checkpoint and rollback features.
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xml.dom.minidom, re, string, copy, time, os, random 
import xenrt

class Comparer:

    def getparameters(self, root, uuid):
        if not xenrt.isUUID(uuid): return {}
        regexp = re.compile(r"\s*(?P<parameter>\S+)\s+\(.*\)\s*(?:\[DEPRECATED\])?:\s*(?P<value>.*)")
        cli = self.host.getCLIInstance()
        command = ["%s-param-list" % (root)]
        command.append("uuid=%s" % (uuid))
        parameters = cli.execute(string.join(command), strip=True)
        parameters = map(regexp.match, parameters.splitlines())
        return dict(map(lambda x:(x.group("parameter"), x.group("value")), parameters))

    def validateObject(self, root, object, corresponding):
        original = self.objects[root][object]
        comparison = self.getparameters(root, corresponding)
        if not len(original) == len(comparison):
            raise xenrt.XRTFailure("Objects have a different number of parameters.")
        values = dict(zip(original.keys(), 
                      zip(original.values(), comparison.values())))
        differences = dict(filter(lambda (x,(y,z)):not y == z, values.items()))
        tobechecked = map(lambda (x,y):x, self.checks[root])
        unknown = filter(lambda x:not(x in tobechecked or x in self.ignore[root]), differences)
        if unknown:
            for u in unknown:
                xenrt.TEC().logverbose("Discrepancy: %s (%s, %s)" % ((u,) + values[u]))
                self.errors.append((root, u))
            xenrt.TEC().logverbose("Unexpected metadata difference(s) found: %s" % (unknown))
        for parameter,condition in self.checks[root]:
            if parameter in values:
                x,y = values[parameter]
                if not condition(self, x, y, object, corresponding):
                    xenrt.TEC().logverbose("Unexpected value for %s. (%s, %s) (%s, %s)" % 
                                           (parameter, x, y, object, corresponding))
                    self.errors.append((root, parameter, x, y))
            else:
                xenrt.TEC().logverbose("Not found: %s" % (parameter))
                self.errors.append((root, parameter))
        return True

    def validateMultiple(self, root, uuid):
        comparison = self.host.minimalList("%s-list" % (root), args="vm-uuid=%s" % (uuid))  
        if not len(self.objects[root]) == len(comparison):
            raise xenrt.XRTFailure("Found a different number of %ss." % (root.upper()))
        for object in self.objects[root]:
            device = self.objects[root][object]["device"]
            for corresponding in comparison:
                if self.host.genParamGet(root, corresponding, "device") == device: 
                    self.validateObject(root, object, corresponding)

    # TODO Get this list of known values checked.
    def __init__(self, host, guest):
        self.errors = []
        self.objects = {}   
        self.ignore = {}
        self.checks = {} 
        self.host = host
        self.guest = guest
        
        self.ignore["vm"] = [] 
        self.ignore["vif"] = []
        self.ignore["vbd"] = []
        self.ignore["vdi"] = []

        self.checks["vm"]       =   []
        self.checks["vif"]      =   []
        self.checks["vbd"]      =   []
        self.checks["vdi"]      =   []
        
        self.update()

    def update(self):
        self.objects["vm"] = {}
        self.objects["vif"] = {}
        self.objects["vbd"] = {}
        self.objects["vdi"] = {}

        self.objects["vm"][self.guest] = self.getparameters("vm", self.guest)
        for vif in self.host.minimalList("vif-list", args="vm-uuid=%s" % (self.guest)):
            self.objects["vif"][vif] = self.getparameters("vif", vif)
        for vbd in self.host.minimalList("vbd-list", args="vm-uuid=%s" % (self.guest)):
            self.objects["vbd"][vbd] = self.getparameters("vbd", vbd)
            vdi = self.host.genParamGet("vbd", vbd, "vdi-uuid")
            self.objects["vdi"][vdi] = self.getparameters("vdi", vdi)

    def test(self, uuid, addignore=[], addchecks=[]):
        for root,parameter in addignore:
            self.ignore[root].append(parameter)
        for root,parameter,check in addchecks:
            self.checks[root].append((parameter, check))

        self.errors = []

        self.validateObject("vm", self.guest, uuid)
        self.validateMultiple("vif", uuid)
        self.validateMultiple("vbd", uuid)

        for root,parameter in addignore:
            self.ignore[root].remove(parameter)
        for root,parameter,check in addchecks:
            for p,c in self.checks[root]:
                if p == parameter:
                    self.checks[root].remove((parameter, check))

        return self.errors

    def checkSnapshotInfo(self, x, y, alpha, beta):
        try: snapshotparams = dict([ a.split(": ") for a in y.split("; ") ])
        except: return False 
        current = self.host.genParamGet("vm", alpha, "power-state")
        expected = {"disk-snapshot-type"        :   "crash_consistent",
                    "power-state-at-snapshot"   :   current.capitalize()}
        return snapshotparams == expected 

    def checkSnapshotTime(self, x, y, alpha, beta):
        return xenrt.util.timenow() - xenrt.util.parseXapiTime(y) < 300

    # The equality check deals with ISOs. 
    def validatevdi(self, x, y, alpha, beta): return (x == y) or self.validateObject("vdi", x, y)

    # Expected to change without user action.
    IGNOREVOLATILE =  [("vm",  "VCPUs-utilisation"),
                       ("vif", "io_write_kbs"),
                       ("vif", "io_read_kbs"),
                       ("vbd", "io_write_kbs"),
                       ("vbd", "io_read_kbs"),
                       ("vdi", "physical-utilisation")]
    
    # Expected to change when we snapshot, checkpoint or create a template. 
    IGNORECOMMON =    [("vm",  "allowed-operations"),
                       ("vm",  "resident-on"),
                       ("vif", "uuid"),
                       ("vif", "allowed-operations"),
                       ("vbd", "uuid"),
                       ("vbd", "allowed-operations"),
                       ("vdi", "uuid"),
                       ("vdi", "vbd-uuids"),
                       ("vdi", "allowed-operations"),
                       ("vdi", "location"),
                       ("vdi", "sm-config")] # XXX vmhint not present for snapshots etc.

    COMMONCHECKS =    [("vbd", "vdi-uuid",       validatevdi)]

    # Expected to change when we snapshot or checkpoint.
    SNAPPOINTIGNORE = [('vm',  'uuid'),
                       ('vm',  'name-label'),
                       ('vm',  'dom-id'),
                       ('vm',  'console-uuids'),
                       ('vif', 'vm-uuid'),
                       ('vif', 'vm-name-label'),
                       ('vbd', 'vm-uuid'),
                       ('vbd', 'vm-name-label')]

    # Validate when snapshotting or checkpointing.
    SNAPPOINTCHECKS = [("vm",  "is-a-snapshot",  lambda s,x,y,a,b:x == "false" and y == "true"),
                       ("vm",  "snapshot-of",    lambda s,x,y,a,b:y == a),
                       ("vm",  "snapshots",      lambda s,x,y,a,b:b in x.split("; ")),
                       ("vm",  "snapshot-info",  checkSnapshotInfo),
                       ("vm",  "parent",         lambda s,x,y,a,b:x == b),
                       ("vm",  "children",       lambda s,x,y,a,b:y == a),
                       ("vm",  "is-a-template",  lambda s,x,y,a,b:x == "false" and y == "true"),
                       ("vm",  "snapshot-time",  checkSnapshotTime),
                       ("vdi", "snapshot-time",  checkSnapshotTime),
                       ("vdi", "is-a-snapshot",  lambda s,x,y,a,b:x == "false" and y == "true"),
                       ("vdi", "snapshot-of",    lambda s,x,y,a,b:y == a),
                       ("vdi", "snapshots",      lambda s,x,y,a,b:b in x.split("; "))]

    # Values we lose if a VM is halted.
    IGNOREIFHALTED =  [("vm",  "guest-metrics-last-updated"),
                       ("vm",  "PV-drivers-up-to-date"),
                       ("vm",  "networks"),
                       ("vm",  "live"),
                       ("vm",  "other"),
                       ("vm",  "memory"),
                       ("vm",  "os-version"),
                       ("vm",  "disks"),
                       ("vm",  "PV-drivers-version"),
                       ("vm",  "allowed-VBD-devices"), # XXX
                       ("vm",  "allowed-VIF-devices"), # XXX
                       ("vif", "currently-attached"),
                       ("vbd", "currently-attached")]

    def validateGuest(self, uuid, addignore=[], addchecks=[]):
        addignore = addignore + self.IGNOREVOLATILE
        return self.test(uuid, addignore, addchecks)

    def validateCheckpoint(self, uuid):
        addignore   = [("vm",  "suspend-VDI-uuid"),
                       ("vbd", "current-operations"), 
                       ("vbd", "attachable"), 
                       ("vdi", "current-operations")] # XXX Why?
        addchecks   = [("vm",  "power-state",    lambda s,x,y,a,b:y == "suspended")]
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON + self.SNAPPOINTIGNORE
        addchecks += self.COMMONCHECKS + self.SNAPPOINTCHECKS
        return self.test(uuid, addignore, addchecks)

    def validateCheckpointRollback(self, uuid):
        addignore   = [("vm",  "suspend-VDI-uuid"), #XXX Why?
                       ("vm",  "parent"),           
                       ("vdi", "snapshots"),
                       ("vdi", "xenstore-data"),    
                       ("vm",  "dom-id"),            
                       ("vm",  "guest-metrics-last-updated"), 
                       ("vm",  "platform"), 
                       ("vm",  "other"), 
                       ("vm",  "PV-drivers-version"),
                       ("vm",  "possible-hosts"),
                       ("vm",  "memory-actual")] # XXX Discrepancy: memory-actual (268435456, 16384) transient
        addchecks   = [("vm",  "power-state",    lambda s,x,y,a,b:y == "suspended")]
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON
        addchecks += self.COMMONCHECKS
        return self.test(uuid, addignore, addchecks)

    def validateSnapshot(self, uuid):
        addignore   = [("vm",  "suspend-VDI-uuid")] # XXX Why?
        addchecks   = [("vm",  "power-state",    lambda s,x,y,a,b:y == "halted")]
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON + self.SNAPPOINTIGNORE + self.IGNOREIFHALTED
        addchecks += self.COMMONCHECKS + self.SNAPPOINTCHECKS
        return self.test(uuid, addignore, addchecks)

    def validateSnapshotRollback(self, uuid):
        addignore   = [("vm",  "suspend-VDI-uuid"), # XXX Why?
                       ("vm",  "parent"),
                       ("vm",  "dom-id"),
                       ("vm",  "possible-hosts"),
                       ("vdi", "xenstore-data"),
                       ("vdi", "snapshots")]
        addchecks   = [("vm",  "power-state",    lambda s,x,y,a,b:y == "halted")]
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON + self.IGNOREIFHALTED
        addchecks += self.COMMONCHECKS
        return self.test(uuid, addignore, addchecks)

    def validateTemplate(self, uuid):
        addignore   = [("vm",  "snapshots"), 
                       ("vm",  "other-config"), 
                       ("vif", "MAC"),
                       ("vif", "MAC-autogenerated"),
                       ("vdi", "snapshots")]
        addchecks   = [("vm",  "power-state",    lambda s,x,y,a,b:y == "halted"),
                       ("vm",  "is-a-template",  lambda s,x,y,a,b:x == "false" and y == "true")]
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON + \
                     self.SNAPPOINTIGNORE + self.IGNOREIFHALTED
        addchecks += self.COMMONCHECKS
        return self.test(uuid, addignore, addchecks)

    def validateInstance(self, uuid):
        addignore = [("vm",  "xenstore-data"), 
                     ("vm",  "start-time"),
                     ("vm",  "install-time"),
                     ("vm",  "last-boot-record"),
                     ("vm",  "guest-metrics-last-updated"),
                     ("vm",  "parent"),
                     ("vm",  "snapshots"),
                     ("vm",  "other-config"),
                     ("vm",  "networks"),
                     ("vif", "MAC"),
                     ("vif", "MAC-autogenerated"),
                     ("vdi", "snapshots"),
                     ("vdi", "xenstore-data")]
        addchecks = []
        addignore += self.IGNOREVOLATILE + self.IGNORECOMMON + \
                     self.SNAPPOINTIGNORE
        addchecks += self.COMMONCHECKS
        return self.test(uuid, addignore, addchecks)

class _SnappointRollback(xenrt.TestCase):
    """Superclass for snapshot, checkpoint and rollback
       test cases."""

    VM = "SNAPPOINT"
    DISTRO = "ws08r2-x64"
    UNINSTALL = False
    SMOKETEST = False
    ARCH = "x86-32"
    EXISTING_GUEST = False

    INITIALSTATE = "UP"
    OPERATION = ""

    def snapshot(self):
        self.snappoint = self.guest.snapshot() 
        self.checkSnapshot()

    def quiesced(self):
        self.snappoint = self.guest.snapshot(quiesced=True)
        self.checkSnapshot()

    def checkpoint(self):
        self.snappoint = self.guest.checkpoint()
        self.checkCheckpoint()    
    
    def checkSnapshot(self):
        if self.INITIALSTATE == "UP":
            self.guest.checkHealth()
        addignore = [("vm",  "parent"),    
                     ("vm",  "snapshots"), 
                     ("vbd", "allowed-operations")] # XXX (pause; unpause; attach, pause; unpause)
        errors = self.comparer.validateGuest(self.guest.getUUID(), addignore=addignore)
        if errors:
            xenrt.TEC().warning("Check failed after snapshot: %s" % (errors))
            #raise xenrt.XRTFailure("Check failed after snapshot: %s" % (errors))
        self.comparer.update()
        errors = self.comparer.validateSnapshot(self.snappoint)
        if errors:
            xenrt.TEC().warning("Snapshot check failed: %s" % (errors))
            #raise xenrt.XRTFailure("Snapshot check failed: %s" % (errors))
 
    def checkCheckpoint(self):
        if self.INITIALSTATE == "UP":
            # Make sure we're not in the suspended state any more
            domains = self.guest.getHost().listDomains(includeS=True)
            if not domains.has_key(self.guest.getUUID()):
                raise xenrt.XRTFailure(\
                    "Guest not found on host after checkpoint")
            if domains[self.guest.getUUID()][3] == \
                   xenrt.GenericHost.STATE_SHUTDOWN:
                raise xenrt.XRTFailure("Guest still in suspended state "
                                       "after checkpoint")
            self.guest.checkHealth()
        addignore = [("vm",  "parent"),    
                     ("vm",  "snapshots"),
                     ("vm",  "suspend-VDI-uuid"), 
                     ("vbd", "allowed-operations")] # XXX (pause; unpause; attach, pause; unpause)
        errors = self.comparer.validateGuest(self.guest.getUUID(), addignore=addignore)
        if errors:
            xenrt.TEC().warning("Check failed after checkpoint: %s" % (errors))
            #raise xenrt.XRTFailure("Check failed after checkpoint: %s" % (errors))
        self.comparer.update()
        errors = self.comparer.validateCheckpoint(self.snappoint)
        if errors:
            xenrt.TEC().warning("Checkpoint check failed: %s" % (errors))
            #raise xenrt.XRTFailure("Checkpoint check failed: %s" % (errors))

    def rollback(self):
        self.guest.revert(self.snappoint) 
        if self.OPERATION == "checkpoint":
            errors = self.comparer.validateCheckpointRollback(self.guest.getUUID())
            if errors:
                xenrt.TEC().warning("Rollback check failed: %s" % (errors))
                #raise xenrt.XRTFailure("Rollback check failed: %s" % (errors))
            self.guest.resume()
        elif self.OPERATION == "snapshot" or self.OPERATION == "quiesced":
            errors = self.comparer.validateSnapshotRollback(self.guest.getUUID())
            if errors:
                xenrt.TEC().warning("Rollback check failed: %s" % (errors))
                #raise xenrt.XRTFailure("Rollback check failed: %s" % (errors))
            self.guest.start()
        self.guest.checkHealth()
        self.comparer.update()

    def removeSnapshot(self, uuid):
        self.guest.removeSnapshot(uuid)

    def prepare(self, arglist):
        self.snappoint = None
        self.host = self.getDefaultHost()
        self.sr = self.host.getLocalSR()
        self.host.addExtraLogFile("/var/log/SMlog")
        if not self.EXISTING_GUEST:
            self.guest = None
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "guest":
                    self.guest = self.getGuest("%s"%l[1])
                    self.guest.setName(l[1])
        if not self.guest and not self.SMOKETEST:
            name = "%s-%s" % (self.VM, self.DISTRO)
            self.guest = self.getGuest(name)
        if not self.guest:
            if self.SMOKETEST:
                self.guest = xenrt.lib.xenserver.guest.createVM(\
                    self.host,
                    xenrt.randomGuestName(),
                    distro=self.DISTRO,
                    arch=self.ARCH,
                    memory=1024,
                    sr=self.sr,
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT)
            elif self.DISTRO == "DEFAULT":
                self.guest = self.host.createGenericLinuxGuest(name=name, sr=self.sr)
            else:
                self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO, 
                                                                 memory=1024,
                                                                 sr=self.sr)
                self.guest.setName(name)
            if not self.SMOKETEST:
                xenrt.TEC().registry.guestPut(name, self.guest)
        try:
            if self.guest.getState() == "DOWN":
                self.guest.start()
            else:
                self.guest.reboot()
            self.guest.checkHealth()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Guest broken before we started: %s" % (str(e)))
        if self.UNINSTALL:
            xenrt.TEC().logverbose("Marking %s for cleanup." % (self.guest.getName()))
            self.uninstallOnCleanup(self.guest)
        self.guest.setState(self.INITIALSTATE)
        if self.OPERATION == "quiesced":
            self.guest.installVSSTools()
            self.guest.enableVSS()
        self.comparer = Comparer(self.host, self.guest.getUUID())

    def run(self, arglist):
        result = self.runSubcase(self.OPERATION, (), "Live", self.OPERATION.capitalize())
        if not result == xenrt.RESULT_PASS: return
        self.runSubcase("rollback", (), "Live", "Rollback")

    def postRun(self):
        try: self.removeSnapshot(self.snappoint)
        except: pass
        try: self.guest.disableVSS()
        except: pass
        try: self.guest.setState("DOWN")
        except: pass
        try: self.host.waitForCoalesce(self.sr)
        except: pass
    
class _SnappointTrees(_SnappointRollback):
    """Superclass for creating arbitrary trees of snappoints."""

    SNAPTREE = ""

    def _snappoint(self, method):
        current = self.snappoint
        method(self)
        self.snappoint = _SnappointTrees.SnappointTreeNode(self.snappoint)
        if current: 
            current.children.append(self.snappoint)
            self.snappoint.parent = current
        else: 
            self.snaptrees.append(self.snappoint)

    def checkpoint(self):
        self._snappoint(_SnappointRollback.checkpoint)

    def snapshot(self):
        self._snappoint(_SnappointRollback.snapshot)

    def rollback(self, snappoint):
        self.snappoint = snappoint.value         
        _SnappointRollback.rollback(self)
        self.snappoint = snappoint

    def removeSnapshot(self, snappoint):
        if not snappoint.parent:
            self.snaptrees.remove(snappoint)
            for child in snappoint.children:
                child.parent = None
                self.snaptrees.append(child)
        else:
            for child in snappoint.children:
                child.parent = snappoint.parent
                snappoint.parent.children.append(child)
            snappoint.parent.children.remove(snappoint)
            snappoint.parent = None
            snappoint.children = []
        _SnappointRollback.removeSnapshot(self, snappoint.value)
        self.checkTree()

    class SnappointTreeNode:

        def __init__(self, value):
            self.value = value
            self.id = "" 
            self.parent = ""
            self.children = []

        def traverse(self):
            yield self
            for child in self.children:
                for node in child.traverse():
                    yield node 

        def depth(self):
            if not self.children:
                return 1
            else:
                return 1 + max([ x.depth() for x in self.children ])

        def show(self):
            s = "<snappoint id='%s' uuid='%s'>" % (self.id, self.value)
            for child in self.children: s += child.show()
            s += "</snappoint>"
            return s

    def handleNode(self, node):
        if node.nodeName == "checkpoint":
            id = node.getAttribute("id")
            self.checkpoint()
        elif node.nodeName == "snapshot":
            id = node.getAttribute("id")
            self.snapshot()
        else:
            return 
        if id: self.snappoint.id = id
        current = self.snappoint
        for x in node.childNodes:
            if not self.snappoint == current:
                self.rollback(current)
            self.handleNode(x)

    def checkTree(self):
        for tree in self.snaptrees:
            xenrt.TEC().logverbose("TREE: %s" % (tree.show()))
            for node in tree.traverse():
                uuid = node.value
                children = self.host.genParamGet("snapshot", uuid, "children").split("; ")
                if children == ['']:
                    children = []
                if node == self.snappoint: 
                    expected = len(node.children) + 1
                else: 
                    expected = len(node.children)
                if not len(children) == expected:
                    raise xenrt.XRTFailure("Differing number of children. (%s, %s)" %
                                           (children, node.children))
                for child in node.children:
                    if not child.value in children:
                        raise xenrt.XRTFailure("Child mismatch: %s, %s" % 
                                               (child.value, children))
                    parent = self.host.genParamGet("snapshot", child.value, "parent")
                    if not parent == node.value:
                        raise xenrt.XRTFailure("Parent mismatch: %s, %s" % 
                                               (node.value, parent))

    def getNodeById(self, id):
        for tree in self.snaptrees:
            for x in tree.traverse():
                if x.id == id: return x

    def createSnappointGraph(self):
        xmltree = xml.dom.minidom.parseString(self.SNAPTREE)
        self.handleNode(xmltree.childNodes[0])
        self.checkTree()

    def prepare(self, arglist):
        self.snaptrees = [] 
        _SnappointRollback.prepare(self, arglist)

    def run(self, arglist):
        return self.runSubcase("createSnappointGraph", (), "Live", "CreateTree")

    def postRun(self):
        _SnappointRollback.postRun(self)
        for tree in self.snaptrees:
            for snappoint in tree.traverse():
                try: self.removeSnapshot(snappoint)
                except: pass
        try: self.host.waitForCoalesce()
        except: pass

class _MixedSnapshots(_SnappointTrees):
    """Snappoint stress tests base class."""

    ITERATIONS = None 
    MAXCHAIN = 30

    OPERATION = "checkpoint"

    def createRandomGraph(self, snapshots):
        for i in range(snapshots):
            xenrt.TEC().logverbose("Starting iteration %s..." % (i))
            if self.snappoint:
                depth = self.snappoint.depth()
                if depth >= self.MAXCHAIN:
                    self.rollback(self.getNodeById(random.randrange(i)))
                    continue
            self.checkpoint()   
            self.snappoint.id = i
            if i and random.choice([True, False]):
                self.rollback(self.getNodeById(random.randrange(i)))
            self.checkTree()
            xenrt.TEC().logverbose("Running vgs prior to waiting for coalesce")
            vgs = "/usr/sbin/vgs"
            try:
                self.host.execdom0("%s" % vgs)
            except Exception, e:
                if string.find(str(e), "SSH command exited with error (%s)" % vgs) > -1:
                    vgs = "/sbin/vgs"
                    self.host.execdom0("%s" % vgs)
            self.host.waitForCoalesce(self.sr)
            xenrt.TEC().logverbose("Running vgs after waiting for coalesce")
            self.host.execdom0("%s" % vgs)

    def run(self, arglist):
        return self.runSubcase("createRandomGraph", (self.ITERATIONS), "Live", "RandomTree")

class _CheckpointOperation(_SnappointRollback):
    """Superclass for testing operations on checkpoints."""

    TESTOP = ""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"

    def createTemplate(self):
        xenrt.TEC().logverbose("Turning snapshot into template...")
        name = xenrt.randomGuestName()
        cli = self.host.getCLIInstance()
        command = ["snapshot-clone"]
        command.append("snapshot-uuid=%s" % (self.snappoint))
        command.append("new-name-label=%s" % (name))
        try:
            self.template = cli.execute(string.join(command), strip=True)
        except xenrt.XRTFailure, e:
            if re.search("Unknown command", str(e)):
                xenrt.TEC().warning("The snapshot-clone command doesn't appear to exist.")
                command = ["snapshot-create-template"]
                command.append("snapshot-uuid=%s" % (self.snappoint))
                command.append("new-name-label=%s" % (name))
                self.template = cli.execute(string.join(command), strip=True)
            else:
                raise e
        self.removeTemplateOnCleanup(self.host, self.template)
        errors = self.comparer.validateTemplate(self.template)
        if errors:
            xenrt.TEC().warning("Template check failed: %s" % (errors))
            #raise xenrt.XRTFailure("Template check failed: %s" % (errors))

    def instantiate(self):
        instance = self.guest.instantiateSnapshot(self.template)
        self.uninstallOnCleanup(instance)
        instance.start()
        instance.checkHealth()
        errors = self.comparer.validateInstance(instance.getUUID())
        if errors:
            xenrt.TEC().warning("Instance check failed: %s" % (errors))
            #raise xenrt.XRTFailure("Instance check failed: %s" % (errors))

    def clone(self):
        xenrt.TEC().logverbose("Attempting to clone snapshot.")
        cli = self.host.getCLIInstance()
        command = ["vm-clone"]
        command.append("uuid=%s" % (self.snappoint))
        command.append("new-name-label=%s" % (xenrt.randomGuestName()))
        try: cli.execute(string.join(command))
        except xenrt.XRTFailure, e:
            xenrt.TEC().warning("Clone failed.")
            if not re.search("VM_IS_SNAPSHOT", e.data):
                raise xenrt.XRTFailure("Clone failed with unexpected error (%s)" % (str(e)))
        else: 
            xenrt.TEC().logverbose("Snapshot clone succeeded.")
    
    def copy(self):
        xenrt.TEC().logverbose("Attempting to copy snapshot.")
        cli = self.host.getCLIInstance()
        command = ["vm-copy"]
        command.append("uuid=%s" % (self.snappoint))
        command.append("new-name-label=%s" % (xenrt.randomGuestName()))
        try: cli.execute(string.join(command))
        except xenrt.XRTFailure, e:
            xenrt.TEC().warning("Copy failed.")
            if not re.search("VM_IS_SNAPSHOT", e.data):
                raise xenrt.XRTFailure("Copy failed with unexpected error (%s)" % (str(e)))
        else: 
            xenrt.TEC().logverbose("Snapshot copy succeeded.")

    def rollbackdeleted(self):
        xenrt.TEC().logverbose("Uninstalling original VM.")
        self.guest.shutdown()
        self.guest.lifecycleOperation("vm-destroy", force=True)
        _SnappointRollback.rollback(self)
 
    def run(self, arglist):
        result = self.runSubcase(self.OPERATION, (), "Live", self.OPERATION.capitalize())
        if not result == xenrt.RESULT_PASS: return
        return self.runSubcase(self.TESTOP, (), "Live", self.TESTOP.capitalize())

class _DeleteSnappoint(_SnappointTrees):

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"

    SNAPTREE = ""

    def rmtest(self):
        target = self.getNodeById("0")
        self.removeSnapshot(target)

    def run(self, arglist):
        result = _SnappointTrees.run(self, arglist)
        if not result == xenrt.RESULT_PASS: return
        self.runSubcase("rmtest", (), "Live", "Remove")

class _CheckpointConsistency(_SnappointRollback):
    """VM checkpoint and rollback consistency."""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"
    WORKLOADS = ["Prime95",
                 "SQLIOSim"]
    UNINSTALL = True

    def checkpoint(self):
        self.workloads = self.guest.startWorkloads(self.WORKLOADS)
        self.processes = self.guest.xmlrpcPS()
        xenrt.TEC().logverbose("Processes before snapshot: %s" % (self.processes))
        self.guest.xmlrpcCreateFile("c:\\before_snapshot", "")
        _SnappointRollback.checkpoint(self)
        self.guest.xmlrpcCreateFile("c:\\after_snapshot", "")
        for w in self.workloads: 
            w.stop()
            w.stopped = False

    def rollback(self):
        self.guest.xmlrpcReadFile("c:\\before_snapshot")
        self.guest.xmlrpcReadFile("c:\\after_snapshot")
        _SnappointRollback.rollback(self)
        self.guest.xmlrpcReadFile("c:\\before_snapshot")
        try: self.guest.xmlrpcReadFile("c:\\after_snapshot")
        except: pass
        else: raise xenrt.XRTFailure("Post-snappoint flag still present.")
        ps = self.guest.xmlrpcPS()
        xenrt.TEC().logverbose("Processes after revert: %s" % (ps))
        for w in self.workloads:
            if not w.process in ps:
                if not w.process in self.processes:
                    xenrt.TEC().warning("Workload didn't seem to start properly: %s" % (w.process))
                else:
                    raise xenrt.XRTFailure("Workload not running after rollback. (%s, %s)" %
                                           (w, ps))
        for w in self.workloads: 
            w.stop()
            w.stopped = False
        
    def postRun(self):
        try: self.guest.setState("UP")
        except: pass
        try: 
            for w in self.workloads: w.stop()
        except: pass
        try: self.guest.xmlrpcRemoveFile("c:\\before_snapshot")
        except: pass
        try: self.guest.xmlrpcRemoveFile("c:\\after_snapshot")
        except: pass
        _SnappointRollback.postRun(self)

class TC9207(_SnappointRollback):
    """Snapshot and rollback of a running VM."""

    INITIALSTATE = "UP"
    OPERATION = "snapshot"

class TC9208(_SnappointRollback):
    """Snapshot and rollback of a suspended VM."""
 
    INITIALSTATE = "SUSPENDED"
    OPERATION = "snapshot"

class TC9209(_SnappointRollback):
    """Snapshot and rollback of a shutdown VM."""

    INITIALSTATE = "DOWN"
    OPERATION = "snapshot"

class TC9210(_SnappointRollback):
    """Checkpoint and rollback of a running VM."""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"

class TC9211(_SnappointRollback):
    """Checkpoint and rollback of a suspended VM."""

    INITIALSTATE = "SUSPENDED"
    OPERATION = "checkpoint"

class TCCheckpoint(_SnappointRollback):
    """Checkpoint and rollback of a running VM."""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"
    EXISTING_GUEST = True

    def prepare(self, arglist):
        self.guest = self.getGuest("winguest")
        _SnappointRollback.prepare(self, arglist)

class TC9212(_CheckpointOperation):
    """Rollback of a deleted VM fails."""

    TESTOP = "rollbackdeleted"

class TC9213(_SnappointRollback):
    """Checkpoint of a VM with shared disks fails."""

    INITIALSTATE = "UP"

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.sharer = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.sharer)
        # TODO Set up a shared disk between these two VMs.

    def sharedcheckpoint(self):
        try: _SnappointRollback.checkpoint(self)
        except: pass
        else: raise xenrt.XRTFailure("Checkpoint succeeded.")

    def run(self, arglist):
        self.runSubcase("sharedcheckpoint", (), "Live", "SharedCheckpoint")

class TC9214(_CheckpointOperation):
    """Copying a checkpoint fails."""

    TESTOP = "copy"

class TC9215(_CheckpointOperation):
    """Clone a checkpoint fails."""

    TESTOP = "clone"

class TC9216(_CheckpointOperation):
    """Turn a checkpoint into a template."""

    TESTOP = "createTemplate"

    def prepare(self, arglist):
        self.template = None
        _CheckpointOperation.prepare(self, arglist)
        self.guest.preCloneTailor()

    def run(self, arglist):
        result = _CheckpointOperation.run(self, arglist)
        if not result == xenrt.RESULT_PASS: return
        self.runSubcase("instantiate", (), "Live", "Instantiate")

class TC9217(_CheckpointOperation):
    """Export of a checkpoint."""

    TESTOP = "exportSnapshot"

    def exportSnapshot(self):
        xenrt.TEC().logverbose("Trying to export snapshot.")
        command = ["xe"]
        command.append("snapshot-export-to-template")
        command.append("snapshot-uuid=%s" % (self.snappoint))
        command.append("filename=%s" % (self.image))
        command = string.join(command)
        command = xenrt.lib.xenserver.cli.buildCommandLine(self.host, command)
        result = self.cliguest.execguest(command, timeout=3600).strip()
        if not result == "Export succeeded":
            raise xenrt.XRTFailure("Export failed. (%s)" % (result))

    def importSnapshot(self):
        xenrt.TEC().logverbose("Removing original snapshot.")
        self.removeSnapshot(self.snappoint)
        xenrt.TEC().logverbose("Trying to import exported snapshot.")
        command = ["xe"]
        command.append("vm-import")
        command.append("filename=%s" % (self.image))
        command = string.join(command)
        command = xenrt.lib.xenserver.cli.buildCommandLine(self.host, command)
        self.template = self.cliguest.execguest(command, timeout=3600).strip()
        self.removeTemplateOnCleanup(self.host, self.template)
        allowed = [("vm",  "start-time"), 
                   ("vm",  "install-time"),
                   ("vm",  "memory-actual"), 
                   ("vm",  "VCPUs-number"),
                   ("vm",  "parent")] 
        errors = self.comparer.validateTemplate(self.template)
        errors = filter(lambda x:not x in allowed, errors)
        if errors:
            xenrt.TEC().warning("Template check failed: %s" % (errors))
            #raise xenrt.XRTFailure("Template check failed: %s" % (errors))

    def prepare(self, arglist):
        _CheckpointOperation.prepare(self, arglist)
        hostarch = self.host.execdom0("uname -m").strip()
        if hostarch.endswith("64"):
            arch="x86-64"
        else:
            arch="x86-32"
        self.cliguest = self.host.createGenericLinuxGuest(arch=arch)
        self.uninstallOnCleanup(self.cliguest)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   self.cliguest.getUUID(),
                                                  "device",
                                                  "userdevice=%s" % 
                                                  (self.cliguest.createDisk(sizebytes=30*1024**3)))
        self.cliguest.execguest("mkfs.ext2 /dev/%s" % (device))
        self.cliguest.execguest("mount /dev/%s /mnt" % (device))
        self.image = "/mnt/export-checkpoint.img" 
        self.cliguest.installCarbonLinuxCLI()
        self.getLogsFrom(self.cliguest)
        self.guest.preCloneTailor()

    def run(self, arglist):
        result = _CheckpointOperation.run(self, arglist)
        if not result == xenrt.RESULT_PASS: return
        result = self.runSubcase("importSnapshot", (), "Live", "ImportSnapshot")
        if not result == xenrt.RESULT_PASS: return
        self.runSubcase("instantiate", (), "Live", "Instantiate")

class TC9220(_DeleteSnappoint):
    """Delete the root node of a snapshot tree."""

    SNAPTREE = """
<checkpoint id="0">
  <checkpoint/>
  <checkpoint/>
</checkpoint>
"""

class TC9221(_DeleteSnappoint):
    """Delete an internal node of a snapshot tree."""

    SNAPTREE = """
<checkpoint>
  <checkpoint id="0">
    <checkpoint/>
    <checkpoint/>
  </checkpoint>
</checkpoint>
"""

class TC9224(_SnappointRollback):
    """Quiesced snapshot and rollback of a running VM."""

    INITIALSTATE = "UP"
    OPERATION = "quiesced"
    DISTRO = "ws08r2-x64"

class TC9226(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2003 EE SP2"""

    DISTRO = "w2k3eesp2"

class TC9227(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2003 EE SP2 x64"""

    DISTRO = "w2k3eesp2-x64"

class TC9228(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2008 SP2"""

    DISTRO = "ws08sp2-x86"

class TC9229(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2008 SP2 x64"""

    DISTRO = "ws08sp2-x64"

class TC9713(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2008 R2 x64"""

    DISTRO = "ws08r2-x64"

class TC12556(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2008 R2 SP1 x64"""

    DISTRO = "ws08r2sp1-x64"

class TC9230(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Vista EE SP2"""

    DISTRO = "vistaeesp2"

class TC9231(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Vista EE SP2 x64"""

    DISTRO = "vistaeesp2-x64"

class TC9232(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows XP SP3"""

    DISTRO = "winxpsp3"

class TC9233(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 2000 SP4"""

    DISTRO = "w2kassp4"

class TC9714(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 7"""

    DISTRO = "win7-x86"
    
class TC9715(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 7 x64"""

    DISTRO = "win7-x64"

class TC12557(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 7 SP1"""

    DISTRO = "win7sp1-x86"
    
class TC12558(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 7 SP1 x64"""

    DISTRO = "win7sp1-x64"
    
class TC20686(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 8 x86"""
    DISTRO = "win8-x86"
    
class TC20687(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows Server 2012 (x64)"""
    DISTRO = "ws12-x64"
    
class TC20002(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 81 x64"""
    DISTRO = "win81-x64"
    
class TC21644(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows server 2012 """
    DISTRO = "win81-x64"
    
class TC21645(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 81 x64"""
    DISTRO = "win81-x64"

class TC26423(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 10 x86"""
    DISTRO = "win10-x86"

class TC26424(_CheckpointConsistency):
    """Checkpoint and rollback consistency on Windows 10 x64"""
    DISTRO = "win10-x64"

class TC9234(_SnappointTrees):
    """Check snapshot trees are preserved across pool join."""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"
    
    SNAPTREE = """
<checkpoint>
  <checkpoint>
    <checkpoint/>
  </checkpoint>
</checkpoint>
"""

    def prepare(self, arglist):
        _SnappointTrees.prepare(self, arglist)
        self.master = xenrt.TEC().registry.hostGet("RESOURCE_HOST_1")
        pv = xenrt.TEC().lookup("PRODUCT_VERSION")
        self.pool = xenrt.lib.xenserver.poolFactory(pv)(self.master)

    def join(self):
        self.pool.addHost(self.host)

    def run(self, arglist):
        result = _SnappointTrees.run(self, arglist)
        if not result == xenrt.RESULT_PASS: return
        result = self.runSubcase("join", (), "Live", "Join")
        if not result == xenrt.RESULT_PASS: return
        return self.runSubcase("checkTrees", (), "Live", "CheckTrees")

    def postRun(self):
        _SnappointTrees.postRun(self)
        try: self.pool.eject(self.host)
        except: pass

class TC9237(_MixedSnapshots):
    """Snappoint stress test."""

    ITERATIONS = 50

class _TCVMOpAfterCheckpoint(xenrt.TestCase):

    WINDOWS = False

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        if self.WINDOWS:
            self.guest = self.host.createGenericWindowsGuest()
        else:
            self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.checkpoint = self.guest.checkpoint()

    def run(self, arglist=None):
        raise xenrt.XRTError("Unimplemented")

    def postRun(self):
        try:
            self.guest.removeSnapshot(self.checkpoint)
        except Exception, e:
            xenrt.TEC().logverbose("Exception removing checkpoint: %s" %
                                   (str(e)))

class TC9316(_TCVMOpAfterCheckpoint):
    """Shut down a Linux VM previously checkpointed using in-VM shutdown"""

    def run(self, arglist=None):
        self.guest.unenlightenedShutdown()
        self.guest.poll("DOWN")

class TC9317(TC9316):
    """Shut down a Windows VM previously checkpointed using in-VM shutdown"""

    WINDOWS = True

class TC9321(_TCVMOpAfterCheckpoint):
    """Verify network connectivity of a Linux VM previously checkpointed"""

    def run(self, arglist=None):
        self.guest.checkReachable()

class TC9320(TC9321):
    """Verify network connectivity of a Windows VM previously checkpointed"""

    WINDOWS = True

class TC9236(xenrt.TestCase):

    SNAPSHOTS = 3

    def prepare(self, arglist):
        self.snapshots = {}
        self.host = self.getDefaultHost()
        self.guest = self.host.createBasicGuest(distro="debian50")

    def run(self, arglist):
        for i in range(self.SNAPSHOTS):
            self.snapshots[i] = self.guest.snapshot()
        self.host.upgrade()
        for i in self.snapshots:
            parent = self.host.genParamGet("snapshot", self.snapshots[i], "parent")
            children = self.host.genParamGet("snapshot", self.snapshots[i], "children").split(";")
            if i-1 in self.snapshots:
                if not parent == self.snapshots[i-1]:
                    raise xenrt.XRTFailure("Snapshot has unexpected parent field. (%s != %s)" %
                                           (parent, self.snapshots[i-1])) 
            if i+1 in self.snapshots:
                if not self.snapshots[i+1] in children:
                    raise xenrt.XRTFailure("Snapshot has unexpected children. (%s not in %s)" %
                                           (self.snapshots[i+1], children))
    
class _CheckpointSmoketest(_SnappointRollback):
    """VM checkpoint and rollback smoketest."""

    INITIALSTATE = "UP"
    OPERATION = "checkpoint"
    UNINSTALL = True
    SMOKETEST = True

    def checkpoint(self):
        if self.guest.windows:
            self.guest.xmlrpcCreateFile("c:\\before_snapshot", "")
        else:
            self.guest.execguest("touch /tmp/before_snapshot")
        _SnappointRollback.checkpoint(self)
        if self.guest.windows:
            self.guest.xmlrpcCreateFile("c:\\after_snapshot", "")
        else:
            self.guest.execguest("touch /tmp/after_snapshot")

    def rollback(self):
        if self.guest.windows:
            self.guest.xmlrpcReadFile("c:\\before_snapshot")
            self.guest.xmlrpcReadFile("c:\\after_snapshot")
        else:
            self.guest.execguest("test -e /tmp/before_snapshot")
            self.guest.execguest("test -e /tmp/after_snapshot")
        _SnappointRollback.rollback(self)
        if self.guest.windows:
            self.guest.xmlrpcReadFile("c:\\before_snapshot")
        else:
            self.guest.execguest("test -e /tmp/before_snapshot")
        try:
            if self.guest.windows:
                self.guest.xmlrpcReadFile("c:\\after_snapshot")
            else:
                self.guest.execguest("test -e /tmp/after_snapshot")
        except:
            pass
        else:
            raise xenrt.XRTFailure("Post-snappoint flag still present.")
        
    def postRun(self):
        try: self.guest.setState("UP")
        except: pass
        try:
            if self.guest.windows:
                self.guest.xmlrpcRemoveFile("c:\\before_snapshot")
            else:
                self.guest.execguest("rm -f /tmp/before_snapshot")
        except:
            pass
        try:
            if self.guest.windows:
                self.guest.xmlrpcRemoveFile("c:\\after_snapshot")
            else:
                self.guest.execguest("rm -f /tmp/after_snapshot")
        except:
            pass
        _SnappointRollback.postRun(self)

class TC11205(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.4 VM"""

    DISTRO = "rhel54"

class TC11206(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.4 x64 VM"""

    DISTRO = "rhel54"
    ARCH = "x86-64"

class TC12552(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.5 VM"""

    DISTRO = "rhel55"

class TC12553(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.5 x64 VM"""

    DISTRO = "rhel55"
    ARCH = "x86-64"

class TC15288(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.6 VM"""

    DISTRO = "rhel56"

class TC15289(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 5.6 x64 VM"""

    DISTRO = "rhel56"
    ARCH = "x86-64"

class TC11207(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 4.8 VM"""

    DISTRO = "rhel48"

class TC11208(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 11 VM"""

    DISTRO = "sles11"

class TC11209(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 11 x64 VM"""

    DISTRO = "sles11"
    ARCH = "x86-64"

class TC12554(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 11 SP1 VM"""

    DISTRO = "sles111"

class TC12555(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 11 SP1 x64 VM"""

    DISTRO = "sles111"
    ARCH = "x86-64"

class TC11212(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a Debian 5.0 VM"""

    DISTRO = "debian50"

class TC11210(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 10 SP2 VM"""

    DISTRO = "sles102"

class TC11211(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a SLES 10 SP2 x64 VM"""

    DISTRO = "sles102"
    ARCH = "x86-64"
    
class TC21646(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a Debian 7 x86 VM"""

    DISTRO = "debian70"
    
class TC21647(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a Ubuntu 14.04 x64 VM"""

    DISTRO = "ubuntu1404"
    ARCH = "x86-64"
    
class TC21648(_CheckpointSmoketest):
    """VM checkpoint and rollback smoketest of a RHEL 7 x64 VM"""

    DISTRO = "rhel7"
    ARCH = "x86-64"

