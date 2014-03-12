#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["PowerState"]

class Enum(object):
    pass

class PowerState(Enum):
    down = "down"
    up = "up"
    paused = "paused"
    suspended = "suspended"

