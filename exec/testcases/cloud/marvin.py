import json, os, xml.dom.minidom, re, glob

import xenrt
from xenrt.lib.netscaler import NetScaler

class RemoteNoseInstaller(object):
    GIT_LOCATION = "https://git-wip-us.apache.org/repos/asf/cloudstack"

    def __init__(self, runner):
        self.runner = runner

    def install(self):
        # Install git, python, pip, paramiko, nose
        self.runner.execguest("apt-get install -y --force-yes git python python-dev python-setuptools python-dev python-pip")
        # Install marvin
        if xenrt.TEC().lookup("MARVIN_URL", None):
            self.runner.execguest("wget -O /root/marvin.tar.gz \"%s\"" % xenrt.TEC().lookup("MARVIN_URL"))
        else:
            sftp = self.runner.sftpClient()
            sftp.copyTo(xenrt.getMarvinFile(), "/root/marvin.tar.gz")

        self.runner.execguest("wget '%s/marvindeps.tgz' -O /root/marvindeps.tgz" % xenrt.TEC().lookup("TEST_TARBALL_BASE"))
        self.runner.execguest("tar -zxf /root/marvindeps.tgz -C /root/")
        self.runner.execguest("pip install --no-index --find-links=/root/marvindeps /root/marvindeps/pip*")
        self.runner.execguest("pip install --no-index --find-links=/root/marvindeps /root/marvindeps/*")
        self.runner.execguest("pip install /root/marvin.tar.gz")

        testurl = xenrt.TEC().lookup("MARVIN_TEST_URL", None)
        if testurl:
            self.runner.execguest("mkdir /root/cloudstack")
            self.runner.execguest("wget -O /root/marvintests.tar.gz %s" % testurl)
            self.runner.execguest("cd /root/cloudstack && tar -xvzf /root/marvintests.tar.gz")
        else:
            self.git = xenrt.TEC().lookup("CLOUDSTACK_GIT", "http://git-ccp.citrix.com/cgit/internal-cloudstack.git")
            self.gitBranch = xenrt.TEC().lookup("CLOUDSTACK_GIT_BRANCH", "master")

            self.runner.execguest("git clone %s /root/cloudstack" % self.git, timeout=3600)
            self.runner.execguest("cd /root/cloudstack && git checkout %s" % self.gitBranch)
            self.runner.execguest("cd /root/cloudstack && git pull")

        patch = xenrt.TEC().lookup("MARVIN_PATCH", None)
        if patch:
            self.runner.execguest("wget -O /root/cs.patch %s" % patch)
            self.runner.execguest("cd /root/cloudstack && patch -p1 < /root/cs.patch")

class _TCRemoteNoseBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        self.runner = self.getGuest(self.args.get("runner", "CS-Marvin"))
        self.toolstack = self.getDefaultToolstack()
        xenrturl = xenrt.TEC().lookup("JIRA_XENRT_WEB", 
                              "http://xenrt.hq.xensource.com/control/queue.cgi")
        jobid = xenrt.GEC().dbconnect.jobid()
        if self.group:
            phase = self.group.replace(" ","%20")
        else:
            phase = "Phase%2099"
        test = self.basename.replace(" ","%20")
        self.logurl = "%s?action=testlogs&id=%s&phase=%s&test=%s" % (xenrturl, jobid, phase, test) 

    def ticketAssignee(self):
        return self.args.get("ticketassignee", None)

    def getReason(self, failure):
        if not failure:
            return None
        failure = failure.split("-------------------- >>")[0]
        cmd = None
        # See if this is a JSON error with a command
        m = re.search("cmd : u'\S+\.(\S+?)'", failure)
        if m:
            cmd = m.group(1)
        error = None
        # And see if we've got some errortext
        m = re.search("errortext : u'(.+?)'", failure)
        if m:
            error = m.group(1)
        if error:
            if cmd:
                reason = "%s failed: %s" % (cmd, error)
            else:
                reason = error
        else:
            reason = failure
        
        reason = re.sub("\d+-\d+-VM", "xx-xx-VM", reason)
        reason = re.sub("\d+-VM", "xx-VM", reason)
        reason = re.sub("\[\S+\|\S+\|\S+\]", "[xx|xx|xx]", reason)
        reason = re.sub("rule \d+", "rule xx", reason)
        
        return reason

class TCRemoteNoseSetup(_TCRemoteNoseBase):
    def run(self, arglist):
        sftp = self.runner.sftpClient()
        sftp.copyTreeTo("%s/data/tests/marvin" % xenrt.TEC().lookup("XENRT_BASE"), "/root/marvin-scripts")
        try:
            testData = json.loads(self.runner.execguest("/root/marvin-scripts/getDefaultConfig.py"))
        except:
            xenrt.TEC().logverbose("test_data not supported")
        else:
            # Older versions of marvin don't have configurableData.
            # Initialise it to an empty dict here so we don't get exceptions
            # later on
            if not testData.has_key('configurableData'):
                testData['configurableData'] = {}
            if self.args.has_key("resources"):
                resources = self.args['resources'].split(",")
            else:   
                resources = []
            if "nfs" in resources:
                nfspath = xenrt.ExternalNFSShare().getMount()
                testData['nfs'] = {"url": "nfs://%s" % nfspath, "name": "Test NFS Storage"}
            if "iscsi" in resources:
                lun = xenrt.ISCSITemporaryLun(100)
                testData['iscsi'] = {"url": "iscsi://%s/%s/%d" % (lun.getServer(), lun.getTargetName(), lun.getLunID()), "name": "Test iSCSI Storage"}
                testData['configurableData']['iscsi'] = {"url": "iscsi://%s/%s/%d" % (lun.getServer(), lun.getTargetName(), lun.getLunID()), "name": "Test iSCSI Storage"}
            if "portableip" in resources:
                range = xenrt.StaticIP4Addr().getIPRange(4)
                testData['configurableData']['portableIpRange']['startip'] = range[0].getAddr()
                testData['configurableData']['portableIpRange']['endip'] = range[-1].getAddr()
                testData['configurableData']['portableIpRange']['gateway'] = xenrt.getNetworkParam("NPRI", "GATEWAY")
                testData['configurableData']['portableIpRange']['netmask'] = xenrt.getNetworkParam("NPRI", "SUBNETMASK")
                testData['configurableData']['portableIpRange']['vlan'] = 1000
            if "netscaler" in resources:
                netscaler = NetScaler.setupNetScalerVpx('NetScaler-VPX')
                netscaler.applyLicense(netscaler.getLicenseFileFromXenRT())
                testData['configurableData']['netscaler']['ipaddress'] = netscaler.managementIp
                testData['configurableData']['netscaler']['username'] = 'nsroot'
                testData['configurableData']['netscaler']['password'] = 'nsroot'
                testData['configurableData']['netscaler']['networkdevicetype'] = 'NetscalerVPXLoadBalancer'
                testData['configurableData']['netscaler']['publicinterface'] = '1/1'
                testData['configurableData']['netscaler']['privateinterface'] = '1/1'
                testData['configurableData']['netscaler']['numretries'] = '2'
            if self.args['hypervisor'].lower() == "hyperv":
                testData['service_offering']['memory'] = 512
                testData['service_offerings']['memory'] = 512
                testData['service_offerings']['tiny']['memory'] = 512
                testData['service_offerings']['small']['memory'] = 512
                testData['service_offerings']['medium']['memory'] = 512
                testData['service_offerings']['big']['memory'] = 512

                testData['service_offering']['cpuspeed'] = 500
                testData['service_offerings']['cpuspeed'] = 500
                testData['service_offerings']['tiny']['cpuspeed'] = 500
                testData['service_offerings']['small']['cpuspeed'] = 500
                testData['service_offerings']['medium']['cpuspeed'] = 500
                testData['service_offerings']['big']['cpuspeed'] = 500

            testData['hypervisor'] = self.args['hypervisor']
            testData['small']['hypervisor'] = self.args['hypervisor']
            testData['medium']['hypervisor'] = self.args['hypervisor']
            testData['server']['hypervisor'] = self.args['hypervisor']
            testData['server_without_disk']['hypervisor'] = self.args['hypervisor']
            testData['host_password'] = xenrt.TEC().lookup("ROOT_PASSWORD")
            testData['configurableData']['host']['password'] = xenrt.TEC().lookup("ROOT_PASSWORD")
            with open("%s/testdata.cfg" % xenrt.TEC().getLogdir(), "w") as f:
                f.write(json.dumps(testData, indent=2))
    
            sftp.copyTo("%s/testdata.cfg" % xenrt.TEC().getLogdir(), "/root/testdata.cfg")
            self.toolstack.marvinCfg['TestData'] = {'Path': "/root/testdata.cfg"}

        with open("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "w") as f:
            f.write(json.dumps(self.toolstack.marvinCfg, indent=2))

        sftp.copyTo("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "/root/marvin.cfg")

class TCRemoteNoseSimSetup(_TCRemoteNoseBase):
    def run(self, arglist):
        mgmtSvr = self.getGuest("CS-MS")
        mgmtSvrIp = mgmtSvr.getIP()
        cfg = json.loads(self.runner.execguest("cat /root/cloudstack/%s | grep -v \"^#\"" % self.args['deploy']))
        cfg['dbSvr']['dbSvr'] = mgmtSvrIp
        cfg['mgtSvr'][0]['mgtSvrIp'] = mgmtSvrIp
        cfg['mgtSvr'][0]['passwd'] = mgmtSvr.password

        with open("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "w") as f:
            f.write(json.dumps(cfg, indent=2))

        sftp = self.runner.sftpClient()
        sftp.copyTo("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "/root/marvin.cfg")
        
        self.runner.execguest("python /root/cloudstack/tools/marvin/marvin/deployDataCenter.py -i /root/marvin.cfg")
        cloud = xenrt.lib.cloud.CloudStack(self.getGuest("CS-MS"))
        cloud.mgtsvr.restart()
        marvin = xenrt.lib.cloud.MarvinApi(cloud.mgtsvr)
        marvin.waitForBuiltInTemplatesReady()
        xenrt.GEC().registry.toolstackPut("cloud", cloud)
        self.getDefaultToolstack()

class TCRemoteNose(_TCRemoteNoseBase):
    SUBCASE_TICKETS = True

    def run(self, arglist):
        self.workdir = self.runner.execguest("mktemp -d /root/marvinXXXXXXXX").strip()
        self.failures = {}
        noseargs = ""

        if self.args.has_key("tags"):
            noseargs = "-a tags=%s" % self.args['tags']
        elif self.args.has_key("args"):
            noseargs = self.args['args']

        if self.tec.lookup("POF_ALL", False, boolean=True):
            noseargs += " --stop"

        if self.args.has_key("hypervisor"):
            noseargs += " --hypervisor=%s" % self.args['hypervisor']

        self.runner.execguest("nosetests -v --logging-level=DEBUG --log-folder-path=%s --with-marvin --marvin-config=/root/marvin.cfg --with-xunit --xunit-file=%s/results.xml %s /root/cloudstack/%s" %
                   (self.workdir,
                    self.workdir,
                    noseargs,
                    self.args['file']), timeout=28800, retval="code")

        sftp = self.runner.sftpClient()
        logdir = xenrt.TEC().getLogdir()
        sftp.copyTreeFrom(self.workdir, logdir + '/marvin')
        self.parseResultsXML("%s/marvin/results.xml" % logdir)

    def truncateText(self, text):
        ret = text.split("--------")[0]
        ret += "\n\nLogs available at %s" % self.logurl
        return ret

    def truncateTCText(self, tc, suite, doc):
        t = doc.createElement("testcase")
        for a in tc.attributes.keys():
            t.setAttribute(a, tc.getAttribute(a))

        for n in tc.childNodes:
            if n.nodeName in ("system-out", "system-err"):
                continue
            
            newNode = doc.createElement(n.nodeName)
            for a in n.attributes.keys():
                if a == "message":
                    newNode.setAttribute("message", self.truncateText(n.getAttribute("message")))
                else:
                    newNode.setAttribute(a, n.getAttribute(a))
            for m in n.childNodes:
                if m.nodeType == m.CDATA_SECTION_NODE:
                    cdata = doc.createCDATASection(self.truncateText(m.data))
                    newNode.appendChild(cdata) 
                else:
                    newNode.appendChild(m)
            t.appendChild(newNode)

        suite.appendChild(t)

    def parseResultsXML(self, fname):
        d = xml.dom.minidom.parse(fname)
        newdoc = xml.dom.minidom.Document()
        suites = d.getElementsByTagName("testsuite")
        for s in suites:
            tcs = s.getElementsByTagName("testcase")
            for t in tcs:
                result = xenrt.RESULT_PASS
                msg = None
                if t.getElementsByTagName("failure"):
                    result = xenrt.RESULT_FAIL
                    msg = t.getElementsByTagName("failure")[0].getAttribute("message")
                elif t.getElementsByTagName("error"):
                    result = xenrt.RESULT_FAIL
                    msg = t.getElementsByTagName("error")[0].getAttribute("message")
                elif t.getElementsByTagName("skipped"):
                    result = xenrt.RESULT_SKIPPED
                self.testcaseResult(t.getAttribute("classname"), t.getAttribute("name"), result, self.getReason(msg))
                if msg and len(msg) > 12500:
                    # Need to trim the message for Jira
                    newmsg = msg[:2500]
                    newmsg += "\n\n-- trimmed - full logs available on link above --\n\n"
                    newmsg += msg[-10000:]
                    msg = newmsg
                self.failures["%s/%s" % (t.getAttribute("classname"), t.getAttribute("name"))] = msg

            newsuite = newdoc.createElement("testsuite")
            for a in s.attributes.keys():
                newsuite.setAttribute(a, s.getAttribute(a))

            for t in s.getElementsByTagName("testcase"):
                self.truncateTCText(t, newsuite, newdoc)

            newdoc.appendChild(newsuite)

        with open("%s-truncated.xml" % fname[:-4], "w") as f:
            f.write(newdoc.toprettyxml())

    def getSubCaseTicketDescription(self, group, test):
        msg = self.failures.get("%s/%s" % (group, test), None)
        if msg:
            return "{noformat}\n%s\n{noformat}\n\n" % msg
        else:
            return None

    def getSubCaseJiraIdent(self, group, test):
        grouptext = ".".join(reversed(group.split(".")))
        return "Marvin: %s.%s" % (test, grouptext)

    def ticketAttachments(self):
        logdir = xenrt.TEC().getLogdir()
        return glob.glob("%s/marvin/MarvinLogs/*/results.txt" % logdir)

class TCCombineResults(_TCRemoteNoseBase):
    def run(self, arglist):
        alltcs = []
        sftp = self.runner.sftpClient()
        files = [x.strip() for x in self.runner.execguest("ls /root/marvin*/results.xml").splitlines()]

        t = xenrt.TempDirectory()
        for f in files:
            sftp.copyFrom(f, "%s/results.xml" % t.path())
            dom = xml.dom.minidom.parse("%s/results.xml" % t.path())
            suites = dom.getElementsByTagName("testsuite")
            for s in suites:
                tcs = s.getElementsByTagName("testcase")
                alltcs.extend(tcs)

        failcount = len([x for x in alltcs if x.getElementsByTagName("failure")])
        skipcount = len([x for x in alltcs if x.getElementsByTagName("skipped")])
        errorcount = len([x for x in alltcs if x.getElementsByTagName("error")])
        totalcount = len(alltcs)

        d = xml.dom.minidom.Document()

        s = d.createElement("testsuite")
        s.setAttribute("name", "nosetests")
        s.setAttribute("tests", str(totalcount))
        s.setAttribute("errors", str(errorcount))
        s.setAttribute("failures", str(failcount))
        s.setAttribute("skip", str(skipcount))
        d.appendChild(s)
        for t in alltcs:
            s.appendChild(t)

        os.mkdir("%s/marvin" % (xenrt.TEC().getLogdir()))

        with open("%s/marvin/results.xml" % xenrt.TEC().getLogdir(), "w") as f:
            f.write(d.toprettyxml())
