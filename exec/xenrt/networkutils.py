#
# XenRT: Test harness for Xen and the XenServer product family
#
# Network Utilities
#
# Copyright (c) 2012 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
import math, threading, re, time, string, subprocess, os, random, socket
import xenrt, xenrt.networkutils
from abc import ABCMeta, abstractmethod
from xenrt.lazylog import step, comment, log, warning

# Symbols we want to export from the package.
__all__ = ["Scapy", "TcpDump", "Telnet", "HackersChoiceFirewall6Ubuntu", "HackersChoiceFloodRouter26Ubuntu"]

class Telnet(object):
    """Telnet is a utility for network service reachability test."""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def run(self):
        try:
            s = socket.create_connection((self.host, self.port), 5)
            s.close()
            return True
        except:
            pass
        return False

class Scapy(object):
    """Scapy is a utility for creating and sending network packets. http://www.secdev.org/projects/scapy/"""
    
    def __init__(self, guest):
        self.guest = guest
        
        if guest.windows:
            raise xenrt.XRTError("Not supported on Windows guests")
    
    def install(self):
        """Installs Scapy onto the guest"""
        
        if self.guest.execguest("test -e /tmp/scapy", retval="code") != 0:
            self.guest.execguest("apt-get -y install unzip")
            self.guest.execguest("wget '%s/scapy.tgz' -O - | tar -zx -C /tmp" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
            self.guest.execguest("cd /tmp/scapy && unzip scapy2.2.zip")
            self.guest.execguest("cd /tmp/scapy/scapy-2.2.0 && python setup.py install")
    
    def _getSendIPPacketScript(self, iface, srcMac, dstMac, srcIP, dstIP):
        """Gets a scapy script for sending an empty ip packet"""
        
        return """#!/usr/bin/python
from scapy.all import *
ip=IP(src="%s",dst="%s")
e = Ether(src="%s",dst="%s")
sendp(e/ip, iface="%s")
""" % (srcIP, dstIP, srcMac, dstMac, iface)

    def _getSendArpScript(self, iface, opcode, hwSrc, pSrc, ethHwSrc, hwDst, pDst, ethHwDst):
        """Gets a scapy script for sending an arp"""
    
        return """#!/usr/bin/python
from scapy.all import *
a = ARP()
a.op="%s"
a.hwsrc="%s"
a.psrc="%s"
a.hwdst="%s"
a.pdst="%s"
e = Ether(src="%s",dst="%s")
sendp(e/a, iface="%s")
""" % (opcode, hwSrc, pSrc, hwDst, pDst, ethHwSrc, ethHwDst, iface)
        
    def _getSendNeighbourAdvertisementScript(self, iface, hwSrc, pSrc, hwDst, pDst, pReq, hwResp):
        
        return """#!/usr/bin/python
from scapy.all import *
e = (Ether(src='%s', dst='%s'))
ipv6 = IPv6(src='%s', dst='%s')
na = ICMPv6ND_NA(tgt='%s', R=0)
lla = ICMPv6NDOptDstLLAddr(lladdr='%s')

sendp(e/ipv6/na/lla, iface='%s')
""" % (hwSrc, hwDst, pSrc, pDst, pReq, hwResp, iface)
    
    
    def _getSendIPv6PacketScript(self, iface, hwSrc, hwDst, pSrc, pDst):
        return """#!/usr/bin/python
from scapy.all import *
e = (Ether(src='%s', dst='%s'))
ipv6 = IPv6(src='%s', dst='%s')

sendp(e/ipv6, iface='%s')
""" % (hwSrc, hwDst, pSrc, pDst, iface)
    
    
    def sendNeighbourAdvertisement(self, iface, hwSrc, pSrc, hwDst, pDst, pReq, hwResp):
        """ Sends an NDP Neighbour Advertisement packet
        
        @iface (string): the device id of the interface to send the packet e.g. eth0
        @hwSrc (string): the source mac address of the packet
        @pSrc (string): the source IPv6 address of the packet
        @hwDst (string): the destination mac address of the packet
        @pDst (string): the destination IPv6 address of the packet
        @pReq (string): the IPv6 address for which the mac address is required
        @hwResp (string): the mac address of the required IPv6 address"""
        
        self.executeScript(self._getSendNeighbourAdvertisementScript(iface, hwSrc, pSrc, hwDst, pDst, pReq, hwResp))
    
    def sendArp(self, iface, opcode, hwSrc, pSrc, ethHwSrc, hwDst, pDst, ethHwDst):
        """Sends an ARP with the specified parameters
        
        @iface (string): the device id of the interface to send the packet e.g. eth0
        @opcode (string): the opcode of the packet. Can be "is-at" or "who-has"
        @hwSrc (string): the source mac of the packet
        @pSrc (string): the source IP address of the packet
        @ethHwSrc (string): the source mac of the packet specified in ethernet part of packet
        @hwDst (string): the destination mac of the packet
        @pDst (string): the destination IP address of the packet
        @ethHwDst (string): the dest mac of the packet specified in ethernet part of packet"""
        
        self.executeScript(self._getSendArpScript(iface, opcode, hwSrc, pSrc, ethHwSrc, hwDst, pDst, ethHwDst))
        
    def sendEmptyIPPacket(self, iface, srcMac, dstMac, srcIP, dstIP):
        """Sends an empty IP packet
        
        @iface (string): the device id of the interface to send the packet e.g. eth0
        @srcMac (string): the source mac address of the packet
        @dstMac (string): the destination mac address of the packet
        @srcIP (string): the source IP address of the packet
        @dstIP (string): the destimation IP address of the packet"""
        
        self.executeScript(self._getSendIPPacketScript(iface, srcMac, dstMac, srcIP, dstIP))
    
    def sendEmptyIPv6Packet(self, iface, srcMac, dstMac, srcIP, dstIP):
        """Sends an empty IPv6 packet
        
        @iface (string): the device id of the interface to send the packet e.g. eth0
        @srcMac (string): the source mac address of the packet
        @dstMac (string): the destination mac address of the packet
        @srcIP (string): the source IPv6 address of the packet
        @dstIP (string): the destimation IPv6 address of the packet"""
        
        self.executeScript(self._getSendIPv6PacketScript(iface, srcMac, dstMac, srcIP, dstIP))

    def sendPacket(self, iface, b64):
        """Sends the specified packet (L2)
        
        @iface (string): the device id of the interface to send the packet e.g. eth0
        @b64 (string): base 64 encoded contents of the packet to send"""
        
        tmp = "/tmp/" + xenrt.randomGuestName()
        self.guest.execguest("echo '%s' | base64 -d > %s" % (b64, tmp))
        
        scr= """#!/usr/bin/python
from scapy.all import *
from scapy.utils import rdpcap
sendp(rdpcap('%s'), iface='%s')
""" % (tmp, iface)

        self.executeScript(scr)
    
    def executeScript(self, data):
        """Executes a script with the specified contents on the guest"""
        
        tmp = "/tmp/scapy_tmp"
        self.writeFile(tmp, data)
        self.guest.execguest("chmod +x " + tmp)
        xenrt.TEC().logverbose("Running script: " + data)
        self.guest.execguest(tmp)
    
    def writeFile(self, fullpath, data):
        """Writes a file with the specified contents to the specified path on the guest"""
        dir = xenrt.TEC().tempDir()
        tempFile = dir + "/tmp"
        f = open(tempFile, "w")
        f.write(data)
        f.close()
        sftp = self.guest.sftpClient()
        try:
            sftp.copyTo(tempFile, fullpath)
        finally:
            sftp.close()

class TcpDump(object):
    """TcpDump is a command-line network packet analyzer"""
    
    def __init__(self, guest):
        if guest.windows:
            raise xenrt.XRTError("TcpDump not supported on Windows")
        self.guest = guest
        self.res = ""
        self.pid = 0
        self.filename = "/tmp/tcpdump_tmp"
        self.guest.execguest("apt-get -y install tcpdump")

    def start(self, ifname):
        """Starts TcpDump on the guest"""
        if self.pid != 0:
            raise xenrt.XRTError("Started TcpDump without stopping it first.")
        self.res = ""
        self.pid = 0
        xenrt.sleep(5) # tcp dump has a slight delay to it.
        param = "tcpdump -i %s -net &> %s & echo $!" % (ifname, self.filename)
        self.guest.execguest("rm -f %s" % (self.filename))
        self.pid = self.guest.execguest(param).strip()
        
    def stop(self):
        """Stops TcpDump on the guest"""
        if self.pid == 0:
            raise xenrt.XRTError("Stopped TcpDump without starting it first.")
        
        xenrt.sleep(5) # tcp dump has a slight delay to it.
        self.guest.execguest("kill %s" % (self.pid))
        self.res = self.guest.execguest("cat %s" % (self.filename))
        self.pid = 0
    
    def verifyNothingReceived(self, ignoreTrafficFromMac=None, errorMessage=None):
        regex = "^\d{2,}[\.:]"
        if ignoreTrafficFromMac:
            self._checkFor(string.replace(self.res, ignoreTrafficFromMac, ""), regex, True, errorMessage)
        else:
            self._checkFor(self.res, regex, True, errorMessage)
    
    def verifyNothingReceivedFromMac(self, srcMac, errorMessage):
        self._checkFor(self.res, "^%s " % (srcMac), True, errorMessage)
    
    def verifyNdpNotReceived(self, srcMac, errorMessage):
        self._checkFor(self.res, "^%s .+ICMP6" % (srcMac), True, errorMessage)
    
    def verifyNdpReceived(self, srcMac, errorMessage):
        self._checkFor(self.res, "^%s .+ICMP6" % (srcMac), False, errorMessage)
    
    def verifyIPPacketNotReceived(self, srcMac, errorMessage):
        self._checkFor(self.res, "^%s.+IP" % (srcMac), True, errorMessage)
    
    def verifyIPPacketReceived(self, srcMac, errorMessage):
        self._checkFor(self.res, "^%s" % (srcMac), False, errorMessage)
    
    def verifyArpReplyReceived(self, ethSrcMac, requestedIP, isAt, errorMessage):
        self._checkArpReply(ethSrcMac, requestedIP, isAt, False, errorMessage)
    
    def verifyArpReplyNotReceived(self, ethSrcMac, requestedIP, isAt, errorMessage):
        self._checkArpReply(ethSrcMac, requestedIP, isAt, True, errorMessage)
    
    def verifyArpRequestReceived(self, whoHasIP, tellIP, errorMessage):
        self._checkArpRequest(whoHasIP, tellIP, False, errorMessage)
    
    def verifyArpRequestNotReceived(self, whoHasIP, tellIP, errorMessage):
        self._checkArpRequest(whoHasIP, tellIP, True, errorMessage)

    def _checkArpReply(self, ethSrcMac, requestedIP, isAt, raiseIfFound, errorMessage):
        self._checkFor(self.res, "^%s.+ARP.+%s is-at %s" % (ethSrcMac, requestedIP, isAt), raiseIfFound, errorMessage)
    
    def _checkArpRequest(self, whoHasIP, tellIP, raiseIfFound, errorMessage):
        self._checkFor(self.res, "ARP.+who-has %s tell %s" % (whoHasIP, tellIP), raiseIfFound, errorMessage)
    
    def _checkFor(self, res, checkFor, raiseIfFound, errorMessage):
        xenrt.TEC().logverbose("Checking TcpDump results for: " + checkFor)
        xenrt.TEC().logverbose("TcpDump results to check are:\n" + res)
        match = re.search(checkFor, res, re.MULTILINE)
        
        if match:
            if raiseIfFound:
                raise xenrt.XRTFailure(errorMessage, data='Error: Found "%s" in results' % (checkFor))
            else:
                xenrt.TEC().logverbose('Success: Found "%s" in results' % (checkFor))
        else:
            if raiseIfFound:
                xenrt.TEC().logverbose('Success: Didnt find "%s" in results' % (checkFor))
            else:
                raise xenrt.XRTFailure(errorMessage, data='Error: Didnt find "%s" in results' % (checkFor))

"""
Hacker's choice packages for running IPv6 network attacks
"""

class HackersChoiceUbuntuPackage(object):
    __metaclass__ = ABCMeta
    
    PACKAGE = "thc-ipv6-2.3.tgz"
    TARGET_ROOT = "/"
    TARGET_PATH = "/thc-ipv6-2.3"
    
    @abstractmethod
    def run(self, guest): pass
    
    @abstractmethod    
    def results(self): pass
    
    def install(self, guest): 
        if guest.windows:
            raise xenrt.XRTFailure("This is a linux only package")
       
        step("Getting package....")
 
        log(guest.execguest( "wget %s/%s -O %s%s" %(xenrt.TEC().lookup("TEST_TARBALL_BASE"), self.PACKAGE, self.TARGET_ROOT, self.PACKAGE)))
        log(guest.execguest( "tar -xvzf %s%s -C %s" %(self.TARGET_ROOT, self.PACKAGE, self.TARGET_ROOT)))
        
        step("Install build dependencies....")
        
        for dep in ["libpcap-dev", "libssl-dev"]:
            log(guest.execguest("apt-get -y install %s" % dep))
        
        step("Build the code")
        
        log(guest.execguest("cd %s && make" % self.TARGET_PATH))

class HackersChoiceFirewall6Ubuntu(HackersChoiceUbuntuPackage):

    TEST = "firewall6"
    __NUMBER_OF_TESTS = 38 #Tests run from 1 to 38
    
    def __init__(self, interface, targetipv6, tcpPort = 80):
        self.__interface = interface
        self.__targetipv6 = targetipv6
        self.__tcpPort = tcpPort
        self.__results = []
        
    def testCasesIds(self):
        return range(1, self.__NUMBER_OF_TESTS + 1)
    
    def run(self, guest):
        [self.runtestcase(guest, x) for x in self.testCasesIds()]
            
    def runtestcase(self, guest, testcaseId):
        self.__results = []

        step("Running firewall6 test case %d on guest %s" % (testcaseId, guest))
        
        self.__results.append(guest.execguest("%s/%s %s %s %d %d" % (self.TARGET_PATH, self.TEST, self.__interface, self.__targetipv6, self.__tcpPort, testcaseId)))
            
    def results(self):
        return self.__results
    

class HackersChoiceFloodRouter26Ubuntu(HackersChoiceUbuntuPackage):
    TEST = "flood_router26"
    
    def __init__(self, interface):
        self.__interface = interface
        self.__results = []
        
    def run(self, guest):
        log("%s started..." % self.TEST)
        self.__results.append(guest.execguest("nohup %s/%s %s >/dev/null 2>&1 &" % (self.TARGET_PATH, self.TEST, self.__interface)))
        log("Running.....")
        
    def results(self):
        return self.__results
        
    
