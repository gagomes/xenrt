import xenrt
from xenrt import util
from xenrt import ixiachariot


class IxiaChariotBasedTest(xenrt.TestCase):

    def executeOnChariotConsole(self, cmd):
        result = xenrt.ssh.SSH(
            ixiachariot.CONSOLE_ADDRESS,
            cmd,
            username=ixiachariot.CONSOLE_USER,
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

    def run(self, arglist=None):
        argDict = util.strlistToDict(arglist)
        distmasterBase = xenrt.TEC().lookup("TEST_TARBALL_BASE")

        endpoint0 = ixiachariot.createEndpoint(
            argDict['endpointSpec0'], distmasterBase, self)
        endpoint1 = ixiachariot.createEndpoint(
            argDict['endpointSpec1'], distmasterBase, self)

        endpoint0.install()
        endpoint1.install()

        ixiaTest = argDict['ixiaTestFile']
        jobId = xenrt.GEC().jobid()

        pairTest = ixiachariot.PairTest(
            endpoint0.ipAddress, endpoint1.ipAddress, ixiaTest, jobId)

        for cmd in pairTest.getCommands():
            self.executeOnChariotConsole(cmd)

        logdir = xenrt.TEC().getLogdir()

        sftpclient = xenrt.ssh.SFTPSession(
            ixiachariot.CONSOLE_ADDRESS,
            username=ixiachariot.CONSOLE_USER)

        sftpclient.copyTreeFrom(pairTest.workingDir, logdir + '/results')
        sftpclient.close()
