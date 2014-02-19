#
# XenRT: Test harness for Xen and the XenServer product family
#
# General testcases
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, shutil, threading
import xenrt

class TCLinkLatest(xenrt.TestCase):
    """Update -latest symlinks for build inputs."""

    # Assumes the path is reachable from the controller.
    # Assumes the running user can use sudo to manipulate the symlinks

    def run(self, arglist=[]):

        inputdir = xenrt.TEC().lookup("INPUTDIR", None)
        if not inputdir:
            raise xenrt.XRTError("No input directory specified")
        if not arglist or len(arglist) == 0:
            raise xenrt.XRTError("No -latest tag name given")
        tagname = arglist[0]

        # First check the directory looks like a suitable candidate for
        # symlinking
        base = xenrt.TEC().lookup("LATEST_SYMLINK_BASE", None)
        if base:
            if not inputdir.startswith(base):
                xenrt.TEC().skip("Input directory '%s' not suitable for a "
                                 "-latest symlink" % (inputdir))
                return
            
        # Must end in a build number for symlinking
        r = re.search("/(\d+)$", inputdir)
        if not r:
            xenrt.TEC().skip("Input directory does not end in a build number")
            return
        buildnumber = r.group(1)

        dirname = os.path.dirname(inputdir)
        linkfull = "%s/%s-latest" % (dirname, tagname)

        # If we already have a symlink and its named *-active-latest then
        # rename to *-latest, otherwise just remove
        if os.path.exists(linkfull):
            if tagname.endswith("-active"):
                prevfull = "%s/%s-latest" % (dirname, tagname[0:-7])
                if os.path.lexists(prevfull):
                    xenrt.sudo("rm -f %s" % (prevfull))
                xenrt.sudo("mv %s %s" % (linkfull, prevfull))
            else:
                xenrt.sudo("rm -f %s" % (linkfull))
        elif os.path.lexists(linkfull):
            xenrt.sudo("rm -f %s" % (linkfull))
            

        # Create the new link
        xenrt.sudo("ln -s %s %s" % (buildnumber, linkfull))
