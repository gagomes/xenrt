#
# XenRT: Test harness for Xen and the XenServer product family
#
# SR-IOV and other PCI pass through testcases
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, xenrt.lib.xenserver
import time, calendar, re, os, os.path
import IPy
from xenrt.lazylog import step, log

class TC12666(xenrt.TestCase):
    
    def prepare(self, arglist=None):

        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.pool.setPoolParam("other-config:pass_through_pif_carrier", "true")
        self.host.restartToolstack()
        self.host.waitForEnabled(300)

        # Identify the clock difference between host and controller (CA-72889)
        self.clockSkew = self.host.getClockSkew()

        self.pif = self.host.parseListForUUID("pif-list", 
                                              "device", 
                                              self.host.getDefaultInterface())
        self.mac = self.host.genParamGet("pif", self.pif, "MAC")
        
        self.guest = self.host.installHVMLinux(start=True)
        self.uninstallOnCleanup(self.guest)
        self.domid = self.host.getDomid(self.guest)


    def __parse_xapi_time__(self, timestamp):
        return int(calendar.timegm(time.strptime(timestamp.split('.')[0], "%Y%m%dT%H:%M:%S")))

    def __parse_syslog_time__(self, timestamp):
        # The timestamp doesn't have a year in it, so we have to insert that
        return int(calendar.timegm(time.strptime("%s %s" % (time.strftime("%Y"), timestamp), "%Y %b %d %H:%M:%S")))

    def getVIFDisconnectTime(self):
        time.sleep(30)  # Assuming that the logs are flushed.
        cmd = 'grep /local/domain/%s/device/vif/0/disconnect /var/log/xenstored-access.log | grep write | tail -n2 | head -n1' % self.domid
        try:
            log_line = self.host.execdom0(cmd).strip()
        except:
            raise xenrt.XRTError("Could not parse /var/log/xenstored-access.log")
        
        l = log_line.split()
        if len(l) == 0:
            raise xenrt.XRTError("Nothing found parsing /var/log/xenstored-access.log")
        if log_line.startswith("["):
            # Old style timestamp (e.g. [20120427T17:02:33.838Z]
            time_stamp = l[0][1:-1]
            xenstore_val = l[4]

            xenrt.TEC().logverbose(log_line)
            if xenstore_val != "1":
                raise xenrt.XRTFailure("xenstore key is not updated correctly to reflect link state (DOWN)")
        
            return self.__parse_xapi_time__(time_stamp) - self.clockSkew
        else:
            # New style timestamp (e.g. Jul  5 18:02:10)
            xenstore_val = l[-1]
            if xenstore_val != "1":
                raise xenrt.XRTFailure("xenstore key is not updated correctly to reflect link state (DOWN)")
            return self.__parse_syslog_time__("%s %s %s" % (l[0], l[1], l[2])) - self.clockSkew

    def copyScriptOntoDom0(self, script):
        tmpdir = xenrt.resources.TempDirectory()

        script_file = "%s/link_state_test.sh" % tmpdir.path()
        f = open(script_file, 'w')
        f.write(script)
        f.close()
        
        sftp = self.host.sftpClient()
        sftp.copyTo(script_file, "/tmp/link_state_test.sh")
        sftp.close()
        

    def executeScript(self):
        self.host.execdom0('chmod +x /tmp/link_state_test.sh')
        self.host.execdom0('nohup /tmp/link_state_test.sh &> /dev/null < /dev/null & exit 0')
        
    
    def generateScript(self):

        script = """#!/bin/bash

sleep 1m;
xe vm-start uuid=%(uuid)s

domid=`xe vm-param-get param-name=dom-id uuid=%(uuid)s`
carrier=`xe pif-param-get param-name=carrier uuid=%(pif)s`
disconnect=`xenstore-read /local/domain/$domid/device/vif/0/disconnect`
echo $carrier $disconnect > /tmp/link_states

xe vm-reboot uuid=%(uuid)s force=true

domid=`xe vm-param-get param-name=dom-id uuid=%(uuid)s`
carrier=`xe pif-param-get param-name=carrier uuid=%(pif)s`
disconnect=`xenstore-read /local/domain/$domid/device/vif/0/disconnect`
echo $carrier $disconnect >> /tmp/link_states


xe vm-shutdown uuid=%(uuid)s force=true
xe vm-start uuid=%(uuid)s

domid=`xe vm-param-get param-name=dom-id uuid=%(uuid)s`
carrier=`xe pif-param-get param-name=carrier uuid=%(pif)s`
disconnect=`xenstore-read /local/domain/$domid/device/vif/0/disconnect`
echo $carrier $disconnect >> /tmp/link_states

        """ % { 'uuid' : self.guest.getUUID(), 'pif' : self.pif }


        return script

#    When the Ethernet carrier disappears you should see 
#    PIF.carrier <- false and in the VIF frontends in xenstore disconnect <- 1

    def checkScriptOutput(self):
        output = self.host.execdom0('cat /tmp/link_states')
        lines = [l.strip() for l in output.splitlines()]
        if len(lines) != 3:
            raise xenrt.XRTFailure("Expected 3 lines in /tmp/link_states found only %s" % len(lines))
        for i in lines:
            l = i.split()
            if len(l) != 2:
                raise xenrt.XRTFailure("Invalid (or no) entries in /tmp/link_states")
            if l[0] != 'false':
                raise xenrt.XRTFailure("PIF carrier field is not set to false")
            if l[1] != '1':
                raise xenrt.XRTFailure("xenstore key is not updated correctly to reflect link state (DOWN)")
                

    def run(self, arglist=None):

        time_1 = xenrt.util.timenow()
        self.host.disableNetPort(self.mac)
        time.sleep(30)
        self.host.enableNetPort(self.mac)
        self.host.waitForSSH(300)
        
        time_2 = self.getVIFDisconnectTime()
        xenrt.TEC().logverbose("link was disabled at %s" % time.ctime(time_1))
        xenrt.TEC().logverbose("xenstored was updated at %s" % time.ctime(time_2))

        # CA-72889: The carrier status is checked every 5s, but the act of passing through 
        #           the update takes a bit longer
        # CA-72889: Bringing the link down does not happen immediately, be generous and allow
        #           up to 30s
        update_wait = 30

        if (time_2 - time_1) > update_wait:
            raise xenrt.XRTFailure("Time taken to update xenstored is more than %d seconds" % (update_wait))

        # Now that the link is up, this key should be 0
        xenstore_val = self.host.xenstoreRead("/local/domain/%s/device/vif/0/disconnect" % self.domid)
        if xenstore_val != "0":
            raise xenrt.XRTFailure("xenstore key is not updated correctly to reflect link state (UP)")

        self.guest.shutdown(force=True)
        script = self.generateScript()
        self.copyScriptOntoDom0(script)
        self.executeScript()
        self.host.disableNetPort(self.mac)
        time.sleep(360)
        self.host.enableNetPort(self.mac)
        self.host.waitForSSH(300)
        self.checkScriptOutput()

        
    def postRun(self):
        pass


class SRIOVTests(xenrt.TestCase):

    MAX_VF_PER_VM = 16
    
    def _setupInfrastructure(self):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master

    def prepare(self, arglist=None):

        self._setupInfrastructure()

        # Let us install/use two guests for all tests
        self._createGuests()
        self.io = self._createIO(self.host)

    def _createGuests(self):
        self.guest_01 = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest_01)
        self.guest_02 = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest_02)
   
    def _createIO(self, host):
        io = xenrt.lib.xenserver.IOvirt(host)
        io.enableIOMMU(restart_host=False)
        host.enableVirtualFunctions()
        return io

    def getSRIOVEthDevices(self):
        self.io.queryVFs()
        return self.io.getSRIOVEthDevices()


    def getFreeVFsPerEth(self, eths_to_use=None):
        
        eth_devs = self.getSRIOVEthDevices()
        eth_devs = set(eth_devs)
        log("SRIOV eths: %s" % eth_devs)

        if eths_to_use is not None:
            eths_to_use = set(eths_to_use)
            eth_devs = eth_devs.intersection(eths_to_use)

        free_vfs = {}
        for eth_dev in eth_devs:
            l = self.io.getFreeVFs(eth_dev) 
            if len(l) > 0:
                free_vfs[eth_dev] = l

        return free_vfs


    def assignVFsToVM(self, 
                           guest, 
                           n, 
                           strict=False, 
                           eths_to_use=None,
                           mac=None,
                           vlan=None):
        
        vm_uuid = guest.getUUID()
        curr_pci_assignment = self.io.getVMInfo(vm_uuid)

        #iovirt implementation modified
        #fn = lambda x: x[1].values() == 'vf'
        #curr_vf_assignment = [x[0] for x in curr_pci_assignment if fn(x)]
        curr_vf_assignment = curr_pci_assignment.keys()
        for key in curr_pci_assignment:
            if 'vf' not in curr_pci_assignment[key].values():
                curr_vf_assignment.remove(curr_pci_assignment[key])
                
        if n + len(curr_vf_assignment) > self.MAX_VF_PER_VM:
            raise xenrt.XRTError("Invalid test: max number of VF assignment (%s) > %s" 
                                 % (n + len(curr_vf_assignment), 
                                    self.MAX_VF_PER_VM))

        free_vfs_per_eth = self.getFreeVFsPerEth(eths_to_use)
        log("Free VFs per Eth: %s" % free_vfs_per_eth)

        num_free_vfs = sum([len(vfs) for vfs in free_vfs_per_eth.values()])
        log("Num of free VFs: %s" % num_free_vfs)
        
        if n > num_free_vfs:
            if strict:
                return 0 #Our assignment failed
            else:
                n = num_free_vfs
        
        times = lambda x, n : [x for i in range(n)] 

        vf_list = []
        for eth_dev, vfs in free_vfs_per_eth.items():
            vf_list.extend(zip(times(eth_dev, len(vfs)), vfs))

        for i in range(n):
            self.io.assignFreeVFToVM(vm_uuid,
                                     vf_list[i][0],
                                     vlan,
                                     mac)
        return n
                

    def unassignVFsByIndex(self, guest):
        
        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)
        
        indices = [pci_devs_assigned_to_vm[pciid]['index'] 
                   for pciid in pci_devs_assigned_to_vm.keys() 
                   if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']
    
        for index in indices:
            self.io.unassignVF(vm_uuid, index=index)

        return

    def unassignVFsByPCIID(self, guest):

        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)
        
        pciids = [pciid for pciid in pci_devs_assigned_to_vm.keys() 
                  if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']
        
        for pciid in pciids:
            self.io.unassignVF(vm_uuid, pciid=pciid)

        return

    def unassignVFsByVFnum(self, guest):

        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)
        
        vfnums = [(pci_devs_assigned_to_vm[pciid]['device'], pci_devs_assigned_to_vm[pciid]['vfnum'])
                  for pciid in pci_devs_assigned_to_vm.keys() 
                  if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']
 
        for ethdev, vfnum in vfnums:
            self.io.unassignVF(vm_uuid, ethdev=ethdev, vfnum=vfnum)

        return

    def getVFsAssignedToVM(self, guest):
        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)

        vfs_assigned = [pciid for pciid in pci_devs_assigned_to_vm.keys() 
                        if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']

        return set(vfs_assigned)


    def getVMMacsAssignedToVM(self, guest):
        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)

        macs_assigned = [pci_devs_assigned_to_vm[pciid]['mac'] 
                         for pciid in pci_devs_assigned_to_vm.keys() 
                         if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']

        
        return set(macs_assigned)

    def checkPCIDevicesInVM(self, guest):
        # make sure that vm is UP
        if guest.getState() == "UP":
            pass
        else:
            guest.start()
            guest.waitForSSH(900)

        self.io.checkPCIDevsAssignedToVM(guest)


    def checkWhetherEthDevsHaveIPs(self, guest, fail=False):
        # make sure that vm is UP
        if guest.getState() == "UP":
            pass
        else:
            guest.start()
            guest.waitForSSH(900)

        ip_addrs = self.io.getIPAddressFromVM(guest)
        xenrt.TEC().logverbose("IPs from VM: %s" % ip_addrs)
        
        eths_without_ip = [eth for (eth,ip) in ip_addrs.items() if ip == ""]
        if len(eths_without_ip) > 0:
            xenrt.TEC().logverbose("Eth devs without IP: %s" % eths_without_ip)
            if fail:
                raise xenrt.XRTFailure("some eth devices didn't get DHCP IP")
            else:
                xenrt.TEC().warning("some eth devices didn't get DHCP IP")
            

    def verifyEthDevsRemainSameOnVMlifecycleOps(self, guest):
        
        if guest.getState() == "UP":
            pass 
        else:
            guest.start()
            guest.waitForSSH(900)
        
        vf_macs_assigned = self.getVMMacsAssignedToVM(guest)
        
        eth_devs_01 = self.io.getHWAddressFromVM(guest)

        # Check MAC as seen by plugin
        if len(vf_macs_assigned - set(eth_devs_01.values())) > 0:
            xenrt.TEC().logverbose("MACs as seen by iovirt plugin: %s" % vf_macs_assigned)
            xenrt.TEC().logverbose("MACs from VM: %s" % eth_devs_01)
            raise xenrt.XRTFailure("HW addrs of eth devices in VM differ from iovirt:get_vm")

        guest.reboot()
        guest.waitForSSH(900)
        
        eth_devs_02 = self.io.getHWAddressFromVM(guest)

        # Check MAC as seen by plugin
        if len(vf_macs_assigned - set(eth_devs_02.values())) > 0:
            xenrt.TEC().logverbose("MACs as seen by iovirt plugin: %s" % vf_macs_assigned)
            xenrt.TEC().logverbose("MACs from VM: %s" % eth_devs_02)
            raise xenrt.XRTFailure("HW addrs of eth devices in VM differ from iovirt:get_vm")


        guest.shutdown(force=True)
        guest.start()
        guest.waitForSSH(900)
        eth_devs_03 = self.io.getHWAddressFromVM(guest)

        # Check MAC as seen by plugin
        if len(vf_macs_assigned - set(eth_devs_03.values())) > 0:
            xenrt.TEC().logverbose("MACs as seen by iovirt plugin: %s" % vf_macs_assigned)
            xenrt.TEC().logverbose("MACs from VM: %s" % eth_devs_03)
            raise xenrt.XRTFailure("HW addrs of eth devices in VM differ from iovirt:get_vm")

        
        if not (len(eth_devs_01) == len(eth_devs_02)
                and
                len(eth_devs_01) == len(eth_devs_03)):
            xenrt.TEC().logverbose("eth devs seen after initial boot: %s" %  eth_devs_01)
            xenrt.TEC().logverbose("eth devs seen after reboot: %s" %  eth_devs_02)
            xenrt.TEC().logverbose("eth devs seen after forced shutdown followed by start: %s" 
                                   % eth_devs_03)
            raise xenrt.XRTFailure("Eth devs lost (???) on VM lifecycle operations")
        
        return

    def run(self, arglist=None):
        raise xenrt.XRTError("Base class: run() not implemented")
        
    def postRun(self):
        if self.guest_01.getState() == "UP":
            self.guest_01.shutdown(force=True)
        self.unassignVFsByPCIID(self.guest_01)

        if self.guest_02.getState() == "UP":
            self.guest_02.shutdown(force=True)
        self.unassignVFsByPCIID(self.guest_02)
        
class ReachableAfterVfFlipFlop(SRIOVTests):
    """
    Need to run: TCNsSuppPackVerify and TC12666 prior to running this test
    """
    NUMBER_OF_FLIPS = 10
    ETHUP = "up"
    ETHDOWN = "down"
    WAIT = 900

    def _setupInfrastructure(self):
        self.host = self.getDefaultHost()
        
    def _createGuests(self):
        self.guest_01 = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest_01)

    def run(self, arglist=None):
       
        step("Assign VFs")
        pciid = self.assignVFsToVM(self.guest_01, 1)
        log("pciid: %s" % pciid)

        log("vf on vm: %s" % self.getVFsAssignedToVM(self.guest_01))

        step("Bring up host if required")
        if self.guest_01.getState() == "DOWN":
            self.guest_01.start()
            self.guest_01.waitForSSH(self.WAIT)
        
        step("Determine which eth on the VM is VF")
        eth, vfEth = self.__determineEths()
        vfip  = self.__getIPs(vfEth)

        step("Ping guest on the VF eth")
        self.__ping(vfip) 

        step("Send VF eth up and down on guest")
        for n in range(self.NUMBER_OF_FLIPS):
            [self.__sendEthernet(direction, self.guest_01, vfEth) for direction in [self.ETHDOWN, self.ETHUP]]

        step("Make sure VF eth is up on guest")
        self.__sendEthernet(self.ETHUP, self.guest_01, vfEth)

        step("Re-ping the guest on the VF eth")
        self.__ping(vfip) 
   
    def __getIPs(self, dev):
        """ Get the ip from a VM on a named device """
        ips = self.io.getIPAddressFromVM(self.guest_01)
        log("IPs : %s" % ips)
        return ips[dev].split('/')[0]

    def __determineEths(self):
        """ Determine which of the named devices is VF and which is not """
        devices = self.io.getIPAddressFromVM(self.guest_01).keys()
        eth = devices[0] 
        vfEth =devices[1] 

        if not self.__getIPs(eth) in self.guest_01.mainip:
            eth = devices[1] 
            vfEth =devices[0] 

        log("VF eth: %s ; SSH eth = %s" % (vfEth, eth))
        return (eth, vfEth)

    def __ping(self, ip):
        """ Ping an IP on the VM"""
        log("Pinging %s" % ip)
        response = self.host.execdom0("ping -c3 -w10 %s" % ip) 
        log("Ping response: %s" %response)
        return response

    def __sendEthernet(self, upDown, guest, dev):
        """Send the named eth device either up or down"""
        if not upDown in [self.ETHUP, self.ETHDOWN]:
            raise xenrt.XRTFailure("Not a valid ifconfig option - option provided was: %s" % upDown)
        log("Sending %s on %s %s" %(dev, guest, upDown))
        guest.execguest("ifconfig %s %s" % (dev, upDown))


class TC12673(SRIOVTests):
    
    def run(self, arglist=None):
            
        self.assignVFsToVM(self.guest_01, 1)
        self.guest_01.start()
        self.guest_01.waitForSSH(900)

        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" 
                               % (self.guest_01.getUUID(), vfs))

        self.checkPCIDevicesInVM(self.guest_01)
        self.checkWhetherEthDevsHaveIPs(self.guest_01)
        for i in range(3):
            self.verifyEthDevsRemainSameOnVMlifecycleOps(self.guest_01)        
        
        self.guest_01.shutdown(force=True)
        
        self.unassignVFsByPCIID(self.guest_01)
        
        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)

        if len(vfs) > 0:
            raise xenrt.XRTFailure("VFs assigned to VM (%s) when none were expected"
                                   % self.guest_01.getUUID())


class TC12674(SRIOVTests):
    
    def run(self, arglist=None):
            
        self.assignVFsToVM(self.guest_01, 2)
        self.guest_01.start()
        self.guest_01.waitForSSH(900)

        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" 
                               % (self.guest_01.getUUID(), vfs))

        self.checkPCIDevicesInVM(self.guest_01)
        self.checkWhetherEthDevsHaveIPs(self.guest_01)
        for i in range(3):
            self.verifyEthDevsRemainSameOnVMlifecycleOps(self.guest_01)        
        
        self.guest_01.shutdown(force=True)
        
        self.unassignVFsByIndex(self.guest_01)
        
        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)

        if len(vfs) > 0:
            raise xenrt.XRTFailure("VFs assigned to VM (%s) when none were expected"
                                   % self.guest_01.getUUID())


class TC12675(SRIOVTests):
    
    def run(self, arglist=None):
            
        self.assignVFsToVM(self.guest_01, 16)
        self.guest_01.start()
        self.guest_01.waitForSSH(900)

        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" 
                               % (self.guest_01.getUUID(), vfs))

        self.checkPCIDevicesInVM(self.guest_01)
        self.checkWhetherEthDevsHaveIPs(self.guest_01)
        for i in range(3):
            self.verifyEthDevsRemainSameOnVMlifecycleOps(self.guest_01)        
            
        self.guest_01.shutdown(force=True)
        
        self.unassignVFsByVFnum(self.guest_01)
        
        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)

        if len(vfs) > 0:
            raise xenrt.XRTFailure("VFs assigned to VM (%s) when none were expected"
                                   % self.guest_01.getUUID())



class TC12676(SRIOVTests):
    
    def run(self, arglist=None):
            
        self.assignVFsToVM(self.guest_01, 16)
        self.guest_01.start()
        self.guest_01.waitForSSH(900)

        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" 
                               % (self.guest_01.getUUID(), vfs))


        self.assignVFsToVM(self.guest_02, 16)
        self.guest_02.start()
        self.guest_02.waitForSSH(900)

        vfs = self.getVFsAssignedToVM(self.guest_02)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" 
                               % (self.guest_01.getUUID(), vfs))


        self.checkPCIDevicesInVM(self.guest_01)
        self.checkWhetherEthDevsHaveIPs(self.guest_01)
        for i in range(3):
            self.verifyEthDevsRemainSameOnVMlifecycleOps(self.guest_01)        


        self.checkPCIDevicesInVM(self.guest_02)
        self.checkWhetherEthDevsHaveIPs(self.guest_02)
        for i in range(3):
            self.verifyEthDevsRemainSameOnVMlifecycleOps(self.guest_02)        
            
        
        self.guest_01.shutdown(force=True)
        self.guest_02.shutdown(force=True)
        
        
        self.unassignVFsByPCIID(self.guest_01)
        self.unassignVFsByVFnum(self.guest_02)
        
        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)

        if len(vfs) > 0:
            raise xenrt.XRTFailure("VFs assigned to VM (%s) when none were expected"
                                   % self.guest_01.getUUID())

        vfs = self.getVFsAssignedToVM(self.guest_02)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)

        if len(vfs) > 0:
            raise xenrt.XRTFailure("VFs assigned to VM (%s) when none were expected"
                                   % self.guest_02.getUUID())


class TC12710(xenrt.TestCase):

    def prepare(self, arglist=None):

        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
        
        self.guest = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest)
        mac = xenrt.randomMAC()
        xenapi_uuid = self.getHostInternalNetworkUuid()
        xenapi_bridge = self.host.genParamGet("network", xenapi_uuid, "bridge")
        self.guest.createVIF(bridge=xenapi_bridge, mac=mac)
        self.guest.start()
        self.guest.waitForSSH(900)
        self.guest_uuid = self.guest.getUUID()
        self.host_uuid = self.host.getMyHostUUID()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host_uuid).strip()
        
    def getHostInternalNetworkUuid(self):
        
        xenapi_uuid = ""
        for uuid in self.host.minimalList("network-list", "uuid"):
            try:
                is_host_internal_management_network = self.host.genParamGet("network",
                                                                            uuid,
                                                                            "other-config",
                                                                            pkey="is_host_internal_management_network")
                if is_host_internal_management_network.strip() == "true":
                    xenapi_uuid = uuid.strip()
                    break
            except:
                pass

        if len(xenapi_uuid.strip()) == 0:
            raise xenrt.XRTFailure("No network found with 'is_host_internal_management_network' set to true")

        return xenapi_uuid

    def getXenapiNetworkID(self):
        
        xenapi_uuid = self.getHostInternalNetworkUuid()
        other_config = self.host.genParamGet("network", xenapi_uuid, "other-config")

        xenapi_other_config = dict([tuple(i.split(':')) 
                                   for i in other_config.replace(' ', '').split(';')])
        
        xenapi_IP = IPy.IP("%s/%s" % (xenapi_other_config['ip_begin'],
                                     xenapi_other_config['netmask']),
                          make_net=True)
        return xenapi_IP


    def getVMIPAddress(self, guest):
        
        output_lines = guest.execcmd('ip -4 -o addr show').splitlines()
        return [line.split()[3] for line in output_lines]  
    
    def heyXapiYouThere(self, guest, xenapi_ip):
        ret = self.guest.execcmd('wget -O /dev/null http://%s' % xenapi_ip, retval="code")
        if ret != 0:
            raise xenrt.XRTFailure("Xapi is not reachable from VM on %s" % xenapi_ip)
        

    def checkIfXapiIsReachable(self, guest, xenapi_ip):
        
        self.heyXapiYouThere(guest, xenapi_ip)
        self.guest.execcmd('nohup /sbin/shutdown -r now &> /dev/null < /dev/null & exit 0')
        time.sleep(180)
        guest.waitForSSH(900)
        self.heyXapiYouThere(guest, xenapi_ip)        

        
    def waitForHostToBeEnabled(self, timeout=300):
        now = xenrt.util.timenow()
        deadline = now + timeout

        while True:
            ret = self.host.execdom0('xe host-param-get param-name=enabled uuid=%s || exit 0' % 
                                     self.host_uuid).strip()
            if ret == 'true':
                return
            
            now = xenrt.util.timenow()
            if now > deadline:
                ret = self.host.execdom0('uptime')
                raise xenrt.XRTFailure('host is not enabled after the reboot')
            
            time.sleep(60)
            

    def checkIfXapiIsReachableFromExternalWorld(self):
        cli = self.host.getCLIInstance()
        try:
            cli.execute('vm-list')
        except:
            pass
        else:
            raise xenrt.XRTFailure('Xapi is reachable from external world with host management disabled')


    def run(self, arglist=None):
        
        xenapi_IP = self.getXenapiNetworkID()
        xenapi_ip = xenapi_IP[1]

        #1. Check if we can reach Xapi from VM
        self.checkIfXapiIsReachable(self.guest, xenapi_ip)

        #2. Disable management interface
        xenrt.TEC().logverbose("Disabling host management interface")
        self.host.execcmd("xe host-management-disable")

        #3. Check if we can reach Xapi from VM
        self.checkIfXapiIsReachable(self.guest, xenapi_ip)

        #4. Make sure that xapi is not reachable from outside.
        self.checkIfXapiIsReachableFromExternalWorld()
        
        for i in range(3):
        
            self.host.execdom0('shutdown -r now')
            time.sleep(180)
            self.host.waitForSSH(600)
            self.waitForHostToBeEnabled()
            self.host.execdom0('xe vm-start uuid=%s' % self.guest_uuid)
            self.guest.waitForSSH(900)
            xenrt.TEC().logverbose("VM's IPs: %s" % self.getVMIPAddress(self.guest))
            self.checkIfXapiIsReachable(self.guest, xenapi_ip)
            self.checkIfXapiIsReachableFromExternalWorld()


        
    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)



class NSBVT(xenrt.TestCase):

    CLIENT_VLAN = "VR08"
    SERVER_VLAN = "VR07"
    XVA_DIR = "ns_xvas"

    ATS_PASSWORD = "freebsd"

    # Client VMs should reside on Client VLAN 
    ATS = "ATS_10_5.xva"
    BWC1="BWC1.xva"
    BWC2="BWC2.xva"
    LCLNT1="LCLNT1.xva"
    LCLNT2="LCLNT2.xva"
    WCLNT1="WCLNT1.xva"
    
    # Server VMs that should reside on Server VLAN
    APACHE1 = "APACHE1.xva"
    APACHE2 = "APACHE2.xva"
    APACHE3 = "APACHE3.xva"
    BWS = "BWS.xva"
    IIS1 = "IIS1.xva"
    IIS2 = "IIS2.xva"
    IIS3 = "IIS3.xva"

    # NS VMs
    VPX1 = "VPX1_10_5.xva"
    VPX2 = "VPX2_10_5.xva"

    # Acceptable failures
    IGNORE_TESTS = set(['26.2.1.14'])
    PASS_TESTS = xenrt.TEC().lookup("EXPECTED_TEST_PASSES", 127)

    def getMountDir(self, mounts, src_path):
        
        for line in mounts:
            e = line.split()
            if e[0] == src_path:
                return e[1]
        
        return ""
        
        
    def mountXvaNfsDir(self, host):
        
        assert self.cfg.has_key('nfs_src')
        nfs_src = self.cfg['nfs_src']
        cur_mounts = host.execdom0("cat /proc/mounts | cut -f1,2 -d ' ' | grep '%s'" % 
                                   nfs_src).splitlines()
        
        if len(cur_mounts) != 0:
            mount_dir = self.getMountDir(cur_mounts, nfs_src)
            if len(mount_dir) != 0:
                return mount_dir

        ret = host.execdom0('mkdir -p /root/xvas; mount -o ro %s /root/xvas' % nfs_src, 
                            retval="code")
        if ret != 0:
            raise xenrt.XRTError('Could not mount %s on %s' % (nfs_src, host.getMyHostName()))
        
        return '/root/xvas'
    

    def getLocalSR(self, host):
        
        sr_list_lvm = host.minimalList("sr-list", 
                                       args="host=%s type=lvm" % host.getMyHostName())
        sr_list_ext = host.minimalList("sr-list", 
                                       args="host=%s type=ext" % host.getMyHostName())
        if sr_list_lvm:
            return sr_list_lvm[0]
        elif sr_list_ext:
            return sr_list_ext[0]
        
        raise xenrt.XRTFailure("%s doesn't have local storage" % host.getMyHostName())


    def importXVA(self, host, file_name):
        
        local_sr = self.getLocalSR(host)
        vm_uuid = host.execdom0('xe vm-import filename=%s sr-uuid=%s' % (file_name, local_sr),
                                timeout=2400).strip()
        
        return vm_uuid


    def getVlanID(self, host, vlan):
        vlan_id, subnet, netmask = host.getVLAN(vlan)
        return vlan_id


    def getVlanNetworkUuid(self, host, vlan):

        vlan_id = self.getVlanID(host, vlan)

        pif_uuid = host.parseListForUUID("pif-list", 
                                         "VLAN", 
                                         vlan_id)
        network_uuid = host.genParamGet("pif", pif_uuid, "network-uuid")
                                             
        return network_uuid
    

    def createVIF(self, host, vm_uuid, nic, network):
        
        cli = host.getCLIInstance()
        args = []
        args.append('network-uuid=%s' % network)
        args.append('vm-uuid=%s' % vm_uuid)
        args.append('device=%s' % nic)
        args.append("mac=%s" % (xenrt.randomMAC()))
        cli.execute('vif-create', ' '.join(args), strip=True)

        return


    def getPrimaryNetworkUuid(self, host):
        
        bridge = host.getPrimaryBridge()
        network_uuid = host.parseListForUUID("network-list",
                                             "bridge",
                                             bridge)

        return network_uuid


    def addVIFOnVlan(self, host, vm_uuid, vlan, nic):
            
        if vlan is None:
            network_uuid = self.getPrimaryNetworkUuid(host)
        else:
            network_uuid = self.getVlanNetworkUuid(host, vlan)

        self.createVIF(host, vm_uuid, nic, network_uuid)
        return


    def deleteAllVIFs(self, host, vm_uuid):

        vifs = host.minimalList("vif-list", args="vm-uuid=%s" % vm_uuid)
        cli = host.getCLIInstance()
        for vif in vifs:
            cli.execute("vif-destroy", "uuid=%s" % vif)

        return

        
    def createAtsGuestObject(self, host, vm_uuid):
        vm_name = host.genParamGet('vm', vm_uuid, 'name-label')
        guest = host.guestFactory()(vm_name, None)
        guest.distro = "debian60"
        guest.enlightenedDrivers = False
        guest.windows = False
        guest.tailored = True
        guest.existing(host)
        xenrt.TEC().logverbose("Found existing guest: %s" % vm_name)
        xenrt.TEC().registry.guestPut(vm_name, guest)
        guest.password = self.ATS_PASSWORD

        return guest


    def configureAtsController(self):

        ats_xva_path = os.path.join(self.cfg['clnt_nfs_dir'],
                                    self.cfg["xva_dir"],
                                    self.ATS)
        clnt = self.cfg['clnt']

        ats_uuid = self.importXVA(clnt, ats_xva_path)
        self.cfg['ats_uuid'] = ats_uuid
        self.deleteAllVIFs(clnt, ats_uuid)
        self.addVIFOnVlan(clnt, ats_uuid, self.CLIENT_VLAN, "0")
        self.addVIFOnVlan(clnt, ats_uuid, None, "1")

        self.cfg["ats"] = self.createAtsGuestObject(clnt, ats_uuid)

        return


    def configureTestVM(self, 
                          host, 
                          vlan_lst,  # Vlans on which a VIF should be placed 
                          xva_path, 
                          vm_key, 
                          start_vm):
        
        vm_uuid = self.importXVA(host, xva_path)
        self.cfg[vm_key] = vm_uuid
        self.deleteAllVIFs(host, vm_uuid)
        
        assert len(vlan_lst) != 0
        
        for i in range(len(vlan_lst)):
            nic = str(i)
            vlan = vlan_lst[i]
            self.addVIFOnVlan(host, vm_uuid, vlan, nic)
        
        if start_vm:
            cli = host.getCLIInstance()
            cli.execute('vm-start', 'uuid=%s' % vm_uuid)
        
        return


    def configureClientVM(self, xva, start_vm):
        
        xva_path = os.path.join(self.cfg['clnt_nfs_dir'],
                                self.cfg["xva_dir"],
                                xva)
        vm_key = xva.split('.')[0].strip().lower() + '_uuid'
        vlan_lst = [self.CLIENT_VLAN]
        host = self.cfg['clnt']
        
        self.configureTestVM(host, vlan_lst, xva_path, vm_key, start_vm)
        
        return
        

    def configureServerVM(self, xva, start_vm):

        xva_path = os.path.join(self.cfg['srv_nfs_dir'],
                                self.cfg["xva_dir"],
                                xva)
        vm_key = xva.split('.')[0].strip().lower() + '_uuid'
        vlan_lst = [self.SERVER_VLAN]
        host = self.cfg['srv']

        self.configureTestVM(host, vlan_lst, xva_path, vm_key, start_vm)
        
        return
    
    def configureClient(self, start_vm=True):
        
        self.cfg['clnt_nfs_dir'] = self.mountXvaNfsDir(self.cfg['clnt'])
        
        client_test_vms = [self.BWC1, self.BWC2, self.LCLNT1, self.LCLNT2, self.WCLNT1]
        for xva in client_test_vms:
            self.configureClientVM(xva, start_vm)
            
        self.configureAtsController()
        if start_vm:
            ats = self.cfg["ats"]
            ats.enlightenedDrivers = False
            ats.start()
            time.sleep(180)
            ats.waitForSSH(300, level=xenrt.RC_ERROR, desc="Waiting for ATS vm to boot")
            
        return


    def configureServer(self, start_vm=True):
        
        self.cfg['srv_nfs_dir'] = self.mountXvaNfsDir(self.cfg['srv'])
        
        server_test_vms = [self.APACHE1, self.APACHE2, self.APACHE3, self.BWS, self.IIS1, self.IIS2, self.IIS3]
        
        for xva in server_test_vms:
            self.configureServerVM(xva, start_vm)

        return

    def configureNSVPX(self, xva, start_vm):

        xva_path = os.path.join(self.cfg['ns_nfs_dir'],
                                self.cfg["xva_dir"],
                                xva)
        vm_key = xva.split('.')[0].strip().lower() + '_uuid'
        vlan_lst = [self.CLIENT_VLAN, self.SERVER_VLAN]
        host = self.cfg['ns']

        self.configureTestVM(host, vlan_lst, xva_path, vm_key, start_vm)

        return


    def configureNSHost(self, start_vm=True):
        
        self.cfg['ns_nfs_dir'] = self.mountXvaNfsDir(self.cfg['ns'])

        vpx_vms = [self.VPX1, self.VPX2]

        for xva in vpx_vms:
            self.configureNSVPX(xva, start_vm)
        
        return

    
    def getTestIDFromAts(self):
        
        ats = self.cfg["ats"]
        test_id = ats.execcmd("su atsuser -c 'cat /home/atsuser/www/cgi-bin/1'").strip()
        if not re.search(self.expected_id, test_id) : raise xenrt.XRTError("Wrong Test ID %s generated" %(test_id))
        return test_id

        
    def parseTestResults(self):
        
        if self.cfg.has_key('test_results'):
            return self.cfg['test_results']
        
        test_id = self.getTestIDFromAts()
        result_file = os.path.join(self.cfg['sanity_log_dir'], 
                                   'Result', 
                                   test_id,
                                   'SANITY_sanity.result')
        
        test_results = dict()

        # Test case Id : Description : Test result
        fd = open(result_file)
        for line in fd:
            fields = line.split(':')
            if len(fields) != 3:
                continue
            test_results[fields[0].strip()] = (fields[1].strip(), fields[2].strip()) 
        
        fd.close()

        self.cfg['test_results'] = test_results

        return test_results


    def spitResultsOntoLog(self, results=None):
        
        if results is None:
            results = self.parseTestResults()
            
        for tc_id, val in results.items():
            xenrt.TEC().logverbose("%s  %s  %s" % (tc_id, val[0], val[1]))

        return


    def getTestStatus(self):
        
        results = self.parseTestResults()
        failed_tests = dict()
        passed_tests = dict()
        for tc_id in results.keys(): 
            if results[tc_id][1] == 'FAILED':
                failed_tests[tc_id] = results[tc_id]
            elif results[tc_id][1] == 'PASSED':
                passed_tests[tc_id] = results[tc_id]

        return (failed_tests,passed_tests)


    def createSanityLogDir(self):

        ats = self.cfg["ats"]
        base = xenrt.TEC().getLogdir()
        d = "%s/%s" % (base, ats.getName())
        if not os.path.exists(d):
            os.makedirs(d)
        
        sanity_log_dir = os.path.join(d, "sanity")
        os.makedirs(sanity_log_dir)
        self.cfg['sanity_log_dir'] = sanity_log_dir

        return


    def getTestLogsFromAts(self):
        
        self.createSanityLogDir()
        ats = self.cfg['ats']

        sanity_dir = self.cfg['sanity_log_dir']
        log_dir = os.path.join(sanity_dir, "Log")
        suite_dir = os.path.join(sanity_dir, "Suite")
        result_dir = os.path.join(sanity_dir, "Result")

        os.makedirs(log_dir)
        os.makedirs(suite_dir)
        os.makedirs(result_dir)
        
        sftp = ats.sftpClient()
        
        sftp.copyTreeFromRecurse('/home/atsuser/Log', log_dir)
        sftp.copyTreeFromRecurse('/home/atsuser/Suite', suite_dir)
        sftp.copyTreeFromRecurse('/home/atsuser/Result', result_dir)
        
        #ats.execcmd("su atsuser -c '/home/atsuser/www/cgi-bin/collect_vpx_logs '", 
        #            retval='code')
        
        sftp.copyFrom('/home/atsuser/vpx1.tgz', os.path.join(sanity_dir, 'vpx1.tgz'))
        sftp.copyFrom('/home/atsuser/vpx2.tgz', os.path.join(sanity_dir, 'vpx2.tgz'))
        
        sftp.close()
        
        return
        

    def pollTestStatus(self, timeout=180): # timout in minutes
        
        ats = self.cfg["ats"]
        out = ""
        xenrt.TEC().logverbose("Polling for test results every 10 mins")
        for i in range(timeout / 10 + 1):
            out = ats.execcmd("cd /home/atsuser/www/cgi-bin/; perl ns-sanity.pl STATUS ",
                              username='atsuser', password="atsuser")
            if out.strip() != 'RUNNING':
                break 
            time.sleep(60 * 10)

        return out.strip()

        
    def startTest(self):
        
        ats = self.cfg["ats"]
        xenrt.TEC().logverbose("Starting NS Sanity test run")
        
        self.expected_id = "Test-" + ats.execcmd("date +%Y_%m_%d",username='atsuser', password="atsuser").strip()
        out = ats.execcmd("cd /home/atsuser/www/cgi-bin/; perl ns-sanity.pl START ", 
                          username='atsuser',
                          retval='code', 
                          password='atsuser')
        if out != 0:
            raise xenrt.XRTFailure("NS sanity test failed to start")
        
        return

        
    def stopTest(self):
        
        ats = self.cfg["ats"]
        xenrt.TEC().logverbose("Stopping NS Sanity test run")
        
        out = ats.execcmd("cd /home/atsuser/www/cgi-bin/; perl ns-sanity.pl STOP ", 
                          username='atsuser',
                          retval='code',
                          password='atsuser')
        if out != 0:
            raise xenrt.XRTFailure("NS sanity test failed to stop")
        
        return

    def prepare(self, arglist=None):
        
        self.cfg = {}
        self.cfg["clnt"] = self.getHost("RESOURCE_HOST_0")
        self.cfg["ns"] = self.getHost("RESOURCE_HOST_1")
        self.cfg["srv"] = self.getHost("RESOURCE_HOST_2")
        
        nfs_src = xenrt.TEC().lookup("NS_XVA_SOURCE_NFS", None)
        if nfs_src is None:
            raise xenrt.XRTError('NFS directory for NS XVAs not defined!')
        self.cfg["nfs_src"] = nfs_src
        self.cfg["xva_dir"] = self.XVA_DIR
        
        self.configureServer()
        self.configureNSHost()
        self.configureClient()

        #CHECKME: We need a mechanism to verify that all the VMs are in a usable state
        
        return


    def testsExpectedToFail(self, failed_tests):
        for test_id in failed_tests.keys():
            if test_id not in self.IGNORE_TESTS:
                return False
        return True

        
    def run(self, arglist=None):
        
        # A little wait can do wonders
        time.sleep(60 * 5)
        
        # Let us reset the Sanity Test Bed status
        try:
            self.stopTest()
        except:
            pass
        
        self.startTest()

        # A little wait can do wonders
        time.sleep(60 * 10)
        status = self.pollTestStatus()
        if status == 'RUNNING':
            self.stopTest()
            
        self.getTestLogsFromAts()
        self.spitResultsOntoLog()

        xenrt.TEC().logverbose("Sanity test status is %s" % status)
        
        failed_tests,passed_tests = self.getTestStatus()
        
        #Currently there are 128 tests cases running, out of which 127 test cases should pass
        if len(passed_tests) < self.PASS_TESTS :
            raise xenrt.XRTFailure("NS Sanity test failed since we did not get %s pass results." %(self.PASS_TESTS))
        
        if status == 'FAILED':
            if not self.testsExpectedToFail(failed_tests):
                raise xenrt.XRTFailure("NS Sanity test failed")
        elif status != 'PASSED':
            raise xenrt.XRTFailure("NS Sanity test failed")

    def postRun(self):
        
        self.cfg["clnt"].poweroff()
        self.cfg["ns"].poweroff()
        self.cfg["srv"].poweroff()


class TC14935(xenrt.TestCase):
    """Xen scheduler timeslice can be overriden to 10ms."""
    
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

        self.host.execdom0("test -e /boot/extlinux.conf")

        # Back up extlinux.conf
        self.host.execdom0("cp /boot/extlinux.conf /boot/extlinux.conf.10mstest")

    def run(self, arglist):
        # Add 10ms timeslice option to hypervisor args
        extconf = self.host.execdom0("cat /boot/extlinux.conf")
        extconf = re.sub("(append\s+\S+xen\S+\s+)", r"\1 sched_credit_tslice_ms=10 ", extconf)
        gfile = xenrt.TEC().tempFile()
        file(gfile, "w").write(extconf)
        sftp = self.host.sftpClient()
        sftp.copyTo(gfile, "/boot/extlinux.conf")
        sftp.close()

        # Reboot and check the timeslice is reported as 10ms. Note we
        # cannot easily check this is enforced but the main threat here
        # is losing the patch which makes the timeslice tunable.
        self.host.reboot()
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            self.host.execdom0("xl debug-keys r")
        else:
            self.host.execdom0("/opt/xensource/debug/xenops debugkeys r")
            
        dmesg = self.host.execdom0("xe host-dmesg uuid=%s" % (self.host.getMyHostUUID()))
        r = re.search(r"\stslice\s+=\s+(\d+)ms", dmesg)
        if not r:
            raise xenrt.XRTFailure("No tslice reported in debug-q output")
        if r.group(1) != "10":
            raise xenrt.XRTFailure("Reported tslice %sms is not 10ms" %
                                   (r.group(1)))

    def postRun(self):
        if self.host:
            # Restore extlinux.conf
            self.host.execdom0("if [ -e /boot/extlinux.conf.10mstest ]; then  "
                               "  cp /boot/extlinux.conf.10mstest /boot/extlinux.conf; "
                               "fi")
            self.host.reboot()

class TCNsSuppPack(xenrt.TestCase):

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

    def getSourcesFromP4(self):
        '''Sync the NS-SDX supplemental pack source code from NetScaler perforce server'''

        # Get the perforce command line client (32bit or 64bit) tool: p4
        arch = self.ddkVM.execguest('uname -m').strip()
        if arch == 'x86_64':
            p4File = xenrt.TEC().getFile('/usr/groups/xenrt/perforce/x86_64/p4')
        else:
            p4File = xenrt.TEC().getFile('/usr/groups/xenrt/perforce/x86/p4')

        sftp = self.ddkVM.sftpClient()
        try:
            sftp.copyTo(p4File, '/usr/bin/p4')
        except:
            raise xenrt.XRTError("Failed to sftp perforce binary to ddkVM")
        finally:
            sftp.close()

        self.ddkVM.execguest("chmod +x /usr/bin/p4")

        # Get NetScaler perforce server credentials
        p4user = xenrt.TEC().lookup("NS_P4_USERNAME")
        p4passwd = xenrt.TEC().lookup("NS_P4_PASSWORD")
        p4client = xenrt.TEC().lookup("NS_P4_CLIENT")
        p4port = xenrt.TEC().lookup("NS_P4_PORT")

        # setup the p4 environment in the ddkVM
        p4config_cmd = 'echo "export P4USER=%s; export P4PASSWD=%s; export P4CLIENT=%s; export P4PORT=%s"  >> /root/.bash_profile' % (p4user, p4passwd, p4client, p4port)
        self.ddkVM.execguest(p4config_cmd)

        # Force sync because multiple ddk vm's will be using the same p4 client and without force sync, the checkout will be unpredictable
        self.ddkVM.execguest('source /root/.bash_profile; p4 sync -f //depot/SDX/main/supp-pack/xs-netscaler/...')


    def run(self, arglist):
        self.getSourcesFromP4()
        self.ddkVM.execguest('make -C xs-netscaler > install.log 2>&1')

        self.workdir = "/root/xs-netscaler/output"

        # Create a tmp directory on the controller that will be automatically cleaned up
        ctrlTmpDir = xenrt.TEC().tempDir()

        sourcePath = self.ddkVM.execguest("find /root/xs-netscaler/output/ -iname xs-netscaler*iso -type f").strip()
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
        
        # Perform the platform_check function
        self.command = "xe host-call-plugin plugin=nicaea "\
                        "host-uuid=%s fn=%s" \
            % (self.host.getMyHostUUID(), "platform_check")
        cli = self.host.getCLIInstance()

        result = self.host.execdom0(self.command).strip()
        xenrt.TEC().logverbose("Response from nicaea plugin: %s" % (result))
        if len(result) > 0:
            raise xenrt.XRTFailure("NS nicaea plugin is not correctly installed")
        
    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
        # Fetch the make logfile if available
        sftp = self.ddkVM.sftpClient()
        sftp.copyFrom('install.log', '%s/ns-make-log' % (xenrt.TEC().getLogdir()))         
        

class TC18604(xenrt.TestCase):

    allocatedIPAddrs = []
    
    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
            
        self.host_uuid = self.host.getMyHostUUID()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host_uuid).strip()

        xenrt.TEC().logverbose("Disabling host management interface")
        self.host.execcmd("xe host-management-disable")

        return
    
    def importNsXva(self, host, xva):
        distfiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        host.execdom0('mkdir -p /mnt/distfiles')
        host.execdom0('mount %s /mnt/distfiles' % distfiles)

        try:
            vm_uuid =  host.execdom0('xe vm-import filename=/mnt/distfiles/tallahassee/%s' % xva).strip()
        except:
            raise xenrt.XRTFailure("Import of XVA failed with management interface disabled")

        gName = xenrt.randomGuestName()
        host.execdom0('xe vm-param-set uuid=%s name-label=%s' % (vm_uuid, gName))
        host.execdom0('umount /mnt/distfiles; exit 0')

        s_obj = xenrt.StaticIP4Addr()
        (_, netmask, gw) = host.getNICAllocatedIPAddress(0)
        self.allocatedIPAddrs.append(s_obj)
        ip = s_obj.getAddr()

        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/ip=%s" % (vm_uuid, ip))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/netmask=%s" % (vm_uuid, netmask))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/gateway=%s" % (vm_uuid, gw))

        vpx = host.guestFactory()(gName, host=host)
        vpx.uuid = vm_uuid
        vpx.mainip = ip
        vpx.password = 'nsroot' 

        return vpx

    def run(self, arglist=None):
        vpx = self.importNsXva(self.host, "NSVPX-XEN-10.0-72.5_nc.xva")
        state = self.host.execdom0("xe vm-param-get uuid=%s param-name=power-state" % vpx.uuid).strip()
        
        if state.lower() <> "running":
            self.host.execdom0("xe vm-start uuid=%s" % vpx.uuid)
            vpx.waitForSSH(600, desc="Waiting for NS VPX to boot", username="nsroot", cmd="shell true")
            
        vpx.execguest('show ns ip', username='nsroot')
        return

    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
        for s_obj in self.allocatedIPAddrs:
            s_obj.release()
        self.host.execdom0("grep /mnt/distfiles /proc/mounts && umount /mnt/distfiles; exit 0")
        return


class NSSRIOV(SRIOVTests):
    
    # We have to release all the allocated IPv4 address 
    ALLOCATED_IPADDRS = []
    NS_XVA = "NSVPX-XEN-10.5-52.11_nc.xva"
    GOLDEN_VM = None
    NETWORK = 'NPRI' # 'NSEC'; Orjen has SR-IOV nics on NSEC
    
    def allocateIPv4Addr(self):
        s_obj = xenrt.StaticIP4Addr(network=self.NETWORK)
        self.ALLOCATED_IPADDRS.append(s_obj)
        return s_obj.getAddr()

    def getNetmaskAndGW(self, host):
        if self.NETWORK == "NPRI":
            config = ["NETWORK_CONFIG", "DEFAULT"]
        elif self.NETWORK == "NSEC":
            config = ["NETWORK_CONFIG", "SECONDARY"]
        else:
            raise xenrt.XRTError("Only NPRI or NSEC can be used")
        
        gw = host.lookup(config + ['GATEWAY'])
        netmask = host.lookup(config + ['SUBNETMASK'])
        return (gw, netmask)

    def importNsXva(self, host, xva, name="GOLDENIMG"):
        distfiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        host.execdom0('mkdir -p /mnt/distfiles')
        host.execdom0('mount %s /mnt/distfiles' % distfiles)

        try:
            vm_uuid =  host.execdom0('xe vm-import filename=/mnt/distfiles/tallahassee/%s' % xva).strip()
        except:
            raise xenrt.XRTFailure("Import of XVA failed with management interface disabled")

        host.genParamSet("vm", vm_uuid, "name-label", name)
        host.execdom0('umount /mnt/distfiles; exit 0')
            
        (gw, netmask) = self.getNetmaskAndGW(host)
        
        ip = '192.168.0.2' # We use GOLDENIMG only for cloning new VMs from it

        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/ip=%s" % (vm_uuid, ip))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/netmask=%s" % (vm_uuid, netmask))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/gateway=%s" % (vm_uuid, gw))

        vpx = host.guestFactory()(name, host=host)
        xenrt.TEC().registry.guestPut(name, vpx)
        
        vpx.uuid = vm_uuid
        vpx.mainip = ip
        vpx.password = 'nsroot' 

        return vpx

    def getLicenseFile(self):
        lic = "CNS_V3000_SERVER_PLT_Retail.lic"
        out = os.path.join("/",lic)
        step ("Mounting NFS Share to copy lic file to host")

        distfiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        self.host.execdom0('mkdir -p /mnt/distfiles')
        self.host.execdom0('mount %s /mnt/distfiles' % distfiles)
        self.host.execdom0('cp /mnt/distfiles/tallahassee/%s %s' %(lic,out)).strip()

        step("Copying contents of out to selflicense_file")

        self.license_file = out.strip()
        xenrt.TEC().logverbose("license file is %s" %(self.license_file))

        step("unmount the NFS Share")
        self.host.execdom0('umount /mnt/distfiles')

    def installLicense(self, vpx):
    
        step("Checking if VPX already has license")
            
        if hasattr(self, 'license_file') and self.license_file is not None:
            pass
        
        else:
            self.license_file = self.getLicenseFile()

        
        step("Create a tmp directory on the controller that will be automatically cleaned up...........")

        ctrlTmpDir = xenrt.TEC().tempDir()

        step("Copy the license file from / on host to a temp directory on controller")
        filePathController = os.path.basename(self.license_file)
        sftp = self.host.sftpClient()

        sftp.copyFrom(self.license_file, os.path.join(ctrlTmpDir,filePathController))
        sftp.close()

        step("copy license file from tempdir on controller to guest...........")

        if vpx.getState() != "UP":
            self.startVPX(vpx)
            
        sftp = vpx.sftpClient(username='nsroot')
        
        sftp.copyTo(os.path.join(ctrlTmpDir,filePathController), os.path.join('/nsconfig/license',os.path.basename(filePathController)))
        sftp.close()
        
        
        vpx.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        self.rebootVPX(vpx)
        return

    def prepVpxForFirstboot(self, host, vpx):
        ip = self.allocateIPv4Addr()
        vpx_uuid=vpx.getUUID()
        host.genParamSet("vm", vpx_uuid, 'xenstore-data', ip, pkey='vm-data/ip')
        vpx.mainip = ip
        vpx.password = 'nsroot'
        return

    def getGoldenVM(self, host):
        
        g = xenrt.TEC().registry.guestGet('GOLDENIMG')
        if g is not None:
            return g
        return self.importNsXva(host, self.NS_XVA)
    
    def configureVPXIPs(self, host, vpx, vip=None, snip=None):
        
        (_, netmask) = self.getNetmaskAndGW(host)
        if vip:
            vpx.execguest('add ip %s %s -type vip' % (vip, netmask), username='nsroot')
        if snip:
            vpx.execguest('add ip %s %s -type snip' % (snip, netmask), username='nsroot')

        return

    def startVPX(self, vpx, sleep=60):
        if vpx.getState() != "UP":
            vpx.lifecycleOperation("vm-start")
            vpx.waitForSSH(600, 
                           desc="Waiting for %s to boot" % vpx.getName(), 
                           username="nsroot", 
                           cmd="show ns ip")
            time.sleep(sleep) # time for PV drivers to settle down
        return

    def rebootVPX(self, vpx, sleep=60):
        if vpx.getState() == "UP":
            time.sleep(10)
            vpx.lifecycleOperation("vm-reboot")
            vpx.waitForSSH(600, 
                           desc="Waiting for %s to reboot" % vpx.getName(), 
                           username="nsroot", 
                           cmd="show ns ip")
            time.sleep(sleep) # time for PV drivers to settle down
        return
            
    def getTrafficGenVM(self, host):
        g = xenrt.TEC().registry.guestGet('TRAFFICGEN')
        if g is not None:
            g.password = 'nsroot'
            g.tailored = True
            if g.getState() != "UP":
                self.startVPX(g)
            return g
        
        gold = self.getGoldenVM(host)
        t_vm = gold.cloneVM(name='TRAFFICGEN')
        xenrt.TEC().registry.guestPut('TRAFFICGEN', t_vm)

        # IP address configuration
        s_obj = xenrt.StaticIP4Addr(network=self.NETWORK)
        ip = s_obj.getAddr()
        t_uuid = t_vm.getUUID()
        host.genParamSet("vm", t_uuid, 'xenstore-data', ip, pkey='vm-data/ip')
        t_vm.mainip = ip
        t_vm.password = 'nsroot'
        t_vm.tailored = True
        
        # License installation
        self.installLicense(t_vm)
        
        # Configure NS_VIP and NS_SNIP
        t_vm.NS_VIP = xenrt.StaticIP4Addr(network=self.NETWORK).getAddr()
        t_vm.NS_SNIP = xenrt.StaticIP4Addr(network=self.NETWORK).getAddr()
        self.configureVPXIPs(host, t_vm, vip=t_vm.NS_VIP, snip=t_vm.NS_SNIP)
        t_vm.execguest('save ns config', username='nsroot')
        t_vm.execguest('show ns ip', username='nsroot')
        return t_vm

    def getTestVPX(self, host, name=None):
        gold = self.getGoldenVM(host)
        vpx = gold.cloneVM(name=name)
        self.prepVpxForFirstboot(host, vpx)
        self.installLicense(vpx)
        vpx.NS_VIP = self.allocateIPv4Addr()
        self.configureVPXIPs(host, vpx, vip=vpx.NS_VIP)
        vpx.execguest('save ns config', username='nsroot')
        vpx.execguest('show ns ip', username='nsroot')
        return vpx

    def enableSRIOV(self, host):
        iovirt = xenrt.lib.xenserver.IOvirt(host)
        iovirt.enableIOMMU(restart_host=False)
        host.enableVirtualFunctions()
        return iovirt
        
    def assignVFs(self, iovirt, vpx, eths):
        """Assign a VF from each eth(PF)."""
        
        # For VPX 10.0, max VF per VPX is 8
        for eth in eths:
            iovirt.assignFreeVFToVM(vpx.getUUID(), eth)
        return

    # unassignVFsByIndex(vpx)
    
    def addMacToVFs(self, guest, index=None, mac=None): 
        #if index arguement NULL, then error
        vm_uuid = guest.getUUID()
        return self.io.addMacToVFsByIndex(vm_uuid, index, mac)
    
    def getAdditionalMac(self, guest):
        pci_devs_assigned_to_vm = self.io.getVMInfo(guest.getUUID())
        if pci_devs_assigned_to_vm.values()[0].has_key('additionalmac'):
            xenrt.TEC().logverbose("Additional MAC %s verified" % pci_devs_assigned_to_vm.values()[0]['additionalmac'])
        else:
            xenrt.XRTFailure("No additionalmac entry for the guest %s " % guest.name)
        return pci_devs_assigned_to_vm.values()[0]['additionalmac']
        
    def delMacToVFs(self, guest, index=None, mac=None):
        #if index arguement NULL, then error
        vm_uuid = guest.getUUID()
        self.io.delMacToVFsByIndex(vm_uuid, index, mac)
        return
        
        
        
    def assignVipToVPX(self, host, guest):
        s_obj = xenrt.StaticIP4Addr()
        (_, netmask, gw) = host.getNICAllocatedIPAddress(0)
        self.ALLOCATED_IPADDRS.append(s_obj)
        ip = s_obj.getAddr()
        self.command = 'add ns ip ' + ip + ' ' + netmask + ' -type VIP'
        guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout =20, cmd='sh ns ip', username='nsroot')
        return ip
    
    def assignSnipToVPX(self, host, guest):
        s_obj=xenrt.StaticIP4Addr()
        (_, netmask, gw) = host.getNICAllocatedIPAddress(0)
        self.ALLOCATED_IPADDRS.append(s_obj)
        ip=s_obj.getAddr()
        self.command = 'add ns ip ' + ip + ' ' + netmask + ' -type SNIP'
        guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout =20, cmd='sh ns ip', username='nsroot')
        return ip
    
    def changeMacOfVFs(self, guest, index=None, mac=None): 
        #if index arguement NULL, then error
        vm_uuid = guest.getUUID()
        self.io.changeMacOfVFsByIndex(vm_uuid, index, mac)
        return
        
    def addVridToVF(self, guest, num):
        self.command = 'add vrid ' + num
        guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout =20, cmd='sh ns ip', username='nsroot')
        return
        
    def getVFInterfaceList(self, guest):
        list=[]
        ret = guest.execguest('sh int summary', 'nsroot')
        for i in range(len(ret.splitlines())):
            if "10G Virtual" in ret.splitlines()[i]:
                list.append(ret.splitlines()[i].split()[1])
        return list
        
    def bindVridToVF(self, guest, num, int):
        self.command = 'bind vrid ' + num + ' if '+ int
        guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout =20, cmd='sh ns ip', username='nsroot')
        return
        
    def getVmacOfInt(self, guest, int, level=xenrt.RC_FAIL):
        self.command = "sh int "+ int
        res = guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout =20, cmd='sh ns ip', username='nsroot', level = level)
        vmac = re.findall(r'VMAC=(.+)', res)
        xenrt.TEC().logverbose(vmac)
        return vmac[0]
    
    def addStaticArp(self, guest, ip, int, mac):
        self.command = 'add arp -ip %s -ifnum %s -mac %s'%(ip, int, mac)
        guest.execguest(self.command, 'nsroot')
        guest.waitForSSH(timeout = 20, cmd='sh ns ip', username = 'nsroot')
        return 
        
    def postRun(self):

        for s_obj in self.ALLOCATED_IPADDRS:
            s_obj.release()
        return


class NSBasic(NSSRIOV):
    
    testVPXs = []
    iovirt = None
    sriov_eths = []
    
    def createTestVPXs(self, vpx_ids):
        self.testVPXs = [self.getTestVPX(self.host, name='VPX%03d' % int(i)) for i in vpx_ids]
        return

    def shutVPXs(self):
        for vpx in self.testVPXs:
            vpx.shutdown()
        return
    
    def startVPXs(self):
        for vpx in self.testVPXs:
            self.startVPX(vpx, sleep=0)
        time.sleep(60)
        return
    
    def rebootVPXs(self):
        for vpx in self.testVPXs:
            self.rebootVPX(vpx, sleep=0)
        time.sleep(60)
        return

    def assignVFstoVPXs(self):
        eth_devs = self.sriov_eths
        eth_devs = eth_devs[:8] # each VPX can have only 8 VFs
        xenrt.TEC().logverbose("Assigning %d VFs per VPX" % len(eth_devs))
        for vpx in self.testVPXs:
            self.assignVFs(self.iovirt, vpx, eth_devs)
        return
            
    def rebootVPXsFromInside(self):
        for vpx in self.testVPXs:
            vpx.execguest('shell reboot', username='nsroot', retval='code')
        
        time.sleep(60)
        
        for vpx in self.testVPXs:
            vpx.waitForSSH(600, 
                           desc="Waiting for %s to reboot" % vpx.getName(), 
                           username="nsroot", 
                           cmd="show ns ip")
        return

    def checkReachability(self):
        ping_failed = False
        for vpx in self.testVPXs:
            if self.traffic_vm.execguest('ping -c 3 %s' % vpx.NS_VIP, username='nsroot', retval='code') <> 0:
                xenrt.TEC().logverbose('PING %s [%s] [%s] failed' % (vpx.getName(), vpx.NS_VIP, vpx.getUUID()))
                ping_failed = True
            else:
                self.traffic_vm.execguest('show arp', username='nsroot')
                
        if ping_failed:
            raise xenrt.XRTFailure('PING VIP failed on one or more VPX(s)')
        return 

    def displayINTsandIPs(self):
        for vpx in self.testVPXs:
            xenrt.TEC().logverbose('Interface and IPs for %s' % vpx.getName())
            vpx.execguest('show int -summary', username='nsroot')
            vpx.execguest('show ns ip', username='nsroot')
        return

    def prepare(self, arglist=[]):

        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master

        for arg in arglist:
            if arg.startswith('VPX'):
                (_, _, vpx_ids) = arg.partition('=')
                vpx_ids = eval(vpx_ids)
            
        self.iovirt = self.enableSRIOV(self.host)
        
        self.golden_vm = self.getGoldenVM(self.host)
        self.traffic_vm = self.getTrafficGenVM(self.host)

        # hard coded values
        vpx_ids = range(49) # We'll create only (49 + 1) VPX
        self.sriov_eths = self.iovirt.getSRIOVEthDevices()
        
        self.createTestVPXs(vpx_ids)
        return


    def run(self, arglist=[]):
        
        self.shutVPXs()
        self.assignVFstoVPXs()
        self.startVPXs()
        self.displayINTsandIPs()
        self.checkReachability()

        for i in range(3): # This is bit of random
            self.shutVPXs()
            self.traffic_vm.shutdown()
            self.host.reboot()
            self.host.waitForSSH(600, desc='Waiting for host to reboot')
            self.host.waitForXapi(600, desc="Xapi startup post reboot")
            self.startVPXs()
            self.startVPX(self.traffic_vm)
            self.displayINTsandIPs()
            self.checkReachability()
            self.rebootVPXsFromInside()
            self.displayINTsandIPs()
            self.checkReachability()
            
        return
    
class TC18781(NSBasic):
    pass

class TC18553(NSSRIOV):
    """Assign VFs to 110 VPXs"""
    NUM_VPX_INSTANTS = 110

    def prepare(self, arglist=None):
        pass


    def run(self, arglist=None):
        self.guest=[]
        i=0
        for i in range(self.NUM_VPX_INSTANTS):
            self.guest.append(self.GOLDEN_VM.cloneVM())
            self.uninstallOnCleanup(self.guest[i])
            self.prepVpxForFirstboot(self.host,self.guest[i])
            vfs=self.assignVFsToVM(self.guest[i],1)
            xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" % (self.guest[i].getUUID(), vfs))
            xenrt.TEC().logverbose("The password was (%s)" % (self.guest[i].password))
            self.guest[i].lifecycleOperation("vm-start")
            #self.checkPCIDevicesInVM(self.guest[i],level=xenrt.RC_OK, username='nsroot')
            #self.checkWhetherEthDevsHaveIPs(self.guest[i])
            self.guest[i].waitForSSH(timeout=900, cmd='sh ns ip', username='nsroot')
            self.installLicense(self.guest[i])
        return
        
class TC18685(NSSRIOV):
    """Add and remove additional MAC address with the VF currently in use by a running VPX"""
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.io = xenrt.lib.xenserver.IOvirt(self.host)
        self.io.enableIOMMU(restart_host=False)
        self.host.enableVirtualFunctions()
        self.GOLDEN_VM = self.importNsXva(self.host, "NSVPX-XEN-10.0-72.5_nc.xva")
        self.TraffGen = self.GOLDEN_VM.cloneVM(name ='Traffic Generator VPX')
        self.prepVpxForFirstboot(self.host,self.TraffGen)
        vfsForTraffGen=self.assignVFsToVM(guest=self.TraffGen,n=1)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" % (self.TraffGen.getUUID(), vfsForTraffGen))
        self.TraffGen.lifecycleOperation("vm-start")
        self.TraffGen.waitForSSH(timeout=900, cmd='sh ns ip', username='nsroot')
        self.installLicense(self.TraffGen)
        #self.uninstallOnCleanup(self.TraffGen)
        self.Target = self.GOLDEN_VM.cloneVM(name ='Target VPX')
        self.prepVpxForFirstboot(self.host,self.Target)
        vfsForTarget=self.assignVFsToVM(guest=self.Target,n=1) 
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" % (self.Target.getUUID(), vfsForTarget))
        self.Target.lifecycleOperation("vm-start")
        self.Target.waitForSSH(timeout=900, cmd='sh ns ip', username='nsroot')
        self.installLicense(self.Target)
        #self.uninstallOnCleanup(self.Target)

    def run(self,arglist=None):
        
        traffGenVIP = self.assignVipToVPX(self.host, self.TraffGen)#TfcGen VIP
        self.Target.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        targetVIP=self.assignVipToVPX(self.host, self.Target)#Target VIP
        self.assignSnipToVPX(self.host, self.TraffGen)#TfcGen SNIP
        num = str(xenrt.random.randint(1,255)) #VRID Number can be allowed between 1 to 255
        self.addVridToVF(self.Target, num)#Target vrid to interface "int = 10/1"
        list = self.getVFInterfaceList(self.Target)
        int = xenrt.random.choice(list)
        self.bindVridToVF(self.Target, num, int) #get the 10G int
        time.sleep(10)
        vmac = self.getVmacOfInt(self.Target, int)#extract VMAC
        pci_devs_assigned_to_vm = self.io.getVMInfo(self.Target.getUUID())#get index of VF
        if len(pci_devs_assigned_to_vm):
            index = pci_devs_assigned_to_vm.values()[0]['index']
        else: 
            xenrt.XRTError("VF not assignable in available eth devices. Please check with the configuration")
        ret = self.addMacToVFs(self.Target,index,vmac)#assign the additional VMAC
        if ret[0] == 'OK':
            xenrt.TEC().logverbose("Additional MAC assigned successfully")
        else:
            xenrt.XRTFailure("Error message: '%s'" % ret[1])
        
        self.addStaticArp(self.TraffGen,targetVIP, int, vmac)#add static ARP with ip, MAC, interface
        self.command = 'ping -c 3 %s' % targetVIP #ping and verify 
        if (self.TraffGen.execguest(self.command,'nsroot')):
            xenrt.TEC().logverbose("Traffic Generator can ping the Target using the 10G Interface")
        
        self.delMacToVFs(self.Target,index,vmac)
        if self.getVmacOfInt(self.Target, int) is not None:
            
            xenrt.XRTError("Error removing VMAC")
        xenrt.TEC().logverbose("VMAC ID is removed from running VPX" )
        return 
        
    def postRun(self):
        s_obj = xenrt.StaticIP4Addr() 
        for s_obj in self.ALLOCATED_IPADDRS:
            s_obj.release()
        self.Target.uninstall()
        self.TraffGen.uninstall()
        self.GOLDEN_VM.uninstall()
        
        
class TC18822(TC18685):
    """Add and remove additional MAC address with the VF currently assigned to a VPX not currently running"""
    
    def run(self,arglist=None):
        
        self.TraffGen.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        traffGenVIP = self.assignVipToVPX(self.host, self.TraffGen)#TfcGen VIP
        
        self.Target.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        targetVIP=self.assignVipToVPX(self.host, self.Target)#Target VIP
        
        self.assignSnipToVPX(self.host, self.TraffGen)#TfcGen SNIP
        
        num = str(xenrt.random.randint(1,255)) #VRID Number can be allowed between 1 to 255
        self.addVridToVF(self.Target, num)#Target vrid 
        list = self.getVFInterfaceList(self.Target)
        int = xenrt.random.choice(list)
        self.bindVridToVF(self.Target, num, int) #get the 10G int
        time.sleep(10)
        vmac = self.getVmacOfInt(self.Target, int)#extract VMAC
        pci_devs_assigned_to_vm = self.io.getVMInfo(self.Target.getUUID())#get index of VF
        index = pci_devs_assigned_to_vm.values()[0]['index']
        
        ret = self.addMacToVFs(self.Target,index,vmac)#assign the additional VMAC
        if ret[0] == 'OK':
            xenrt.TEC().logverbose("Additional MAC assigned successfully")
        else:
            xenrt.XRTFailure("Error message: '%s'" % ret[1])
        self.addStaticArp(self.TraffGen,targetVIP, int, vmac)#add static ARP with ip, MAC, interface
        self.command = 'ping -c 3 %s' % targetVIP #ping and verify 
        if (self.TraffGen.execguest(self.command,'nsroot')):
            xenrt.TEC().logverbose("Traffic Generator can ping the Target using the 10G Interface")
        self.Target.execguest('save ns config', username='nsroot')
        self.Target.lifecycleOperation("vm-shutdown")
        self.delMacToVFs(self.Target,index,vmac)
        pci_devs_assigned_to_vm = self.io.getVMInfo(self.Target.getUUID())
        time.sleep(10)
        if pci_devs_assigned_to_vm.values()[0].has_key('additionalmac'):
            xenrt.XRTError("Error removing additional VMAC %s") % pci_devs_assigned_to_vm.values()[0]['additionalmac']
        xenrt.TEC().logverbose("VMAC ID is removed from halted state VM")
        return 
        
class TC18823(NSSRIOV):
    """Simultaneously add the same MAC address to multiple VFs such that incoming packets to that MAC address get delivered to all VFs configured with it"""
    NUM_VPX_INSTANTS = 8
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.io = xenrt.lib.xenserver.IOvirt(self.host)
        self.io.enableIOMMU(restart_host=False)
        self.host.enableVirtualFunctions()
        self.GOLDEN_VM = self.importNsXva(self.host, "NSVPX-XEN-10.0-72.5_nc.xva")
        self.uninstallOnCleanup(self.GOLDEN_VM)
        self.TraffGen = self.GOLDEN_VM.cloneVM(name ='Traffic Generator VPX')
        self.prepVpxForFirstboot(self.host,self.TraffGen)
        vfsForTraffGen=self.assignVFsToVM(guest=self.TraffGen,n=1)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" % (self.TraffGen.getUUID(), vfsForTraffGen))
        self.TraffGen.lifecycleOperation("vm-start")
        #self.uninstallOnCleanup(self.TraffGen)
        self.TraffGen.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        time.sleep(10)
        self.installLicense(self.TraffGen)
        traffGenVIP = self.assignVipToVPX(self.host, self.TraffGen)#TfcGen VIP
        self.t_guest=[] #create 8 Targets
        self.t_VIP = [] #targetVIP of each
        i=0
        for i in range(self.NUM_VPX_INSTANTS):
            self.t_guest.append(self.GOLDEN_VM.cloneVM())
            self.prepVpxForFirstboot(self.host,self.t_guest[i])
            vfs=self.assignVFsToVM(self.t_guest[i],1)
            xenrt.TEC().logverbose("VFs assigned to VM (%s): %s" % (self.t_guest[i].getUUID(), vfs))
            xenrt.TEC().logverbose("The password was (%s)" % (self.t_guest[i].password))
            self.t_guest[i].lifecycleOperation("vm-start")
            
            #time.sleep(10)
            #self.checkPCIDevicesInVM(self.guest[i],level=xenrt.RC_OK, username='nsroot')
            #self.checkWhetherEthDevsHaveIPs(self.guest[i])
        self.t_guest[i].waitForSSH(timeout=900, cmd='sh ns ip', username='nsroot')
        
        for i in range(self.NUM_VPX_INSTANTS):
            self.installLicense(self.t_guest[i])
        
        self.t_guest[i].waitForSSH(timeout=900, cmd='sh ns ip', username='nsroot')
    
    def run(self,arglist=None):
        #Assign VIP to each VPX
        for i in range(self.NUM_VPX_INSTANTS):
            self.t_VIP.append(self.assignVipToVPX(self.host, self.t_guest[i]))
            self.t_guest[i].execguest('save ns config','nsroot')
            self.t_guest[i].execguest('shell reboot', username='nsroot', retval='code')
        
        self.t_guest[i].waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        
        self.assignSnipToVPX(self.host, self.TraffGen)#TfcGen SNIP

        num = str(xenrt.random.randint(1,255)) #VRID Number can be allowed between 1 to 255
        for i in range(self.NUM_VPX_INSTANTS):
            self.addVridToVF(self.t_guest[i], num)
            list = self.getVFInterfaceList(self.t_guest[i])
            int = xenrt.random.choice(list)
            self.bindVridToVF(self.t_guest[i], num, int)
        
        time.sleep(10)
        vmac = self.getVmacOfInt(self.t_guest[i], int)#(any int can do... Here, last assigned int) extracts VMAC
        
        for i in range(self.NUM_VPX_INSTANTS):
            pci_devs_assigned_to_vm = self.io.getVMInfo(self.t_guest[i].getUUID())#get index of VF
            index = pci_devs_assigned_to_vm.values()[i]['index']
            ret = self.addMacToVFs(self.t_guest[i],index,vmac)#assign the additional VMAC
            if ret[0] == 'OK':
                xenrt.TEC().logverbose("Additional MAC assigned successfully")
            else:
                xenrt.XRTFailure("Error message: '%s'" % ret[1])
            self.addStaticArp(self.TraffGen,self.t_VIP[i], int, vmac)
            
        xenrt.XRTError("TC not implemented Completely - Fail")    
        
class TC18824(TC18685):
    """Additional MAC address configuration shall be persistent across VPX shutdowns and re-starts and across XenServer reboots"""
    def run(self,arglist=None):
        self.TraffGen.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        traffGenVIP = self.assignVipToVPX(self.host, self.TraffGen)#TfcGen VIP
        self.Target.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        targetVIP=self.assignVipToVPX(self.host, self.Target)#Target VIP
        self.assignSnipToVPX(self.host, self.TraffGen)#TfcGen SNIP
        
        num = str(xenrt.random.randint(1,255)) #VRID Number can be allowed between 1 to 255
        self.addVridToVF(self.Target, num)#Target vrid to interface "int = 10/1"
        list = self.getVFInterfaceList(self.Target)
        int = xenrt.random.choice(list)
        self.bindVridToVF(self.Target, num, int) #get the 10G int
        time.sleep(10)
        vmac = self.getVmacOfInt(self.Target, int)#extract VMAC
        pci_devs_assigned_to_vm = self.io.getVMInfo(self.Target.getUUID())#get index of VF
        index = pci_devs_assigned_to_vm.values()[0]['index']
        
        ret = self.addMacToVFs(self.Target,index,vmac)#assign the additional VMAC
        if ret[0] == 'OK':
            xenrt.TEC().logverbose("Additional MAC assigned successfully")
        else:
            xenrt.XRTFailure("Error message: '%s'" % ret[1])

        self.addStaticArp(self.TraffGen,targetVIP, int, vmac)#add static ARP with ip, MAC, interface
        self.command = 'ping -c 3 %s' % targetVIP #ping and verify 
        if (self.TraffGen.execguest(self.command,'nsroot')):
            xenrt.TEC().logverbose("Traffic Generator can ping the Target using the 10G Interface")
        
        self.Target.lifecycleOperation("vm-shutdown")
        time.sleep(10)
        #after shutdown
        if vmac != self.getAdditionalMac(self.Target):
            xenrt.XRTFailure("Lost the added additional MAC")
        xenrt.TEC().logverbose("vmac %s verified to be persistent after VPX shutdown" % vmac)
        
        self.Target.lifecycleOperation("vm-start")
        self.Target.waitForSSH(timeout=100,cmd='save ns config',username='nsroot')
        #after start
        if vmac != self.getAdditionalMac(self.Target):
            xenrt.XRTFailure("Lost the added additional MAC")
        xenrt.TEC().logverbose("vmac %s verified to be persistent after VPX start" % vmac)
        
        self.Target.lifecycleOperation("vm-reboot")
        self.Target.waitForSSH(timeout=100,cmd='save ns config',username='nsroot')
        #After reboot
        if vmac != self.getAdditionalMac(self.Target):
            xenrt.XRTFailure("Lost the added additional MAC")
        xenrt.TEC().logverbose("vmac %s verified to be persistent after VPX reboot" % vmac)
        
        self.host.reboot()
        self.host.waitForSSH(300, desc="host reboot to check for persitence of additional mac field for the VPX")
        #After XenServer reboot
        if vmac != self.getAdditionalMac(self.Target):
            xenrt.XRTFailure("Lost the added additional MAC")
        xenrt.TEC().logverbose("vmac %s verified to be persistent after XenServer reboot" % vmac)
        return 
        
class TC19038(TC18685):
    """An attempt to add an additional MAC address where hardware resource are not available shall return a suitable error."""
    def run(self,arglist=None):
        self.Target.waitForSSH(timeout=100,cmd='sh ns ip',username='nsroot')
        targetVIP=self.assignVipToVPX(self.host, self.Target)#Target VIP
        pci_devs_assigned_to_vm = self.io.getVMInfo(self.Target.getUUID())#get index of VF
        index = pci_devs_assigned_to_vm.values()[0]['index']
        device = pci_devs_assigned_to_vm.values()[0]['device']
        #Total free macs from the device being used by Target VM
        freeMacs=self.io.getAdditionalMacsFree(device)
        for i in range(int(freeMacs)):
            mac=xenrt.randomMAC()
            ret = self.addMacToVFs(self.Target,index,mac)#assign the additional VMAC
            if ret[0] == 'OK':
                xenrt.TEC().logverbose("Additional MAC assigned successfully")
            else:
                xenrt.XRTFailure("Error message: '%s'" % ret[1])
        #Attempt to try assign extra mac
        ret = self.addMacToVFs(self.Target,index,xenrt.randomMAC())#assign the additional VMAC
        if ret[0] == 'OK':
            xenrt.TEC().XRTFailure("Additional MAC assigned successfully: UNEXPECTED")
        else:
            xenrt.TEC().logverbose("Error message: '%s' EXPECTED" % ret[1])
        return 
        
class TC18849(xenrt.TestCase):
    
    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        try:
            self.host.execdom0('ls -l /etc/xapi.d/plugins/xsnsmonitor')
        except:
            raise xenrt.XRTError("Looks like we don't have NS Supp pack installed")
        return
    
    def run(self, arglist=[]):
        cmd = 'xe host-call-plugin plugin=xsnsmonitor host-uuid=%s' % self.host.getMyHostUUID()
        
        # Get the list of CPU sensors
        cpu_sensors = map(lambda s: s.strip(), 
                          self.host.execdom0(cmd + " fn=ipmi_sensor_list | grep CPU | cut -f1 -d'|' ; exit 0").splitlines())
        if len(cpu_sensors) == 0:
            self.host.execdom0(cmd + " fn=ipmi_sensor_list; exit 0") # for logging purpose
            raise xenrt.XRTFailure("ipmitool is not displaying CPU sensor")

        def getCpuStatus(cpu):
            cpustat = cmd + " fn=ipmi_sensor_get args:sensors=\'%s\' | grep Status | cut -d: -f2 ; exit 0" % cpu
            return self.host.execdom0(cpustat).strip()

        for cpu in cpu_sensors:
            stat = getCpuStatus(cpu)
            if stat.lower() != 'ok':
                self.host.execdom0(cmd + " fn=ipmi_sensor_get args:sensors=\'%s\' ; exit 0") # for logging purpose
                raise xenrt.XRTFailure("IPMI doesn't display CPU stats")
            
        return
        
