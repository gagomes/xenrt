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
        """ Enable the RDP via xapi cmd : Returns True if cmd success else False """

        xenrt.TEC().logverbose("XAPI trying to enable RDP for the guest %s on the host %s" % (self.guest,self.host))
        cmd = "xe vm-call-plugin vm-uuid=%s plugin=guest-agent-operation fn=request-rdp-on" % (self.guest.getUUID())
        return self.host.execdom0(cmd, retval="code") == 0

    def disableRdp(self):
        """ Disable the RDP via xapi cmd : Returns True if cmd success else False"""

        xenrt.TEC().logverbose("XAPI trying to disable RDP for the guest %s on the host %s" % (self.guest,self.host))
        cmd = "xe vm-call-plugin vm-uuid=%s plugin=guest-agent-operation fn=request-rdp-off" % (self.guest.getUUID())
        return self.host.execdom0(cmd, retval="code") == 0

    def isRdpEnabled(self):
        """ Check that RDP is enabled on the guest : Returns True if RDP enabled else False """

        xenrt.TEC().logverbose("XAPI trying to check the status of RDP for the guest %s on the host %s" % (self.guest,self.host))
        path = "/local/domain/%u/data/ts" % (self.guest.getDomid())
        tsPath = "/local/domain/%u/control/feature-ts2" % (self.guest.getDomid())
        rdpStatus = (self.host.xenstoreRead(tsPath)=="1") and (self.host.xenstoreRead(path)=="1")
        return rdpStatus



