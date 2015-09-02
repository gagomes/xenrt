#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["PowerState", "LifecycleOperation", "HypervisorType", "IsoRepository", "InstallMethod", "XenServerLicenseSKU","WindowsVersions"]

# All known Windows distros
windowsdistros = [('w2k3eesp2pae','Windows Server Enterprise Edition SP2 with PAE Enabled'),
                  ('w2k3ee','Windows Server 2003 SP0 Enterprise'),
                  ('w2k3eesp1','Windows Server 2003 SP1 Enterprise'),
                  ('w2k3eer2','Windows Server 2003 SP1 R2 Enterprise'),
                  ('w2k3eesp2','Windows Server 2003 SP2 Enterprise'),
                  ('w2k3eesp2-x64','Windows Server 2003 SP2 Enterprise x64'),
                  ('w2k3se','Windows Server 2003 SP0 Standard'),
                  ('w2k3sesp1','Windows Server 2003 SP1 Standard'),
                  ('w2k3ser2','Windows Server 2003 SP1 R2 Standard'),
                  ('w2k3sesp2','Windows Server 2003 SP2 Standard'),
                  ('w2kassp4','Windows 2000 Server SP4'),
                  ('winxpsp2','Windows XP SP2'),
                  ('winxpsp3','Windows XP SP3'),
                  ('vistaee','Windows Vista SP0 Enterprise'),
                  ('vistaee-x64','Windows Vista SP0 Enterprise x64'),
                  ('vistaeesp1','Windows Vista SP1 Enterprise'),
                  ('vistaeesp1-x64','Windows Vista SP1 Enterprise x64'),
                  ('vistaeesp2','Windows Vista SP2 Enterprise'),
                  ('vistaeesp2-x64','Windows Vista SP2 Enterprise x64'),
                  ('ws08-x86','Windows Server 2008 Enterprise'),
                  ('ws08-x64','Windows Server 2008 Enterprise x64'),
                  ('ws08sp2-x86','Windows Server 2008 SP2 Enterprise'),
                  ('ws08sp2-x64','Windows Server 2008 SP2 Enterprise x64'),
                  ('ws08dc-x86','Windows Server 2008 Datacenter'),
                  ('ws08dc-x64','Windows Server 2008 Datacenter x64'),
                  ('ws08dcsp2-x86','Windows Server 2008 SP2 Datacenter'),
                  ('ws08dcsp2-x64','Windows Server 2008 SP2 Datacenter x64'),
                  ('ws08r2-x64','Windows Server 2008 R2 Enterprise x64'),
                  ('ws08r2sp1-x64','Windows Server 2008 R2 SP1 Enterprise x64'),
                  ('ws08r2dcsp1-x64','Windows Server 2008 R2 SP1 Datacenter x64'),
                  ('win7-x86','Windows 7'),
                  ('win7-x64','Windows 7 x64'),
                  ('win7sp1-x86','Windows 7 SP1'),
                  ('win7sp1-x64','Windows 7 SP1 x64'),
                  ('win8-x86','Windows 8'),
                  ('win8-x64','Windows 8 x64'),
                  ('win10-x86','Windows 10'),
                  ('win10-x64','Windows 10 x64'),
                  ('win81-x86','Windows 8.1'),
                  ('win81-x64','Windows 8.1 x64'),
                  ('ws12-x64','Windows Server 2012 x64'),
                  ('ws12core-x64','Windows Server2012 Core x64'),
                  ('ws12r2-x64','Windows Server 2012 R2 x64'),
                  ('ws12r2core-x64','Windows Server 2012 R2 Core x64')]

class Enum(object):
    pass

class PowerState(Enum):
    down = "down"
    up = "up"
    paused = "paused"
    suspended = "suspended"

class LifecycleOperation(Enum):
    start = "start"
    stop = "stop"
    reboot = "reboot"
    suspend = "suspend"
    resume = "resume"
    nonlivemigrate = "nonlivemigrate"
    livemigrate = "livemigrate"
    destroy = "destroy"
    snapshot = "snapshot"

class HypervisorType(Enum):
    xen = "xen"
    native = "native"
    kvm = "kvm"
    vmware = "vmware"
    hyperv = "hyperv"
    simulator = "simulator"
    other = "other"
    lxc = "lxc"

class InstallMethod(Enum):
    PV = "PV"
    Iso = "iso"
    IsoWithAnswerFile = "isowithanswerfile"

class IsoRepository(Enum):
    Windows = "windows"
    Linux = "linux"


class XenServerLicenseSKU(Enum):
    PerSocketEnterprise = "PerSocketEnterprise"
    PerUserEnterprise = "PerUserEnterprise"
    PerConcurrentUserEnterprise = "PerConcurrentUserEnterprise"
    XenDesktop = "XenDesktop"
    PerSocketStandard = "PerSocketStandard"
    XenDesktopPlusXDS = "XenDesktopXDS"
    XenDesktopPlusMPS = "XenDesktopMPS"
    Free = "Free"
    PerSocket = "PerSocket" # Clearwater version
    XSPlatinum = "Platinum"  #Tampa version
    XSEnterprise = "Enterprise"  #Tampa version
    XSAdvance = "Advance"    #Tampa version

class WindowsVersions(Enum):
    winXP = "5.1"
    ws2003AndR2 = "5.2"
    ws2008 = "6.0"
    win7 = "6.1"
    win8AndWS2012 = "6.2"
    
    
