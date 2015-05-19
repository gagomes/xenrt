#
# XenRT: Test harness for Xen and the XenServer product family
#
# Power control of physical machines
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

# XXX May need to remove random relays (or at least make them optional
# for HA testing, as we might want simultaneous failures)

import sys, os, string, time, random, re
import xenrt, xenrt.util

class _PowerCtlBase(object):
    """A base class for power control implementations"""

    def __init__(self, machine):
        self.machine = machine
        self.antiSurge = True
        self.verbose = False

    def log(self, msg):
        xenrt.TEC().logverbose(msg)
        if self.verbose:
            sys.stderr.write(msg)

    def setAntiSurge(self, antiSurge):
        self.antiSurge = antiSurge

    def off(self):
        raise xenrt.XRTError("Unimplemented")

    def on(self):
        raise xenrt.XRTError("Unimplemented")

    def cycle(self, fallback=False):
        # Default implementation
        self.off()
        xenrt.sleep(5)
        self.on()

    def triggerNMI(self):
        raise xenrt.XRTError("Unimplemented")

    def status(self):
        """Returns a tuple of (status, source) indicating the power status"""
        return ("unknown", "unknown")

    def command(self, command, retval="string"):
        if self.verbose:
            sys.stderr.write("Executing %s\n" % command)
        return xenrt.util.localOrRemoteCommand(command, retval)

    def setVerbose(self):
        self.verbose = True

    def setBootDev(self, dev, persistent=False):
        raise xenrt.XRTError("Unsupported")

class Dummy(_PowerCtlBase):

    def off(self):
        xenrt.TEC().logverbose("Simulating power off of %s" % 
                               (self.machine.name))

    def on(self):
        xenrt.TEC().logverbose("Simulating power on of %s" % 
                               (self.machine.name))

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Simulating power cycle of %s" %
                               (self.machine.name))

class Xenuse(_PowerCtlBase):

    def xenuse(self,action):
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.
        if self.antiSurge:
            xenrt.sleep(random.randint(0, 20))
        xenuse = xenrt.TEC().lookup("XENUSE", default="xenuse")
        mname = string.split(self.machine.name, ".")[0]
        succeeded = False
        for i in range(3):
            if self.command("%s --%s %s" % (xenuse, action, mname),
                                  retval="code") == 0:
                succeeded = True
                break
            xenrt.sleep(30)
        if not succeeded:
            raise xenrt.XRTError("Error performing %s on %s with xenuse" %
                                 (action,self.machine.name))

    def off(self):
        xenrt.TEC().logverbose("Turning off machine %s" % (self.machine.name))
        self.xenuse("off")

    def on(self):
        xenrt.TEC().logverbose("Turning on machine %s" % (self.machine.name))
        self.xenuse("on")

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Power cycling machine %s" % (self.machine.name))
        self.xenuse("reboot")
        # Just in case it was turned off
        xenrt.sleep(6) # Avoid a weird bug where this somehow cancels the reboot
        self.xenuse("on")

class AskUser(_PowerCtlBase):

    def pause(self, msg):
        if xenrt.GEC().jobid():
            xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "yes")
            xenrt.TEC().tc.pause(msg)
            xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "no")
            return True
        else:
            return False

    def off(self):
        if not self.pause("Please turn off machine %s" % self.machine.name):
            print "\nPlease turn off machine %s and press enter\n" % \
                  (self.machine.name)
            dummy = sys.stdin.readline()
            print "Enter pressed."

    def on(self):
        if not self.pause("Please turn on machine %s" % self.machine.name):
            print "\nPlease turn on machine %s and press enter\n" % \
                  (self.machine.name)
            dummy = sys.stdin.readline()
            print "Enter pressed."

    def cycle(self, fallback=False):
        if not self.pause("Please power cycle machine %s" % self.machine.name):
            print "\nPlease power cycle machine %s and press enter\n" % \
                  (self.machine.name)
            dummy = sys.stdin.readline()
            print "Enter pressed."

class Soft(_PowerCtlBase):

    def off(self):
        xenrt.TEC().logverbose("Trying a soft shutdown of %s" % 
                               (self.machine.name))
        host = self.machine.getHost()
        host.execcmd("/sbin/poweroff")
        xenrt.sleep(15)

    def on(self):
        print "\nPlease turn on machine %s and press enter\n" % \
              (self.machine.name)
        dummy = sys.stdin.readline()
        print "Enter pressed."

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Trying a soft reboot of %s" %
                               (self.machine.name))
        host = self.machine.getHost()
        host.execcmd("/sbin/reboot")
        xenrt.sleep(15)         

class PDU(_PowerCtlBase):
    PDU_PREFIXES = ["PDU", "PDU0", "PDU1", "PDU2", "PDU3", "PDU4", "PDU5", "PDU6"]

    def __init__(self, machine):
        _PowerCtlBase.__init__(self, machine)
        self.pdus = []
        for p in self.PDU_PREFIXES:
            address = xenrt.TEC().lookupHost(self.machine.name, "%s_ADDRESS" % p, None)
            if address:
                comm = xenrt.TEC().lookupHost(self.machine.name, "%s_COMMUNITY_STRING" % p, "private")
                pduvendor = xenrt.TEC().lookupHost(self.machine.name, "%s_VENDOR" % p, "APC")
                if pduvendor == "RARITAN":
                    values = {"on": 1, "off": 0, "cycle": 2}
                    oidbase = xenrt.TEC().lookupHost(self.machine.name,
                                         "%s_OID_BASE" % p,
                                         ".1.3.6.1.4.1.13742.6.4.1.2.1.2.1")
                else:
                    values = {"on": 1, "off": 2, "cycle": 3}
                    oidbase = xenrt.TEC().lookupHost(self.machine.name,
                                         "%s_OID_BASE" % p,
                                         ".1.3.6.1.4.1.318.1.1.12.3.3.1.1.4")

                pduport = xenrt.TEC().lookupHost(self.machine.name, "%s_PORT" % p, None)
                if not pduport:
                    raise xenrt.XRTError("No PDU port found for %s" % (self.machine.name))
                self.pdus.append((address, comm, oidbase, pduport, values))

    def snmp(self,value):
        if len(self.pdus) == 0:
            raise xenrt.XRTError("No PDU found for %s" %
                                 (self.machine.name))
        for p in self.pdus:
            (address, comm, oidbase, pduport, values) = p
            command = "snmpset -v1 -c %s %s %s.%s i %d" % \
                      (comm, address, oidbase, pduport, values[value])
            pdulock = xenrt.resources.CentralResource()
            attempts = 0
            while True:
                try:
                    pdulock.acquire("SNMP_PDU")
                    break
                except:
                    xenrt.sleep(10)
                    attempts += 1
                    if attempts > 6:
                        raise xenrt.XRTError("Couldn't get SNMP PDU lock.")
            try:
                attempts = 0
                while True:
                    try:
                        self.command(command)
                        break
                    except Exception, e:
                        if self.verbose:
                            sys.stderr.write("SNMP failed, waiting 30 seconds before retry\n")
                        attempts += 1
                        if attempts >= 3:
                            raise
                        xenrt.sleep(30)
            finally:
                pdulock.release()

    def off(self):
        xenrt.TEC().logverbose("Turning off machine %s" % (self.machine.name))
        self.snmp("off")

    def on(self):
        xenrt.TEC().logverbose("Turning on machine %s" % (self.machine.name))
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.
        if self.antiSurge:
            xenrt.sleep(random.randint(0, 20))
        self.snmp("on")

    def cycle(self, fallback=False):
        cyclehack = int(xenrt.TEC().lookupHost(self.machine.name,
                                               "PDU_REBOOT_DELAY",
                                               "0"))
        if not cyclehack and len(self.pdus) > 1:
            cyclehack = 10

        if cyclehack:
            # Rather than reboot we'll power down, sleep and then power up
            self.off()
            xenrt.sleep(cyclehack)
            self.on()
        else:
            xenrt.TEC().logverbose("Power cycling machine %s" % (self.machine.name))
            # Wait a random delay to try to avoid power surges when testing
            # with multiple machines.
            if self.antiSurge:
                xenrt.sleep(random.randint(0, 20))
            self.snmp("cycle")

    def status(self):
        if len(self.pdus) == 0:
            raise xenrt.XRTError("No PDU found for %s" %
                                 (self.machine.name))
        result = None
        for p in self.pdus:
            (address, comm, oidbase, pduport, values) = p
            command = "snmpget -v1 -c %s %s %s.%s" % \
                      (comm, address, oidbase, pduport)
            pdulock = xenrt.resources.CentralResource()
            attempts = 0
            while True:
                try:
                    pdulock.acquire("SNMP_PDU")
                    break
                except:
                    xenrt.sleep(10)
                    attempts += 1
                    if attempts > 6:
                        raise xenrt.XRTError("Couldn't get SNMP PDU lock.")
            try:
                attempts = 0
                while True:
                    try:
                        data = self.command(command)
                        m = re.search("INTEGER: (\d)", data)
                        if m:
                            val = int(m.group(1))
                            result = [x for x in values.keys() if values[x]==val][0]
                            break
                    except Exception, e:
                        if self.verbose:
                            sys.stderr.write("SNMP failed, waiting 30 seconds before retry\n")
                        attempts += 1
                        if attempts >= 3:
                            raise
                        xenrt.sleep(30)
            finally:
                pdulock.release()
        return (result, "PDU")

class ILO(_PowerCtlBase):

    def off(self):
        xenrt.TEC().logverbose("Turning off machine %s" % (self.machine.name))
        self.ilo("off")

    def on(self):
        xenrt.TEC().logverbose("Turning on machine %s" % (self.machine.name))
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.
        if self.antiSurge:
            xenrt.sleep(random.randint(0, 20))
        self.ilo("on")

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Power cycling machine %s" % (self.machine.name))
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.
        if self.antiSurge:
            xenrt.sleep(random.randint(0, 20))
        self.ilo("reboot")

    def ilo(self, action):
        script = xenrt.TEC().lookup("POWERCTL_ILO_SCRIPT", None)
        if script:
            # Old method
            address = self.machine.host.lookup("ILO_ADDRESS", None)
            if not address:
                raise xenrt.XRTError("No ILO adress specified.")
            command = "%s %s" % (script, address)
            self.command(command)
        else:
            # New method
            address = self.machine.host.lookup("ILO_ADDRESS", None)
            if not address:
                raise xenrt.XRTError("No ILO address specified")
            command = "%s/utils/ilo.pl -a %s -o %s" % \
                      (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"),
                       address,action)
            login = self.machine.host.lookup("ILO_LOGIN", None)
            if login:
                command += " -l %s" % (login)
            password = self.machine.host.lookup("ILO_PASSWORD", None)
            if password:
                command += " -p %s" % (password)
            self.command(command)

class IPMIWithPDUFallback(_PowerCtlBase):
    
    def __init__(self, machine):
        _PowerCtlBase.__init__(self, machine)
        self.ipmi = IPMI(machine)
        self.PDU = PDU(machine)

    def setBootDev(self, dev, persist=False):
        self.ipmi.setBootDev(dev, persist)

    def setVerbose(self):
        _PowerCtlBase.setVerbose(self)
        self.ipmi.setVerbose()
        self.PDU.setVerbose()

    def setAntiSurge(self, antiSurge):
        self.ipmi.setAntiSurge(antiSurge)
        self.PDU.setAntiSurge(antiSurge)

    def triggerNMI(self):
        self.ipmi.triggerNMI()

    def off(self):
        try:
            self.ipmi.off()
        except:
            xenrt.TEC().logverbose("IPMI failed, falling back to PDU control")
            self.PDU.off()

    def on(self):
        try:
            self.ipmi.on()
        except:
            xenrt.TEC().logverbose("IPMI failed, falling back to PDU control")
            self.PDU.on()
            if self.machine.consoleLogger:
                xenrt.TEC().logverbose("Waiting 60 seconds before resetting serial console")
                xenrt.sleep(60)
                self.machine.consoleLogger.reload()

    def status(self):
        try:
            return self.ipmi.status()
        except:
            xenrt.TEC().logverbose("IPMI failed, falling back to PDU control")
            return self.PDU.status()

    def cycle(self, fallback=False):
        try:
            if fallback:
                raise xenrt.XRTError("Hard reset requested")
            self.ipmi.cycle()
        except:
            xenrt.TEC().logverbose("IPMI failed, falling back to PDU control")
            self.PDU.cycle()
            if self.machine.consoleLogger:
                xenrt.TEC().logverbose("Waiting 60 seconds before resetting serial console")
                xenrt.sleep(60)
                self.machine.consoleLogger.reload()

class IPMI(_PowerCtlBase):

    def getPower(self):
        status = self.ipmi("chassis power status")
        if re.search("is off", status):
            return "off"
        elif re.search("is on", status):
            return "on"

    def setBootDev(self, dev, persist=False):
        cmd = "chassis bootdev %s" % dev
        if persist:
            cmd += " options=persistent"
        self.ipmi(cmd, resetOnFailure=False)

    def triggerNMI(self):
        self.ipmi("chassis power diag")

    def off(self):
        xenrt.TEC().logverbose("Turning off machine %s" % (self.machine.name))
        if xenrt.TEC().lookupHost(self.machine.name, "IPMI_IGNORE_STATUS", False, boolean=True) or self.getPower() != "off":
            self.ipmi("chassis power off")

    def on(self):
        xenrt.TEC().logverbose("Turning on machine %s" % (self.machine.name))
        # Some ILO controllers have broken serial on boot
        if xenrt.TEC().lookupHost(self.machine.name, "SERIAL_DISABLE_ON_BOOT",False, boolean=True) and self.machine.consoleLogger:
            self.machine.consoleLogger.pauseLogging()
            
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.
        if xenrt.TEC().lookupHost(self.machine.name, "IPMI_IGNORE_STATUS", False, boolean=True) or self.getPower() != "on":
            if xenrt.TEC().lookupHost(self.machine.name, "IPMI_SET_PXE",True, boolean=True):
                try:
                    self.setBootDev("pxe", True)
                except:
                    xenrt.TEC().logverbose("Warning: failed to set boot dwvice to PXE")
            if self.antiSurge:
                xenrt.sleep(random.randint(0, 20))
            self.ipmi("chassis power on")

    def status(self):
        result = self.ipmi("chassis power status")
        m = re.search("Chassis Power is (.+)\n", result)
        if m:
            return (m.group(1), "IPMI")
        return ("unknown", "IPMI")

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Power cycling machine %s" % (self.machine.name))
        # Some ILO controllers have broken serial on boot
        if xenrt.TEC().lookupHost(self.machine.name, "SERIAL_DISABLE_ON_BOOT",False, boolean=True) and self.machine.consoleLogger:
            self.machine.consoleLogger.pauseLogging()
        # Wait a random delay to try to avoid power surges when testing
        # with multiple machines.


        if self.antiSurge:
            xenrt.sleep(random.randint(0, 20))
        currentPower = self.getPower()

        if currentPower == "off" and xenrt.TEC().lookupHost(self.machine.name, "RESET_BMC", False, boolean=True):
            self.ipmi("mc reset cold")
            deadline = xenrt.timenow() + 120
            while xenrt.timenow() < deadline:
                xenrt.sleep(10)
                try:
                    self.ipmi("chassis power status")
                    break
                except:
                    pass
            if self.machine.consoleLogger:
                self.machine.consoleLogger.reload()
            
        if xenrt.TEC().lookupHost(self.machine.name, "IPMI_SET_PXE",True, boolean=True):
            try:
                self.setBootDev("pxe", True)
            except:
                xenrt.TEC().logverbose("Warning: failed to set boot dwvice to PXE")
        offon = xenrt.TEC().lookupHost(self.machine.name, "IPMI_RESET_UNSUPPORTED",False, boolean=True)
        if offon:
            if xenrt.TEC().lookupHost(self.machine.name, "IPMI_IGNORE_STATUS", False, boolean=True) or currentPower == "on":
                self.ipmi("chassis power off")
                xenrt.sleep(5)
            self.ipmi("chassis power on")
        else:
            if xenrt.TEC().lookupHost(self.machine.name, "IPMI_IGNORE_STATUS", False, boolean=True) or currentPower == "on":
                self.ipmi("chassis power reset")
                if xenrt.TEC().lookupHost(self.machine.name, "IPMI_IGNORE_STATUS", False, boolean=True):
                    self.ipmi("chassis power on")
            else:
                self.ipmi("chassis power on") # In case the machine was hard powered off

    def ipmi(self, action, resetOnFailure=True):
        # New method
        address = self.machine.host.lookup("BMC_ADDRESS", None)
        if not address:
            raise xenrt.XRTError("No BMC address specified")
        ipmiintf = self.machine.host.lookup("IPMI_INTERFACE", "lan")
        ipmipass = self.machine.host.lookup("IPMI_PASSWORD", None)
        if ipmipass:
            auth = "-P %s" % (ipmipass)
        else:
            auth = ""
        ipmiuser = self.machine.host.lookup("IPMI_USERNAME", None)
        if ipmiuser:
            user = "-U %s" % (ipmiuser)
        else:
            user = ""
        command = "ipmitool -vv -I %s -H %s %s %s %s" % \
                   (ipmiintf, address, auth, user, action)
        try:
            return self.command(command)
        except Exception, e:
            resetcmd = self.machine.host.lookup("BMC_RESET_COMMAND", None)
            if resetcmd and resetOnFailure:
                xenrt.TEC().logverbose("Could not execute command: %s" % str(e))
                self.command(resetcmd) # Reset the BMC
                xenrt.sleep(60) # Allow 1 minute for the IPMI controller to restart
                return self.command(command)
            else:
                raise


class Custom(_PowerCtlBase):

    def off(self):
        xenrt.TEC().logverbose("Running custom command to turn off machine %s" % (self.machine.name))
        self.runCustom("OFF")

    def on(self):
        xenrt.TEC().logverbose("Running custom command to turn on machine %s" % (self.machine.name))
        self.runCustom("ON")

    def cycle(self, fallback=False):
        xenrt.TEC().logverbose("Running custom command to power cycle machine %s" % (self.machine.name))
        if not self.machine.host.lookup("CUSTOM_POWER_CYCLE", None):
            self.runCustom("OFF")
            xenrt.sleep(10)
            self.runCustom("ON")
        else:
            self.runCustom("CYCLE")
            xenrt.sleep(5)
            self.runCustom("ON")

    def runCustom(self, action):
        # Look up command
        cmd = self.machine.host.lookup("CUSTOM_POWER_%s" % (action), None)
        if not cmd:
            raise xenrt.XRTError("No definition for CUSTOM_POWER_%s found" % (action))

        self.command(cmd)

class CiscoUCS(_PowerCtlBase):
    def off(self):
        self._ucs("admin-down")

    def on(self):
        self._ucs("admin-up")

    def cycle(self, fallback=False):
        self._ucs("cycle-immediate")

    def _ucs(self, op):
        fabric = self.machine.host.lookup("UCS_FABRIC_ADDRESS")
        user = self.machine.host.lookup("UCS_USERNAME")
        password = self.machine.host.lookup("UCS_PASSWORD")
        sp = self.machine.host.lookup("UCS_SERVICE_PROFILE", self.machine.name)
        root = self.machine.host.lookup("UCS_ROOT_ORG", "org-root")

        xenrt.TEC().logverbose("Sending %s to %s/%s/%s/%s/%s" % (op, fabric, user, password, root, sp))

        text = xenrt.command("%s/ucspower %s %s %s %s %s %s" % (
                                xenrt.TEC().lookup("LOCAL_SCRIPTDIR"),
                                fabric,
                                user,
                                password,
                                sp,
                                root,
                                op))
        if self.verbose:
            sys.stderr.write(text)

class Xapi(_PowerCtlBase):
    def off(self):
        try:
            self.xapi("vm-shutdown", force=True)
        except Exception, e:
            self.log("Warning: %s" % str(e))

    def on(self):
        try:
            self.xapi("vm-start")
        except Exception, e:
            self.log("Warning: %s" % str(e))
    
    def cycle(self, fallback=False):
        try:
            self.xapi("vm-shutdown", force=True)
        except Exception, e:
            self.log("Warning: %s" % str(e))
        self.xapi("vm-start")

    def xapi(self, cmd, force=False):
        addr = self.machine.host.lookup("CONTAINER_HOST")
        password = self.machine.host.lookup("CONTAINER_PASSWORD", xenrt.TEC().lookup("ROOT_PASSWORD"))
        cmd = "xe %s vm=%s" % (cmd, self.machine.name)
        if force:
            cmd += " --force"
        xenrt.SSH(addr, cmd, password=password, retval="string")
