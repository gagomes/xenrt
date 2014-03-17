#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["PowerState", "HypervisorType", "IsoRepository", "InstallMethod"]

class Enum(object):
    pass

class PowerState(Enum):
    down = "down"
    up = "up"
    paused = "paused"
    suspended = "suspended"

class HypervisorType(Enum):
    xen = "xen"
    native = "native"
    kvm = "kvm"
    other = "other"

class InstallMethod(Enum):
    PV = "PV"
    Iso = "iso"
    IsoWithAnswerFile = "isowithanswerfile"

class IsoRepository(Enum):
    Windows = "windows"
    Linux = "linux"
