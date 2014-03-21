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
            cloud.downloadTemplate(templateName, "%s/%s.vhd" % (d.path(), distro))
            xenrt.util.command("bzip2 %s/%s.vhd" % (d.path(), distro))
            m = xenrt.MountNFSv3(xenrt.TEC().lookup("EXPORT_CCP_TEMPLATES_NFS"))
            xenrt.sudo("cp %s/%s.vhd.bz2 %s" % (d.path(), distro, m.getMount()))
            d.remove()

