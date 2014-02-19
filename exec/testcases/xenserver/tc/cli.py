#
# XenRT: Test harness for Xen and the XenServer product family
#
# CLI testcases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, tarfile, os
import xenrt, xenrt.lib.xenserver

class TC8906(xenrt.TestCase):
    """Verify that attempting to upload a non existent patch generates a sane
       error message"""
    COMMAND = "patch-upload"
    FILENAME_PARAM = "file-name"
    DESC = "upload nonexistent patch"

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()
        allowed = False
        try:
            cli.execute(self.COMMAND, "%s=/tmp/doesntexist" %
                                      (self.FILENAME_PARAM))
            allowed = True
        except xenrt.XRTFailure, e:
            # We don't expect an internal error
            if re.search("internal error", e.data):
                raise xenrt.XRTFailure("Internal error reported when "
                                       "attempting to %s" % (self.DESC),
                                       data=e.data)
            # We expect to see a not found message
            if not re.search("does not exist", e.data):
                raise xenrt.XRTFailure("Unexpected error message when "
                                       "attempting to %s" % (self.DESC),
                                       data=e.data)

        if allowed:
            raise xenrt.XRTFailure("No error when trying to %s" % (self.DESC))

class TC8907(TC8906):
    """Verify that attempting to import a non existent VM generates a sane
       error message"""
    COMMAND = "vm-import"
    FILENAME_PARAM = "filename"
    DESC = "import nonexistent VM"

