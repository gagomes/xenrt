import xenrt
import requests, os.path

__all__ = ["VirtualMediaFactory"]

@xenrt.irregularName
def VirtualMediaFactory(machine):
    bmc = machine.lookup("BMC_TYPE", None)
    if bmc == "SUPERMICRO":
        return VirtualMediaSuperMicro(machine)
    else:
        return VirtualMediaBase(machine)

class VirtualMediaBase(object):

    def __init__(self, machine):
        self.machine = machine

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
        self.session.post("http://%s/cgi/login.cgi" % self.machine.lookup("BMC_ADDRESS"), data={"name": self.machine.lookup("IPMI_USERNAME"), "pwd": self.machine.lookup("IPMI_PASSWORD")})

    def unmountCD(self):
        self._login()
        self.session.post("http://%s/cgi/op.cgi" % self.machine.lookup("BMC_ADDRESS"), data={"op": "umount_iso"})
        
    def mountCD(self, location):
        cifs = self._exportCifs(location)
        self._login()
        self.session.post("http://%s/cgi/op.cgi" % self.machine.lookup("BMC_ADDRESS"), data={"op": "config_iso", "host": xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"), "path": "\\%s" % cifs, "user": "", "pwd": ""})
        self.session.post("http://%s/cgi/op.cgi" % self.machine.lookup("BMC_ADDRESS"), data={"op": "mount_iso"})

    def _exportCifs(self, location):
        if not os.path.exists(location):
            raise xenrt.XRTError("Asked to mount non-existant ISO file")
        d = xenrt.WebDirectory()
        d.copyIn(location)
        return d.getCIFSPath() + "\\" + os.path.basename(location)
        
