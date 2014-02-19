#
# XenRT: Custom test case (Python) file.
#
# To run this test case you will need to:
#
# 1. Create a sequence file.
# 2. Reference this class in the sequence file.
# 3. Submit a job using the sequence.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver

class TCRPP2(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        xenrt.TEC().logverbose("TCMyCustomTestCase::prepare called")
    
    def run(self, arglist=None):
        
        self.g1 = self.getGuest('VM1')
        self.g2 = self.getGuest('VM2')
        self.g3 = self.getGuest('VM3')
        
        self.g1.execguest("ping %s -c 5" % self.g2.getIP())
        self.g1.execguest("ping %s -c 5" % self.g3.getIP())
        xenrt.TEC().logverbose("VM installed")

        
        if self.g1.execguest("test -e /root/.ssh/id_rsa", retval="code") != 0:
                
            # generate new key pair on guest and use for SSH
            self.g1.execguest("rm -f /root/.ssh/id_rsa")
            self.g1.execguest("rm -f /root/.ssh/id_rsa.pub")
            self.g1.execguest("ssh-keygen -q -t rsa -N '' -f /root/.ssh/id_rsa")
                
            # copy guest public key to tempdir on controller
            tmp = xenrt.TEC().tempDir()
            sftp = self.g1.sftpClient()
            try:
                sftp.copyFrom("/root/.ssh/id_rsa.pub", tmp + "/id_rsa.pub")
            finally:
                sftp.close()
                
            # copy guest public key from tempdir on controller to vm
            sftp = self.g3.sftpClient()
            try:
                sftp.copyTo(tmp + "/id_rsa.pub", "/root/id_rsa.pub")
            finally:
                sftp.close()
                
            # add guest public key to host's autorized keys
            self.g3.execguest("mkdir /root/.ssh")
            self.g3.execguest("cat /root/id_rsa.pub >> /root/.ssh/authorized_keys")
            
        # do simple SSH command to dom0 from guest using the HIMN
        vip = self.g3.getIP()
        ret = self.g1.execguest("ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@%s ls /" % (vip), retval="code")
        
        xenrt.TEC().logverbose(ret)
        
        if not ret or not "root" in ret:
                raise xenrt.XRTFailure("Could not access VM3 via SSH")
