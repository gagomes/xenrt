import xenrt
from xenrt import util
from xenrt import ixiachariot


class IxiaChariotBasedTest(xenrt.TestCase):

    def executeOnChariotConsole(self, cmd):
        result = xenrt.ssh.SSH(
            self.consoleAddress,
            cmd,
            username=self.consoleUser,
            level=xenrt.RC_FAIL,
            timeout=300,
            idempotent=False,
            newlineok=False,
            getreply=True,
            nolog=False,
            useThread=False,
            outfile=None,
            password=None)

        xenrt.log(result)

    def getConfigValue(self, key):
        return xenrt.TEC().lookup(["IXIA_CHARIOT", key])

    @property
    def consoleAddress(self):
        return self.getConfigValue("CONSOLE_ADDRESS")

    @property
    def consoleUser(self):
        return self.getConfigValue("CONSOLE_USER")

    @property
    def distmasterDir(self):
        return self.getConfigValue("DISTMASTER_DIR")

    def run(self, arglist=None):
        argDict = util.strlistToDict(arglist)
        distmasterBase = xenrt.TEC().lookup("TEST_TARBALL_BASE")

        endpoint0 = ixiachariot.createEndpoint(
            argDict['endpointSpec0'], distmasterBase, self)
        endpoint1 = ixiachariot.createEndpoint(
            argDict['endpointSpec1'], distmasterBase, self)

        endpoint0.install(self.distmasterDir)
        endpoint1.install(self.distmasterDir)

        ixiaTest = argDict['ixiaTestFile']
        jobId = xenrt.GEC().jobid()

        pairTest = ixiachariot.PairTest(
            endpoint0.ipAddress, endpoint1.ipAddress, ixiaTest, jobId)

        for cmd in pairTest.getCommands():
            self.executeOnChariotConsole(cmd)

        logdir = xenrt.TEC().getLogdir()

        sftpclient = xenrt.ssh.SFTPSession(
            self.consoleAddress,
            username=self.consoleUser)

        sftpclient.copyTreeFrom(pairTest.workingDir, logdir + '/results')
        sftpclient.close()
