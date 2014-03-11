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

    def createInstance(self,
                       distro,
                       name=None,
                       vcpus=None,
                       memory=None,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None):

        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        if not "iso" in instance.os.supportedInstallMethods:
            raise xenrt.XRTError("ISO Install not supported")

        self.marvin.addIsoIfNotPresent(distro, instance.os.isoName, instance.os.isoRepo)

        deployVirtualMachineC = deployVirtualMachine.deployVirtualMachineCmd()
        deployVirtualMachineC.displayname = name
        deployVirtualMachineC.templateid = [x.id for x in self.marvin.apiClient.listIsos(listIsos.listIsosCmd()) if x.name == instance.os.isoName][0]
        # TODO support different service offerings
        deployVirtualMachineC.serviceofferingid = [x.id for x in self.marvin.apiClient.listServiceOfferings(listServiceOfferings.listServiceOfferingsCmd()) if x.name == "Medium Instance"][0]
        # TODO support different disk offerings
        deployVirtualMachineC.diskofferingid = [x.id for x in self.marvin.apiClient.listDiskOfferings(listDiskOfferings.listDiskOfferingsCmd()) if x.disksize == 20]
        # TODO Support different hypervisors
        deployVirtualMachineC.hypervisor = "XenServer"
        deployVirtualMachineC.zoneid = self.marvin.apiClient.listZones(listZones.listZonesCmd())[0].id

        xenrt.TEC().logverbose("Deploying VM")

        rsp = self.marvin.apiClient.deployVirtualMachine(deployVirtualMachineC)

        instance.toolstackId = rsp.id

        createTagsC = createTags.createTagsCmd()
        createTagsC.resourceids.append(instance.toolstackId)
        createTagsC.resourcetype = "userVm"
        createTagsC.tags.append({"key":"distro", "value": distro})
        self.marvin.apiClient.createTags(createTagsC)

        xenrt.TEC().logverbose("Waiting for install complete")
        instance.os.waitForInstallCompleteAndFirstBoot()
        return instance


    def existingInstance(self, name):

        vm = [x for x in self.marvin.apiClient.listVirtualMachines(listVirtualMachines.listVirtualMachinesCmd()) if x.displayname==name][0]
        listTagsC = listTags.listTagsCmd()
        listTagsC.resourceid = vm.id
        tags = self.marvin.apiClient.listTags(listTagsC)
        distro = [x.value for x in tags if x.key=="distro"][0]

        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(self, name, distro, 0, 0, {}, [], 0)
        instance.toolstackId = vm.id
        return instance

    def installPVTools(self, instance):
        xenrt.lib.cloud.pvtoolsinstall.PVToolsInstallerFactory(self, instance).install()

    def getIP(self, instance, timeout, level):
        cmd = listNics.listNicsCmd()
        cmd.virtualmachineid=instance.toolstackId
        instance.mainip = [x.ipaddress for x in self.marvin.apiClient.listNics(cmd) if x.isdefault][0]
        return instance.mainip

    def startInstance(self, instance, on):
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

