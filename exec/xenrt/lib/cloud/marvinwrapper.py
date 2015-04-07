import xenrt
import logging
import os, urllib, glob
from datetime import datetime
import shutil
import tarfile
import inspect

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin import configGenerator
    from marvin.cloudstackAPI import *
    from xenrt.lib.cloud.marvindeploy import MarvinDeployer
except ImportError:
    pass

__all__ = ["MarvinApi"]

class XenRTLogStream(object):
    def write(self, data):
        xenrt.TEC().logverbose(data.rstrip())

    def flush(self):
        pass

class CloudApi(object):
    def __init__(self, apiClient):
        self.__apiClient = apiClient

    def __command(self, command, **kwargs):
        """Wraps a generic command. Paramters are command - name of the command (e.g. "listHosts"), then optional arguments of the command parameters. Returns the response class"""
        # First we create the command

        if command.endswith("Async"):
            command = command[:-5]
            async = True
        else:
            async = False

        cls = eval("%s.%sCmd" % (command, command))
        cmd = cls()
        # Then iterate through the parameters
        for k in kwargs.keys():
            # If the command doesn't already have that member, it's not a valid parameter
            if not cmd.__dict__.has_key(k):
                raise xenrt.XRTError("Command does not have parameter %s" % k)
            # Set the member value
            cmd.__dict__[k] = kwargs[k]
        
        # Then run the command
        if async:
            if not cmd.isAsync=="true":
                raise xenrt.XRTError("Command is not an asynchronous command")
            cmd.isAsync="false"
            return getattr(self.__apiClient, command)(cmd).jobid
        else:
            return getattr(self.__apiClient, command)(cmd)

    def checkAsyncJob(self, jobid):
        status = self.queryAsyncJobResult(jobid=jobid)
        if status.jobstatus == 0:
            return None
        elif status.jobstatus == 2:
            raise xenrt.XRTFailure("Cloudstack job failed with %s" % str(status.jobresult))
        else:
            return status.jobresult

    def pollAsyncJob(self, jobid, timeout=1800):
        deadline = xenrt.timenow() + timeout
        while xenrt.timenow() <= deadline:
            result = self.checkAsyncJob(jobid)
            if result:
                return result
            xenrt.sleep(15)
        raise xenrt.XRTError("Timed out waiting for response")

    def __getattr__(self, attr):
        def wrapper(**kwargs):
            return self.__command(attr, **kwargs)
        return wrapper

class MarvinApi(object):
    MARVIN_LOGGER = 'MarvinLogger'
    
    MS_USERNAME = 'admin'
    MS_PASSWORD = 'password'

    def __init__(self, mgtSvr):
        self.__testClientObj = None
        self.mgtSvr = mgtSvr
        self.xenrtStream = XenRTLogStream()
        logFormat = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        self.logger = logging.getLogger(self.MARVIN_LOGGER)
        if len(self.logger.handlers) == 0:
            # Add a stream handler to the logger and initialise it
            self.logger.setLevel(logging.DEBUG)
            stream = logging.StreamHandler(stream=self.xenrtStream)
            stream.setLevel(logging.DEBUG)
            stream.setFormatter(logFormat)
            self.logger.addHandler(stream)

        self.mgtSvrDetails = configGenerator.managementServer()
        self.mgtSvrDetails.mgtSvrIp = mgtSvr.place.getIP()
        self.mgtSvrDetails.user = self.MS_USERNAME
        self.mgtSvrDetails.passwd = self.MS_PASSWORD
        self.dbDetails = configGenerator.dbServer()
        self.dbDetails.dbSvr = mgtSvr.place.getIP()

        self.__apiClient = self.__testClient.getApiClient()
        self.__userApiClientObj = None
        self.cloudApi = CloudApi(self.__apiClient)

    @property
    def __testClient(self):
        if not self.__testClientObj:
            if hasattr(cloudstackTestClient, 'cloudstackTestClient'):
                testCliCls = cloudstackTestClient.cloudstackTestClient
            elif hasattr(cloudstackTestClient, 'CSTestClient'):
                testCliCls = cloudstackTestClient.CSTestClient
            else:
                raise xenrt.XRTError('Unknown Marvin test client class')
            xenrt.TEC().logverbose('Using Marvin Test Client class: %s' % (testCliCls))

            testCliArgs = inspect.getargspec(testCliCls.__init__).args
            xenrt.TEC().logverbose('Marvin Test Client class has constructor args: %s' % (testCliArgs))

            if 'mgtSvr' in testCliArgs:
                # This is 3.x Marvin
                self.__testClientObj = testCliCls(mgtSvr=self.mgtSvr.place.getIP(), logging=self.logger)
            elif 'mgmtDetails' in testCliArgs:
                # This is 4.2 / 4.3 Marvin
                self.__testClientObj = testCliCls(mgmtDetails=self.mgtSvrDetails, dbSvrDetails=None, logger=self.logger)
            elif 'mgmt_details' in testCliArgs:
                # This is 4.4+ Marvin
                self.__testClientObj = testCliCls(mgmt_details=self.mgtSvrDetails, dbsvr_details=self.dbDetails, logger=self.logger)
                self.__testClientObj.createTestClient()
            else:
                raise xenrt.XRTError('Unable to determine Marvin Test Client constructor signature')
        return self.__testClientObj

    @property
    def __userApiClient(self):
        if not self.__userApiClientObj:
            if not hasattr(self.__apiClient, "hypervisor"):
                self.__apiClient.hypervisor = None
            self.__userApiClientObj = self.__testClient.createUserApiClient("admin", None)
        return self.__userApiClientObj

    def signCommand(self, params):
        params["apikey"] = self.__userApiClient.connection.apiKey
        params['signature'] = self.__userApiClient.connection.sign(params)
        return params

    def marvinDeployerFactory(self):
        return MarvinDeployer(self.mgtSvrDetails.mgtSvrIp, self.logger, "root", self.mgtSvr.place.password, self.__testClient)

    def getCloudGlobalConfig(self, name):
        configSetting = self.cloudApi.listConfigurations(name=name)
        if configSetting == None or len(configSetting) == 0:
            raise xenrt.XRTError('Could not find setting: %s' % (name))
        elif len(configSetting) > 1:
            configSetting = filter(lambda x:x.name == name, configSetting)
        xenrt.TEC().logverbose('Current value for setting: %s is %s' % (name, configSetting[0].value))
        return configSetting[0].value

    def setCloudGlobalConfig(self, name, value, restartManagementServer=False):
        if value != self.getCloudGlobalConfig(name):
            self.cloudApi.updateConfiguration(name=name, value=value)
            if restartManagementServer:
                self.mgtSvr.restart()
        else:
            xenrt.TEC().logverbose('Value of setting %s already %s' % (name, value))

    def waitForSystemVmsReady(self):
        deadline = xenrt.timenow() + 1200

        while True:
            systemvms = self.cloudApi.listSystemVms() or []
            startingvms = [x for x in systemvms if x.state == "Starting"]
            systemvmhosts = [x for x in self.cloudApi.listHosts() or [] if x.name in [y.name for y in systemvms]]
            if systemvmhosts: # At least one host object has been created
                downhosts = [x for x in systemvmhosts if x.state != "Up"]
                if not downhosts and not startingvms:
                    # All up, complete
                    xenrt.TEC().logverbose("All System VMs ready")
                    return
                else:
                    if downhosts:
                        xenrt.TEC().logverbose("%s not up" % ", ".join([x.name for x in downhosts]))
                    if startingvms:
                        xenrt.TEC().logverbose("%s starting" % ", ".join([x.name for x in startingvms]))
            else:
                xenrt.TEC().logverbose("No system VMs present yet")
            
            if xenrt.timenow() > deadline:
                raise xenrt.XRTError("Waiting for system VMs timed out")
            xenrt.sleep(15)

    def waitForBuiltInTemplatesReady(self):
        templateList = [x for x in self.cloudApi.listTemplates(templatefilter='all') if x.templatetype == "BUILTIN"]
        map(lambda x:self.waitForTemplateReady(name=x.name, zoneId=x.zoneid), templateList)

    def waitForTemplateReady(self, name, zoneId=None):
        templateReady = False
        startTime = datetime.now()
        timeout = 1800
        while((datetime.now() - startTime).seconds < timeout):
            templateList = self.cloudApi.listTemplates(templatefilter='all', name=name, zoneid=zoneId)
            if not templateList:
                xenrt.TEC().logverbose('Template %s not found' % (name))
            elif len(templateList) == 1:
                xenrt.TEC().logverbose('Template %s, is ready: %s, status: %s' % (name, templateList[0].isready, templateList[0].status))
                templateReady = templateList[0].isready
                if templateReady:
                    break
                if templateList[0].hypervisor.lower() == "hyperv":
                    # CS-20595 - Hyper-V downloads are very slow
                    timeout = 10800
            else:
                raise xenrt.XRTFailure('>1 template found with name %s' % (name))

            xenrt.sleep(60)

        if not templateReady:
            raise xenrt.XRTFailure('Timeout expired waiting for template %s' % (name))

        xenrt.TEC().logverbose('Template %s ready after %d seconds' % (name, (datetime.now() - startTime).seconds))

    def copySystemTemplatesToSecondaryStorage(self, storagePath, provider):
        # Load templates for this version
        templates = self.mgtSvr.lookup("SYSTEM_TEMPLATES", None)
        if not templates:
            raise xenrt.XRTError('Failed to find system templates')

        # Check if any non-default system templates have been specified
        # These should be added in the form -D CLOUD_TMPLT/hypervisor=url
        sysTemplates = xenrt.TEC().lookup("CLOUD_TMPLT", {})
        for s in sysTemplates:
            templates[s] = sysTemplates[s]

        # Legacy XenServer template support
        sysTemplateSrcLocation = xenrt.TEC().lookup("CLOUD_SYS_TEMPLATE", None)
        if sysTemplateSrcLocation:
            xenrt.TEC().warning("Use of CLOUD_SYS_TEMPLATE is deprecated, use CLOUD_SYS_TEMPLATES/xenserver instead")
            templates['xenserver'] = sysTemplateSrcLocation

        hvlist = xenrt.TEC().lookup("CLOUD_REQ_SYS_TMPLS", None)
        if hvlist:
            hvlist = hvlist.split(",")
        else:
            hvlist = []
        for t in templates.keys():
            if t not in hvlist:
                del templates[t]
        
        xenrt.TEC().logverbose('Using System Templates: %s' % (templates))
        webdir = xenrt.WebDirectory()
        if provider == 'NFS':
            self.mgtSvr.place.execcmd('mount %s /media' % (storagePath))
        elif provider == 'SMB':
            ad = xenrt.getADConfig()
            self.mgtSvr.place.execcmd('mount -t cifs %s /media -o user=%s,password=%s,domain=%s' % (storagePath, ad.adminUser, ad.adminPassword, ad.domainName))
        installSysTmpltLoc = self.mgtSvr.place.execcmd('find / -name *install-sys-tmplt -ignore_readdir_race 2> /dev/null || true').strip()
        for hv in templates:
            templateFile = xenrt.TEC().getFile(templates[hv])
            xenrt.TEC().logverbose("Using %s system VM template %s (md5sum: %s)" % (hv, templates[hv], xenrt.command("md5sum %s" % templateFile)))
            if templateFile.endswith(".zip") and xenrt.TEC().lookup("WORKAROUND_CS22839", False, boolean=True):
                xenrt.TEC().warning("Using CS-22839 workaround")
                tempDir = xenrt.TEC().tempDir()
                xenrt.command("cd %s && unzip %s" % (tempDir, templateFile))
                dirContents = glob.glob("%s/*" % tempDir)
                if len(dirContents) != 1:
                    raise xenrt.XRTError("Unexpected contents of system template ZIP file")
                templateFile = dirContents[0]
            webdir.copyIn(templateFile) 
            templateUrl = webdir.getURL(os.path.basename(templateFile))

            if provider in ('NFS', 'SMB'):
                self.mgtSvr.place.execcmd('%s -m /media -u %s -h %s -F' % (installSysTmpltLoc, templateUrl, hv), timeout=60*60)

        if provider in ('NFS', 'SMB'):
            self.mgtSvr.place.execcmd('umount /media')
        webdir.remove()


from lxml import etree
import glob, shutil, os, re, json

class TCMarvinTestRunner(xenrt.TestCase):

    def generateMarvinTestConfig(self):
        self.marvinCfg = {}
        self.marvinCfg['dbSvr'] = {}
        self.marvinCfg['dbSvr']['dbSvr'] = self.marvinApi.mgtSvrDetails.mgtSvrIp
        self.marvinCfg['dbSvr']['passwd'] = 'cloud'
        self.marvinCfg['dbSvr']['db'] = 'cloud'
        self.marvinCfg['dbSvr']['port'] = 3306
        self.marvinCfg['dbSvr']['user'] = 'cloud'

        self.marvinCfg['mgtSvr'] = []
        self.marvinCfg['mgtSvr'].append({'mgtSvrIp': self.marvinApi.mgtSvrDetails.mgtSvrIp,
                                         'port'    : self.marvinApi.mgtSvrDetails.port})

        self.marvinCfg['zones'] = map(lambda x:x.__dict__, self.marvinApi.cloudApi.listZones())
        for zone in self.marvinCfg['zones']:
            zone['pods'] = map(lambda x:x.__dict__, self.marvinApi.cloudApi.listPods(zoneid=zone['id']))
            for pod in zone['pods']:
                pod['clusters'] = map(lambda x:x.__dict__, self.marvinApi.cloudApi.listClusters(podid=pod['id']))
                for cluster in pod['clusters']:
                    cluster['hosts'] = map(lambda x:x.__dict__, self.marvinApi.cloudApi.listHosts(clusterid=cluster['id']))
                    for host in cluster['hosts']:
                        host['username'] = 'root'
                        host['password'] = xenrt.TEC().lookup("ROOT_PASSWORD")
                        host['url'] = host['ipaddress']

        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        json.dump(self.marvinCfg, fh)
        fh.close()
        return fn

    def getTestsToExecute(self, nosetestSelectorStr, tagStr=None):
        noseTestList = xenrt.TEC().tempFile()
        tempLogDir = xenrt.TEC().tempDir()
        noseArgs = ['--with-marvin', '--marvin-config=%s' % (self.marvinConfigFile),
                    '--with-xunit', '--xunit-file=%s' % (noseTestList),
                    '--log-folder-path=%s' % (tempLogDir),
                    '--load',
                    nosetestSelectorStr,
                    '--collect-only']

        if tagStr:
            noseArgs.append(tagStr)

        xenrt.TEC().logverbose('Using nosetest args: %s' % (' '.join(noseArgs)))

        try:
            result = xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))
            xenrt.TEC().logverbose('Completed with result: %s' % (result))
        except Exception, e:
            xenrt.TEC().logverbose('Failed to get test information from nose - Exception raised: %s' % (str(e)))
            raise

        testData = open(noseTestList).read()
        treeData = etree.fromstring(testData)
        elements = treeData.getchildren()

        self.testsToExecute = map(lambda x:{ 'name': x.get('name'), 'classname': x.get('classname') }, elements)
        xenrt.TEC().logverbose('Found %d test-cases reported by nose' % (len(self.testsToExecute))) 

        map(lambda x:xenrt.TEC().logverbose('  Testcase: %s, Class path: %s' % (x['name'], x['classname'])), self.testsToExecute)
        failures = filter(lambda x:x['classname'] == 'nose.failure.Failure', self.testsToExecute)

        if len(self.testsToExecute) == 0:
            raise xenrt.XRTError('No nose tests found for %s with tags: %s' % (self.nosetestSelectorStr, self.noseTagStr))

        if len(failures) > 0:
            raise xenrt.XRTError('Nosetest lookup failed')

        testNames = map(lambda x:x['name'], self.testsToExecute)
        if len(testNames) != len(set(testNames)):
            raise xenrt.XRTError('Duplicate Marvin test names found')

    def getMarvinTestCode(self):
        localTestCodeDir = xenrt.TEC().tempDir()
        sourceLocation = xenrt.TEC().lookup('MARVIN_TEST_CODE_PATH', None)
        if not sourceLocation:
            # TODO - add logic to get correct code for SUT
            return '/local/scratch/cloud'

        if not sourceLocation:
            raise xenrt.XRTError('Failed to find source location for Marvin testcode')

        xenrt.TEC().logverbose('Using Marvin testcode from source location: %s' % (sourceLocation))
        sourceFile = xenrt.TEC().getFile(sourceLocation)
        if not sourceFile:
            raise xenrt.XRTError('Failed to getFile from %s' % (sourceLocation))
        
        if os.path.splitext(sourceFile)[1] == '.py':
            xenrt.TEC().logverbose('Moving single python file [%s] to test directory [%s]' % (sourceFile, localTestCodeDir)) 
            shutil.copy(sourceFile, localTestCodeDir)
            os.chmod(os.path.join(localTestCodeDir, os.path.basename(sourceFile)), 0o664)
        elif tarfile.is_tarfile(sourceFile):
            tf = tarfile.open(sourceFile)
            for tarInfo in tf:
                if os.path.splitext(tarInfo.name)[1] == '.py':
                    xenrt.TEC().logverbose('Extracting %s to test directory [%s]' % (tarInfo.name, localTestCodeDir))
                    tf.extract(tarInfo.name, path=localTestCodeDir)
        else:
            raise xenrt.XRTError('Invalid file type: %s (should be .py or tarball)' % (sourceFile))
            
        return localTestCodeDir

    def prepare(self, arglist):
        self.marvinTestCodePath = self.getMarvinTestCode()
        self.nosetestSelectorStr = self.marvinTestCodePath
        self.noseTagStr = None

        if self.marvinTestConfig != None:
            xenrt.TEC().logverbose('Using marvin test config: %s' % (self.marvinTestConfig))
            if self.marvinTestConfig.has_key('path') and self.marvinTestConfig['path'] != None:
                self.nosetestSelectorStr = os.path.join(self.marvinTestCodePath, self.marvinTestConfig['path'])

            if self.marvinTestConfig.has_key('cls') and self.marvinTestConfig['cls'] != None:
                self.nosetestSelectorStr += ':' + self.marvinTestConfig['cls']

            if self.marvinTestConfig.has_key('tags') and self.marvinTestConfig['tags'] != None and len(self.marvinTestConfig['tags']) > 0:
                self.noseTagStr = '-a "%s"' % (','.join(map(lambda x:'tags=%s' % (x), self.marvinTestConfig['tags'])))
                xenrt.TEC().logverbose('Using nose tag str: %s' % (self.noseTagStr))

        xenrt.TEC().logverbose('Using nose selector str: %s' % (self.nosetestSelectorStr))

        cloud = self.getDefaultToolstack()
        self.manSvr = cloud.mgtsvr
        self.marvinApi = cloud.marvin
        self.marvinConfigFile = self.generateMarvinTestConfig()

        self.getTestsToExecute(self.nosetestSelectorStr, self.noseTagStr)

        # Apply test configration
        self.marvinApi.setCloudGlobalConfig("network.gc.wait", "60")
        self.marvinApi.setCloudGlobalConfig("storage.cleanup.interval", "300")
        self.marvinApi.setCloudGlobalConfig("vm.op.wait.interval", "5")
        self.marvinApi.setCloudGlobalConfig("default.page.size", "10000")
        self.marvinApi.setCloudGlobalConfig("network.gc.interval", "60")
        self.marvinApi.setCloudGlobalConfig("workers", "10")
        self.marvinApi.setCloudGlobalConfig("account.cleanup.interval", "600")
        self.marvinApi.setCloudGlobalConfig("expunge.delay", "60")
        self.marvinApi.setCloudGlobalConfig("vm.allocation.algorithm", "random")
        self.marvinApi.setCloudGlobalConfig("expunge.interval", "60")
        self.marvinApi.setCloudGlobalConfig("expunge.workers", "3")
        self.marvinApi.setCloudGlobalConfig("check.pod.cidrs", "true")
        self.marvinApi.setCloudGlobalConfig("direct.agent.load.size", "1000", restartManagementServer=True)
        
        #Parse arglist from sequence file to set global settings requried for the particular testcase        
        for arg in arglist:
            if arg.startswith('globalconfig'):            
                config = eval(arg.split('=')[1])
                self.marvinApi.setCloudGlobalConfig(config['key'],config['value'] ,restartManagementServer=config['restartManagementServer'])
            else :
                raise xenrt.XRTError("Unknown arguments specified ")


    def writeRunInfoLog(self, testcaseName, runInfoFile):
        xenrt.TEC().logverbose('-------------------------- START MARVIN LOGS FOR %s --------------------------' % (testcaseName))
        searchStr = '- DEBUG - %s' % (testcaseName)
        for line in open(runInfoFile):
            if re.search(searchStr, line):
                xenrt.TEC().log(line)
        xenrt.TEC().logverbose('-------------------------- END MARVIN LOGS FOR %s --------------------------' % (testcaseName))

    def handleMarvinTestCaseFailure(self, testData, reasonData):
        reason = reasonData.get('type')
        message = reasonData.get('message')
        if reason == 'unittest.case.SkipTest':
            # TODO - should this fail the test?
            xenrt.TEC().warning('Marvin testcase %s was skipped for reason: %s' % (testData['name'], message))
        else:
            # TODO - do more checking of failure reason
            xenrt.TEC().logverbose('Marvin testcase %s failed/errored with reason: %s, message: %s' % (testData['name'], reason, message))
            raise xenrt.XRTFailure('Marvin testcase %s failed/errored with reason: %s, message: %s' % (testData['name'], reason, message))


    def marvinTestCase(self, testData, runInfoFile, resultData):
        self.writeRunInfoLog(testData['name'], runInfoFile)

        xenrt.TEC().logverbose('Test duration: %s (sec)' % (resultData.get('time')))
        childElements = resultData.getchildren()
        if len(childElements) > 0:
            for childElement in childElements:
                self.handleMarvinTestCaseFailure(testData, childElement)

    def run(self, arglist):
        tempLogDir = xenrt.TEC().tempDir()
        noseTestResults = xenrt.TEC().tempFile()
        noseArgs = ['-v',
                    '--logging-level=DEBUG',
                    '--log-folder-path=%s' % (tempLogDir),
                    '--with-marvin', '--marvin-config=%s' % (self.marvinConfigFile),
                    '--with-xunit', '--xunit-file=%s' % (noseTestResults),
                    '--load']

        if self.noseTagStr:
            noseArgs.append(self.noseTagStr)
        noseArgs.append(self.nosetestSelectorStr)

        xenrt.TEC().logverbose('Using nosetest args: %s' % (' '.join(noseArgs)))

        try:
            result = xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))
            xenrt.TEC().logverbose('Test(s) completed with result: %s' % (result))
        except Exception, e:
            xenrt.TEC().logverbose('Exception raised: %s' % (str(e)))

        testData = open(noseTestResults).read()
        xmlResultData = etree.fromstring(testData)

        if len(self.testsToExecute) != int(xmlResultData.get('tests')):
            xenrt.TEC().warning('Expected %d Marvin tests to be executed, Actual: %d' % (len(self.testsToExecute), int(xmlResultData.get('tests'))))

        xenrt.TEC().comment('Marvin tests executed: %s' % (xmlResultData.get('tests')))
        xenrt.TEC().comment('Marvin tests failed:   %s' % (xmlResultData.get('failures')))
        xenrt.TEC().comment('Marvin test errors:    %s' % (xmlResultData.get('errors')))
        xenrt.TEC().comment('Marvin tests skipped:  %s' % (xmlResultData.get('skipped')))

        logPathList = glob.glob(os.path.join(tempLogDir, '*', 'runinfo.txt'))
        if len(logPathList) != 1:
            xenrt.TEC().logverbose('%d Marvin log directories found' % (len(logPathList)))
            raise xenrt.XRTError('Unique Marvin log directory not found')

        runInfoFile = logPathList[0]
        logPath = os.path.dirname(runInfoFile)
        self.logsubdir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'marvintest')
        xenrt.TEC().logverbose('Add full test logs to path %s' % (self.logsubdir))
        shutil.copytree(logPath, self.logsubdir)

        for test in self.testsToExecute:
            resultDataList = filter(lambda x:x.get('name') == test['name'], xmlResultData.getchildren())
            if len(resultDataList) != 1:
                xenrt.TEC().logverbose('%d Marvin test results found for test %s' % (len(resultDataList), test['name']))
                raise xenrt.XRTError('Unique Marvin test result not found')

            self.runSubcase('marvinTestCase', (test, runInfoFile, resultDataList[0]), test['classname'], test['name'])

        self.manSvr.getLogs(self.logsubdir)

