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
import os, os.path

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


class TC21473(xenrt.TestCase):
    """Verify that kernel ABI is not broken"""

    def test_kabi(self, module):
        
        # delete existing kabi modules
        rpms = self.host.execdom0('rpm -qa | grep test_kabi ; true').splitlines()
        for r in rpms:
            self.host.execdom0('rpm -e %s ; true' % r)
            
        uname_r = self.host.execdom0('uname -r').strip()
        
        expected_to_pass = False
        if module.startswith('./' + uname_r):
            expected_to_pass = True

        
        try:
            self.host.execdom0('cd /root/test-rpms; rpm -ivh %s ;' % module)
        except:
            raise xenrt.XRTFailure('Failed to install ' + 
                                   os.path.basename(module))
        
        modprobe_passed = True
        try:
            self.host.execdom0('modprobe test_kabi')
        except:
            modprobe_passed = False
        finally:
            self.host.execdom0('modprobe -r test_kabi ; true')
            
        if expected_to_pass:
            return modprobe_passed
        else:
            return not modprobe_passed

        
    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        if self.host.guests.has_key('ddk'):
            self.ddkVM = self.host.guests['ddk']
            self.ddkVM.password = 'xensource'
        else:
            # Import the DDK from xe-phase-2 of the build
            self.ddkVM = self.host.importDDK()
            self.ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
            self.ddkVM.start()

    def run(self, arglist):
        
        # Get the branch.
        branch = self.host.lookup('INPUTDIR').split('/')[-2]
        
        repo_url = 'http://hg.uk.xensource.com/closed/test-kabi.hg' 
        
        # clone test-kabi repo
        self.ddkVM.execguest('rm -rf /root/test-kabi.hg')
        ret = self.ddkVM.execguest('hg clone %s ' % repo_url, retval='code')
        if ret != 0:
            raise xenrt.XRTFailure('Failed to clone %s' %  repo_url)
        
        uname_r = self.host.execdom0('uname -r').strip()
        
        # Do we need to build test_kabi rpm?
        ret = self.ddkVM.execguest('[[ -d test-kabi.hg/test-rpms/%s/%s ]]' % (branch, uname_r), 
                                   retval='code')
        if ret != 0:
            ret = self.ddkVM.execguest('pushd test-kabi.hg; make PRODUCT_BRANCH=%s &> /root/build.log' % branch, retval='code')
            if ret != 0:
                self.ddkVM.execguest('cat /root/build.log')
                raise xenrt.XRTFailure('Failed to build test-kabi rpm')
        
        # Copy test-kabi rpms onto dom0
        ddkSFTP = self.ddkVM.sftpClient()

        workdir = xenrt.TEC().getWorkdir()
        ddkSFTP.copyTreeFrom('/root/test-kabi.hg/%s/test-rpms' % branch, 
                             os.path.join(workdir, "test-rpms"))
        ddkSFTP.close()
        hostSFTP = self.host.sftpClient()
        hostSFTP.copyTreeTo("%s/test-rpms" % (workdir), "/root/test-rpms")
        hostSFTP.close()
        
        test_modules = self.host.execdom0(r"cd /root/test-rpms; find  -name '*.rpm' -type f -print0").splitlines()
        
        test_ok = True
        for module in test_modules:
            if not self.test_kabi(module):
                test_ok = False
                xenrt.TEC().logverbose('%s is incompatible with %s' % 
                                       (os.path.basename(module), uname_r))

        if not test_ok:
            raise xenrt.XRTFailure('Kernel ABI test failed')
        
    def postRun(self):
        pass
