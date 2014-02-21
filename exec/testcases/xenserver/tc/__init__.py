import re
import string
import time
import xenrt

class _XapiRTBase(xenrt.TestCase):
    """Base class for running Xapi RT style test cases"""
    TCID = None
    TYPE = None
    TIMEOUT = 300
    AUTO_UNINSTALL_OLD_VMS = False
    CLEANUP_VDIS_ON_SR_TYPES = []
    EXPECTED_PATH = '/tmp/local/bm/scripts/remote/patterns.py'
    ACTUAL_PATH = '/opt/xenrt/scripts/remote/patterns.py'
    LOCATION = '/etc/xapi.d/plugins/lvhdrt-helper'
    CHANGE_PATTERNS_PATH = False
    
    def prepare(self, arglist):
        if not self.TCID:
            raise xenrt.XRTError("TCID not specified")
        if not self.TYPE:
            raise xenrt.XRTError("TYPE not specified")
        self.host = self.getDefaultHost()
        # Check the script is present
        rc = self.host.execdom0("ls /opt/xensource/debug/%srt" % (self.TYPE),
                                retval="code")
        if rc != 0:
            raise xenrt.XRTError("%srt not found in /opt/xensource/debug" % (self.TYPE))

        #Tweak /etc/xapi.d/plugins/lvhdrt-helper to point to correct location of patterns.py( /tmp/local/bm/scripts/remote/patterns.py to /opt/xenrt/scripts/remote/patterns.py)
        if self.CHANGE_PATTERNS_PATH:
            self.host.execdom0("sed -i 's,%s,%s,g' %s" %(self.EXPECTED_PATH,self.ACTUAL_PATH,self.LOCATION))
            
        # If the testcase wants it, remove any old VMs hanging around
        # on the host.
        if self.AUTO_UNINSTALL_OLD_VMS:
            self.host.uninstallAllGuests()

        # If the testcase wants it, make sure all VDIs on SR(s) are gone
        cli = self.host.getCLIInstance()
        srs = []
        for srtype in self.CLEANUP_VDIS_ON_SR_TYPES:
            xsrs = self.host.getSRs(type=srtype)
            if xsrs:
                srs.extend(xsrs)
        for sr in srs:
            xenrt.TEC().logverbose("Making sure SR %s is empty" % (sr))
            vdis = self.host.minimalList("vdi-list",
                                         "uuid",
                                         "sr-uuid=%s" % (sr))
            if len(vdis) == 0:
                continue
            needgc = False
            for vdi in vdis:
                vdiname = self.host.genParamGet("vdi", vdi, "name-label")
                if vdiname == "base copy":
                    needgc = True
                    continue
                vbds = self.host.genParamGet("vdi", vdi, "vbd-uuids")
                if vbds:
                    for vbd in vbds.split(";"):
                        vbd = vbd.strip()
                        ca = self.host.genParamGet("vbd",
                                                   vbd,
                                                   "currently-attached")
                        if ca == "true":
                            cli.execute("vbd-unplug", "uuid=%s" % (vbd))
                        cli.execute("vbd-destroy", "uuid=%s" % (vbd))
                cli.execute("vdi-destroy", "uuid=%s" % (vdi))
            allclean = False
            msg = None
            for i in range(3):
                vdis = self.host.minimalList("vdi-list",
                                             "uuid",
                                             "sr-uuid=%s" % (sr))
                if len(vdis) == 0:
                    allclean = True
                    break
                msg = "SR %s, VDI(s) %s" % (sr, string.join(vdis))
                if not needgc:
                    raise xenrt.XRTError("VDIs left in SR after cleanup",
                                         msg)
                time.sleep(30)
            if not allclean:
                raise xenrt.XRTError("VDIs left in SR after cleanup", msg)

        self.extraPrepare()

    def extraPrepare(self):
        pass

    def run(self, arglist):
        xenrt.TEC().logverbose("Running test case TC-%s." % (self.TCID))
        outfile = xenrt.TEC().getLogdir() + "/%srt.out" % (self.TYPE)
        result = self.host.execdom0("/opt/xensource/debug/%srt "
                                    "-u root -h %s -p %s -tc %s" %
                                    (self.TYPE,
                                     self.host.getIP(),
                                     self.host.password,
                                     self.TCID),
                                     retval="code",
                                     outfile=outfile,
                                     timeout=self.TIMEOUT)
        data = file(outfile, "r").read()
        successes = re.findall("^SUCCESS.*|^PASS.*", data, re.MULTILINE)
        for s in successes:
            xenrt.TEC().comment(s)
        failures = re.findall("^Fatal error: .*|^FAIL.*", data, re.MULTILINE)
        if result:
            failures.append("%sRT exited with non-zero return code." % (self.TYPE))
        errors = re.findall("^ERROR.*|^Test error: .*", data, re.MULTILINE)
        if errors:
            for e in errors: xenrt.TEC().reason(e)
            raise xenrt.XRTError("%sRT error(s) detected." % (self.TYPE))
        if failures:
            for f in failures: xenrt.TEC().reason(f)
            raise xenrt.XRTFailure("%sRT failure(s) detected." % (self.TYPE))

