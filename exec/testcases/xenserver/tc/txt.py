#
# XenRT: Test harness for Xen and the XenServer product family
#
# TXT testcases
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import random, string, time, os, os.path, hashlib, pprint
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, log


class TxtChangedInitrdBase(xenrt.TestCase):
    def _modifyInitrd(self, host):
        xenrt.TEC().logverbose("Rebuilding initrd for host %s..." % str(host))
        kernel = host.execdom0("uname -r").strip()
        imgFile = "initrd-" + kernel + ".img"
        xenrt.TEC().logverbose("md5sum=" + host.execdom0("md5sum /boot/%s" % imgFile))
        # Fingers crossed no reboot happens until the following 2 steps complete successfully or the machine will be trashed
        # There is away to avoid this in clearwater and newer, but we'll need to do this for Tampa too
        # For clearwater and greater just need to do "sh initrd*.xen.img.cmd -f" without removing the original image file
        xenrt.TEC().logverbose("Removing boot image %s and rebuilding" % imgFile)
        host.execdom0("cd /boot")
        host.execdom0("rm -rf %s" % imgFile)
        host.execdom0("""new-kernel-pkg.py --install --package=kernel-xen --mkinitrd "$@" %s""" % kernel)
        xenrt.TEC().logverbose("md5sum=" + host.execdom0("md5sum /boot/%s" % imgFile))
        xenrt.TEC().logverbose("initrd has been rebuilt")

    def _readInitrdPcr(self, session, hostRef):
        xenrt.TEC().logverbose("Reading PCR for host: %s; session %s" % (hostRef, pprint.pformat(session)))
        xenrt.txt.AttestationIdParser(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
        nonce = xenrt.txt.TpmQuoteParser.generateRandomNonce()
        quoteValue = xenrt.txt.TXTCommand().getQuote(hostRef, session, nonce)
        return xenrt.txt.TpmQuoteParser(quoteValue).getInitrdPcr()


class TCTxtChangedInitrd(TxtChangedInitrdBase):
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]
        preModInitrdValue = self._readInitrdPcr(session, hostRef)
        xenrt.TEC().logverbose("Pre-modification PCR19 value: %s" % preModInitrdValue)

        self.host.reboot()
        preModInitrdValueReboot = self._readInitrdPcr(session, hostRef)
        xenrt.TEC().logverbose("Pre-modification PCR19 value after reboot: %s" % preModInitrdValueReboot)

        #Check PCR 19 does not change on reboot
        if preModInitrdValue != preModInitrdValueReboot:
            raise xenrt.XRTFailure("Initrd PCR values were not the same, despite no changes, only a reboot")  

        self._modifyInitrd(self.host)
        self.host.reboot()

        #Check PCR 19 has changed now the boot image has been rewritten
        postModInitrdValue = self._readInitrdPcr(session, hostRef)
        xenrt.TEC().logverbose("Post-modification PCR19 value: %s" % postModInitrdValue)
        if preModInitrdValue == postModInitrdValue:
            raise xenrt.XRTFailure("Pre- and post initrd modification PCR values were the same")        

class TCTxtSuppPackQuoteVerify(xenrt.TestCase):
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]

        # Get the attestation identity values
        attId = xenrt.txt.AttestationIdParser(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
        
        #tpmCert, endorsmentKeyPub, aikTcpa, aikPub = self.getAttestationIdentity(session)
        nonce = xenrt.txt.TpmQuoteParser.generateRandomNonce()

        # Get the TPM Quote
        quoteValue = xenrt.txt.TXTCommand().getQuote(hostRef, session, nonce)
        quoteParser = xenrt.txt.TpmQuoteParser(quoteValue)
        
        # Verify the TPM quote
        self.runSubcase("_verifyTpmQuote", (quoteParser, attId.getAikPem(), nonce), "TPM quote is valid", "TPM quote is valid")
        self.runSubcase("_verifyXenPcr", (quoteParser), "Verify Xen PCR", "PCR 17")
        self.runSubcase("_verifyDomZeroPcr", (quoteParser), "Verify Dom0 PCR", "PCR 18")
        self.runSubcase("_verifyInitrdPcr", (quoteParser), "Verify initrd PCR", "PCR 19")
        self.runSubcase("_verifyLowEndPcrs", (quoteParser), "Verify low-end PCRs", "PCRs 0 through 7")
        
    def _verifyTpmQuote(self, quoteParser, aik, nonce):
        if not quoteParser.verifyQuote(aik, nonce):
            raise xenrt.XRTFailure("Quote value: %s, nonce: %s, AIK; %s was not valid" % (quoteParser.getCurrentQuoteValue(), nonce, aik))
   
    def _verifyXenPcr(self, quoteParser):
        pcrValue = quoteParser.getXenPcr()
        xenrt.TEC().logverbose("Checking PCR: %s" % pcrValue)
        self.__checkPcrString(pcrValue)
    
    def _verifyDomZeroPcr(self, quoteParser):
        pcrValue = quoteParser.getDomZeroPcr()
        xenrt.TEC().logverbose("Checking PCR: %s" % pcrValue)
        self.__checkPcrString(pcrValue)
    
    def _verifyInitrdPcr(self, quoteParser):
        pcrValue = quoteParser.getInitrdPcr()
        xenrt.TEC().logverbose("Checking PCR: %s" % pcrValue)
        self.__checkPcrString(pcrValue)
          
    def _verifyLowEndPcrs(self, quoteParser):
        for pcrIndex in range(8):
            pcrValue = quoteParser.getPcr(pcrIndex)
            xenrt.TEC().logverbose("Checking PCR %d - value found: %s" % (pcrIndex, pcrValue))
            self.__checkPcrString(pcrValue)
            
    def __checkPcrString(self, pcrValue):
        if(pcrValue.count("f") == len(pcrValue)):
            raise xenrt.XRTFailure("PCR value contained all F's")
        if(pcrValue.count("0") == len(pcrValue)):
            raise xenrt.XRTFailure("PCR value contained all 0's")

class TCTxtHostCanReboot(xenrt.TestCase):
    """
    Check the host can reboot
    """
    def run(self, arglist):
        self.host = self.getDefaultHost()
        xenrt.TEC().logverbose("Calling self.host.reboot()")
        self.host.reboot()
        xenrt.TEC().logverbose("self.host.reboot() completed")

class TCTxtTpmCreatesOutput(xenrt.TestCase):
    """
    Check the host can read TPM
    Note: requires the supp pack for measured boot to be installed
    """

    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]
        
        self.runSubcase("_runAttestationCommand", (hostRef, session), "Attestation API call", "Attestation API call")
        self.runSubcase("_runQuoteCommand", (hostRef, session), "Quote API call", "Quote API call")
    
    def _runAttestationCommand(self, hostRef, session):
        self.__verifyOutput(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
        
    def _runQuoteCommand(self, hostRef, session):
        self.__verifyOutput(xenrt.txt.TXTCommand().getQuote(hostRef, session, "asdfghjklqwertyuiop"))

    def __verifyOutput(self, pluginOutput):
        if pluginOutput == None or len(pluginOutput) < 1:
            raise xenrt.XRTFailure("Output from the command was empty")
        if("Exception" in pluginOutput):
            raise xenrt.XRTFailure("Exception text found in return value")


class TCTxtSuppPackInstall(xenrt.TestCase):
    def run(self, arglist):
        self.host = self.getDefaultHost()
        xenrt.txt.TXTSuppPackInstaller().install([self.host])


class TCTxtSuppPackInstallOld(xenrt.TestCase):

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        # Import the DDK from xe-phase-2 of the build
        self.ddkVM = self.host.importDDK()
        self.ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        self.ddkVM.start()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host.getMyHostUUID()).strip()

    def run(self, arglist):
        self.ddkVM.execguest('hg clone http://hg.uk.xensource.com/carbon/trunk-appliances/tboot.hg tboot.hg')
        self.ddkVM.execguest('make -C tboot.hg > install.log 2>&1')

        self.workdir = "/root/tboot.hg/output"

        # Create a tmp directory on the controller that will be automatically cleaned up
        ctrlTmpDir = xenrt.TEC().tempDir()

        sourcePath = self.ddkVM.execguest("find /root/tboot.hg/output/ -iname xenserver-measured-boot.iso -type f").strip()
        packName = os.path.basename(sourcePath)

        # copy to tempdir on controller
        sftp = self.ddkVM.sftpClient()
        try:
            sftp.copyFrom(sourcePath, os.path.join(ctrlTmpDir, packName))
        finally:
            sftp.close()

        # copy from tempdir on controller to host
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(os.path.join(ctrlTmpDir, packName), os.path.join('/tmp', packName))
        finally:
            sftp.close()

        self.host.execdom0("xe-install-supplemental-pack /tmp/%s" % packName)

        self.host.execdom0("sync")
        xenrt.TEC().logverbose("Calling self.host.reboot()")
        self.host.reboot()
        xenrt.TEC().logverbose("self.host.reboot() completed")

    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
        # Fetch the make logfile if available
        sftp = self.ddkVM.sftpClient()
        sftp.copyFrom('install.log', '%s/txt-make-log' % (xenrt.TEC().getLogdir()))

class TCTxtSuppPackBasicTest(xenrt.TestCase):

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        # Import the DDK from xe-phase-2 of the build
        self.ddkVM = self.host.importDDK()
        self.ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        self.ddkVM.start()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host.getMyHostUUID()).strip()

    def run(self, arglist):
        # Perform the platform_check function
        self.ddkVM.execguest('hg clone http://hg.uk.xensource.com/carbon/trunk-appliances/tboot.hg tboot.hg')
        self.ddkVM.execguest('make -C tboot.hg/XenTPMClient > client_build.log 2>&1')

        self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMGetAik.py %s root %s >> txt_test.log 2>&1" % (self.host.getIP(), self.host.password))
        self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMChallange.py %s root %s >> txt_test.log 2>&1" % (self.host.getIP(), self.host.password))
        self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMQuote.py %s root %s >> txt_test.log 2>&1" % (self.host.getIP(), self.host.password))

    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
        # Fetch the make logfile if available
        sftp = self.ddkVM.sftpClient()
        sftp.copyFrom('client_build.log', '%s/client_build-log' % (xenrt.TEC().getLogdir()))
        sftp.copyFrom('tboot.hg/XenTPMClient/txt_test.log', '%s/txt-test-log' % (xenrt.TEC().getLogdir()))

class TCTxtSuppPackStress(xenrt.TestCase):

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        # Import the DDK from xe-phase-2 of the build
        self.ddkVM = self.host.importDDK()
        self.ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        self.ddkVM.start()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host.getMyHostUUID()).strip()

    def run(self, arglist):
        # Perform the platform_check function
        self.ddkVM.execguest('hg clone http://hg.uk.xensource.com/carbon/trunk-appliances/tboot.hg tboot.hg')
        self.ddkVM.execguest('make -C tboot.hg/XenTPMClient > client_build.log 2>&1')

        for x in range(1, 100):
            self.ddkVM.execguest("cd tboot.hg/XenTPMClient && echo pass %s >> txt_stress.log 2>&1" % (x))
            self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMGetAik.py %s root %s >> txt_stress.log 2>&1" % (self.host.getIP(), self.host.password))
            self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMChallange.py %s root %s >> txt_stress.log 2>&1" % (self.host.getIP(), self.host.password))
            self.ddkVM.execguest("cd tboot.hg/XenTPMClient && python xenTPMQuote.py %s root %s >> txt_stress.log 2>&1" % (self.host.getIP(), self.host.password))

    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
        # Fetch the make logfile if available
        sftp = self.ddkVM.sftpClient()
        sftp.copyFrom('client_build.log', '%s/client_build-log' % (xenrt.TEC().getLogdir()))
        sftp.copyFrom('tboot.hg/XenTPMClient/txt_stress.log', '%s/txt-stress-log' % (xenrt.TEC().getLogdir()))
        
        
"""Pool Tests"""
class TCPoolWideSuppPackInstaller(xenrt.TestCase):
    def run(self, arglist):
        xenrt.txt.TXTSuppPackInstaller().install(self.getAllHosts())
            
class TCTxtPoolIdsAreUnique(xenrt.TestCase):
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostA = session.xenapi.host.get_all()[0]
        hostB = session.xenapi.host.get_all()[1]
        
        pluginOutputHostA = xenrt.txt.TXTCommand().getAttestationId(hostA, session)
        pluginOutputHostB = xenrt.txt.TXTCommand().getAttestationId(hostB, session)
        
        xenrt.TEC().logverbose("Att Id host A: %s" % pluginOutputHostA)
        xenrt.TEC().logverbose("Att Id host B: %s" % pluginOutputHostB)
        
        self.runSubcase("_checkEndorsementKey", (pluginOutputHostA, pluginOutputHostB), "Endorsement key", "Endorsement key")
        self.runSubcase("_checkTCPA", (pluginOutputHostA, pluginOutputHostB), "TCPA key", "TCPA key")
        self.runSubcase("_checkAIK", (pluginOutputHostA, pluginOutputHostB), "AIK PEM", "AIK PEM")
        
    def _checkEndorsementKey(self, tpmOutputA, tpmOutputB):
        keyA = xenrt.txt.AttestationIdParser(tpmOutputA).getEndorsementKey()
        keyB = xenrt.txt.AttestationIdParser(tpmOutputB).getEndorsementKey()
        
        xenrt.TEC().logverbose("Endorsement key Host A: %s" % keyA)
        xenrt.TEC().logverbose("Endorsement key  Host B: %s" % keyB)
        
        if(keyA == None or len(keyA) < 1):
            raise xenrt.XRTFailure("Key was empty")    
        
        if(keyB == None or len(keyB) < 1):
            raise xenrt.XRTFailure("Key was empty")  
        
        if(keyA == keyB):
            raise xenrt.XRTFailure("Endorsement keys were equal")  

    def _checkTCPA(self, tpmOutputA, tpmOutputB):
        tcpaKeyA = xenrt.txt.AttestationIdParser(tpmOutputA).getTcpaKey()
        tcpaKeyB = xenrt.txt.AttestationIdParser(tpmOutputB).getTcpaKey()
        
        xenrt.TEC().logverbose("TCPA key Host A: %s" % tcpaKeyA)
        xenrt.TEC().logverbose("TCPA key  Host B: %s" % tcpaKeyB)
        
        if(tcpaKeyA == None or len(tcpaKeyA) < 1):
            raise xenrt.XRTFailure("Key was empty")    
        
        if(tcpaKeyB == None or len(tcpaKeyB) < 1):
            raise xenrt.XRTFailure("Key was empty")  
        
        if(tcpaKeyA == tcpaKeyB):
            raise xenrt.XRTFailure("TCPA keys were equal")        
        
    def _checkAIK(self, tpmOutputA, tpmOutputB):
        aikPemA = xenrt.txt.AttestationIdParser(tpmOutputA).getAikPem()
        aikPemB = xenrt.txt.AttestationIdParser(tpmOutputB).getAikPem()
        
        xenrt.TEC().logverbose("AIK PEM Host A: %s" % aikPemA)
        xenrt.TEC().logverbose("AIK PEM Host B: %s" % aikPemB)
            
        if(aikPemA == None or len(aikPemA) < 1):
            raise xenrt.XRTFailure("Key was empty")    
        
        if(aikPemB == None or len(aikPemB) < 1):
            raise xenrt.XRTFailure("Key was empty")  
        
        if(aikPemA == aikPemB):
            raise xenrt.XRTFailure("AIK PEMs were equal")
        
class TCTxtPoolChangedInitrd(TxtChangedInitrdBase):
    def run(self, arglist):
        #self.host = self.getDefaultHost()
        
        hostA = self.getHost("RESOURCE_HOST_0")
        hostB = self.getHost("RESOURCE_HOST_1")
        session = hostA.getAPISession()
        
        #Read both host's PCR19 values
        preTamperPcrA = self.__getPcr(session, hostA)
        preTamperPcrB = self.__getPcr(session, hostB)
        
        # Modify host A
        self._modifyInitrd(hostA)
        hostA.reboot()
        
        #Read both host's PCR19 values after tampering the initrd
        postTamperPcrA = self.__getPcr(session, hostA) 
        postTamperPcrB = self.__getPcr(session, hostB)

        #Check only hostA's PCR has changed
        if preTamperPcrA == postTamperPcrA:
            raise xenrt.XRTFailure("Tampered-with host's PCR value should have changed but didn't") 
        if preTamperPcrB != postTamperPcrB:
            raise xenrt.XRTFailure("Non-tampered-with host's PCR value should not have changed")
    
    def __getPcr(self, session, host):
        hostRef = session.xenapi.host.get_by_uuid(host.getMyHostUUID())
        xenrt.TEC().logverbose("Host %s; Session: %s" % (hostRef, str(session)))
        pcrValue = self._readInitrdPcr(session, hostRef)
        xenrt.TEC().logverbose("PCR19 Host %s: %s" % (host.getName(), pcrValue))
        return pcrValue
           

"""Soak Test"""
class TCTxtRepeatedQuoteCall(xenrt.TestCase):
    __SECS_IN_MIN = 60
    __WAIT_TIME_MINS = 2
    __MINS_IN_THREE_DAYS = 60 * 24 * 3
    
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]
        
        loopMax = int(self.__MINS_IN_THREE_DAYS / self.__WAIT_TIME_MINS)
        xenrt.TEC().logverbose("Attempting %d iterations, sleeping for %d mins per iteration...." % (loopMax, self.__WAIT_TIME_MINS))
        xenrt.txt.TXTCommand().getAttestationId(hostRef, session)
        
        currentN = 0
        nonce=None
        quote=None
        
        try:
            for n in range(loopMax):
                currentN = n
                nonce = xenrt.txt.TpmQuoteParser.generateRandomNonce()
                quote = xenrt.txt.TXTCommand().getQuote(hostRef, session, nonce)
                
                if nonce == None or len(nonce) < 1:
                    raise xenrt.XRTFailure("Nonce was empty on iteration %d", n)
                
                if quote == None or len(quote) < 1:
                    raise xenrt.XRTFailure("Quote was empty on iteration %d", n)
                
                time.sleep(self.__WAIT_TIME_MINS * self.__SECS_IN_MIN)
        except:
            xenrt.TEC().logverbose("Nonce: %s" % nonce)
            xenrt.TEC().logverbose("Quote: %s" % quote)
            raise xenrt.XRTFailure("Failure occurred whilst calling the quote api repeatedly on iteration %d" % currentN)
            
            
class TCTxtRepeatAttIdAndReboot(xenrt.TestCase):
    __DURATION = 60 * 60 * 18
    
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]
        
        end = time.time() + self.__DURATION
        log("This test will end in %s secs" % str(end))
        
        try:
            while time.time() < end:
                step("Fetch the attestation id....")
                log(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
                step("Reboot host....")
                self.host.reboot()
        except:
            raise xenrt.XRTFailure("Failure occurred whilst calling the attestation id api repeatedly")
            
class TCTxtSuppPackChallenge(xenrt.TestCase):
    __NUM_OF_ATTEMPTS = 3
    __SECRET_SIZE = 30
    
    def run(self, arglist):
        hostRef = self.getDefaultHost().getHandle()
        session = self.getDefaultHost().getAPISession()

        attParser = xenrt.txt.AttestationIdParser(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
        
        challengeParser = xenrt.txt.TpmChallengeParser(attParser.getTcpaKey(), attParser.getEndorsementKey())
        
        for x in range(self.__NUM_OF_ATTEMPTS):
            
            secret = "".join([random.choice(string.ascii_letters + string.digits) for n in xrange(self.__SECRET_SIZE)])
            xenrt.TEC().logverbose("Attempt: %d, secret: %s" % (x, secret))
            
            challenge = challengeParser.createChallenge(session, secret)
            decryptedAnswer = xenrt.txt.TXTCommand().getChallenge(hostRef, session, challenge)
                
            if decryptedAnswer != secret:
                raise xenrt.XRTFailure("The challenge was not successfully decrypted")   


class TCTxtSuppPackAssetTagVerify(xenrt.TestCase):
    def run(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        hostRef = session.xenapi.host.get_all()[0]

        # Create a random asset tag
        lst = [random.choice(string.ascii_letters + string.digits) for n in xrange(20)]
        tag = "".join(lst)
        tag_sha1 = self._getSHA1(tag)

        # Set the asset tag
        xenrt.TEC().logverbose("Set the Asset Tag")
        xenrt.TEC().logverbose("Setting Asset Tag to: %s" % str(tag_sha1).encode('hex'))
        assetTagPcrValue = self._readAssetTagPcr(session, hostRef)
        xenrt.TEC().logverbose("Pre-modification PCR22 value: %s" % assetTagPcrValue)
        quoteValue = xenrt.txt.TXTCommand().setAssetTag(hostRef, session, tag_sha1)

        # Restart the XenServer host
        self.host.reboot()

        # Verify PCR22
        # To build up what PCR-22 should be do the following:
        # - take a sha1 hash of the original tag (this was what was set in nvram location #40000010)
        # - take the original pcr-22 value (20 bytes of 0's) and prepend the value of nvram location #40000010.
        # - Finally take another sha1 hash of the entire 40 bytes
        # - This should match the value that is in pcr-22
        zeroPCR = bytearray([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0])
        newGeoTaglen = len(zeroPCR) + len(tag_sha1)
        newGeoTag = bytearray(([0]*newGeoTaglen))
        newGeoTag[0 : len(zeroPCR)] = zeroPCR
        newGeoTag[len(zeroPCR): len(zeroPCR) + len(tag_sha1)] = tag_sha1
        newGeoTag_sha1 = self._getSHA1(str(newGeoTag[0:len(zeroPCR) + len(tag_sha1)]))
        xenrt.TEC().logverbose("PCR22 value should be: %s" % str(newGeoTag_sha1).encode('hex'))
        assetTagPcrValue = self._readAssetTagPcr(session, hostRef)
        xenrt.TEC().logverbose("PCR22 value is: %s" % assetTagPcrValue)
        if str(newGeoTag_sha1).encode('hex') != assetTagPcrValue:
            raise xenrt.XRTFailure("Asset Tag PCR value was not correct!")  

        # Clear the asset tag
        xenrt.TEC().logverbose("Clear the Asset Tag")
        assetTagPcrValue = self._readAssetTagPcr(session, hostRef)
        xenrt.TEC().logverbose("Pre-modification PCR22 value: %s" % assetTagPcrValue)
        quoteValue = xenrt.txt.TXTCommand().clearAssetTag(hostRef, session)

        # Restart the XenServer host
        self.host.reboot()

        # Verify PCR22 is 0000000000000000000000000000000000000000
        xenrt.TEC().logverbose("PCR22 value should be: %s" % str(zeroPCR).encode('hex'))
        assetTagPcrValue = self._readAssetTagPcr(session, hostRef)
        xenrt.TEC().logverbose("PCR22 value is: %s" % assetTagPcrValue)
        if str(zeroPCR).encode('hex') != assetTagPcrValue:
            raise xenrt.XRTFailure("Asset Tag PCR value was not 20 bytes of 0 after being clear!")  

    def _readAssetTagPcr(self, session, hostRef):
        xenrt.TEC().logverbose("Reading PCR22 for host: %s; session %s" % (hostRef, pprint.pformat(session)))
        xenrt.txt.AttestationIdParser(xenrt.txt.TXTCommand().getAttestationId(hostRef, session))
        nonce = xenrt.txt.TpmQuoteParser.generateRandomNonce()
        quoteValue = xenrt.txt.TXTCommand().getQuote(hostRef, session, nonce)
        return xenrt.txt.TpmQuoteParser(quoteValue).getAssetTagPcr()

    def _getSHA1(self, data):
        sha1 = hashlib.sha1()
        sha1.update(data)
        return sha1.digest()
