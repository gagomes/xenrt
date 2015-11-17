#
# XenRT: Test harness for Xen and the XenServer product family
#
# Native OS machine installation
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, os, time, crypt 
import urllib, re, glob, zipfile, xmlrpclib, stat
import xenrt

# Symbols we want to export from the package.
__all__ = ["NativeHost",
           "createHost",
           "hostFactory"]

def hostFactory(hosttype):
    if hosttype == "Linux":
        return xenrt.lib.native.NativeLinuxHost
    elif hosttype == "Windows":
        return xenrt.lib.native.NativeHost

def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskid=0,
               diskCount=1,
               productVersion=None,
               productType=None,
               withisos=False,
               noisos=None,
               overlay=None,
               installSRType=None,
               suppackcds=None,
               addToLogCollectionList=False,
               disablefw=False,
               cpufreqgovernor=None,
               defaultlicense=True,
               ipv6=None,
               enableAllPorts=True,
               noipv4=False,
               basicNetwork=True,
               extraConfig=None,
               containerHost=None,
               vHostName=None,
               vHostCpus=2,
               vHostMemory=4096,
               vHostDiskSize=50,
               vHostSR=None,
               vNetworks=None,
               **kwargs):

    if containerHost != None:
        raise xenrt.XRTError("Nested hosts not supported for this host type")

    # noisos isn't used here, it is present in the arg list to
    # allow its use as a flag in PrepareNode in sequence.py

    machine = str("RESOURCE_HOST_%s" % (id))
    mname = xenrt.TEC().lookup(machine)
    m = xenrt.PhysicalHost(mname)

    xenrt.GEC().startLogger(m)

    (distro, arch) = xenrt.getDistroAndArch(productVersion)

    host = xenrt.lib.native.NativeLinuxHost(m, version)
    host.installLinuxVendor(distro, arch=arch)

    if cpufreqgovernor:
        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("Before changing cpufreq governor: %s" % (output,))

        # For each CPU, set the scaling_governor. This command will fail if the host does not support cpufreq scaling (e.g. BIOS power regulator is not in OS control mode)
        # TODO also make this persist across reboots
        host.execcmd("for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo %s > $cpu; done" % (cpufreqgovernor,))

        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("After changing cpufreq governor: %s" % (output,))

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class NativeHost(xenrt.GenericPlace):

    def __init__(self, machine,productVersion=None):
        xenrt.GenericPlace.__init__(self)
        self.machine = machine
        self.memory = None
        self.vcpus = None
        
        self.pddomaintype = "Native"
        self.password = xenrt.TEC().lookup("NATIVE_WINPE_PASSWORD")
        self.productVersion=productVersion

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        """Check the location is healthy."""
        # TODO
        pass

    def getIP(self):
        if self.machine:
            return self.machine.ipaddr
        return None
   
    def getName(self):
        if self.machine:
            return self.machine.name
        return None

    def checkVersion(self):
        try:
            if self.windows:
                self.productVersion = "Windows"
                self.productRevision = self.xmlrpcWindowsVersion()
        except:
            pass

    def setVCPUs(self, vcpus):
        self.vcpus = vcpus

    def setMemory(self, memory):
        self.memory = memory

    def installWindows(self, version, build, arch):
        self.windows = True

        if not os.path.exists("%s/%s/%s/autoinstall-%s.zip" % 
            (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch)):
            if not os.path.exists("%s/%s/%s/autoinstall-%s.tar" %
                (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch)):
                raise xenrt.XRTError("No install files found for %s build %s" % (version, build)) 
 
        if version == "longhorn" or version[0:7] == "vistaee":
            method = "longhorn"
        else:
            method = "normal"
        self.distro = version
        
        xenrt.TEC().progress("Preparing TFTP...")
        tftp = "%s/xenrt/native" % (xenrt.TEC().lookup("TFTP_BASE"))
        if not os.path.exists(tftp):
            xenrt.sudo("mkdir -p %s" % (tftp))
        xenrt.getTestTarball("native", extract=True)
        xenrt.sudo("rsync -avxl %s/winpe32.wim %s/winpe.wim" %
                   (xenrt.TEC().lookup("IMAGES_ROOT"), tftp))

        # Get a PXE directory to put boot files in.
        xenrt.TEC().progress("Preparing PXE...")
        serport = xenrt.TEC().lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = xenrt.TEC().lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe = xenrt.PXEBoot()
        pxe.copyIn("%s/native/pxe/pxeboot.0" % (xenrt.TEC().getWorkdir()))
        xenrt.sudo("rsync -avxl %s/native/pxe/32/BCD %s/BCD" % 
                      (xenrt.TEC().getWorkdir(), tftp))
        xenrt.sudo("rsync -avxl %s/native/pxe/boot.sdi %s/boot.sdi" %
                      (xenrt.TEC().getWorkdir(), tftp))
        xenrt.sudo("rsync -avxl %s/native/pxe/bootmgr.exe %s/bootmgr.exe" %
                      (xenrt.TEC().getWorkdir(), tftp))
        
        # Set the boot files and options for PXE
        pxe.setSerial(serport, serbaud)
        pxe.addEntry("local", boot="local")
        pxecfg = pxe.addEntry("winpe", default=1, boot="linux")
        pxecfg.linuxSetKernel("pxeboot.0")

        xenrt.TEC().progress("Preparing web directory")
        w = xenrt.WebDirectory()

        f = file("%s/native/pe/perun.cmd" % (xenrt.TEC().getWorkdir()), "r")
        perun = f.read()
        f.close()    

        if method == "longhorn":
            t = xenrt.TempDirectory()
            
            xenrt.command("tar xf %s/%s/%s/autoinstall-%s.tar -C %s" %
                         (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch, t.path()))    
            
            w.copyIn("%s/install/unattend.xml" %
                    (t.path()))
            perun += "wget %FILES%/unattend.xml\n"

            # Count the number of install.wim fragments.
            catcmd = "cat "
            partpath = "%s/install/install.part" % (t.path())
            numparts = len(glob.glob("%s*" % (partpath)))  
            for i in range(1, numparts + 1):
                # Download install.wim fragment.
                perun += "wget %%FILES%%/%s%d\n" % (os.path.basename(partpath), i) 
                # Make sure fragments get recombined.
                catcmd += "%s%d " % (os.path.basename(partpath), i)
                # Make fragment available over the network.
                w.copyIn("%s%d" % (partpath, i))
            catcmd += "> c:\\win\\sources\\install.wim\n"
            perun += catcmd
            w.copyIn("%s/install/install.zip" % (t.path()), target="win.zip")

            t.remove()

            # 32-bit installs just require the one stage.
            if arch == "x86-32":
                perun += "c:\\win\\sources\\setup.exe /unattend:c:\\unattend.xml"
        else:
            t = xenrt.TempDirectory()
            
            xenrt.command("unzip %s/%s/%s/autoinstall-%s.zip unattend.txt -d %s" %
                         (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch, t.path()))
            try:
                xenrt.command("unzip %s/%s/%s/autoinstall-%s.zip runonce.cmd -d %s" %
                             (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch, t.path()))
            except:
                try:
                    xenrt.command("unzip %s/%s/%s/autoinstall-%s.zip win/i386/runonce.cmd -d %s" %
                                 (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch, t.path()))
                except:
                    xenrt.command("unzip %s/%s/%s/autoinstall-%s.zip win/I386/runonce.cmd -d %s" %
                                 (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch, t.path()))
                xenrt.command("mv %s/win/?386/runonce.cmd %s/runonce.cmd" %
                              (t.path(), t.path()))
            xenrt.command("chmod a+rwx %s/runonce.cmd" % (t.path())) 

            perun += """
wget %FILES%/runonce.cmd
wget %FILES%/unattend.txt
bootsect /nt52 c: /force
c:\win\i386\winnt32.exe /makelocalsource /syspart:c: /s:c:\win\i386 /unattend:c:\unattend.txt /cmd:c:\runonce.cmd
wpeutil reboot
"""
            f = file("%s/runonce.cmd" % (t.path()), "r")
            data = f.read()
            f.close()
            # HACK to support Broadcom NICs on those machines that have them. 
            if xenrt.TEC().lookup("BROADCOM_POSTINSTALL", False, boolean=True):
                data = string.replace(data, "EXIT", "")
                data = data + 'REG ADD %KEY%\\050 /VE /D "Broadcom Driver" /f\n'
                data = data + 'REG ADD %KEY%\\050 /V 1 /D ' \
                       '"%systemdrive%\\win\\post\\Broadcom\\setup.exe ' \
                       '/s /v/qn" /f\n'
                data = data + "EXIT\n"
 
            xenrt.TEC().copyToLogDir("%s/runonce.cmd" % (t.path()))
            f = file("%s/runonce.cmd" % (t.path()), "w")
            f.write(data)
            f.close()
            w.copyIn("%s/unattend.txt" % (t.path()))
            w.copyIn("%s/runonce.cmd" % (t.path()))
            w.copyIn("%s/%s/%s/autoinstall-%s.zip" % 
                    (xenrt.TEC().lookup("IMAGES_ROOT"), version, build, arch), target="win.zip")
            t.remove()
    
        # Copy common files.
        w.copyIn("%s/native/pe/makepart.txt" % (xenrt.TEC().getWorkdir()))
 
        perun_dir = os.path.dirname(xenrt.TEC().lookup("WINPE_START_FILE"))
        if not os.path.exists(perun_dir):
            xenrt.sudo("mkdir -p %s" % (perun_dir))
        # Replace variables in perun.cmd.
        perun = string.replace(perun, "%FILES%", "%s" % (w.getURL("/")))        
        f = file("%s/perun.cmd" % (xenrt.TEC().getWorkdir()), "w")
        f.write(perun)
        f.close()
        xenrt.TEC().copyToLogDir("%s/perun.cmd" %
                                (xenrt.TEC().getWorkdir()))
        # Put perun.cmd where WinPE expects it.
        lock = xenrt.resources.CentralResource()
        for i in range(10):
            try:
                lock.acquire("WINPE_START_FILE")
                break
            except:
                if i == 9:
                    raise xenrt.XRTError("Couldn't get lock on WINPE "
                                         "bootstrap file.")
                xenrt.sleep(60)
        xenrt.sudo("cp %s/perun.cmd %s" %
                   (xenrt.TEC().getWorkdir(),
                    xenrt.TEC().lookup("WINPE_START_FILE")))

        # Start install.
        xenrt.TEC().progress("Starting installation")
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        self.machine.powerctl.cycle()
        xenrt.TEC().progress("Rebooted host to start installation.")

        xenrt.sleep(120)

        lock.release()

        # 64-bit requires a two-stage installation. 
        if arch == "x86-64":
            # Wait for first stage to complete.
            xenrt.sleep(360)
            xenrt.TEC().progress("Preparing TFTP for second stage.")
            xenrt.sudo("rsync -avxl %s/native/pxe/64/ %s/" %
                    (xenrt.TEC().getWorkdir(), tftp))
            xenrt.sudo("rsync -avxl %s/winpe64.wim %s/winpe.wim" %
                    (xenrt.TEC().lookup("IMAGES_ROOT"), tftp))
            self.machine.powerctl.cycle()
            xenrt.TEC().progress("Rebooted host into second installation stage.") 

        # Wait for PXE boot.
        xenrt.sleep(120)
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        # Wait for Windows to boot.
        xenrt.TEC().progress("Waiting for host to boot")
        self.waitforxmlrpc(7200)

        w.remove()

        if method == "longhorn":
            self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\Terminal Server", "fDenyTSConnections", "DWORD", 0)
            self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\Lsa", "LMCompatibilityLevel", "DWORD", 1)

        if not method == "longhorn":
            bootini = self.xmlrpcReadFile("c:\\boot.ini").strip() 
            if self.memory:
                bootini += " /MAXMEM=%d" % (self.memory)
            if self.vcpus:
                bootini += " /NUMPROC=%d" % (self.vcpus)
            self.xmlrpcRemoveFile("c:\\boot.ini") 
            self.xmlrpcCreateFile("c:\\boot.ini", xmlrpclib.Binary(bootini))
            self.xmlrpcReboot()
            xenrt.sleep(180)
            self.waitforxmlrpc(300)

            self.tailor()

class NativeLinuxHost(xenrt.GenericHost):

    def __init__(self, machine, productVersion=None):
        xenrt.GenericHost.__init__(self, machine)
        self.arch = None
        self.serial = 0
        self.memory = None
        self.vcpus = None
        self.pddomaintype = "Native"
        self.productVersion = productVersion

    def existing(self):
        pass

    def setVCPUs(self, vcpus):
        self.vcpus = vcpus

    def setMemory(self, memory):
        self.memory = memory

    def getIP(self):
        if self.machine:
            return self.machine.ipaddr
        return None

    def getName(self):
        if self.machine:
            return self.machine.name
        return None

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        """Check the location is healthy."""
        pass

    def isEnabled(self):
        return self.execdom0("true", retval="code") == 0

    def checkVersion(self):
        # Figure out the product version and revision of the host if we can
        try:
            if self.windows:
                self.productVersion = "Windows"
                self.productRevision = self.xmlrpcWindowsVersion()
        except:
            pass

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        # configure single nic non vlan jumbo networks
        requiresReboot = False
        has_mgmt_ip = False
        usedEths = []
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            # create only on single nic non valn nets
            if len(nicList) == 1  and len(vlanList) == 0:
                eth = self.getNIC(nicList[0])[3:]
                usedEths.append(nicList[0])
                xenrt.TEC().logverbose("Processing eth%s: %s" % (eth, p))
                #make sure it is up

                # Record the friendlynetname for this NIC
                self.execcmd("echo '%s	eth%s' >> /var/xenrtnetname" % (friendlynetname, eth))

                if mgmt or storage:
                    #use the ip of the mgtm nic on the list as the default ip of the host
                    if mgmt:
                        mode = mgmt
                        self.execcmd("sed -i /GATEWAYDEV/d /etc/sysconfig/network")
                        self.execcmd("echo 'GATEWAYDEV=eth%s' >> /etc/sysconfig/network" % eth)
                    else:
                        mode = storage
                    self.execcmd("sed -i /ONBOOT/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                    self.execcmd("echo 'ONBOOT=yes' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)

                    if mode == "static":
                        newip, netmask, gateway = self.getNICAllocatedIPAddress(nicList[0])
                        xenrt.TEC().logverbose("XenRT static configuration for host %s: ip=%s, netmask=%s, gateway=%s" % (self, newip, netmask, gateway))
                        self.execcmd("sed -i /BOOTPROTO/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /IPADDR/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /NETMASK/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /GATEWAY/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("echo 'BOOTPROTO=none' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("echo 'IPADDR=%s' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % (newip, eth))
                        self.execcmd("echo 'NETMASK=%s' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % (netmask, eth))
                        if mgmt:
                            self.execcmd("echo 'GATEWAY=%s' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % (gateway, eth))
                        self.execcmd("ifdown eth%s; ifup eth%s || true" % (eth, eth))

                    elif mode == "dhcp":
                        self.execcmd("sed -i /BOOTPROTO/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /IPADDR/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /NETMASK/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("sed -i /GATEWAY/d /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("echo 'BOOTPROTO=dhcp' >> /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                        self.execcmd("ifdown eth%s; ifup eth%s || true" % (eth, eth))
                    
                    #read final ip in eth
                    newip = self.execcmd("ip addr show eth%s|grep \"inet \"|gawk '{print $2}'| gawk -F/ '{print $1}'" % eth).strip()
                    if newip and len(newip)>0:
                        xenrt.TEC().logverbose("New IP %s for host %s on eth%s" % (newip, self, eth))
                        if mgmt:
                            self.machine.ipaddr = newip
                            has_mgmt_ip = True
                    else:
                        raise xenrt.XRTError("Wrong new IP %s for host %s on eth%s" % (newip, self, eth))

                else: 
                    self.execcmd("ifup eth%s || true" % eth)

                if jumbo == True:
                    #enable jumbo frames immediately
                    self.execcmd("ifconfig eth%s mtu 9000" % eth)
                    #make it permanent
                    self.execcmd("sed -i 's/MTU=.*$/MTU=\"9000\"/; t; s/^/MTU=\"9000\"/' /etc/sysconfig/network-scripts/ifcfg-eth%s" % eth)
                    requiresReboot = False
                elif jumbo != False: #ie jumbo is a string
                    self.execcmd("ifconfig eth%s mtu %s" % (eth, jumbo))
                    self.execcmd("sed -i 's/MTU=.*$/MTU=\"%s\"/; t; s/^/MTU=\"%s\"/' /etc/sysconfig/network-scripts/ifcfg-eth%s" % (jumbo,jumbo,eth))
                    requiresReboot = False

            if len(nicList) > 1:
                raise xenrt.XRTError("Can't create bond on %s using %s" %
                                       (network, str(nicList)))
            if len(vlanList) > 0:
                raise xenrt.XRTError("Can't create vlan on %s using %s" %
                                       (network, str(vlanList)))

        if len(physList)>0:
            if not has_mgmt_ip:
                raise xenrt.XRTError("The network topology did not define a management IP for the host")

        allEths = [0]
        allEths.extend(self.listSecondaryNICs())

        for e in allEths:
            if e not in usedEths:
                eth = self.getNIC(e)[3:]
                self.execcmd("ifdown eth%s || true" % eth)
                self.execcmd("sed -i /ONBOOT/d /etc/sysconfig/network-scripts/ifcfg-eth%s || true" % eth)
                self.execcmd("echo 'ONBOOT=no' >> /etc/sysconfig/network-scripts/ifcfg-eth%s || true" % eth)
                

        # Only reboot if required and once while physlist is processed
        if requiresReboot == True:
            self.reboot()

        # Make sure no firewall will interfere with tests
        self.execcmd("iptables -F")

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

    def getAssumedId(self, friendlyname):
        # NET_A -> eth0         recorded in /var/xenrtnetname
        #       -> MAC          ip addr
        #       -> assumedid    h.listSecondaryNICs()
        eth = self.execcmd("grep '^%s	' /var/xenrtnetname" % (friendlyname)).strip().split("	")[1]
        mac = self.execcmd("ip addr show dev %s | fgrep link/ether | awk '{print $2}'" % (eth)).strip()

        nics = self.listSecondaryNICs(macaddr=mac)
        xenrt.TEC().logverbose("getAssumedId (native linux host): network '%s' corresponds to NICs with assumedids %s" % (friendlyname, nics))
        return nics[0]

    def installIperf(self, version=""):
        """Install iperf into the host"""

        if version=="":
            sfx = "2.0.4"
        else:
            sfx = version

        if self.execcmd("test -e /usr/local/bin/iperf -o "
                        "     -e /usr/bin/iperf",
                        retval="code") != 0:
            workdir = string.strip(self.execcmd("mktemp -d /tmp/XXXXXX"))
            self.execcmd("wget '%s/iperf%s.tgz' -O %s/iperf%s.tgz" %
                         (xenrt.TEC().lookup("TEST_TARBALL_BASE"), version,
                          workdir, version))
            self.execcmd("tar -zxf %s/iperf%s.tgz -C %s" % (workdir, version, workdir))
            self.execcmd("tar -zxf %s/iperf%s/iperf-%s.tar.gz -C %s" %
                         (workdir, version, sfx, workdir))
            self.execcmd("cd %s/iperf-%s && ./configure" %
                           (workdir, sfx))
            self.execcmd("cd %s/iperf-%s && make" % (workdir, sfx))
            self.execcmd("cd %s/iperf-%s && make install" %
                         (workdir, sfx))
            self.execcmd("rm -rf %s" % (workdir))

    def setupDataDisk(self):
        try:
            self.execcmd("test -e /data")
            return
        except:
            pass
        if self.getGuestDisks()[0] == self.getInstallDisk():
            # Add a partition
            disk = self.getGuestDisks()[0]
            partitions = self.execcmd("fdisk -l /dev/%s | awk '{print $1}' | grep '/dev'" % disk)
            lastpart = int(partitions.splitlines()[-1].strip()[-1])
            script = "n\\np\\n%d\\n\\n\\nw\\n" % (lastpart + 1)

            ret = self.execcmd("echo -e '%s' | fdisk /dev/%s" % (script, disk), retval="code")
            if ret != 0 and ret != 1:
                raise xenrt.XRTError("fdisk exited with %d" % ret)

            partitions = self.execcmd("fdisk -l /dev/%s | awk '{print $1}' | grep '/dev'" % disk)
            if int(partitions.splitlines()[-1].strip()[-1]) == lastpart:
                raise xenrt.XRTError("New partition was not created")
            datadisk = partitions.splitlines()[-1].strip()
            self.reboot()

        else:
            datadisk = "/dev/%s" % self.getGuestDisks()[0]

        self.execcmd("mkfs.ext4 %s" % datadisk)
        self.execcmd("echo %s /data ext4 defaults 0 0 >> /etc/fstab" % datadisk)
        self.execcmd("mkdir /data")
        self.execcmd("mount /data")


class TCNativeHostTest(xenrt.TestCase):

    def run(self, arglist):
        host = NativeHost("w2k3eesp2-x64")
        host.installWindows("Tampa", "w2k3eesp2-x64", "x86-64")
