#
# XenRT: Test harness for Xen and the XenServer product family
#
# Tests of PV drivers
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time
import xenrt
import xenrt.lib.xenserver

class TCVerifyDriversUptoDate(xenrt.TestCase):

    def run(self, arglist=None):
        gname = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]

        if not gname:
            raise xenrt.XRTError("No guest name specified.")

        guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        if not guest.pvDriversUpToDate():
            raise xenrt.XRTFailure("PV Drivers are not reported as up-to-date after installation")


class TCVerifyDriversOutOfDate(xenrt.TestCase):

    def run(self, arglist=None):
        gname = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]

        if not gname:
            raise xenrt.XRTError("No guest name specified.")

        guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            xenrt.TEC().skip("Skipping these tests from Dundee onwards")
        elif guest.pvDriversUpToDate():
            raise xenrt.XRTFailure("PV Drivers are not reported as out-of-date")


class TCDriverInstall(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCDriverInstall")
        self.blocker = True

    def run(self, arglist=None):

        if xenrt.TEC().lookup(["CLIOPTIONS", "NOINSTALL"],
                              False,
                              boolean=True):
            xenrt.TEC().skip("Skipping because of --noinstall option.")
            return

        # Mandatory args.
        gname = None
        verify = False
        useHostTimeUTC = False
        resident_on = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" %
                                        (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "verify":
                if l[1] == "yes":
                    verify = True
            elif l[0] == "resident_on":
                resident_on = l[1]
            elif l[0] == "useHostTimeUTC":
                useHostTimeUTC = True

        if not gname:
            raise xenrt.XRTError("No guest name specified.")

        guest = None
        if resident_on:
            host = self.getHost(resident_on)
            guest = host.getGuest(gname)
        else:
            guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        # Make sure the guest is up
        if guest.getState() == "DOWN":
            xenrt.TEC().comment("Starting guest for driver install")
            try:
                guest.start()
            except xenrt.XRTFailure, e:
                raise xenrt.XRTError(e.reason)

        if isinstance(guest, xenrt.lib.xenserver.guest.TampaGuest):
            guest.installDrivers(useHostTimeUTC=useHostTimeUTC,ejectISO=False)
        else:
            guest.installDrivers()

        if xenrt.TEC().lookup("DISABLE_EMULATED_DEVICES", False, boolean=True):
            guest.shutdown()
            cli = guest.getCLIInstance()
            cli.execute("vm-param-set", "uuid=%s platform:parallel=none" % guest.getUUID())
            cli.execute("vm-param-set", "uuid=%s other-config:hvm_serial=none" % guest.getUUID())
            cli.execute("vm-param-set", "uuid=%s platform:nousb=true" % guest.getUUID())
            cli.execute("vm-param-set", "uuid=%s platform:monitor=null" % guest.getUUID())
            guest.removeCD()
            guest.start()
        if verify:
            time.sleep(120)
            guest.enableDriverVerifier()


class TCDriverUpgrade(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCDriverUpgrade")
        self.blocker = True

    def run(self, arglist=None):

        gname = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" %
                                        (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified.")
        guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        # Make sure the guest is up
        if guest.getState() == "DOWN":
            xenrt.TEC().comment("Starting guest for driver upgrade")
            try:
                guest.start()
            except xenrt.XRTFailure, e:
                raise xenrt.XRTError(e.reason)

        if guest.windows:
            guest.installDrivers()
        else:
            guest.installTools()
        guest.waitForAgent(60)
        guest.shutdown()


class TCGPODoesNotBSOD(xenrt.TestCase):

    def run(self, arglist=None):
        host = self.getDefaultHost()
        guest = self.getGuest(host.listGuests()[0])
        self.__setGPO(guest)
        guest.reboot()
        guest.installDrivers()
        guest.checkHealth()

    def __setGPO(self, guest):
        """
        This is the registry key settings for the required Group Policy Object
        """
        guest.winRegAdd("HKLM", """SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions""", "DenyDeviceIDs", "DWORD", 1)
        guest.winRegAdd("HKLM", """SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions""", "DenyDeviceIDsRetroactive", "DWORD", 0)
        guest.winRegAdd("HKLM", """SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions\DenyDeviceIDs""", "1", "SZ", """USB\\\\Class_0e&SubClass_03&Prot_00""")
