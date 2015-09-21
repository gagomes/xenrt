 #
# XenRT: Test harness for Xen and the XenServer product family
#
# Bonding testcases
#

import socket, re, string, time, traceback, sys, random, copy, os, subprocess
import urllib2
import xenrt
import xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log, warning
from network import TCWith16Nics
import itertools
        
class _BondTestCase(xenrt.TestCase):
    BOND_MODE = None
    LACP_HASH_ALG = None
    NUMBER_NICS = 2
    
    def __init__(self):
        xenrt.TestCase.__init__(self)
        self.host = None
        self.secondaryInterfaces = []
    
    def findPIFToBondWithManagementNIC(self, host, numberOfNics=2):
        """Returns a list of two PIF UUIDs. The first in the list is the
        management interface and the second is an interface suitable to
        join with the current management NIC in a bond.
        """
        # Assume that the current management NIC is on the default NIC.
        managementPIF = host.parseListForUUID("pif-list","management","true")
        managementNIC = host.genParamGet("pif", managementPIF, "device")
        if managementNIC != host.getDefaultInterface():
            raise xenrt.XRTError("Management interface not initially "
                                 "on default interface")

        # Find another interface on the NPRI network (same as the default NIC)
        assumedids = host.listSecondaryNICs("NPRI")
        if len(assumedids) < (numberOfNics - 1):
            raise xenrt.XRTError("Could not find secondary NICs on NPRI")

        # Get the PIF for this interface
        secPIFs = []
        numberOfNics = numberOfNics - 1
        
        if self.BOND_MODE != 'lacp':
            assumedids = assumedids[0:numberOfNics]
        else:
            # find netport for management interface
            mngSwitch = self._getSwitchStackNameForNic(0)
            sameStackNics = []
            
            if not xenrt.lib.switch.suitableForLacp(mngSwitch):
                raise xenrt.XRTError("Management interface connected to switch "
                                     "with no XenRT LACP support: %s" % mngSwitch)
            
            for id in assumedids:
                switchStackName = self._getSwitchStackNameForNic(id)
                if switchStackName == mngSwitch:
                    sameStackNics.append(id)
                if len(sameStackNics) == numberOfNics:
                    break
            else:
                raise xenrt.XRTError("Failed to find %s NICs on the same switch and network as %s" 
                                    % (numberOfNics, managementNIC) )
                                    
            assumedids = sameStackNics
                
        for id in assumedids:
            secNIC = host.getSecondaryNIC(id)
            secPIFs.append(host.parseListForUUID("pif-list","device",secNIC))

        return [managementPIF] +  secPIFs


    def findPIFToBondWithNonManagementNIC(self, host,numberOfNics=2):
        """Returns a list of PIF UUIDs that can be bonded together"""
        # TODO: for LACP bonds, make sure only NICs within one switch stack
        #       once we have the distinction mechanism implemented
        ids = host.listSecondaryNICs("NSEC")
        if len(ids) < numberOfNics:
            raise xenrt.XRTError("Could not find secondry NICs on NSEC (%s found.)" % len(ids))

        if self.BOND_MODE != 'lacp':
            ids = ids[0:numberOfNics]
        else:
            counters={}
            for id in ids:
                switchStackName = self._getSwitchStackNameForNic(id)
                if not counters.has_key(switchStackName):
                    counters[switchStackName] = []
                counters[switchStackName].append(id)
            for switch, nicList in counters.items():
                if len(nicList) >= numberOfNics and xenrt.lib.switch.suitableForLacp(switch):
                    ids = nicList[0:numberOfNics]
                else:
                    log("Found secondary NICs on switches: %s" % counters)
                    raise xenrt.XRTError("Could not find %s secondary NICs on NSEC (%s)"
                                         % (numberOfNics, self.host.getName() ) )
                
        # Get the PIFs for the interfaces
        pifs = []      
        for id in ids:
            NIC = host.getSecondaryNIC(id)
            pifs.append(host.parseListForUUID("pif-list","device",NIC))

        ip = host.setIPAddressOnSecondaryInterface(ids[0])
        xenrt.TEC().comment("Secondary interface configured with IP %s" % (ip))
        self.secondaryInterfaces = [(ids[0], ip)]
        
        return pifs
        
    def _getSwitchStackNameForNic(self,id):
        if id==0:
            netport = self.host.lookup("NETPORT", None)
        else:
            netport = self.host.lookup(["NICS", "NIC%s" % id, "NETPORT"])
        if not netport:
            raise xenrt.XRTError("No NETPORT specified for NIC%s (%s)"
                        % (id, self.host.getName()))
        netportSplit = netport.rsplit('-', 1)
        if len(netportSplit) != 2:
            raise xenrt.XRTError("Unexpected format of NETPORT for NIC%s (%s): '%s'"
                        % (id, self.host.getName(), netport))
        stackName = netportSplit[0]
        return stackName

class Bond(object):
    """Structure to hold the basic data of one bond"""
    
    def __init__(self,device,bridge,uuid):
        self.device = device
        self.bridge = bridge
        self.uuid = uuid
        

class _BondSetUp(_BondTestCase):
    """Set up and functional test of bonded network interface"""

    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    
    def run(self, arglist=None):
        
        host = self.getDefaultHost()
        self.host = host
        
        step("Check if we don't already have a bond")
            
        if len(host.getBonds()) > 0:
            raise xenrt.XRTError("Host already has a bond interface")
        
        bond = self.createBonds(1, nicsPerBond=self.NUMBER_NICS, networkName=self.NETWORK_NAME)[0]
        
        self.device = bond.device
        
        step("Check the bond mode and number of NICs")
        
        self.checkBond()

        step("Check we can still see the host etc.")
        
        host.check(interfaces=[(bond.bridge, "yes", "dhcp", None, None, None, None, None, None)])

        step("Reboot the host")
        
        host.reboot()
        
        step("Check the bond after reboot")
        
        self.checkBond()
        
        step("Check we can still see the host after the reboot.")
        host.check(interfaces=[(bond.bridge, "yes", "dhcp", None, None, None, None, None, None)])

    def checkBond(self, device=None):
        # Check the bond status (bond mode and number of NICs)
        
        if not device:
            device = self.device
        
        (info,slaves) = self.host.getBondInfo(device)
        if len(info['slaves']) != self.NUMBER_NICS:
            raise xenrt.XRTFailure("Bond has %u slave devices, expected %u" % 
                                   (len(info['slaves']),self.NUMBER_NICS))
        
        # For LACP on Linux bridge, we do only rough bond mode check
        if self.BOND_MODE == 'lacp' and self.host.special['Network subsystem type'] == "linux":
            if info['mode'] != 'IEEE 802.3ad Dynamic link aggregation':
                raise xenrt.XRTFailure('We expected LACP bonding (IEEE 802.3ad), but bond mode is "%s"' % info['mode'])
            return
            
        # For vSwitch, we check that 'lacp_negotiated' is 'True'
        if self.BOND_MODE:
            if self.BOND_MODE == 'lacp':
                if not (info['lacp'] == 'true' or info['lacp'] == 'negotiated'):
                    log('LACP did not converge for the bond, maybe due to configuration mismatch between server and switch.')
                    log('Logging LACP information')
                    self.host.execdom0("ovs-appctl lacp/show %s" % device)
                    raise xenrt.XRTFailure(
                        "We expected lacp bonding, found lacp_negotiated=%s and mode=%s" %
                        (info['lacp'], info['mode']) )
            else:
                if not re.search(self.BOND_MODE, info['mode']):
                    raise xenrt.XRTFailure("We expected %s bonding, found %s" %
                                       (self.BOND_MODE, info['mode']))
    
    def createBonds(self, numOfBonds=1, nicsPerBond=2, networkName="NPRI"):
        """ Creates N bonds of M Nics each on the specified network, 
            Return: list of bond objects"""
        
        bonds = []
        
        log("Get the NICs for the bond")
        nics = numOfBonds * nicsPerBond
        if networkName == "NPRI":
            newpifs = self.findPIFToBondWithManagementNIC(self.host,numberOfNics=nics)
        else:
            newpifs = self.findPIFToBondWithNonManagementNIC(self.host,numberOfNics=nics)
            
        for i in range(numOfBonds):
            log("Creating bond %d of %d" % (i + 1, numOfBonds))
            j = i * nicsPerBond
            (bridge, device) = self.host.createBond(newpifs[j:j+nicsPerBond],dhcp=True,management=True,mode=self.BOND_MODE)
            bondPif = self.host.parseListForUUID("pif-list", "device", device)
            bondUuid = self.host.parseListForUUID("bond-list", "master", bondPif)
            bond = Bond(device,bridge,bondUuid)
            bonds.append(bond)
        
        return bonds

class TC6763(_BondSetUp):
    """Set up and functional test of bonded network interface"""
        
class TC12448(_BondSetUp):
    """Set up and functional test of active/passive bonded on NPRI network interface"""
    BOND_MODE = "active-backup"

class TC15595(_BondSetUp):
    """Set up and functional test of bonded network interface on NPRI with 3 Nics"""
    NUMBER_NICS = 3

class TC15596(_BondSetUp):
    """Set up and functional test of active/passive bonded network interface on NPRI with 3 NICS"""
    BOND_MODE = "active-backup"
    NUMBER_NICS = 3

class TC15597(_BondSetUp):
    """Set up and functional test of bonded network interface on NPRI with 4 NICS"""
    NUMBER_NICS = 4

class TC15598(_BondSetUp):
    """Set up and functional test of active/passive bonded network interface on NPRI with 4 NICS"""
    BOND_MODE = "active-backup"
    NUMBER_NICS = 4

class TC15599(_BondSetUp):
    """Set up and functional test of bond on NSEC network interface"""
    NETWORK_NAME = "NSEC"

class TC15600(_BondSetUp):
    """Set up and functional test of active/passive bond on NSEC network interface """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"

class TC15601(_BondSetUp):
    """Set up and functional test of bond on NSEC network interface with 3 Nics """
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 3

class TC15602(_BondSetUp):
    """Set up and functional test of active/passive bond on NSEC network interface with 3 Nics """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 3

class TC15603(_BondSetUp):
    """Set up and functional test of bond on NSEC network interface with 4 Nics """
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 4

class TC15604(_BondSetUp):
    """Set up and functional test of active/passive bond on NSEC network interface with 4 Nics """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 4

class TCActiveActive18nic(_BondSetUp):
    """Set up and functional test of active/active bond on NPRI network interface with 18 Nics """
    # jira TC18598
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 18

class TCActivePassive18nic(_BondSetUp):
    """Set up and functional test of active/passive bond on NPRI network interface with 18 Nics """
    # jira TC18600
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 18

class LacpBondSetUpNoMng(_BondSetUp):
    """Set up and functional test for a LACP bond"""
    # jira TC15398
    BOND_MODE = "lacp"
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 2

class LacpBondSetUpMng(_BondSetUp):
    """Set up and functional test for a LACP bond with management"""
    # jira TC15471
    BOND_MODE = "lacp"
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    
class TCLacpBondSetUpMng8Nic(LacpBondSetUpMng):
    """ Setup up and functional test for LACP bond with management using 8 Nics"""
    # jira TC18516
    NUMBER_NICS = 8
    
class TCLacpBondSetUpMng24Nic(LacpBondSetUpMng):
    """ Setup up and functional test for LACP bond with management using 24 Nics"""
    # jira id TC-18593
    NUMBER_NICS = 24
    
class TCAggregationKey(LacpBondSetUpMng):
    """ Verify that we can set a custom LACP aggregation key"""

    NUMBER_NICS = 2
    AGGREGATION_KEY = 23

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.bond = self.createBonds(1, nicsPerBond=self.NUMBER_NICS, networkName=self.NETWORK_NAME)[0]

    def run(self, arglist=None):
        bond = self.bond
        slaveDevice = self.host.parseListForOtherParam("pif-list", "bond-slave-of", bond.uuid, "device").split(',')[0]
        
        step("Set the custom value of aggregation key")
        log("Setting aggregation key %d" % (self.AGGREGATION_KEY))
        self.host.genParamSet('bond', bond.uuid, 'properties', self.AGGREGATION_KEY, 'lacp-aggregation-key')
        
        step('Verify the aggregation key from xapi')
        aggregationKey = self.host.genParamGet('bond',bond.uuid,'properties','lacp-aggregation-key')
        if int(aggregationKey) != self.AGGREGATION_KEY:
            raise xenrt.XRTFailure('Found aggregation-key from xapi to be: %d, expected: %d' % (int(aggregationKey), self.AGGREGATION_KEY))
        
        step('Verify the aggregation-key in LACPDU frames')
        mac = self.host.parseListForOtherParam("pif-list", "device", slaveDevice, "MAC")
        d = self.host.execdom0('tcpdump -v -c 1 -i %s ether proto 0x8809 and ether src host %s' % (slaveDevice, mac))
        match = re.search('Key (\d+)', d , re.MULTILINE)
        #The first "Key" match returns the Actor's key which is the host here
        if not match:
            raise xenrt.XRTError('Aggregation key not found in LACPDU frames')
        key = match.group(1)
        if int(key) != self.AGGREGATION_KEY:
            raise xenrt.XRTFailure('Found aggregation-key in LACPDU frames: %d, expected: %d' % (int(key), self.AGGREGATION_KEY))
            
    def postRun(self):
        self.host.removeBond(self.bond.uuid)
        
class TCLacpTime(LacpBondSetUpMng):
    """Set up and functional test of lacp-time parameter for a LACP bond"""
    # jira id TC-18773
    
    NUMBER_NICS = 2
    BOND_LACP_TIME = {"slow":30, "fast":1}
    SWITCH_LACP_TIME = {"long":30, "short":1}
    numOfBonds = 1
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.bonds = self.createBonds(self.numOfBonds, nicsPerBond=self.NUMBER_NICS, networkName=self.NETWORK_NAME)

    def getLacpTimeFromFrameFrequency(self, device, switch=False):
        """Determine the lacp-time value in LACPDU frames captured by one of the slave devices of the bonds.
           Arguments: slave device of a LACP bond"""
        
        numOfFramesToCapture = 10
        mac = self.host.parseListForOtherParam("pif-list", "device", device, "MAC")
        
        log("Capturing %d LACP frames" % numOfFramesToCapture)
        # Command tcpdump -ttt prints the time difference between two consecutive lines
        if not switch:
            command = "tcpdump -ttt -c %d -i %s ether proto 0x8809 and not ether src host %s" % (numOfFramesToCapture, device, mac)
        else:
            command = "tcpdump -ttt -c %d -i %s ether proto 0x8809 and ether src host %s" % (numOfFramesToCapture, device, mac)
        data = self.host.execdom0(command, timeout=600)
        measuredLacpTimes = re.findall(r'(\d+:\d+:\d+.\d+)', data, re.MULTILINE)
        if len(measuredLacpTimes) != numOfFramesToCapture:
            raise xenrt.XRTError("Unexpected number of LACP frames captured. Captured: %d, Expected: %d" % (len(measuredLacpTimes), numOfFramesToCapture))
        #first line has undefined interval
        del measuredLacpTimes[0]
        measuredLacpTimesSec = sum([3600*int(h) + 60*int(m) + float(s) for h, m, s in [t.split(':') for t in measuredLacpTimes]])
        avg = measuredLacpTimesSec/(numOfFramesToCapture - 1)
        
        return avg
    
    def getLacpTimeFromOvs(self, device):
        """ Retrieve the lacp-time value from the output of ovs-appctl command"""
        
        data = self.host.execdom0("ovs-appctl lacp/show %s" % device)
        match = re.search(r'lacp_time:(.+)', data, re.MULTILINE)
        if not match:
            raise xenrt.XRTError("Parameter lacp_time not found in the output of ovs-appctl command")
        
        return match.group(1).strip()

    def checkLacpTimeValue(self, actualValue, expectedValue):
        """ Verify if the actualValue matches expectedValue"""
        
        if actualValue != expectedValue:
            raise xenrt.XRTFailure("Unexpected value of lacp-time! Found: %s ; Expected: %s" % (actualValue, expectedValue))

    def verifyBondLacpTime(self, bond, lacpTimeType):
        """ Verify the lacp-time using xapi, ovs commands and LACP frames"""
        resolution = 5
        minLacpTime = self.BOND_LACP_TIME[lacpTimeType] - resolution
        maxLacpTime = self.BOND_LACP_TIME[lacpTimeType] + resolution
        
        slaveDevice = self.host.parseListForOtherParam("pif-list", "bond-slave-of", bond.uuid, "device").split(',')[0]
        
        log("Verify the lacp-time from xapi, ovs-appctl command, and LACP frames")
        lacpTimeFromXapi = self.host.genParamGet('bond',bond.uuid,'properties','lacp-time')
        lacpTimeFromOvs = self.getLacpTimeFromOvs(bond.device)
        lacpTimeFromLACPDUFrequency = self.getLacpTimeFromFrameFrequency(slaveDevice)
        if not ( all(t == lacpTimeType for t in (lacpTimeFromXapi,lacpTimeFromOvs)) and \
                 minLacpTime <= round(lacpTimeFromLACPDUFrequency) <= maxLacpTime ):
            
            raise xenrt.XRTFailure("Unexpected LACP time found",
                                     data="Xapi: %s, Ovs: %s, Lacp Frame rate: %d"
                                     % (lacpTimeFromXapi, lacpTimeFromOvs, lacpTimeFromLACPDUFrequency))

    def verifySwitchLacpTime(self, bond, lacpTime):
        """ Verify the lacptime by capturing LACP frames"""
        resolution = 5
        minLacpTime = self.SWITCH_LACP_TIME[lacpTime] - resolution
        maxLacpTime = self.SWITCH_LACP_TIME[lacpTime] + resolution
        
        slaveDevice = self.host.parseListForOtherParam("pif-list", "bond-slave-of", bond.uuid, "device").split(',')[0]
        
        log("Verify the lacp-time from  LACP frames")
        lacpTimeFromLACPDUFrequency = self.getLacpTimeFromFrameFrequency(slaveDevice, switch=True)
        if not (minLacpTime <= round(lacpTimeFromLACPDUFrequency) <= maxLacpTime) :
            raise xenrt.XRTFailure("Unexpected LACP time found",
                                     data="LACP Timeout@switch should be between %d and %d ,actual lacpFrameRate : %d"
                                     % (minLacpTime, maxLacpTime, lacpTimeFromLACPDUFrequency))

    def setSwitchLacpTimeout(self, switch, lacpTime):
        """ Set the Lacp Timeout of switch to specified value"""
        
        for port in switch.ports:
            switch.setLacpTimeout(port, lacpTime)
            
        switch.disconnect()

    def run(self, arglist=None):
        
        bond = self.bonds[0]
        pifs = [pif.strip() for pif in self.host.genParamGet("bond",bond.uuid,"slaves").split(";")]
        self.switch = xenrt.lib.switch.createSwitchForPifs(self.host, pifs)
        
        xenrt.sleep(300)
        
        step("Verify the default lacp-time of the bond")
        self.verifyBondLacpTime(bond, "slow")
        
        step("Verify the default lacp-time of the switch")
        self.verifySwitchLacpTime(bond, "long")
        
        step("Modify lacp-time of bond and switch and check if settings survive after host reboot")
        for bondLacpTime in self.BOND_LACP_TIME.keys():
            
            step("Set the lacp-time of bond to %s" % (bondLacpTime))
            self.host.genParamSet("bond",bond.uuid,"properties",bondLacpTime,"lacp-time")
            
            for switchLacpTime in self.SWITCH_LACP_TIME.keys():
                
                step("Set the lacp-time of switch to %s" % (switchLacpTime))
                self.setSwitchLacpTimeout(self.switch, switchLacpTime)
                
                xenrt.sleep(300)
                
                step("Verify the lacp-time of the bond")
                self.verifyBondLacpTime(bond, bondLacpTime)
                
                step("Verify the lacp-time of the switch")
                self.verifySwitchLacpTime(bond, switchLacpTime)
                
                step('Reboot the host')
                self.host.reboot()
                
                xenrt.sleep(300)
                
                step("Verify the lacp-time of the bond after host reboot")
                self.verifyBondLacpTime(bond, bondLacpTime)
                
                step("Verify the lacp-time of the switch after host reboot")
                self.verifySwitchLacpTime(bond, switchLacpTime)

    def postRun(self):
        self.setSwitchLacpTimeout(self.switch, "long")
        for bond in self.bonds:
            self.host.removeBond(bond.uuid)

class TCLacpTime2Bonds(TCLacpTime):
    """Set up and functional test of lacp-time parameter for two LACP bonds on same network.
       We change the lacp-time on one of the two bonds and check if the change persists"""
    
    # jira id TC-18776
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    numOfBonds=2

    def run(self, arglist=None):
        
        step("Get the lacp-time of the bonds")
        for bond in self.bonds:
            lacpTime = self.host.genParamGet('bond',bond.uuid,'properties','lacp-time')
            log("The lacp-time of %s is : %s" % (bond.device, lacpTime))
            
        bond2modif = self.bonds[1]
        bondUnmodif = self.bonds[0]
        
        step('Change the lacp-time to fast for one of the bonds')
        self.host.genParamSet("bond", bond2modif.uuid, "properties", "fast", "lacp-time")

        step("Verify lacp-time value for the unmodified bond")
        self.verifyBondLacpTime(bondUnmodif, "slow")
        
        step("Verify lacp-time value for the modified bond")
        self.verifyBondLacpTime(bond2modif, "fast")
        
    def postRun(self):
        for bond in self.bonds:
            self.host.removeBond(bond.uuid)

class LacpBondMngAs2(_BondSetUp):
    """LACP bond with management pif given as second in the pif list"""
    # jira TC-15935
    BOND_MODE = "lacp"
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    
    def findPIFToBondWithNonManagementNIC(self, host,numberOfNics=2):
        pifList = _BondSetUp.findPIFToBondWithNonManagementNIC(self, host, numberOfNics)
        mNic = pifList[0]
        pifList[0] = pifList[1]
        pifList[1] = mNic
        return pifList
        
    def run(self, arglist=None):

        _BondSetUp.run(self, arglist)
        
        step("Delete the bond") 
        host = self.host
        bond = host.getBonds()[0]        
        (bridge,device) = host.removeBond(bond, dhcp=True, management=True)
        time.sleep(20)
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
        
        host.reboot()
        
        step("Check the host after reboot") 
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
    
class TCNxMultiNicBond(_BondSetUp):
    """ Create x Bonds with n NICs each"""
    
    NUM_OF_BONDS = None
    NUMBER_NICS = None
    bonds = []
    
    def run(self, arglist=None):
        
        self.host = self.getDefaultHost()
        
        step("Get the NICs for the bond")
        nics = self.NUM_OF_BONDS * self.NUMBER_NICS
        if self.NETWORK_NAME == "NPRI":
            newpifs = self.findPIFToBondWithManagementNIC(self.host,numberOfNics=nics)
        else:
            newpifs = self.findPIFToBondWithNonManagementNIC(self.host,numberOfNics=nics)
            
        for i in range(self.NUM_OF_BONDS):
        
            step("Creating bond %d of %d" % (i + 1, self.NUM_OF_BONDS))
            j = i * self.NUMBER_NICS
            (bridge,device) = self.host.createBond(newpifs[j:j+self.NUMBER_NICS],mode=self.BOND_MODE)
            self.bonds.append((bridge,device))
        
            step("Check the bond mode and number of NICs")
            self.checkBond(device)
        
        if len(self.host.getBonds()) != self.NUM_OF_BONDS:
            raise xenrt.XRTError('Number of bonds created is %d and does not equals the intended number %d' % (len(self.host.getBonds()), self.NUM_OF_BONDS))
        
        step("Check we can still see the host")
        self.host.check(interfaces=[(self.bonds[0][0], "yes", "dhcp", None, None, None, None, None, None)])
        
        step("Reboot the host")
        self.host.reboot()
        
        step("Check the bond mode and number of NICs")
        for bridge, device in self.bonds:
            self.checkBond(device)
        
        step("Check we can still see the host after the reboot")
        self.host.check(interfaces=[(self.bonds[0][0], "yes", "dhcp", None, None, None, None, None, None)])

class TCLacpBondx9(TCNxMultiNicBond):
    """Create 9 LACP Bonds with 2 NICs each"""
    # jira id TC-18515
    BOND_MODE = "lacp"
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    NUM_OF_BONDS = 9
    
class TCLacpBondx12(TCNxMultiNicBond):
    """Create 12 LACP Bonds with 2 NICs each"""
    # jira id TC-18596
    BOND_MODE = "lacp"
    NETWORK_NAME = "NPRI"
    NUMBER_NICS = 2
    NUM_OF_BONDS = 12
    
class BondSplit(_BondTestCase):
    """Split a bonded interface into two normal interfaces"""
    NETWORK_NAME = 'NPRI'

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        
        management = True
        if self.NETWORK_NAME != "NPRI":
            management = False

        step("Check that we have a bond")
        
        bonds = host.getBonds()
        if len(bonds) == 0:
            raise xenrt.XRTError("Host has no bond interfaces")

        step("Delete the bond device")
        (bridge,device) = host.removeBond(bonds[0], dhcp=True, management=management)

        step("Wait 20 seconds to do DHCP etc.")

        time.sleep(20)

        step("Check we can still see the host etc.")
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        step("Reboot the host") 
        host.reboot()
        
        step("Check the host after reboot") 
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

class TC6868(BondSplit):
    """Split a bonded interface into two normal interfaces"""
    
class BondSplitNoMng(BondSplit):
    NETWORK_NAME = "NSEC"
    
class TCSplitExistingBonds(BondSplit):
    """Remove all the bonds present"""

    def run(self, arglist=None):
        
        self.host = self.getDefaultHost()
        
        step("Check that we have a bond")
        bonds = self.host.getBonds()
        if len(bonds) == 0:
            raise xenrt.XRTError("Host has no bond interfaces")
        log(bonds)
        
        for bond in bonds:
            step("Deleting bond %s " % (bond))
            (bridge,device) = self.host.removeBond(bond)

            step("Wait 20 seconds to do DHCP etc.")
            xenrt.sleep(20)

        step("Check we can still see the host etc.")
        bridge = self.host.getPrimaryBridge()
        self.host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        step("Reboot the host") 
        self.host.reboot()
        
        step("Check the host after reboot") 
        self.host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
        
class VmOnVlanOnBond(_BondTestCase):
    """VLAN based networks on top of a bonded interface (VM on VLAN, management on bond)"""

    NUMBER_NICS = 2
    NETWORK_NAME = "NPRI"

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        self.vlansToRemove = []

        step("Check available VLANS for the host")
        vlans = host.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]

        step("Check if we already have a bond")
        # If we don't already have a bond create one
        bonds = host.getBonds()
        if len(bonds) > 0:
            usebond = bonds[0]
            deletebond = False
        else:
            # Create the bond
            step("Create the bond")
            if self.NETWORK_NAME == "NPRI":
                newpifs = self.findPIFToBondWithManagementNIC(host,numberOfNics=self.NUMBER_NICS)
            else:
                newpifs = self.findPIFToBondWithNonManagementNIC(host,numberOfNics=self.NUMBER_NICS)
 
            (bridge,device) = host.createBond(newpifs,
                                              dhcp=True,
                                              management=True,
                                              mode=self.BOND_MODE)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)
            
            step("Check the number of slaves")

            (info,slaves) = host.getBondInfo(device)
            if len(info['slaves']) != self.NUMBER_NICS:
                raise xenrt.XRTFailure("Bond has %u slave devices, expected %u" % 
                                       (len(info['slaves']),self.NUMBER_NICS))

            step("Check we can still see the host etc.")
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
            usebond = host.getBonds()[0]
            deletebond = True

        step("Create a VLAN network on the bonded PIF")
        pif = host.genParamGet("bond", usebond, "master")
        nic = host.genParamGet("pif", pif, "device")
        vbridge = host.createNetwork()
        host.createVLAN(vlan, vbridge, nic)
        self.vlansToRemove.append(vlan)
        
        step("Check VLAN")
        host.checkVLAN(vlan, nic)

        step("Install a VM using the VLAN network")
        bridgename = host.genParamGet("network", vbridge, "bridge")
        g = host.createGenericLinuxGuest(bridge=bridgename)
        self.uninstallOnCleanup(g)

        step("Check the VM")
        g.check()
        g.checkHealth()
        if subnet and netmask:
            ip = g.getIP()
            if xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (ip, subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")
        g.shutdown()

        step("Reboot the host and check VM again")
        host.reboot()

        step("Check the VM after host reboot")
        g.start()
        g.check()
        g.checkHealth()
        if subnet and netmask:
            ip = g.getIP()
            if not xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")

        step("Uninstall the VM")
        g.shutdown()
        g.uninstall()

        step("Remove the VLAN interface")
        host.removeVLAN(vlan)
        self.vlansToRemove.remove(vlan)
        
        # Unbond the interfaces
        if deletebond:
            step("Delete the bond device")
            (bridge,device) = host.removeBond(usebond,
                                              dhcp=True,
                                              management=True)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

            # Reboot and check it still works
            host.reboot()
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

    def postRun2(self):
        try:
            for vlan in self.vlansToRemove:
                try:
                    self.host.removeVLAN(vlan)
                except:
                    pass
        except:
            pass

class TCGROEnable(VmOnVlanOnBond):
    """GRO can be enabled/disabled via ethtool on a VLAN on top of the bond (Regression test for SCTX-1584)"""
    #Jira TC-20998

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        vid, subnet, netmask = host.getVLAN("VR01")
        cli = host.getCLIInstance()
        self.device = cli.execute("pif-list", "VLAN=%s params=device --minimal" % vid).strip()
        
    def run(self, arglist=None):
        host = self.getDefaultHost()
        
        step("Enable GRO and check status")
        host.execdom0('ethtool -K %s gro on' % self.device)
        status = host.execdom0('ethtool -k %s | grep "generic-receive-offload: " | cut -d ":" -f 2' % self.device).strip()
        if status == "on":
            log("GRO could be enabled using ethtool")
        else:
            raise xenrt.XRTFailure("Unexpected Exception Occured. Expected status='on', Found '%s'" % status)
            
        step("Disable GRO and check status")
        host.execdom0('ethtool -K %s gro off' % self.device)
        status = host.execdom0('ethtool -k %s | grep "generic-receive-offload: " | cut -d ":" -f 2' % self.device).strip()
        if status == "off":
            log("GRO could be disabled using ethtool")
        else:
            raise xenrt.XRTFailure("Unexpected Exception Occured. Expected status='off', Found '%s'" % status)

class TCGSOBondedInterface(xenrt.TestCase):
    """GRO and GSO enablement for bonded interface (SCTX-1532)"""
    #Jira TC-21157
 
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        cli = self.host.getCLIInstance()
        self.bondSlavePif = cli.execute("bond-list", "params=slaves --minimal").split(';')[0]
        self.pifDevice = cli.execute("pif-param-get", "param-name=device uuid=%s --minimal" % self.bondSlavePif).strip()
        
    def run(self, arglist=None):
        step("Set gso off and gro on for bonded interface")
        cli = self.host.getCLIInstance()
        cli.execute("pif-param-set", "uuid=%s other-config:ethtool-gso='off' --minimal" % self.bondSlavePif)
        cli.execute("pif-param-set", "uuid=%s other-config:ethtool-gro='on' --minimal" % self.bondSlavePif)
        
        step("Reboot Host")
        self.host.reboot()
        xenrt.sleep(30)
        
        step("Verify GRO and GSO status")
        self.verifyEthtoolParam("generic-segmentation-offload", "off")
        self.verifyEthtoolParam("generic-receive-offload", "on")
            
        step("Set gso on and gro off for bonded interface")
        cli.execute("pif-param-set", "uuid=%s other-config:ethtool-gso='on' --minimal" % self.bondSlavePif)
        cli.execute("pif-param-set", "uuid=%s other-config:ethtool-gro='off' --minimal" % self.bondSlavePif)
        
        step("Reboot Host")
        self.host.reboot()
        xenrt.sleep(30)
        
        step("Verify GRO and GSO")
        self.verifyEthtoolParam("generic-segmentation-offload", "on")
        self.verifyEthtoolParam("generic-receive-offload", "off")
        
    def verifyEthtoolParam(self, param, expected):
        command = 'ethtool -k %s | grep "%s: " | cut -d ":" -f 2' % (self.pifDevice, param)
        status = self.host.execdom0(command).strip()
        if status == expected:
            log("%s is %s on bonded interface" % (param, status))
        else:
            raise xenrt.XRTFailure("Unexpected Exception Occured. Expected %s status='%s', Found '%s'" % (param, expected, status))
        

class TC7338(VmOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM on VLAN, management on bond)"""
            
class TC12449(VmOnVlanOnBond):
    """VLAN based networks on top of an active/passive bonded interface
    (VM on VLAN, management on bond)"""
    BOND_MODE = "active-backup"

class TC15615(VmOnVlanOnBond):
    """VLAN based networks on top of a NSEC bonded interface (VM on VLAN, management on bond) """
    NETWORK_NAME = "NSEC"

class TC15616(VmOnVlanOnBond):
    """VLAN based networks on top of a NSEC active/passive bonded interface (VM on VLAN, management on bond) """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"

class TC15617(VmOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM on VLAN, management on bond) with 3 Nics"""
    NUMBER_NICS = 3
 
class TC15618(VmOnVlanOnBond):
    """VLAN based networks on top of a active passive bonded interface (VM on VLAN, management on bond) with 3 Nics """
    BOND_MODE = "active-backup"
    NUMBER_NICS = 3

class TC15619(VmOnVlanOnBond):
    """VLAN based NSEC networks on top of a bonded interface (VM on VLAN, management on bond) with 3 Nics """
    NUMBER_NICS = 3
    NETWORK_NAME = "NSEC"

class TC15620(VmOnVlanOnBond):
    """VLAN based NSEC networks on top of a active passive bonded interface (VM on VLAN, management on bond) with 3 Nics """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 3

class TC15621(VmOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM on VLAN, management on bond) with 4 Nics"""
    NUMBER_NICS = 4

class TC15622(VmOnVlanOnBond):
    """VLAN based networks on top of a active passive bonded interface (VM on VLAN, management on bond) with 4 Nics """
    BOND_MODE = "active-backup"
    NUMBER_NICS = 4

class TC15623(VmOnVlanOnBond):
    """VLAN based NSEC networks on top of a bonded interface (VM on VLAN, management on bond) with 4 Nics """
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 4

class TC15624(VmOnVlanOnBond):
    """VLAN based NSEC networks on top of a active passive bonded interface (VM on VLAN, management on bond) with 4 Nics """
    BOND_MODE = "active-backup"
    NETWORK_NAME = "NSEC"
    NUMBER_NICS = 4


class VmOnVlanOnLacp(VmOnVlanOnBond):
    """VLAN based networks on top of LACP bond (VM on VLAN, management on bond)"""
    BOND_MODE = "lacp"
    
class VmAndMngOnVlanOnBond(_BondTestCase):
    """VLAN based networks on top of a bonded interface (VM and management on VLAN)"""
    NUMBER_NICS = 2

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        self.vlansToRemove = []
        
        step("Check available VLANS for the host")
        vlans = host.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]

        step("Check if we already have a bond")
        # If we don't already have a bond create one
        bonds = host.getBonds()
        if len(bonds) > 0:
            usebond = bonds[0]
            deletebond = False
        else:
            # Create the bond
            step("Create the bond")
            newpifs = self.findPIFToBondWithManagementNIC(host,numberOfNics=self.NUMBER_NICS)
            (bridge,device) = host.createBond(newpifs,
                                              dhcp=True,
                                              management=True,
                                              mode=self.BOND_MODE)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            step("Check the number of slaves")

            (info,slaves) = host.getBondInfo(device)
            if len(info['slaves']) != self.NUMBER_NICS:
                raise xenrt.XRTFailure("Bond has %u slave devices, expected %u" % 
                                       (len(info['slaves']),self.NUMBER_NICS))

            step("Check we can still see the host etc.")
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
            usebond = host.getBonds()[0]
            deletebond = True

        step("Create a VLAN network on the bonded PIF")
        pif = host.genParamGet("bond", usebond, "master")
        nic = host.genParamGet("pif", pif, "device")
        vbridge = host.createNetwork()
        host.createVLAN(vlan, vbridge, nic)
        self.vlansToRemove.append(vlan)
        host.checkVLAN(vlan, nic)

        step("Move the management interface to the VLAN PIF")
        oldpif = host.parseListForUUID("pif-list",
                                       "management",
                                       "true",
                                       "host-uuid=%s" % (host.getMyHostUUID()))
        newpif = host.parseListForUUID("pif-list",
                                       "VLAN",
                                       vlan,
                                       "host-uuid=%s" % (host.getMyHostUUID()))
        cli = host.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (newpif))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (newpif))
        except:
            pass
        time.sleep(120)
        newip = host.execdom0("xe host-param-get uuid=%s param-name=address" %
                              (host.getMyHostUUID())).strip()
        if newip == host.getIP():
            raise xenrt.XRTError("Host address unchanged after reconfigure")
        host.machine.ipaddr = newip
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (oldpif))

        step("Install a VM using the VLAN network")
        bridgename = host.genParamGet("network", vbridge, "bridge")
        g = host.createGenericLinuxGuest(bridge=bridgename)
        self.uninstallOnCleanup(g)

        step("Check the VM")
        g.check()
        g.checkHealth()
        if subnet and netmask:
            ip = g.getIP()
            if xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (ip, subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")
        g.shutdown()

        step("Reboot the host and check VM again")
        host.reboot()

        step("Check the VM after host reboot")
        g.start()
        g.check()
        g.checkHealth()
        if subnet and netmask:
            ip = g.getIP()
            if not xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")

        step("Uninstall the VM")
        g.shutdown()
        g.uninstall()

        step("Switch management back to the bond")
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (oldpif))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (oldpif))
        except:
            pass
        time.sleep(120)
        newip = host.execdom0("xe host-param-get uuid=%s param-name=address" %
                              (host.getMyHostUUID())).strip()
        if newip == host.getIP():
            raise xenrt.XRTError("Host address unchanged after 2nd reconfigure")
        host.machine.ipaddr = newip
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (newpif))

        step("Remove the VLAN interface")
        host.removeVLAN(vlan)
        self.vlansToRemove.remove(vlan)
        
        # Unbond the interfaces
        if deletebond:
            step("Delete the bond device")
            (bridge,device) = host.removeBond(usebond,
                                              dhcp=True,
                                              management=True)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

            # Reboot and check it still works
            host.reboot()
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

    def postRun2(self):
        try:
            for vlan in self.vlansToRemove:
                try:
                    self.host.removeVLAN(vlan)
                except:
                    pass
        except:
            pass

class TC8092(VmAndMngOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM and management on VLAN)"""
    NUMBER_NICS = 2
            
class TC15625(VmAndMngOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM and management on VLAN) with 3 Nics"""
    NUMBER_NICS = 3

class TC15626(VmAndMngOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM and management on VLAN) with 4 Nics"""
    NUMBER_NICS = 4

class VmAndMngOnVlanOnLacp(VmAndMngOnVlanOnBond):
    """VLAN based networks on top of a bonded interface (VM and management on VLAN) with 4 Nics"""
    BOND_MODE = "lacp"
    
class TC6764(_BondTestCase):
    """Bonded network interface failover"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TC6764")
        self.host = None
        self.device = None
        self.macs = []
        self.guestsToClean = []
        self.workloads = ["LinuxNetperfTX","LinuxNetperfRX"]

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"

        if arglist and len(arglist) > 0:
            machine = arglist[0]

        if len(arglist) > 1:
            for arg in arglist[1:]:
                l = string.split(arg, "=")
                if l[0] == "workloads":
                    self.workloads = l[1].split(",")

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host

        if len(host.getBonds()) == 0:
            raise xenrt.XRTError("Host does not have any bonded interfaces")

        bondUUID = host.getBonds()[0]

        # Get the bond device, and get info about it
        bondPIF = host.genParamGet("bond", bondUUID, "master")
        device = host.genParamGet("pif", bondPIF, "device")
        self.device = device
        (info, slaves) = host.getBondInfo(device)

        if len(info['slaves']) != 2:
            raise xenrt.XRTError("Bond has %u slaves, expected 2" % 
                                 (len(info['slaves'])))


        slaveNames = slaves.keys()
        for slave in slaveNames:
            if info['active_slave'] == slave:
                # slave0 is defined as the initially active port
                slave0 = slave
                mac0 = slaves[slave]["hwaddr"]
            else:
                slave1 = slave
                mac1 = slaves[slave]["hwaddr"]

        # Install a linux guest for netperf use
        guest = host.createGenericLinuxGuest()
        self.guestsToClean.append(guest)
        
        # Start workloads going
        startedWorkloads = guest.startWorkloads(self.workloads)

        self.macs.append(mac0)
        self.macs.append(mac1)

        # Disable the inactive port
        host.disableNetPort(mac1)
        time.sleep(5)
        self.checkBond(slave0,[slave0],[slave1])
        # Re-enable
        host.enableNetPort(mac1)
        time.sleep(35)
        self.checkBond(slave0,[slave0,slave1],[])

        # Disable the active port
        host.disableNetPort(mac0)
        time.sleep(5)
        self.checkBond(slave1,[slave1],[slave0])
        # Re-enable
        host.enableNetPort(mac0)
        time.sleep(35)
        self.checkBond(slave1,[slave0,slave1],[])

        # Disable the newly active port
        host.disableNetPort(mac1)
        time.sleep(5)
        self.checkBond(slave0,[slave0],[slave1])
        # Re-enable
        host.enableNetPort(mac1)
        time.sleep(35)
        self.checkBond(slave0,[slave0,slave1],[])

        # Stop the workloads
        guest.stopWorkloads(startedWorkloads)

    def checkBond(self, active, up, down):
        # Check the bond device matches what we expect
        (info, slaves) = self.host.getBondInfo(self.device)
        if info['active_slave'] != active:
            raise xenrt.XRTFailure("Slave %s was active, expected %s" % 
                                   (info['active_slave'],active))
        for s in up:
            if s in info['slaves']:
                if slaves[s]['status'] != "up":
                    raise xenrt.XRTFailure("Slave %s %s, expected up" %
                                           (s,slaves[s]['status']))
            else:
                raise xenrt.XRTFailure("Slave %s not found" % (s))       
        for s in down:
            if s in info['slaves']:
                if slaves[s]['status'] != "down":
                    raise xenrt.XRTFailure("Slave %s %s, expected down" %
                                           (s,slaves[s]['status']))
            else:
                raise xenrt.XRTFailure("Slave %s not found" % (s))

    def postRun(self):
        xenrt.TEC().logverbose("Re-enabling all ports in case any have been "
                               "left disabled")
        for mac in self.macs:
            self.host.enableNetPort(mac)

        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

class TC7342(_BondTestCase):
    """Netperf TX and RX over a bonded interface"""

    DURATION = 3600
    PERFDURATION = 120

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host

        # If we don't already have a bond create one
        bonds = host.getBonds()
        if len(bonds) > 0:
            usebond = bonds[0]
            deletebond = False
        else:
            # Create the bond
            newpifs = self.findPIFToBondWithManagementNIC(host)
            (bridge,device) = host.createBond(newpifs,dhcp=True,management=True)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check the bond status
            (info,slaves) = host.getBondInfo(device)
            if len(info['slaves']) != 2:
                raise xenrt.XRTFailure("Bond has %u slave devices, expected 2" % 
                                       (len(info['slaves'])))

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
            usebond = host.getBonds()[0]
            deletebond = True

        # Install a VM using the bonded network
        bpif = host.genParamGet("bond", usebond, "master")
        bnetwork = host.genParamGet("pif", bpif, "network-uuid")
        bridgename = host.genParamGet("network", bnetwork, "bridge")
        g = host.createGenericLinuxGuest(bridge=bridgename)
        self.uninstallOnCleanup(g)
        g.installNetperf()

        # Check the VM
        g.check()
        g.checkHealth()

        peer = xenrt.NetworkTestPeer(shared=True)
        try:
            # Start netperf transfers
            cmd = "netperf -H %s -t TCP_STREAM -l %u -v 0 -P 0" % \
                  (peer.getAddress(), self.DURATION)
            handle0 = self.startAsync(g, cmd)
            cmd = "netperf -H %s -t TCP_MAERTS -l %u -v 0 -P 0" % \
                  (peer.getAddress(), self.DURATION)
            handle1 = self.startAsync(g, cmd)
            
            # Wait for the jobs to complete, check health while we go
            deadline = xenrt.util.timenow() + self.DURATION + 60
            while xenrt.util.timenow() < deadline:
                # Check VM and the host
                g.checkHealth()
                host.checkHealth()
                time.sleep(30)

            # Check the jobs have completed and get the results
            if self.pollAsync(handle0):
                rate = float(self.completeAsync(handle0))
                if rate < 200.0:
                    xenrt.TEC().warning("Tranfer TX rate %fMbps" % (rate))
            else:
                raise xenrt.XRTFailure("Tranfer TX still running")
            if self.pollAsync(handle1):
                rate = float(self.completeAsync(handle1))
                if rate < 200.0:
                    xenrt.TEC().warning("Tranfer RX rate %fMbps" % (rate))
            else:
                raise xenrt.XRTFailure("Tranfer RX still running")
        finally:
            peer.release()

        # Now run a performance test
        peer = xenrt.NetworkTestPeer()
        try:
            # Start netperf transfers
            cmd = "netperf -H %s -t TCP_STREAM -l %u -v 0 -P 0" % \
                  (peer.getAddress(), self.PERFDURATION)
            handle0 = self.startAsync(g, cmd)
            cmd = "netperf -H %s -t TCP_MAERTS -l %u -v 0 -P 0" % \
                  (peer.getAddress(), self.PERFDURATION)
            handle1 = self.startAsync(g, cmd)
            
            # Wait for the jobs to complete, check health while we go
            deadline = xenrt.util.timenow() + self.PERFDURATION + 60
            while xenrt.util.timenow() < deadline:
                # Check VM and the host
                g.checkHealth()
                host.checkHealth()
                time.sleep(30)

            # Check the jobs have completed and get the results
            if self.pollAsync(handle0):
                rate = float(self.completeAsync(handle0))
                if rate < 600.0:
                    raise xenrt.XRTFailure("Tranfer TX rate %fMbps" % (rate))
            else:
                raise xenrt.XRTFailure("Tranfer TX still running")
            if self.pollAsync(handle1):
                rate = float(self.completeAsync(handle1))
                if rate < 600.0:
                    raise xenrt.XRTFailure("Tranfer RX rate %fMbps" % (rate))
            else:
                raise xenrt.XRTFailure("Tranfer RX still running")
        finally:
            peer.release()

        # Check the VM
        g.check()
        g.checkHealth()

        # Uninstall the VM
        g.shutdown()
        g.uninstall()

        # Unbond the interfaces
        if deletebond:
            # Delete the bond device
            (bridge,device) = host.removeBond(usebond,
                                              dhcp=True,
                                              management=True)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

            # Reboot and check it still works
            host.reboot()
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

class MngOnExBondSlave(_BondTestCase):
    """Verify that an interface used as a bond slave can be used as a management interface"""
    NUMBER_NICS = 2

    def run(self, arglist=None):
        host = self.getDefaultHost()
        self.host = host
        cli = host.getCLIInstance()

        # Check we don't already have a bond...
        if len(host.getBonds()) > 0:
            raise xenrt.XRTError("Host already has a bond interface")

        # Create the bond
        newpifs = self.findPIFToBondWithManagementNIC(host,numberOfNics=self.NUMBER_NICS)
        (bridge,device) = host.createBond(newpifs,dhcp=True,management=True, mode=self.BOND_MODE)

        # Give it 20 seconds to do DHCP etc
        time.sleep(20)

        # Check the bond status
        (info,slaves) = host.getBondInfo(device)
        if len(info['slaves']) != self.NUMBER_NICS:
            raise xenrt.XRTFailure("Bond has %u slave devices, expected %u" %
                                   (len(info['slaves']),self.NUMBER_NICS))

        # Check we can still see the host etc...
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        # Delete the bond device
        bonds = host.getBonds()
        (bridge,device) = host.removeBond(bonds[0], dhcp=True, management=True)

        # Give it 20 seconds to do DHCP etc
        time.sleep(20)

        # Check we can still see the host etc...
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        # Now try and set up the second slave interface as mgmt interface
        intf = newpifs[1]
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (intf))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (intf))
        except:
            pass
        time.sleep(120)

        newip = host.execdom0("xe host-param-get uuid=%s param-name=address" %
                              (host.getMyHostUUID())).strip()
        oldip = host.getIP()
        if not newip:
            raise xenrt.XRTError("Host IP address is blank after reconfiguring"
                                 "slave interface as management interface")
        elif newip == oldip:
            raise xenrt.XRTError("Host IP address is unchanged after reconfiguring"
                                 "slave interface as management interface")
        host.machine.ipaddr = newip

        # Check it worked correctly
        network = host.genParamGet("pif", intf, "network-uuid")
        bridge = host.genParamGet("network", network, "bridge")
        host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        # It worked, so set it back
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (newpifs[0]))
        except:
            pass
        time.sleep(120)

        host.machine.ipaddr = oldip

class TC8124(MngOnExBondSlave):
    """Verify that an interface used as a bond slave can be used as a management interface"""
    
class TC15627(MngOnExBondSlave):
    """Verify that an interface used as a bond slave (3 NICs) can be used as a management interface"""
    NUMBER_NICS = 3

class TC15628(MngOnExBondSlave):
    """Verify that an interface used as a bond slave (4 NICs) can be used as a management interface"""
    NUMBER_NICS = 4

class MngOnExLacpSlave(MngOnExBondSlave):
    """Interface used as a LACP bond slave can be used as a management interface"""
    BOND_MODE = "lacp"

# TC-8195 Aggregate Bonds

class _AggregateBondTest(xenrt.TestCase):
    """Base class for bond tests"""

    DIRECT_GUESTS = 1 # Number of guests to put directly on the bond
    VLAN_GUESTS = 0 # Number of guests to put on VLANs
    USE_DOM0 = False # Use dom0 in the test
    BOND_MODE = None
    NICS_IN_BOND = 2 # From Tampa onwards we support 4 NICs in a bond
    
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.host = None
        self.guests = []
        self.nics = []
        self.macs = []
        self.gmacs = {}
        self.gmachashes = {}
        self.bondDevice = None

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Set up the network topology on the host
        # We have to use NPRI for the bond, otherwise dom0 won't use it to get
        # to the network test peer
        bondMode = ""
        if self.BOND_MODE:
            bondMode = self.BOND_MODE
        netConfig = """<NETWORK>
  <PHYSICAL network="NSEC">
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NPRI" bond-mode="%s">
    """ % bondMode
        for i in range(self.NICS_IN_BOND):
            netConfig += """<NIC/> 
    """
        netConfig += """<VMS/>
""" 
        if self.USE_DOM0:
            netConfig += """    <STORAGE/>
"""
        for i in range(self.VLAN_GUESTS):
            netConfig += "    <VLAN network=\"VR0%u\"/>\n" % (i+1)
        netConfig += """  </PHYSICAL>
</NETWORK>"""

        self.host.createNetworkTopology(netConfig)

        if xenrt.TEC().lookup("WORKAROUND_CA90457", False, boolean=True):
            # Manually reset the rebalance interval to 10s
            bond = self.host.getBonds()[0]
            pif = self.host.parseListForUUID("pif-list", "bond-master-of", bond)
            self.host.genParamSet("pif", pif, "other-config", "10000", pkey="bond-rebalance-interval")
            self.host.reboot() # We only need to replug the PIF, but we don't know whats using it
                               # so this is simpler

        # Install VMs to the appropriate places
        for i in range(self.DIRECT_GUESTS):
            g = self.host.createGenericLinuxGuest()
            self.getLogsFrom(g)
            self.uninstallOnCleanup(g)
            g.installIperf()
            self.guests.append(g)
        for i in range(self.VLAN_GUESTS):            
            # Find the bridge
            netNameStart = "VLAN VR0%u on NPRI" % (i+1)
            networks = self.host.minimalList("network-list",params="name-label")
            network = None
            for n in networks:
                if n.startswith(netNameStart):
                    network = n
                    break
            if not network:
                raise xenrt.XRTError("Unable to find VLAN network")
            # Find the actual bridge device
            netuuid = self.host.minimalList("network-list", 
                                            args="name-label=\"%s\"" % 
                                                 (network))[0]
            bridge = self.host.genParamGet("network", netuuid, "bridge")
            g = self.host.createGenericLinuxGuest(bridge=bridge)
            self.uninstallOnCleanup(g)
            g.installIperf()
            self.guests.append(g)
        if self.USE_DOM0:
            # Drop the binary onto dom0 (we don't have a compiler built in)
            self.host.execdom0("wget '%s/iperf.tgz' -O /tmp/iperf.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
            self.host.execdom0("tar -zxf /tmp/iperf.tgz -C /tmp")

        # Get actual NICs
        bond = self.host.getBonds()[0]
        self.bondUUID = bond
        slaves = self.host.genParamGet("bond", bond, "slaves").split("; ")
        for s in slaves:
            device = self.host.genParamGet("pif", s, "device")
            self.nics.append(device)
        # Figure out the bond device
        master = self.host.genParamGet("bond", bond, "master")
        self.bondDevice = self.host.genParamGet("pif", master, "device")

        # Get MAC addresses
        for g in self.guests:
            vifs = g.getVIFs()
            self.macs.append(vifs.values()[0][0])
            self.gmacs[g] = vifs.values()[0][0]
        if self.USE_DOM0:
            # Get the MAC associated with the bridge in dom0
            pif = self.host.genParamGet("bond", bond, "master")
            mac = self.host.genParamGet("pif", pif, "MAC")
            self.macs.append(mac)
            self.gmacs[self.host] = mac
            

class _FailoverBondTest(_AggregateBondTest):
    """Base class for bond failover TCs"""

    PERMUTATIONS = 4

    def disablePath(self, host, mac):
        
        # Disable the port on switch side
        host.disableNetPort(mac)
        
    def enablePath(self, host, mac):
        
        # Enable the port on switch side
        host.enableNetPort(mac)

    def checkFailureOfOnePath(self, host, mac, total_paths):


        # Fail the given NIC, verify reachability immediately after the 
        # failure, and 2 minutes later.
        
        self.disablePath(host, mac)
        #time.sleep(2)
        #self.check(total_paths - 1)
        time.sleep(120)
        self.check(total_paths - 1)
        
        # Restore the NIC, verify reachability immediately after the 
        # failure, and 2 minutes later.
        self.enablePath(host, mac)
        #self.check(total_paths - 1)
        time.sleep(60)
        try:
            self.check(total_paths)
        except Exception, e:
            xenrt.TEC().logverbose("Check failed after 60s. (%s)" % (e))
        time.sleep(60)
        try:
            self.check(total_paths)
        except Exception, e:
            xenrt.TEC().logverbose("Check failed after 120s. (%s)" % (e))
        time.sleep(60)
        try:
            self.check(total_paths)
        except Exception, e:
            xenrt.TEC().logverbose("Check failed after 180s. (%s)" % (e))
        time.sleep(60)
        try:
            self.check(total_paths)
        except Exception, e:
            xenrt.TEC().logverbose("Check failed after 240s. (%s)" % (e))
        time.sleep(60)
        xenrt.TEC().logverbose("Checking after 300s.")
        self.check(total_paths)
        
        return

    def checkPathsAfterRandomFailure(self, host, macs, total_paths, total_permutation):
        
        # We need to simulate random UNPLUG and PLUG of NICs.
        permutations = tuple(itertools.permutations(macs))
        expected_paths = total_paths
        macs_disabled = set([])

        for i in range(total_permutation):
            step("Check paths after random failure - permutation %s" % i)
            p1 = random.choice(permutations)
            p2 = random.choice(permutations)
            p = []
            for i in zip(p1,p2):
                p.extend(i)
            for mac in p:
                if expected_paths != 0:
                    self.check(expected_paths)
                if mac in macs_disabled:
                    self.enablePath(host, mac)
                    xenrt.sleep(100)
                    expected_paths += 1
                    self.check(expected_paths)
                    macs_disabled.remove(mac)
                elif len(macs_disabled) != total_paths - 1:
                        self.disablePath(host, mac)
                        xenrt.sleep(100)
                        expected_paths -= 1
                        self.check(expected_paths)
                        macs_disabled.add(mac)
        return
        
    def run(self, arglist=None):
        # Get the VMs generating some traffic
        step('Start netperf loads on the guests')
        for g in self.guests:
            g.startWorkloads(["LinuxNetperfRX", "LinuxNetperfTX"])
        if self.USE_DOM0:
            # TODO: Start iperf/netperf
            pass

        step('Get the NIC MACs')
        
        pifs = [self.host.parseListForUUID("pif-list", "device", nic)
                for nic in self.nics]
        macs = [self.host.genParamGet("pif", pif, "MAC") 
                for pif in pifs]
        
        # Stores mac and interface as key and value pair
        self.eth = {}
        for mac, eth in zip(macs, self.nics):
            self.eth[mac]=eth
 
        log("List of interfaces : %s" % str(self.eth))
        
        try:
            total_paths = len(macs)
            assert (total_paths == self.NICS_IN_BOND)
            for mac in macs:
                step('Check failure of one path (MAC %s)' % mac)
                self.checkFailureOfOnePath(self.host, mac, total_paths)
                
            self.checkPathsAfterRandomFailure(self.host, macs, total_paths, self.PERMUTATIONS)
            
        finally:
            # Enable the ports
            for mac in macs:
                self.enablePath(self.host, mac)


    def check(self, paths):
        # Check that the bond shows what we expect
        info = self.host.getBondInfo(self.bondDevice)
        slaves = info[1]
        activePaths = 0
        for s in slaves.keys():
            if slaves[s]['status'] == "up":
                activePaths += 1
        if activePaths != paths:
            raise xenrt.XRTError("Expecting %u paths up, found %u" % 
                                 (paths, activePaths))
        # Verify that all VMs / dom0 are reachable
        if self.USE_DOM0:
            self.host.checkReachable()
            # Todo net/iperf on dom0
        for g in self.guests:
            g.checkReachable()
            g.check()
            rc = g.execguest("ps -ef | grep [n]etperf", retval="code")
            if rc > 0:
                raise xenrt.XRTFailure("netperf no longer running on %s" % 
                                       (g.getName()))

class _TCFailoverMultinic(_FailoverBondTest):
    """Bonded NIC failover with single VM on a bond"""
    
    DIRECT_GUESTS = 1
    NICS_IN_BOND = None
    
    def prepare(self, arglist=None):
        
        #The prepare method of _AggregateBond class requires the host to have an NSEC NIC to make it as a management interface.
        #We do not use it because we want this test case to work on hosts which do not have NSEC NICs.
        
        self.host = self.getDefaultHost()
        
        log('Create a Linux Guest on the bond')
        g = self.host.createGenericLinuxGuest()
        self.guests.append(g)
        
        log('Get the NICs of the bond')
        bond = self.host.getBonds()[0]
        slaves = self.host.genParamGet("bond", bond, "slaves").split("; ")
        for s in slaves:
            device = self.host.genParamGet("pif", s, "device")
            self.nics.append(device)
            
        log('Get the device of the bond')
        master = self.host.genParamGet("bond", bond, "master")
        self.bondDevice = self.host.genParamGet("pif", master, "device")
        
class TCFailover8nic(_TCFailoverMultinic):
    """Bonded NIC failover with single VM for 8 NIC lacp bond"""
    # jira id TC-18554
    DIRECT_GUESTS = 1
    BOND_MODE = 'lacp'
    NICS_IN_BOND = 8
    
class TCFailover24nic(_TCFailoverMultinic):
    """Bonded NIC failover with single VM for 24 NIC lacp bond"""
    # jira id TC-18594
    DIRECT_GUESTS = 1
    BOND_MODE = 'lacp'
    NICS_IN_BOND = 24
    
class TCFailoverEth(_TCFailoverMultinic):
    """Bonded NIC failover with single VM for 8 NIC lacp bond using unplug device (disabling from host side)"""
    # jira id TC-18711
    DIRECT_GUESTS = 1
    BOND_MODE = 'lacp'
    NICS_IN_BOND = 8
    
    def disablePath(self, host, mac):
        
        # Disable the interface on host side
        host.execdom0("ifconfig %s down" % (self.eth[mac]))
        
    def enablePath(self, host, mac):
        
        #Enable the interface from host side
        host.execdom0("ifconfig %s up" % (self.eth[mac]))
    
class TCFailoverExistingBonds(_FailoverBondTest):
    """Bonded NIC failover with single VM for more than one bond"""
    bondsinfo = []
    
    def prepare(self, arglist=None):
        
        self.host = self.getDefaultHost()
        
        for bond in self.host.getBonds():
            
            master = self.host.genParamGet("bond", bond, "master")
            device = self.host.genParamGet("pif", master, "device")
            
            step("Retrieving bridge of %s" % (device))
            network = self.host.genParamGet("pif", master, "network-uuid")
            bridge = self.host.genParamGet("network", network, "bridge")
            
            step('Retrieving the NICs in %s' % (device))
            slaves = self.host.genParamGet("bond", bond, "slaves").split("; ")
            nics = [self.host.genParamGet("pif", s, "device") for s in slaves]
            
            step('Creating a Linux Guest on %s' % (device))
            guest = self.host.createGenericLinuxGuest(bridge=bridge)
            
            self.bondsinfo.append((device,nics,guest))
            log(self.bondsinfo)

    def run(self, arglist=None):
        
        for device, nics, guest in self.bondsinfo:
            self.bondDevice = device
            self.guests.append(guest)
            self.nics = nics
            
            step("Checking failover for %s" %(self.bondDevice))
            _FailoverBondTest.run(self)
            
            del self.guests[:]
            del self.nics[:]

class TC8200(_FailoverBondTest):
    """Bonded NIC failover with single VM"""
    DIRECT_GUESTS = 1

class TC15930(TC8200):
    """Bonded NIC failover with single VM (4 NICs in the Bond)"""
    NICS_IN_BOND = 4

class TC12451(TC8200):
    """Bonded NIC (active/passive) failover with single VM"""
    BOND_MODE = "active-backup"

class TC15933(TC12451):
    """Bonded NIC (active/passive) failover with single VM (4 NICs in the bond)"""
    NICS_IN_BOND = 4

class TC8202(_FailoverBondTest):
    """Bonded NIC failover with three VMs and two VLANs"""
    DIRECT_GUESTS = 1
    VLAN_GUESTS = 2

class TC15931(TC8202):
    """Bonded NIC failover with three VMs and two VLANs (4 NICs in the bond)"""
    NICS_IN_BOND = 4

class TC12452(TC8202):
    """Bonded NIC (active/passive) failover with three VMs and two VLANs"""
    BOND_MODE = "active-backup"

class TC15934(TC12452):
    """Bonded NIC (active/passive) failover with three VMs and two VLANs (4 NICs in the bond)"""
    NICS_IN_BOND = 4

class TC8210(_FailoverBondTest):
    """Bonded NIC failover with two VMs and dom0"""
    DIRECT_GUESTS = 2
    USE_DOM0 = True

class TC15932(TC8210):
    """Bonded NIC failover with two VMs and dom0 (4 NICs in the bond)"""
    DIRECT_GUESTS = 2
    USE_DOM0 = True
    NICS_IN_BOND = 4

class TC17718(xenrt.TestCase):
    """Check packet loss during bond failover"""
    THRESHOLD = 10 # The number of pings declared acceptable to lose
    THRESHOLD_PERCENT = 6 # The percentage of pings acceptable to lose
    def prepare(self, arglist):
        # Set up a host with a bond of 2 NICs
        self.host = self.getDefaultHost()
        # Find 2 NSEC NICs
        nics = self.host.listSecondaryNICs(network="NSEC")
        if len(nics) < 2:
            raise xenrt.XRTError("Need 2 NSEC NICs")
        nics = nics[0:2]
        pifs = map(lambda n: self.host.getNICPIF(n), nics)
        self.macs = map(lambda p: self.host.genParamGet("pif", p, "MAC"), pifs)
        bridge, bondDevice = self.host.createBond(pifs)
        self.bond = self.host.genParamGet("pif", pifs[0], "bond-slave-of")
                
        # Set up a VM running on the bond that we will ping
        self.guest = self.host.createGenericLinuxGuest(bridge=bridge)
        self.uninstallOnCleanup(self.guest)
        self.tempdir = xenrt.TempDirectory().path()

    def startPing(self):
        """Starts ping monitoring the VM"""
        xenrt.command("[ -e %s/ping.pid ] && kill -s INT `cat %s/ping.pid`; rm -f %s/ping.pid" % (self.tempdir, self.tempdir, self.tempdir))
        xenrt.command("ping -q %s > %s/ping.log 2>&1 & echo $! > %s/ping.pid" % (self.guest.getIP(), self.tempdir, self.tempdir))

    def stopPing(self):
        """Stops ping monitoring the VM and returns the number of lost pings"""
        xenrt.command("kill -s INT `cat %s/ping.pid`; rm -f %s/ping.pid" % (self.tempdir, self.tempdir))
        data = xenrt.command("cat %s/ping.log" % (self.tempdir))
        for line in data.splitlines():
            m = re.findall("(\d+)",line)
            txd = int(m[0])
            rxd = int(m[1])
            if len(m) == 4:      #if there were no duplicate packets
                packetlossPercent = m[2]
            else:
                packetlossPercent = m[3]
            return (txd, rxd, packetlossPercent)
        raise xenrt.XRTError("Unable to parse ping output")

    def run(self, arglist):
        delays = [1, 2, 5, 10]
        for d in delays:
            self.runSubcase("failCycle", (d), "FailoverTest", str(d))
            time.sleep(15)

    def failCycle(self, failSecondDelay):
        self.startPing()
        try:
            # Fail first link
            self.host.disableNetPort(self.macs[0])
            time.sleep(1)
            # Recover first link
            self.host.enableNetPort(self.macs[0])
            time.sleep(failSecondDelay)
            # Fail second link
            self.host.disableNetPort(self.macs[1])
            time.sleep(1)
            # Recover second link
            self.host.enableNetPort(self.macs[1])
        except:
            # Recover any links that might be down for the next test
            xenrt.TEC().logverbose("Enabilng all ports and sleeping 1 minute")
            for m in self.macs: self.host.enableNetPort(m)
            time.sleep(60)

        # Allow time for things to settle and review packet loss
        time.sleep(60)
        
        #If the pings are more than 100, tolerate a percent packet loss of THRESHOLD_PERCENT
        #otherwise tolerate packet loss of self.THRESHOLD at max
        transmitted, received, packetlossPercent = self.stopPing()
        packetloss = transmitted - received
        if transmitted > 100 and packetlossPercent > self.THRESHOLD_PERCENT:
            raise xenrt.XRTFailure("Lost > %d% pings during bond failover cycle" % (self.THRESHOLD_PERCENT))
        elif packetloss > self.THRESHOLD:
            raise xenrt.XRTFailure("Lost > %d pings during bond failover cycle" % (self.THRESHOLD))

    def postRun(self):
        try:
            self.guest.shutdown(force=True)
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass
        try:
            self.host.removeBond(self.bond)
        except:
            pass

class TC12519(_AggregateBondTest):
    """Traffic should only be sent through the active slave of an active/passive bond"""
    BOND_MODE = "active-backup"
    DIRECT_GUESTS = 2

    def getSentPacketsThruInterface(self, dev):
        info = self.host.getNetDevInfo(dev)
        return int(info["tx_packets"])

    def run(self, arglist=None):
        # Find the active bond slave
        info, x = self.host.getBondInfo(self.bondDevice)
        slaves = info["slaves"]
        activeSlave = info["active_slave"]

        # Record the current number of transmitted packets
        sentPacketsBefore = {}
        for slave in slaves:
            sentPacketsBefore[slave] = self.getSentPacketsThruInterface(slave)

        # Get the VMs generating some traffic
        for g in self.guests:
            g.startWorkloads(["LinuxNetperfRX", "LinuxNetperfTX"])

        # Sleep for a while
        time.sleep(30)

        # Record the current number of transmitted packets
        sentPacketsAfter = {}
        for slave in slaves:
            sentPackets = self.getSentPacketsThruInterface(slave)
            if slave == activeSlave and sentPackets - sentPacketsBefore[slave] == 0:
                raise xenrt.XRTFailure("No packets were sent through active slave (%s)" % slave)
            
            # set threshold to 20 packets...as we know a small numbers can get transmitted (CA-83712)
            val = sentPackets - sentPacketsBefore[slave]
            if slave != activeSlave and val > 20:
                raise xenrt.XRTFailure("Packets were sent through inactive slave (%s)" % slave, data="%u packets transmitted" % val)

class _BondBalance(_AggregateBondTest):
    """Base class for bonding balancing TCs"""
    LACP_HASH_ALG = None

    def __init__(self, tcid=None):
        _AggregateBondTest.__init__(self, tcid=tcid)
        self.counts = {}
        self.netpeer = None
        self.lacpHashAlg = None

    def prepare(self, arglist=None):
        step("Preparing %d guests on bond and %d guests on vlan on top of bond" % (self.DIRECT_GUESTS, self.VLAN_GUESTS))
        _AggregateBondTest.prepare(self, arglist=arglist)
        self.netpeer = xenrt.NetworkTestPeer()

        if self.BOND_MODE == "lacp":
            if self.LACP_HASH_ALG:
                # We've been told to use a specific one, so set it
                self.host.genParamSet("bond", self.bondUUID, "properties:hashing_algorithm", self.LACP_HASH_ALG)

            self.lacpHashAlg = self.host.genParamGet("bond", self.bondUUID, "properties", "hashing_algorithm")
            if not self.lacpHashAlg in ["src_mac", "tcpudp_ports"]:
                raise xenrt.XRTError("Unable to test LACP %s hashing algorithm" % (self.lacpHashAlg))

        # Check we don't have any colliding macs
        for g,m in self.gmacs.items():
            hash = self.host.calculateBondingHash(m)
            collisions = [cg for cg,h in self.gmachashes.items() if h == hash]
            if len(collisions) > 0:
                # We have a collision - need to change MAC to avoid it
                if g == self.host:
                    # It's dom0 thats colliding, we can't change dom0s MAC so
                    # change the guest we've collided with, and sort the hashes
                    # out in gmachashes
                    self.gmachashes[g] = hash
                    g = collisions[0]
                    del self.gmachashes[g]

                xenrt.TEC().logverbose("Found MAC hash collision, changing MAC...")
                g.preCloneTailor() # Avoid udev related problems
                g.shutdown()
                # Find a MAC to use
                nic, bridge, _, ip = g.vifs[0]
                # Look up the bridge and get the VLAN id
                nwuuid = self.host.getNetworkUUID(bridge)
                vlan = int(self.host.parseListForOtherParam("pif-list", "network-uuid", nwuuid, "VLAN"))
                newMac = None
                while newMac is None:
                    newMac = xenrt.randomMAC()
                    newHash = self.host.calculateBondingHash(newMac, vlan)
                    if newHash in self.gmachashes.values():
                        newMac = None
                g.vifs[0] = (nic, bridge, newMac, ip)
                g.recreateVIFs()
                hash = newHash
                self.gmacs[g] = newMac
                g.start()

            xenrt.TEC().logverbose("MAC hash %s -> %s" % (hash, m))
            self.gmachashes[g] = hash
        
        log("gmacs: %s" % str(self.gmacs))
        log("gmachashes: %s" % str(self.gmachashes))

    def run(self, arglist=None):
        peerips = []
        # Add them in the right order
        step("Start iperf traffic from guests to their respective netpeers") 
        for i in range(self.DIRECT_GUESTS):
            peerips.append(self.netpeer.getAddress())
        for i in range(self.VLAN_GUESTS):
            peerips.append(self.netpeer.getAddress( \
                                        self.host.getVLAN("VR0%u" % (i+1))[0]))
        if self.USE_DOM0:
            peerips.append(self.netpeer.getAddress())

        # Set up each VM/dom0 to generate 50Mbit of traffic
        i = 0
        for g in self.guests:
            g.execcmd("iperf -c %s -u -b 50M -t 100000 > /tmp/iperf.log 2>&1 "
                      "< /dev/null &" % (peerips[i]))
            i += 1
        if self.USE_DOM0:
            self.host.execcmd("/tmp/iperf/iperf -c %s -u -b 50M -t 100000 > "
                              "/tmp/iperf.log 2>&1 < /dev/null &" % (peerips[i]))

        # Give it 10 minutes (this avoids the initial 10 seconds where we might
        # be unbalanced having an effect, and also is about the interval real
        # world customers are likely to care about), checking balance after 30
        # seconds to make sure things are right instantaneously
        step("Start capturing the packets on host")
        self.startCounts()
        time.sleep(30)
        
        step("Check if the bond traffic is balanced based on bond info")
        sourceCount = self.DIRECT_GUESTS + self.VLAN_GUESTS
        if self.USE_DOM0: sourceCount += 1
        log("sourceCount: %d" % sourceCount)
        self.checkBondBalance((sourceCount / 2) + 1,sourceCount)
        time.sleep(570)

        step("Stop capturing and retrieve packet counts")
        counts = self.stopAndGetCounts()
        log("counts: %s" % str(counts))

        step("Check if the bond traffic was balanced based on packet counts")
        self.checkBalanced(counts)

        step("Reducing the number of guest traffic sources by 4")
        ignoreMACs = []
        for i in range(4):
            g = self.guests[i]
            g.execcmd("killall iperf", level=xenrt.RC_OK)
            ignoreMACs.append(self.gmacs[g])
        time.sleep(2)
        for i in range(4):
            self.guests[i].execcmd("cat /tmp/iperf.log")
        sourceCount -= 4
        log("sourceCount: %d" % sourceCount)

        step("Start capturing the packets on host")
        # Check again, but only for 5 minutes this time
        self.startCounts()
        time.sleep(30)
        
        step("Check if the bond traffic is balanced based on bond info")
        self.checkBondBalance((sourceCount / 2) + 1,sourceCount,ignoreMACs)
        time.sleep(270)
        
        step("Stop capturing and retrieve packet counts")
        counts = self.stopAndGetCounts()
        log("counts: %s" % str(counts))

        step("Check if the bond traffic was balanced based on packet counts")
        self.checkBalanced(counts)

    def postRun(self):
        # Stop any remaining iperf processes
        for g in self.guests:
            try:
                g.execcmd("killall iperf", level=xenrt.RC_OK)
                time.sleep(2)
                g.execcmd("cat /tmp/iperf.log")
            except:
                pass
        if self.USE_DOM0:
            try:
                self.host.execcmd("killall iperf")
                time.sleep(2)
                self.host.execcmd("cat /tmp/iperf.log")
            except:
                pass
        # Release the test peer
        if self.netpeer:
            self.netpeer.release()

    def startCounts(self):
        for nic in self.nics:
            for mac in self.macs:
                fn = "%s/%s_%s.txt" % (xenrt.TEC().lookup("LOCAL_BASE"),nic,mac)
                self.host.execdom0("tcpdump -w /dev/null -i %s \"ether src %s\""
                                   " > %s 2>&1 < /dev/null &" % (nic, mac, fn))

    def stopAndGetCounts(self):
        #Returns the counts as a dictionary with (hostEth,guestMAC) as the key
        #packet count as the value. e.g {(eth0,82:36:77:86:8a:3f):1234 ...}
        
        self.host.execdom0("killall tcpdump")
        time.sleep(5) # Allow 5s for the tcpdumps to actually stop
        counts = {}
        for nic in self.nics:
            for mac in self.macs:
                fn = "%s/%s_%s.txt" % (xenrt.TEC().lookup("LOCAL_BASE"),nic,mac)
                tcpdump = self.host.execdom0("cat %s" % (fn)).strip()
                # Check we didn't run out of dom0 memory
                if re.search("Cannot allocate memory", tcpdump):
                    raise xenrt.XRTError("tcpdump in dom0 failed with 'Cannot allocate memory'")
                # Parse this to get the count
                m = re.search("(\d+) packet\w* captured", tcpdump)
                counts[(nic,mac)] = int(m.group(1))

        return counts

    def checkBalanced(self, counts, ratio=1):
        # We expect 2-4 nics

        nicTotals = {}
        for nic in self.nics:
            nicTotals[nic] = 0
        for mac in self.macs:
            # Get the traffic it used on each nic and add to the totals
            for n in self.nics:
                nicTotals[n] += int(counts[(n,mac)])

        xenrt.TEC().logverbose("nicTotals: %s" % (str(nicTotals)))
        # Check the totals roughly fit the ratio we expect
        nicsRemaining = self.nics
        for nic in self.nics:
            nicsRemaining.remove(nic)
            for n in nicsRemaining:
                xenrt.TEC().logverbose("Checking balance between NICs %s and %s" % (nic, n))
                actualRatio = float(nicTotals[nic]) / \
                              float(nicTotals[n])
                if actualRatio < 1 and actualRatio != 0:
                    actualRatio = 1 / actualRatio
                difference = actualRatio - float(ratio)
                # Note that if difference is negative, then it means
                # the balancing code did a better job than we expected
                # We allow up to a 0.9 difference (this is *very* generous, but particularly with 4 NIC bonds it seems they are only about this good)
                if difference > 0.9:
                    # Get bond info so we have some debug data
                    self.host.getBondInfo(self.bondDevice)
                    raise xenrt.XRTFailure("NICs not balanced", data = "Expected ratio "
                                           "%u, actual %.2f" % (ratio, actualRatio))

    def checkBondBalance(self, maxSources, numSources, ignoreMACs=[]):
        if self.BOND_MODE == "lacp" and self.lacpHashAlg == "tcpudp_ports":
            # We don't currently actually verify the balancing here, we just assume its OK
            # and that the packet counts will identify any balancing issues problems
            return
        # Check that we've balanced groupA onto one NIC, and groupB onto the other
        (info, slaves) = self.host.getBondInfo(self.bondDevice)
        # Check this isn't a repeat of CA-25903 (if it is, wait 5s and try again)        
        if len(info['slb']) < numSources:
            xenrt.TEC().logverbose("Didn't find enough sources, retrying in 5 "
                                   "seconds (CA-25903)...")
            time.sleep(5)
            (info, slaves) = self.host.getBondInfo(self.bondDevice)
        log("info: %s" % str(info))
        log("slaves: %s" % str(slaves))
        
        # Figure out where each MAC we know about is
        eths = {}
        for guest in self.gmacs:
            if self.gmacs[guest] in ignoreMACs:
                continue
            hashid = self.gmachashes[guest]
            log("Checking MAC %s (hash %s)" % (self.gmacs[guest], hashid))
            if hashid in info['slb']:
                eth = info['slb'][hashid]
                if eth in eths:
                    eths[eth].append(guest)
                else:
                    eths[eth] = [guest]
        log("eths: %s" % str(eths))

        # Check the two lists match one way round or the other
        ifs = eths.keys()
        if len(ifs) < len(self.nics):
            raise xenrt.XRTFailure("One or more interfaces not carrying "
                                   "our traffic",
                                   str(ifs))
        nicSourceCounts = {}
        for intf in ifs:
            nicSourceCounts[intf] = len(eths[intf])
        log("niSourceCounts: %s" % str(nicSourceCounts))
        if sum(nicSourceCounts.values()) != numSources:
            raise xenrt.XRTError("Found %u sources, expecting %u" %
                                 (sum(nicSourceCounts.values()), numSources))
        
        if len(ifs) > 2:        
            raise xenrt.XRTError("Load balancing verification is NOT yet implemented for more than 2 slaves")
        
        if self.host.special['Network subsystem type'] == "linux":
            biggest = max(nicSourceCounts.values())
            smallest = min(nicSourceCounts.values())
            if biggest > maxSources:
                raise xenrt.XRTFailure("Balancing outside allowed range",
                                    data="Allowed %u:%u, found %u:%u" %
                                    (maxSources, (numSources-maxSources),
                                        biggest, smallest))
        else:
            iftraffic0 = info['load'][ifs[0]]
            iftraffic1=  info['load'][ifs[1]]
            if iftraffic0 < 100 and iftraffic1 < 100 :
                raise xenrt.XRTError("Not enough traffic across interface to verify Balalncing .%s load = %s,%s load = %s" %(ifs[0],iftraffic0,ifs[1],iftraffic1))
            
            if iftraffic0 >= iftraffic1 :
                balanceratio = float(iftraffic1)/float(iftraffic0)
            else :
                balanceratio = float(iftraffic0)/float(iftraffic1)            
            
            # If there exist a even number of hash distribution across the NICs then we expect traffic to be balanced at least for 6:4 accuracy
            # otherwise we expect atlest 4:2 accuracy  
            if info['slb'].values().count(info['slaves'][0]) % 2 == 0 and info['slb'].values().count(info['slaves'][1]) % 2 == 0:
                if not (0.66 <= balanceratio <= 1.0):
                    raise xenrt.XRTFailure("Load is not balanced across nics . Balance ratio = %s .%s load = %s,%s load = %s" \
                                           %(balanceratio,ifs[0],iftraffic0,ifs[1],iftraffic1))
            elif not (0.50 <= balanceratio <= 1.0):
                    raise xenrt.XRTFailure("Load is not balanced across nics . Balance ratio = %s .%s load = %s,%s load = %s" \
                                           %(balanceratio,ifs[0],iftraffic0,ifs[1],iftraffic1))
            log("Load is BALANCED with ratio of %s " %balanceratio)
            

class TC8310(_BondBalance):
    """Verify bond balancing works as expected"""
    DIRECT_GUESTS = 6
    VLAN_GUESTS = 3
    USE_DOM0 = True

class TC17755(TC8310):
    """Verify bond balancing works on LACP src_mac as expected"""
    BOND_MODE = "lacp"
    LACP_HASH_ALG = "src_mac"
    DIRECT_GUESTS = 7
    USE_DOM0 = False

class TC17756(TC8310):
    """Verify bond balancing works on LACP tcpudp_ports as expected"""
    BOND_MODE = "lacp"
    LACP_HASH_ALG = "tcpudp_ports"
    DIRECT_GUESTS = 7
    USE_DOM0 = False

class TC18038(TC8310):
    """Verify bond balancing works as expected (4 NIC bonds)"""
    NICS_IN_BOND = 4
    DIRECT_GUESTS = 8
    VLAN_GUESTS = 3

class TC18039(TC17755):
    """Verify bond balancing works on LACP src_mac as expected (4 NIC bonds)"""
    NICS_IN_BOND = 4
    DIRECT_GUESTS = 9
    VLAN_GUESTS = 3

class TC18040(TC17756):
    """Verify bond balancing works on LACP tcpudp_ports as expected (4 NIC bonds)"""
    NICS_IN_BOND = 4
    DIRECT_GUESTS = 9
    VLAN_GUESTS = 3

class TC8224(xenrt.TestCase):
    """Regression test for CA-22465 (wrong source MAC on bond)"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.host = None
        self.guest1 = None
        self.guest2 = None
        self.nics = []
        self.dom0macs = []
        self.workdir = None

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Set up the host with a bond on NSEC used for VMs
        netConfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <VMS/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
</NETWORK>"""
        self.host.createNetworkTopology(netConfig)

        # Install 2 VMs
        self.guest1 = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest1)
        self.guest2 = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest2)

        # Figure out which NICs are on the bond
        bond = self.host.getBonds()[0]
        slaves = self.host.genParamGet("bond", bond, "slaves").split("; ")
        for s in slaves:
            device = self.host.genParamGet("pif", s, "device")
            mac = self.host.genParamGet("pif", s, "MAC")
            self.nics.append(device)
            self.dom0macs.append(mac)

        # Get a workdir
        self.workdir = self.host.hostTempDir()

    def run(self, arglist=None):
        # Run a netperf workload on the VMs (just to generate some traffic)
        self.guest1.startWorkloads(["LinuxNetperfTX"])
        self.guest2.startWorkloads(["LinuxNetperfTX"])

        # Run tcpdump on dom0 to count the number of packets going out each
        # NIC with the source MAC address of the VMs. This should be a large
        # number...
        vifs = self.guest1.getVIFs()
        gmac1 = vifs.values()[0][0]
        vifs = self.guest2.getVIFs()
        gmac2 = vifs.values()[0][0]
        for nic in self.nics:
            fn = "%s/%s_guests" % (self.workdir, nic)
            self.host.execdom0("tcpdump -w /dev/null -i %s \"ether src %s or "
                               "ether src %s\" > %s 2>&1 < /dev/null &" % 
                               (nic, gmac1, gmac2, fn))

        # Also count the number of packets going out each NIC with the source
        # MAC address equal to either of the NIC MAC addresses. This should be
        # 0 as we aren't using the bond in dom0...
        for mac in self.dom0macs:
            for nic in self.nics:
                fn = "%s/%s_%s" % (self.workdir, nic, mac)
                self.host.execdom0("tcpdump -w /dev/null -i %s \"ether src %s\""
                                   " > %s 2>&1 < /dev/null &" % (nic, mac, fn))

        # Give it 1 minute and verify the packet counts
        time.sleep(60)
        self.host.execdom0("killall tcpdump")

        # Guest MAC counts
        gcount = 0
        for nic in self.nics:
            fn = "%s/%s_guests" % (self.workdir, nic)
            tcpdump = self.host.execdom0("cat %s" % (fn)).strip()
            # Parse this to get the count
            m = re.search("(\d+) packets captured", tcpdump)
            gcount += int(m.group(1))
        # Host MAC counts
        hcount = 0
        for mac in self.dom0macs:
            for nic in self.nics:
                fn = "%s/%s_%s" % (self.workdir, nic, mac)
                tcpdump = self.host.execdom0("cat %s" % (fn)).strip()
                # Parse this to get the count
                m = re.search("(\d+) packets captured", tcpdump)
                hcount += int(m.group(1))

        xenrt.TEC().logverbose("%u packets with guest MAC as source, %u with "
                               "a bond slave MAC as source" % (gcount, hcount))

        # If we have a large hcount, then it's CA-22465
        if hcount > 5000:
            raise xenrt.XRTFailure("CA-22465 Packets on bond being transmitted "
                                   "with bond slave MAC addresses")
        elif gcount < 40000:
            # Not enough guest packets
            raise xenrt.XRTFailure("Packets on bond being transmitted with "
                                   "incorrect (unknown) MAC addresses")

class TC8323(xenrt.TestCase):
    """Verify pif-plug of a VLAN on a bond doesn't cause connectivity loss"""

    def prepare(self, arglist=None):
        # Get the host
        self.host = self.getDefaultHost()
        # Give it the intial (no VLAN) configuration
        netConfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
</NETWORK>"""
        self.host.createNetworkTopology(netConfig)
        # Find the bond UUID
        self.bond = self.host.getBonds()[0]

    def run(self, arglist=None):
        # Start a ping going
        self.host.execdom0("ping %s > /tmp/pinglog 2>&1 < /dev/null &" %
                           (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")))

        # Get the current count of link down messages
        beforeCount = int(self.host.execdom0("dmesg | grep 'link status "
                          "definitely down for interface' | wc -l"))

        # Add and plug the VLAN
        vlans = self.host.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]
        pif = self.host.genParamGet("bond", self.bond, "master")
        nic = self.host.genParamGet("pif", pif, "device")
        vbridge = self.host.createNetwork()
        self.host.createVLAN(vlan, vbridge, nic)
        self.host.checkVLAN(vlan, nic)

        # Wait 1 minute
        time.sleep(60)
        # Check for any lost pings
        self.host.execdom0("killall -s SIGINT ping")
        data = self.host.execdom0("cat /tmp/pinglog")
        m = re.search(", (\d+)% packet loss, time", data)
        if not m:
            raise xenrt.XRTError("Unable to parse ping output")
        #It is acceptable to loose up to 5% packets in 60+ packets
        if int(m.group(1)) >=5:
            raise xenrt.XRTFailure("CA-23680 Ping across bond failed while "
                                   "adding new VLAN")

        # Get the new count of link down messages
        afterCount = int(self.host.execdom0("dmesg | grep 'link status "
                         "definitely down for interface' | wc -l"))

        if afterCount > beforeCount:
            raise xenrt.XRTFailure("CA-23680 dmesg indicates bond was taken "
                                   "down when adding new VLAN")

class TC8570(xenrt.TestCase):
    """A bond brought up from cold should not have a delay"""

    # This test requires that a non-management bond is configured with
    # static IP addressing.

    TOPOLOGY = """<NETWORK>
        <PHYSICAL network="NPRI">
          <NIC/>
          <NIC/>
          <STORAGE mode="static"/>
        </PHYSICAL>
        <PHYSICAL network="NSEC">
          <NIC/>
          <MANAGEMENT mode="static"/>
        </PHYSICAL>
      </NETWORK>"""

    def doPing(self):
        data = self.host.execdom0("ping -c 3 -w 2 %s | cat" % (self.pingable))
        r = re.search(r"(\d+) received,", data)
        if not r:
            raise xenrt.XRTError("Could not parse ping output")
        if r.group(1) == "0":
            return False
        return True

    def prepare(self, arglist):

        self.toreplug = None
        self.host = self.getDefaultHost()
        self.host.createNetworkTopology(self.TOPOLOGY)
        self.host.checkNetworkTopology(self.TOPOLOGY)

        # Find a suitable bond
        self.pif = None
        bondpifs = self.host.minimalList("bond-list", "master")
        for pif in bondpifs:
            if self.host.genParamGet("pif", pif, "IP-configuration-mode") \
                   != "Static":
                continue
            if self.host.genParamGet("pif", pif, "management") \
                   != "false":
                continue
            self.pif = pif
            break
        if not self.pif:
            raise xenrt.XRTError("No suitable bond found")

        # Find something pingable on the subnet to which the bond is attached
        self.pingable = None
        ip = self.host.genParamGet("pif", self.pif, "IP")
        netmask = self.host.genParamGet("pif", self.pif, "netmask")
        subnet = xenrt.calculateSubnet(ip, netmask)
        for nw in ["DEFAULT", "SECONDARY"]:
            gateway = self.host.lookup(["NETWORK_CONFIG", nw, "GATEWAY"], None)
            if gateway:
                if xenrt.util.isAddressInSubnet(gateway, subnet, netmask):
                    self.pingable = gateway
                    break
        if not self.pingable:
            raise xenrt.XRTError("Could not find a suitable pingable gateway",
                                 "PIF %s" % (self.pif))

        # Make sure the PIF is plugged and the target is pingable
        cli = self.host.getCLIInstance()
        if self.host.genParamGet("pif", self.pif, "currently-attached") == \
               "false":
            cli.execute("pif-plug", "uuid=%s" % (self.pif))
            time.sleep(60)
        if not self.doPing():
            raise xenrt.XRTError("Could not ping target before test started")
        
    def run(self, arglist):
        cli = self.host.getCLIInstance()
        
        # Unplug the PIF
        dup = self.host.genParamGet("pif", self.pif, "disallow-unplug")
        if dup == "true":
            self.host.genParamSet("pif", self.pif, "disallow-unplug", "false")
        try:
            cli.execute("pif-unplug", "uuid=%s" % (self.pif))
            self.toreplug = self.pif
        finally:
            if dup == "true":
                self.host.genParamSet("pif", self.pif, "disallow-unplug", dup)
        time.sleep(60)

        # Plug the PIF
        cli.execute("pif-plug", "uuid=%s" % (self.pif))
        self.toreplug = None

        # Verify connectivity via the bond - this assumes that the routing
        # table is now set up to route traffic for the subnet to which the
        # bond is attached via the bond. In the failure case the bond won't
        # pass traffic for 31s so packets to that subnet will be lost.
        p1 = self.doPing()
        time.sleep(60)
        p2 = self.doPing()

        if not p1 and not p2:
            raise xenrt.XRTError("Could not ping via bond even after delay")
        if not p1 and p2:
            raise xenrt.XRTFailure("Could not ping via bond after pif-plug")
        if not p2:
            raise xenrt.XRTError("Could not ping via bond after delay")

    def postRun(self):
        cli = self.host.getCLIInstance()
        if self.toreplug:
            cli.execute("pif-plug", "uuid=%s" % (self.toreplug))
        # Wait for the updelay
        time.sleep(60)

class TC12450(TC8570):
    """A bond (active/passive) brought up from cold should not have a delay"""
    TOPOLOGY = """<NETWORK>
        <PHYSICAL network="NPRI" bond-mode="active-backup">
          <NIC/>
          <NIC/>
          <STORAGE mode="static"/>
        </PHYSICAL>
        <PHYSICAL network="NSEC">
          <NIC/>
          <MANAGEMENT mode="static"/>
        </PHYSICAL>
      </NETWORK>"""

class TC12423(xenrt.TestCase):
    
    def assertInPromiscMode(self, nics):
        IFF_PROMISC = 0x100
        
        for nic in nics:
            flags = self.host.execdom0("cat /sys/class/net/%s/flags" % nic)
            
            if(int(flags, 16) & IFF_PROMISC) == 0:
                raise xenrt.XRTFailure("%s was not in promiscuous mode. Flags were: %s." % (nic, flags))
    
    def run(self, arglist=None):
    
        self.host = self.getDefaultHost()
        bonds = self.host.getBonds()

        if "vswitch" in self.host.special['Network subsystem type']:
            # if vswitch then exit.
            return
        
        if len(bonds) != 1:
            raise xenrt.XRTError("Host should only have 1 bond. Found %u." % len(bonds))
        
        nics = []
        slaves = self.host.genParamGet("bond", bonds[0], "slaves").split("; ")
        
        for s in slaves:
            nics.append(self.host.genParamGet("pif", s, "device"))
        
        if len(nics) != 2:
            raise xenrt.XRTError("Should be 2 NICs in bond. Found %u." % len(nics))
        
        bondPifUUID = self.host.parseListForUUID("pif-list", "bond-master-of", bonds[0])
        bondDevice = self.host.genParamGet("pif", bondPifUUID, "device")
        
        xenrt.TEC().logverbose("bond device is: %s" % bondDevice)

        # now check bond is attached
        if self.host.genParamGet("pif", bondPifUUID, "currently-attached") != "true":
            #raise xenrt.XRTFailure("Bond PIF is not attached: %s" %  bondPifUUID)
            cli = self.host.getCLIInstance()
            cli.execute("pif-plug", "uuid=%s" % bondPifUUID)
            
        # bring down both nics in the bond
        for nic in nics:
            self.host.execdom0("ifconfig %s down" % nic)
        
        # remove bond from bridge - we'll re-add this later.
        bondNetwork = self.host.genParamGet("pif", bondPifUUID, "network-uuid")
        bridge = self.host.genParamGet("network", bondNetwork, "bridge")
        self.host.execdom0("brctl delif %s %s" % (bridge, bondDevice))
        
        time.sleep(10)
        
        # bring up nics and bond in order which is known to set promiscuity ref-count incorrectly. 
        for nic in nics:
            self.host.execdom0("ifconfig %s up" % nic)
        self.host.execdom0("brctl addif %s %s" % (bridge, bondDevice))
        
        # check both nics are in promiscuous mode
        self.assertInPromiscMode(nics)
        
        # bring first nic down and check still in promisc mode
        self.host.execdom0("ifconfig %s down" % nics[0])
        self.assertInPromiscMode(nics)
        
        time.sleep(10)
        
        # bring first nic back up and check still in promisc mode
        self.host.execdom0("ifconfig %s up" % nics[0])
        self.assertInPromiscMode(nics)

class TC12704(_BondTestCase):
    """Bond MII monitoring - use of miimon and use_carrier options"""
    # We do not take into account bond updelay and downdelay, as we believe
    # they should be negligible in the tests below.
    BOND_MODE = "active-backup"
    deletebond = False
    usebond = None
    host = None
    host_tcpdump_pid = {}
    guest_tcpdump_pid = {}
    ip2ping = ''
    nb_checks = 5 # number times eth0 and eth1 get desactivated
    bond_macs = {}

    def startHostTcpdump(self, ifname, guest=None):
        # run tcpdump i an infinite loop (as tcpdump ethX exits after each ifdown ethX)
        if guest:
            def execute(s): return guest.execguest(s)
        else:
            def execute(s): return self.host.execdom0(s)
        outfile = "tcpdump_%s" % ifname
        execute("rm -f %s" % outfile)
        scriptname = "tcpdump_%s.sh" % ifname
        script = '#!/bin/bash\n while [ 1 ] ; do  tcpdump -l -i %s icmp -ntt >> %s; done' % (ifname, outfile)
        execute("echo '%s' > %s" % (script, scriptname))
        execute("chmod 0700 %s" % scriptname)
        cmd =  'nohup ./%s &> /dev/null & echo $! ' % scriptname
        pid = execute(cmd).strip()
        # save pid
        if guest:
            self.guest_tcpdump_pid[ifname] = pid
        else:
            self.host_tcpdump_pid[ifname] = pid
            

    def collectHostTcpdumpResults(self, ifname, guest=None):
        if guest:
            def execute(s): return guest.execguest(s)
            pid = self.guest_tcpdump_pid[ifname]
        else:
            def execute(s): return self.host.execdom0(s)
            pid = self.host_tcpdump_pid[ifname]
        # kill the tcpdump process
        execute("kill %s" % pid )
        # kill all hanging children processes
        orphans_pids = []
        try: 
            orphans = execute(" ps --ppid 1 | grep tcpdump | grep -v tcpdump_ ")
            orphans_pids =  re.findall("^\s*(\d+)", orphans, re.MULTILINE)
        except:
            orphan_pids = []
        for pid in orphans_pids:
            execute("kill %s" % pid )
            time.sleep(2)
        # return all ICMP echo requests
        try:
            result = execute("grep 'ICMP echo request' tcpdump_%s" % ifname)
        except:
            result = ""
        result = result.strip()
        if result:
            lines = len(result.split("\n"))
        else:
            lines = 0
        xenrt.TEC().logverbose("Tcpdump collected %s lines." % lines)
        return result.strip()

    def guestStartPing(self, target_ip):
        self.startHostTcpdump("eth0", self.linux_0)
        self.linux_0.execguest("nohup ping -i 0.1 %s &> ping_out &" % target_ip)


    def guestStopPing(self):
        self.linux_0.execguest("killall ping")
        time.sleep(2)
        ping_out = self.linux_0.execguest("cat ping_out")
        self.linux_0.execguest("rm -f ping_out")
        xenrt.TEC().logverbose("Ping output: \n%s" % ping_out)
        pings_sent = self.collectHostTcpdumpResults("eth0", self.linux_0)

    def bondTwitch(self, interval = 10):
        # oscillate between bonded eth0 and eth1 on host 
        hostscript = """#!/bin/bash
for i in $( seq %s ) ; do
    for ethX in %s ; do
        for mode in down up ; do
            ifconfig $ethX $mode
            echo "$( date +%%s.%%N ) $ethX $mode"
            sleep %s
            sleep $(( $RANDOM %% 10 ))
        done
    done
done
""" % (self.nb_checks, string.join(self.bondInterfaces), interval)
        scriptname = "twitch.sh"
        self.host.execdom0("echo '%s' > %s" % (hostscript, scriptname))
        self.host.execdom0("chmod 0700 %s" % scriptname)
        maxtime = 10*(interval+11) # max whole sleep time is 10*(interval+9)
        times = self.host.execdom0("./%s" % scriptname, timeout=maxtime )
        self.host.execdom0("rm %s" % scriptname)
        return times.strip().split('\n')

    def bondTwitchLinks(self, interval=30):
        # disable and then enable switch ports for eth0 and eth1
        log = []
        for i in range(self.nb_checks):
            for ethX in self.bondInterfaces:
                # Disable the port
                timeBefore = time.time()
                self.host.disableNetPort(self.bond_macs[ethX])
                log.append("%s %s down\n" % (timeBefore, ethX))
                time.sleep(interval+random.random()*10)

                # Re-enable the port
                self.host.enableNetPort(self.bond_macs[ethX])
                log.append("%s %s up\n" % (time.time(), ethX))
                time.sleep(interval+random.random()*10)
        return log

    def findInpoolIP(self):
        # return the address of the slave host in the pool
        # (we'll ping it from a VM set on the master)
        ip = 'example.com'
        for h in self.hosts:
            if not h is self.host:
                ip = h.getIP()
                break
        return ip
        
    def findUnassignedIP(self):
        # find an unassigned IP address

        def isUnassigned(ip):
            cmd = "ping -q -c 60 %s" % unassigned
            try: 
                ret = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE).communicate()[0]
                received = re.search("\d+ packets transmitted, (\d+) received,", ret).group(1)
                return not ( int(received) > 0 )
            except Exception, e:
                raise xenrt.XRTFailure("Failed to use ping and find an unassigned IP address: %s" % e)

        subnet = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])
        for hostid in (9,8,7,6):
            unassigned = re.sub( '(\d+)$', lambda m: "%d" % (int(m.group(0))+hostid) , subnet)
            if isUnassigned(unassigned):
                return unassigned
        xenrt.TEC().warning("No unassigned IP found - an existing  host will be used and test results might be influenced")
        return re.sub( '(\d+)$', lambda m: "%d" % (int(m.group(0))+9) , subnet)
        
    def getOtherConfig(self):
        # return other-config XE PIF parameters
        return self.host.genParamGet("pif", self.bondPIF, "other-config")

    def setMIIMon(self, new_miimon, pif_reconfig = True):
        self.cli.execute("pif-param-set uuid=%s other-config:bond-miimon=%s" % (self.bondPIF, new_miimon))
        if pif_reconfig: self.reconfigurePIF()

    def setUseCarrier(self, use_carrier, pif_reconfig = True):
        self.cli.execute("pif-param-set uuid=%s other-config:bond-use_carrier=%s" % (self.bondPIF, use_carrier) )
        if pif_reconfig: self.reconfigurePIF()

    def reconfigurePIF(self):
        self.cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % self.bondPIF)

    def unsetMIIParams(self):
        self.cli.execute("pif-param-set uuid=%s other-config:bond-miimon= other-config:bond-use_carrier=" % self.bondPIF)
        self.cli.execute("pif-param-remove uuid=%s param-name=other-config param-key=bond-miimon " % self.bondPIF )
        self.cli.execute("pif-param-remove uuid=%s param-name=other-config param-key=bond-use_carrier " % self.bondPIF)
        self.reconfigurePIF()

    def learnNSEC(self):
        # Forces the switch to learn that the host management inetrface
        # is routable via NSEC
        mpif = self.host.parseListForUUID("pif-list",
                                     "management",
                                     "true",
                                     "host-uuid=%s" % (self.host.getMyHostUUID()))
        netmask = self.host.genParamGet("pif", mpif, "netmask")
        subnet = xenrt.util.calculateSubnet(self.host.getIP(), netmask)
        bcast = xenrt.util.calculateLANBroadcast(subnet, netmask)
        script="""#!/bin/bash
# Force phyiscal switch to send all man traffic through NSEC

"""
        for intf in self.bondInterfaces:
            script += "ifconfig %s down\n" % (intf)

        script += "\nping -c 5 -b %s\n\n" % (bcast)

        for intf in self.bondInterfaces:
            script += "ifconfig %s up\n" % (intf)

        self.host.execdom0("echo '%s' > script" % script)
        self.host.execdom0("chmod a+x script")
        self.guestStartPing(self.ip2ping) # let the switch know if the network address changes        
        self.host.execdom0("nohup ./script &")
        time.sleep(30) # give time for interfaces to ressurect
        self.guestStopPing()

    def setMacs(self):
        (info, slaves) = self.host.getBondInfo(self.device)
        if len(info['slaves']) != 2:
            raise xenrt.XRTError("Bond has %u slaves, expected 2" % (len(info['slaves'])))
        for eth in self.bondInterfaces:
            self.bond_macs[eth] = slaves[eth]['hwaddr']
        self.active_slave_eth = info['active_slave'] # slave defined as the initially active port

    def unsetDelays(self):
        # Remove default up and down delays, reducing them to 0, 
        # but save default values to restore them later.
        # All delays are expressed in miliseconds.
        if self.host.special['Network subsystem type'] == "vswitch":
            self.orig_downdelay = self.host.execdom0("ovs-vsctl get port %s bond_downdelay" % self.device)
            self.orig_updelay = 200 # original updelay
            # set updelay and downdelay to 0
            self.host.execdom0("ovs-vsctl set port bond0 bond_downdelay=%d" % 0 )
            self.host.genParamSet("pif", self.bondPIF, "other-config:bond-updelay",0)
            # we must reconfigure the ip in this case
            self.host.execdom0("xe pif-reconfigure-ip uuid=%s mode=None" % self.bondPIF )
        else: # for bridge:
            self.cli.execute("pif-param-set other-config:bond-downdelay=0 other-config:bond-updelay=0 uuid=%s"
                % self.bondPIF)
            self.host.execdom0("xe pif-reconfigure-ip uuid=%s mode=None" % self.bondPIF )

    def restoreDelays(self):
        # restore original values or up- and downdelay
        if self.host.special['Network subsystem type'] == "vswitch":
            self.host.execdom0("ovs-vsctl set port bond0 bond_downdelay=%d" % self.orig_downdelay )
            self.host.genParamSet("pif", self.bondPIF, "other-config:bond-updelay",self.orig_updelay)
            self.host.execdom0("xe pif-reconfigure-ip uuid=%s mode=None" % self.bondPIF )
        else:
            self.cli.execute("pif-param-set other-config:bond-downdelay= other-config:bond-updelay= uuid=%s"
                % self.bondPIF)
            self.cli.execute("pif-param-remove uuid=%s param-name=other-config param-key=bond-updelay"
                                                                % self.bondPIF)
            self.cli.execute("pif-param-remove uuid=%s param-name=other-config param-key=bond-downdelay"
                                                                % self.bondPIF)                                                    
            self.host.execdom0("xe pif-reconfigure-ip uuid=%s mode=None" % self.bondPIF )

    def setBondMode(self):
        if self.host.productVersion == "Boston":
            self.cli.execute("bond-set-mode uuid=%s mode=%s" %  (self.bonduuid, self.BOND_MODE) )
        else:
            self.cli.execute("pif-param-set uuid=%s other-config:bond-mode=%s" %
                                              (self.bondPIF, self.BOND_MODE) )
            self.host.execdom0("xe pif-reconfigure-ip uuid=%s mode=None" % self.bondPIF )

    def limitedBy(self, lst, maxval):
        # return True if all elements in list lst do not excess maxval
        if len([ i for i in list if float(i)>maxval ]) > 0:
            return False
        else:
            return True

    def valuesWithinRange(self, values, lower, upper):
        # return values that are only within given boundaries (strictly)
        return filter(lambda x: x>lower and x<upper, values)
        
    def prepare(self, arglist=None):
        _BondTestCase.prepare(self, arglist)
        self.host = self.getDefaultHost()
        self.pool = self.getDefaultPool()
        self.hosts = self.pool.slaves.values()
        self.bonduuid = self.host.getBonds()[0]
        self.bondPIF = self.host.genParamGet("bond", self.bonduuid, "master")
        self.device = self.host.genParamGet("pif", self.bondPIF, "device")
        networkUUID = self.host.genParamGet("pif", self.bondPIF, "network-uuid")
        self.bondbridge = self.host.genParamGet("network", networkUUID, "bridge")
        self.cli = self.host.getCLIInstance()
        self.setBondMode()
        self.linux_0 = self.host.createGenericLinuxGuest(bridge=self.bondbridge, name='LinGuestOnBond')
        self.ip2ping = self.findInpoolIP()  # set up peer IP
        # check if the bond is working before doing anything
        xenrt.TEC().logdelimit("Before changing anything, check if the bond is working")
        bondSlavePIFs = self.host.minimalList("pif-list", args="bond-slave-of=%s" % (self.bonduuid))
        self.bondInterfaces = map(lambda p: self.host.genParamGet("pif", p, "device"), bondSlavePIFs)
        for intf in self.bondInterfaces:
            self.startHostTcpdump(intf)
        self.guestStartPing(self.ip2ping)
        time.sleep(30)
        self.guestStopPing()
        noTrafficInterfaces = filter(lambda i: len(self.collectHostTcpdumpResults(i).split("\n")) == 0, self.bondInterfaces)
        if len(noTrafficInterfaces) > 0:
            raise xenrt.XRTFailure("No traffic on bonded interfaces")
        
        self.learnNSEC()  # force traffic through NSEC network
        self.setMacs()
        self.unsetDelays()
        xenrt.TEC().logverbose(self.host.getBondInfo(self.device))

    def run(self, arglist=None):

        # check if the bond is working at all

        xenrt.TEC().logdelimit("Check the bond after changing the settings")
        for intf in self.bondInterfaces:
            self.startHostTcpdump(intf)
        self.guestStartPing(self.ip2ping)
        time.sleep(30)
        self.guestStopPing()
        noTrafficInterfaces = filter(lambda i: len(self.collectHostTcpdumpResults(i).split("\n")) == 0, self.bondInterfaces)
        if len(noTrafficInterfaces) > 0: 
            raise xenrt.XRTFailure("No traffic on bonded interfaces")

        # check and change the default values of miimon and use_carrier
        xenrt.TEC().logdelimit("Checking setting miimon values through xapi")
        defvals = self.getOtherConfig() # probably empty, but check
        xenrt.TEC().logverbose("Default values of miimon and use_carrier: '%s'" % defvals)
        new_miimon = 200
        self.setMIIMon(new_miimon, pif_reconfig = False)
        self.setUseCarrier(0)

        # check if changing the MII monitoring values worked
        
        oth_conf = self.getOtherConfig()
        newvals_strings = re.search("bond-use_carrier:\s*(\d); bond-miimon: (\d+)", oth_conf).group(1,2)
        (newval_use_carrier, newval_miimon) =  map (int, newvals_strings)
        if (newval_use_carrier != 0 or newval_miimon != new_miimon):
            xenrt.TEC().logverbose("Other-config: '%s'" % oth_conf)
            raise xenrt.XRTFailure("Changing MII monitoring parameters failed. Set: use_carrier=0 and miimon=1. "
                "Found: use_carrier=%s and miimon=%s." % (newval_use_carrier, newval_miimon) )

        # revert to default MII monitoring values

        self.unsetMIIParams()
        new_defvals = self.getOtherConfig() 
        if new_defvals != defvals :
            xenrt.TEC().logverbose("Values of miimon and use_carrier after switching to default settings: '%s'" % new_defvals)
            raise xenrt.XRTFailure("Reverting to default values of miimon and use_carrier failed")

        # Set use_carrier to 0

        self.setUseCarrier(1) # CHANGED FOR DEBUGGING ONLY !!!

        # For miimon values of : default (100ms), 1s and 10s,
        # check that network transfer resumes as promptly as expected

        for miimon in (False, 100, 1000, 10000): # 1s and 10s
            xenrt.TEC().logdelimit("Checking transfer resume delays for miimon=%s" % miimon)
            if miimon:
                self.setMIIMon(miimon)
                expected_max_delay = 1.2 * miimon/1000
            else: # for default miimon value (100ms), check that network transfer resumes within 1s.
                expected_max_delay = 1

            # start pinging and tcpdump on both interfaces
            for intf in self.bondInterfaces:
                self.startHostTcpdump(intf)
            self.guestStartPing(self.ip2ping)
            # switch off and back on eth1 and then eth1, repeating multiple times
#           interface_mode_switch_times = self.bondTwitch(interval = 10+2*expected_max_delay)
            interface_mode_switch_times = self.bondTwitchLinks(interval = 200)
            xenrt.TEC().logverbose("Bond twitch times:\n%s" % "\n".join(interface_mode_switch_times))
            
            # stop pinging and tcpdump, collect results
            self.guestStopPing()
            icmp_times = {}
            for eth in self.bondInterfaces:
                times = self.collectHostTcpdumpResults(eth)
                # get icmp echo request timestamps
                icmp_times[eth] = [ float(l.split()[0]) for l in times.split("\n") if len(l) ]
                # log icmp times - for debugging only!
                xenrt.TEC().logverbose("ICMP times for %s: \n%s" % (eth, "\n".join(map(str,icmp_times[eth]))) )

            # check transfer during bond twitch 

            # During bondTwitch(), ethX is repetitively switched off at t_off and then back on at t_off.
            # We want to make sure there was traffic on ethY between t_off and t_on.
            delays = []
            for line in interface_mode_switch_times:
                # line format: "<timestamp>  <iface: eth0/eth1>  <mode: off/on>"
                t, ethX, mode = line.split()
                if mode == 'down':
                    t_off = float(t) 
                    continue
                t_on = float(t)
                ethY = filter(lambda i: i != ethX, self.bondInterfaces)[0]
                # check there was transfer on ethY while ethX was switched off (t1 < t < t2)
                times_Y = self.valuesWithinRange(icmp_times[ethY], t_off, t_on)
                times_X = self.valuesWithinRange(icmp_times[ethX], t_off, t_on)
                if len(times_Y) == 0 :
                    raise xenrt.XRTFailure("No transfer on %s between time=%s and time=%s, while %s was switched off" %
                        (ethY, t_off, t_on, ethX) )
                # transfer resumes at times_Y[0]
                delay = times_Y[0] - t_off
                delays.append(delay)
                if len(times_X)>0:
                    xenrt.TEC().warning("After switching off %s at t=%s, transfer still observed at t = %s" %
                        (ethX, t_off, ", ".join(map(str,times_X)) ) )
            # process observed delays:
            # - log the data
            # - issue error if any delay > expected_max_delay,
            # - issue warning if max. delay < 0.5 of expected delay.
            xenrt.TEC().logverbose("Delays of transfer resume for miimon of %s: %s" % (miimon, ", ".join(map(str,delays))) )
            excessive_delays = [ d for d in delays if delay > expected_max_delay ]
            if len(excessive_delays) > 0:
                # raise xenrt.XRTFailure("Delays in resuming transfer bigger than expected for miimon of %s: %s. " %
                xenrt.TEC().warning("Delays in resuming transfer bigger than expected for miimon of %s: %s. " %
                  (miimon, ", ".join(map(str,excessive_delays))))
            if max(delays) < 0.4*expected_max_delay:
                xenrt.TEC().warning("Expected max. delay around %s, observed max. delay: %s." % (expected_max_delay, max(delays)) )
    
    def postRun(self):
        # revert to default settings
        self.unsetMIIParams()
        self.restoreDelays()

class TC14909(xenrt.TestCase):
    """Regression test for CA-58506"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Create a bond of two NSEC NICs
        # (we're going to change the MTU so don't want to break mgmt network)
        assumedids = self.host.listSecondaryNICs("NSEC")
        if len(assumedids) < 2:
            raise xenrt.XRTError("Couldn't find 2 NSEC NICs")

        nics = map(self.host.getSecondaryNIC, assumedids[:2])
        pifs = []
        for n in nics:
            pifs.append(self.host.parseListForUUID("pif-list","device",n,"host-uuid=%s" % (self.host.getMyHostUUID())))

        self.network = self.host.createNetwork("CA58506-test")
        self.bond = self.host.createBond(pifs,dhcp=True,network=self.network)
        # Find the bond PIF
        bondUUID = self.host.genParamGet("pif", pifs[0], "bond-slave-of")
        self.bondpif = self.host.parseListForUUID("pif-list", "bond-master-of", bondUUID)

    def run(self, arglist):
        # Set the network MTU to 9000
        self.host.genParamSet("network", self.network, "MTU", "9000")

        # Now replug the bond PIF
        cli = self.host.getCLIInstance()
        cli.execute("pif-unplug", "uuid=%s" % (self.bondpif))
        cli.execute("pif-plug", "uuid=%s" % (self.bondpif))

        # Now check the MTU on the bond
        errors = []

        pifmtu = self.host.genParamGet("pif", self.bondpif, "MTU")
        if int(pifmtu) != 9000:
            errors.append("Bond PIF MTU is %s, expecting 9000" % (pifmtu))
        ifconfig = self.host.execdom0("ifconfig %s" % (self.bond[0]))
        if not "MTU:9000" in ifconfig and not "mtu 9000" in ifconfig:
            errors.append("Bond device MTU is not 9000")

        if len(errors) > 0:
            raise xenrt.XRTFailure(string.join(errors,", "))

class TC15296(_AggregateBondTest):
    """Regression test for CA-66947"""
    
    def run(self, arglist):
        
        h1 = self.getHost("RESOURCE_HOST_0")
        h1.reboot()
        
        # this is a script to check that bond slaves have carrier=True
        # for their PIF_metrics.
        
        scr = """#!/usr/bin/python
import XenAPI
import sys

session=XenAPI.xapi_local()
session.xenapi.login_with_password("root","")

bond_refs_recs = session.xenapi.Bond.get_all_records()
pif_refs_recs = session.xenapi.PIF.get_all_records()
pif_metrics_refs_recs = session.xenapi.PIF_metrics.get_all_records()

for sl in bond_refs_recs[bond_refs_recs.keys()[0]]['slaves']:
        metricsRef = pif_refs_recs[sl]['metrics']
        if not pif_metrics_refs_recs[metricsRef]['carrier']:
                print 'TEST FAILED'
                sys.exit(0)

print 'TEST PASSED'
"""
        
        # write script to temp file on controller
        dir = xenrt.TEC().tempDir()
        tempFile = dir + "/CA66947"
        f = open(tempFile, "w")
        f.write(scr)
        f.close()
        
        # copy script to host
        sftp = h1.sftpClient()
        try:
            sftp.copyTo(tempFile, "/root/CA66947")
        finally:
            sftp.close()
        
        # make script executable
        h1.execdom0("chmod +x /root/CA66947")
        
        # execute script and check STDOUT
        if not "TEST PASSED" in h1.execdom0("/root/CA66947"):
            raise xenrt.XRTFailure("Connected bond slaves should always have carrier=True in their PIF_metrics.")
    
class _BondsOn16NICs(TCWith16Nics):

    BOND_MODES = []
    N_OF_BONDS = 0
    
    def rebootTheHost(self):
        
        for g in self.test_guests:
            g.shutdown()

        self.host.reboot()

        for g in self.test_guests:
            g.start()
    
    def checkBond(self, device, num_of_slaves):
        (info,slaves) = self.host.getBondInfo(device)
        
        if len(info['slaves']) != num_of_slaves:
            raise xenrt.XRTFailure("Bond has %u slave devices, expected %s" % 
                                   (len(info['slaves']), num_of_slaves))

    def postRun(self):
        for g in self.test_guests:
            g.uninstall()
        
        for bond in self.host.getBonds():
            self.host.removeBond(bond)
            
    def run(self, arglist=None):
        
        bonds = {}
        step('Get pifs to bond')
        self.all_pifs = list(self.all_pifs)
        
        step('Create the %s bonds' % self.N_OF_BONDS)
        for i in range(self.N_OF_BONDS):     # N_OF_BONDS*4 PIFs are used for creating bonds
            pifs_to_be_bonded = self.all_pifs[4 * i : 4 * (i + 1)]
            bridge, dev = self.host.createBond(pifs_to_be_bonded,
                                mode=self.BOND_MODES[i%len(self.BOND_MODES)])
            bonds[bridge] = dev
            
        step("Bring up a VM on each bond")
        for bridge in bonds.keys():
            self.test_guests.append(self.cloneVM(self.host, self.guest, bridge=bridge))

        step("Bring up a VM on remaining pifs")
        pifs = self.all_pifs[self.N_OF_BONDS*4:16]   # e.g. [12:16]
        for pif in pifs:
            self.test_guests.append(self.cloneVM(self.host, self.guest, pif_uuid=pif))
            
        step("Reboot host and VM")
        self.rebootTheHost()
    
        step("Check the bond after reboot")
        for device in bonds.values():
            self.checkBond(device, 4)

class FourAPBondsOn16NICs(_BondsOn16NICs):
    """Creation of 4 active-passive bonds with 4 NICs each"""
    # Jira TC15915
    BOND_MODES = ["active-backup"]
    N_OF_BONDS = 4
    
class FourAABondsOn16NICs(_BondsOn16NICs):
    """Creation of 4 active-active bonds with 4 NICs each"""
    # Jira TC15916
    BOND_MODES = ["balance-slb"]
    N_OF_BONDS = 4
    
class LacpBondx4On16NICs(_BondsOn16NICs):
    """Creation of 4 LACP bonds with 4 NICs each"""
    # Jira TC15919
    BOND_MODES = ["lacp"]
    N_OF_BONDS = 4
            
class VarBondx4On16NICs(_BondsOn16NICs):
    """Verify creation of 4 bonds with 4 NICs each (assorted bond types)"""
    BOND_MODES = ["active-backup", "balance-slb"]
    N_OF_BONDS = 4
    
class VarBondx3On16NICs(_BondsOn16NICs):
    """Verify creation of 4 bonds with 4 NICs each (assorted bond types)"""
    BOND_MODES = ["active-backup", "balance-slb", "lacp"]
    N_OF_BONDS = 3

class _BondMonitoring(xenrt.TestCase):
    """Base class for bond monitoring TCs"""
    NICS_IN_BOND = 2  # Number of NICS in the bond
    WAIT_SECONDS = 50 # The number of seconds to wait after changing link status before expecting to find any messages
    RANDOM_OP_COUNT = 12 # The number of random operations to complete (each one will take at least WAIT_SECONDS to run)
    START_DOWN = 0    # The number of NICs to bring down before creating the bond
    BOND_MODE = None

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self._pifsToPlug = []
        self._networkToRemove = []
    
    def setupBond(self, host):
        """Sets up the bond, should return the bond UUID"""
        raise xenrt.XRTError("Unimplemented in base class")

    def checkLinkCount(self, expectedCount):
        """Checks the links-up count is as expected"""
        linksUp = int(self.host.genParamGet("bond", self.bondUUID, "links-up"))
        if linksUp != expectedCount:
            if linksUp == 0:
                xenrt.TEC().warning("Links up count wrong - CA-83990")
            else:
                raise xenrt.XRTFailure("Expecting to find %d links up, actually found %d" % (expectedCount, linksUp))

    def checkMessages(self, expected):
        """Checks we have the expected set of messages"""
        messages = self.host.getMessages(messageName="BOND_STATUS_CHANGED", ignoreMessages=self.handledMessages)
        for m in messages:
            self.handledMessages.append(m['uuid'])

        # Xapi gives messages to us in reverse order!
        messages.reverse()

        # Convert this set of messages in to a list to compare to expected
        convertedMessages = []
        for m in messages:
            if m['obj-uuid'] != self.host.getMyHostUUID():
                raise xenrt.XRTFailure("Found message that did not correspond to our host UUID")
            cm = self._convertMessage(m['body'])
            if cm[0] != self.bondNICs:
                raise xenrt.XRTFailure("Message showed incorrect bond NICs", data="Expecting %s, found %s" % (self.bondNICs, cm[0]))

            convertedMessages.append(cm[1:])

        if isinstance(expected, list):
            set_expected = set(expected)
            set_convertedMessages = set(convertedMessages)
            if not set_expected.issubset(set_convertedMessages):
                raise xenrt.XRTFailure("Bond status monitoring messages were not as expected",
                                       data="Expecting %s, found %s" % (expected, convertedMessages))
        elif isinstance(expected, int):
            # Check the most recent message is showing expected/total links up
            total = self.NICS_IN_BOND
            if len(convertedMessages) < 1:
                if expected == total:
                    # This is permissible, as if all links are up a message need not be generated
                    return
                raise xenrt.XRTFailure("PR-1430 messages were not as expected",
                                       data="Expecting a message showing %d/%d" % (expected, total))
            lastMessage = convertedMessages[-1]
            # Also check that the 'was x' number is less than the new total
            if lastMessage[0] != expected or lastMessage[1] != total or lastMessage[2] >= expected:
                raise xenrt.XRTFailure("PR-1430 messages were not as expected",
                                       data="Expecting a message showing %d/%d, found %s" % (expected, total, convertedMessages))
            # Check any messages prior to the final one went in sequence (first message should have no 'was' value)
            # We expect the number of links up to always increase (though not necessarily in a regular increment)
            # e.g. a potential sequence might be (0/4, 1/4 (was 0), 3/4 (was 1))
            lastSeen = None # None indicates we expect no 'was' entry
            for m in convertedMessages[:-1]:
                current = m[0]
                reportedTotal = m[1]
                was = m[2]
                # LACP bond are exception to logical ordering of nics coming up as it requires negotiation with physical switch. CA-113633
                #Following if condition was modified to not to check the previous messages as they were inconsistent ,resulting into intermittent failures.CA-134684
                #if current > expected or (self.BOND_MODE !="lacp" and lastSeen is not None and current <= lastSeen) or \
                #   reportedTotal != total or was != lastSeen:
                if current > expected or (self.BOND_MODE !="lacp" and lastSeen is not None and current <= lastSeen):
                    messages = self.host.minimalList("message-list")
                    step(messages)
                    raise xenrt.XRTFailure("PR-1430 messages were not as expected",
                                           data="Expecting a message in up sequence showing x/%d, was %s, found %s" %
                                                (total, lastSeen, convertedMessages))
                lastSeen = current
        else:
            raise xenrt.XRTError("checkMessages called with unexpected type")

    def _convertMessage(self, message):
        """Converts a BOND_STATUS_CHANGED body in to a tuple"""
        # Message is in format "The status of the ethX+ethY bond changed: x/y up (was z/y)"
        # We want to return: (bondNICs, x, y, z)
        m = re.match("The status of the (eth\d[+eth\d]+) bond (?:changed|is): (\d)/(\d) up(?: \(was (\d)/(\d)\))?", message)
        if not m:
            raise xenrt.XRTError("Unable to parse BOND_STATUS_CHANGED message")
        nics = m.group(1).split("+")
        nics.sort()
        x = int(m.group(2))
        y = int(m.group(3))
        z = None
        if m.group(4):
            z = int(m.group(4))
            if int(m.group(5)) != y:
                raise xenrt.XRTFailure("Bond message invalid (shows different number of total NICs in current vs previous report)", data=message)
        return (nics, x, y, z)

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.handledMessages = []
        self.downMACs = []

        step("Clearing alert list")
        self.host.clearMessages()

    def run(self, arglist):
        step("Setting up bond")
        self.bondUUID = self.setupBond(self.host)
        bondPIF = self.host.genParamGet("bond", self.bondUUID, "master")
        slavePIFs = self.host.genParamGet("bond", self.bondUUID, "slaves").split("; ")
        nics = []
        self.nicMACs = []
        nicMACsMapping = {}
        for s in slavePIFs:
            nic = self.host.genParamGet("pif", s, "device")
            nics.append(nic)
            mac = self.host.genParamGet("pif", s, "MAC")
            self.nicMACs.append(mac)
            nicMACsMapping[nic] = mac
        nics.sort()
        self.bondNICs = nics

        cli = self.host.getCLIInstance()
        bondPIF = self.host.genParamGet("bond", self.bondUUID, "master")
        try:
            cli.execute("pif-plug", "uuid=%s" % (bondPIF))
        except:
            pass # Bond may already be plugged

        time.sleep(self.WAIT_SECONDS)

        # Check we have the expected messages, if all links are up we expect either none, or some number culminating in x/x
        # If a link is down, then we expect some number culminating in x-down/x
        self.checkMessages(self.NICS_IN_BOND - self.START_DOWN)
        self.checkLinkCount(self.NICS_IN_BOND - self.START_DOWN)

        step("Cycling links down/up")
        upCount = self.NICS_IN_BOND - self.START_DOWN

        # Down them all
        for mac in self.nicMACs:
            if mac in self.downMACs:
                # Already down, so we don't need to worry
                continue
            self.host.disableNetPort(mac)
            time.sleep(self.WAIT_SECONDS)
            self.checkMessages([(upCount-1, self.NICS_IN_BOND, upCount)])
            self.checkLinkCount(upCount-1)
            upCount -= 1

        # Up them all
        for mac in self.nicMACs:
            self.host.enableNetPort(mac)
            time.sleep(self.WAIT_SECONDS)
            self.checkMessages([(upCount+1, self.NICS_IN_BOND, upCount)])
            self.checkLinkCount(upCount+1)
            upCount += 1

        step("Random operations")
        upLinks = copy.copy(self.bondNICs)
        downLinks = []
        for i in range(self.RANDOM_OP_COUNT):
            if len(upLinks) == 0:
                up = True
            elif len(upLinks) == self.NICS_IN_BOND:
                up = False
            else:
                # Make a random choice about what to do
                up = (random.randint(0,1) == 1)
            if up:
                # Bring a link up
                nic = random.choice(downLinks)
                mac = nicMACsMapping[nic]
                self.host.enableNetPort(mac)
                time.sleep(self.WAIT_SECONDS)
                self.checkMessages([(len(upLinks)+1, self.NICS_IN_BOND, len(upLinks))])
                self.checkLinkCount(len(upLinks)+1)
                downLinks.remove(nic)
                upLinks.append(nic)
            else:
                # Take a link down
                nic = random.choice(upLinks)
                mac = nicMACsMapping[nic]
                self.host.disableNetPort(mac)
                time.sleep(self.WAIT_SECONDS)
                self.checkMessages([(len(upLinks)-1, self.NICS_IN_BOND, len(upLinks))])
                self.checkLinkCount(len(upLinks)-1)
                downLinks.append(nic)
                upLinks.remove(nic)

        if len(downLinks) > 0:
            # Clean up from random test
            broughtLinkUp = False
            for nic in downLinks:
                self.host.enableNetPort(nicMACsMapping[nic])
                broughtLinkUp = True
            if broughtLinkUp:
                time.sleep(self.WAIT_SECONDS)
            self.handledMessages = []
            self.host.clearMessages()
        
        step("Link operations with bond PIF unplugged")
        # We expect to get no messages!
        cli.execute("pif-unplug", "uuid=%s" % (bondPIF))
        time.sleep(self.WAIT_SECONDS)
        self.checkMessages([])
        
        for mac in self.nicMACs:
            self.host.disableNetPort(mac)
        time.sleep(self.WAIT_SECONDS)
        self.checkMessages([])
        for mac in self.nicMACs:
            self.host.enableNetPort(mac)
        time.sleep(self.WAIT_SECONDS)
        self.checkMessages([])

        step("Destroying bond")
        cli.execute("bond-destroy", "uuid=%s" % (self.bondUUID))
        # We deliberately wait a bit longer here as we won't pick up any 'late' messages in a later step
        time.sleep(120)
        self.checkMessages([])

    def postRun(self):
        try:
            self.host.removeBond(self.bondUUID)
        except:
            pass

        cli = self.host.getCLIInstance()
        for pif in self._pifsToPlug:
            try:
                cli.execute("pif-plug", "uuid=%s" % (pif))
            except:
                pass
        
        for network in self._networkToRemove:
            try:
                self.host.removeNetwork(network)
            except:
                pass
        
        for n in self.nicMACs:
            try:
                self.host.enableNetPort(n)
            except:
                pass

class _BondMonitoringDefaultMode(_BondMonitoring):

    def setupBond(self, host):
        # Find NICS on NSEC
        nics = host.listSecondaryNICs(network="NSEC")
        if len(nics) < self.NICS_IN_BOND:
            raise xenrt.XRTError("Insufficient NSEC NICs", data="Required %d, found %d" % (self.NICS_IN_BOND, len(nics)))
        pifs = map(lambda n: host.getNICPIF(n), nics)
        self._pifsToPlug.extend(pifs)
        ignorePifCarrierFor = []
        for i in range(self.START_DOWN):
            pif = pifs[i]
            mac = host.genParamGet("pif", pif, "MAC")
            host.disableNetPort(mac)
            self.downMACs.append(mac)
            ignorePifCarrierFor.append(pif)
        if self.START_DOWN:
            xenrt.sleep(30)
        self.network = self.host.createNetwork()
        self._networkToRemove.append(self.network)
        host.createBond(pifs[0:self.NICS_IN_BOND],network=self.network, ignorePifCarrierFor=ignorePifCarrierFor)
        return host.genParamGet("pif", pifs[0], "bond-slave-of")

class TC17712(_BondMonitoringDefaultMode):
    """Bond monitoring of a default 2 NIC bond"""
    NICS_IN_BOND = 2

class TC17713(_BondMonitoringDefaultMode):
    """Bond monitoring of a default 3 NIC bond"""
    NICS_IN_BOND = 3

class TC17714(_BondMonitoringDefaultMode):
    """Bond monitoring of a default 4 NIC bond"""
    NICS_IN_BOND = 4

class _BondMonitoringLACP(_BondMonitoring, _BondTestCase):

    BOND_MODE="lacp"
    
    def setupBond(self, host):
        # Check we're using vswitch (LACP not supported on bridge)
        if host.special['Network subsystem type'] != "vswitch":
            raise xenrt.XRTError("vswitch is required to test LACP bonds")

        # We need to find the requisite number of NSEC NICs that are on a switch
        # that supports LACP
        nics = host.listSecondaryNICs(network="NSEC")
        switchName = None
        for n in nics:
            sn = self._getSwitchStackNameForNic(n)
            if xenrt.lib.switch.suitableForLacp(sn):
                switchName = sn
                break
        if not switchName:
            raise xenrt.XRTError("Couldn't find a LACP suitable switch")

        # Filter the NICs to those on the switch
        nics = filter(lambda n: self._getSwitchStackNameForNic(n) == switchName, nics)

        if len(nics) < self.NICS_IN_BOND:
            raise xenrt.XRTError("Insufficient NSEC NICs on LACP capable switch", data="Required %d, found %d" % (self.NICS_IN_BOND, len(nics)))

        pifs = map(lambda n: host.getNICPIF(n), nics)
        self._pifsToPlug.extend(pifs)
        self.network = self.host.createNetwork()
        self._networkToRemove.append(self.network)
        self.lacpPifs = pifs[0:self.NICS_IN_BOND]
        host.createBond(self.lacpPifs, network=self.network, mode=self.BOND_MODE)
        return host.genParamGet("pif", pifs[0], "bond-slave-of")

    def postRun(self):
        _BondMonitoring.postRun(self)
        # remove LACP set-up on the switch
        xenrt.TEC().logverbose("Attempting to clear LACP configuration")
        try:
            switch = xenrt.lib.switch.createSwitchForPifs(self.host, self.lacpPifs)
            switch.unsetLACP()
        except:
            pass

class TC17715(_BondMonitoringLACP):
    """Bond monitoring of a 2 NIC LACP bond"""
    NICS_IN_BOND = 2

class TC17716(_BondMonitoringLACP):
    """Bond monitoring of a 4 NIC LACP bond"""
    NICS_IN_BOND = 4

class TC17717(_BondMonitoringDefaultMode):
    """Bond monitoring of a 2 NIC bond with one link down at creation"""
    NICS_IN_BOND = 2
    START_DOWN = 1

class TC17766(_BondTestCase):
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
        #find 2 NPRI pifs.
        self.bondPifs = self.findPIFToBondWithManagementNIC(self.host)

        #Create a bond
        self.host.createBond(self.bondPifs,dhcp=True,management=True)

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Waiting for 2 minutes to stabilise the carrier information in xapi and ethtool.")
        xenrt.sleep(120)
        
        for pif in self.bondPifs:
            link = self.host.minimalList("pif-list uuid=%s params=carrier" % (pif))[0][0] == 't'
            eth  = self.host.minimalList("pif-list uuid=%s params=device"  % (pif))[0]
            if not (link and self.ethtoolLink(eth)):
                raise xenrt.XRTFailure("Inconsistent information between xapi and ethtool for device."
                                "link = '%s', Device = '%s'" % (link, eth))

    def ethtoolLink(self, dev):
        return self.ethtool(dev)["Link detected"][0] == 'y'

    def ethtool(self, dev):
        data = self.host.execdom0("ethtool %s" % (dev))
        return xenrt.util.strlistToDict(data.splitlines(), sep=":", keyonly=False)

    def postRun(self):
        bondUUID = self.host.genParamGet("pif", self.bondPifs[0], "bond-slave-of")
        self.host.removeBond(bondUUID)

class TC17897(xenrt.TestCase):
    """ Old VLAN device not removed when automatically moving VLAN to bond (Linux bridge only) """
    vlan = 666
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.host.reboot()
        self.host.waitForSSH(600, desc="host reboot after switching to bridge")
        bridge = self.host.createNetwork()

        nics = self.host.listSecondaryNICs("NPRI")
        if len(nics) < 2:
            raise xenrt.XRTFailure("less than 2 NICs in NPRI.")

        pifs = []
        for nic in nics:
            xenrt.TEC().logverbose("getNICPIF of %s" % (nic))
            pifs.append(self.host.getNICPIF(nic))
            
        assumedid = self.host.listSecondaryNICs("NPRI")[0]
        pifuuid = self.host.getNICPIF(assumedid)
        self.host.createVLAN(self.vlan, bridge, pifuuid=pifuuid)

        time.sleep(30)

        self.nic = self.host.minimalList("pif-list uuid=%s" % pifuuid, "device")[0]
        self.host.execdom0("ifconfig %s.%d" % (self.nic, self.vlan))

        self.host.createBond(pifs)

        # let it settle
        time.sleep(120)

        # check ifconfig bond0.x exists
        self.host.execdom0("ifconfig bond0.%d" % (self.vlan))

    def run(self, arglist=None):
        rc = self.host.execdom0("ifconfig %s.%s" % (self.nic, self.vlan),retval="code")
        if rc == 0:
            raise xenrt.XRTFailure("VLAN interface persists after bond creation")
            

class TCBondModeChange(_BondTestCase):
    """Changing bond mode should not trigger vSwitch segmentation fault (regression test for CA-71284)"""
    
    def __init__(self):
        _BondTestCase.__init__(self)
        self.bond_uuid = None
        
    def prepare(self,arglist):
        self.host = self.getDefaultHost()
        
        #Create an active-passive bond with NIC0+NIC1
        pifs = self.findPIFToBondWithManagementNIC(self.host)
        self.host.createBond(pifs, mode = "active-backup")
        
        #get the bond-uuid
        self.bond_uuid = self.host.genParamGet("pif", pifs[0], "bond-slave-of")
        
    def run(self,arglist):
    
        #change the bond mode to balance-slb
        self.host.execdom0("xe bond-set-mode uuid=%s mode=balance-slb" %(self.bond_uuid))
        
        #check the daemon.log file for any vswitch segmentation fault
        msg = 'ovs-vswitchd:.*Segmentation fault'
        if self.host.execdom0("grep '%s' /var/log/daemon.log" %(msg),retval = "code") == 0:
            raise xenrt.XRTFailure("Segmentation fault in vswitch observed")
        else:
            xenrt.TEC().logverbose("No segmentation fault observed while changing bond mode")
        
    def postRun(self):
        self.host.removeBond(self.bond_uuid,management = True)

class TCBondFailoverRarp(_BondSetUp):
    """Test to verify LLC-SNAP/RARP packet is sent on bond failover. Regression test for SCTX-1774"""
    # Jira TC-21566

    BOND_MODE = "active-backup"
    FILENAME = "tcpdump.txt"

    def prepare(self, arglist=None):        
        self.host = self.getDefaultHost()
        step("Create Bond of 2 NICs")
        self.bond = self.createBonds(1, nicsPerBond=self.NUMBER_NICS, networkName=self.NETWORK_NAME)[0]
        
        step("Create a VM on the bond")
        self.g = self.host.createGenericLinuxGuest(bridge=self.bond.bridge)
        self.uninstallOnCleanup(self.g)
    
    def run(self, arglist=None):
        self.bondMac = self.host.parseListForOtherParam("pif-list", "device", self.bond.device, "MAC")
        vif = self.g.getVIFs().keys()[0]
        self.guestMac = vif[0]
        
        step("Generate traffic on guest")
        retCode = xenrt.command(("ping -c 3 %s" % self.g.getIP()), retval="code")
        if retCode != 0:
            raise xenrt.XRTFailure("Failed to ping the guest on %s" % self.g.getIP())
        self.g.execguest("ping -c 3 %s" % (self.host.getIP()))
        
        step("Fetch active and passive slaves of bond")
        info, x = self.host.getBondInfo(self.bond.device)
        slaves = info["slaves"]
        self.activeSlave = info["active_slave"]
        passiveSlave = [s for s in slaves if s != self.activeSlave][0]
        
        step("Get ovs version")
        ovsVersion= self.host.getOvsVersion()
        ovsVersion = float(ovsVersion.rsplit('.', 1)[0])
        log("OVS version is %s" % (ovsVersion))
        
        step("Perform bond failover and fetch TCP packets on passive slave")
        if ovsVersion >= 1.8:
            command = "tcpdump -i %s rarp &> %s & echo $!" % (passiveSlave, self.FILENAME)
            self.tcpDumpOnBondFailover(command)
            step("Since ovs version is %s, looking for RARP packets" % ovsVersion)
            self.verifyRARP()
        else:
            command = "tcpdump -i %s -e &> %s & echo $!" % (passiveSlave, self.FILENAME)
            self.tcpDumpOnBondFailover(command)
            step("Since ovs version is %s, looking for LLC broadcast packet" % ovsVersion)
            self.verifyLLC()
            
    def tcpDumpOnBondFailover(self, command):
        pid = self.host.execdom0(command).strip()
        
        #disable active bond slave and capture tcpdump over next 30 seconds
        self.host.execdom0("ifconfig %s down" % (self.activeSlave))
        xenrt.sleep(30)
        self.host.execdom0("kill %s" % (pid))
        
    def verifyLLC(self):
        """LLC packet is broadcasted.
        Format of packet:
        08:37:50.421514 b2:24:46:86:03:79 (oui Unknown) > Broadcast, 802.3, length 55: LLC, dsap SNAP (0xaa) Individual, ssap SNAP (0xaa)..."""
        
        res = self.host.execdom0("cat %s | grep '%s.*Broadcast.*LLC.*SNAP'" % (self.FILENAME, self.guestMac))
        if res:
            log("LLC packet found")
        else:
            raise xenrt.XRTFailure("Could not find LLC packet")
            
    def verifyRARP(self):
        """CA-140817.RARP packet is sent for both dom0's MAC  and guest MAC.
        Format of packet:
        10:30:50.341194 ARP, Reverse Request who-is c8:1f:66:d9:38:71 tell c8:1f:66:d9:38:71, length 28
        10:30:50.341242 ARP, Reverse Request who-is 62:6f:cf:5f:e9:0d tell 62:6f:cf:5f:e9:0d, length 28"""
        
        res = self.host.execdom0("cat %s | grep 'ARP, Reverse Request'" % (self.FILENAME))
        if len(res.splitlines()) >= 2 and (self.guestMac in res) and (self.bondMac in res):
            log("RARP packets for both guest and dom0 MAC found")
        else:
            raise xenrt.XRTFailure("Could not find expected RARP packets. tcpdump output:%s" % (res))
            
    def postRun(self):
        self.host.removeBond(self.bond.uuid)
