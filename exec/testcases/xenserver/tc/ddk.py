#
# XenRT: Test harness for Xen and the XenServer product family
#
# DDK tests
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, xenrt.lib.xenserver

class TC21003(xenrt.TestCase):
    """Verify the ddk examples build and can be installed"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Import the DDK from xe-phase-2 of the build
        self.ddkVM = self.host.importDDK()
        self.uninstallOnCleanup(self.ddkVM)
        self.ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        self.ddkVM.start()

    def run(self, arglist):
        # Test each example in turn to ensure it builds
        for example in ["userspace", "driver", "combined"]:
            try:
                self.ddkVM.execguest("cd ~/examples/%s && make build-iso" % (example))
            except:
                raise xenrt.XRTFailure("Unable to build DDK %s example" % (example))

        # Verify the combined ISO can be installed onto the host
        # (the userspace and driver ISOs are just the component parts so
        #  no real need to test them individually)
        ddkSFTP = self.ddkVM.sftpClient()
        workdir = xenrt.TEC().getWorkdir()
        ddkSFTP.copyFrom("/root/examples/combined/helloworld.iso", "%s/helloworld.iso" % (workdir))
        ddkSFTP.close()
        hostSFTP = self.host.sftpClient()
        hostSFTP.copyTo("%s/helloworld.iso" % (workdir), "/tmp/helloworld.iso")
        hostSFTP.close()

        self.host.execdom0("mount -o loop,ro /tmp/helloworld.iso /mnt")
        try:
            self.host.execdom0("cd /mnt && echo 'Y' | ./install.sh")
        except:
            raise xenrt.XRTFailure("Error installing DDK combined example")

        # Verify the module loads and unloads
        try:
            self.host.execdom0("modprobe helloworld")
            self.host.execdom0("modprobe -r helloworld")
        except:
            raise xenrt.XRTFailure("Unable to load/unload DDK example kernel module")

        # Verify the userspace content is there
        try:
            self.host.execdom0("ls /usr/share/doc/helloworld/EULA")
        except:
            raise xenrt.XRTFailure("Can't find DDK example userspace content")

    def postRun(self):
        try:
            self.host.execdom0("umount /mnt")
        except:
            pass

