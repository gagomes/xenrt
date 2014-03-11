#
# XenRT: Test harness for Xen and the XenServer product family
#
# Enumerations used for returning state information
#

import xenrt

__all__ = ["State"]

class Enum(object):
    pass

class State(Enum):
    down = 0
    up = 1
    paused = 2
    suspended = 3

