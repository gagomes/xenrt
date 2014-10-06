import xenrt
import requests, os.path

__all__ = ["VirtualMediaFactory"]

def VirtualMediaFactory(host):
    bmc = host.lookup("BMC_TYPE", None)
    if bmc == "SUPERMICRO":
        return VirtualMediaSuperMicro(host)
    else:
        return VirtualMediaBase(host)

class VirtualMediaBase(object):

    def __init__(self, host):
        self.host = host

    @property
    def supportedMediaTypes(self):
        return []

    def unmountCD(self):
        return

    def unmountUSB(self):
        return

class VirtualMediaSuperMicro(VirtualMediaBase):
    @property
    def supportedMediaTypes(self):
        return ["CD"]

    def _login(self):
        self.session = requests.Session()
        self.session.post("http://%s/cgi/login.cgi" % self.host.lookup("BMC_ADDRESS"), data={"name": self.host.lookup("IPMI_USERNAME"), "pwd": self.host.lookup("IPMI_PASSWORD")})

    def unmountCD(self):
        self._login()
        self.session.post("http://%s/cgi/op.cgi" % self.host.lookup("BMC_ADDRESS"), data={"op": "umount_iso"})
        
    def mountCD(self, location):
        cifs = self._exportCifs(location)
        self._login()
        self.session.post("http://%s/cgi/op.cgi" % self.host.lookup("BMC_ADDRESS"), data={"op": "config_iso", "host": xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"), "path": cifs, "user": "", "pwd": ""})
        self.session.post("http://%s/cgi/op.cgi" % self.host.lookup("BMC_ADDRESS"), data={"op": "mount_iso"})

    def _exportCifs(self, location):
        d = xenrt.WebDirectory()
        d.copyIn(location)
        return d.getCIFSPath() + "\\" + os.path.basename(location)
        
