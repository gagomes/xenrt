import xenrt
import logging
import os, urllib
from datetime import datetime
from xenrt.lazylog import log
from zope.interface import implements

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
    implements(xenrt.interfaces.Toolstack)

    def __init__(self, place=None, ip=None):
        assert place or ip
        if not place:
            place = xenrt.GenericGuest("CS-MS")
            place.mainip = ip
            place.findPassword()
        self.mgtsvr = xenrt.lib.cloud.ManagementServer(place)
        self.marvin = xenrt.lib.cloud.MarvinApi(self.mgtsvr)

    def instanceHypervisorType(self, instance):
        # TODO actually determine what hypervisor is selected for the given instance
        return xenrt.HypervisorType.xen

    def instanceResidentOn(self, instance):
        return [x.hostname for x in VirtualMachine.list(self.marvin.apiClient, id=instance.toolstackId)][0]

    def instanceCanMigrateTo(self, instance): 
        cmd = findHostsForMigration.findHostsForMigrationCmd()
        cmd.virtualmachineid = instance.toolstackId
        return [x.name for x in self.marvin.apiClient.findHostsForMigration(cmd)]

    def instanceSupportedLifecycleOperations(self, instance):
        ops = [xenrt.LifecycleOperation.start,
               xenrt.LifecycleOperation.stop,
               xenrt.LifecycleOperation.reboot,
               xenrt.LifecycleOperation.destroy,
               xenrt.LifecycleOperation.snapshot]

        if not isinstance(instance.os, xenrt.lib.opsys.WindowsOS) or \
                (instance.extraConfig.has_key("CCP_PV_TOOLS") and instance.extraConfig['CCP_PV_TOOLS']):
            ops.append(xenrt.LifecycleOperation.livemigrate)
        
        return ops

    def createInstance(self,
                       distro,
                       name=None,
                       vcpus=None,
                       memory=None,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None,
                       installTools=True,
                       useTemplateIfAvailable=True):
        
        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)
    
        template = None        

        # If we can use a template and it exists, use it
        if useTemplateIfAvailable:
            templateDir = xenrt.TEC().lookup("EXPORT_CCP_TEMPLATES_HTTP", None)
            if templateDir:
                url = "%s/%s.vhd.bz2" % (templateDir, distro)
                if xenrt.TEC().fileExists(url):
                    self.marvin.addTemplateIfNotPresent(distro, url)
                    template = [x for x in Template.list(self.marvin.apiClient, templatefilter="all") if x.displaytext == distro][0].id
            # If we use a template, we can't specify the disk size
            diskOffering=None        

        # If we don't have a template, do ISO instead
        if not template:
            self.marvin.addIsoIfNotPresent(distro, instance.os.isoName, instance.os.isoRepo)
            template = Iso.list(self.marvin.apiClient, name=instance.os.isoName)[0].id
            supportedInstallMethods = [xenrt.InstallMethod.Iso, xenrt.InstallMethod.IsoWithAnswerFile]

            for m in supportedInstallMethods:
                if m in instance.os.supportedInstallMethods:
                    instance.os.installMethod = m
                    break

            if not instance.os.installMethod:
                raise xenrt.XRTError("No compatible install method found")
            # TODO support different disk offerings
            #diskOffering = [x for x in DiskOffering.list(self.marvin.apiClient) if x.disksize == 20][0].id            
            diskOffering = self.findOrCreateDiskOffering(disksize = instance.rootdisk / xenrt.GIGA)


        zone = Zone.list(self.marvin.apiClient)[0].id
        # TODO support different service offerings
        #svcOffering = ServiceOffering.list(self.marvin.apiClient, name = "Medium Instance")[0].id        
        svcOffering = self.findOrCreateServiceOffering(cpus = instance.vcpus , memory = instance.memory)


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

        # If we don't have an install method, we created this from a template, so we just need to start it.
        if not instance.os.installMethod:
            instance.start()
        else:
            self.startInstance(instance)

            if instance.os.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
                xenrt.TEC().logverbose("Generating answer file")
                instance.os.generateIsoAnswerfile()

            xenrt.TEC().logverbose("Waiting for install complete")
            instance.os.waitForInstallCompleteAndFirstBoot()
        
        # We don't install the tools as part of template generation, so install these all the time
        if installTools:
            self.installPVTools(instance)

        return instance


    def existingInstance(self, name):

        vm = [x for x in VirtualMachine.list(self.marvin.apiClient, name=name) if x.name==name][0]
        tags = Tag.list(self.marvin.apiClient, resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]

        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(toolstack=self,
                                      name=name,
                                      distro=distro,
                                      vcpus=0,
                                      memory=0)
        instance.toolstackId = vm.id
        instance.populateFromExisting()
        # TODO: Assuming for now the PV tools are installed
        instance.extraConfig['CCP_PV_TOOLS'] = True
        return instance

    def destroyInstance(self, instance):
        cmd = destroyVirtualMachine.destroyVirtualMachineCmd()
        cmd.id = instance.toolstackId
        cmd.expunge = True
        self.marvin.apiClient.destroyVirtualMachine(cmd)

    def setInstanceIso(self, instance, isoName, isoRepo):
        if isoRepo:
            self.marvin.addIsoIfNotPresent(None, isoName, isoRepo)
        listIsosC = listIsos.listIsosCmd()
        listIsosC.name=isoName
        isoId = self.marvin.apiClient.listIsos(listIsosC)[0].id

        attachIsoC = attachIso.attachIsoCmd()
        attachIsoC.id = isoId
        attachIsoC.virtualmachineid = instance.toolstackId
        self.marvin.apiClient.attachIso(attachIsoC)

        # Allow the CD to appear
        xenrt.sleep(30)

    def installPVTools(self, instance):
        try:
            installer = xenrt.lib.cloud.pvtoolsinstall.pvToolsInstallerFactory(self, instance)
        except:
            xenrt.TEC().logverbose("No PV tools installer found for instance")
        else:
            installer.install()
            instance.extraConfig['CCP_PV_TOOLS'] = True

    def getInstanceIP(self, instance, timeout, level):
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

    def suspendInstance(self, instance):
        raise xenrt.XRTError("Not implemented")

    def resumeInstance(self, instance, on):
        raise xenrt.XRTError("Not implemented")

    def migrateInstance(self, instance, to, live=True):
        if not live:
            raise xenrt.XRTError("Non-live migrate is not supported")

        cmd = migrateVirtualMachine.migrateVirtualMachineCmd()
        cmd.virtualmachineid = instance.toolstackId
        cmd.hostid = [x for x in Host.list(self.marvin.apiClient, name=to) if x.name==to][0].id
        self.marvin.apiClient.migrateVirtualMachine(cmd)

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

    def ejectInstanceIso(self, instance):
        cmd = detachIso.detachIsoCmd()
        cmd.virtualmachineid = instance.toolstackId
        self.marvin.apiClient.detachIso(cmd)

    def createInstanceSnapshot(self, instance, name, memory=False, quiesce=False):
        cmd = createVMSnapshot.createVMSnapshotCmd()
        cmd.virtualmachineid = instance.toolstackId
        cmd.name = name
        cmd.snapshotmemory=memory
        cmd.quiesce=quiesce
        self.marvin.apiClient.createVMSnapshot(cmd)

    def getSnapshotId(self, instance, name):
        return VmSnapshot.list(self.marvin.apiClient, virtualmachineid = instance.toolstackId, name=name)[0].id

    def deleteInstanceSnapshot(self, instance, name):
        cmd = deleteVMSnapshot.deleteVMSnapshotCmd()
        cmd.vmsnapshotid = self.getSnapshotId(instance, name)
        self.marvin.apiClient.deleteVMSnapshot(cmd)

    def revertInstanceToSnapshot(self, instance, name):
        cmd = revertToVMSnapshot.revertToVMSnapshotCmd()
        cmd.vmsnapshotid = self.getSnapshotId(instance, name)
        self.marvin.apiClient.revertToVMSnapshot(cmd)

    def downloadTemplate(self, templateName, downloadLocation):
        template = [x for x in Template.list(self.marvin.apiClient, templatefilter="all") if x.displaytext == templateName][0].id
        cmd = extractTemplate.extractTemplateCmd()
        cmd.mode = "HTTP_DOWNLOAD"
        cmd.id = template
        rsp = self.marvin.apiClient.extractTemplate(cmd)
        xenrt.util.command("wget -nv '%s' -O '%s'" % (rsp.url, downloadLocation))
        
    def findOrCreateServiceOffering(self, cpus, memory):               
        svcOfferingExist = [x for x in ServiceOffering.list(self.marvin.apiClient) if x.cpunumber == cpus and x.memory == memory]        
        if svcOfferingExist :
            return svcOfferingExist[0].id
        else :
            cmd = {}
            cmd["cpunumber"]= cpus
            cmd["memory"] = memory
            cmd["name"] = "CPUs=%d ,Memory=%d MB offering" %(cpus,memory)
            cmd["displaytext"] = "New Offering"
            cmd["cpuspeed"] = 1000
            xenrt.TEC().logverbose("Creating New Service Offering ")
            svcOfferingNew = ServiceOffering.create(self.marvin.apiClient,cmd)
            return svcOfferingNew.id       
        
    def findOrCreateDiskOffering(self, disksize):
        xenrt.log("Inside the disk Offering")        
        diskOfferingExist = [x for x in DiskOffering.list(self.marvin.apiClient) if x.disksize == disksize]        
        if diskOfferingExist :
            return diskOfferingExist[0].id
        else :
            cmd = {}
            cmd["name"]="Disk=%d GB offering" %disksize
            cmd["displaytext"]="Disk Offering"            
            cmd["disksize"] = disksize
            xenrt.TEC().logverbose("Creating new Disk OFfering ")
            diskOfferingNew = DiskOffering.create(self.marvin.apiClient ,cmd)
            return diskOfferingNew.id



