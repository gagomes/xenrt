import xenrt
import logging
import os, urllib, re
from datetime import datetime
from xenrt.lazylog import log
from zope.interface import implements
from collections import namedtuple

import xenrt.lib.cloud

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
                        "KVM": "QCOW2",
                        "Hyperv": "VHD"}

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

    @property
    def cloudApi(self):
        return self.marvin.cloudApi

    def instanceHypervisorType(self, instance, nativeCloudType=False):
        """Returns the hypervisor type for the given instance. nativeCloudType allows the internal cloud string to be returned"""
        hypervisor = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hypervisor
        return nativeCloudType and hypervisor or self.hypervisorToHypervisorType(hypervisor)

    def instanceHypervisorTypeAndVersion(self, instance, nativeCloudType=False):
        hypervisorInfo = namedtuple('hypervisorInfo', ['type','version'])
        host = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hostid
        hostdetails = self.cloudApi.listHosts(id=host)[0]
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
        return self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].hostname

    def instanceCanMigrateTo(self, instance):
        hosts = self.cloudApi.findHostsForMigration(virtualmachineid = instance.toolstackId)
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
        hypervisors = [h.hypervisor for h in self.cloudApi.listHosts(type="routing")]
        if len(hypervisors) > 0:
            # TODO reinstate this when all controllers run python >=2.7
            # return Counter(hypervisors).most_common(1)[0][0]
            return xenrt.util.mostCommonInList(hypervisors)
        return "XenServer"

    def createInstance(self,
                       distro=None,
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

        return self.__createInstance(distro=distro,
                                     name=name,
                                     vcpus=vcpus,
                                     memory=memory,
                                     vifs=vifs,
                                     rootdisk=rootdisk,
                                     extraConfig=extraConfig,
                                     startOn=startOn,
                                     installTools=installTools,
                                     useTemplateIfAvailable=useTemplateIfAvailable,
                                     hypervisorType=hypervisorType,
                                     zone=zone)

    def __createInstance(self,
                         distro,
                         template=None,
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
        
        zoneid = None
        templateid = None

        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        xenrt.TEC().registry.instancePut(name, instance)

        try:
    
            hypervisor = None
            if hypervisorType:
                hypervisor = self.hypervisorTypeToHypervisor(hypervisorType)
            startOnId = None
            if startOn:
                hosts = self.cloudApi.listHosts(name=startOn)
                if len(hosts) != 1:
                    raise xenrt.XRTError("Cannot find host %s on cloud" % startOn)
                startOnId = hosts[0].id
                # Ignore any provided hypervisorType and set this based on the host
                hypervisor = hosts[0].hypervisor
            
            

            if template:
                t = [x for x in self.cloudApi.listTemplates(templatefilter="all", name=template)][0]
                xenrt.XRTAssert(not hypervisor, "Cannot specify hypervisor when specifying a template")
                hypervisor = t.hypervisor
                xenrt.XRTAssert(not zone, "Cannot specify zone when specifying a template")
                zoneid = t.zoneid
                templateid = t.id

            if not hypervisor:
                hypervisor = self._getDefaultHypervisor()

            # If we can use a template and it exists, use it
            if not templateid and useTemplateIfAvailable:
                # See what templates we've got
                xenrt.TEC().logverbose("Seeing if we have a suitable template")
                templates = [x for x in self.cloudApi.listTemplates(templatefilter="all") if x.displaytext == instance.os.canonicalDistroName and x.hypervisor == hypervisor]
                for t in templates:
                    if not zone or t.zoneid == self.cloudApi.listZones(name=zone)[0].id:
                        zoneid = t.zoneid
                        templateid = t.id
                        xenrt.TEC().logverbose("Found template %s" % templateid)
                        break
                    
                if not templateid:
                    templateFormat = self._templateFormats[hypervisor]
                    templateDir = xenrt.TEC().lookup("EXPORT_CCP_TEMPLATES_HTTP", None)
                    if templateDir:
                        url = "%s/%s/%s.%s.bz2" % (templateDir, hypervisor, instance.os.canonicalDistroName, templateFormat.lower())
                        if xenrt.TEC().fileExists(url):
                            templateid = self.addTemplateIfNotPresent(hypervisor, templateFormat, instance.os.canonicalDistroName, url, zone)

            # If we don't have a template, do ISO instead
            if not templateid:
                templateid = self.addIsoIfNotPresent(instance.os.canonicalDistroName, instance.os.isoName, instance.os.isoRepo, zone)
                supportedInstallMethods = [xenrt.InstallMethod.Iso, xenrt.InstallMethod.IsoWithAnswerFile]

                for m in supportedInstallMethods:
                    if m in instance.os.supportedInstallMethods:
                        instance.os.installMethod = m
                        break

                if not instance.os.installMethod:
                    raise xenrt.XRTError("No compatible install method found")
                diskOffering = self.findOrCreateDiskOffering(disksize = instance.rootdisk / xenrt.GIGA)
                toolsInstalled=False
            else:
                diskOffering = None
                toolsInstalled = [x for x in self.cloudApi.listTags(resourceid=templateid) if x.key=="tools" and x.value=="yes"]

            if zoneid and zone:
                xenrt.XRTAssert(zoneid ==  self.cloudApi.listZones(name=zone)[0].id, "Specified Zone ID does not match template zone ID")

            if not zoneid:
                if zone:
                    zoneid = self.cloudApi.listZones(name=zone)[0].id
                else:
                    zoneid = self.getDefaultZone().id
            svcOffering = self.findOrCreateServiceOffering(cpus = instance.vcpus , memory = instance.memory)

            xenrt.TEC().logverbose("Deploying VM")

            networkProvider = NetworkProvider.factory(self, zoneid, instance, extraConfig)

            secGroupIds = networkProvider.getSecurityGroupIds()
            networks = networkProvider.getNetworkIds()

            rsp = self.cloudApi.deployVirtualMachine(serviceofferingid=svcOffering,
                                                     zoneid=zoneid,
                                                     displayname=name,
                                                     name=name,
                                                     templateid=templateid,
                                                     diskofferingid=diskOffering,
                                                     hostid = startOnId,
                                                     hypervisor=hypervisor,
                                                     startvm=False,
                                                     securitygroupids=secGroupIds,
                                                     networkids = networks)

            instance.toolstackId = rsp.id

            self.cloudApi.createTags(resourceids=[instance.toolstackId],
                                     resourcetype="userVm",
                                     tags=[{"key":"distro", "value":distro}])



            networkProvider.setupNetworkAccess()

            xenrt.TEC().logverbose("Starting VM")

            # If we don't have an install method, we created this from a template, so we just need to start it.
            if not instance.os.installMethod:
                instance.start()
            else:
                if instance.outboundip and instance.os.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
                    # We could have multiple instances behind the same IP, so we can only do one install at a time
                    with xenrt.GEC().getLock("CCP_INSTANCE_INSTALL-%s" % instance.outboundip):
                        xenrt.TEC().logverbose("Generating answer file")
                        instance.os.generateIsoAnswerfile()
                        self.startInstance(instance)
                        instance.os.waitForIsoAnswerfileAccess()
                        instance.os.cleanupIsoAnswerfile()

                else:
                    self.startInstance(instance)
    
                    if instance.os.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
                        xenrt.TEC().logverbose("Generating answer file")
                        instance.os.generateIsoAnswerfile()

                xenrt.TEC().logverbose("Waiting for install complete")
                instance.os.waitForInstallCompleteAndFirstBoot()
            
            if toolsInstalled:
                # Already installed as part of template generation
                self.cloudApi.createTags(resourceids=[instance.toolstackId],
                                         resourcetype="userVm",
                                         tags=[{"key":"tools", "value":"yes"}])
            elif installTools:
                self.installPVTools(instance)
                self.cloudApi.createTags(resourceids=[instance.toolstackId],
                                         resourcetype="userVm",
                                         tags=[{"key":"tools", "value":"yes"}])

        except Exception, ex:
            raise
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

    def getDefaultZone(self, zone=None):
        return self.cloudApi.listZones()[0]

    def getAllExistingInstances(self):
        """Returns all existing instances"""
        return self.cloudApi.listVirtualMachines()

    def existingInstance(self, name):

        vm = [x for x in self.cloudApi.listVirtualMachines(name=name) if x.name==name][0]
        tags = self.cloudApi.listTags(resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]

        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(toolstack=self,
                                      name=name,
                                      distro=distro,
                                      vcpus=0,
                                      memory=0)
        xenrt.TEC().registry.instancePut(name, instance)
        instance.toolstackId = vm.id
        instance.populateFromExisting()
        # TODO: Assuming for now the PV tools are installed
        instance.extraConfig['CCP_PV_TOOLS'] = True
        return instance

    def destroyInstance(self, instance):
        self.cloudApi.destroyVirtualMachine(id=instance.toolstackId, expunge=True)

    def setInstanceIso(self, instance, isoName, isoRepo):
        if isoRepo:
            self.addIsoIfNotPresent(None, isoName, isoRepo)
        isoId = self.cloudApi.listIsos(name=isoName)[0].id

        self.cloudApi.attachIso(id=isoId, virtualmachineid=instance.toolstackId)

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
        instance.mainip = [x.ipaddress for x in self.cloudApi.listNics(virtualmachineid = instance.toolstackId) if x.isdefault][0]
        return instance.mainip

    def startInstance(self, instance, on=None):
        if on:
            hosts = self.cloudApi.listHosts(name=on)
            if len(hosts) != 1:
                raise xenrt.XRTError("Cannot find host %s on cloud" % on)
            self.cloudApi.startVirtualMachine(id=instance.toolstackId, hostid=hosts[0].id)
        else:
            self.cloudApi.startVirtualMachine(id=instance.toolstackId)

    def stopInstance(self, instance, force=False):
        self.cloudApi.stopVirtualMachine(id=instance.toolstackId, forced=force)

    def rebootInstance(self, instance, force=False):
        if force:
            self.stopInstance(instance, True)
            self.startInstance(instance)
        else:
            self.cloudApi.rebootVirtualMachine(id=instance.toolstackId)

    def suspendInstance(self, instance):
        raise xenrt.XRTError("Not implemented")

    def resumeInstance(self, instance, on):
        raise xenrt.XRTError("Not implemented")

    def migrateInstance(self, instance, to, live=True):
        if not live:
            raise xenrt.XRTError("Non-live migrate is not supported")

        hostid = [x for x in self.cloudApi.listHosts(name=to) if x.name==to][0].id
        self.cloudApi.migrateVirtualMachine(hostid=hostid, virtualmachineid=instance.toolstackId)

    def getInstancePowerState(self, instance):
        state = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0].state
        if state in ("Stopped", "Starting"):
            return xenrt.PowerState.down
        elif state in ("Running", "Stopping"):
            return xenrt.PowerState.up
        raise xenrt.XRTError("Unrecognised power state")

    def createOSTemplate(self,
                         distro,
                         rootdisk=None,
                         installTools=True,
                         useTemplateIfAvailable=True,
                         hypervisorType=None,
                         zone=None):
        instance = self.createInstance(distro=distro,
                                       rootdisk=rootdisk,
                                       installTools=installTools,
                                       useTemplateIfAvailable=useTemplateIfAvailable,
                                       hypervisorType=hypervisorType,
                                       zone=zone)

        instance.stop()

        vm = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0]

        self.createTemplateFromInstance(instance, "%s-%s" % (instance.distro, xenrt.randomSuffix()), instance.distro)
        instance.destroy()

    def createTemplateFromInstance(self, instance, templateName, displayText=None):
        if not displayText:
            displayText = templateName
        origState = instance.getPowerState()
        instance.setPowerState(xenrt.PowerState.down)

        volume = self.cloudApi.listVolumes(virtualmachineid=instance.toolstackId, type="ROOT")[0].id

        vm = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0]
        ostypeid = vm.guestosid

        tags = self.cloudApi.listTags(resourceid = vm.id)
        distro = [x.value for x in tags if x.key=="distro"][0]


        t = self.cloudApi.createTemplate(
                            name=templateName,
                            displaytext=displayText,
                            ispublic=True,
                            ostypeid=ostypeid,
                            volumeid = volume)
        
        self.cloudApi.createTags(resourceids=[t.id],
                                 resourcetype="Template",
                                 tags=[{"key":"distro", "value":distro}])
        if [x for x in tags if x.key=="tools" and x.value=="yes"]:
            self.cloudApi.createTags(resourceids=[t.id],
                                     resourcetype="Template",
                                     tags=[{"key":"tools", "value":"yes"}])

        instance.setPowerState(origState)

    def createInstanceFromTemplate(self,
                                   templateName,
                                   name=None,
                                   vcpus=None,
                                   memory=None,
                                   vifs=None,
                                   extraConfig={},
                                   startOn=None,
                                   installTools=True):
        if not name:
            name = xenrt.util.randomGuestName()
        template = [x for x in self.cloudApi.listTemplates(templatefilter="all", name=templateName)][0]
        
        tags = self.cloudApi.listTags(resourceid = template.id)
        distro = [x.value for x in tags if x.key=="distro"][0]
        
        return self.__createInstance(distro,
                                     template=templateName,
                                     name=name,
                                     vcpus=vcpus,
                                     memory=memory,
                                     vifs=vifs,
                                     extraConfig=extraConfig,
                                     startOn=startOn,
                                     installTools=installTools)

    def ejectInstanceIso(self, instance):
        self.cloudApi.detachIso(virtualmachineid = instance.toolstackId)

    def createInstanceSnapshot(self, instance, name, memory=False, quiesce=False):
        self.cloudApi.createVMSnapshot(virtualmachineid = instance.toolstackId,
                                               name = name,
                                               snapshotmemory=memory,
                                               quiesce=quiesce)

    def getSnapshotId(self, instance, name):
        return self.cloudApi.listSnapshots(virtualmachineid = instance.toolstackId, name=name)[0].id

    def deleteInstanceSnapshot(self, instance, name):
        self.cloudApi.deleteVMSnapshot(vmsnapshotid = self.getSnapshotId(instance, name))

    def revertInstanceToSnapshot(self, instance, name):
        self.cloudApi.revertToVMSnapshot(vmsnapshotid = self.getSnapshotId(instance, name))


    def downloadTemplate(self, templateName, downloadLocation):
        template = [x for x in self.cloudApi.listTemplates(templatefilter="all") if x.displaytext == templateName][0].id
        rsp = self.cloudApi.extractTemplate(mode = "HTTP_DOWNLOAD", id = template)
        xenrt.util.command("wget -nv '%s' -O '%s'" % (rsp.url, downloadLocation))
        
    def findOrCreateServiceOffering(self, cpus, memory):               
        svcOfferingExist = [x for x in self.cloudApi.listServiceOfferings() if x.cpunumber == cpus and x.memory == memory]        
        if svcOfferingExist :
            return svcOfferingExist[0].id
        else :
            xenrt.TEC().logverbose("Creating New Service Offering ")
            svcOfferingNew = self.cloudApi.createServiceOffering(cpunumber=cpus,
                                                                         memory=memory,
                                                                         name="CPUs=%d ,Memory=%d MB offering" %(cpus,memory),
                                                                         displaytext="New Offering",
                                                                         cpuspeed=1000)
            return svcOfferingNew.id       
        
    def findOrCreateDiskOffering(self, disksize):
        xenrt.log("Inside the disk Offering")        
        diskOfferingExist = [x for x in self.cloudApi.listDiskOfferings() if x.disksize == disksize]        
        if diskOfferingExist :
            return diskOfferingExist[0].id
        else :
            xenrt.TEC().logverbose("Creating new Disk Offering ")
            diskOfferingNew = self.cloudApi.createDiskOffering(disksize=disksize,
                                                                      name="Disk=%d GB offering" %disksize,
                                                                      displaytext="Disk Offering")
            return diskOfferingNew.id

    def instanceScreenshot(self, instance, path):
        keys={"cmd": "access",
              "vm": instance.toolstackId}
        keys = self.marvin.signCommand(keys)
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

    def addTemplateIfNotPresent(self, hypervisor, templateFormat, distro, url, zone):

        if zone:
            zoneid = self.cloudApi.listZones(name=zone)[0].id
        else:
            zoneid = self.getDefaultZone().id
        
        templates = [x for x in self.cloudApi.listTemplates(templatefilter="all") if ( \
                                    x.hypervisor == hypervisor and \
                                    x.displaytext == distro and \
                                    x.zoneid == zoneid)]
        if not templates:
            xenrt.TEC().logverbose("Template is not present, registering")

            zone = self.cloudApi.listZones()[0].id

            osname = self.mgtsvr.lookup(["OS_NAMES", distro])

            ostypeid = self.cloudApi.listOsTypes(description=osname)[0].id

            self.cloudApi.registerTemplate(zoneid=zoneid,
                                           ostypeid=ostypeid,
                                           name="%s-%s" % (distro, xenrt.randomSuffix()),
                                           displaytext=distro,
                                           ispublic=True,
                                           url=url,
                                           hypervisor=hypervisor,
                                           format=templateFormat)

        # Now wait until the Template is ready
        deadline = xenrt.timenow() + 3600
        xenrt.TEC().logverbose("Waiting for Template to be ready")
        while True:
            try:
                template = [x for x in self.cloudApi.listTemplates(templatefilter="all") if ( \
                                            x.hypervisor == hypervisor and \
                                            x.displaytext == distro and \
                                            x.zoneid == zoneid)][0]
                if template.isready:
                    break
                else:
                    xenrt.TEC().logverbose("Status: %s" % template.status)
            except:
                pass
            if xenrt.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for template to be ready")
            xenrt.sleep(15)
        return template.id

    def addIsoIfNotPresent(self, distro, isoName, isoRepo, zone):
        if zone:
            zoneid = self.cloudApi.listZones(name=zone)[0].id
        else:
            zoneid = self.getDefaultZone().id
        isos = [x for x in self.cloudApi.listIsos(isofilter="all") if x.displaytext == isoName and x.zoneid == zoneid]
        if not isos:
            xenrt.TEC().logverbose("ISO is not present, registering")
            if isoRepo == xenrt.IsoRepository.Windows:
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP"), isoName)
            elif isoRepo == xenrt.IsoRepository.Linux:
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP_STATIC"), isoName)
            else:
                raise xenrt.XRTError("ISO Repository not recognised")

            zone = self.cloudApi.listZones()[0].id
            if distro:
                osname = self.mgtsvr.lookup(["OS_NAMES", distro])
            else:
                osname = "None"

            ostypeid = self.cloudApi.listOsTypes(description=osname)[0].id
            self.cloudApi.registerIso(zoneid= zoneid,
                                      ostypeid=ostypeid,
                                      name="%s-%s" % (isoName, xenrt.randomSuffix()),
                                      displaytext=isoName,
                                      ispublic=True,
                                      url=url)

        # Now wait until the ISO is ready
        deadline = xenrt.timenow() + 3600
        xenrt.TEC().logverbose("Waiting for ISO to be ready")
        while True:
            try:
                iso = [x for x in self.cloudApi.listIsos(isofilter="all") if x.displaytext == isoName and x.zoneid == zoneid][0]
                if iso.isready:
                    break
                else:
                    xenrt.TEC().logverbose("Status: %s" % iso.status)
            except:
                pass
            if xenrt.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for ISO to be ready")
            xenrt.sleep(15)
        return iso.id

class NetworkProvider(object):

    @staticmethod
    def factory(cloudstack, zoneid, instance, config):
        # Is this a basic zone?
        cls = None
        if cloudstack.cloudApi.listZones(id=zoneid)[0].networktype == "Basic":
            cls = BasicNetworkProvider
        else:
            if config.has_key("networktype") and config['networktype']:
                networkType = config['networktype']
            else:
                networkType = "IsolatedWithSourceNAT"
            xenrt.TEC().logverbose("Finding a network provider for %s" % networkType)
            if networkType == "IsolatedWithSourceNAT":
                cls = AdvancedNetworkProviderIsolatedWithSourceNAT
            elif networkType == "IsolatedWithStaticNAT":
                cls = AdvancedNetworkProviderIsolatedWithStaticNAT
            elif networkType == "IsolatedWithSourceNATAsymmetric":
                cls = AdvancedNetworkProviderIsolatedWithSourceNATAsymmetric
                

        if not cls:
            raise xenrt.XRTError("No suitable network provider found")

        return cls(cloudstack, zoneid, instance, config)

    def __init__(self, cloudstack, zoneid, instance, config):
        self.cloudstack = cloudstack
        self.zoneid = zoneid
        self.instance = instance
        self.config = config

    def getSecurityGroupIds(self):
        # Do we need to sort out a security group?
        if self.cloudstack.cloudApi.listZones(id=self.zoneid)[0].securitygroupsenabled:
            secGroups = self.cloudstack.cloudApi.listSecurityGroups(securitygroupname="xenrt_default_sec_grp")
            if not isinstance(secGroups, list):
                domainid = self.cloudstack.cloudApi.listDomains(name='ROOT')[0].id
                secGroup = self.cloudstack.cloudApi.createSecurityGroup(name= "xenrt_default_sec_grp", account="system", domainid=domainid)
                self.cloudstack.cloudApi.authorizeSecurityGroupIngress(securitygroupid = secGroup.id,
                                                                       protocol="TCP",
                                                                       startport=0,
                                                                       endport=65535,
                                                                       cidrlist = "0.0.0.0/0")
                self.cloudstack.cloudApi.authorizeSecurityGroupIngress(securitygroupid = secGroup.id,
                                                                       protocol="ICMP",
                                                                       icmptype=-1,
                                                                       icmpcode=-1,
                                                                       cidrlist = "0.0.0.0/0")
                secGroupId = secGroup.id
            else:
                secGroupId = secGroups[0].id
            secGroupIds = [secGroupId]
        else:
            secGroupIds = []

        return secGroupIds

    def getNetworkIds(self):
        raise xenrt.XRTError("Not Implemented")

    def setupNetworkAccess(self):
        pass

class BasicNetworkProvider(NetworkProvider):
    def getNetworkIds(self):
        return []

class AdvancedNetworkProviderIsolated(NetworkProvider):
    def __init__(self, cloudstack, zoneid, instance, config):
        super(AdvancedNetworkProviderIsolated, self).__init__(cloudstack, zoneid, instance, config)
        self.network = None
    
    def getNetworkIds(self):
        if self.config.has_key('networkname') and self.config['networkname']:
            netName = self.config['networkname']
        else:
            netName = "XenRT-IsolatedSourceNAT-%s" % self.zoneid


        nets = [x for x in self.cloudstack.cloudApi.listNetworks(zoneid=self.zoneid) or [] if x.name==netName]
        if len(nets) > 0:
            self.network = nets[0].id
        else:
            netOffering = [x.id for x in self.cloudstack.cloudApi.listNetworkOfferings(name='DefaultIsolatedNetworkOfferingWithSourceNatService')][0]
            net = self.cloudstack.cloudApi.createNetwork(name=netName,
                                                         displaytext=netName,
                                                         networkofferingid=netOffering,
                                                         zoneid=self.zoneid).id
            self.cloudstack.cloudApi.associateIpAddress(networkid=net)
            cidr = self.cloudstack.cloudApi.listNetworks(id=net)[0].cidr
            self.cloudstack.cloudApi.createEgressFirewallRule(protocol="all", cidrlist=[cidr], networkid=net)
            self.network = net

        return [self.network]

class AdvancedNetworkProviderIsolatedWithSourceNAT(AdvancedNetworkProviderIsolated):

    def _getIP(self):
        return self.cloudstack.cloudApi.listPublicIpAddresses(associatednetworkid=self.network, issourcenat=True)[0]
        

    def setupNetworkAccess(self):
        ip = self._getIP()

        # For each communication port, find a free port on the NAT IP to use
        for p in self.instance.os.tcpCommunicationPorts.keys():
            existingRules = self.cloudstack.cloudApi.listPortForwardingRules(ipaddressid=ip.id) or []
            i = 1025
            # Find a free port, by checking the existing rules
            while True:
                ok = True
                for r in existingRules:
                    if i >= int(r.publicport) and i <= int(r.publicendport):
                        ok = False
                        break
                if ok:
                    break
                i += 1

                if i > 65535:
                    raise xenrt.XRTError("Not enough ports available for port forwarding")

            # Crete the rule
            self.cloudstack.cloudApi.createPortForwardingRule(openfirewall=True,
                                                              protocol="TCP",
                                                              publicport=i,
                                                              publicendport=i,
                                                              privateport=self.instance.os.tcpCommunicationPorts[p],
                                                              privateendport=self.instance.os.tcpCommunicationPorts[p],
                                                              ipaddressid=ip.id,
                                                              virtualmachineid=self.instance.toolstackId)

            # And update the inbound IP map
            self.instance.inboundmap[p] = (ip.ipaddress, i)

        self.instance.outboundip = ip.ipaddress

class AdvancedNetworkProviderIsolatedWithSourceNATAsymmetric(AdvancedNetworkProviderIsolatedWithSourceNAT):
    def _getIP(self):
        # First see if there's an IP not being used for source NAT or static NAT

        # If yes, use it, otherwise create a new one
        return None

class AdvancedNetworkProviderIsolatedWithStaticNAT(AdvancedNetworkProviderIsolated):
    def setupNetworkAccess(self):
        # Acquire IP for network

        ip = self.cloudstack.cloudApi.associateIpAddress(networkid=self.network).ipaddress
      
        xenrt.TEC().logverbose("Got IP, ID=%s, Address=%s" % (ip.id, ip.ipaddress))

        # Setup static NAT to this VM
        self.cloudstack.cloudApi.enableStaticNat(ipaddressid=ip.id, virtualmachineid=self.instance.toolstackId)
        
        self.instance.inboundip = ip.ipaddress
        self.instance.outboundip = ip.ipaddress
