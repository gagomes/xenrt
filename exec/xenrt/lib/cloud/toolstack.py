import xenrt
import logging
import os, urllib, re, random
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
                     "Simulator": xenrt.HypervisorType.simulator,
                     "LXC": xenrt.HypervisorType.lxc}

    # Mapping of hypervisors to template formats
    _templateFormats = {"XenServer": "VHD",
                        "KVM": "QCOW2",
                        "VMware": "OVA",
                        "Hyperv": "VHD",
                        "LXC": "TAR"}

    def __init__(self, place=None, ip=None):
        assert place or ip
        if not place:
            place = xenrt.GenericGuest("CS-MS")
            place.mainip = ip
            place.findPassword()
            place.findDistro()
        self.mgtsvr = xenrt.lib.cloud.ManagementServer(place)
        self.marvin = xenrt.lib.cloud.MarvinApi(self.mgtsvr)
        self.marvinCfg = {}

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

        # Verify instance name.  Names must start with a letter and contain only letters, numbers and hyphens
        result = re.findall('^[a-zA-Z][a-zA-Z0-9-]*$', name)
        xenrt.xrtAssert(len(result) == 1 and result[0] == name, 'Cloud instance name starts with a letter and contains only letters, numbers and hyphens')

        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        xenrt.TEC().registry.instancePut(name, instance)

        try:
    
            hypervisor = None
            if hypervisorType:
                if hypervisorType in self.__hypervisorTypeMapping.keys():
                    # This is a slight abuse of the interface, however it avoids
                    # unnecessary complications in sequence files with multiple names
                    # for the same hypervisor!
                    hypervisor = hypervisorType
                else:
                    hypervisor = self.hypervisorTypeToHypervisor(hypervisorType)
            startOnId = None
            startOnZoneId = None
            if startOn:
                hosts = [x for x in self.cloudApi.listHosts(name=startOn) if x.name==startOn]
                if len(hosts) != 1:
                    raise xenrt.XRTError("Cannot find host %s on cloud" % startOn)
                startOnId = hosts[0].id
                startOnZoneId = hosts[0].zoneid
                # Ignore any provided hypervisorType and set this based on the host
                hypervisor = hosts[0].hypervisor

            if template:
                t = [x for x in self.cloudApi.listTemplates(templatefilter="all", name=template) if x.name==template][0]
                xenrt.xrtAssert(t.hypervisor == hypervisor or not hypervisor, "Cannot specify different hypervisor when specifying a template")
                hypervisor = t.hypervisor
                xenrt.xrtAssert(not zone or t.zoneid == [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id, "Cannot specify different zone when specifying a template")
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
                    if not zone or t.zoneid == [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id:
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
                xenrt.xrtAssert(zoneid == [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id, "Specified Zone ID does not match template zone ID")

            if not zoneid:
                if zone:
                    zoneid = [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id
                elif startOnZoneId:
                    zoneid = startOnZoneId
                else:
                    zoneid = self.getDefaultZone().id
            svcOffering = self.findOrCreateServiceOffering(cpus = instance.vcpus , memory = instance.memory)

            xenrt.TEC().logverbose("Deploying VM")

            networkProvider = NetworkProvider.factory(self, zoneid, instance, hypervisor, extraConfig)

            secGroupIds = networkProvider.getSecurityGroupIds()
            networks = networkProvider.getNetworkIds()

            domainid = self.cloudApi.listDomains(name='ROOT')[0].id

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
                                                     networkids = networks,
                                                     account="admin",
                                                     domainid=domainid)

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

    def discoverInstanceAdvancedNetworking(self, instance):
        vm = self.cloudApi.listVirtualMachines(id=instance.toolstackId)[0]
        if self.cloudApi.listZones(id=vm.zoneid)[0].networktype == "Basic":
            xenrt.TEC().logverbose("Instance uses basic networking")
            return
        else:
            nic = vm.nic[0]
            if nic.type == "Shared":
                # Shared networking, no special access
                xenrt.TEC().logverbose("Instance uses shared networking")
                return
            elif nic.type == "Isolated":
                # First look for a static NAT IP
                vmips = [x for x in self.cloudApi.listPublicIpAddresses(associatednetworkid=nic.networkid, isstaticnat=True) or [] if x.virtualmachineid == instance.toolstackId]
                if vmips:
                    instance.inboundip = vmips[0].ipaddress
                    instance.outboundip = vmips[0].ipaddress
                    xenrt.TEC().logverbose("Found Static NAT IP %s" % vmips[0].ipaddress)
                    return
                else:
                    instance.outboundip = self.cloudApi.listPublicIpAddresses(associatednetworkid=nic.networkid, issourcenat=True)[0].ipaddress
                    xenrt.TEC().logverbose("Found Outbound IP %s" % instance.outboundip)
                    rules = [x for x in self.cloudApi.listPortForwardingRules(listall=True, networkid=nic.networkid) or [] if x.virtualmachineid==instance.toolstackId]
                    for p in instance.os.tcpCommunicationPorts.keys():
                        validrules = [x for x in rules if int(x.privateport) == instance.os.tcpCommunicationPorts[p]]
                        if not validrules:
                            raise xenrt.XRTError("Could not find valid port forwarding rule for %s" % p)
                        xenrt.TEC().logverbose("Found %s:%s for %s" % (validrules[0].ipaddress, validrules[0].publicport, p))
                        instance.inboundmap[p] = (validrules[0].ipaddress, int(validrules[0].publicport))

    def destroyInstance(self, instance):
        self.cloudApi.destroyVirtualMachine(id=instance.toolstackId, expunge=True)

    def setInstanceIso(self, instance, isoName, isoRepo):
        if isoRepo:
            self.addIsoIfNotPresent(None, isoName, isoRepo)
        isoId = [x for x in self.cloudApi.listIsos(name=isoName, isofilter="all") if x.name==isoName][0].id

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
            hosts = [x for x in self.cloudApi.listHosts(name=on) if x.name==on]
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
        instance.setPowerState(xenrt.PowerState.up)
        instance.os.preCloneTailor()
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
        template = [x for x in self.cloudApi.listTemplates(templatefilter="all", name=templateName) if x.name==templateName][0]
        
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
                                               quiescevm=quiesce)

    def getSnapshotId(self, instance, name):
        return [x for x in self.cloudApi.listVMSnapshot(virtualmachineid = instance.toolstackId, name=name, listall=True) if x.displayname==name][0].id

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
        if xenrt.TEC() == xenrt.GEC().anontec or xenrt.TEC().lookup("ALWAYS_DUMP_CS_DB", False, boolean=True):
            # CP-9393 We're the anonymous TEC, which means we are collecting job
            # logs, so get a database dump in addition to other logs
            self.mgtsvr.getDatabaseDump(path)
        if xenrt.TEC() == xenrt.GEC().anontec and xenrt.TEC().lookup("CCP_CODE_COVERAGE", False, boolean=True):
            self.mgtsvr.stop()
            try:
                sftp.copyTreeFrom("/coverage_results", path)
            except:
                xenrt.TEC().warning("Unable to collect code coverage data")
            self.mgtsvr.start()
        sftp.close()

    def addTemplateIfNotPresent(self, hypervisor, templateFormat, distro, url, zone):

        if zone:
            zoneid = [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id
        else:
            zoneid = self.getDefaultZone().id
        with xenrt.GEC().getLock("CCP_TEMPLATE_DOWNLOAD-%s-%s-%s" % (hypervisor, distro, zone)):
            
            templates = [x for x in self.cloudApi.listTemplates(templatefilter="all") if ( \
                                        x.hypervisor == hypervisor and \
                                        x.displaytext == distro and \
                                        x.zoneid == zoneid)]
            if not templates:
                xenrt.TEC().logverbose("Template is not present, registering")

                zone = self.cloudApi.listZones()[0].id

                osname = self.mgtsvr.lookup(["OS_NAMES", distro])

                ostypeid = [x for x in self.cloudApi.listOsTypes(description=osname) if x.description==osname][0].id

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
            zoneid = [x for x in self.cloudApi.listZones(name=zone) if x.name==zone][0].id
        else:
            zoneid = self.getDefaultZone().id
        with xenrt.GEC().getLock("CCP_ISO_DOWNLOAD-%s-%s" % (distro, zone)):
            isoList = self.cloudApi.listIsos(isofilter="all")
            if isinstance(isoList, list) and len(filter(lambda x:x.displaytext == isoName and x.zoneid == zoneid, isoList)) == 1:
                xenrt.TEC().logverbose('Found existing ISO: %s' % (isoList[0].displaytext))
            else:
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

                xenrt.TEC().logverbose('Looking for CCP OS Name: %s' % (osname))
                ostypeid = [x for x in self.cloudApi.listOsTypes(description=osname) if x.description==osname][0].id
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

    def getAllHypervisors(self):

        return self.marvin.cloudApi.listHosts(type="routing")

    def getAllHostInClusterByClusterId(self,clusterId):

        hostsInClusters = []
        hosts = self.getAllHypervisors()
        for h in hosts:
            if h.clusterid == clusterId:
                hostsInClusters.append(h)

        return hostsInClusters

    def _createDestroyInstance(self,host,distro=None):

        if not distro:
           distro = "debian70_x86-64"

        try:
            xenrt.TEC().logverbose("Creating VM instance on %s" % str(host.name))
            instance = self.createInstance(distro,startOn = host.name)

            xenrt.TEC().logverbose("Taking snapshot of instance")
            self.createInstanceSnapshot(instance,"sampleSnapshot")

            xenrt.TEC().logverbose("Deleting snapshot of instance")
            self.deleteInstanceSnapshot(instance,"sampleSnapshot")

            xenrt.TEC().logverbose("Destroying VM instance from %s" % str(host.name))
            self.destroyInstance(instance)
        except Exception, e:
            msg = "Create/destroy/snaphsot Instance failed on host %s with error %s" % (host.name,str(e))
            xenrt.TEC().reason(msg)
            raise xenrt.XRTFailure(msg)

    def _checkVM(self, vm):

        xenrt.TEC().registry.instanceGet(vm.name).assertHealthy()

    def _checkSystemVMs(self,sv):

        os.system("ping -c 10 %s > /tmp/ping" % str(sv.privateip))
        output = os.popen('cat /tmp/ping').read()
        m = re.search(", (\d+)% packet loss, time", output)

        if int(m.group(1)) >=5:
            reason = "System VM %s is not reachable" % str(sv.name)
            xenrt.TEC().reason(reason)
            raise xenrt.XRTFailure(reason)

    def _level1HealthCheck(self,ignoreHosts=None):

        errors = []

        xenrt.TEC().logverbose("Level 1 Health check in progress")

        xenrt.TEC().logverbose("Checking all the host in the cloud")
        hosts = self.getAllHypervisors()
        for host in hosts:
            if ignoreHosts:
                for h in ignoreHosts:
                    if host.name == h.name:
                        continue
            if host.state != 'Up':
                msg = 'Host %s is DOWN as per CLOUD' % host.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all the system VMs in the cloud")
        svms = self.marvin.cloudApi.listSystemVms()
        for svm in svms:
            if svm.state != 'Running':
                msg = 'System VM %s is DOWN as per CLOUD' % svm.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all Zones in the cloud")
        zones = self.marvin.cloudApi.listZones()
        for zone in zones:
            if zone.allocationstate != 'Enabled':
                msg  = 'Zone %s is DOWN as per CLOUD' % zone.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all Pods in the cloud")
        pods = self.marvin.cloudApi.listPods()
        for pod in pods:
            if pod.allocationstate != 'Enabled':
                msg  = 'Pod %s is DOWN as per CLOUD' % pod.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all Clusters in the cloud")
        clusters = self.marvin.cloudApi.listClusters()
        for cluster in clusters:
            if cluster.allocationstate != 'Enabled':
                msg  = 'Cluster %s is DOWN as per CLOUD' % cluster.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        #Commenting this out for the time being
        #xenrt.TEC().logverbose("Checking all the Networks in the cloud")
        #nws = self.marvin.cloudApi.listNetworks()
        #for nw in nws:
        #    if nw.state != 'Setup':
        #        msg = 'Network %s is DOWN as per CLOUD' % nw.name
        #        errors.append(msg)
        #        xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking Primary Storage in the cloud")
        sps = self.marvin.cloudApi.listStoragePools()
        for sp in sps:
            if sp.state != 'Up':
                msg = 'Storage %s is DOWN as per CLOUD' % sp.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all zones in the cloud")
        zs = self.marvin.cloudApi.listZones()
        for z in zs:
            if sp.state != 'Up':
                msg = 'Zone %s is Not enabled as per CLOUD' % z.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        xenrt.TEC().logverbose("Checking all the VMs in the cloud")
        vms = self.marvin.cloudApi.listVirtualMachines()
        for vm in vms:
            if vm.state != 'Running':
                msg = 'VM %s is DOWN as per CLOUD' % vm.name
                errors.append(msg)
                xenrt.TEC().reason(msg)

        return errors

    def _level2HealthCheck(self):

        errors = []
        xenrt.TEC().logverbose("Level 2 Health check in progress")

        xenrt.TEC().logverbose("Pinging all the System VMs")
        svms = self.marvin.cloudApi.listSystemVms()
        for svm in svms:
            try:
                self._checkSystemVMs(svm)
            except Exception, e:
                errors.append(str(e))

        return errors

    def _level3HealthCheck(self):

        errors = []
        xenrt.TEC().logverbose("Level 3 Health check in progress")

        xenrt.TEC().logverbose("Creating VM instance, snapshoting it and destroying VM")
        hosts = self.getAllHypervisors()
        try:
            xenrt.pfarm([xenrt.PTask(self._createDestroyInstance, host) for host in hosts])
        except Exception, e:
            errors.append(str(e))

        xenrt.TEC().logverbose("Checking health of all the VMs in the cloud")
        vms = self.marvin.cloudApi.listVirtualMachines()
        try:
            xenrt.pfarm([xenrt.PTask(self._checkVM, vm) for vm in vms])
        except Exception, e:
            errors.append("VM health check failed with error message %s " % (str(e)))

        return errors

    def healthCheck(self,listDownHost=None):

        errors = []

        errors = self._level1HealthCheck(listDownHost)
        if len(errors) > 0:
            xenrt.TEC().logverbose("Level 1 Health check of Cloud has failed")
            xenrt.TEC().logverbose(errors)
            m = ' '.join(errors)
            raise xenrt.XRTFailure(m)

        errors = self._level2HealthCheck()
        if len(errors) > 0:
            xenrt.TEC().logverbose("Level 2 Health check of Cloud has failed")
            xenrt.TEC().logverbose(errors)
            m = ' '.join(errors)
            raise xenrt.XRTFailure(m)

        errors = self._level3HealthCheck()
        if len(errors) > 0:
            xenrt.TEC().logverbose("Level 3 Health check of Cloud has failed")
            xenrt.TEC().logverbose(errors)
            m = ' '.join(errors)
            raise xenrt.XRTFailure(m)

        xenrt.TEC().logverbose("No problem found during the healthcheck of Cloud")

    def postDeploy(self):
        # Perform any post deployment steps
        if xenrt.TEC().lookup("WORKAROUND_CSTACK7320", False, boolean=True) and \
           "LXC" in [h.hypervisor for h in self.cloudApi.listHosts(type="routing")]:
            ostypeid = [x for x in self.cloudApi.listOsTypes(description="CentOS 6.5 (64-bit)") if x.description=="CentOS 6.5 (64-bit)"][0].id
            response = self.cloudApi.registerTemplate(zoneid=-1,
                                                      ostypeid=ostypeid,
                                                      name="CentOS 6.5(64-bit) no GUI (LXC)",
                                                      displaytext="CentOS 6.5(64-bit) no GUI (LXC)",
                                                      ispublic=True,
                                                      isextractable=True,
                                                      isfeatured=True,
                                                      url="%s/cloudTemplates/centos65_x86_64_2.tar.gz" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                                                      hypervisor="LXC",
                                                      format="TAR",
                                                      requireshvm=False)
            templateId = response[0].id
            # Now wait until the Template is ready
            deadline = xenrt.timenow() + 3600
            xenrt.TEC().logverbose("Waiting for Template to be ready")
            while True:
                try:
                    template = self.cloudApi.listTemplates(templatefilter="all", id=templateId)[0]
                    if template.isready:
                        break
                    else:
                        xenrt.TEC().logverbose("Status: %s" % template.status)
                except:
                    pass
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTError("Timed out waiting for LXC template to be ready")
                xenrt.sleep(15)

class NetworkProvider(object):

    @staticmethod
    def factory(cloudstack, zoneid, instance, hypervisor, config):
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
            elif networkType == "Shared":
                cls = AdvancedNetworkProviderShared
                

        if not cls:
            raise xenrt.XRTError("No suitable network provider found")

        return cls(cloudstack, zoneid, instance, hypervisor, config)

    def __init__(self, cloudstack, zoneid, instance, hypervisor, config):
        self.cloudstack = cloudstack
        self.zoneid = zoneid
        self.instance = instance
        self.config = config
        self.hypervisor = hypervisor

    def getSecurityGroupIds(self):
        # Do we need to sort out a security group?
        if self.cloudstack.cloudApi.listZones(id=self.zoneid)[0].securitygroupsenabled and self.hypervisor.lower() != "vmware":
            with xenrt.GEC().getLock("CCP_SEC_GRP-%s" % self.zoneid):
                secGroups = self.cloudstack.cloudApi.listSecurityGroups(securitygroupname="xenrt_default_sec_grp")
                if not isinstance(secGroups, list):
                    domainid = self.cloudstack.cloudApi.listDomains(name='ROOT')[0].id
                    secGroup = self.cloudstack.cloudApi.createSecurityGroup(name= "xenrt_default_sec_grp", account="admin", domainid=domainid)
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
    def __init__(self, cloudstack, zoneid, instance, hypervisor, config):
        super(AdvancedNetworkProviderIsolated, self).__init__(cloudstack, zoneid, instance, hypervisor, config)
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
            # Find the network for this zone
            gw=self.cloudstack.cloudApi.listVlanIpRanges(physicalnetworkid=self.cloudstack.cloudApi.listPhysicalNetworks(zoneid = self.zoneid)[0].id)[0].gateway
            domain = "xenrtcloud"
            if gw == xenrt.TEC().lookup(["NETWORK_CONFIG", "SECONDARY", "GATEWAY"]):
                domain = "nsec-xenrtcloud"
            else:
                for v in xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS"]).keys():
                    if gw == xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", v, "GATEWAY"], None):
                        domain = "%s-xenrtcloud" % v.lower()
                

            netOffering = [x.id for x in self.cloudstack.cloudApi.listNetworkOfferings(name='DefaultIsolatedNetworkOfferingWithSourceNatService')][0]
            domainid = self.cloudstack.cloudApi.listDomains(name='ROOT')[0].id
            net = self.cloudstack.cloudApi.createNetwork(name=netName,
                                                         displaytext=netName,
                                                         networkofferingid=netOffering,
                                                         zoneid=self.zoneid,
                                                         account="admin",
                                                         domainid=domainid,
                                                         networkdomain=domain).id
            self.cloudstack.cloudApi.associateIpAddress(networkid=net)
            cidr = self.cloudstack.cloudApi.listNetworks(id=net)[0].cidr
            self.cloudstack.cloudApi.createEgressFirewallRule(protocol="all", cidrlist=[cidr], networkid=net)
            self.network = net

        return [self.network]

class AdvancedNetworkProviderIsolatedWithSourceNAT(AdvancedNetworkProviderIsolated):

    def _getOutboundIP(self):
        return self.cloudstack.cloudApi.listPublicIpAddresses(associatednetworkid=self.network, issourcenat=True)[0]
    
    def _getInboundIP(self):
        return self._getOutboundIP()

    def setupNetworkAccess(self):
        ip = self._getInboundIP()

        with xenrt.GEC().getLock("CCP_NETWORK_PORTFORWARD-%s" % ip):
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

                try:
                    # Crete the rule
                    self.cloudstack.cloudApi.createPortForwardingRule(openfirewall=True,
                                                                      protocol="TCP",
                                                                      publicport=i,
                                                                      publicendport=i,
                                                                      privateport=self.instance.os.tcpCommunicationPorts[p],
                                                                      privateendport=self.instance.os.tcpCommunicationPorts[p],
                                                                      ipaddressid=ip.id,
                                                                      virtualmachineid=self.instance.toolstackId)
                except:
                    # Workaround for CS-20617
                    # Wait for the virtual routers to be running

                    deadline = xenrt.timenow() + 600
                    while True:
                        if not [x for x in self.cloudstack.cloudApi.listRouters(listall=True, networkid=self.network) or [] if x.state != "Running"]:
                            break
                        if xenrt.timenow() > deadline:
                            raise xenrt.XRTFailure("Timed out waiting for VR to come up")
                        xenrt.sleep(15)

                    # Now the VR is up, try again
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

        self.instance.outboundip = self._getOutboundIP().ipaddress

class AdvancedNetworkProviderIsolatedWithSourceNATAsymmetric(AdvancedNetworkProviderIsolatedWithSourceNAT):
    def _getInboundIP(self):
        # Lock around this in case another thread is setting up a static NAT
        with xenrt.GEC().getLock("CCP_NETWORK_IP-%s" % self.network):
            # First see if there's an IP not being used for source NAT or static NAT
            addrs = self.cloudstack.cloudApi.listPublicIpAddresses(associatednetworkid=self.network, issourcenat=False, isstaticnat=False)
        if addrs:
            return addrs[0]
        else:
            # There isn't - create one
            return self.cloudstack.cloudApi.associateIpAddress(networkid=self.network).ipaddress


class AdvancedNetworkProviderIsolatedWithStaticNAT(AdvancedNetworkProviderIsolated):
    def setupNetworkAccess(self):
        # Lock around this in case another thread is looking for a free IP that isn't Source NAT
        with xenrt.GEC().getLock("CCP_NETWORK_IP-%s" % self.network):
            # Acquire IP for network

            ip = self.cloudstack.cloudApi.associateIpAddress(networkid=self.network).ipaddress
      
            xenrt.TEC().logverbose("Got IP, ID=%s, Address=%s" % (ip.id, ip.ipaddress))

            try:
                # Setup static NAT to this VM
                self.cloudstack.cloudApi.enableStaticNat(ipaddressid=ip.id, virtualmachineid=self.instance.toolstackId)
            except:
                # Workaround for CS-20617
                # Wait for the virtual routers to be running

                deadline = xenrt.timenow() + 600
                while True:
                    if not [x for x in self.cloudstack.cloudApi.listRouters(listall=True, networkid=self.network) or [] if x.state != "Running"]:
                        break
                    if xenrt.timenow() > deadline:
                        raise xenrt.XRTFailure("Timed out waiting for VR to come up")
                    xenrt.sleep(15)

                # Now the VR is up, try again
                self.cloudstack.cloudApi.enableStaticNat(ipaddressid=ip.id, virtualmachineid=self.instance.toolstackId)
        
        self.instance.inboundip = ip.ipaddress
        self.instance.outboundip = ip.ipaddress
        
        for p in self.instance.os.tcpCommunicationPorts.values():
            self.cloudstack.cloudApi.createFirewallRule(ipaddressid=ip.id, protocol="TCP", cidrlist=["0.0.0.0/0"], startport=p, endport=p)
            
class AdvancedNetworkProviderShared(NetworkProvider):
    def __init__(self, cloudstack, zoneid, instance, hypervisor, config):
        super(AdvancedNetworkProviderShared, self).__init__(cloudstack, zoneid, instance, hypervisor, config)
    
    def getNetworkIds(self):
        if self.config.has_key('networkname') and self.config['networkname']:
            netName = self.config['networkname']
        else:
            netName = "XenRT-Shared-%s" % self.zoneid

        nets = [x for x in self.cloudstack.cloudApi.listNetworks(zoneid=self.zoneid) or [] if x.name==netName]
        if len(nets) > 0:
            self.network = nets[0].id
        else:
            if self.config.has_key("sharednetworkvlan"):
                vlanName = self.config["sharednetworkvlan"]
            else:
                vlanName = random.choice([x for x in xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS"]).keys() if x.startswith("VR")])
            vlan = xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", vlanName])

            if self.config.has_key("sharednetworksize"):
                sharednetworksize = self.config['sharednetworksize']
            else:
                sharednetworksize = 10

            ips = xenrt.StaticIP4Addr.getIPRange(sharednetworksize, network=vlanName)


            netOffering = [x.id for x in self.cloudstack.cloudApi.listNetworkOfferings(name='DefaultSharedNetworkOffering') if x.name=='DefaultSharedNetworkOffering'][0]
            domainid = self.cloudstack.cloudApi.listDomains(name='ROOT')[0].id
            net = self.cloudstack.cloudApi.createNetwork(name=netName,
                                                         displaytext=netName,
                                                         networkofferingid=netOffering,
                                                         zoneid=self.zoneid,
                                                         startip=ips[0].getAddr(),
                                                         endip=ips[-1].getAddr(),
                                                         vlan=vlan['ID'],
                                                         netmask=vlan['SUBNETMASK'],
                                                         gateway=vlan['GATEWAY'],
                                                         account="admin",
                                                         domainid=domainid,
                                                         networkdomain="%s-xenrtcloud" % vlanName.lower()).id

            self.network = net

        return [self.network]
