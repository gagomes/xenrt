#
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Job level tests for XenServer
#

import sys, string, os.path, glob, time, re, random, shutil, os, stat
import traceback
import xenrt

class JTDom0Xen(xenrt.JobTest):
    TCID = "TC-20690"
    FAIL_MSG = "Dom0 attempted operations which are only allowed for Xen"
    
    def preJob(self):
        preJobValue = self.host.execdom0("xl dmesg | grep ':d0 Domain attempted'", level = xenrt.RC_OK)
        self.res = []
        if type(preJobValue) == str: #Some error messages found
            self.res = preJobValue.strip().splitlines()
            xenrt.TEC().logverbose("Dom0 found to be attempting disallowed operations in the pre job phase:\n%s" % preJobValue)
            
    def postJob(self):
        postJobValue = self.host.execdom0("xl dmesg | grep ':d0 Domain attempted'", level = xenrt.RC_OK)
        if type(postJobValue) == str: # Some error messages found
            self.res.extend([x for x in postJobValue.strip().splitlines() if x not in self.res]) # To add only the extra errors that were observed during the job
        if self.res:
            return ",".join(self.res) 


class JTSUnreclaim(xenrt.JobTest):
    TCID = "TC-20616"
    FAIL_MSG = "SUnreclaim value > 2 times pre job value"

    def preJob(self):
        self.preJobValue = self.host.getFromMemInfo("SUnreclaim")

    def postJob(self):
        postJob = self.host.getFromMemInfo("SUnreclaim")
        ratio = float(postJob) / float(self.preJobValue)
        xenrt.TEC().logverbose("SUnreclaim finish / start = %.2f" % ratio)
        if ratio >= 2:
            return ratio

class JTSlab(xenrt.JobTest):
    TCID = "TC-20617"
    FAIL_MSG = "Slab value > 200Mib"

    def postJob(self):
        slabValue = self.host.getFromMemInfo("Slab") / xenrt.KILO
        xenrt.TEC().logverbose("Slab = %d MiB" % slabValue)
        if slabValue > 200:
            return slabValue

class JTPasswords(xenrt.JobTest):
    TCID = "TC-20622"
    FAIL_MSG = "Plaintext password seen in log file"

    IGNORE_PASSWORDS = ['xensource', 'administrator', 'admin', 'password']
    PRE_COMMANDS = ["rm -rf /root/support-unpacked && mkdir /root/support-unpacked && tar -xf /root/support.tar.bz2 -C /root/support-unpacked"]
    CHECK_COMMANDS = ["find /var/log -exec zgrep -H -E %s {} \\;",
                      "find /tmp -wholename \"/tmp/local\" -prune -o -wholename \"/tmp/xencert_isl.conf\" -prune -o -name \\* -exec grep -H -E %s {} \\; 2>/dev/null",
                      "ps ax | grep -v grep | grep -E %s  || [ $? -eq 1 ] && true",
                      "grep -r -E %s /root/support-unpacked  || [ $? -eq 1 ] && true",
                      "find /etc -wholename \"/etc/iscsi\" -prune -o -type f -exec grep -r -E -H %s {} \; || [ $? -eq 1 ] && true"]


    def postJob(self):
        self.passwords = []
        foundPasswords = []

        self._addPassword(xenrt.TEC().lookup("ROOT_PASSWORD"))
        self._addPassword(xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        for l in xenrt.TEC().lookup("ISCSI_LUNS", {}).keys():
            self._addPassword(xenrt.TEC().lookup(["ISCSI_LUNS", l, "CHAP", "SECRET"], None), user=xenrt.TEC().lookup(["ISCSI_LUNS", l, "CHAP", "USERNAME"], None))
        for x in ['FC_PROVIDER', 'EQUALLOGIC', 'NETAPP_FILERS', 'SMIS_ISCSI_TARGETS', 'SMIS_FC_TARGETS']:
            for t in xenrt.TEC().lookup(x, {}).keys():
                self._addPassword(xenrt.TEC().lookup([x, t, "PASSWORD"], None))
  
        if len(self.passwords) == 0:
            return

        for c in self.PRE_COMMANDS:
            try:
                self.host.execdom0(c)
            except Exception, e:
                xenrt.TEC().logverbose("Failed to execute %s - %s" % (c, str(e)))
                
        for c in self.CHECK_COMMANDS:
            cmd = c % ("\"%s\"" % string.join([re.escape(x) for x in self.passwords], "|"))
            try:
                lines = self.host.execdom0(cmd)
                if len(lines.strip()) > 0:
                    foundPasswords.append(c)
            except Exception, e:
                xenrt.TEC().logverbose("Failed to execute %s - %s" % (cmd, str(e)))
                

        if len(foundPasswords) > 0:
            return "Found plain text passwords in commands %s" % string.join(foundPasswords, ", ")

    def _addPassword(self, password, user=None):
        if password and not (password.lower() in [x.lower() for x in self.IGNORE_PASSWORDS] or # Exclude ignored passwords
                             password in self.passwords or # Don't add it if it's already in the list
                             user == password): # If the username and the password are the same, ignore (valid to log usernames)
            self.passwords.append(password)

# collect coverage informations
class JTCoverage(xenrt.JobTest):
    TCID = "TC-21013"
    FAIL_MSG = "Collect coverage information"

    def preJob(self):
        self.coverageSupport = False
        if xenrt.TEC().lookup("COVERAGE_URL", None) is None or \
           self.host.execdom0("rm -rf /var/coverage; mkdir -p /var/coverage; xencov reset", retval="code") != 0:
            return

        self.coverageSupport = True
        # save log on reboot to collect even these data
        self.host.execdom0("""cat > /etc/rc6.d/S00xencov <<EOF
#!/bin/bash

if [ "$1" = "start" ]; then
	export PATH=/sbin:/usr/sbin:/bin:/usr/bin
	mkdir -p /var/coverage
	NOW=$(date +'%Y%m%d%H%M%S')
	xencov read | xz -c > /var/coverage/gcov-$NOW.dat.xz
fi

EOF
chmod +x /etc/rc6.d/S00xencov""")

    def postJob(self):
        if not self.coverageSupport:
            return

        # now use curl to collect data
        self.host.execdom0("""cd /var/coverage || exit 0
NOW=$(date +'%%Y%%m%%d%%H%%M%%S')
xencov read | xz -c > gcov-$NOW.dat.xz
BUILD_NUMBER=0x
eval $(grep ^BUILD_NUMBER= /etc/xensource-inventory)
HOST="$(hostname)"
for f in gcov-*.dat.xz; do
	curl -F "hostname=$HOST" -F "build=$BUILD_NUMBER" -F "job=%s" -F "suite=%s" -F "tag=%s" -F userfile=@$f %s
done
""" % (xenrt.TEC().lookup("JOBID", "-"), xenrt.TEC().lookup("JOBGROUP", "-"), xenrt.TEC().lookup("JOBGROUPTAG", "-"), xenrt.TEC().lookup("COVERAGE_URL", None)) )

class JTGro(xenrt.JobTest):
    TCID = "TC-20999"
    FAIL_MSG = "Gro not on by default on trunk host"

    def postJob(self):
        # Verify GRO is set to the 'ON' by default for all the NICs
        nics = [] #list containing the nics with GRO off
        for id in [0]+self.host.listSecondaryNICs():
            nic = self.host.getNIC(id)
            currstate = self.host.execdom0("ethtool -k %s | grep 'generic-receive-offload' | cut -d ':' -f 2" %nic).strip()
            if not currstate == "on":
                nics.append(nic)
        if not nics:
            xenrt.TEC().logverbose("GRO is on by default for all the NICs")
        else:
            return "GRO is off for NICs : %s" % string.join(nics,", ")

__all__ = ["JTDom0Xen", "JTSUnreclaim", "JTSlab", "JTPasswords", "JTCoverage", "JTGro"]
