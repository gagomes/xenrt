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
                args = {"distro": a, "arch": arch}
                fulldistro = "%s_%s" % (distro, arch)
            g = h.createBasicGuest(**args)
            g.shutdown()
            vdiuuid = h.minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % g.getUUID(), params="vdi-uuid")[0]
            cfg = "%s/%s.cfg" % (m.getMount(), fulldistro)
            if os.path.exists(cfg):
                with open(cfg) as f:
                    u = f.read().strip()
            else:
                u = str(uuid.uuid4())
                with open(cfg, "w") as f:
                    f.write(u)
            vhd = "%s/%s.vhd" % (m.getMount(), u)
            xenrt.rootops.sudo("wget -O %s 'http://%s/export_raw_vdi?vdi=%s&format=vhd' --user=root --password=%s" % (vhd, h.getIP(), vdiuuid, h.password))

