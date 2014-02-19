#
# XenRT: Test harness for Xen and the XenServer product family
#
# Point to Point network tests
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, xenrt.lib.xenserver
import string, time, calendar, re, os, os.path
import IPy
from datetime  import datetime

class TCPoint2PointNetwork(xenrt.TestCase):
    NUM_CLIENT_VMS = 4
    TEST_DURATION = 120

    def _createP2PNetwork(self):
        nwuuid = self.host.execdom0("xe network-create name-label=\"Point To Point\"")
        return nwuuid.strip()

    def _createPrivateNetwork(self):
        nwuuid = self.host.execdom0("xe network-create name-label=\"Private Network\"")
        return nwuuid.strip()
        
    def _setupNetBack(self):
        # Import the DDK VM for the NetBack server
        ddkServer = self.host.importDDK("Netback")
        xenrt.TEC().logverbose("Netback VM: %s" % ddkServer.getUUID())
        self.host.execdom0("xe network-param-set uuid=%s other-config:backend_vm=%s" % (self.p2p_network, ddkServer.getUUID()))
        ddkServer.createVIF(bridge=self.host.getPrimaryBridge())
        ddkServer.start()
        # Get the name of the bridge
        bridge = self.host.execdom0("xe network-param-get uuid=%s param-name=bridge" % self.p2p_network)
        # Install bridge-utils
        ddkServer.execguest("yum --disablerepo=citrix --enablerepo=base,updates install bridge-utils -y")
        # Setup rc.local to add the bridge each boot
        ddkServer.execguest("echo \"brctl addbr %s\" >> /etc/rc.local" % (bridge))
        ddkServer.execguest("echo \"ifup %s\" >> /etc/rc.local" % (bridge))
        # Setup network.conf to say we are using "bridge" and not OVS
        ddkServer.execguest("echo \"bridge\" > /etc/xensource/network.conf")
        # Bridge ifcfg settings
        ddkServer.execguest("echo \"DEVICE=%s\" > /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge, bridge))
        ddkServer.execguest("echo \"BOOTPROTO=static\" >> /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge))
        ddkServer.execguest("echo \"TYPE=ethernet\" >> /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge))
        ddkServer.execguest("echo \"IPADDR=192.168.50.1\" >> /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge))
        ddkServer.execguest("echo \"NETMASK=255.255.255.0\" >> /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge))
        ddkServer.execguest("echo \"ONBOOT=yes\" >> /etc/sysconfig/network-scripts/ifcfg-%s" % (bridge))
        # Create udev rule for "vif"
        ddkServer.execguest("echo 'SUBSYSTEM==\"xen-backend\", KERNEL==\"vif*\", RUN+=\"/etc/xensource/scripts/vif $env{ACTION} vif\"' > /etc/udev/rules.d/xen-backend.rules")
        # Create /etc/xensource/scripts/vif file for handling online/remove of vifs
        ddkServer.execguest("mkdir -p /etc/xensource/scripts")
        ddkServer.execguest("echo '#!/bin/sh\' > /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'DOMID=`echo ${XENBUS_PATH} | cut -f 3 -d '/'`' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'DEVID=`echo ${XENBUS_PATH} | cut -f 4 -d '/'`\' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'case \"$1\" in' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'online)' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    bridge=$(xenstore-read \"/xapi/${DOMID}/private/vif/${DEVID}/bridge\")' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    /sbin/ip link set \"vif${DOMID}.${DEVID}\" down' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    /usr/sbin/brctl addif \"${bridge}\" \"vif${DOMID}.${DEVID}\"' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    /sbin/ip link set \"vif${DOMID}.${DEVID}\" up' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    xenstore-write \"/xapi/${DOMID}/hotplug/vif/${DEVID}/hotplug\" \"online\"'  >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    ;;' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'remove)' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    xenstore-rm \"/xapi/${DOMID}/hotplug/vif/${DEVID}/hotplug\"' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo '    ;;' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("echo 'esac' >> /etc/xensource/scripts/vif")
        ddkServer.execguest("chmod +x /etc/xensource/scripts/vif")
        # Create eth1 settings for the Private Network
        ddkServer.execguest("echo \"DEVICE=eth1\" > /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkServer.execguest("echo \"BOOTPROTO=static\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkServer.execguest("echo \"TYPE=ethernet\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkServer.execguest("echo \"IPADDR=192.168.100.1\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkServer.execguest("echo \"NETMASK=255.255.255.0\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkServer.execguest("echo \"ONBOOT=yes\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        # Add the VIF to the Point to Point network
        bridge = self.host.genParamGet("network", self.private_network, "bridge")
        ddkServer.createVIF(eth = "eth1", bridge=bridge, plug=True) # Now create the VIFs on the other networks that the host has IPs on
        # Install netperf
        ddkServer.installNetperf()
        ddkServer.execguest("echo '/usr/local/bin/netserver &' >> /etc/rc.local")
        # Reboot
        ddkServer.reboot()
        return ddkServer

    def _setupNetFront(self, ip):
        # Import the DDK VM for the NetFront client
        ddkClient = self.host.importDDK("Netfront")
        ddkClient.createVIF(bridge=self.host.getPrimaryBridge())
        ddkClient.start()
        xenrt.TEC().logverbose("Netfront VM: %s" % ddkClient.getUUID())
        # Create eth1 settings for the Point to Point Network
        ddkClient.execguest("echo \"DEVICE=eth1\" > /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkClient.execguest("echo \"BOOTPROTO=static\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkClient.execguest("echo \"TYPE=ethernet\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkClient.execguest("echo \"IPADDR=192.168.50.%d\" >> /etc/sysconfig/network-scripts/ifcfg-eth1" % ip)
        ddkClient.execguest("echo \"NETMASK=255.255.255.0\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        ddkClient.execguest("echo \"ONBOOT=yes\" >> /etc/sysconfig/network-scripts/ifcfg-eth1")
        # Add the VIF to the Point to Point network
        bridge = self.host.genParamGet("network", self.p2p_network, "bridge")
        ddkClient.createVIF(eth = "eth1", bridge=bridge, plug=True) # Now create the VIFs on the other networks that the host has IPs on
        #ddkClient.execguest("ifup eth1") # And bring the link up
        # Create eth2 settings for the Private Network
        ddkClient.execguest("echo \"DEVICE=eth2\" > /etc/sysconfig/network-scripts/ifcfg-eth2")
        ddkClient.execguest("echo \"BOOTPROTO=static\" >> /etc/sysconfig/network-scripts/ifcfg-eth2")
        ddkClient.execguest("echo \"TYPE=ethernet\" >> /etc/sysconfig/network-scripts/ifcfg-eth2")
        ddkClient.execguest("echo \"IPADDR=192.168.100.%d\" >> /etc/sysconfig/network-scripts/ifcfg-eth2" % ip)
        ddkClient.execguest("echo \"NETMASK=255.255.255.0\" >> /etc/sysconfig/network-scripts/ifcfg-eth2")
        ddkClient.execguest("echo \"ONBOOT=yes\" >> /etc/sysconfig/network-scripts/ifcfg-eth2")
        # Add the VIF to the Point to Point network
        bridge = self.host.genParamGet("network", self.private_network, "bridge")
        ddkClient.createVIF(eth = "eth2", bridge=bridge, plug=True) # Now create the VIFs on the other networks that the host has IPs on
        #ddkClient.execguest("ifup eth2") # And bring the link up
        # Install netperf
        ddkClient.installNetperf()
        ddkClient.reboot()
        return ddkClient

    def prepare(self, arglist):
        self.ddkNetfront = []
        self.host = self.getDefaultHost()
        # Create the Point to Point network
        self.p2p_network = self._createP2PNetwork()
        xenrt.TEC().logverbose("Point to Point Network: %s" % self.p2p_network)
        # Create a Private Network
        self.private_network = self._createPrivateNetwork()
        xenrt.TEC().logverbose("Private Network: %s" % self.private_network)
        # Create and Setup the NetBack server VM
        self.ddkNetback = self._setupNetBack()
        # Create and Setup the NetFront client VMs
        pTasks = map(lambda x: xenrt.PTask(self._setupNetFront, x+2), range(self.NUM_CLIENT_VMS))
        self.ddkNetfront = xenrt.pfarm(pTasks)
        # Get the management PIF for collecting logs
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host.getMyHostUUID()).strip()

    def _dom0PerfTest(self, threshold):
        count = 0
        cpuUsageTotal = 0
        deadline = xenrt.util.timenow() + self.TEST_DURATION
        # Check the dom0 cpu usage
        while xenrt.util.timenow() < deadline:
            usage = self.host.getXentopData()
            cpuUsage = usage["0"]["CPU(%)"]
            count += 1
            cpuUsageTotal += float(cpuUsage)
        cpuUsageAvg = float(cpuUsageTotal) / float(count)
        xenrt.TEC().logverbose("CPU Usage of dom0 average is %f" % float(cpuUsageAvg))
        if float(cpuUsageAvg) > float(threshold):
            raise xenrt.XRTFailure("CPU Usage of dom0 is high, Expected was less than %s and obtained is %s" % (threshold, cpuUsageAvg))

    def _runNetperf(self, client, server_ip):
        data = client.execguest("netperf -H %s -t TCP_STREAM -l 120 -v 0 -P 0" % (server_ip))
        return float(data.strip())

    def _runNetperfThread(self, client, server_ip):
        throughput = self._runNetperf(client, server_ip)
        self.netperfRates.append(throughput)

    def run(self, arglist):
        # Run a single guest Point to Point Network test vs. a single guest Private Network test
        # The Point to Point should be at least 30% faster than the Privaet Network
        p2p_rate = self._runNetperf(self.ddkNetfront[0], "192.168.50.1")
        xenrt.TEC().logverbose("Point To Point Network throughput is %0.2f" % p2p_rate)
        private_rate = self._runNetperf(self.ddkNetfront[0], "192.168.100.1")
        xenrt.TEC().logverbose("Private Network throughput is %0.2f" % private_rate)
        if(p2p_rate < private_rate):
            raise xenrt.XRTFailure("Point to Point Network throughput was less than Private Network throughput")    
        diff_percent = (((p2p_rate - private_rate)/private_rate)*100)
        xenrt.TEC().logverbose("P2P Network is %0.2f %% faster" % diff_percent)
        if (diff_percent < 30):
            raise xenrt.XRTFailure("Point to Point Network wasn't 30% faster than Private Network")    

        # Run multiple netperf clients against the Point to Point Network
        # Make sure that the dom0 CPU usage isn't over 20% during these tests
        self.netperfRates = []
        pTasks = map(lambda x:xenrt.PTask(self._runNetperfThread, x, "192.168.50.1"), self.ddkNetfront)
        pTasks.append(xenrt.PTask(self._dom0PerfTest, 20))
        xenrt.pfarm(pTasks)
        p2p_avg_rate = 0
        for p2p_rate in self.netperfRates:
            p2p_avg_rate += p2p_rate
            xenrt.TEC().logverbose("Point to Point Network throughput is %0.2f" % p2p_rate)
        p2p_avg_rate = p2p_avg_rate / len(self.netperfRates)
        xenrt.TEC().logverbose("Average Point to Point Network throughput is %0.2f" % p2p_avg_rate)
        
        # Run multiple netperf clients against the Private Network
        self.netperfRates = []
        pTasks = map(lambda x:xenrt.PTask(self._runNetperfThread, x, "192.168.100.1"), self.ddkNetfront)
        pTasks.append(xenrt.PTask(self._dom0PerfTest, 200))
        xenrt.pfarm(pTasks)
        priv_avg_rate = 0
        for priv_rate in self.netperfRates:
            priv_avg_rate += priv_rate
            xenrt.TEC().logverbose("Private Network throughput is %0.2f" % priv_rate)
        priv_avg_rate = priv_avg_rate / len(self.netperfRates)
        xenrt.TEC().logverbose("Average Private throughput is %0.2f" % priv_avg_rate)

        if(p2p_avg_rate < priv_avg_rate):
            raise xenrt.XRTFailure("Point to Point Network average throughput was less than Private Network average throughput")    
        diff_percent = (((p2p_avg_rate - priv_avg_rate)/priv_avg_rate)*100)
        xenrt.TEC().logverbose("P2P Network average is %0.2f %% faster" % diff_percent)
        if (diff_percent < 30):
            raise xenrt.XRTFailure("Point to Point Network average wasn't 30% faster than Private Network average")    

    def postRun(self):
        self.host.execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)
