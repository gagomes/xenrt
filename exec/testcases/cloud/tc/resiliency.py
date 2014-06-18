import xenrt
from datetime import datetime
import random

class TCStorageResiliency(xenrt.TestCase):

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
                                                                            name='%s-%d' % (templateName, x)), range(instancesPerDistro))
        return instances

    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []
        args = self.parseArgsKeyValue(arglist)
        for zone in self.cloud.marvin.cloudApi.listZones():
            self.instances += self.createInstances(zoneName=zone.name,
                                                   distroList=args.has_key('distros') and args['distros'].split(','))
        map(lambda x:x.assertHealthy(), self.instances)

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
