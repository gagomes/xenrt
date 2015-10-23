import xenrt

from zope.interface import implements


class Instance(object):
    implements(xenrt.interfaces.OSParent)

    def __init__(self, toolstack, name, distro, vcpus, memory, vifs=None,
                 rootdisk=None, extraConfig={}):
        self.toolstack = xenrt.interfaces.Toolstack(toolstack)
        self.toolstackId = None
        self.name = name
        self.distro = distro
        self.extraConfig = extraConfig
        self.mainip = None

        self.inboundmap = {}
        self.inboundip = None
        self.outboundip = None


        self.os = xenrt.lib.opsys.osFactory(self.distro, self)

        self.rootdisk = rootdisk or self.os.defaultRootdisk
        self.vcpus = vcpus or self.os.defaultVcpus
        self.memory = memory or self.os.defaultMemory
        self.vifs = vifs or [("%s0" % (self.os.vifStem), None,
                              xenrt.randomMAC(), None)]
        self.special = {}

    @property
    def hypervisorType(self):
        return self.toolstack.instanceHypervisorType(self)

    @property
    def supportedLifecycleOperations(self):
        return self.toolstack.instanceSupportedLifecycleOperations(self)

    @property
    def canMigrateTo(self):
        return self.toolstack.instanceCanMigrateTo(self)

    @property
    def residentOn(self):
        return self.toolstack.instanceResidentOn(self)

    def populateFromExisting(self, ip=None):
        if ip:
            self.mainip = ip
        else:
            self.mainip = self.getIP()
        self.toolstack.discoverInstanceAdvancedNetworking(self)
        self.os.populateFromExisting()

    def pollOSPowerState(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        deadline = xenrt.timenow() + timeout
        while 1:
            status = self.getPowerState()
            if state == status:
                return
            if xenrt.timenow() > deadline:
                xenrt.XRT("Timed out waiting for VM %s to be %s" %
                          (self.name, state), level)
            xenrt.sleep(15, log=False)

    def getPort(self, trafficType):
        if self.inboundmap.has_key(trafficType):
            return self.inboundmap[trafficType][1]
        else:
            return self.os.tcpCommunicationPorts[trafficType] 

    def getIPAndPort(self, trafficType, timeout=600, level=xenrt.RC_ERROR):
        if self.inboundmap.has_key(trafficType):
            return self.inboundmap[trafficType]
        elif self.inboundip:
            return (self.inboundip, self.os.tcpCommunicationPorts[trafficType])
        else:
            return (self.getMainIP(timeout, level), self.os.tcpCommunicationPorts[trafficType])
        

    def getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        if trafficType:
            if trafficType == "OUTBOUND":
                if self.outboundip:
                    return self.outboundip
                else:
                    return self.getMainIP(timeout, level)
            elif self.inboundmap.has_key(trafficType):
                return self.inboundmap[trafficType][0]
            elif self.inboundip:
                return self.inboundip
            else:
                return self.getMainIP(timeout, level)
        else:
            return self.getMainIP(timeout, level)

    def getMainIP(self, timeout, level):
        if self.mainip:
            return self.mainip
        return self.toolstack.getInstanceIP(self, timeout, level)

    def setIP(self, ip):
        raise xenrt.XRTError("Not implemented")

    def startOS(self, on=None):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.down, "Power state before starting must be down")
        self.toolstack.startInstance(self, on)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.up, "Power state after start should be up")

    def start(self, on=None, timeout=600):
        self.startOS(on)
        self.os.waitForBoot(timeout)

    def reboot(self, force=False, timeout=600, osInitiated=False):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.up, "Power state before rebooting must be up")
        if osInitiated:
            self.os.reboot()
            xenrt.sleep(120)
        else:
            self.toolstack.rebootInstance(self, force)
        self.os.waitForBoot(timeout)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.up, "Power state after reboot should be up")

    def stop(self, force=False, osInitiated=False):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.up, "Power state before shutting down must be up")
        if osInitiated:
            self.os.shutdown()
            self.pollOSPowerState(xenrt.PowerState.down)
        else:
            self.toolstack.stopInstance(self, force)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.down, "Power state after shutdown should be down")

    def suspend(self):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.up, "Power state before suspend down must be up")
        self.toolstack.suspendInstance(self)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.suspended, "Power state after suspend should be suspended")

    def resume(self, on=None):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.suspended, "Power state before resume down must be suspended")
        self.toolstack.resumeInstance(self, on)
        self.os.waitForBoot(60)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.up, "Power state after resume should be up")

    def destroy(self):
        self.toolstack.destroyInstance(self)

    def migrate(self, to, live=True):
        xenrt.xrtAssert(self.getPowerState() == xenrt.PowerState.up, "Power state before migrate must be up")
        self.toolstack.migrateInstance(self, to, live)
        self.os.waitForBoot(60)
        xenrt.xrtCheck(self.getPowerState() == xenrt.PowerState.up, "Power state after migrate should be up")
        xenrt.xrtCheck(self.residentOn == to, "Resident on after migrate should be %s" % to)

    def setPowerState(self, powerState):
        transitions = {}
        transitions[xenrt.PowerState.up] = {}
        transitions[xenrt.PowerState.up][xenrt.PowerState.down] = [self.stop]
        transitions[xenrt.PowerState.up][xenrt.PowerState.suspended] = [self.suspend]

        transitions[xenrt.PowerState.down] = {}
        transitions[xenrt.PowerState.down][xenrt.PowerState.up] = [self.start]
        transitions[xenrt.PowerState.down][xenrt.PowerState.suspended] = [self.start, self.suspend]

        transitions[xenrt.PowerState.suspended] = {}
        transitions[xenrt.PowerState.suspended][xenrt.PowerState.up] = [self.resume]
        transitions[xenrt.PowerState.suspended][xenrt.PowerState.down] = [self.resume, self.stop]

        curState = self.getPowerState()

        try:
            ts = transitions[curState][powerState]
        except:
            xenrt.TEC().logverbose("No transition needed for %s to %s" % (curState, powerState))
        else:
            for t in ts:
                t()

    def getPowerState(self):
        return self.toolstack.getInstancePowerState(self)

    def setIso(self, isoName, isoRepo=None):
        return self.toolstack.setInstanceIso(self, isoName, isoRepo)

    def ejectIso(self):
        return self.toolstack.ejectInstanceIso(self)

    def createSnapshot(self, name, memory=False, quiesce=False):
        return self.toolstack.createInstanceSnapshot(self, name, memory)

    def deleteSnapshot(self, name):
        return self.toolstack.deleteInstanceSnapshot(self, name)

    def revertToSnapshot(self, name):
        return self.toolstack.revertInstanceToSnapshot(self, name)

    def assertHealthy(self, quick=False):
        self.os.assertHealthy(quick=quick)

    def screenshot(self, path):
        return self.toolstack.instanceScreenshot(self, path)

__all__ = ["Instance"]
