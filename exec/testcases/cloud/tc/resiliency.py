import xenrt
from datetime import datetime
import random

class _TCCloudResiliencyBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []
        args = self.parseArgsKeyValue(arglist)
        for zone in self.cloud.marvin.cloudApi.listZones():
            self.instances += self.createInstances(zoneName=zone.name,
                                                   distroList=args.has_key('distros') and args['distros'].split(','))
        map(lambda x:x.assertHealthy(), self.instances)

    def createInstances(self, zoneName, distroList=None, instancesPerDistro=1):
        instances = []
        zoneid = self.cloud.marvin.cloudApi.listZones(name=zoneName)[0].id
        # Use existing templates (if any)
        existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=zoneid)
        templateList = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)

        if len(templateList) != 0:
            # Use the template names
            templateList = map(lambda x:x.name, templateList)
        else:
            # Create templates based on the distro list
            for distro in distroList:    
                distroName = distro.replace('_','-')
                instance = self.cloud.createInstance(distro=distro, name='%s-template' % (distroName))
                templateName = '%s-tplt' % (distroName)
                self.cloud.createTemplateFromInstance(instance, templateName)
                instance.destroy()
                templateList.append(templateName)

        xenrt.TEC().logverbose('Using templates: %s' % (','.join(templateList)))

        # Create instances
        for templateName in templateList:
            instances += map(lambda x:self.cloud.createInstanceFromTemplate(templateName=templateName, 
                                                                            name='%s-%d' % (templateName.replace("_","-"), x)), range(instancesPerDistro))
        return instances

class TCStorageResiliency(_TCCloudResiliencyBase):

    def storageOutage(self, storageVM, durationSec):
        storageVM.shutdown(force=True)
        xenrt.sleep(durationSec)
        storageVM.start()

        map(lambda x:x.assertHealthy(), self.instances)
        # TODO - Check CCP health

    def run(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        storageVMName = args.has_key('storageVM') and args['storageVM'] or None
        storageVM = xenrt.TEC().registry.guestGet(storageVMName)
        storageVM.checkHealth()

        iterations = args.has_key('iterations') and args['iterations'] or 3
        outageDurationSec = args.has_key('outageDurationSec') and args['outageDurationSec'] or 60

        for i in range(iterations):
            self.runSubcase('storageOutage', (storageVM, outageDurationSec), 'StorageOutage', 'Iter-%d' % (i))

class _TCManServerResiliencyBase(_TCCloudResiliencyBase):

    def recover(self):
        pass

    def specificCheck(self):
        pass

    def genericCheck(self):
        map(lambda x:x.assertHealthy(), self.instances)
        # TODO - Check CCP health

    def run(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        iterations = self.args.has_key('iterations') and self.args['iterations'] or 3

        for i in range(iterations):
            self.runSubcase('outage', (), 'Outage', 'Iter-%d' % (i))
            self.runSubcase('recover', (), 'Recover', 'Iter-%d' % (i))
            self.runSubcase('specificCheck', (), 'SpecificCheck', 'Iter-%d' % (i))
            self.runSubcase('genericCheck', (), 'GenericCheck', 'Iter-%d' % (i))

    def waitForCCP(self):
        deadline = xenrt.timenow() + 600
        while True:
            try:
                self.cloud.cloudApi.listHosts()
                break
            except:
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Cloudstack Management did not come back after 10 minutes")
                xenrt.sleep(15) 

class TCManServerVMReboot(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.reboot()

    def recover(self):
        self.waitForCCP()


class TCManServerRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service cloudstack-management restart")

    def recover(self):
        self.waitForCCP()


class TCDBRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service mysqld restart")

    def recover(self):
        self.waitForCCP()


class TCDBOutage(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service mysqld stop")
        xenrt.sleep(120)
        msvm.execcmd("service mysqld start")

    def recover(self):
        self.waitForCCP()


