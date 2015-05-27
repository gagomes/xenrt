#
# XenRT: Test harness for Xen and the XenServer product family
#
# Priviledged operations
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, sys, os, tempfile, traceback, stat, shutil, time
import xenrt, xenrt.util

# Symbols we want to export from the package.
__all__ = ["MountISO",
           "MountNFS",
           "mountWinISO",
           "nmap",
           "sudo"]
    
class Mount(object):
    def __init__(self, device, options=None, mtype=None, retry=True):
        self.mounted = 0
        exceptiondata = None
        try:
            self.mountpoint = tempfile.mkdtemp("", "xenrt", "/tmp")
            xenrt.TEC().logverbose("Created mountpoint %s" % (self.mountpoint))
            xenrt.TEC().gec.registerCallback(self)
            os.chmod(self.mountpoint,
                     stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
            for i in range(6):
                cmd = ["sudo", "mount"]
                if options:
                    cmd.append("-o%s" % (options))
                if mtype:
                    cmd.append("-t %s" % (mtype))
                cmd.append(device)
                cmd.append(self.mountpoint)
                try:
                    xenrt.util.command(string.join(cmd))
                    self.mounted = 1
                except xenrt.XRTFailure, e:
                    exceptiondata = e.data
                if self.mounted == 1:
                    break
                if not retry:
                    break
                # wait a bit then try again
                xenrt.sleep(120)
            
            if not self.mounted:    
                xenrt.TEC().logverbose("Error mounting %s at %s" %
                                       (device, self.mountpoint))
                raise xenrt.XRTError("Unable to mount %s" % (device),
                                     exceptiondata)
            xenrt.TEC().logverbose("Mounted %s at %s" %
                                   (device, self.mountpoint))
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise

    def getMount(self):
        return self.mountpoint

    def unmount(self):
        if self.mounted:
            xenrt.TEC().logverbose("Unmounting %s" % (self.mountpoint))
            tries = 3
            while tries > 0:
                if xenrt.util.command("sudo umount %s" % (self.mountpoint),
                                      retval="code") == 0:
                    break
                xenrt.TEC().logverbose("Error unmounting %s" %
                                       (self.mountpoint))
                tries = tries - 1
                if tries == 0:
                    raise xenrt.XRTError("Unable to umount %s" %
                                         (self.mountpoint))
                xenrt.sleep(15)
            self.mounted = 0

    def callback(self):
        if self.mounted:
            xenrt.TEC().logverbose("Unmounting %s" % (self.mountpoint))
            if xenrt.util.command("sudo umount %s" % (self.mountpoint),
                                    retval="code"):
                xenrt.TEC().logverbose("Error unmounting %s" %
                                       (self.mountpoint))
            else:
                self.mounted = 0
        if self.mountpoint:
            try:
                if os.path.exists(self.mountpoint):
                    xenrt.TEC().logverbose("Removing directory %s" %
                                           (self.mountpoint))
                    os.removedirs(self.mountpoint)
            except OSError:
                xenrt.TEC().logerror("Error removing directory %s" %
                                     (self.mountpoint))

class MountISO(Mount):
    """Mount an ISO so we can extract files."""
    def __init__(self, iso):
        Mount.__init__(self, iso, options="loop,ro")

class MountNFS(Mount):
    def __init__(self, nfs, retry=True, version="3"):
        Mount.__init__(self, nfs, options="nfsvers=%s" % version, mtype="nfs", retry=retry)

class MountSMB(Mount):
    def __init__(self, smb, domain, username, password, retry=True):
        Mount.__init__(self, "//%s" % smb.replace(":","/"), options="username=%s,password=%s,domain=%s" % (username, password, domain), mtype="cifs", retry=retry)

def mountWinISO(distro):
    """Mount a Windows ISO globally for the controller"""

    isolock = xenrt.resources.CentralResource()
    iso = "%s/%s.iso" % (xenrt.TEC().lookup("EXPORT_ISO_LOCAL_STATIC"), distro)
    mountpoint = "/winmedia/%s" % distro
    attempts = 0
    while True:
        try:
            isolock.acquire("WIN_ISO_%s" % distro)
            break
        except:
            xenrt.sleep(10)
            attempts += 1
            if attempts > 6:
                raise xenrt.XRTError("Couldn't get Windows ISO lock.")
    try:
        # Check the ISO isn't directly mounted and there's no loopback mount for that ISO
        mounts = xenrt.command("mount")
        loops = xenrt.command("sudo losetup -a")

        def loDeviceOfISO(iso, line):
            if iso in line:
                return line.split(':')[0]
            else:
                return None

        loopDevs = filter(lambda x : not x is None, map(lambda line: loDeviceOfISO(iso, line), loops.split('\n')))

        if not "%s on %s" % (iso, mountpoint) in mounts and (len(loopDevs) == 0 or (not "%s on %s" % (loopDevs[0], mountpoint))):
            sudo("mkdir -p %s" % mountpoint)
            sudo("mount -o loop %s %s" % (iso, mountpoint))
        return mountpoint
    finally:
        isolock.release()


def nmap(target, xmlfile, output):
    """Run nmap against the specified target."""
    # Make temporary output files which we can later copy, this avoids
    # the final copies being owned by root
    f, txmlfile = tempfile.mkstemp()
    os.close(f)
    os.chmod(txmlfile,
             stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    f, toutfile = tempfile.mkstemp()
    os.close(f)
    os.chmod(toutfile,
             stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    xenrt.util.command("sudo nmap -vvv -p1- -T4 -n -R -sV -oN %s -oX %s %s" %
                       (toutfile, txmlfile, target))
    shutil.copy(txmlfile, xmlfile)
    shutil.copy(toutfile, output)
    xenrt.util.command("sudo rm -f %s %s" % (txmlfile, toutfile))

def sudo(command):
    return xenrt.util.command("sudo %s" % (command))
    
