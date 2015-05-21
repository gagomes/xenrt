#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer storage repository.
#
# Copyright (c) 2006-2015 Citrix Systems UK. All use and distribution of
# this copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt
from xenrt.lib.xenserver import LVMStorageRepository, ISCSIStorageRepository, HBAStorageRepository


# Symbols we want to export from the package.
__all__ = ["getStorageRepositoryClass"
    ]


def getStorageRepositoryClass(host, sruuid):
    """Find right SR class for existing SR"""

    srtype = host.genParamGet("sr", sruuid, "type")

    if srtype == "lvm":
        return LVMStorageRepository
    if srtype == "lvmoiscsi":
        return ISCSIStorageRepository
    if srtype == "lvmohba":
        return HBAStorageRepository

    raise xenrt.XRTError("%s SR type class getter is not implemented." % srtype)
