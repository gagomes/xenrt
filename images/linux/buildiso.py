#!/usr/bin/python

import sys
import re
import os.path
import glob
import shutil
import tempfile

def execcmd(cmd):
    print "Executing %s" % cmd
    ret = os.system(cmd)
    if ret != 0:
        raise Exception("%s exitted with error %d" % (cmd, ret))

def repackiso(inputiso, outputiso, isolinuxfile):
    try:
        td = tempfile.mkdtemp(prefix="isobuild", dir="/local/scratch/tmp")
        print "Created directory %s" % td
        os.mkdir("%s/mp" % td)
        execcmd("sudo mount -o loop,ro %s %s/mp" % (inputiso, td))
        print "Loop mounted ISO. Now copying files"
        shutil.copytree("%s/mp" % td, "%s/repack" % td, symlinks=True)
        print "Copied files, now overwriting isolinux.cfg"
        execcmd("sudo cp %s %s/repack/isolinux/isolinux.cfg" % (isolinuxfile, td))
        print "Overwritten isolinux.cfg, building ISO"
        execcmd("sudo genisoimage -J -R -o %s -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot -boot-load-size 4 -boot-info-table %s/repack" % (outputiso, td))
    finally:
        execcmd("sudo umount %s/mp" % td)
        execcmd("sudo rm -rf %s" % td)

if __name__ == "__main__":

    inputiso = sys.argv[1]
    outputiso = sys.argv[2]

    noCopy = False

    if len(sys.argv) > 3:
        if "nocopy" in sys.argv[3]:
            noCopy = True

    doTailor = False

    isoname = inputiso.split("/")[-1]

    m = re.match("(.*)[-_](x86-\d\d)\.iso", isoname)

    if m:
        doTailor = True
        distro = m.group(1)
        arch = m.group(2)

        # Now find the longest match

        path = os.path.dirname(__file__)
        files = glob.glob("%s/isolinux/*.%s" % (path, arch))

        match = ""
        fileToUse = None
        # Find the longest match
        for f in files:
            fn = os.path.basename(f).rsplit(".", 1)[0]

            if distro.startswith(fn) and len(fn) > len(match):
                match = fn
                fileToUse = f

        # If we can't find a file, don't tailor
        if not fileToUse:
            doTailor = False

    if doTailor:
        print "Tailoring ISO"
        repackiso(inputiso, outputiso, fileToUse)
    else:
        print "Not tailoring ISO"
        if not noCopy:
            shutil.copyfile(inputiso, outputiso)
