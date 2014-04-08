import textwrap


def createEndpoint(endpointSpec, distmasterBase, hostRegistry):
    host, guestName = endpointSpec.split('/')
    guest = hostRegistry.getHost(host).getGuest(guestName)
    return WindowsEndpoint(guest, distmasterBase)


class WindowsEndpoint(object):

    def __init__(self, guest, distmasterBase):
        self.guest = guest
        self.distmasterBase = distmasterBase

    @property
    def installer(self):
        bitCount = '64' if self.guest.xmlrpcGetArch() == 'amd64' else '32'

        if float(self.guest.xmlrpcWindowsVersion()) < 6.0:
            productName = 'windows'
        else:
            productName = 'vista'

        return 'pe{productName}{bitCount}_730.exe'.format(
            productName=productName, bitCount=bitCount)

    def install(self, distmaster_dir):
        tmpDir = self.guest.xmlrpcTempDir()

        self.guest.xmlrpcUnpackTarball(
            '/'.join([self.distmasterBase, distmaster_dir + '.tgz']),
            tmpDir
        )

        endpointInstaller = '\\'.join(
            [tmpDir, distmaster_dir, self.installer])

        self.guest.xmlrpcExec("{0} /S /v/qn".format(endpointInstaller))

    @property
    def ipAddress(self):
        return self.guest.getIP()


class PairTest(object):
    ROOTWINPATH = r'C:\\tests'

    def __init__(self, endpoint1, endpoint2, testName, jobId):
        self.endpoint1 = endpoint1
        self.endpoint2 = endpoint2
        self.testName = testName
        self.jobId = jobId

    @property
    def originalTestWinPath(self):
        return r'"{ROOTWINPATH}\\{testName}"'.format(
            testName=self.testName,
            ROOTWINPATH=self.ROOTWINPATH)

    @property
    def cloneWinPath(self):
        return r'"{ROOTWINPATH}\\{jobId}\\clone"'.format(
            testName=self.testName,
            jobId=self.jobId,
            ROOTWINPATH=self.ROOTWINPATH)

    @property
    def testWinPath(self):
        return r'"{ROOTWINPATH}\\{jobId}\\test.tst"'.format(
            jobId=self.jobId,
            ROOTWINPATH=self.ROOTWINPATH)

    @property
    def resultWinPath(self):
        return r'"{ROOTWINPATH}\\{jobId}\\result.tst"'.format(
            jobId=self.jobId,
            ROOTWINPATH=self.ROOTWINPATH)

    @property
    def resultCSVWinPath(self):
        return r'"{ROOTWINPATH}\\{jobId}\\result.csv"'.format(
            jobId=self.jobId,
            ROOTWINPATH=self.ROOTWINPATH)

    @property
    def workingDir(self):
        return '/cygdrive/c/tests/{jobId}'.format(jobId=self.jobId)

    def getCommands(self):
        commands = [
            'mkdir {workingDir}',
            'echo "1 {endpoint1} {endpoint2}" > {workingDir}/clone',
            '{clonetst} {originalTestWinPath} {cloneWinPath} {testWinPath}',
            '{runtst} {testWinPath} {resultWinPath}',
            '{fmttst} {resultWinPath} -v {resultCSVWinPath}',
        ]

        params = dict(
            workingDir=self.workingDir,
            endpoint1=self.endpoint1,
            endpoint2=self.endpoint2,
            clonetst='"/cygdrive/c/Program Files/Ixia/IxChariot/clonetst"',
            runtst='"/cygdrive/c/Program Files/Ixia/IxChariot/runtst"',
            fmttst='"/cygdrive/c/Program Files/Ixia/IxChariot/fmttst"',
            originalTestWinPath=self.originalTestWinPath,
            cloneWinPath=self.cloneWinPath,
            testWinPath=self.testWinPath,
            resultWinPath=self.resultWinPath,
            resultCSVWinPath=self.resultCSVWinPath,
        )

        return [command.format(**params) for command in commands]
