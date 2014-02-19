#
# XenRT: Test harness for Xen and the XenServer product family
#
# Host network reset testcases
#
# Copyright (c) 2011 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#


import socket, re, string, time, traceback, sys, random, copy, os, subprocess
import urllib2
import xenrt, xenrt.lib.xenserver

def addExternalNetwork(host,vlanId):

    nic = host.getDefaultInterface()
    extuuid = host.createNetwork()
    vlanPif = host.createVLAN(vlanId, extuuid, nic)
    return extuuid,vlanPif

def addInternalNetwork(host):

    intuuid = host.createNetwork()
    return intuuid

def addBondedNetwork(host,bondMode,numberOfNics=2):

    assumedids = host.listSecondaryNICs("NSEC")
    if len(assumedids) < 2:
        raise xenrt.XRTError("Couldn't find 2 NSEC NICs")

    nics = map(host.getSecondaryNIC, assumedids[:numberOfNics])
    pifs = []
    for n in nics:
        pifs.append(host.parseListForUUID("pif-list","device",n,"host-uuid=%s" % (host.getMyHostUUID())))

    bond = host.createBond(pifs,dhcp=True,mode=bondMode)

def addTunnel(host):

    args = []
    cli = host.getCLIInstance()
    networkuuid = addInternalNetwork(host)
    pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
    args.append("network-uuid=%s" % (networkuuid))
    args.append("pif-uuid=%s" % (pifManagement))
    tunnel = cli.execute("tunnel-create", string.join(args)).strip()

class _NetworkReset(xenrt.TestCase):

    HOSTLIST = ["DEFAULT"]
    NETWORKHOSTNAME = None
    AFFECTEDHOSTNAMES = ["DEFAULT"]
#    VMS = False
    MANAGEMENTMODIFY = None
    OLDIP = None

    def prepare(self, arglist):

        self.hostPifsSettings = {}
        self.hostPifsList = {}
        self.hostVifsSettings = {}
        self.hostVifsList = {}
        self.hostNetworkSettings = {}
        self.hostNetworkList = {}
        self.hostVlanSettings = {}
        self.hostVlanList = {}
        self.hostTunnelSettings = {}
        self.hostTunnelList = {}
        self.hostBondSettings = {}
        self.hostBondList = {}
        self.hostsObject = {}
        self.hostNewNetworkSettings = {} 
        self.hostNewNetworkList = {}
        self.hostPifsListAfterChange = {}   
        self.hostManagementSettings = {}
 
        if self.HOSTLIST[0] <> "DEFAULT":
            self.pool = self.getDefaultPool() 

        for hostName in self.HOSTLIST:
            self.hostsObject[hostName] = self.getHostObject(hostName)
            host = self.hostsObject[hostName]
            self.hostPifsSettings[hostName],self.hostPifsList[hostName] = self.getPifsSettings(host)
            self.hostManagementSettings[hostName] = self.getManagementSettings(host) 
            self.hostVifsSettings[hostName],self.hostVifsList[hostName] = self.getSettings(host,"vif")
            self.hostNetworkSettings[hostName],self.hostNetworkList[hostName] = self.getSettings(host,"network")
            self.hostVlanSettings[hostName],self.hostVlanList[hostName] = self.getSettings(host,"vlan")
            self.hostTunnelSettings[hostName],self.hostTunnelList[hostName] = self.getSettings(host,"tunnel")
            self.hostBondSettings[hostName],self.hostBondList[hostName] = self.getSettings(host,"bond")
            self.hostNewNetworkList[hostName] = self.hostNetworkList[hostName]
 
    def getHostObject(self,hostName):
 
        if hostName == "DEFAULT":
            host = self.getDefaultHost()
        else:
            pool = self.getDefaultPool()
            if hostName == "MASTER":
                host = pool.master
            elif hostName == "SLAVE1":
                host = pool.getSlaves()[0]
            elif hostName == "SLAVE2":
                host = pool.getSlaves()[1]
     
        return host

    def getManagementSettings(self,host):

        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        param = {}
        param["IP"] = host.genParamGet("pif", pifManagement, "IP")
        param["Netmask"] = host.genParamGet("pif", pifManagement, "netmask")
        param["Device"] = host.genParamGet("pif", pifManagement, "device")
        param["gateway"] = self.getGateway(host)
        return param
 
    def getPifsSettings(self,host):

        settings = {}
        pifsList = []

        cli = host.getCLIInstance()

        pifsList = host.minimalList("pif-list",args="host-uuid=%s" % (host.getMyHostUUID())) 
        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
    
        for pif in pifsList:    
            if pif == pifManagement:
                settings["Management"] = cli.execute("pif-param-list","uuid=%s" % (pif), strip=True)
            else:
                settings[pif] = cli.execute("pif-param-list","uuid=%s" % (pif), strip=True)

        return settings,pifsList

    def getSettings(self,host,string):

        settings = {}
        list = []

        cli = host.getCLIInstance()

        list = host.minimalList("%s-list" % string)

        for elmnt in list:
            settings[elmnt] = cli.execute("%s-param-list" % (string),"uuid=%s" % (elmnt), strip=True)

        return settings,list

    def run(self, arglist):

        if self.NETWORKHOSTNAME:
            hostName = self.NETWORKHOSTNAME
            if self.runSubcase("changeNetworkSettings", (self.hostsObject[hostName]), "ChangeNetwork", "Host") != \
                    xenrt.RESULT_PASS:
                return
            time.sleep(60)

            if self.NETWORKHOSTNAME == "MASTER":
                for hostName in self.HOSTLIST:
                    if hostName <> "MASTER":
                        host = self.hostsObject[hostName]
                        host.reboot()

            for hostName in self.HOSTLIST:
                host = self.hostsObject[hostName]         
                self.hostNewNetworkSettings[hostName],self.hostNewNetworkList[hostName] = self.getSettings(host,"network")
                self.hostVlanSettings[hostName],self.hostVlanList[hostName] = self.getSettings(host,"vlan")
                self.hostTunnelSettings[hostName],self.hostTunnelList[hostName] = self.getSettings(host,"tunnel")
                self.hostBondSettings[hostName],self.hostBondList[hostName] = self.getSettings(host,"bond")
                temp,self.hostPifsListAfterChange[hostName] = self.getPifsSettings(host)


        if self.MANAGEMENTMODIFY:
            if self.runSubcase("modifyManagement",(self.hostsObject[self.MANAGEMENTMODIFY]),"ModifyManagement","Pif") != xenrt.RESULT_PASS:
                return

        flag = False
        for hostName in self.AFFECTEDHOSTNAMES:
            if flag: 
                self.NETWORKHOSTNAME = hostName
            if self.runSubcase("networkReset",(self.hostsObject[hostName],hostName),"Reset","Host") != \
                    xenrt.RESULT_PASS:
                return
            time.sleep(60)
            if self.runSubcase("verifyPostResetSettings",(hostName),"VerifySettings","Host") != \
                    xenrt.RESULT_PASS:
                return  
            flag = True

    def networkReset(self,host,hostName):

        if self.OLDIP:
            host.networkReset(setIP=self.OLDIP)
        else:
            host.networkReset()

        self.checkManagementSettings(host,self.hostManagementSettings[hostName])

    def installVMs(self):

        for hostName in self.HOSTLIST:
            lg = self.hostsObject[hostName].createGenericLinuxGuest()
            self.uninstallOnCleanup(lg)
            wg = self.hostsObject[hostName].createGenericWindowsGuest()
            self.uninstallOnCleanup(wg)

    def getGateway(self,host):

        data = host.execdom0("/sbin/ip route | awk '/default/ { print $3 }'") 
        gateway = data.splitlines()[0]
        return gateway

    def modifyManagement(self,host):

        args = []
        cli = host.getCLIInstance()
     
        #Giving same IP address but changing the mode
        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        self.OLDIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]
        gateway = self.getGateway(host)
        ip = self.OLDIP
        netmask = host.minimalList("pif-param-get",args="uuid=%s param-name=netmask" % (pifManagement))[0]
 
        args.append("uuid=%s" % pifManagement)
        args.append("IP=%s" % ip)
        args.append("netmask=%s" % netmask)
        args.append("mode=static")
        args.append("gateway=%s" % gateway)
        command = "xe pif-reconfigure-ip %s" % (string.join(args).strip())
        try:
            #execdom0 is used instead of cli because cli.execute was taking forever.
            host.execdom0("nohup %s > f.out 2> f.err < /dev/null &" % command,timeout=120)
        except:
            raise xenrt.XRTFailure("Failed while trying to change the Primary Management interface")

        #time to get things settled
        time.sleep(120)

        host.setIP(ip) 
 
    def verifyPostResetSettings(self,hostName):

        currNetList = []
        currVlanList = []
        currBondList = []
        currTunnelList = []
        currVifsList = []
        currPifsList = []
        temp = {}
        currNetSett = {}
        currVifSett = {}
        currVlanSett = {}
        currTunnelSett = {}
        currBondSett = {}

        host = self.getHostObject(hostName)
        currVlanSett,currVlanList = self.getSettings(host,"vlan")
        currVifSett,currVifsList = self.getSettings(host,"vif")
        currTunnelSett,currTunnelList = self.getSettings(host,"tunnel")
        currBondSett,currBondList = self.getSettings(host,"bond")
        temp,currPifsList = self.getPifsSettings(host)
        currNetSett,currNetList = self.getSettings(host,"network")

        if self.NETWORKHOSTNAME == hostName:
            for vlan in currVlanList:
                pif = host.minimalList("vlan-param-get",args="uuid=%s param-name=tagged-PIF" % (vlan))[0] 
                hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
                if hostuuid == host.getMyHostUUID():
                    raise xenrt.XRTFailure("VLAN was not removed from host")

            for bond in currBondList:
                pif = host.minimalList("bond-param-get",args="uuid=%s param-name=master" % (bond))[0]
                hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
                if hostuuid == host.getMyHostUUID():
                    raise xenrt.XRTFailure("Bond was not removed from host")

            for tunnel in currTunnelList:
                pif = host.minimalList("tunnel-param-get",args="uuid=%s param-name=access-PIF" % (tunnel))[0]
                hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
                if hostuuid == host.getMyHostUUID():
                    raise xenrt.XRTFailure("Tunnel was not removed from host")

            self.checkPifsDoesNotExist(currPifsList,hostName)
            self.checkVif(currVifsList,currVifSett,hostName)

            self.checkNetwork(currNetList,currNetSett,hostName)
 
        elif self.NETWORKHOSTNAME <> hostName:
            if self.NETWORKHOSTNAME == "MASTER":     

                self.checkVlan(currVlanList,host)
                self.checkBond(currBondList,host)
                self.checkTunnel(currTunnelList,host)
                self.checkVif(currVifsList,currVifSett,hostName)
                self.checkNetwork(currNetList,currNetSett,hostName)
                self.checkPifsExist(currPifsList,hostName)

            elif self.NETWORKHOSTNAME == "SLAVE1": 

                if currVlanList:
                    raise xenrt.XRTFailure("VLAN was not removed from Host")
                if currBondList:
                    raise xenrt.XRTFailure("Bond was not removed from Host")
                if currTunnelList:
                    raise xenrt.XRTFailure("Tunnel was not removed from Host")

                self.checkPifsDoesNotExist(currPifsList,hostName)
                self.checkVif(currVifsList,currVifSett,hostName)

                self.checkNetwork(currNetList,currNetSett,hostName)

    def checkPifsDoesNotExist(self,currPifList,hostName):
 
        if len(currPifList) <> len(self.hostPifsList[hostName]):
            raise xenrt.XRTFailure("Number of Pifs are not same after Network reset")
 
    def checkPifsExist(self,currPifList,hostName):

        if len(currPifList) <> len(self.hostPifsListAfterChange[hostName]):
            raise xenrt.XRTFailure("Number of Pifs are not same after Network reset")    

    def checkVlan(self,currVlanList,host):

        flag = False
        if not currVlanList:
            flag = True
        for vlan in currVlanList:
            pif = host.minimalList("vlan-param-get",args="uuid=%s param-name=tagged-PIF" % (vlan))[0]
            hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
            if hostuuid == host.getMyHostUUID():
                flag = True
        if not flag:
            raise xenrt.XRTFailure("VLAN not found on host")
  
    def checkBond(self,currBondList,host):

        flag = False
        if not currBondList:
            flag = True
        for bond in currBondList:
            pif = host.minimalList("bond-param-get",args="uuid=%s param-name=master" % (bond))[0]
            hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
            if hostuuid == host.getMyHostUUID():
                flag = True
        if not flag:
            raise xenrt.XRTFailure("Bond not found on host")

    def checkTunnel(self,currTunnelList,host):

        flag = False
        if not currTunnelList:
            flag = True
        for tunnel in currTunnelList:
            pif = host.minimalList("tunnel-param-get",args="uuid=%s param-name=access-PIF" % (tunnel))[0]
            hostuuid = host.minimalList("pif-param-get",args="uuid=%s param-name=host-uuid" % (pif))[0]
            if hostuuid == host.getMyHostUUID():
                flag = True
        if not flag:
            raise xenrt.XRTFailure("Tunnel not found on host")
       
    def checkVif(self,currVifsList,currVifSett,hostName):

        if len(currVifsList) <> len(self.hostVifsList[hostName]):
            raise xenrt.XRTFailure("Number of vifs are not same after Network reset")
        elif len(currVifsList) > 0:
            for vif in currVifsList:
                if not vif in self.hostVifsList[hostName]:
                    raise xenrt.XRTFailure("Vif %s did not not exist earlier" % vif)
                else:
                    if currVifSett[vif] <> self.hostVifsSettings[hostName][vif]:
                        raise xenrt.XRTFailure("Vif settings of %s has changed" % vif)

    def checkNetwork(self,currNetList,currNetSett,hostName):

        if len(currNetList) <> len(self.hostNewNetworkList[hostName]):
            raise xenrt.XRTFailure("Number of networks are not same after Network reset")
        else:
            for net in currNetList:
                if not net in self.hostNewNetworkList[hostName]:
                    raise xenrt.XRTFailure("Network %s did not not exist earlier" % net)

    def checkManagementSettings(self,host,expectedSettings):

        param = {}
        #time to get things settled
        time.sleep(60)
        param = self.getManagementSettings(host)
        if param["IP"] <> expectedSettings["IP"]:
            raise xenrt.XRTFailure("IP is not same")
        if param["Netmask"] <> expectedSettings["Netmask"]:
            raise xenrt.XRTFailure("Netmask is not same")

    def postRun(self):

        currNetList = [] 
        currVlanList = []
        currTunnelList = []
        currBondList = []
        temp = {}

        for hostName in self.HOSTLIST:
            host = self.getHostObject(hostName) 
            cli = host.getCLIInstance()

            temp,currTunnelList = self.getSettings(host,"tunnel")
            for elmt in currTunnelList:
                if not elmt in self.hostTunnelList[hostName]:
                    try:
                        cli.execute("tunnel-destroy uuid=%s" %elmt)
                    except:
                        xenrt.TEC().logverbose("Exception occurred while destroying tunnel with uuid %s" % elmt) 

            temp,currVlanList = self.getSettings(host,"vlan")
            for elmt in currVlanList:
                if not elmt in self.hostVlanList[hostName]:
                    try:
                        cli.execute("vlan-destroy uuid=%s" %elmt)
                    except:
                        xenrt.TEC().logverbose("Exception occurred while destroying vlan with uuid %s" % elmt)

            temp,currBondList = self.getSettings(host,"bond")
            for elmt in currBondList:
                if not elmt in self.hostBondList[hostName]:
                    try:
                        cli.execute("bond-destroy uuid=%s" %elmt)
                    except:
                        xenrt.TEC().logverbose("Exception occurred while destroying bond with uuid %s" % elmt)

            #sleep is required so that host will come up with its default NIC instead of bond
            time.sleep(60)     
 
            temp,currNetList = self.getSettings(host,"network")
            for elmt in currNetList:
                if not elmt in self.hostNetworkList[hostName]:
                    try:
                        cli.execute("network-destroy uuid=%s" %elmt)
                    except:
                        xenrt.TEC().logverbose("Exception occurred while destroying network with uuid %s" % elmt)
        self.OLDIP = None

        if self.HOSTLIST[0] == "DEFAULT":
            host = self.getHostObject("DEFAULT")
            _NetworkReset.networkReset(self,host,"DEFAULT")
        else:
            host = self.getHostObject("MASTER")
            _NetworkReset.networkReset(self,host,"MASTER")           
            for hostName in self.HOSTLIST: 
                if hostName <> "MASTER":
                    host = self.getHostObject(hostName) 
                    _NetworkReset.networkReset(self,host,hostName)

class TC15479(_NetworkReset):
    """To test the behaviour of network reset on Slave when Management interface of Slave has changed, Bonds,tunnels,VLANs are created on Master """

    HOSTLIST = ["MASTER","SLAVE1","SLAVE2"]
    NETWORKHOSTNAME = "MASTER"
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    MANAGEMENTMODIFY = "SLAVE1"

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"balance-slb")
        addTunnel(host)         

class TC15480(_NetworkReset):
    """To test the behaviour of network reset on Master when Management interface of Master has changed, Bonds,tunnels,VLANs are created on Master"""

    HOSTLIST = ["MASTER","SLAVE1"]
    NETWORKHOSTNAME = "MASTER"
    AFFECTEDHOSTNAMES = ["MASTER"]
    MANAGEMENTMODIFY = "MASTER"
#    VMS = True

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"active-backup")
        addInternalNetwork(host)

class TC15481(_NetworkReset):
    """To test the behaviour of network reset on Slave when Management interface of Slave has changed, Bonds,internal networks are created on Slave"""

    HOSTLIST = ["MASTER","SLAVE1"]
    NETWORKHOSTNAME = "MASTER"
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    MANAGEMENTMODIFY = "SLAVE1"
#    VMS = True

    def changeNetworkSettings(self,host):

        addBondedNetwork(host,"active-backup")
        addInternalNetwork(host)

class TC15482(_NetworkReset):
    """To test the behaviour of network reset on Single host when its Management interface has changed,internal and external networks,tunnels are created on it"""

    HOSTLIST = ["DEFAULT"]
    NETWORKHOSTNAME = "DEFAULT"
    AFFECTEDHOSTNAMES = ["DEFAULT"]
    MANAGEMENTMODIFY = "DEFAULT"
#    VMS = True

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addTunnel(host)
        addInternalNetwork(host)
    
class TC15483(_NetworkReset):
    """To test the behaviour of network reset on Master of pool when its Management interface has moved to different device"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["MASTER"]
    MANAGEMENTMODIFY = "MASTER"
    OLDDEVICE = None
    
    def modifyManagement(self,host): 

        cli = host.getCLIInstance()
        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        self.OLDIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]
        self.OLDDEVICE = host.minimalList("pif-param-get",args="uuid=%s param-name=device" % (pifManagement))[0]

        nicid = host.listSecondaryNICs(network="NSEC")[0]        
        interface = host.getSecondaryNIC(nicid)        
        secPif = host.minimalList("pif-list",args="host-uuid=%s device=%s management=false carrier=true" % (host.getMyHostUUID(),interface))[0]        
        cli.execute("pif-reconfigure-ip mode=dhcp uuid=%s" % secPif)
        newIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (secPif))[0]
        command = "xe host-management-reconfigure pif-uuid=%s" % (secPif)
        try:
            host.execdom0("nohup %s > f.out 2> f.err < /dev/null &" % command,timeout=120)
        except:
            raise xenrt.XRTFailure("Failed while trying to change the Primary Management interface")

        #time to get things settled
        time.sleep(120)
        host.setIP(newIP)

class TC15484(TC15483):
    """To test the behaviour of network reset on Slave of pool when its Management interface has moved to different """

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    MANAGEMENTMODIFY = "SLAVE1"

class TC15485(TC15483):
    """To test the behaviour of network reset on Master of pool with the device as parameter when its Management interface has moved to different"""

    def networkReset(self,host,hostName):

        #Sleep is required as host-management-reconfigure command takes some time to swtich from one device to another
        time.sleep(60)
       
        host.networkReset(device=self.OLDDEVICE,setIP=self.OLDIP)
        self.checkManagementSettings(host,self.hostManagementSettings[hostName])

class TC15486(TC15485):
    """To test the behaviour of network reset on Slave of pool with the device as parameter when its Management interface has moved to different"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    MANAGEMENTMODIFY = "SLAVE1"

class TC15487(_NetworkReset):
    """To test the behaviour of network reset on Master and slave of pool when IP address of Master has changed"""

    HOSTLIST = ["MASTER","SLAVE1"]
    MANAGEMENTMODIFY = "MASTER"
    AFFECTEDHOSTNAMES = ["MASTER","SLAVE1"]

    def modifyManagement(self,host):

        pool = self.getDefaultPool()
        slaveHost = self.hostsObject["SLAVE1"]
        pool.eject(slaveHost)
        
        #Apply platinum license to slave host so we can form a pool 
        if not isinstance(slaveHost, xenrt.lib.xenserver.ClearwaterHost):
            slaveHost.license(edition='platinum')

        cli = slaveHost.getCLIInstance()
        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        self.OLDIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]

        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        self.masterOldIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]
        
        _NetworkReset.modifyManagement(self,host)
 
        pool.addHost(slaveHost)
        self.hostNewNetworkSettings["MASTER"],self.hostNewNetworkList["MASTER"] = self.getSettings(host,"network")
        self.hostNewNetworkSettings["SLAVE1"],self.hostNewNetworkList["SLAVE1"] = self.getSettings(slaveHost,"network")

    def networkReset(self,host,hostName):
 
        if hostName == "SLAVE1":
            host.networkReset(masterIP=self.masterOldIP)
        elif hostName == "MASTER":
            host.networkReset(setIP=self.masterOldIP)
        self.checkManagementSettings(host,self.hostManagementSettings[hostName])
 
class TC15488(_NetworkReset):
    """To test the behaviour of network reset on Master and slave when Bonds,tunnels,VLANs are created on Master"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["MASTER","SLAVE1"]
    NETWORKHOSTNAME = "MASTER"

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"balance-slb")
        addTunnel(host)

class TC15683(_NetworkReset):
    """To test the behaviour of network reset on Master and slave when Bonds (3 nics),tunnels,VLANs are created on Master"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["MASTER","SLAVE1"]
    NETWORKHOSTNAME = "MASTER"

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"balance-slb",numberOfNics=3)
        addTunnel(host)

class TC15684(_NetworkReset):
    """To test the behaviour of network reset on Master and slave when Bonds (4 nics),tunnels,VLANs are created on Master"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["MASTER","SLAVE1"]
    NETWORKHOSTNAME = "MASTER"

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"balance-slb",numberOfNics=4)
        addTunnel(host)

class TC15489(_NetworkReset):
    """To test the behaviour of network reset on slave when tunnels,VLANs and internal networks are created on slave"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    NETWORKHOSTNAME = "SLAVE1"

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addTunnel(host)
        addInternalNetwork(host)

class TC15490(_NetworkReset):
    """To test the behaviour of network reset command with all the possible valid parameters on Slave of pool when Management interface of Slave has changed, Bonds,tunnels,VLANs are created on Master"""

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["SLAVE1"]
    NETWORKHOSTNAME = "MASTER"
    MANAGEMENTMODIFY = "SLAVE1"

    def modifyManagement(self,host):

        self.param = {}
        cli = host.getCLIInstance()
 
        masterHost = self.hostsObject["MASTER"]
        pifManagement = host.minimalList("pif-list",args="host-uuid=%s management=true" % (host.getMyHostUUID()))[0]
        self.OLDIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]

        self.param["IP"] = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (pifManagement))[0]
        self.param["Netmask"] = host.minimalList("pif-param-get",args="uuid=%s param-name=netmask" % (pifManagement))[0]  
        self.param["Device"] = host.minimalList("pif-param-get",args="uuid=%s param-name=device" % (pifManagement))[0] 
        self.param["Mode"] = "static"
        self.param["masterIP"] = masterHost.getIP()
        self.param["gateway"] = self.getGateway(host)

        _NetworkReset.modifyManagement(self,host)

    def changeNetworkSettings(self,host):

        addExternalNetwork(host,123)
        addBondedNetwork(host,"balance-slb")
        addTunnel(host)

    def networkReset(self,host,hostName):
 
        host.networkReset(masterIP=self.param["masterIP"],
                          device=self.param["Device"],
                          ipMode="static",
                          ipAddr=self.param["IP"],
                          netmask=self.param["Netmask"],
                          setIP=self.param["IP"],
                          gateway=self.param["gateway"])
        expectedSettings = self.param
        self.checkManagementSettings(host,expectedSettings)

class TC15491(_NetworkReset):
    """To test the behaviour of network reset with device name being of NSec on Slave """

    HOSTLIST = ["MASTER","SLAVE1"]
    AFFECTEDHOSTNAMES = ["SLAVE1"]

    def networkReset(self,host,hostName):

        cli = host.getCLIInstance()
        nicid = host.listSecondaryNICs(network="NSEC")[0]
        interface = host.getSecondaryNIC(nicid)
        secPif = host.minimalList("pif-list",args="host-uuid=%s device=%s management=false carrier=true" % (host.getMyHostUUID(),interface))[0]
        cli.execute("pif-reconfigure-ip mode=dhcp uuid=%s" % secPif)
  
        time.sleep(120)
        newIP = host.minimalList("pif-param-get",args="uuid=%s param-name=IP" % (secPif))[0]
        newDevice = host.minimalList("pif-param-get",args="uuid=%s param-name=device" % (secPif))[0]

        expectedSettings ={}
        expectedSettings["IP"] = newIP
        expectedSettings["Netmask"] = host.minimalList("pif-param-get",args="uuid=%s param-name=netmask" % (secPif))[0]
        expectedSettings["Device"] = newDevice

        host.networkReset(device=newDevice,setIP=newIP)
        self.checkManagementSettings(host,expectedSettings)

class TC15492(TC15482):
    """To test the behaviour of network reset on Slave when Xapi is down """

    def networkReset(self,host,hostName):
      
        host.execdom0("service xapi stop")  

        host.networkReset(setIP=self.OLDIP) 

        self.checkManagementSettings(host,self.hostManagementSettings[hostName])
