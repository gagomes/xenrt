#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["PowerState", "IsoRepository", "InstallMethod"]

class Enum(object):
    pass

class PowerState(Enum):
    down = "down"
    up = "up"
    paused = "paused"
    suspended = "suspended"

class InstallMethod(Enum):
    PV = "PV"
    Iso = "iso"
    IsoWithAnswerFile = "isowithanswerfile"

class IsoRepository(Enum):
    Windows = "windows"
    Linux = "linux"
