#
# XenRT: Test harness for Xen and the XenServer product family
#
# File Cache
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import stat, os, os.path, urllib, time
import xenrt
from random import choice

__all__ = ["FileCache"]

class FileCache(object):
    """XenRT File Cache"""

    def __init__(self,type):
        # type is the particular subdir in the cache we're using

        # Get cache basedir, and construct new dir
        basedir = xenrt.TEC().lookup("CACHE_PATH",None)
        if not basedir:
            raise xenrt.XRTError("CACHE_PATH not specified!")

        self.path = "%s/%s" % (basedir,type)

        # Check it exists, if not create it
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def getURL(self,URL):
        """Get the file specified by the URL, returns a local path"""

        fn = os.path.basename(URL)
        filepath = "%s/%s" % (self.path,fn)

        # First see if it already exists
        if os.path.exists(filepath):
            return filepath

        flagpath = "%s/%s.fetching" % (self.path,fn)

        # See if there's a .fetching file
        if os.path.exists(flagpath):
            # Poll waiting for it to appear or for the downloading file to
            # disappear (with a timeout)
            xenrt.TEC().logverbose("Waiting for another process to fetch %s" % 
                                   (fn))
            deadline = xenrt.util.timenow() + 1800
            while not os.path.exists(filepath):
                if not os.path.exists(flagpath):
                    # Apparently it's downloaded or aborted
                    break
                if xenrt.util.timenow() > deadline:
                    xenrt.TEC().logverbose("Timed out waiting for %s, will "
                                           "fetch here..." % (fn))
                    break
                xenrt.sleep(60)

            if os.path.exists(filepath):
                return filepath

        # Download it ourselves...
        xenrt.TEC().logverbose("Fetching %s" % (fn))
        f = file(flagpath, "w")
        f.write("%u" % (xenrt.util.timenow()))
        f.close()
        os.chmod(flagpath,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)

        rand = ""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i in range(8):
            rand += choice(chars)

        tf = "%s.%s" % (filepath,rand)
        try:
            try:
                urllib.urlretrieve(URL, tf)
                os.link(tf,filepath)
                os.unlink(tf)
            except Exception, e:
                raise xenrt.XRTError("Exception fetching %s: %s" % (URL,e))
        finally:
            # Make it clear we aren't downloading it any more
            os.unlink(flagpath)

        return filepath

