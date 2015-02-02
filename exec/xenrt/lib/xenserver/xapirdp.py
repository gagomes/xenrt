# XenRT: Test harness for Xen and the XenServer product family
#
# RDP Operations on windows and linux guests via Xapi .  
#

import xenrt

class XapiRdp(object):
    def __init__(self,guest):
        self.guest = guest
        self.host = self.guest.getHost()

    def enableRdp(self):
        """ Enable the RDP via xapi cmd : Returns 0 if success else 1 """

        xenrt.TEC().logverbose("XAPI trying to enable RDP for the guest %s on the host %s" % (self.guest,self.host))
        cmd = "xe vm-call-plugin vm-uuid=%s plugin=guest-agent-operation fn=request-rdp-on" % (self.guest.getUUID())
        return self.host.execdom0(cmd, retval="code")

    def disableRdp(self):
        """ Disable the RDP via xapi cmd : Returns 0 if success else 1"""

        xenrt.TEC().logverbose("XAPI trying to disable RDP for the guest %s on the host %s" % (self.guest,self.host))
        cmd = "xe vm-call-plugin vm-uuid=%s plugin=guest-agent-operation fn=request-rdp-off" % (self.guest.getUUID())
        return self.guest.getHost().execdom0(cmd, retval="code")

    def isRdpEnabled(self):
        """ Check that RDP is enabled on the guest : Returns True if enabled else False """

        xenrt.TEC().logverbose("XAPI trying to check the status of RDP for the guest %s on the host %s" % (self.guest,self.host))
        path = "/local/domain/%u/data/ts" % (self.host.getDomid(self.guest))
        rdpStatus = (self.host.xenstoreExists(path)) and (self.host.xenstoreRead(path)=="1")
        return rdpStatus



