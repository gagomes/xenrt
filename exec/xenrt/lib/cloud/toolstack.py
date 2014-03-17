import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

__all__ = ["CloudStack"]

import xenrt.lib.cloud.pvtoolsinstall

class CloudStack(object):
    def __init__(self, place):
        self.mgtsvr = xenrt.lib.cloud.ManagementServer(place)
        self.marvin = xenrt.lib.cloud.MarvinApi(self.mgtsvr)

    def hypervisorType(self, instance):
        # TODO actually determine what hypervisor is selected for the given instance
        return xenrt.HypervisorType.xen

    def createInstance(self,
                       distro,
                       name=None,
                       vcpus=None,
                       memory=None,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None,
                       installTools=True):

        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        supportedInstallMethods = ["iso", "isowithanswerfile"]

        for m in supportedInstallMethods:
            if m in instance.os.supportedInstallMethods:
                instance.os.installMethod = m
                break

        if not instance.os.installMethod:
            raise xenrt.XRTError("No compatible install method found")

        self.marvin.addIsoIfNotPresent(distro, instance.os.isoName, instance.os.isoRepo)

        zone = Zone.list(self.marvin.apiClient)[0].id
        # TODO support different service offerings
        svcOffering = ServiceOffering.list(self.marvin.apiClient, name = "Medium Instance")[0].id

        # TODO support different disk offerings
        diskOffering = [x for x in DiskOffering.list(self.marvin.apiClient) if x.disksize == 20][0].id

        template = Iso.list(self.marvin.apiClient, name=instance.os.isoName)[0].id

        xenrt.TEC().logverbose("Deploying VM")
        rsp = VirtualMachine.create(self.marvin.apiClient, {
                                        "serviceoffering": svcOffering,
                                        "zoneid": zone,
                                        "displayname": name,
                                        "name": name,
                                        "template": template,
                                        "diskoffering": diskOffering},
                                    startvm=False)

        instance.toolstackId = rsp.id

        Tag.create(self.marvin.apiClient, [instance.toolstackId], "userVm", {"distro": distro})

        xenrt.TEC().logverbose("Starting VM")

        self.startInstance(instance)

        if instance.os.installMethod == "isowithanswerfile":
            xenrt.TEC().logverbose("Generating answer file")
            instance.os.generateIsoAnswerfile()

        xenrt.TEC().logverbose("Waiting for install complete")
        instance.os.waitForInstallCompleteAndFirstBoot()
        
        if installTools:
            self.installPVTools(instance)

        return instance


    def existingInstance(self, name):

        vm = VirtualMachine.list(self.marvin.apiClient, name=name)[0]
        tags = Tag.list(self.marvin.apiClient, resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]

        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(self, name, distro, 0, 0, {}, [], 0)
        instance.toolstackId = vm.id
        return instance

    def installPVTools(self, instance):
        try:
            installer = xenrt.lib.cloud.pvtoolsinstall.PVToolsInstallerFactory(self, instance)
        except:
            xenrt.TEC().logverbose("No PV tools installer found for instance")
        else:
            installer.install()

    def getIP(self, instance, timeout, level):
        cmd = listNics.listNicsCmd()
        cmd.virtualmachineid=instance.toolstackId
        instance.mainip = [x.ipaddress for x in NIC.list(self.marvin.apiClient, virtualmachineid = instance.toolstackId) if x.isdefault][0]
        return instance.mainip

    def startInstance(self, instance, on=None):
        cmd = startVirtualMachine.startVirtualMachineCmd()
        cmd.id = instance.toolstackId
        self.marvin.apiClient.startVirtualMachine(cmd)

    def stopInstance(self, instance, force=False):
        cmd = stopVirtualMachine.stopVirtualMachineCmd()
        cmd.id = instance.toolstackId
        if force:
            cmd.forced = force
        self.marvin.apiClient.stopVirtualMachine(cmd)

    def rebootInstance(self, instance, force=False):
        cmd = rebootVirtualMachine.rebootVirtualMachineCmd()
        cmd.id = instance.toolstackId
        if force:
            cmd.forced = force
        self.marvin.apiClient.rebootVirtualMachine(cmd)

    def getInstancePowerState(self, instance):
        state = VirtualMachine.list(self.marvin.apiClient, id=instance.toolstackId)[0].state
        if state in ("Stopped", "Starting"):
            return xenrt.PowerState.down
        elif state in ("Running", "Stopping"):
            return xenrt.PowerState.up
        raise xenrt.XRTError("Unrecognised power state")

    def createTemplateFromInstance(self, instance, templateName):
        origState = instance.getPowerState()
        instance.setPowerState(xenrt.PowerState.down)
        
        volume = Volume.list(self.marvin.apiClient, virtualmachineid=instance.toolstackId, type="ROOT")[0].id

        vm = VirtualMachine.list(self.marvin.apiClient, id=instance.toolstackId)[0]
        ostypeid = vm.guestosid

        tags = Tag.list(self.marvin.apiClient, resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]


        t = Template.create(self.marvin.apiClient, {
                            "name": templateName,
                            "displaytext": templateName,
                            "ispublic": True,
                            "ostypeid": ostypeid
                        }, volumeid = volume)
        
        Tag.create(self.marvin.apiClient, [t.id], "Template", {"distro": distro})
        instance.setPowerState(origState)

    def createInstanceFromTemplate(self, templateName, name=None, start=True):
        if not name:
            name = xenrt.util.randomGuestName()
        template = [x for x in Template.list(self.marvin.apiClient, templatefilter="all") if x.displaytext == templateName][0].id
        
        tags = Tag.list(self.marvin.apiClient, resourceid = template)
        distro = [x.value for x in tags if x.key=="distro"][0]
        
        zone = Zone.list(self.marvin.apiClient)[0].id
        # TODO support different service offerings
        svcOffering = ServiceOffering.list(self.marvin.apiClient, name = "Medium Instance")[0].id

        xenrt.TEC().logverbose("Deploying VM")
        rsp = VirtualMachine.create(self.marvin.apiClient, {
                                        "serviceoffering": svcOffering,
                                        "zoneid": zone,
                                        "displayname": name,
                                        "name": name,
                                        "template": template},
                                    startvm=False)
        
        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(self, name, distro, 0, 0, {}, [], 0)
        instance.toolstackId = rsp.id

        Tag.create(self.marvin.apiClient, [instance.toolstackId], "userVm", {"distro": distro})
        if start:
            instance.start()

        return instance

    def ejectIso(self, instance):
        cmd = detachIso.detachIsoCmd()
        cmd.virtualmachineid = instance.toolstackId
        self.marvin.apiClient.detachIso(cmd)
