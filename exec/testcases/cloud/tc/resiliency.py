import xenrt
from datetime import datetime
import random

class TCSecondaryStorageResiliency(xenrt.TestCase):

    def tailorBuiltInTemplateForXenRT(self, template):
        """Make a built-in template look like a tempalte created by XenRT"""
        if 'password' not in xenrt.TEC().lookup('ROOT_PASSWORDS'):
            xenrt.TEC().config.setVariable('ROOT_PASSWORDS', 'password ' + xenrt.TEC().lookup('ROOT_PASSWORDS'))
            xenrt.TEC().logverbose('ROOT_PASSWORDS: %s' % (xenrt.TEC().lookup('ROOT_PASSWORDS')))
        if len(filter(lambda x:x.key == 'distro', template.tags)) == 0:
            if 'CentOS' in template.ostypename and '5.6' in template.ostypename and '64' in template.ostypename:
                self.cloud.marvin.cloudApi.createTags(resourceids=[template.id],
                                                resourcetype="Template",
                                                tags=[{"key":"distro", "value":'centos56_x86-64'}])
            else:
                raise xenrt.XRTError('Unknown built in template type')

    def createInstances(self, zoneName, distroList=None, instancesPerDistro=1):
        templateList = []
        instances = []
        if not distroList:
            # Use existing templates [if present] or built in template
            zoneid = self.cloud.marvin.cloudApi.listZones(name=zoneName)[0].id
            existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=zoneid)
            templateList = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)
            if len(templateList) == 0:
                templateList = filter(lambda x:x.templatetype == 'BUILTIN', existingTemplates) 
                map(lambda x:self.tailorBuiltInTemplateForXenRT(x), templateList)
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
        self.storageVM = args.has_key('storageVM') and args['storageVM']

        for zone in self.cloud.marvin.cloudApi.listZones():
            self.instances += self.createInstances(zoneName=zone.name,
                                                   distroList=args.has_key('distros') and args['distros'].split(','))
            map(lambda x:x.assertHealthy(), self.instances)

    def run(self, arglist):
        pass
