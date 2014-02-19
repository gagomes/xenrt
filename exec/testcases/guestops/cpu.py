#
# XenRT: Test harness for Xen and the XenServer product family
#
# CPU resource operations.
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time
import xenrt

class TCCPUWalk(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCCPUWalk")
        self.blocker = True

    def run(self, arglist=None):

        hotplug = True
        hotunplug = True
        max = 8
        gname = None
        noplugwindows = False

        # Mandatory args:
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "max":
                if l[1] == "skip":
                    xenrt.TEC().skip("Skipping due to max=skip arg")
                    return
                max = int(l[1])
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" %
                                        (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "nohotplug":
                hotplug = False
            elif l[0] == "nohotunplug":
                hotunplug = False
            elif l[0] == "noplugwindows":
                noplugwindows = True

        if not gname:
            raise xenrt.XRTError("No guest name specified.")
        guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        # Check if we can hot(un)plug
        if noplugwindows and guest.windows:
            hotplug = False
            hotunplug = False
        elif guest.distro:
            x = string.split(guest.host.lookup("GUEST_NO_HOTPLUG_CPU", ""),
                             ",")
            if guest.distro in x:
                hotplug = False
            x = string.split(guest.host.lookup("GUEST_NO_HOTUNPLUG_CPU", ""),
                             ",")
            if guest.distro in x:
                hotunplug = False

        # See if we have guest SKU limits
        if guest.host.lookup("VCPU_IS_SINGLE_CORE", False, boolean=True):
            usecap = "MAXSOCKETS"
        else:
            usecap = "MAXCORES"
        cpucap = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                         guest.distro,
                                         usecap],
                                        "0"))
        if cpucap and cpucap < max:
            xenrt.TEC().comment("%s is capped to %u CPUs" %
                                (guest.distro, cpucap))
            max = cpucap

        initial = guest.cpuget()

        if hotplug:
            # Make sure VCPUs-max is sufficient
            cmax = int(guest.paramGet("VCPUs-max"))
            if cmax < max:
                xenrt.TEC().progress("Updating VCPUs-max to %u" % (max))
                if guest.getState() == "UP":
                    guest.shutdown()
                guest.paramSet("VCPUs-max", "%u" % (max))

        if hotplug and hotunplug:
            comment = "hot plug and unplug"
        elif hotplug:
            comment = "hot plug only"
        elif hotunplug:
            comment = "hot unplug only"
        else:
            comment = "no hot (un)plug"
        xenrt.TEC().comment("Starting with %u vCPUS up to %u vCPUS; %s" %
                            (initial, max, comment))

        hostcores = guest.host.getCPUCores()
        for i in range(max):
            target = ((initial + i) % max) + 1
            
            xenrt.TEC().progress("Testing target of %u vCPU(s)" % (target))
            if target > hostcores:
                xenrt.TEC().warning("Attempting to test with %u vCPUs on a "
                                    "host with only %u cores" %
                                    (target, hostcores))
                
            if target > guest.cpuget():
                if hotplug and guest.getState() != "UP":
                    guest.start()
                elif not hotplug and guest.getState() == "UP":
                    guest.shutdown()
            else:
                if hotunplug and guest.getState() != "UP":
                    guest.start()
                elif not hotunplug and guest.getState() == "UP":
                    guest.shutdown()

            if guest.getState() == "UP":
                guest.cpuset(target, live=True)
            else:
                guest.cpuset(target)

            if guest.getState() != "UP":
                guest.start()
                time.sleep(30)
                guest.reboot()
                guest.check()
            else:
                time.sleep(5)

            # Allow time for all CPUs to start up
            time.sleep(target * 25)

            # Check again, this is for configs where we only warn on
            # resource mismatches
            n = guest.getGuestVCPUs()
            if n != target:
                raise xenrt.XRTFailure("Wanted %u vCPUs, guest only had %u" %
                                       (target, n))
            
