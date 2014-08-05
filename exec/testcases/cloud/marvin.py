import json, os, xml.dom.minidom

import xenrt

class RemoteNoseInstaller(object):
    GIT_LOCATION = "https://git-wip-us.apache.org/repos/asf/cloudstack.git"

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
        self.runner.execguest("pip install /root/marvin.tar.gz")

        self.git = xenrt.TEC().lookup("CLOUDSTACK_GIT", "http://git-ccp.citrix.com/cgit/internal-cloudstack.git")
        self.gitBranch = xenrt.TEC().lookup("CLOUDSTACK_GIT_BRANCH", "master")

        self.runner.execguest("git clone %s /root/cloudstack.git" % self.git, timeout=3600)
        self.runner.execguest("cd /root/cloudstack.git && git checkout %s" % self.gitBranch)
        self.runner.execguest("cd /root/cloudstack.git && git pull")

        patch = xenrt.TEC().lookup("MARVIN_PATCH", None)
        if patch:
            self.runner.execguest("wget -O /root/cs.patch %s" % patch)
            self.runner.execguest("cd /root/cloudstack.git && patch -p1 < /root/cs.patch")

class _TCRemoteNoseBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        self.runner = self.getGuest(self.args.get("runner", "CS-Marvin"))
        self.toolstack = self.getDefaultToolstack()

class TCRemoteNoseSetup(_TCRemoteNoseBase):
    def run(self, arglist):
        sftp = self.runner.sftpClient()
        sftp.copyTreeTo("%s/data/tests/marvin" % xenrt.TEC().lookup("XENRT_BASE"), "/root/marvin-scripts")
        try:
            testData = json.loads(self.runner.execguest("/root/marvin-scripts/getDefaultConfig.py"))
        except:
            xenrt.TEC().logverbose("test_data not supported")
        else:
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
            testData['hypervisor'] = self.args['hypervisor']
            testData['small']['hypervisor'] = self.args['hypervisor']
            testData['medium']['hypervisor'] = self.args['hypervisor']
            testData['server']['hypervisor'] = self.args['hypervisor']
            testData['server_without_disk']['hypervisor'] = self.args['hypervisor']
            with open("%s/testdata.cfg" % xenrt.TEC().getLogdir(), "w") as f:
                f.write(json.dumps(testData, indent=2))
    
            sftp.copyTo("%s/testdata.cfg" % xenrt.TEC().getLogdir(), "/root/testdata.cfg")
            self.toolstack.marvinCfg['TestData'] = {'Path': "/root/testdata.cfg"}

        with open("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "w") as f:
            f.write(json.dumps(self.toolstack.marvinCfg, indent=2))

        sftp.copyTo("%s/marvin.cfg" % xenrt.TEC().getLogdir(), "/root/marvin.cfg")

class TCRemoteNose(_TCRemoteNoseBase):
    def run(self, arglist):
        self.workdir = self.runner.execguest("mktemp -d /root/marvinXXXXXXXX").strip()
        
        self.runner.execguest("nosetests -v --logging-level=DEBUG --log-folder-path=%s --with-marvin --marvin-config=/root/marvin.cfg --with-xunit --xunit-file=%s/results.xml --hypervisor=%s -a tags=%s /root/cloudstack.git/%s" %
                   (self.workdir,
                    self.workdir,
                    self.args['hypervisor'],
                    self.args['tags'],
                    self.args['file']), timeout=14400, retval="code")

        sftp = self.runner.sftpClient()
        logdir = xenrt.TEC().getLogdir()
        sftp.copyTreeFrom(self.workdir, logdir + '/marvin')
        d = xml.dom.minidom.parse("%s/marvin/results.xml" % logdir)

        suites = d.getElementsByTagName("testsuite")
        for s in suites:
            tcs = s.getElementsByTagName("testcase")
            for t in tcs:
                result = xenrt.RESULT_PASS
                if t.getElementsByTagName("failure"):
                    result = xenrt.RESULT_FAIL
                elif t.getElementsByTagName("error"):
                    result = xenrt.RESULT_FAIL
                elif t.getElementsByTagName("skipped"):
                    result = xenrt.RESULT_SKIPPED
                self.testcaseResult(t.getAttribute("classname"), t.getAttribute("name"), result)


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
