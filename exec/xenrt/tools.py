#
# XenRT: Test harness for Xen and the XenServer product family
#
# Miscellaneous tools (aux mode xrt commands)
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, re, xml.dom.minidom, os, xmlrpclib, urllib, json, time
import xenrt
from xml.sax.saxutils import escape

global tccache
tccache = {}
global fasttccache
fasttccache = {}
global childrencache
childrencache = {}

global _jira
_jira = None
global _xmlrpcjira
_xmlrpcjira = None
global _xmlrpcjiraauth
_xmlrpcjiraauth = None

def testrunJSONLoad(tool, params):
    return json.load(urllib.urlopen("%s/rest/inquisitor/latest/%s?os_username=%s&os_password=%s&%s" %
                    (xenrt.TEC().lookup("JIRA_URL", None),
                    tool,
                    xenrt.TEC().lookup("JIRA_USERNAME"),
                    xenrt.TEC().lookup("JIRA_PASSWORD"),
                    params)))

def getIssue(j, issue):
    global tccache
    if issue not in tccache:#not tccache.has_key(issue):
        print "  Getting %s" % issue
        i = j.jira.issue(issue)
        tccache[issue] = i
    return tccache[issue]

def getIssues(j, issues):
    global tccache
    need = [x for x in issues if x not in tccache.keys()]
    pageSize = 25;
    i = 0
    while i < len(need):
        fetch = need[i:i+pageSize]
        print "  Getting %s" % ", ".join(fetch)
        try:
            found = j.jira.search_issues("key IN (%s)" % ",".join(fetch))
            for f in found:
                tccache[f.key] = f
        except:
            print "  Warning: could not get issues"
        i += pageSize

def _findOrCreateTestCase(existing, tcsummary, jiralink, container, desc, xenrttcid=None, xenrttcargs=None, component=None):
    j = jiralink
    if existing.has_key(tcsummary):
        try:
            existing[tcsummary].key
            t = getIssue(j, existing[tcsummary].key)
        except Exception as e:
            t = getIssue(j, existing[tcsummary])
        print "Found %s - %s" % (t.key, t.fields.summary)
    elif existing.has_key("[experimental] " + tcsummary):
        t = getIssue(j, existing["[experimental] " + tcsummary])
        print "Found %s - %s" % (t.key, t.fields.summary)
    else:
        # raise tcsummary
        print "Creating new issue for %s" % tcsummary
        t = j.jira.create_issue(project={"key":"TC"}, summary=tcsummary, issuetype={"name":"Test Case"})
        j.jira.create_issue_link(type="Contains", inwardIssue = container.key, outwardIssue=t.key)
        flushChildrenCache(container.key)
    d = t.fields.description
    if not d:
        d = ""
    if d != desc:
        t.update(description=desc)
    if xenrttcid:
        x = j.getCustomField(t, "xenrtTCID")
        if x != xenrttcid:
            j.setCustomField(t, "xenrtTCID", xenrttcid)
    if xenrttcargs:
        x = j.getCustomField(t,"xenrtTCArgs")
        if x != xenrttcargs:
            j.setCustomField(t, "xenrtTCArgs", xenrttcargs)
    x = j.getCustomField(t, "Test Case Type")
    if not x or x.value != "XenRT":
        j.setCustomField(t, "Test Case Type", "XenRT", choice=True)
    if component:
        xcomp = [x.name for x in t.fields.components]
        if xcomp != [component]:
            t.update(components=[{'name': component}])
    tcid = t.key
    return tcid

def _createXMLFragment(j,
                       output,
                       guestname,
                       testcase,
                       tcid,
                       name=None,
                       extraargs=None): 
    if name:
        alt = "name=\"%s\" " % (name)
    else:
        alt = ""
    output.append("        <testcase id=\"%s\" %stc=\"%s\">" % (testcase, alt, tcid))
    args = []
    if extraargs and len(extraargs) > 0 and extraargs[0] == False:
        args.append("N/A")
    args.append("guest=%s" % (guestname))
    if extraargs:
        for arg in extraargs:
            if arg:
                args.append(arg)
    output.extend(map(lambda x:"        <arg>%s</arg>" % (x), args))
    output.append("        </testcase>")
    t = getIssue(j, tcid)
    x = j.getCustomField(t, "xenrtTCID")
    if x != testcase:
        j.setCustomField(t, "xenrtTCID", str(testcase))
    xenrttcargs = string.join(args)
    x = j.getCustomField(t, "xenrtTCArgs")
    if x != xenrttcargs:
        j.setCustomField(t, "xenrtTCArgs", str(xenrttcargs))

def defineOSTests(distro,
                  desc,
                  windows=None,
                  arch=None):
    """Create Jira TC tickets for OS functionality tests for the specified
    OS. Return XML suitable for a sequence file."""

    j = J()

    # Check if this is Windows
    if windows == None and distro[0] in ('w', 'v'):
        windows = True
    if windows:
        comp = "Guest Compatibility - Windows"
    else:
        comp = "Guest Compatibility - Linux"

    # See if we have a hierarchy ticket for the OS
    osh = getIssue(j, "TC-6950")
    oshlinks = osh.fields.issuelinks
    container = None
    for oshlink in oshlinks:
        if oshlink.type.name == "Contains" and hasattr(oshlink, "outwardIssue"):
            if oshlink.outwardIssue.fields.summary == desc:
                container = getIssue(j, oshlink.outwardIssue.key)
                break

    # If not then make one
    if not container:
        print "Creating new container for %s" % desc
        container = j.jira.create_issue(project={"key":"TC"}, summary=desc, issuetype={"name":"Hierarchy"})
        j.jira.create_issue_link(type="Contains", inwardIssue="TC-6950", outwardIssue=container.key)

    print "Using %s as container for %s" % (container.key, desc)
    # Get a list of existing tickets for this OS
    existing = {}
    clinks = container.fields.issuelinks
    for clink in clinks:
        if clink.type.name == "Contains" and hasattr(clink, "outwardIssue"):
            t = getIssue(j, clink.outwardIssue.key)
            if t.fields.status.name in ("New", "Open"):
                existing[t.fields.summary] = t
    if arch:
        guestname = distro + arch
    else:
        guestname = distro

    # For each testcase create a testcase ticket unless one already
    # exists and output XML
    output = []
    output.append("    <serial group=\"%s\">" % (guestname))
    if windows:
        install = "xenserver.guest.TCXenServerWindowsInstall"
    elif distro in ('etch', 'sarge'):
        install = "xenserver.guest.TCXenServerDebianInstall"
    else:
        install = "xenserver.guest.TCXenServerVendorInstall"

    tcsummary = "Install %s" % (desc)
    tcdesc = "1. Install a %s VM using harness defaults\n" \
             "2. Verify the installed VM is working and reachable via the " \
             "network" % (desc)
    args = ["RESOURCE_HOST_0",
            "guest=%s" % (guestname),
            "distro=%s" % (distro)]
    if arch:
        args.append("arch=%s" % (arch))
    args.append("memory=1024")

    tcid =  _findOrCreateTestCase(existing,
                                 tcsummary,
                                 j,
                                 container,
                                 tcdesc,
                                 xenrttcid=install,
                                 xenrttcargs=string.join(args),
                                 component=comp)
    output.append("      <testcase id=\"%s\" name=\"VMInstall\" tc=\"%s\">" %
                  (install, tcid))
    output.extend(map(lambda x:"        <arg>%s</arg>" % (x), args))
    #output.append("        <arg>RESOURCE_HOST_0</arg>")
    #output.append("        <arg>guest=%s</arg>" % (guestname))
    #output.append("        <arg>distro=%s</arg>" % (distro))
    #if arch:
    #    output.append("        <arg>arch=%s</arg>" % (arch))
    #output.append("            <arg>memory=1024</arg>")
    
    output.append("      </testcase>")
    output.append("      <serial guest=\"%s\">" % (guestname))

    if windows:
        testcase = "guestops.drivers.TCDriverInstall"
        tcsummary = "Install PV drivers into %s" % (desc)
        tcdesc = "1. Install the PV drivers/tools package into the VM\n" \
                 "2. Verify the VM has switched to using PV drivers\n" \
                 "3. Verify the VM is working and reachable via the network\n" \
                 "4. Verify the guest agent is running\n"
        tcid = _findOrCreateTestCase(existing,
                                     tcsummary,
                                     j,
                                     container,
                                     tcdesc,
                                     component=comp)
        _createXMLFragment(j, output, guestname, testcase, tcid)
    if arch == "x86-64" :
        MAX = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                   distro,
                                  "MAX_VM_VCPUS64"], 8))
    else:
        MAX =  int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                   distro,
                                  "MAX_VM_VCPUS"], 8))

    for testdef in [("guestops.basic.TCStartStop",
                     "Startup-shutdown loop test of",
                     None,
                     "1. Start the VM and verify it is working\n"
                     "2. Shutdown the VM and verify it becomes halted\n"
                     "3. Repeat for 20 iterations\n",
                     ["loops=20"]),

                    ("guestops.basic.TCReboot",
                     "Reboot loop test of",
                     None,
                     "1. Reboot the VM and verify it has rebooted and works\n"
                     "2. Repeat for 20 iterations\n",
                     ["loops=20"]),

                    ("guestops.srm.TCSuspendResume",
                     "Suspend/resume loop test of",
                     None,
                     "1. Start stress workloads on the VM\n"
                     "2. Suspend the VM to local storage\n"
                     "3. Resume the VM and verify it is working\n"
                     "4. Repeat steps 2 and 3 for 20 iterations\n"
                     "5. Stop stress workloads\n"
                     "6. Check workload logs for problems\n",
                     ["workloads", "loops=20"]),

                    ("guestops.srm.TCMigrate",
                     "Localhost non-live migrate loop test of",
                     None,
                     "1. Start stress workloads on the VM\n"
                     "2. Perform a localhost non-live migrate\n"
                     "3. Verify the VM is working\n"
                     "4. Repeat steps 2 and 3 for 10 iterations\n"
                     "5. Stop stress workloads\n"
                     "6. Check workload logs for problems\n",
                     ["workloads", "loops=10"]),

                    ("guestops.srm.TCMigrate",
                     "Localhost live migrate loop test of",
                     "TCLiveMigrate",
                     "1. Start stress workloads on the VM\n"
                     "2. Perform a localhost live migrate\n"
                     "3. Verify the VM is working\n"
                     "4. Repeat steps 2 and 3 for 20 iterations\n"
                     "5. Stop stress workloads\n"
                     "6. Check workload logs for problems\n",
                     ["live", "workloads", "loops=20"]),

                    ("guestops.srm.TCHibernate",
                     "Hibernate-resume loop test of",
                     None,
                     "1. Start stress workloads on the VM\n"
                     "2. Hibernate the VM using Windows commands\n"
                     "3. Start the VM to resume from hibernate\n"
                     "4. Repeat steps 2 and 3 for 10 iterations\n"
                     "5. Stop stress workloads\n"
                     "6. Check workload logs for problems\n",
                     ["workloads", "loops=10"]),

                    ("xenserver.storage.TCMultipleVDI",
                     "VBD plug/unplug test of",
                     None,
                     "1. Create, attach and make filesystems on disk to "
                     "give the VM 4 attached disks\n"
                     "2. Create a new VBD.\n"
                     "3. Attach the VBD to the VM (hotplug)\n"
                     "4. From the VM create a filesystem on the new disk\n"
                     "5. Repeat steps 2 to 4 for a total of 7 VBDs\n"
                     "6. Unplug and destroy all but the primary disk\n"
                     "7. Repeat steps 2 to 4 up to 4 disks on the VM\n"
                     "8. Unplug and destroy all but the primary disk\n",
                     [False, "noshutdown", "initial=4", "max=7"]),

                    ("xenserver.network.TCNICTest",
                     "VIF plug/unplug test of",
                     "TCNICTestLive",
                     "1. Install a Linux VM to act as a network test target\n"
                     "2. Create a new VIF on a private bridge with the Linux VM\n"
                     "3. Hot plug the VIF to the VM\n"
                     "4. Verify connectivity between the VMs using the new VIF\n"
                     "5. Repeat steps 2 to 4 for a total of 7 VIFs\n"
                     "6. Unplug and destroy all but the primary VIF\n",
                     [False, "noshutdown"]),

                    ("guestops.cpu.TCCPUWalk",
                     "CPU adjustment test of",
                     None,
                     "1. Shut down the VM\n"
                     "2. Make the CPU count of the VM 2\n"
                     "3. Start the VM\n"
                     "4. If the VM is Windows and previously had 1 CPU, reboot\n"
                     "5. Verify the correct number of CPUs are reported inside the VM\n"
                     "6. Repeat steps 1 to 5 for CPU counts up to 8 and then 1\n",
                     ["max=%s" % MAX, "noplugwindows"])]:

        testcase, pref, name, tcdesc, extraargs = testdef
        skip = False
        if (testcase, distro) in [("guestops.cpu.TCCPUWalk", "w2kassp4")]:
            skip = True
        if testcase in ["guestops.srm.TCHibernate"] and not windows:
            skip = True
        if not skip:
            tcsummary = "%s %s" % (pref, desc)
            tcid = _findOrCreateTestCase(existing,
                                         tcsummary,
                                         j,
                                         container,
                                         tcdesc,
                                         component=comp)
            _createXMLFragment(j,
                               output,
                               guestname,
                               testcase,
                               tcid,
                               name=name,
                               extraargs=extraargs)

    output.append("        <finally>")
    output.append("          <testcase id=\"guestops.basic.TCShutdown\">")
    output.append("            <arg>guest=%s</arg>" % (guestname))
    output.append("            <arg>finally</arg>")
    output.append("          </testcase>")
    output.append("        </finally>")
    output.append("      </serial>")
    output.append("    </serial>")
 
    return string.join(output, "\n")

def generateOSTestSequences():
    """Define OS tests in Jira and create sequence files."""

    defineOSTests("w2k3eesp2pae", "Windows Server 2003 x86 Enterprise Edition SP2 with PAE Enabled")
    defineOSTests("w2k3ee", "Windows Server 2003 Enterprise Edition")
    defineOSTests("w2k3eesp1", "Windows Server 2003 Enterprise Edition SP1")
    defineOSTests("w2k3eesp2", "Windows Server 2003 Enterprise Edition SP2")
    defineOSTests("w2k3eesp2-x64", "Windows Server 2003 Enterprise Edition SP2 x64")
    defineOSTests("w2kassp4", "Windows 2000 Server SP4")
    defineOSTests("winxpsp2", "Windows XP SP2")
    defineOSTests("winxpsp3", "Windows XP SP3")
    defineOSTests("vistaee", "Windows Vista Enterprise Edition")
    defineOSTests("vistaee-x64", "Windows Vista Enterprise Edition x64")
    defineOSTests("vistaee", "Windows Vista Enterprise Edition (IPv6 only)")
    defineOSTests("vistaee-x64", "Windows Vista Enterprise Edition x64 (IPv6 only)")
    defineOSTests("vistaeesp1", "Windows Vista Enterprise Edition SP1")
    defineOSTests("vistaeesp1-x64", "Windows Vista Enterprise Edition SP1 x64")
    defineOSTests("vistaeesp1", "Windows Vista Enterprise Edition SP1 (IPv6 only)")
    defineOSTests("vistaeesp1-x64", "Windows Vista Enterprise Edition SP1 x64 (IPv6 only)")
    defineOSTests("vistaeesp2", "Windows Vista Enterprise Edition SP2")
    defineOSTests("vistaeesp2-x64", "Windows Vista Enterprise Edition SP2 x64")
    defineOSTests("vistaeesp2", "Windows Vista Enterprise Edition SP2 (IPv6 only)")
    defineOSTests("vistaeesp2-x64", "Windows Vista Enterprise Edition SP2 x64 (IPv6 only)")
    defineOSTests("ws08-x86", "Windows Server 2008 Enterprise Edition")
    defineOSTests("ws08-x64", "Windows Server 2008 Enterprise Edition x64")
    defineOSTests("ws08-x86", "Windows Server 2008 Enterprise Edition (IPv6 only)")
    defineOSTests("ws08-x64", "Windows Server 2008 Enterprise Edition x64 (IPv6 only)")
    defineOSTests("ws08sp2-x86", "Windows Server 2008 Enterprise Edition SP2")
    defineOSTests("ws08sp2-x64", "Windows Server 2008 Enterprise Edition SP2 x64")
    defineOSTests("ws08sp2-x86", "Windows Server 2008 Enterprise Edition SP2 (IPv6 only)")
    defineOSTests("ws08sp2-x64", "Windows Server 2008 Enterprise Edition SP2 x64 (IPv6 only)")
    defineOSTests("ws08r2-x64", "Windows Server 2008 R2 Enterprise Edition x64")
    defineOSTests("ws08r2sp1-x64", "Windows Server 2008 R2 SP1 Enterprise Edition x64")
    defineOSTests("ws08r2-x64", "Windows Server 2008 R2 Enterprise Edition x64 (IPv6 only)")
    defineOSTests("ws08r2sp1-x64", "Windows Server 2008 R2 SP1 Enterprise Edition x64 (IPv6 only)")
    defineOSTests("win7-x86", "Windows 7")
    defineOSTests("win7-x64", "Windows 7 x64")
    defineOSTests("win7-x86", "Windows 7 (IPv6 only)")
    defineOSTests("win7-x64", "Windows 7 x64 (IPv6 only)")
    defineOSTests("win7sp1-x86", "Windows 7 SP1")
    defineOSTests("win7sp1-x64", "Windows 7 SP1 x64")
    defineOSTests("win7sp1-x86", "Windows 7 SP1 (IPv6 only)")
    defineOSTests("win7sp1-x64", "Windows 7 SP1 x64 (IPv6 only)")
    defineOSTests("win8-x86", "Windows 8")
    defineOSTests("win8-x64", "Windows 8 x64")
    defineOSTests("win81-x86", "Windows 8.1")
    defineOSTests("win81-x64", "Windows 8.1 x64")
    defineOSTests("ws12-x64", "Windows Server 2012 x64")
    defineOSTests("ws12core-x64", "Windows Server 2012 Core x64")
    defineOSTests("ws12r2-x64", "Windows Server 2012 R2 x64")
    defineOSTests("ws12r2core-x64", "Windows Server 2012 R2 Core x64")
    defineOSTests("rhel41", "RedHat Enterprise Linux 4.1")
    defineOSTests("rhel44", "RedHat Enterprise Linux 4.4")
    defineOSTests("rhel45", "RedHat Enterprise Linux 4.5")
    defineOSTests("rhel46", "RedHat Enterprise Linux 4.6")
    defineOSTests("rhel47", "RedHat Enterprise Linux 4.7")
    defineOSTests("rhel48", "RedHat Enterprise Linux 4.8")
    defineOSTests("rhel5", "RedHat Enterprise Linux 5.0")
    defineOSTests("rhel5", "RedHat Enterprise Linux 5.0 x64", arch="x86-64")
    defineOSTests("rhel51", "RedHat Enterprise Linux 5.1")
    defineOSTests("rhel51", "RedHat Enterprise Linux 5.1 x64", arch="x86-64")
    defineOSTests("rhel52", "RedHat Enterprise Linux 5.2")
    defineOSTests("rhel52", "RedHat Enterprise Linux 5.2 x64", arch="x86-64")
    defineOSTests("rhel53", "RedHat Enterprise Linux 5.3")
    defineOSTests("rhel53", "RedHat Enterprise Linux 5.3 x64", arch="x86-64")
    defineOSTests("rhel54", "RedHat Enterprise Linux 5.4")
    defineOSTests("rhel54", "RedHat Enterprise Linux 5.4 x64", arch="x86-64")
    defineOSTests("rhel55", "RedHat Enterprise Linux 5.5")
    defineOSTests("rhel55", "RedHat Enterprise Linux 5.5 x64", arch="x86-64")
    defineOSTests("rhel56", "RedHat Enterprise Linux 5.6")
    defineOSTests("rhel56", "RedHat Enterprise Linux 5.6 x64", arch="x86-64")
    defineOSTests("rhel6", "RedHat Enterprise Linux 6.0")
    defineOSTests("rhel6", "RedHat Enterprise Linux 6.0 x64", arch="x86-64")
    defineOSTests("rhel6", "RedHat Enterprise Linux 6.0 (IPv6)")
    defineOSTests("rhel6", "RedHat Enterprise Linux 6.0 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("rhel61", "RedHat Enterprise Linux 6.1")
    defineOSTests("rhel61", "RedHat Enterprise Linux 6.1 x64", arch="x86-64")
    defineOSTests("rhel61", "RedHat Enterprise Linux 6.1 (IPv6)")
    defineOSTests("rhel61", "RedHat Enterprise Linux 6.1 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("rhel62", "RedHat Enterprise Linux 6.2")
    defineOSTests("rhel62", "RedHat Enterprise Linux 6.2 x64", arch="x86-64")
    defineOSTests("rhel62", "RedHat Enterprise Linux 6.2 (IPv6)")
    defineOSTests("rhel62", "RedHat Enterprise Linux 6.2 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("sles94", "SuSE Linux Enterprise Server 9 SP4")
    defineOSTests("sles101", "SuSE Linux Enterprise Server 10 SP1")
    defineOSTests("sles101", "SuSE Linux Enterprise Server 10 SP1 x64", arch="x86-64")
    defineOSTests("sles102", "SuSE Linux Enterprise Server 10 SP2")
    defineOSTests("sles102", "SuSE Linux Enterprise Server 10 SP2 x64", arch="x86-64")
    defineOSTests("sles103", "SuSE Linux Enterprise Server 10 SP3")
    defineOSTests("sles103", "SuSE Linux Enterprise Server 10 SP3 x64", arch="x86-64")
    defineOSTests("sles104", "SuSE Linux Enterprise Server 10 SP4")
    defineOSTests("sles104", "SuSE Linux Enterprise Server 10 SP4 x64", arch="x86-64")
    defineOSTests("sles11", "SuSE Linux Enterprise Server 11")
    defineOSTests("sles11", "SuSE Linux Enterprise Server 11 x64", arch="x86-64")
    defineOSTests("sles11", "SuSE Linux Enterprise Server 11 (IPv6)")
    defineOSTests("sles11", "SuSE Linux Enterprise Server 11 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("sles111", "SuSE Linux Enterprise Server 11 SP1")
    defineOSTests("sles111", "SuSE Linux Enterprise Server 11 SP1 x64", arch="x86-64")
    defineOSTests("sles111", "SuSE Linux Enterprise Server 11 SP1 (IPv6)")
    defineOSTests("sles111", "SuSE Linux Enterprise Server 11 SP1 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP1")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP1 x64", arch="x86-64")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP1 (IPv6)")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP1 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("sarge", "Debian Sarge")
    defineOSTests("etch", "Debian Etch")
    defineOSTests("debian50", "Debian Lenny 5.0")
    defineOSTests("debian60", "Debian Lenny 6.0")
    defineOSTests("debian60", "Debian Lenny 6.0 (IPv6)")
    defineOSTests("debian60", "Debian Lenny 6.0 x64 (IPv6)", arch="x86-64")
    defineOSTests("solaris10u9", "Solaris 10u9")
    defineOSTests("solaris10u9", "Solaris 10u9 x64", arch="x86-64")
    defineOSTests("ubuntu1004", "Ubuntu Lucid Lynx 10.04")
    defineOSTests("ubuntu1004", "Ubuntu Lucid Lynx 10.04 x64", arch="x86-64")
    defineOSTests("ubuntu1004", "Ubuntu Lucid Lynx 10.04 (IPv6)")
    defineOSTests("ubuntu1004", "Ubuntu Lucid Lynx 10.04 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("oel56", "Oracle Enterprise Linux 5.6")
    defineOSTests("oel56", "Oracle Enterprise Linux 5.6 x64", arch="x86-64")
    defineOSTests("centos56", "CentOS 5.6")
    defineOSTests("centos56", "CentOS 5.6 x64", arch="x86-64")
    defineOSTests("oel6", "Oracle Enterprise Linux 6.0")
    defineOSTests("oel6", "Oracle Enterprise Linux 6.0 x64", arch="x86-64")
    defineOSTests("oel6", "Oracle Enterprise Linux 6.0 (IPv6)")
    defineOSTests("oel6", "Oracle Enterprise Linux 6.0 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("centos6", "CentOS 6.0")
    defineOSTests("centos6", "CentOS 6.0 x64", arch="x86-64")
    defineOSTests("centos6", "CentOS 6.0 (IPv6)")
    defineOSTests("centos6", "CentOS 6.0 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("rhel57", "RedHat Enterprise Linux 5.7")
    defineOSTests("rhel57", "RedHat Enterprise Linux 5.7 x64", arch="x86-64")
    defineOSTests("centos57", "CentOS 5.7")
    defineOSTests("centos57", "CentOS 5.7 x64", arch="x86-64")
    defineOSTests("oel57", "Oracle Enterprise Linux 5.7")
    defineOSTests("oel57", "Oracle Enterprise Linux 5.7 x64", arch="x86-64")
    defineOSTests("centos61", "CentOS 6.1")
    defineOSTests("centos61", "CentOS 6.1 x64", arch="x86-64")
    defineOSTests("centos61", "CentOS 6.1 (IPv6)")
    defineOSTests("centos61", "CentOS 6.1 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("oel61", "Oracle Enterprise Linux 6.1")
    defineOSTests("oel61", "Oracle Enterprise Linux 6.1 x64", arch="x86-64")
    defineOSTests("oel61", "Oracle Enterprise Linux 6.1 (IPv6)")
    defineOSTests("oel61", "Oracle Enterprise Linux 6.1 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("centos62", "CentOS 6.2")
    defineOSTests("centos62", "CentOS 6.2 x64", arch="x86-64")
    defineOSTests("oel62", "Oracle Enterprise Linux 6.2")
    defineOSTests("oel62", "Oracle Enterprise Linux 6.2 x64", arch="x86-64")
    defineOSTests("ubuntu1204", "Ubuntu Precise Pangolin 12.04")
    defineOSTests("ubuntu1204", "Ubuntu Precise Pangolin 12.04 x64", arch="x86-64")
    defineOSTests("ubuntu1204", "Ubuntu Precise Pangolin 12.04 (IPv6)")
    defineOSTests("ubuntu1204", "Ubuntu Precise Pangolin 12.04 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP2")
    defineOSTests("sles112", "SuSE Linux Enterprise Server 11 SP2 x64", arch="x86-64")
    defineOSTests("rhel58", "RedHat Enterprise Linux 5.8")
    defineOSTests("rhel58", "RedHat Enterprise Linux 5.8 x64", arch="x86-64")
    defineOSTests("rhel59", "RedHat Enterprise Linux 5.9")
    defineOSTests("rhel59", "RedHat Enterprise Linux 5.9 x64", arch="x86-64")
    defineOSTests("rhel63", "RedHat Enterprise Linux 6.3")
    defineOSTests("rhel63", "RedHat Enterprise Linux 6.3 x64", arch="x86-64")
    defineOSTests("rhel64", "RedHat Enterprise Linux 6.4")
    defineOSTests("rhel64", "RedHat Enterprise Linux 6.4 x64", arch="x86-64")
    defineOSTests("oel58", "Oracle Enterprise Linux 5.8")
    defineOSTests("oel58", "Oracle Enterprise Linux 5.8 x64", arch="x86-64")
    defineOSTests("oel59", "Oracle Enterprise Linux 5.9")
    defineOSTests("oel59", "Oracle Enterprise Linux 5.9 x64", arch="x86-64")
    defineOSTests("oel63", "Oracle Enterprise Linux 6.3")
    defineOSTests("oel63", "Oracle Enterprise Linux 6.3 x64", arch="x86-64")
    defineOSTests("oel64", "Oracle Enterprise Linux 6.4")
    defineOSTests("oel64", "Oracle Enterprise Linux 6.4 x64", arch="x86-64")
    defineOSTests("centos58", "CentOS 5.8")
    defineOSTests("centos58", "CentOS 5.8 x64", arch="x86-64")
    defineOSTests("centos59", "CentOS 5.9")
    defineOSTests("centos59", "CentOS 5.9 x64", arch="x86-64")
    defineOSTests("centos63", "CentOS 6.3")
    defineOSTests("centos63", "CentOS 6.3 x64", arch="x86-64")
    defineOSTests("centos64", "CentOS 6.4")
    defineOSTests("centos64", "CentOS 6.4 x64", arch="x86-64")
    defineOSTests("ubuntu1404", "Ubuntu Trusty Tahr 14.04")
    defineOSTests("ubuntu1404", "Ubuntu Trusty Tahr 14.04 x64", arch="x86-64")
    defineOSTests("ubuntu1404", "Ubuntu Trusty Tahr 14.04 (IPv6)")
    defineOSTests("ubuntu1404", "Ubuntu Trusty Tahr 14.04 x64 (IPv6 only)", arch="x86-64")
    defineOSTests("centos65", "CentOS 6.5")
    defineOSTests("centos65", "CentOS 6.5 x64", arch="x86-64")
    defineOSTests("oel65", "Oracle Enterprise Linux 6.5")
    defineOSTests("oel65", "Oracle Enterprise Linux 6.5 x64", arch="x86-64")
    defineOSTests("rhel65", "RedHat Enterprise Linux 6.5")
    defineOSTests("rhel65", "RedHat Enterprise Linux 6.5 x64", arch="x86-64")
    defineOSTests("rhel510", "RedHat Enterprise Linux 5.10")
    defineOSTests("rhel510", "RedHat Enterprise Linux 5.10 x64", arch="x86-64")
    defineOSTests("oel510", "Oracle Enterprise Linux 5.10")
    defineOSTests("oel510", "Oracle Enterprise Linux 5.10 x64", arch="x86-64")
    defineOSTests("centos510", "CentOS 5.10")
    defineOSTests("centos510", "CentOS 5.10 x64", arch="x86-64")
    defineOSTests("centos66", "CentOS 6.5")
    defineOSTests("centos66", "CentOS 6.5 x64", arch="x86-64")
    defineOSTests("oel66", "Oracle Enterprise Linux 6.6")
    defineOSTests("oel66", "Oracle Enterprise Linux 6.6 x64", arch="x86-64")
    defineOSTests("rhel66", "RedHat Enterprise Linux 6.6")
    defineOSTests("rhel66", "RedHat Enterprise Linux 6.6 x64", arch="x86-64")
    defineOSTests("rhel511", "RedHat Enterprise Linux 5.11")
    defineOSTests("rhel511", "RedHat Enterprise Linux 5.11 x64", arch="x86-64")
    defineOSTests("oel511", "Oracle Enterprise Linux 5.11")
    defineOSTests("oel511", "Oracle Enterprise Linux 5.11 x64", arch="x86-64")
    defineOSTests("centos511", "CentOS 5.11")
    defineOSTests("centos511", "CentOS 5.11 x64", arch="x86-64")

def getChildren(key):
    global childrencache
    if not childrencache.has_key(key):
        childrencache[key] = testrunJSONLoad("issuetree/%s" % key, "depth=1")[0]['children']
    return childrencache[key]

def flushChildrenCache(key):
    global childrencache
    if childrencache.has_key(key):
        del childrencache[key]

def defineMatrixTest(oses, memory, vcpus, platform, tcArtifacts=None, versionconfig=None, extraDesc = ""):

    pyfile = []
    tcs = []
    defaultmaxmem = "32768"
    defaultmaxvcpus = "8"
    maxmem = defaultmaxmem
    maxmemlin32 = defaultmaxmem
    maxvcpus = defaultmaxvcpus
    if versionconfig:
        if versionconfig.has_key("MAX_VM_MEMORY"):
            maxmem = versionconfig["MAX_VM_MEMORY"]
            maxmemlin32 = versionconfig["MAX_VM_MEMORY"]
        if versionconfig.has_key("MAX_VM_MEMORY_LINUX32BIT"):
            maxmemlin32 = versionconfig["MAX_VM_MEMORY_LINUX32BIT"]
        if versionconfig.has_key("MAX_VM_VCPUS"):
            maxvcpus = versionconfig["MAX_VM_VCPUS"]
    # Open a link to Jira
    j = J()

    # Describe this config
    pmap = {"VMX": "Intel VT", "SVM": "AMD-V", "SVMHAP": "AMD-V+NPT", "VMXEPT" : "VT+EPT"}
    if memory == None and vcpus == None:
        desctail = "using template defaults"
        desc = "OS operation using template default configuration%s" % extraDesc
    else:
        if memory == "Max":
            mdesc = "maximum memory"
            if maxmem != defaultmaxmem or maxmemlin32 != defaultmaxmem:
                mdesc += " (XenServer guest limit %uG/%uG)" % (int(maxmem)/1024, int(maxmemlin32)/1024)
        else:
            mdesc = memory
        if vcpus == 99:
            cdesc = "maximum vCPUs"
            if maxvcpus != defaultmaxvcpus:
                cdesc += " (XenServer guest limit %s)" % maxvcpus
        elif vcpus == 1:
            cdesc = "1 vCPU"
        else:
            cdesc = "%u vCPUs" % (vcpus)
        desc = "OS operation of %s %s%s VMs" % (mdesc, cdesc, extraDesc)
        desctail = "%s %s" % (mdesc, cdesc)
    if platform:
        desc = desc + " on " + pmap[platform]
        desctail = desctail + " on " + pmap[platform]

    print "defineMatrixTest for %s" % desc

    keys = [x['key'] for x in getChildren("TC-6865") if x['title'] == desc]
    if len(keys) > 0:
        container = getIssue(j, keys[0])
    else:
        print "Creating new container for %s" % desc
        container = j.jira.create_issue(project={"key":"TC"}, summary=desc, issuetype={"name":"Hierarchy"})
        j.jira.create_issue_link(type="Contains", inwardIssue="TC-6865", outwardIssue=container.key)
        flushChildrenCache("TC-6865")
    print "Using %s as container for %s" % (container.key, desc)
    
    # Get a list of existing tickets for this config
    existing = {}

    contained = getChildren(container.key)

    for c in contained:
        existing[c['title']] = c['key']
    
    # Iterate of the OSes
    for os in oses:
        distro = os[0]
        tcsummary = "Operation of " + os[1] + " " + desctail
        if len(os) > 2:
            arch = os[2]
        else:
            arch = None
        lin32 = False
        win32 = False
        if distro[0] in ('w', 'v'):
            if not re.search("x64", os[0]):
                win32 = True
        else:
            if not re.search("64 bit", os[1]):
                lin32 = True
        tcid = _findOrCreateTestCase(existing,
                                     tcsummary,
                                     j,
                                     container,
                                     "")
        tcs.append(tcid)
        t = getIssue(j, tcid)
        if not tcArtifacts is None:
            pyfile = []
        pyfile.append("# Autogenerated class - do not edit")
        pyfile.append("class %s(_TCSmoketest):" %
                      (string.replace(t.key, "-", "")))
        pyfile.append("    \"\"\"%s\"\"\"" % (tcsummary))
        pyfile.append("    DISTRO = \"%s\"" % (distro))
        if memory:
            if memory == "Max":
                m = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                        distro,
                                        "MAXMEMORY"], maxmem))
                if (not lin32) and (not win32):
                    m = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                            distro,
                                            "MAXMEMORY64"], m))
                if lin32 and m > int(maxmemlin32):
                    m = int(maxmemlin32)
                if (not lin32) and m > int(maxmem):
                    m = int(maxmem)
                pyfile.append("    MIGRATETEST = False")
            else:
                m = int(string.replace(memory, "GB", "")) * 1024
            pyfile.append("    MEMORY = %u" % (m))
            if distro == "winxpsp3" and m >= 4096: # Workaround the xp3 template root disk being too small to support 4GB memory
                pyfile.append("    ROOTDISK = 16384") 
        if vcpus:
            if vcpus == 99:
                c = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                            distro,
                                            "MAXSOCKETS"], maxvcpus))
                maxvcpus = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                                    distro,
                                                    "MAX_VM_VCPUS"], maxvcpus ))
                if (not lin32) and (not win32):
                    maxvcpus = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS",
                                                    distro,
                                                    "MAX_VM_VCPUS64"], maxvcpus ))
                if c > int(maxvcpus):
                    c = int(maxvcpus)
            else:
                c = vcpus
            pyfile.append("    VCPUS = %u" % (c))
        if platform:
            pyfile.append("    VARCH = \"%s\"" % (platform))
        if arch:
            pyfile.append("    ARCH = \"%s\"" % (arch))
        if distro == "w2kassp4":
            pyfile.append("    HIBERNATE = False")
        if distro.startswith("solaris"): # necessary until solaris has agent/tools
            pyfile.append("    def lifecycle(self): pass") 
            pyfile.append("    def suspendresume(self): pass") 
            pyfile.append("    def migrate(self, live): pass") 
            pyfile.append("    def hibernate(self): pass") 
        pyfile.append("")
        if not tcArtifacts is None:
            tcArtifacts[tcid] = pyfile
        
    if not tcArtifacts is None:
        return tcs
    else:
        return pyfile

def processMatrixTests(release=None):
    """Auto-create appropriate process tests and update suites where specified"""

    if not os.getcwd().endswith("exec"):
        raise xenrt.XRTError("You need to be in the exec dir. cwd=" + os.getcwd())
    
    
    # All known Windows distros
    winDistros = xenrt.enum.windowsdistros
    # All known linux distros that only have 32-bit versions
    linDistros_32only = [('rhel41','RHEL 4.1'),
                         ('rhel44','RHEL 4.4'),
                         ('rhel45','RHEL 4.5'),
                         ('rhel46','RHEL 4.6'),
                         ('rhel47','RHEL 4.7'),
                         ('rhel48','RHEL 4.8'),
                         ('centos45','CentOS 4.5'),
                         ('centos46','CentOS 4.6'),
                         ('centos47','CentOS 4.7'),
                         ('centos48','CentOS 4.8'),
                         ('sles94','SLES9 SP4'),
                         ('sarge','Debian Sarge'),
                         ('etch','Debian Etch'),
                         ('debian50','Debian Lenny 5.0')]

    # All known linux distros that only have 64-bit versions
    linDistros_64only = [('rhel7','RHEL 7.0'),
                         ('rhel71','RHEL 7.1'),
                         ('centos7','CentOS 7.0'),
                         ('oel7','OEL 7.0'),
                         ('sles12','SLES12')]

    # All known linux distros that have both 32 and 64-bit versions
    linDistros = [('rhel5','RHEL 5.0'),
                  ('rhel51','RHEL 5.1'),
                  ('rhel52','RHEL 5.2'),
                  ('rhel53','RHEL 5.3'),
                  ('rhel54','RHEL 5.4'),
                  ('rhel55','RHEL 5.5'),
                  ('rhel56','RHEL 5.6'),
                  ('rhel57','RHEL 5.7'),
                  ('rhel58','RHEL 5.8'),
                  ('rhel59','RHEL 5.9'),
                  ('rhel510','RHEL 5.10'),
                  ('rhel511','RHEL 5.11'),
                  ('rhel6','RHEL 6.0'),
                  ('rhel61','RHEL 6.1'),
                  ('rhel62','RHEL 6.2'),
                  ('rhel63','RHEL 6.3'),
                  ('rhel64','RHEL 6.4'),
                  ('rhel65','RHEL 6.5'),
                  ('rhel66','RHEL 6.6'),
                  ('centos5','CentOS 5.0'),
                  ('centos51','CentOS 5.1'),
                  ('centos52','CentOS 5.2'),
                  ('centos53','CentOS 5.3'),
                  ('centos54','CentOS 5.4'),
                  ('centos55','CentOS 5.5'),
                  ('centos56','CentOS 5.6'),
                  ('centos57','CentOS 5.7'),
                  ('centos58','CentOS 5.8'),
                  ('centos59','CentOS 5.9'),
                  ('centos510','CentOS 5.10'),
                  ('centos511','CentOS 5.11'),
                  ('centos6','CentOS 6.0'),
                  ('centos61','CentOS 6.1'),
                  ('centos62','CentOS 6.2'),
                  ('centos63','CentOS 6.3'),
                  ('centos64','CentOS 6.4'),
                  ('centos65','CentOS 6.5'),
                  ('centos66','CentOS 6.6'),
                  ('oel53','Oracle Enterprise Linux 5.3'),
                  ('oel54','Oracle Enterprise Linux 5.4'),
                  ('oel55','Oracle Enterprise Linux 5.5'),
                  ('oel56','Oracle Enterprise Linux 5.6'),
                  ('oel57','Oracle Enterprise Linux 5.7'),
                  ('oel58','Oracle Enterprise Linux 5.8'),
                  ('oel59','Oracle Enterprise Linux 5.9'),
                  ('oel510','Oracle Enterprise Linux 5.10'),
                  ('oel511','Oracle Enterprise Linux 5.11'),
                  ('oel6','Oracle Enterprise Linux 6.0'),
                  ('oel61','Oracle Enterprise Linux 6.1'),
                  ('oel62','Oracle Enterprise Linux 6.2'),
                  ('oel63','Oracle Enterprise Linux 6.3'),
                  ('oel64','Oracle Enterprise Linux 6.4'),
                  ('oel65','Oracle Enterprise Linux 6.5'),
                  ('oel66','Oracle Enterprise Linux 6.6'),
                  ('sles101','SLES10 SP1'),
                  ('sles102','SLES10 SP2'),
                  ('sles103','SLES10 SP3'),
                  ('sles104','SLES10 SP4'),
                  ('sles11','SLES11'),
                  ('sles111','SLES11 SP1'),
                  ('sles112','SLES11 SP2'),
                  ('sles113','SLES11 SP3'),
                  ('ubuntu1004','Ubuntu 10.04'),
                  ('ubuntu1204','Ubuntu 12.04'),
                  ('ubuntu1404','Ubuntu 14.04'),
                  ('debian60','Debian 6.0'),
                  ('debian70','Debian 7.0'),
                  ('solaris10u9','Solaris 10u9')]

    # List of releases to manage
    releases = ['Backport','George','GeorgeU1','MNR','Cowley','Boston','Sanibel','Tampa','Clearwater','Creedence','Dundee']

    releaseVersionConfig = {}
    releaseVersionConfig['Backport'] = "Orlando"
    releaseVersionConfig['GeorgeU1'] = "George"
    releaseVersionConfig['Cowley'] = "MNR"
    releaseVersionConfig['Sanibel'] = "Boston"

    releasesWithoutSeperateMaxMemTests = ['Backport','George','GeorgeU1','MNR','Cowley']

    # Mapping of suites to releases in the form Release:(Nightly,Regression, Experimental)
    suiteMappings = {'Creedence':('TC-21159', 'TC-21163', 'TC-21190'), 'Dundee':('TC-23497', 'TC-23495', None)}

    # Mapping of distros to Primary/Secondary/Tertiary for each release
    
    # primary: An operating system version that will undergo significant testing
    # secondary: An operating system version that will undergo a limited amount of testing, perhaps in limited scenarios
    # tertiary: An operating system version that will only receive smoke testing (usually defined to be VM installation and basic lifecycle operations)

    distrosToRels = {}
    # Backport of old tests
    distrosToRels['Backport'] = {}
    distrosToRels['Backport']['primary'] = ['w2k3ee','w2k3eesp1','w2k3eesp2',
                                            'w2k3eesp2-x64','w2kassp4','winxpsp2',
                                            'winxpsp3','vistaeesp1','vistaeesp1-x64',
                                            'vistaeesp2','vistaeesp2-x64','ws08-x86',
                                            'ws08-x64','ws08sp2-x86','ws08sp2-x64',
                                            'ws08r2-x64','win7-x86','win7-x64',
                                            'rhel44','rhel46','rhel47','rhel48',
                                            'rhel51','rhel52','rhel53','rhel54',
                                            'sles94','sles101','sles102','sles103',
                                            'sles11','etch','debian50']
    distrosToRels['Backport']['secondary'] = ['rhel41','rhel45','rhel5','oel54',
                                              'sarge']
    distrosToRels['Backport']['tertiary'] = ['w2k3eer2','w2k3se','w2k3sesp1',
                                             'w2k3ser2','w2k3sesp2','vistaee',
                                             'vistaee-x64','oel53','centos45',
                                             'centos46','centos47','centos48',
                                             'centos5','centos51','centos52',
                                             'centos53','centos54']
    distrosToRels['Backport']['level0'] = ['w2k3eesp2','etch']
    distrosToRels['Backport']['experimental'] = []

    # George (5.5)
    distrosToRels['George'] = {}
    distrosToRels['George']['primary'] = ['rhel48','rhel53','sles94',
                                          'sles102','sles11','etch','debian50',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp1',
                                          'vistaeesp1-x64','ws08-x86',
                                          'ws08-x64','w2kassp4']
    distrosToRels['George']['secondary'] = ['rhel47','rhel53','sles102',
                                            'w2k3eesp1','winxpsp2',
                                            'vistaee','vistaee-x64']
    distrosToRels['George']['tertiary'] = ['rhel46','rhel45','rhel52',
                                           'rhel51','rhel5','sles101',
                                           'centos48','centos47','centos46',
                                           'centos45','centos54','centos53',
                                           'centos52','centos51','centos5',
                                           'w2k3ee','w2k3sesp2','w2k3sesp1',
                                           'w2k3se','w2k3eer2','w2k3ser2']
    distrosToRels['George']['level0'] = []
    distrosToRels['George']['experimental'] = []
    #  Update 1
    distrosToRels['GeorgeU1'] = {}
    distrosToRels['GeorgeU1']['primary'] = ['rhel48','rhel53','sles94',
                                            'sles102','sles11','etch','debian50',
                                            'w2k3eesp2','w2k3eesp2-x64',
                                            'winxpsp3','vistaeesp1',
                                            'vistaeesp1-x64','ws08-x86',
                                            'ws08-x64','ws08r2-x64',
                                            'win7-x86','win7-x64','w2kassp4']
    distrosToRels['GeorgeU1']['secondary'] = ['rhel47','rhel53','sles102',
                                              'w2k3eesp1','winxpsp2',
                                              'vistaee','vistaee-x64']
    distrosToRels['GeorgeU1']['tertiary'] = ['rhel46','rhel45','rhel52',
                                             'rhel51','rhel5','sles101',
                                             'centos48','centos47','centos46',
                                             'centos45','centos54','centos53',
                                             'centos52','centos51','centos5',
                                             'w2k3ee','w2k3sesp2','w2k3sesp1',
                                             'w2k3se','w2k3eer2','w2k3ser2']
    distrosToRels['GeorgeU1']['level0'] = []
    distrosToRels['GeorgeU1']['experimental'] = []

    # MNR (5.6)
    distrosToRels['MNR'] = {}
    distrosToRels['MNR']['primary'] = ['rhel48','rhel54','sles94',
                                       'sles103','sles11','debian50',
                                       'w2k3eesp2','w2k3eesp2-x64',
                                       'winxpsp3','vistaeesp2',
                                       'vistaeesp2-x64','ws08sp2-x86',
                                       'ws08sp2-x64','ws08r2-x64',
                                       'win7-x86','win7-x64','w2kassp4']
    distrosToRels['MNR']['secondary'] = ['rhel47','rhel53','sles102',
                                         'w2k3eesp1','winxpsp2',
                                         'vistaeesp1','vistaeesp1-x64',
                                         'ws08-x86','ws08-x64']
    distrosToRels['MNR']['tertiary'] = ['rhel46','rhel45','rhel52',
                                        'rhel51','rhel5','sles101',
                                        'centos48','centos47','centos46',
                                        'centos45','centos54','centos53',
                                        'centos52','centos51','centos5',
                                        'oel54','oel53',
                                        'w2k3ee','w2k3sesp2','w2k3sesp1',
                                        'w2k3se','w2k3eer2','w2k3ser2',
                                        'vistaee','vistaee-x64']
    distrosToRels['MNR']['level0'] = []
    distrosToRels['MNR']['experimental'] = []
    #  Update 1 (Cowley)
    distrosToRels['Cowley'] = {}
    distrosToRels['Cowley']['primary'] = ['rhel6','rhel48','rhel55','sles94',
                                          'sles103','sles111','debian50',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'vistaeesp2-x64','ws08sp2-x86',
                                          'ws08sp2-x64','ws08r2sp1-x64',
                                          'win7sp1-x86','win7sp1-x64']
    distrosToRels['Cowley']['secondary'] = ['rhel47','rhel54','sles11','sles102',
                                            'w2k3eesp1',
                                            'vistaeesp1','vistaeesp1-x64',
                                            'ws08-x86','ws08-x64', 'ws08r2-x64'
                                            'win7-x86','win7-x64']
    distrosToRels['Cowley']['tertiary'] = ['rhel46','rhel45','rhel53','rhel52',
                                           'rhel51','rhel5','sles101',
                                           'centos48','centos47','centos46',
                                           'centos45','centos55','centos54','centos53',
                                           'centos52','centos51','centos5',
                                           'oel55','oel54','oel53',
                                           'w2k3ee','w2k3sesp2','w2k3sesp1',
                                           'w2k3se','w2k3eer2','w2k3ser2',
                                           'vistaee','vistaee-x64']
    distrosToRels['Cowley']['level0'] = ['w2k3eesp2']
    distrosToRels['Cowley']['experimental'] = []
    
    #  (Boston)
    distrosToRels['Boston'] = {}
    distrosToRels['Boston']['primary'] = ['rhel48','rhel56','rhel6','sles94',
                                          'sles104','sles111','debian50',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'vistaeesp2-x64','ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'solaris10u9','ubuntu1004', 'debian60',
                                          'oel56','centos56','oel6']
    distrosToRels['Boston']['secondary'] = ['rhel47','rhel55','sles11','sles103',
                                            'w2k3eesp1',
                                            'vistaeesp1','vistaeesp1-x64',
                                            'ws08-x86','ws08-x64', 'ws08r2-x64'
                                            'win7-x86','win7-x64']
    distrosToRels['Boston']['tertiary'] = ['rhel46','rhel45','rhel54','rhel53','rhel52',
                                           'rhel51','rhel5','sles102',
                                           'centos48','centos47','centos46',
                                           'centos45','centos55','centos54','centos53',
                                           'centos52','centos51','centos5',
                                           'oel55','oel54','oel53',
                                           'w2k3ee','w2k3sesp2','w2k3sesp1',
                                           'w2k3se','w2k3eer2','w2k3ser2',
                                           'vistaee','vistaee-x64']
    distrosToRels['Boston']['level0'] = ['w2k3eesp2']
    distrosToRels['Boston']['experimental'] = []

    #  (Sanibel)
    distrosToRels['Sanibel'] = {}
    distrosToRels['Sanibel']['primary'] = ['rhel48','rhel56','rhel6',
                                          'sles104','sles111','debian50',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'vistaeesp2-x64','ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'solaris10u9','ubuntu1004', 'debian60','oel510',
                                          'centos56','oel65',
                                          'centos57','rhel57','centos65',
                                          'w2k3eesp2pae']
    distrosToRels['Sanibel']['secondary'] = ['rhel47','rhel55','sles11','sles103','centos64',
                                            'w2k3eesp1',
                                            'vistaeesp1','vistaeesp1-x64',
                                            'ws08-x86','ws08-x64', 'ws08r2-x64'
                                            'win7-x86','win7-x64']
    distrosToRels['Sanibel']['tertiary'] = ['rhel46','rhel45','rhel54','rhel53','rhel52',
                                           'rhel51','rhel5','sles102',
                                           'oel57','oel56',
                                           'centos48','centos47','centos46',
                                           'centos45','centos55','centos54','centos53',
                                           'centos52','centos51','centos5','centos63',
                                           'oel55','oel54','oel53',
                                           'w2k3sesp2','w2k3sesp1',
                                           'w2k3eer2','w2k3ser2',
                                           'vistaee','vistaee-x64']
    distrosToRels['Sanibel']['level0'] = ['w2k3eesp2']
    distrosToRels['Sanibel']['experimental'] = []
    
    #  (Tampa)
    distrosToRels['Tampa'] = {}
    distrosToRels['Tampa']['primary'] = ['rhel48','rhel57','rhel61',
                                          'sles104','sles111',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'solaris10u9','ubuntu1004', 'debian60','oel510',
                                          'centos57','oel65','centos61',
                                          'rhel62', 'centos62', 'ubuntu1204']
    distrosToRels['Tampa']['secondary'] = ['rhel47','rhel56','sles11','sles103',
                                            'ws08r2-x64',
                                            'win7-x86','win7-x64','rhel6','oel62', 'centos6']
    distrosToRels['Tampa']['tertiary'] = ['rhel46','rhel45','rhel55','rhel54','rhel53','rhel52',
                                           'rhel51','rhel5','sles102',
                                           'centos48','centos47','centos46',
                                           'centos45','centos56' 'centos55','centos54','centos53',
                                           'centos52','centos51','centos5',
                                           'oel57','oel56','oel55','oel54','oel53','oel61',
                                           'w2k3sesp2',
                                           'w2k3eer2','w2k3ser2']
    distrosToRels['Tampa']['level0'] = ['w2k3eesp2']
    distrosToRels['Tampa']['experimental'] = []

    #  (Clearwater)
    distrosToRels['Clearwater'] = {}
    distrosToRels['Clearwater']['primary'] = ['rhel48','rhel57','rhel61',
                                          'sles104','sles111',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'ubuntu1004', 'debian60',
                                          'centos57','centos61','oel510',
                                          'rhel62', 'centos62', 'oel65', 'ubuntu1204',
                                          'win8-x86','win8-x64', 'ws12-x64','ws12core-x64', 
                                          'win81-x86','win81-x64', 'ws12r2-x64','ws12r2core-x64']
    distrosToRels['Clearwater']['secondary'] = ['rhel47','rhel56','sles11','sles103',
                                            'ws08r2-x64',
                                            'win7-x86','win7-x64','rhel6','oel62', 'centos6']
    distrosToRels['Clearwater']['tertiary'] = ['rhel46','rhel45','rhel55','rhel54','rhel53','rhel52',
                                           'rhel51','sles102',
                                           'centos48','centos47','centos46',
                                           'centos45','centos56' 'centos55','centos54','centos53',
                                           'centos52','centos51',
                                           'oel57','oel56','oel55','oel54','oel53','oel61',
                                           'w2k3sesp2',
                                           'w2k3eer2','w2k3ser2']
    distrosToRels['Clearwater']['level0'] = ['w2k3eesp2']
    distrosToRels['Clearwater']['experimental'] = ['rhel58', 'rhel59', 'rhel63', 'rhel64', 'oel58', 'oel59', 'oel63', 'oel64',
                                                'centos58', 'centos59', 'centos63', 'centos64', 'sles112', 'debian70']


    #  (Creedence)
    distrosToRels['Creedence'] = {}
    distrosToRels['Creedence']['primary'] = ['rhel48','rhel510','rhel65','rhel511','rhel66','rhel7','rhel71','oel7','centos7',
                                          'sles104','sles113','sles12',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'ubuntu1004', 'debian60','debian70',
                                          'oel510','centos510','oel511','oel65','oel66','centos66','centos511','centos65','ubuntu1404',
                                          'ubuntu1204','win8-x86','win8-x64','win10-x86','win10-x64', 'ws12-x64','ws12core-x64', 
                                          'win81-x86','win81-x64', 'ws12r2-x64','ws12r2core-x64']
    distrosToRels['Creedence']['secondary'] = ['rhel47','rhel59','sles103',
                                            'ws08r2-x64'
                                            'win7-x86','win7-x64','rhel64','oel64', 'centos64']
    distrosToRels['Creedence']['tertiary'] = ['rhel46','rhel45',
                                              'rhel58','rhel57','rhel56','rhel55','rhel54','rhel53','rhel52','rhel51',
                                              'rhel63',
                                              'sles102',
                                              'sles11','sles111','sles112',
                                              'centos48','centos47','centos46','centos45',
                                              'centos59','centos58','centos57','centos56' 'centos55','centos54','centos53','centos52','centos51',
                                              'oel59','oel58','oel57','oel56','oel55','oel54','oel53',
                                              'oel63','centos63',
                                              'w2k3sesp2',
                                              'w2k3eer2','w2k3ser2']
    distrosToRels['Creedence']['level0'] = ['w2k3eesp2']
    distrosToRels['Creedence']['experimental'] = []


    #  (Dundee)
    distrosToRels['Dundee'] = {}
    distrosToRels['Dundee']['primary'] = ['rhel48','rhel510','rhel65','rhel511','rhel66','rhel7','rhel71','oel7','centos7',
                                          'sles104','sles113','sles12',
                                          'w2k3eesp2','w2k3eesp2-x64',
                                          'winxpsp3','vistaeesp2',
                                          'ws08dcsp2-x86',
                                          'ws08dcsp2-x64','ws08r2dcsp1-x64',
                                          'win7sp1-x86','win7sp1-x64',
                                          'ubuntu1004', 'debian60','debian70',
                                          'oel510','centos510','oel511','oel65','oel66','centos66','centos511','centos65','ubuntu1404',
                                          'ubuntu1204','win8-x86','win8-x64','win10-x86','win10-x64', 'ws12-x64','ws12core-x64', 
                                          'win81-x86','win81-x64', 'ws12r2-x64','ws12r2core-x64']
    distrosToRels['Dundee']['secondary'] = ['rhel47','rhel59','sles103',
                                            'ws08r2-x64'
                                            'win7-x86','win7-x64','rhel64','oel64', 'centos64']
    distrosToRels['Dundee']['tertiary'] = ['rhel46','rhel45',
                                              'rhel58','rhel57','rhel56','rhel55','rhel54','rhel53','rhel52','rhel51',
                                              'rhel63',
                                              'sles102',
                                              'sles11','sles111','sles112',
                                              'centos48','centos47','centos46','centos45',
                                              'centos59','centos58','centos57','centos56' 'centos55','centos54','centos53','centos52','centos51',
                                              'oel59','oel58','oel57','oel56','oel55','oel54','oel53',
                                              'oel63','centos63',
                                              'w2k3sesp2',
                                              'w2k3eer2','w2k3ser2']
    distrosToRels['Dundee']['level0'] = ['w2k3eesp2']
    distrosToRels['Dundee']['experimental'] = []




    # Do not edit below this line...

    # Use this dictionary to contain TC artifacts to write out
    tcArtifacts = {}

    suiteUpdates = {}

    config = xenrt.Config()

    # For each distro, we need to define appropriate matrix tests, and log
    # which TCs need to be added to each suite.
    if release:
        releases = [ release ]
    for r in releases:
        versionconfig = None
        if releaseVersionConfig.has_key(r):
            versionconfig = config.config["VERSION_CONFIG"][releaseVersionConfig[r]]
        else:
            versionconfig = config.config["VERSION_CONFIG"][r]
        if suiteMappings.has_key(r):
            nightly = suiteMappings[r][0]
            regression = suiteMappings[r][1]
            experimentalsuite = suiteMappings[r][2]
        else:
            nightly = None
            regression = None
            experimentalsuite = None

        level0 = []
        primaryw = []
        primaryl = []
        primaryl32 = []
        primaryl64 = []
        secondary = []
        tertiary = []
        experimentalnl32 = []
        experimentall32 = []
        for d in winDistros:
            if d[0] in distrosToRels[r]['primary']:
                # Primary
                primaryw.append(d)
            if d[0] in distrosToRels[r]['secondary']:
                # Secondary
                secondary.append(d)
            if d[0] in distrosToRels[r]['tertiary']:
                # Tertiary
                tertiary.append(d)
            if d[0] in distrosToRels[r]['level0']:
                level0.append(d)
            if d[0] in distrosToRels[r]['experimental']:
                experimentalnl32.append(d)
        for d in linDistros_32only:
            if d[0] in distrosToRels[r]['primary']:
                # Primary
                primaryl32.append(d)
            if d[0] in distrosToRels[r]['secondary']:
                # Secondary
                secondary.append(d)
            if d[0] in distrosToRels[r]['tertiary']:
                # Tertiary
                tertiary.append(d)
            if d[0] in distrosToRels[r]['level0']:
                level0.append(d)
            if d[0] in distrosToRels[r]['experimental']:
                experimentall32.append(d)

        for d in linDistros_64only:
            if d[0] in distrosToRels[r]['primary']:
                # Primary
                primaryl64.append((d[0],"%s 64 bit" % d[1],"x86-64"))
            if d[0] in distrosToRels[r]['secondary']:
                # Secondary
                secondary.append(d)
            if d[0] in distrosToRels[r]['tertiary']:
                # Tertiary
                tertiary.append(d)
            if d[0] in distrosToRels[r]['level0']:
                level0.append(d)
            if d[0] in distrosToRels[r]['experimental']:
                experimentalnl32.append((d[0],"%s 64 bit" % d[1],"x86-64"))

        for d in linDistros:
            if d[0] in distrosToRels[r]['primary']:
                # Primary
                if d[0].startswith("sles"):
                    primaryl32.append(d)
                else:
                    primaryl32.append((d[0],"%s 32 bit" % d[1]))
                primaryl64.append((d[0],"%s 64 bit" % d[1],"x86-64"))
            if d[0] in distrosToRels[r]['secondary']:
                # Secondary
                if d[0].startswith("sles"):
                    secondary.append(d)
                else:
                    secondary.append((d[0],"%s 32 bit" % d[1]))
                secondary.append((d[0],"%s 64 bit" % d[1],"x86-64"))
            if d[0] in distrosToRels[r]['tertiary']:
                # Tertiary
                if d[0].startswith("sles"):
                    tertiary.append(d)
                else:
                    tertiary.append((d[0],"%s 32 bit" % d[1]))
                tertiary.append((d[0],"%s 64 bit" % d[1],"x86-64"))
            if d[0] in distrosToRels[r]['level0']:
                if d[0].startswith("sles"):
                    level0.append(d)
                else:
                    level0.append((d[0],"%s 32 bit" % d[1]))
                level0.append((d[0],"%s 64 bit" % d[1],"x86-64"))
            if d[0] in distrosToRels[r]['experimental']:
                if d[0].startswith("sles"):
                    experimentall32.append(d)
                else:
                    experimentall32.append((d[0],"%s 32 bit" % d[1]))
                experimentalnl32.append((d[0],"%s 64 bit" % d[1],"x86-64"))

        primaryl = primaryl32 + primaryl64
        primary = primaryw + primaryl
        primarynl32 = primaryw + primaryl64
        all = primary + secondary + tertiary
        ps = primary + secondary
        st = secondary + tertiary
        experimental = experimentalnl32 + experimentall32

        # Now define necessary TCs for this release
        nightlyTCs = []
        regressionTCs = []
        experimentalTCs = []
        # Template defaults (always regression)
        regressionTCs.extend(defineMatrixTest(all, None, None, None, tcArtifacts, versionconfig))              
        experimentalTCs.extend(defineMatrixTest(experimental, None, None, None, tcArtifacts, versionconfig))              
        # 1GB 2 vCPUs on VMX for primaryw (always nightly)
        nightlyTCs.extend(defineMatrixTest(primaryw, "1GB", 2, "VMX", tcArtifacts, versionconfig))
        # 1GB 2 vCPUs on SVM for primaryw (always nightly)
        nightlyTCs.extend(defineMatrixTest(primaryw, "1GB", 2, "SVM", tcArtifacts, versionconfig))
        # 1GB 2 vCPUs on SVMHAP for primaryw (always nightly)
        nightlyTCs.extend(defineMatrixTest(primaryw, "1GB", 2, "SVMHAP", tcArtifacts, versionconfig))
        # 1GB 2 vCPUs on VMXEPT for primaryw (always nightly)
        nightlyTCs.extend(defineMatrixTest(primaryw, "1GB", 2, "VMXEPT", tcArtifacts, versionconfig))
        # 1GB 2 vCPUs on primaryl (nightly)
        nightlyTCs.extend(defineMatrixTest(primaryl, "1GB", 2, None, tcArtifacts, versionconfig))
        experimentalTCs.extend(defineMatrixTest(experimental, "1GB", 2, None, tcArtifacts, versionconfig))
        # 1GB 2 vCPUs on st (regression)
        regressionTCs.extend(defineMatrixTest(st, "1GB", 2, None, tcArtifacts, versionconfig))
        # 5GB 2vCPUs on primary (regression)
        regressionTCs.extend(defineMatrixTest(primary, "5GB", 2, None, tcArtifacts, versionconfig))
        # 1GB max vCPUs on primary (nightly)
        nightlyTCs.extend(defineMatrixTest(primary, "1GB", 99, None, tcArtifacts, versionconfig))
        experimentalTCs.extend(defineMatrixTest(experimental, "1GB", 99, None, tcArtifacts, versionconfig))
        if r in releasesWithoutSeperateMaxMemTests:
            # max RAM 2 vCPUs on primary (nightly)
            nightlyTCs.extend(defineMatrixTest(primary, "Max", 2, None, tcArtifacts, versionconfig))
            experimentalTCs.extend(defineMatrixTest(experimental, "Max", 2, None, tcArtifacts, versionconfig))
        else:
            # max RAM 2 vCPUs on primary (nightly) - all except 32bit linux
            nightlyTCs.extend(defineMatrixTest(primarynl32, "Max", 2, None, tcArtifacts, versionconfig, " (Not Linux 32 Bit)"))
            experimentalTCs.extend(defineMatrixTest(experimentalnl32, "Max", 2, None, tcArtifacts, versionconfig, " (Not Linux 32 Bit)"))
            # max RAM 2 vCPUs on primary (nightly) - 32bit linux
            nightlyTCs.extend(defineMatrixTest(primaryl32, "Max", 2, None, tcArtifacts, versionconfig, " (Linux 32 Bit)" ))
            experimentalTCs.extend(defineMatrixTest(experimentall32, "Max", 2, None, tcArtifacts, versionconfig, " (Linux 32 Bit)" ))
        # 1GB 3 vCPUs on level0 (nightly)
        nightlyTCs.extend(defineMatrixTest(level0, "1GB", 3, None, tcArtifacts, versionconfig))
        if nightly:
            suiteUpdates[nightly] = nightlyTCs
        if regression:
            suiteUpdates[regression] = regressionTCs
        if experimentalsuite:
            suiteUpdates[experimentalsuite] = experimentalTCs

    # Output the test artifacts to smoketest.py (sorted by TC)
    f = file("testcases/xenserver/tc/smoketest.py", "r")
    data = f.read()
    f.close()
    data = string.split(data, "# AUTOGEN")[0]
    data += "# AUTOGEN\n\n"
    tcs = tcArtifacts.keys()
    tcs.sort()
    for tc in tcs:
        data += string.join(tcArtifacts[tc], "\n")
        data += "\n"
    data += "\n# Autogenerated content ends. Do not edit or append.\n"
    f = file("testcases/xenserver/tc/smoketest.py", "w")
    f.write(data)
    f.close()

    # Build up the list of all TCs
    allTCs = tcArtifacts.keys()
    print "Total of %u TCs" % (len(allTCs))

    # We now know what suite updates etc to do
    j = J()
    for suite in suiteUpdates:
        print "Processing suite %s" % (suite)

        suiteissue = getIssue(j, suite)
        suitelinks = suiteissue.fields.issuelinks
        suitetcs = []
        for sl in suitelinks:
            if sl.type.name == "Contains" and hasattr(sl, "outwardIssue"):
                suitetcs.append(sl.outwardIssue.key)

        print "suite updates for " + suite + ": " + str(suiteUpdates[suite])

        # First go through and ensure that the ones that are supposed to be linked are   
        for tc in suiteUpdates[suite]:
            if not tc in suitetcs:
                print "Linking " + tc + " to suite: " + suite
                j.jira.create_issue_link(type="Contains", inwardIssue=suiteissue.key, outwardIssue=tc)
        # Now go through and check for any that are not supposed to be
        for tc in allTCs:
            if tc in suitetcs and not tc in suiteUpdates[suite]:
                print "Deleting link between " + tc + " and suite: " + suite
                links = [x for x in suiteissue.fields.issuelinks if hasattr(x, "outwardIssue") and x.type.name=="Contains" and x.outwardIssue.key == tc]
                if len(links) > 0:
                    links[0].delete()

def _walkHierarchy(j, ticket):
    reply = []
    t = getIssue(j, ticket)
    links = t.fields.issuelinks
    for link in links:
        if link.type.name == "Contains" and hasattr(link, "outwardIssue"):
            c = link.outwardIssue
            if c.fields.status.name in ("New", "Open"):
                ty = c.fields.issuetype.name
                if ty == "Test Case":
                    reply.append(link.outwardIssue.key)
                elif ty == "Hierarchy":
                    reply.extend(_walkHierarchy(j, link))
    return reply


def generateSmokeTestSequences(version="Creedence", regressionSuite="TC-21163", nightlySuite="TC-21159", expSuite="TC-19628", folder="seqs"):
    """Generates all smoke test sequences for the specified product version from the associate Jira tickets.
    
    Before using this method, ensure that processMatrixTests is up to date and has been run for the specified suites."""
   
    maxtests = {}
    maxtests["Boston"] = {}
    maxtests["Boston"]["MaxMem"] = "13419"
    maxtests["Boston"]["MaxMem32BitLin"] = "13437"
    maxtests["Boston"]["MaxvCPUs"] = "13448"
    maxtests["Sanibel"] = {}
    maxtests["Sanibel"]["MaxMem"] = "13419"
    maxtests["Sanibel"]["MaxMem32BitLin"] = "13437"
    maxtests["Sanibel"]["MaxvCPUs"] = "13448"
    maxtests["Tampa"] = {}
    maxtests["Tampa"]["MaxMem"] = "13419"
    maxtests["Tampa"]["MaxMem32BitLin"] = "13437"
    maxtests["Tampa"]["MaxvCPUs"] = "13448"
    maxtests["Clearwater"] = {}
    maxtests["Clearwater"]["MaxMem"] = "13419"
    maxtests["Clearwater"]["MaxMem32BitLin"] = "13437"
    maxtests["Clearwater"]["MaxvCPUs"] = "13448"
    maxtests["Creedence"] = {}
    maxtests["Creedence"]["MaxMem"] = "13419"
    maxtests["Creedence"]["MaxMem32BitLin"] = "13437"
    maxtests["Creedence"]["MaxvCPUs"] = "13448"
    maxtests["Dundee"] = {}
    maxtests["Dundee"]["MaxMem"] = "13419"
    maxtests["Dundee"]["MaxMem32BitLin"] = "13437"
    maxtests["Dundee"]["MaxvCPUs"] = "13448"

    j = J()
    testPrefix = "xenserver.tc.smoketest"

    if nightlySuite:

        print "Getting tickets for %s" % nightlySuite
        nightlySuiteTickets = getSuiteTickets(j, nightlySuite)
    
        # Nightly:
        # OS operation of 1GB 2 vCPUs VMs on VT+EPT
        makeSequence(version, "TC-8434", nightlySuite, "%s/%stc8434.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 15, "2", "3", "EPT1G2C")
    
        # OS operation of 1GB 3 vCPUs VMs
        makeSequence(version, "TC-7395", nightlySuite, "%s/%stc7395.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "1", "4", "VM1G3C")
   
        if maxtests.has_key(version) and maxtests[version].has_key("MaxMem"):
            makeSequence(version, "TC-%s" % maxtests[version]["MaxMem"], nightlySuite, "%s/%stc%s.seq" % (folder,version.lower(),maxtests[version]["MaxMem"]), nightlySuiteTickets, testPrefix, 10, "1", "3", "MaxMem")
            if maxtests[version].has_key("MaxMem32BitLin"):
                makeSequence(version, "TC-%s" % maxtests[version]["MaxMem32BitLin"], nightlySuite, "%s/%stc%s.seq" % (folder,version.lower(),maxtests[version]["MaxMem32BitLin"]), nightlySuiteTickets, testPrefix, 20, "1", "3", "MaxMem32BitLin")
        else:
            makeSequence(version, "TC-7394", nightlySuite, "%s/%stc7394.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "1", "3", "128G")
    
        # OS operation of 1GB 2 vCPUs VMs
        makeSequence(version, "TC-7391", nightlySuite, "%s/%stc7391.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "1", "4", "VM1G2C")
        
        # OS operation of 1GB 2 vCPUs VMs on AMD-V+NPT
        makeSequence(version, "TC-7390", nightlySuite, "%s/%stc7390.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "2", "3", "NPT1G2C")
        
        # OS operation of 1GB 2 vCPUs VMs on AMD-V
        makeSequence(version, "TC-7389", nightlySuite, "%s/%stc7389.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "2", "3", "SVM1G2C")
        
        # OS operation of 1GB 2 vCPUs VMs on Intel VT
        makeSequence(version, "TC-7388", nightlySuite, "%s/%stc7388.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "2", "3", "VMX1G2C")
    
        # OS operation using template default configuration
        makeSequence(version, "TC-6789", nightlySuite, "%s/%stc6789.seq" % (folder,version.lower()), nightlySuiteTickets, testPrefix, 10, "2", "3", "VMs")
    
    if regressionSuite:
        print "Getting tickets for %s" % regressionSuite
        regressionSuiteTickets = getSuiteTickets(j, regressionSuite)
   
        # Regression:
        # OS operation of 1GB maximum vCPUs VMs
        if maxtests.has_key(version) and maxtests[version].has_key("MaxvCPUs"):
            makeSequence(version, "TC-%s" % maxtests[version]["MaxvCPUs"], nightlySuite, "%s/%stc%sWE.seq" % (folder,version.lower(),maxtests[version]["MaxvCPUs"]), nightlySuiteTickets, testPrefix, 10, "1", "4", "MaxvCPUs")
        else:
            makeSequence(version, "TC-7393", regressionSuite, "%s/%stc7393WE.seq" % (folder,version.lower()), regressionSuiteTickets, testPrefix, 10, "1", "4", "HVM1G8C")

        # OS operation of 1GB maximum vCPUs VMs
        makeSequence(version, "TC-7392", regressionSuite, "%s/%stc7392WE.seq" % (folder,version.lower()), regressionSuiteTickets, testPrefix, 10, "1", "4", "HVM5G2C")

        # OS operation of 1GB 2 vCPUs VMs
        makeSequence(version, "TC-7391", regressionSuite, "%s/%stc7391WE.seq" % (folder,version.lower()), regressionSuiteTickets, testPrefix, 10, "1", "4", "VM1G2C")
    
        # OS operation using template default configuration
        makeSequence(version, "TC-6789", regressionSuite, "%s/%stc6789WE.seq" % (folder,version.lower()), regressionSuiteTickets, testPrefix, 10, "2", "4", "VMs")

    if expSuite:
        print "Getting tickets for %s" % expSuite
        expSuiteTickets = getSuiteTickets(j, expSuite)
    
        makeSequence(version, "TC-6789", expSuite, "%s/%stc6789EXP.seq" % (folder,version.lower()), expSuiteTickets, testPrefix, 10, "2", "4", "VMs")
        makeSequence(version, "TC-7391", expSuite, "%s/%stc7391EXP.seq" % (folder,version.lower()), expSuiteTickets, testPrefix, 10, "1", "4", "VM1G2C")
        makeSequence(version, "TC-13448", expSuite, "%s/%stc13448EXP.seq" % (folder,version.lower()), expSuiteTickets, testPrefix, 10, "1", "4", "MaxvCPUs")
   
        if maxtests.has_key(version) and maxtests[version].has_key("MaxMem"):
            makeSequence(version, "TC-%s" % maxtests[version]["MaxMem"], expSuite, "%s/%stc%sEXP.seq" % (folder,version.lower(),maxtests[version]["MaxMem"]), expSuiteTickets, testPrefix, 10, "1", "3", "MaxMem")
            if maxtests[version].has_key("MaxMem32BitLin"):
                makeSequence(version, "TC-%s" % maxtests[version]["MaxMem32BitLin"], expSuite, "%s/%stc%sEXP.seq" % (folder,version.lower(),maxtests[version]["MaxMem32BitLin"]), expSuiteTickets, testPrefix, 20, "1", "3", "MaxMem32BitLin")
        else:
            makeSequence(version, "TC-7394", expSuite, "%s/%stc7394EXP.seq" % (folder,version.lower()), expSuiteTickets, testPrefix, 10, "1", "3", "128G")
        

def getSuiteTickets(j, suite):
    suitetickets = []
    s = getIssue(j, suite)
    slinks = s.fields.issuelinks
    for slink in slinks:
        if slink.type.name == "Contains" and hasattr(slink, "outwardIssue"):
            suitetickets.append(slink.outwardIssue.key)
                
    return suitetickets

def makeSequence(version, ticket, suite, filename, suitetickets=None, testPrefix='xenserver.tc.smoketest', maxPerFile=10, parallelWorkers=0, prio=0, groupName=""):
    """Make a sequence file for a specified hierarchy ticket. This will
    include only tickets under that hierarchy that are part of the specified
    suite.
    """
    # Open a link to Jira
    j = J()
    # Get a list of all ticket in the suite
    if not suitetickets:
        suitetickets = getSuiteTickets(j, suite)
    
    print "Suite tickets for %s: %s" % (suite, (str(suitetickets)))
            
    # Walk the hierarchy to find all ticket in it
    treetickets = _walkHierarchy(j, ticket)

    print "Tree tickets for %s: %s" % (ticket, (str(treetickets)))

    tcs = []
    
    for tcid in treetickets:
        if tcid in suitetickets:
            tcs.append(string.atoi(tcid.replace("TC-", "")))
    
    tcs.sort()

    k = 0
    for i in range(0, len(tcs), maxPerFile):
        
        sequenceType = "serial"
        if parallelWorkers > 0:
            sequenceType = "parallel"
        
        # Create the XML for the seq file
        impl = xml.dom.minidom.getDOMImplementation()
        newdoc = impl.createDocument(None, "xenrt", None)
    
        vars = newdoc.createElement("variables")
        newdoc.documentElement.appendChild(vars)
        varsver = newdoc.createElement("PRODUCT_VERSION")
        vars.appendChild(varsver)
        varsvertext = newdoc.createTextNode(version)
        varsver.appendChild(varsvertext)
    
        prep = newdoc.createElement("prepare")
        newdoc.documentElement.appendChild(prep)
        prephost = newdoc.createElement("host")
        prep.appendChild(prephost)
    
        seq = newdoc.createElement("testsequence")
        newdoc.documentElement.appendChild(seq)
        ser = newdoc.createElement(sequenceType)
        seq.appendChild(ser)
        ser.setAttribute("group", "%s_%s" % (groupName, k))
        
        if parallelWorkers > 0:
            ser.setAttribute("workers", parallelWorkers)
            
        for jj in range(i, maxPerFile+i):
            if jj < len(tcs):
                tcid = "TC-%d" % tcs[jj]
                xenrttcid = "%s.%s" % (testPrefix, tcid.replace('-',''))
                xenrttcargs = None
                tc = newdoc.createElement("testcase")
                ser.appendChild(tc)
                tc.setAttribute("id", xenrttcid)
                tc.setAttribute("tc", tcid)
                
                if prio > 0:
                    tc.setAttribute("prio", prio)
                
                if xenrttcargs:
                    for arg in string.split(xenrttcargs):
                        a = newdoc.createElement("arg")
                        tc.appendChild(a)
                        at = newdoc.createTextNode(arg)
                        a.appendChild(at)

        # Write out the XML
        name = "%s_%s.seq" % (filename.replace(".seq", ""), k)
        print "Writing xml file: %s" % name 
        f = file(name, "w")
        newdoc.writexml(f, addindent="  ", newl="\n")
        f.close()
        k += 1
    
def cleanUpTickets():
    """Clean up any messes in tickets."""

    # Open a link to Jira
    j = J()
    tickets = _walkHierarchy(j, "TC-5783")
    for ticket in tickets:
        t = getIssue(j, ticket)
        # Check there are no newlines in the summary
        s = t.fields.summary
        if re.search(r"\n", s):
            s = string.replace(s, "\n", "")
            print "Removing newline from %s: %s" % (ticket, s)
            t.update(summary=s)
            

def J():
    global _jira
    if not _jira:
        # Open a link to Jira
        _jira = xenrt.getJiraLink()

    return _jira

def machineCSVs():
    [NICCSV(x) for x in xenrt.TEC().lookup("HOST_CONFIGS").keys()]

def NICCSV(machine):
    try:
        f = open("%s.csv" % machine,"w")
        mac = xenrt.TEC().lookupHost(machine,"MAC_ADDRESS")
        ip = xenrt.TEC().lookupHost(machine,"HOST_ADDRESS")
        ip6 = xenrt.TEC().lookupHost(machine,"HOST_ADDRESS6","")
        adapter = xenrt.TEC().lookupHost(machine,"OPTION_CARBON_NETS", "eth0")


        f.write("%s,NPRI,%s,%s,%s\n" % (adapter,mac,ip,ip6))

        bmcaddr = xenrt.TEC().lookupHost(machine,"BMC_ADDRESS",None)
        if bmcaddr:
            bmcmac = xenrt.TEC().lookupHost(machine,"BMC_MAC","")
            bmcuser = xenrt.TEC().lookupHost(machine,"IPMI_USERNAME")
            bmcpassword = xenrt.TEC().lookupHost(machine,"IPMI_PASSWORD")
            bmcint = xenrt.TEC().lookupHost(machine,"IPMI_INTERFACE","lan")
            f.write("BMC,,%s,%s,,%s,%s,%s\n" % (bmcmac,bmcaddr,bmcuser,bmcpassword,bmcint))

        i = 1
        while xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i],None):
            mac = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "MAC_ADDRESS"], "")
            ip = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "IP_ADDRESS"], "")
            ip6 = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "IP_ADDRESS6"], "")
            network = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "NETWORK"], "")
            if network in ("NPRI","NSEC","IPRI","ISEC"):
                f.write("eth%d,%s,%s,%s,%s\n" % (i,network,mac,ip,ip6))
            i+=1
        f.close()
    except Exception,e:
        print "Exception %s creating CSV for machine %s" % (str(e),machine)

def machineXML(machine=None):
    if machine:
        cfg = xenrt.TEC().lookup(["HOST_CONFIGS",machine],{})
        xml = "<xenrt>\n%s</xenrt>" % xenrt.dictToXML(cfg, "  ")
    else:
        cfg = xenrt.TEC().lookup("HOST_CONFIGS",{})
        xml = "<xenrt>\n  <HOST_CONFIGS>\n%s  </HOST_CONFIGS>\n</xenrt>" % xenrt.dictToXML(cfg, "    ")
    print xml

def productCodeName(version):
    print xenrt.TEC().lookup(["PRODUCT_CODENAMES",version], "ERROR: Could not find product codename")

def listGuests():
    print "\n".join(sorted(xenrt.TEC().lookup("GUEST_LIMITATIONS").keys() + [x + "-x64" for x in xenrt.TEC().lookup("GUEST_LIMITATIONS").keys() if xenrt.TEC().lookup(["GUEST_LIMITATIONS", x, "MAXMEMORY64"], None)]))

def netPortControl(machinename, ethid, enable):
    machine = xenrt.PhysicalHost(machinename, ipaddr="0.0.0.0")
    h = xenrt.GenericHost(machine)
    if enable:
        h._controlNetPort(h.getNICMACAddress(ethid), "CMD_PORT_ENABLE")
    else:
        h._controlNetPort(h.getNICMACAddress(ethid), "CMD_PORT_DISABLE")

def listHW(fn):
    nicfields = ['NIC0', 'NIC1', 'NIC2', 'NIC3', 'NIC4', 'NIC5', 'NIC6']
    hbafields = ['FC HBA 0', 'FC HBA 1']
    storagefields = ['Storage Controller', 'RAID Controller']
    rt = xenrt.getRackTablesInstance()
    machines = [x.split(",")[0] for x in open(fn).readlines()]
    models = []
    nics = []
    hbas = []
    storage = []
    for m in machines:
        try:
            o = rt.getObject(m)
        except:
            continue
        model = o.getAttribute("HW Type")
        if model and model not in models:
            models.append(model)
        for f in nicfields:
            v = o.getAttribute(f)
            if v and v not in nics:
                nics.append(v)
        for f in hbafields:
            v = o.getAttribute(f)
            if v and v not in hbas:
                hbas.append(v)
        for f in storagefields:
            v = o.getAttribute(f)
            if v and v not in storage:
                storage.append(v)

    print "==== Server Models ===="
    for v in sorted(models):
        print v
    print "\n==== NICs ====="
    for v in sorted(nics):
        print v
    print "\n==== HBAs ====="
    for v in sorted(hbas):
        print v
    print "\n==== Storage Controllers ====="
    for v in sorted(storage):
        print v

from lxml import etree
from pprint import pprint
import ast
def _getMarvinTestDocStrings(classname, testnames, marvinCodePath):
    pathToClass = os.path.join(marvinCodePath, *classname.split('.')[1:-1])+'.py'
    astData = ast.parse(open(pathToClass).read())
    classElement = filter(lambda x:isinstance(x, ast.ClassDef) and x.name == classname.split('.')[-1], astData.body)[0]
    classDocString = ast.get_docstring(classElement)
    classDocString = classDocString and classDocString.rstrip() or ''
    testMethodElements = filter(lambda x:isinstance(x, ast.FunctionDef) and x.name in testnames, classElement.body)
    testMethodDocStrings = []
    for testMethod in testMethodElements:
        docStr = ast.get_docstring(testMethod)
        docStr = docStr and docStr.rstrip() or ''
        testMethodDocStrings.append((testMethod.name, docStr))
    return (classDocString, testMethodDocStrings)

def createMarvinTCTickets(tags=[], marvinCodePath=None, mgmtSvrIP=None, testMode=False):
    if not (isinstance(tags, list) and len(tags) > 0):
        raise xenrt.XRTError('Must provide a list containing at least 1 tag')
    if not mgmtSvrIP:
        raise xenrt.XRTError('Must provide the IP address of a running CP/CS Management Server')

    # Create dummy marvin config
    marvinCfg = { 'mgtSvr': [ {'mgtSvrIp': mgmtSvrIP, 'port': 8096} ] }
    marvinConfig = xenrt.TEC().tempFile()
    fh = open(marvinConfig, 'w')
    json.dump(marvinCfg, fh)
    fh.close()

    # Get test list from nose
    noseTestList = xenrt.TEC().tempFile()
    tempLogDir = xenrt.TEC().tempDir()
    noseArgs = ['--with-marvin', '--marvin-config=%s' % (marvinConfig),
                '--with-xunit', '--xunit-file=%s' % (noseTestList),
                '--log-folder-path=%s' % (tempLogDir),
                '--load',
                marvinCodePath,
                '-a "%s"' % (','.join(map(lambda x:'tags=%s' % (x), tags))),
                '--collect-only']
    print 'Using nosetest args: %s' % (' '.join(noseArgs))
    xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))

    xmlData = etree.fromstring(open(noseTestList).read())
    testData = {}
    for element in xmlData.getchildren():
        classname = element.get('classname')
        testname = element.get('name')
        if testData.has_key(classname):
            if testname in testData[classname]:
                print 'Duplicate testname [%s] found in class [%s]' % (testname, classname)
            else:
                testData[classname].append(testname)
        else:
            testData[classname] = [ testname ]
    
    pprint(testData)
    testData.pop('nose.failure.Failure')

    jira = xenrt.JiraLink()
    maxResults = 200
    allMarvinTCTickets = jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults)
    print 'Total number Marvin TCs to fetch: %d' % (allMarvinTCTickets.total)
    while(len(allMarvinTCTickets) < allMarvinTCTickets.total):
        allMarvinTCTickets += jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults, startAt=len(allMarvinTCTickets))

    for key in testData.keys():
        (classDocString, testMethodDocStrings) = _getMarvinTestDocStrings(key, testData[key], marvinCodePath)
        title = key.split('.')[-1] + ' [%s]' % (', '.join(tags))
        tcMarvinMetaIdentifer = '%s' % ({ 'classpath': key, 'tags': tags })
        component = [{'id': '11606'}]
        testType = {'id': '12920', 'value': 'Marvin'}
        description  = 'Marvin tests in class %s matching tag(s): %s\n' % (key.split('.')[-1], ', '.join(tags))
        description += 'Full class-path: *%s*\n' % (key)
        if classDocString != '':
            description += '{noformat}\n%s\n{noformat}\n' % (classDocString)
        description += '\nThis class contains the following Marvin test(s)\n'
        for testMethodDocString in testMethodDocStrings:
            description += 'TestMethod: *%s*\n' % (testMethodDocString[0])
            if testMethodDocString[1] != '':
                description += '{noformat}\n%s\n{noformat}\n' % (testMethodDocString[1])
            description += '\n'
        description += '\n*WARNING: This testcase is generated - do not edit any field directly*'

        tcTkts = filter(lambda x:eval(x.fields.customfield_10121) == { 'classpath': key, 'tags': tags }, allMarvinTCTickets)
        if len(tcTkts) == 0:
            newTicketId = 'TestMode'
            if not testMode:
                newTicket = jira.jira.create_issue(project={'key':'TC'}, issuetype={'name':'Test Case'}, reporter={'name':'xenrt'},
                                                   summary=title, 
                                                   components=component, 
                                                   customfield_10121=tcMarvinMetaIdentifer,
                                                   customfield_10713=testType,
                                                   description=description)
                newTicketId = newTicket.key
            print 'Created new ticket [%s]' % (newTicketId)
        elif len(tcTkts) == 1:
            print 'Updating existing ticket [%s]' % (tcTkts[0].key)
            if not testMode:
                tcTkts[0].update(summary=title, components=component, customfield_10121=tcMarvinMetaIdentifer, description=description)
        else:
            raise xenrt.XRTError('%d tickets match classpath: %s, tags: %s [%s] aborting' % (key, tags, ','.join(map(lambda x:x.key, tcTkts))))

        if testMode:
            print title
            print tcMarvinMetaIdentifer
            print description
            print '-------------------------------------------------------------------------------------'

def createMarvinSequence(tags=[], classPathRoot=''):
    if not (isinstance(tags, list) and len(tags) > 0):
        raise xenrt.XRTError('Must provide a list containing at least 1 tag')

    jira = xenrt.JiraLink()
    maxResults = 20
    allMarvinTCTickets = jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults)
    print 'Total number Marvin TCs to fetch: %d' % (allMarvinTCTickets.total)
    while(len(allMarvinTCTickets) < allMarvinTCTickets.total):
        allMarvinTCTickets += jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults, startAt=len(allMarvinTCTickets))
    marvinTestsStrs = []
    for tkt in allMarvinTCTickets:
        marvinMetaData = eval(tkt.fields.customfield_10121)
        if marvinMetaData['tags'] == tags and marvinMetaData['classpath'].startswith(classPathRoot):
            marvinTestsStrs.append('      <marvintests path="%s" class="%s" tags="%s" tc="%s"/>' % (os.path.join(*marvinMetaData['classpath'].split('.')[1:-1])+'.py',
                                                                                                    marvinMetaData['classpath'].split('.')[-1],
                                                                                                    ','.join(tags),
                                                                                                    tkt.key))

    marvinTestsStrs.sort()
    for testStr in marvinTestsStrs:
        print testStr

def newGuestsMiniStress():
    # Tailor to your needs
    families = {"oel": "Oracle Enterprise Linux", "rhel": "RedHat Enterprise Linux", "centos": "CentOS"}

    template = """<xenrt>

  <!-- OS functional test sequence: %s and %s-x64 -->

  <variables>
    <PRODUCT_VERSION>Creedence</PRODUCT_VERSION>
  </variables>

  <default name="PARALLEL" value="2" />
  <default name="MIGRATEPAR" value="1" />

  <semaphores>
    <TCMigrate count="${MIGRATEPAR}" />
  </semaphores>

  <prepare>
    <host />
  </prepare>

  <testsequence>
    <parallel workers="${PARALLEL}">
%s
%s
    </parallel>
  </testsequence>
</xenrt>
"""

    for i in families.keys():
        for j in ["5.11", "6.6"]:
            osname = "%s%s" % (i, j.replace(".", ""))
            print osname
            a = defineOSTests(osname, "%s %s" % (families[i], j))
            b = defineOSTests(osname, "%s %s x64" % (families[i], j), arch="x86-64")
            seq = template % (osname, osname, a, b)

            with open("seqs/creedenceoslin%s.seq" % osname, "w") as f:
                f.write(seq)

def newGuestsInstalls():
    # Tailor to your needs

    families = {"oel": "Oracle Enterprise Linux", "rhel": "RedHat Enterprise Linux", "centos": "CentOS"}
    methods = {"ISO": ("_TC5786", False), "HTTP": ("_TC6767", True), "NFS": ("_TC6767", True) }
    arches = {"x86-32": "32 bit", "x86-64": "64 bit"}
    versions = {"511": "5.11", "66": "6.6"}

    tccode = ""
    seqcode = ""

    j = J()
    container = getIssue(j, "TC-5790")

    for f in families.keys():
        for v in versions.keys():
            for m in methods.keys():
                for a in arches.keys():
                    tcname = "Install a %s %s %s VM from %s" % (families[f], versions[v], arches[a], m)
                    print "Creating %s" % tcname
                    tckey = _findOrCreateTestCase({}, tcname, j, container, tcname)
                    print tckey
                    (base, needmethod) = methods[m]
                    tccode += "class %s(%s):\n" % (tckey.replace("-", ""), base)
                    tccode += "    \"\"\"%s\"\"\"\n" % (tcname)
                    tccode += "    DISTRO=\"%s%s\"\n" % (f, v)
                    tccode += "    ARCH=\"%s\"\n" % a
                    if needmethod:
                        tccode += "    METHOD=\"%s\"\n" % m
                    tccode += "\n"
                    seqcode += "<testcase id=\"xenserver.tc.vminstall.%s\" group=\"VMInstall\"/>\n" % tckey.replace("-", "")

    print tccode
    print seqcode


