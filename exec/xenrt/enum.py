#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["PowerState", "LifecycleOperation", "HypervisorType", "IsoRepository", "InstallMethod", "XenServerPaidFeatures", "XenServerLicenceSKU"]

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


class XenServerPaidFeatures(Enum):
    WorkloadBalancing = "WorkloadBalancing"
    ReadCaching = "ReadCaching"
    VirtualGPU = "VirtualGPU"
    Hotfixing = "Hotfixing"


class XenServerLicenceSKU(Enum):
    PerSocketEnterprise = "PerSocketEnterprise"
    PerUserEnterprise = "PerUserEnterprise"
    XenDesktopPlatinum = "XenDesktopPlatinum"
    PerSocketStandard = "PerSocketStandard"
    PerUserStandard = "PerUserStandard"
    Free = "Free"