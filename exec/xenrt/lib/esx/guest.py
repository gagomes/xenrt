#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on ESX guests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, xml.dom.minidom, xmltodict
import xenrt
import libvirt

__all__ = ["createVMFromFile",
           "createVM",
           "Guest"]

createVM = xenrt.lib.libvirt.createVM
createVMFromFile = xenrt.lib.libvirt.createVMFromFile

class Guest(xenrt.lib.libvirt.Guest):
    DEFAULT = -10
    DEFAULT_DISK_FORMAT = "vmdk"

    def __init__(self, *args, **kwargs):
        xenrt.lib.libvirt.Guest.__init__(self, *args, **kwargs)
        self.esxPaused = False

    def _getDiskDevicePrefix(self):
        return "sd"
    def _getDiskDeviceBus(self):
        return "scsi"
    def _getNetworkDeviceModel(self):
        return "e1000"

    def _createVBD(self, sruuid, vdiname, format, userdevice=None, controllerType='scsi', controllerModel='lsilogic'):
        srobj = self.host.srs[self.host.getSRName(sruuid)]

        if not controllerType:
            controllerType = self._getDiskDeviceBus()

        xmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(xmlstr)

        # Find an existing controller with this type and model
        controllerIndex = None
        highestIndex = 0
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("controller"):
            if node.getAttribute("type") == controllerType:
                index = int(node.getAttribute("index"))
                if controllerModel is None or node.getAttribute("model") == controllerModel:
                    # It matches what we want; use this one
                    controllerIndex = index
                    break
                else:
                    # Keep track of the highest index for a bus of this type we've seen so far
                    if index > highestIndex:
                        highestIndex = index

        # Create a new controller if necessary
        if controllerIndex is None:
            xenrt.TEC().logverbose("The new disk requires a new %s controller %s (model=%s)" % (controllerType, controllerIndex, controllerModel))
            # (Note this needs to be done at the same time as adding the disk,
            # since controllers without any disks silently disappear.)
            controllerIndex = highestIndex + 1
            contxmlstr = "<controller type='%s' index='%s' model='%s'/>" % (controllerType, controllerIndex, controllerModel)
        else:
            xenrt.TEC().logverbose("The new disk can use %s controller %s" % (controllerType, controllerIndex))
            contxmlstr = ""

        if userdevice is None:
            userdevicename = self._getNextBlockDevice(controllerType=controllerType, controllerIndex=controllerIndex)
        else:
            userdevicename = self._getDiskDevicePrefix() +chr(int(userdevice)+self._baseDeviceForBus(busid=controllerIndex))

        # Now create the disk (and possibly a controller)
        vbdxmlstr = """
        <disk type='file' device='disk'>
            <source file='%s'/>
            <target dev='%s' bus='%s'/>
        </disk>
        %s""" % (srobj.getVDIPath(vdiname), userdevicename, controllerType, contxmlstr)
        self._attachDevice(vbdxmlstr, hotplug=True)

        return userdevicename

    def _detectDistro(self):
        # we put the "distro" in the "template" field
        try:
            self.template = self.host.execdom0("grep 'guestOS = .*' /vmfs/volumes/%s/%s/%s.vmx" % (self.host.getDefaultDatastore(), self.name, self.name)).strip().replace("guestOS = ", "").strip("\"")
            self.distro = self.template
            if "win" in self.distro:
                self.windows = True
                self.hasSSH = False
        except:
            xenrt.TEC().warning("Could not get distro information for %s from config file" % self.name)
        # TODO: detect this
        self.enlightenedDrivers = False

    def _attachDevice(self, devicexmlstr, hotplug=False):
        oldxmlstr = self._getXML()
        newxmlstr = oldxmlstr.replace("</devices>", devicexmlstr + "\n  </devices>")
        self._redefineXML(newxmlstr)

    def _updateDevice(self, devicexmlstr, hotplug=False, removeOnly=False):
        oldxmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(oldxmlstr)
        devicexmldom = xml.dom.minidom.parseString(devicexmlstr)
        deviceToRemove=devicexmldom.childNodes[0]
        devicesMatched = [target for target in xmldom.getElementsByTagName(deviceToRemove.localName) if xenrt.util.checkXMLDomSubset(target ,deviceToRemove)]
        if len(devicesMatched) == 0:
            raise xenrt.XRTFailure("Can't update/remove device %s -- device not found" % deviceToRemove.localName)
        for device in devicesMatched:
            device.parentNode.removeChild(device)
            device.unlink()
        if not removeOnly:
            xmldom.getElementsByTagName("devices")[0].appendChild(devicexmldom.documentElement)
        newxmlstr = xmldom.toxml()
        self._redefineXML(newxmlstr)

    def _removeDevice(self, devicexmlstr, hotplug=False):
        self._updateDevice(devicexmlstr, hotplug=hotplug, removeOnly=True)

    def _getXML(self):
        return xenrt.lib.libvirt.tryupto(self.virDomain.XMLDesc)(libvirt.VIR_DOMAIN_XML_INACTIVE)

    def _defineXML(self, newxmlstr):
        xenrt.TEC().logverbose(newxmlstr)
        self.virDomain = xenrt.lib.libvirt.tryupto(self.virConn.defineXML)(newxmlstr)
        self.uuid = self.virDomain.UUIDString()
        # do some manual tweaking
        self.host.execdom0("sed -i -e 's/guestOS = \".*\"/guestOS = \"%s\"/' /vmfs/volumes/%s/%s/%s.vmx" %
                           (self.template.replace("Guest", ""), self.host.getDefaultDatastore(), self.name, self.name))
        # Specifying a pciBridge is required in order to use vmxnet3, otherwise you'll get a cryptic "Vmxnet3 PCI: failed to register vmxnet3 PCIe device" error
        extralines = [
            "pciBridge0.present = \"TRUE\"",
            "pciBridge0.virtualDev = \"pcieRootPort\"",
            "pciBridge0.functions = \"8\"",
        ]
        for line in extralines:
            self.host.execdom0("echo '%s' >> /vmfs/volumes/%s/%s/%s.vmx" % (line, self.host.getDefaultDatastore(), self.name, self.name))

    def _esxGetVMID(self):
        return self.host.execdom0("vim-cmd vmsvc/getallvms | grep '%s/%s.vmx'" % (self.name, self.name)).split(' ')[0]

    def _redefineXML(self, newxmlstr):
        oldxmlstr = self._getXML()
        self.virDomain.undefine()
        try:
            self._defineXML(newxmlstr)
        except:
            # try to restore the old XML
            try:
                self._defineXML(oldxmlstr)
            except:
                pass
            raise

    def _getMainIP(self):
        return self.host.execdom0("vim-cmd vmsvc/get.guest %s | grep -m 1 'ipAddress = \\\"' | awk -F\\\" '{print $2}'" % (self._esxGetVMID())).strip()

    def _ipAddrOfMacAddr(self, mac):
        mac = xenrt.normaliseMAC(mac)

        # Return the first IPv4 address after the MAC address is mentioned (and before another MAC address is mentioned)
        return self.host.execdom0("vim-cmd vmsvc/get.guest %s | grep -e 'ipAddress = \"' -e 'macAddress = \"' | sed 's/^\s*//' | awk 'BEGIN{state=0} {if ($1 == \"macAddress\" && tolower($3) ~ /%s/) { state=1 } else if ($1 == \"macAddress\") {state=2} else if (state==1 && $1 == \"ipAddress\" && $3 ~ /[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*/) { print $3; exit};}' | awk -F\\\" '{print $2}'" % (self._esxGetVMID(), mac)).strip()

    def getVIFs(self):
        xmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(xmlstr)
        reply = {}
        dev = 0
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("interface"):
            if node.getAttribute("type") == "bridge":
                bridge = node.getElementsByTagName("source")[0].getAttribute("bridge")
                nic = "eth%d" % (dev)
                mac = node.getElementsByTagName("mac")[0].getAttribute("address")
                ip = self._ipAddrOfMacAddr(mac)
                reply[nic] = (mac, ip, bridge)
                dev = dev+1
        xmldom.unlink()
        return reply


    # _isSuspended, getState and lifecycleOperation are overridden below to workaround
    # a bug in the ESX driver, which gets the meaning of saves and suspends mixed up
    # see the wiki for clarification:
    # http://confluence.uk.xensource.com/display/QA/XenRT+libvirt+integration+%28adding+support+for+other+hypervisors%29#XenRTlibvirtintegration%28addingsupportforotherhypervisors%29-MappinglibvirtterminologytoXenRT

    def getState(self):
        state = xenrt.lib.libvirt.Guest.getState(self).replace("PAUSED", "SUSPENDED")
        # But actually return 'PAUSED' if we're in the hacked-up paused state
        if self.esxPaused:
            state = state.replace("UP", "PAUSED")
        return state

    def _isSuspended(self):
        return self.virDomain.info()[0] == libvirt.VIR_DOMAIN_PAUSED

    def _vmxProcessOps(self, signal):
        # From http://www.virtuallyghetto.com/2013/03/how-to-pause-not-suspend-virtual.html
        vmxPid = self.host.execdom0("esxcli vm process list | grep -A 5 '^%s$' | fgrep 'VMX Cartel ID:' | awk '{print $4}'" % (self.name)).strip()
        self.host.execdom0("kill -%s %s" % (signal, vmxPid))

    def lifecycleOperation(self, command, *args, **kwargs):
        # pause/unpause not officially supported by ESXi, but we can pause the vmx process
        if command == "vm-pause":
            self._vmxProcessOps("STOP")
            self.esxPaused = True
            return
        elif command == "vm-unpause":
            self._vmxProcessOps("CONT")
            self.esxPaused = False
            return

        if command == "vm-suspend":
            command = "vm-pause"
        elif command == "vm-resume":
            command = "vm-unpause"
        xenrt.lib.libvirt.Guest.lifecycleOperation(self, command, *args, **kwargs)

    def createGuestFromTemplate(self, 
                                template, 
                                sruuid, 
                                ni=False, 
                                db=True, 
                                guestparams=[],
                                rootdisk=None):
        if self.memory is None:
            self.memory = 512
        if self.memory % 4 != 0:
            self.memory -= (self.memory % 4)
            xenrt.warning("ESX: Memory must be a multiple of 4MB. Rounding to %dMB" % self.memory)
        if self.vcpus is None:
            self.vcpus = 1
        if self.vcpus != 1 and self.vcpus % 2 == 1:
            self.vcpus -= (self.vcpus % 2)
            xenrt.warning("ESX: VCPUs must be a multiple of 2 (or 1). Rounding to %d VCPUs" % self.memory)
        if rootdisk == self.DEFAULT or rootdisk is None:
            rootdisk = 16*xenrt.GIGA

        # create disks
        # FIXME: hard-coded
        vdiname = "%s/%s.%s" % (self.name, self.name, self.DEFAULT_DISK_FORMAT)
        self.host.createVDI(rootdisk, sruuid, name=vdiname, format=self.DEFAULT_DISK_FORMAT)

        srobj = self.host.srs[self.host.getSRName(sruuid)]
        domain  = "<domain type='vmware'>"
        domain += "  <name>%s</name>" % self.name
        domain += "  <memory unit='MiB'>%d</memory>" % self.memory
        domain += "  <currentMemory unit='MiB'>%d</currentMemory>" % self.memory
        domain += "  <vcpu placement='static'>%d</vcpu>" % self.vcpus
        domain += "  <os>"
        domain += "    <type arch='i686'>hvm</type>"
        domain += "    <boot dev='hd'/>"
        domain += "  </os>"
        domain += "  <clock offset='utc'/>"
        domain += "  <on_poweroff>destroy</on_poweroff>"
        domain += "  <on_reboot>restart</on_reboot>"
        domain += "  <on_crash>destroy</on_crash>"
        domain += "  <devices>"
        domain += "    <disk type='file' device='disk'>"
        domain += "      <source file='%s'/>" % srobj.getVDIPath(vdiname)
        domain += "      <target dev='%sa' bus='%s'/>" % (self._getDiskDevicePrefix(), self._getDiskDeviceBus())
        domain += "      <address type='drive' controller='0' bus='0' target='0' unit='0'/>"
        domain += "    </disk>"
        domain += "    <controller type='scsi' index='0' model='lsilogic'/>"
        domain += "    <controller type='ide' index='0'/>"
        domain += "    <input type='mouse' bus='ps2'/>"
        domain += "    <graphics type='vnc' autoport='yes'>"
        domain += "      <listen type='address' address='0.0.0.0'/>"
        domain += "    </graphics>"
        domain += "    <video>"
        domain += "      <model type='vmvga' vram='16384'/>"
        domain += "    </video>"
        domain += "  </devices>"
        domain += "</domain>"
        self._defineXML(domain)

    def installDrivers(self, source=None, extrareboot=False, useLegacy=False):
        # no autorun
        self.winRegAdd("HKCU", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\policies\\Explorer", "NoDriveTypeAutorun", "DWORD", 0xFF)
        self.host.execdom0("vim-cmd vmsvc/tools.install %s" % (self._esxGetVMID()))
        xenrt.sleep(30)
        code = self.xmlrpcExec("start /wait D:\\setup.exe /S /v\"/qn REBOOT=R\"", returnrc=True)

        if code == 3010: # ERROR_SUCCESS_REBOOT_REQUIRED
            xenrt.TEC().logverbose("VMware tools installer indicated the need to reboot")
            self.reboot()

        # Switch devices over to use PV drivers automatically
        self.usePVdrivers()

    def changeToPVSCSI(self, force=False):
        self.shutdown(force=force)

        # 1. Attach a dummy VDI on a PVSCSI controller
        dummyDiskPos = self.createDisk(sizebytes=256*xenrt.MEGA, controllerType='scsi', controllerModel='vmpvscsi')

        # 2. Boot the VM so that Windows installs the PVSCSI driver
        self.start()
        xenrt.sleep(30)
        self.shutdown(force=force)

        # 3. Delete the dummy VDI (and the PVSCSI controller will disappear)
        self.removeDisk(userdevicename=dummyDiskPos)

        # 4. Convert the main SCSI controller to PVSCSI
        self.changeControllerDriver('vmpvscsi', typ='scsi', index=0)

        self.start()
        self.reboot()

    def changeToVMXNet3(self, force=False):
        self.shutdown(force=force)
        self.changeVIFDriver("vmxnet3")
        self.start()

    def insertToolsCD(self):
        # Insert the ISO (with the VM stopped, in case we need to create a CD drive to do this)
        self.shutdown(force=True)
        self.changeCD("/usr/lib/vmware/isoimages/linux.iso", absolutePath=True)
        self.start()

    def installKernelHeaders(self):
        # Debian
        if self.execguest("test -e /etc/debian_version", retval="code") == 0:
            self.execguest("apt-get -y --force-yes install linux-headers-$(uname -r)")

        # Centos 4 or 5 or RHEL 5
        elif self.execguest(\
                    "grep -qi CentOS /etc/redhat-release", retval="code") == 0 or \
                self.execguest(\
                    "grep -qi 'Red Hat.*release 5' /etc/redhat-release", retval="code") == 0:
            raise xenrt.XRTError("Obtaining kernel headers for %s (CentOS 4/5, RHEL 5) currently unsupported" % (self.getName()))

        # RHEL 4
        elif self.execguest("grep -qi 'Red Hat.*release 4' /etc/redhat-release", retval="code") == 0:
            raise xenrt.XRTError("Obtaining kernel headers for %s (RHEL 4) currently unsupported" % (self.getName()))

        else:
            raise xenrt.XRTError("No support for downloading kernel headers of %s" % (self.getName()))

    def usePVdrivers(self, force=False):
        self.changeToVMXNet3(force=force)
        self.changeToPVSCSI(force=force)

        self.enlightenedDrivers = True

    def installTools(self, reboot=False, updateKernel=True):
        # On newer guests, VMware prefers the use of open-vm-tools (http://kb.vmware.com/kb/2073803)
        if self.distro.startswith("debian70"):
            self.execguest("apt-get -y --force-yes install open-vm-tools")
        else:
            self.installLegacyTools(reboot, updateKernel)

        # Check it's installed and output the version
        version = self.execguest("/usr/bin/vmware-toolbox-cmd -v").strip()
        xenrt.TEC().logverbose("installed vmware tools version %s" % (version))

        # Switch devices over to use PV drivers automatically
        self.usePVdrivers(force=False)

    def installLegacyTools(self, reboot=False, updateKernel=True):
        self.insertToolsCD()

        # Assume that the CD drive is at /dev/sr0 in the VM
        device = "sr0"
        mountpoint = "/mnt"
        self.execguest("mkdir -p %s || true" % (mountpoint))

        installed = False
        for dev in [device, device, "cdrom"]:
            try:
                self.execguest("mount /dev/%s %s" % (dev, mountpoint))
                installed = True
                break
            except:
                xenrt.TEC().warning("Mounting tools ISO failed on the first attempt.")
                xenrt.sleep(30)

        if not installed:
            raise xenrt.XRTFailure("Couldn't mount tools ISO")

        # Install linux headers
        self.installKernelHeaders()

        # Run the VMware tools installer
        unpackdir = self.execguest("mktemp -d").strip()
        self.execguest("cd %s && tar xvfz %s/VMwareTools*.tar.gz" % (unpackdir, mountpoint))
        output = self.execguest("cd %s/vmware-tools-distrib && ./vmware-install.pl -d" % (unpackdir)) # '-d' means accept all defaults
        xenrt.TEC().logverbose("vmware tools installation output: %s" % (output))
        self.execguest("rm -rf %s" % (unpackdir))

        # TODO eject the CD?

    def enablePXE(self, pxe=True):
        pass

    def xmlrpcTailor(self):
        xenrt.lib.libvirt.Guest.xmlrpcTailor(self)

        # Also disable automatic sleep
        for sleepType in ["monitor", "disk", "standby", "hibernate"]:
            self.xmlrpcExec("powercfg -change -%s-timeout-ac 0" % (sleepType))

    def importVM(self, host, file, sr=None, vifs=[]):
        """
        file is be an absolute path on site controller of type *.ovf or *.ova, which is to be imported.
        """
        ovftoolVersion = xenrt.command("ovftool --version", level=xenrt.RC_OK)
        if ovftoolVersion==1:
            ovftool=xenrt.TEC().getFile("http://10.102.123.140/misc/VMware-ovftool-4.1.0-2459827-lin.x86_64.bundle")
            xenrt.command("sudo sh %s --eulas-agreed --regular --required"% ovftool)
        if not sr:
            sr=host.getDefaultDatastore()
        ovfInfo=xenrt.command("ovftool --machineOutput %s" % file)
        ovfInfoDict=xmltodict.parse("<data"+ovfInfo.split("probeResult")[1].replace("\n+","")+"data>")
        ovfNetworkList=ovfInfoDict["data"]["networks"]["network"]
        brs = host.getBridges()

        command ='ovftool --noSSLVerify '
        command+='-n="%s" ' % self.name
        command+='-ds="%s" ' % sr
        for net in ovfNetworkList:
            if net["name"].strip() in brs:
                command+='--net:"%s"="%s" ' % (net["name"].strip(),net["name"].strip())
            else:
                command+='--net:"%s"="%s" ' % (net["name"].strip(),host.getPrimaryBridge())
        command+='%s vi://%s:%s@%s/' % (file, "root", host.password, host.getIP())
        xenrt.command(command)
        xenrt.sleep(5)
        self.existing(host)

        if not vifs:
            self.reparseVIFs()
            self.vifs.sort()
        else:
            self.vifs = vifs
        self.recreateVIFs(newMACs=True)
