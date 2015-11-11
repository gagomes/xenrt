import re,socket
import yaml
import xenrt
from racktables import RackTables

__all__ = ["getRackTablesInstance", "readMachineFromRackTables", "closeRackTablesInstance"]

_rackTablesInstance = None

BMC_ADDRESSES = ("IPMI", "BMC", "IDRAC", "DRAC", "IRMC", "IRMCS2", "ILO")

def getRackTablesInstance():
    global _rackTablesInstance
    if not _rackTablesInstance:
        rtHost = xenrt.GEC().config.lookup("RACKTABLES_DB_HOST", None)
        if not rtHost:
            return None
        rtUser = xenrt.GEC().config.lookup("RACKTABLES_DB_USER", None)
        rtDB = xenrt.GEC().config.lookup("RACKTABLES_DB_NAME", None)
        rtPassword = xenrt.GEC().config.lookup("RACKTABLES_DB_PASSWORD", None)
        _rackTablesInstance = RackTables(rtHost, rtDB, rtUser, rtPassword)
    return _rackTablesInstance

def closeRackTablesInstance():
    global _rackTablesInstance
    if _rackTablesInstance:
        _rackTablesInstance.close()
        _rackTablesInstance = None
    

def readMachineFromRackTables(machine,kvm=False,xrtMachine=None):
    global BMC_ADDRESSES
    rt = getRackTablesInstance()
    if not rt:
        return None
    o = rt.getObject(machine)
    ipDict = o.getIPAddrs()
    ip6Dict = o.getIP6Addrs()
    ports = o.getPorts()
    primaryInterface = None
    # For some infrastructure setup, we'll proceed without knowing the MAC addresses
    ignoreDisconnectedPorts = False

    # Get the main MAC address
    if not xenrt.GEC().config.lookupHost(machine, "MAC_ADDRESS", None):
        optionNets = xenrt.GEC().config.lookupHost(machine, "OPTION_CARBON_NETS", None)
        if optionNets:
            availablePorts = [p for p in ports if (p[2] or p[3]) and p[4] and p[0] == optionNets]
        else:
            availablePorts = sorted([p for p in ports if (p[2] or p[3]) and p[4] and (p[0].lower().startswith("e") or p[0].lower().startswith("nic"))], key=lambda x: re.sub(r"(\D)(\d)$",r"\g<1>0\g<2>",x[0]))
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "FORCE_NIC_ORDER"], "yes")
        # If there aren't any connected ports, use the first one anyway
        if len(availablePorts) == 0:
            availablePorts = sorted([p for p in ports if (p[2] or p[3]) and (p[0].lower().startswith("e") or p[0].lower().startswith("nic"))], key=lambda x: re.sub(r"(\D)(\d)$",r"\g<1>0\g<2>",x[0]))
            ignoreDisconnectedPorts = True

        if len(availablePorts) > 0:
            mac = availablePorts[0][2]
            if availablePorts[0][1].startswith("10G"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "NIC_SPEED"],"10G")
            if availablePorts[0][1].startswith("40G"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "NIC_SPEED"],"40G")
            primaryInterface = availablePorts[0][0]
            if mac:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "MAC_ADDRESS"],mac)

    # Get the main IP address
    if not xenrt.GEC().config.lookupHost(machine, "HOST_ADDRESS", None):
        ip = None
        interfaceIPs = [x for x in ipDict.keys() if ipDict[x] == primaryInterface] 
        ips = [x for x in ipDict.keys() if ipDict[x].upper() not in BMC_ADDRESSES] 
        if len(interfaceIPs) > 0:
            ip = interfaceIPs[0]
        elif len(ips) > 0:
            ip = ips[0]
        else:
            try:
                ip = xenrt.getHostAddress("%s.%s" % (machine, xenrt.GEC().config.lookup("MACHINE_DOMAIN")))
            except:
                pass
        if ip:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "HOST_ADDRESS"],ip)

    # Get the main IPv6 address
    if not xenrt.GEC().config.lookupHost(machine, "HOST_ADDRESS6", None):
        interfaceIPs = [x for x in ip6Dict.keys() if ip6Dict[x] == primaryInterface] 
        if len(interfaceIPs) > 0:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "HOST_ADDRESS6"],interfaceIPs[0])

    # Get IPMI info
    ipmi = False
    ipmiUser = o.getAttribute("IPMI Username")
    ipmiPassword = o.getAttribute("IPMI Password")
    if ipmiUser and not xenrt.GEC().config.lookupHost(machine, "IPMI_USERNAME", None):
        xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "IPMI_USERNAME"], ipmiUser)
    if ipmiPassword and not xenrt.GEC().config.lookupHost(machine, "IPMI_PASSWORD", None):
        xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "IPMI_PASSWORD"], ipmiPassword)
    bmcips = [x for x in ipDict.keys() if ipDict[x].upper() in BMC_ADDRESSES]
    if len(bmcips) > 0 and not xenrt.GEC().config.lookupHost(machine, "BMC_ADDRESS", None):
        xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "BMC_ADDRESS"], bmcips[0])

    if not xenrt.GEC().config.lookupHost(machine, "BMC_ADDRESS", None):
        bmcaddr = None
        for i in ("bmc", "ilo", "idrac"):
            for j in ("MACHINE_DOMAIN", "INFRASTRUCTURE_DOMAIN"):
                if not xenrt.GEC().config.lookup(j, None):
                    continue
                addr = "%s-%s.%s" % (machine, i, xenrt.GEC().config.lookup(j))
                try:
                    xenrt.getHostAddress(addr)
                except:
                    pass
                else:
                    bmcaddr = addr
                    break
        if bmcaddr:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "BMC_ADDRESS"], bmcaddr)
            if not xenrt.GEC().config.lookupHost(machine, "IPMI_USERNAME", None) and not xenrt.GEC().config.lookupHost(machine, "IPMI_PASSWORD", None):
                if "Dell" in (o.getAttribute("HW type") or ""):
                    xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "IPMI_USERNAME"], "root")
                    xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "IPMI_PASSWORD"], "calvin")

    if xenrt.TEC().lookupHost(machine, "BMC_ADDRESS", None):
        bmcweb = o.getAttribute("BMC Web UI") == "Yes"
        bmckvm = o.getAttribute("BMC KVM") == "Yes"

        if bmcweb:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "BMC_WEB"], "yes")
        if bmckvm:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "BMC_KVM"], "yes")

    # Figure out power control - rules are:
    # 1. Use the config file by default
    # 2. Use IPMI if we have IPMI IP, username and password (with fallback to PDU if we have PDU info)
    # 3. If we don't have IPMI, use PDU
    if not xenrt.GEC().config.lookupHost(machine, "POWER_CONTROL", None):
        if xenrt.GEC().config.lookupHost(machine, "BMC_ADDRESS", None):
            ipmiAddress = xenrt.GEC().config.lookupHost(machine, "BMC_ADDRESS")
            ipmiInterface = o.getAttribute("IPMI Interface")
            if not ipmiInterface:
                ipmiInterface = "lanplus"
            if xenrt.GEC().config.lookupHost(machine, "IPMI_USERNAME", None) and xenrt.GEC().config.lookupHost(machine, "IPMI_PASSWORD", None):
                ipmi = True
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "IPMI_INTERFACE"], ipmiInterface)
            intf = ipDict.get(xenrt.GEC().config.lookupHost(machine, "BMC_ADDRESS"))
            if intf:
                ipmiPorts = [p for p in ports if p[0].lower() == intf.lower()]
                if len(ipmiPorts) > 0:
                    ipmiMAC = ipmiPorts[0][2]
                    if ipmiMAC:
                        xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "BMC_MAC"], ipmiMAC)
        powerports = [p for p in ports if (p[1] == "AC-in" and p[4])]
        i = 0
        for p in powerports:
            if len(powerports) == 1:
                index = ""
            else:
                index = str(i)
            pdu = p[4]
            try:
                pduport = re.findall(r'\d+', p[5])[0]
            except Exception, e:
                continue
            ips = pdu.getIPAddrs()
            if len(ips) > 0:
                address = ips.keys()[0]
            else:
                address = "%s.%s" % (pdu.getName(), xenrt.GEC().config.lookup("INFRASTRUCTURE_DOMAIN"))
            oidbase = pdu.getAttribute("Base SNMP OID")
            comm = pdu.getAttribute("SNMP Community")
            if not comm:
                comm = "private"
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_ADDRESS" % index], address)
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_COMMUNITY_STRING" % index], comm)
            if oidbase:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_OID_BASE" % index], oidbase)
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_PORT" % index], pduport)
            vendor = pdu.getAttribute("HW type")
            if not vendor:
                pass
            elif vendor.startswith("APC"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_VENDOR" % index], "APC")
            elif vendor.startswith("Raritan"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "PDU%s_VENDOR" % index], "RARITAN")
            i += 1

        if ipmi and i > 0:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "POWER_CONTROL"], "ipmipdufallback")
        elif ipmi:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "POWER_CONTROL"], "ipmi")
        elif i > 0:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "POWER_CONTROL"], "PDU")

    # Console. Use IPMI if we have it
    if not xenrt.GEC().config.lookupHost(machine, "CONSOLE_TYPE", None):
        serialports = [p for p in ports if (p[1].startswith("RS-232") and p[4] and (not p[3] or p[3] != "Unused"))]
        if len(serialports) > 0:
            serport = serialports[0]
            ser = serport[4]
            try:
                port = re.findall(r'\d+', serport[5])[0]
            except Exception, e:
                pass
            else:
                ips = ser.getIPAddrs()
                if len(ips) > 0:
                    address = ips.keys()[0]
                else:
                    address = "%s.%s" % (ser.getName(), xenrt.GEC().config.lookup("INFRASTRUCTURE_DOMAIN"))
                portbase = ser.getAttribute("Serial Base TCP Port")
                if not portbase:
                    portbase = 4000
                port = int(port) + portbase
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"CONSOLE_TYPE"], "basic")
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"CONSOLE_ADDRESS"], address)
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"CONSOLE_PORT"], port)
        elif ipmi:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "CONSOLE_TYPE"], "ipmi")

    # Switch port
    if not xenrt.GEC().config.lookupHost(machine,"NETPORT", None):
        pp = [p for p in ports if p[0] == primaryInterface]
        if len(pp) > 0:
            p = pp[0]
            netport = getNetPortNameForPort(p)
            if netport:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS", machine, "NETPORT"], netport)
                
    # Secondary NICs
    if not xenrt.TEC().lookupHost(machine,"NICS",None):
        i = 1
        availablePorts = sorted([p for p in ports if p[3] and (p[4] or ignoreDisconnectedPorts) and (p[0].lower().startswith("e") or p[0].lower().startswith("nic")) and p[0] != primaryInterface], key=lambda x: re.sub(r"(\D)(\d)$",r"\g<1>0\g<2>",x[0]))
        for c in o.getChildren():
            if c.getType() == "PCI Card":
                cports = c.getPorts()
                availablePorts.extend(sorted([p for p in cports if p[3] and (p[4] or ignoreDisconnectedPorts) and (p[0].lower().startswith("e") or p[0].lower().startswith("nic"))], key=lambda x: re.sub(r"(\D)(\d)$",r"\g<1>0\g<2>",x[0])))
        for p in availablePorts:
            netport = getNetPortNameForPort(p)
            nicinfo = p[3].split(" - ")[0].split("/")
            network = nicinfo[0]
            if network.endswith("x"):
                continue
            if "RSPAN" in nicinfo[1:]:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"RSPAN"],"yes")
            mac = p[2]
            ip = [x for x in ipDict.keys() if ipDict[x] == p[0]]
            if len(ip) > 0:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"IP_ADDRESS"],ip[0])
            ip6 = [x for x in ip6Dict.keys() if ip6Dict[x] == p[0]]
            if len(ip6) > 0:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"IP_ADDRESS6"],ip6[0])
            if p[1].startswith("10G"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"SPEED"],"10G")
            if p[1].startswith("40G"):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"SPEED"],"40G")
            if netport:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"NETPORT"],netport)
            xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"NETWORK"],network)
            if mac:
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"NICS","NIC%d" % i,"MAC_ADDRESS"],mac)
            i += 1

    # Disks
    if not xenrt.TEC().lookupHost(machine,"OPTION_CARBON_DISKS", None):
        installDisk = o.getAttribute("Installation disk path")
        if installDisk:
            setDiskConfig(installDisk, ["HOST_CONFIGS",machine,"OPTION_CARBON_DISKS"])
        guestDisk = o.getAttribute("Data disk path")
        if guestDisk:
            setDiskConfig(guestDisk, ["HOST_CONFIGS",machine,"OPTION_GUEST_DISKS"])

    if not xenrt.TEC().lookupHost(machine, "PXE_CHAIN_LOCAL_BOOT", None):
        pxechain = o.getAttribute("PXE chain boot disk")
        if pxechain:
            xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"PXE_CHAIN_LOCAL_BOOT"], pxechain)

    if not xenrt.TEC().lookupHost(machine, "IPXE_EXIT", None):
        ipxeForce = o.getAttribute("Force iPXE Exit")
        if ipxeForce == "Yes":
            xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"IPXE_EXIT"], "yes")

    if not xenrt.TEC().lookupHost(machine, "OPTION_ROOT_MPATH", None):
        if o.getAttribute("Multipath Root Disk") == "Yes":
            xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"OPTION_ROOT_MPATH"], "enabled")
            if not xenrt.TEC().lookupHost(machine, "LOCAL_SR_POST_INSTALL", None) \
                    and xenrt.TEC().lookupHost(machine, "OPTION_CARBON_DISKS", None) != xenrt.TEC().lookupHost(machine, "OPTION_GUEST_DISKS", None):
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"LOCAL_SR_POST_INSTALL"], "yes")

    # Other config
    comment = o.getComment() or ""
    m = re.search("== XenRT config ==(.*)== XenRT config ==", comment, re.DOTALL|re.IGNORECASE)
    if m:
        try:
            cfg = yaml.load(m.group(1))
        except Exception, e:
            xenrt.TEC().logverbose("Warning - could not load yaml config from racktables: %s" % str(e))
        else:
            for k in cfg.keys():
                xenrt.GEC().config.config["HOST_CONFIGS"][machine][k] = cfg[k]

    # KVM (useful for DNS)
    try:
        if kvm:
            kvmports = [p for p in o.getPorts() if p[0] == "kvm" and p[4]]
            if len(kvmports) > 0:
                kvmport = kvmports[0]
                uplinkports = [p for p in kvmport[4].getPorts() if p[4] and p[4].getType() == "KVM switch" and (kvmport[4].getType() != "KVM switch" or len(kvmport[4].getPorts()) < len(p[4].getPorts()))]
                if len(uplinkports) > 0:
                    kvm = uplinkports[0][4]
                else:
                    kvm = kvmport[4]
                ips = kvm.getIPAddrs().keys()
                if len(ips) > 0:
                    xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"KVM_HOST"], ips[0])
                else:
                    if xenrt.GEC().config.lookup("INFRASTRUCTURE_DOMAIN", None):
                        ip = socket.gethostbyname("%s.%s" % (kvm.getName(), xenrt.GEC().config.lookup("INFRASTRUCTURE_DOMAIN")))
                        xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"KVM_HOST"], ip)
                kvmUser = kvm.getAttribute("Username")
                if not kvmUser:
                    kvmUser = "Admin"
                kvmPassword = kvm.getAttribute("Password")
                if not kvmPassword:
                    kvmPassword = ""

                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"KVM_USER"], kvmUser)
                xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"KVM_PASSWORD"], kvmPassword)


    except:
        pass
    if not xrtMachine:
        try:
            xrtMachine = xenrt.GEC().dbconnect.api.get_machine(machine)
        except:
            pass

    xenrt.GEC().config.setVariable(["HOST_CONFIGS",machine,"ASSET_URL"], "https://racktables.uk.xensource.com/index.php?page=object&object_id=%d" % o.getID())

    if xrtMachine:
        updateDict = {}
        for i in ("KVM_HOST", "KVM_USER", "KVM_PASSWORD", "IPMI_USERNAME", "IPMI_PASSWORD", "BMC_ADDRESS", "BMC_WEB", "BMC_KVM", "ASSET_URL"):

            if xrtMachine['params'].get(i, "") != xenrt.TEC().lookupHost(machine, i, ""):
                updateDict[i] = xenrt.TEC().lookupHost(machine, i, "")
        model = o.getAttribute("HW type")
        if model:
            model = model.replace("[", "").replace("]","").split(" | ")[0]
        descr = []
        if model and model != "noname/unknown":
            descr.append(model)
        cpu = o.getAttribute("CPU Model")

        if cpu:
            descr.append(cpu)

        descrstring = ", ".join(descr)

            
        if (not xrtMachine['description'] or xrtMachine['description'] in descrstring) and xrtMachine['description'] != descrstring and descrstring:
            updateDict['DESCRIPTION'] = descrstring
        if updateDict:
            print updateDict
            xenrt.GEC().dbconnect.api.update_machine(machine, params=updateDict)


def setDiskConfig(diskstring, path):
    m = re.match("CCISS:/dev/(.*) SCSI:/dev/(.*)", diskstring)
    if m:
        xenrt.GEC().config.setVariable(path + ["SCSI"], m.group(2))
        xenrt.GEC().config.setVariable(path + ["CCISS"], m.group(1))
    m = re.match("SCSI:/dev/(.*) CCISS:/dev/(.*)", diskstring)
    if m:
        xenrt.GEC().config.setVariable(path + ["SCSI"], m.group(1))
        xenrt.GEC().config.setVariable(path + ["CCISS"], m.group(2))
    m = re.match("/dev/(.*)", diskstring)
    if m:
        xenrt.GEC().config.setVariable(path, m.group(1))

def getNetPortNameForPort(port):
    netport = None
    if not port[5]:
        return None
    portNums = re.findall(r'\d+', port[5])
    if len(portNums) == 1:
        portNum = portNums[0]
        switch = port[4]
        stacks = [x for x in switch.getParents() if x.getType() == "Network Switch Stack"]
        if len(stacks) > 0:
            stack = stacks[0]
            netport = "%s-%d/%s" % (stack.getName(), switch.getAttribute("Stack Member"), portNum)
        else:
            netport = "%s-1/%s" % (switch.getName(), portNum)
    return netport

    
