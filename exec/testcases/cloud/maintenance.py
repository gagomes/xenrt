import xenrt
import shutil

class TCGenerateTemplate(xenrt.TestCase):
    def run(self, arglist):
        cloud = self.getDefaultToolstack()
        assert isinstance(cloud, xenrt.lib.cloud.CloudStack)
        for distro in arglist:
            # Don't install the tools - we want up to date drivers
            instance = cloud.createInstance(distro=distro, installTools=False)
            templateName = xenrt.randomGuestName()
            cloud.createTemplateFromInstance(instance, templateName)
            d = xenrt.TempDirectory()
            hypervisor = cloud.instanceHypervisorType(instance, nativeCloudType=True)
            templateFormat = cloud._templateFormats[hypervisor].lower()
            cloud.downloadTemplate(templateName, "%s/%s.%s" % (d.path(), distro, templateFormat))
            xenrt.util.command("bzip2 %s/%s.%s" % (d.path(), distro, templateFormat))
            m = xenrt.MountNFS(xenrt.TEC().lookup("EXPORT_CCP_TEMPLATES_NFS"))
            xenrt.sudo("mkdir -p %s/%s" % (m.getMount(), hypervisor))
            xenrt.sudo("cp %s/%s.%s.bz2 %s/%s/" % (d.path(), distro, templateFormat, m.getMount(), hypervisor))
            d.remove()

