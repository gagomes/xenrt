import random, string, os, os.path
import xenrt, xenrt.lib.xenserver


class TCMultipleLunCreation(xenrt.TestCase):
    def run(self, arglist):
        # Support for provisioning LUNs from sequence.
        host = self.getDefaultHost()
        
        # Create Fibre Channel LUNs.
        if xenrt.TEC().lookup("FC_PROVIDER",None):
            initiatorList = {}
            
            self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.FibreChannel)

            initiatorList[host.getIP()] = host.getFCWWPNInfo()
            
            self.netAppFiler.provisionLuns(2, 3, initiatorList)
            self.scsiids = map(lambda x : x.getID(), self.netAppFiler.getLuns())
            xenrt.TEC().logverbose(", ".join(self.scsiids))
            self.pause("Check luns")
        else:
            raise xenrt.XRTError("No fibre channel configuration in the XenRT site")
        
