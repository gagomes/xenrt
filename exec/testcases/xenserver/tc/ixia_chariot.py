import xenrt
from xenrt.lazylog import step
from xenrt import util
from xenrt import ixiachariot
from xenrt import resources


class XenRTLock(object):
    def __init__(self):
        self.resource = None

    def acquire(self):
        self.resource = resources.GlobalResource('IXIA')

    def release(self):
        self.resource.release()


class IxiaChariotBasedTest(xenrt.TestCase):

    def executeOnChariotConsole(self, cmd):
        return_code = xenrt.ssh.SSH(
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

        xenrt.log(return_code)
        return return_code

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
        args = self.parseArgsKeyValue(arglist)
        # numThreads specifies the number of tcp streams between the two end points. By Default it is set to 1
        numThreads = int(args.get("num_threads", "1"))
        distmasterBase = xenrt.TEC().lookup("TEST_TARBALL_BASE")
        endpoint0 = ixiachariot.createEndpoint(
            args['endpointSpec0'], distmasterBase, self)
        endpoint1 = ixiachariot.createEndpoint(
            args['endpointSpec1'], distmasterBase, self)

        endpoint0.install(self.distmasterDir)
        endpoint1.install(self.distmasterDir)

        ixiaTest = args['ixiaTestFile']
        jobId = xenrt.GEC().jobid()

        pairTest = ixiachariot.PairTest(
            endpoint0.ipAddress, endpoint1.ipAddress, ixiaTest, jobId)

        console = ixiachariot.Console(
            self.consoleAddress, self.executeOnChariotConsole, XenRTLock())

        step("IXIA console is going to run %d TCP streams between the end points." % numThreads)
        for cmd in pairTest.getCommands(numThreads):
            console.run(cmd)

        logDir = xenrt.TEC().getLogdir()

        sftpclient = xenrt.ssh.SFTPSession(
            self.consoleAddress,
            username=self.consoleUser)

        sftpclient.copyTreeFrom(pairTest.workingDir, logDir + '/results')
        sftpclient.close()
