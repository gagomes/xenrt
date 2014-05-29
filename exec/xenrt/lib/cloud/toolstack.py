import xenrt
import logging
import os, urllib, re
from datetime import datetime
from xenrt.lazylog import log
from zope.interface import implements
from collections import namedtuple

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

    # Mapping Cloud hypervisor strings to the XenRT HypervisorType enum
    __hypervisorTypeMapping = {"XenServer": xenrt.HypervisorType.xen,
                     "KVM": xenrt.HypervisorType.kvm,
                     "VMware": xenrt.HypervisorType.vmware,
                     "Hyperv": xenrt.HypervisorType.hyperv,
                     "BareMetal": xenrt.HypervisorType.native,
                     "Simulator": xenrt.HypervisorType.simulator}

    # Mapping of hypervisors to template formats
    _templateFormats = {"XenServer": "VHD",
                        "KVM": "QCOW2"}

    def __init__(self, place=None, ip=None):
        assert place or ip
        if not place:
            place = xenrt.GenericGuest("CS-MS")
            place.mainip = ip
            place.findPassword()
        self.mgtsvr = xenrt.lib.cloud.ManagementServer(place)
        self.marvin = xenrt.lib.cloud.MarvinApi(self.mgtsvr)

    @property
    def name(self):
        return "CS-%s" % self.mgtsvr.place.mainip

    def instanceHypervisorType(self, instance, nativeCloudType=False):
        """Returns the hypervisor type for the given instance. nativeCloudType allows the internal cloud string to be returned"""
        hypervisor = self.marvin.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hypervisor
        return nativeCloudType and hypervisor or self.hypervisorToHypervisorType(hypervisor)

    def instanceHypervisorTypeAndVersion(self, instance, nativeCloudType=False):
        hypervisorInfo = namedtuple('hypervisorInfo', ['type','version'])
        host = self.marvin.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hostid
        hostdetails = self.marvin.cloudApi.listHosts(id=host)[0]
        if nativeCloudType:
            return hypervisorInfo(hostdetails.hypervisor, hostdetails.hypervisorversion)
        else:
            return hypervisorInfo(self.hypervisorToHypervisorType(hostdetails.hypervisor), hostdetails.hypervisorversion)

    def hypervisorToHypervisorType(self, hypervisor):
        """Map a cloud hypervisor string to a xenrt.HypervisorType enum"""
        if hypervisor in self.__hypervisorTypeMapping.keys():
            return self.__hypervisorTypeMapping[hypervisor]
        raise xenrt.XRTError("Unknown cloud hypervisor: %s" % hypervisor)

    def hypervisorTypeToHypervisor(self, hypervisorType):
        """Map a xenrt.HypervisorType enum to a cloud hypervisor string"""
        try:
            return (h for h,hv in self.__hypervisorTypeMapping.items() if hv == hypervisorType).next()
        except StopIteration:
            raise xenrt.XRTError("Unknown XenRT hypervisorType: %s" % hypervisorType)

    def instanceResidentOn(self, instance):
        return self.marvin.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hostname

    def instanceCanMigrateTo(self, instance):
        hosts = self.marvin.cloudApi.findHostsForMigration(virtualmachineid = instance.toolstackId)
        if hosts is None:
            return []
        else:
            return [h.name for h in hosts]

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

    def _getDefaultHypervisor(self):
        hypervisors = [h.hypervisor for h in self.marvin.cloudApi.listHosts(type="routing")]
        if len(hypervisors) > 0:
            # TODO reinstate this when all controllers run python >=2.7
            # return Counter(hypervisors).most_common(1)[0][0]
            return xenrt.util.mostCommonInList(hypervisors)
        return "XenServer"

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
                       useTemplateIfAvailable=True,
                       hypervisorType=None,
                       zone=None):
        
        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        try:
    
            hypervisor = None
            if hypervisorType:
                hypervisor = self.hypervisorTypeToHypervisor(hypervisorType)
            startOnId = None
            if startOn:
                hosts = self.marvin.cloudApi.listHosts(name=startOn)
                if len(hosts) != 1:
                    raise xenrt.XRTError("Cannot find host %s on cloud" % startOn)
                startOnId = hosts[0].id
                # Ignore any provided hypervisorType and set this based on the host
                hypervisor = hosts[0].hypervisor
            
            template = None        

            # If we can use a template and it exists, use it
            if useTemplateIfAvailable:
                if not hypervisor:
                    hypervisor = self._getDefaultHypervisor()
                templateFormat = self._templateFormats[hypervisor]
                templateDir = xenrt.TEC().lookup("EXPORT_CCP_TEMPLATES_HTTP", None)
                if templateDir:
                    url = "%s/%s/%s.%s.bz2" % (templateDir, hypervisor, instance.os.canonicalDistroName, templateFormat.lower())
                    if xenrt.TEC().fileExists(url):
                        self.marvin.addTemplateIfNotPresent(hypervisor, templateFormat, instance.os.canonicalDistroName, url)
                        template = [x for x in self.marvin.cloudApi.listTemplates(templatefilter="all") if x.displaytext == instance.os.canonicalDistroName][0].id
                # If we use a template, we can't specify the disk size
                diskOffering=None        

            # If we don't have a template, do ISO instead
            if not template:
                self.marvin.addIsoIfNotPresent(instance.os.canonicalDistroName, instance.os.isoName, instance.os.isoRepo)
                template = self.marvin.cloudApi.listIsos(name=instance.os.isoName)[0].id
                supportedInstallMethods = [xenrt.InstallMethod.Iso, xenrt.InstallMethod.IsoWithAnswerFile]

                for m in supportedInstallMethods:
                    if m in instance.os.supportedInstallMethods:
                        instance.os.installMethod = m
                        break

                if not instance.os.installMethod:
                    raise xenrt.XRTError("No compatible install method found")
                diskOffering = self.findOrCreateDiskOffering(disksize = instance.rootdisk / xenrt.GIGA)

            if zone:
                zoneid = self.marvin.cloudApi.listZones(name=zone)[0].id
            else:
                zoneid = self.marvin.cloudApi.listZones()[0].id
            svcOffering = self.findOrCreateServiceOffering(cpus = instance.vcpus , memory = instance.memory)

            # Do we need to sort out a security group?
            if self.marvin.cloudApi.listZones(id=zoneid)[0].securitygroupsenabled:
                secGroups = self.marvin.cloudApi.listSecurityGroups(securitygroupname="xenrt_default_sec_grp")
                if not isinstance(secGroups, list):
                    domainid = self.marvin.cloudApi.listDomains(name='ROOT')[0].id
                    secGroup = self.marvin.cloudApi.createSecurityGroup(name= "xenrt_default_sec_grp", account="system", domainid=domainid)
                    self.marvin.cloudApi.authorizeSecurityGroupIngress(securitygroupid = secGroup.id,
                                                                      protocol="TCP",
                                                                      startport=0,
                                                                      endport=65535,
                                                                      cidrlist = "0.0.0.0/0")
                    self.marvin.cloudApi.authorizeSecurityGroupIngress(securitygroupid = secGroup.id,
                                                                      protocol="ICMP",
                                                                      icmptype=-1,
                                                                      icmpcode=-1,
                                                                      cidrlist = "0.0.0.0/0")
                    secGroupId = secGroup.id
                else:
                    secGroupId = secGroups[0].id


            xenrt.TEC().logverbose("Deploying VM")
            params = {
                      "serviceoffering": svcOffering,
                      "zoneid": zoneid,
                      "displayname": name,
                      "name": name,
                      "template": template,
                      "diskoffering": diskOffering
                     }
            if startOn:
                params["hostid"] = startOnId

            rsp = self.marvin.cloudApi.deployVirtualMachine(serviceofferingid=svcOffering,
                                                            zoneid=zoneid,
                                                            displayname=name,
                                                            name=name,
                                                            templateid=template,
                                                            diskofferingid=diskOffering,
                                                            hostid = startOnId,
                                                            hypervisor=hypervisor,
                                                            startvm=False,
                                                            securitygroupids=[secGroupId])

            instance.toolstackId = rsp.id

            self.marvin.cloudApi.createTags(resourceids=[instance.toolstackId],
                                            resourcetype="userVm",
                                            tags=[{"key":"distro", "value":distro}])

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

        except Exception, ex:
            try:
                instance.screenshot(xenrt.TEC().getLogdir())
            except Exception, e:
                xenrt.TEC().logverbose("Could not take screenshot - %s" % str(e))
            try:
                d = "%s/%s" % (xenrt.TEC().getLogdir(), instance.name)
                if not os.path.exists(d):
                    os.makedirs(d)
                instance.os.getLogs(d)   
            except Exception, e:
                xenrt.TEC().logverbose("Could not get logs - %s" % str(e))
            raise ex
        return instance

    def getAllExistingInstances(self):
        """Returns all existing instances"""
        return self.marvin.cloudApi.listVirtualMachines()

    def existingInstance(self, name):

        vm = [x for x in self.marvin.cloudApi.listVirtualMachines(name=name) if x.name==name][0]
        tags = self.marvin.cloudApi.listTags(resourceid = vm.id)
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
        self.marvin.cloudApi.destroyVirtualMachine(id=instance.toolstackId, expunge=True)

    def setInstanceIso(self, instance, isoName, isoRepo):
        if isoRepo:
            self.marvin.addIsoIfNotPresent(None, isoName, isoRepo)
        isoId = self.marvin.cloudApi.listIsos(name=isoName)[0].id

        self.marvin.cloudApi.attachIso(id=isoId, virtualmachineid=instance.toolstackId)

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
        instance.mainip = [x.ipaddress for x in self.marvin.cloudApi.listNics(virtualmachineid = instance.toolstackId) if x.isdefault][0]
        return instance.mainip

    def startInstance(self, instance, on=None):
        self.marvin.cloudApi.startVirtualMachine(id=instance.toolstackId)

    def stopInstance(self, instance, force=False):
        self.marvin.cloudApi.stopVirtualMachine(id=instance.toolstackId, forced=force)

    def rebootInstance(self, instance, force=False):
        self.marvin.cloudApi.rebootVirtualMachine(id=instance.toolstackId, forced=force)

    def suspendInstance(self, instance):
        raise xenrt.XRTError("Not implemented")

    def resumeInstance(self, instance, on):
        raise xenrt.XRTError("Not implemented")

    def migrateInstance(self, instance, to, live=True):
        if not live:
            raise xenrt.XRTError("Non-live migrate is not supported")

        hostid = [x for x in self.marvin.cloudApi.listHosts(name=to) if x.name==to][0].id
        self.marvin.cloudApi.migrateVirtualMachine(hostid=hostid, virtualmachineid=instance.toolstackId)

    def getInstancePowerState(self, instance):
        state = self.marvin.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].state
        if state in ("Stopped", "Starting"):
            return xenrt.PowerState.down
        elif state in ("Running", "Stopping"):
            return xenrt.PowerState.up
        raise xenrt.XRTError("Unrecognised power state")

    def createTemplateFromInstance(self, instance, templateName):
        origState = instance.getPowerState()
        instance.setPowerState(xenrt.PowerState.down)

        volume = self.marvin.cloudApi.listVolumes(virtualmachineid=instance.toolstackId, type="ROOT")[0].id

        vm = self.marvin.cloudApi.listVirtualMachines(id=instance.toolstackId)[0]
        ostypeid = vm.guestosid

        tags = self.marvin.cloudApi.listTags(resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]


        t = self.marvin.cloudApi.createTemplate(
                            name=templateName,
                            displaytext=templateName,
                            ispublic=True,
                            ostypeid=ostypeid,
                            volumeid = volume)
        
        self.marvin.cloudApi.createTags(resourceids=[t.id],
                                        resourcetype="Template",
                                        tags=[{"key":distro, "value":distro}])
        instance.setPowerState(origState)

    def createInstanceFromTemplate(self, templateName, name=None, start=True):
        if not name:
            name = xenrt.util.randomGuestName()
        template = [x for x in self.marvin.cloudApi.listTemplates(templatefilter="all") if x.displaytext == templateName][0].id
        
        tags = self.marvin.cloudApi.listTags(resourceid = template)
        distro = [x.value for x in tags if x.key=="distro"][0]
        
        zone = self.marvin.cloudApi.listZones()[0].id
        # TODO support different service offerings
        svcOffering = self.marvin.cloudApi.listServiceOfferings(name = "Medium Instance")[0].id

        xenrt.TEC().logverbose("Deploying VM")
        rsp = self.marvin.cloudApi.deployVirtualMachine(
                                        serviceofferingid=svcOffering,
                                        zoneid=zone,
                                        displayname=name,
                                        name= name,
                                        templateid=template,
                                        startvm=False)
        
        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(self, name, distro, 0, 0, {}, [], 0)
        instance.toolstackId = rsp.id

        self.marvin.cloudApi.createTags(resourceids=[instance.toolstackId],
                                        resourcetype="userVm",
                                        tags=[{"key":"distro", "value":distro}])
        if start:
            instance.start()

        return instance

    def ejectInstanceIso(self, instance):
        self.marvin.cloudApi.detachIso(virtualmachineid = instance.toolstackId)

    def createInstanceSnapshot(self, instance, name, memory=False, quiesce=False):
        self.marvin.cloudApi.createVMSnapshot(virtualmachineid = instance.toolstackId,
                                               name = name,
                                               snapshotmemory=memory,
                                               quiesce=quiesce)

    def getSnapshotId(self, instance, name):
        return self.marvin.cloudApi.listSnapshots(virtualmachineid = instance.toolstackId, name=name)[0].id

    def deleteInstanceSnapshot(self, instance, name):
        self.marvin.cloudApi.deleteVMSnapshot(vmsnapshotid = self.getSnapshotId(instance, name))

    def revertInstanceToSnapshot(self, instance, name):
        self.marvin.cloudApi.revertToVMSnapshot(vmsnapshotid = self.getSnapshotId(instance, name))


    def downloadTemplate(self, templateName, downloadLocation):
        template = [x for x in self.marvin.cloudApi.listTemplates(templatefilter="all") if x.displaytext == templateName][0].id
        rsp = self.marvin.cloudApi.extractTemplate(mode = "HTTP_DOWNLOAD", id = template)
        xenrt.util.command("wget -nv '%s' -O '%s'" % (rsp.url, downloadLocation))
        
    def findOrCreateServiceOffering(self, cpus, memory):               
        svcOfferingExist = [x for x in self.marvin.cloudApi.listServiceOfferings() if x.cpunumber == cpus and x.memory == memory]        
        if svcOfferingExist :
            return svcOfferingExist[0].id
        else :
            xenrt.TEC().logverbose("Creating New Service Offering ")
            svcOfferingNew = self.marvin.cloudApi.createServiceOffering(cpunumber=cpus,
                                                                         memory=memory,
                                                                         name="CPUs=%d ,Memory=%d MB offering" %(cpus,memory),
                                                                         displaytext="New Offering",
                                                                         cpuspeed=1000)
            return svcOfferingNew.id       
        
    def findOrCreateDiskOffering(self, disksize):
        xenrt.log("Inside the disk Offering")        
        diskOfferingExist = [x for x in self.marvin.cloudApi.listDiskOfferings() if x.disksize == disksize]        
        if diskOfferingExist :
            return diskOfferingExist[0].id
        else :
            xenrt.TEC().logverbose("Creating new Disk Offering ")
            diskOfferingNew = self.marvin.cloudApi.createDiskOffering(disksize=disksize,
                                                                      name="Disk=%d GB offering" %disksize,
                                                                      displaytext="Disk Offering")
            return diskOfferingNew.id

    def instanceScreenshot(self, instance, path):
        if not hasattr(self.marvin.apiClient, "hypervisor"):
            self.marvin.apiClient.hypervisor = None
        keys={"apikey": self.marvin.userApiClient.connection.apiKey,
              "cmd": "access",
              "vm": instance.toolstackId}
        keys['signature'] = self.marvin.userApiClient.connection.sign(keys)
        frameset = urllib.urlopen("http://%s:8080/client/console?%s" % (self.mgtsvr.place.getIP(), urllib.urlencode(keys))).read()
        frameurl = re.search("src=\"(.*?)\"", frameset).group(1)

        xenrt.TEC().logverbose("Calculated %s as URL of frame" % frameurl)

        consoleproxy = re.search("(.+?://.+)/", frameurl).group(1)
        xenrt.TEC().logverbose("Calculated %s as base URL of console proxy" % consoleproxy)

        frame = urllib.urlopen(frameurl).read()
        imgurl = re.search("'(/ajaximg.*?)'", frame).group(1)
        
        xenrt.TEC().logverbose("Calculated %s as URL of image" % imgurl)

        for i in range(10):

            imglocation = "%s/%s_%s_%d.jpg" % (path, instance.name, instance.toolstackId, i)

            xenrt.sleep(2)

            f = open(imglocation, "w")
            u = urllib.urlopen("%s%s" % (consoleproxy, imgurl))
            f.write(u.read())
            f.close()
            u.close()
            xenrt.TEC().logverbose("Saved screenshot as %s" % imglocation)
        return imglocation

    def getLogs(self, path):
        sftp = self.mgtsvr.place.sftpClient()
        sftp.copyLogsFrom(["/var/log/cloudstack"], path)
