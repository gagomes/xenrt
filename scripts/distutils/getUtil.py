#!/usr/bin/python

# Script to retrieve downloadable utilities

# Known utilities
utils = {
         "psloglist.exe" : ("http://download.sysinternals.com/files/PSTools.zip", True),
         "soon.exe" : ("ftp://ftp.microsoft.com/reskit/win2000/soon.zip", True),
        }

import sys, urllib, os.path, zipfile, os

if len(sys.argv) != 3:
    sys.stderr.write("Usage: %s <utility name> <path to distutils>\n" % sys.argv[0])
    sys.exit(64)

util, distutils = sys.argv[1:3]

if not util in utils:
    sys.stderr.write("\nWARNING: Unable to download utility %s, please see %s/README for more information\n\n" % (util, distutils))
    sys.exit(0) # We exit 0 so as not to break the rest of the deployment

path, inZip = utils[util]

if inZip:
    # Download to a temporary directory, unzip and extract the util
    tempFile, _ = urllib.urlretrieve(path)
    with zipfile.ZipFile(tempFile, 'r') as zf:
        zf.extract(util, distutils)
    os.unlink(tempFile)
else:
    # Download straight to distutils
    urllib.urlretrieve(path, os.path.join(distutils, util))

