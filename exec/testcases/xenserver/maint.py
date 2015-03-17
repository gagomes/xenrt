import xenrt, xenrt.lib.xenserver

import uuid, os

class TCCreateVMTemplate(xenrt.TestCase):
    def run(self, arglist):
        m = xenrt.rootops.MountNFS(xenrt.TEC().lookup("SHARED_VHD_PATH_NFS"))
        h = self.getDefaultHost()
        for a in arglist:
            if a[0] in ("v", "w"):
                args = {"distro": a}
                fulldistro = a
            else:
                (distro, arch) = xenrt.getDistroAndArch(a)
                args = {"distro": distro, "arch": arch}
                fulldistro = "%s_%s" % (distro, arch)
            g = h.createBasicGuest(notools=True, nodrivers=True, **args)
            if g.windows:
                g.installWICIfRequired()
                g.installDotNet35()
                g.installDotNet4()
                g.installPowerShell()
            g.prepareForTemplate()
            vdiuuid = h.minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % g.getUUID(), params="vdi-uuid")[0]
            cfg = "%s/%s.cfg" % (m.getMount(), fulldistro)
            if os.path.exists(cfg):
                with open(cfg) as f:
                    u = f.read().strip()
            else:
                u = str(uuid.uuid4())
            xenrt.rootops.sudo("sh -c 'echo %s > %s.part'" % (u, cfg))
            vhd = "%s/%s.vhd" % (m.getMount(), u)
            xenrt.rootops.sudo("wget -O %s.part 'http://%s/export_raw_vdi?vdi=%s&format=vhd' --user=root --password=%s" % (vhd, h.getIP(), vdiuuid, h.password))
            xenrt.rootops.sudo("mv %s.part %s" % (vhd, vhd))
            xenrt.rootops.sudo("mv %s.part %s" % (cfg, cfg))
            g.uninstall()

