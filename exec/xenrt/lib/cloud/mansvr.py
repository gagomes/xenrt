import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
    import jenkinsapi
    from jenkinsapi.jenkins import Jenkins
except ImportError:
    pass

__all__ = ["ManagementServer"]

class ManagementServer(object):
    def __init__(self, place):
        self.place = place
        self.isCCP = True
        self.__version = None
        if self.version in ['3.0.7']:
            self.cmdPrefix = 'cloud'
        else:
            self.cmdPrefix = 'cloudstack'

    def getLogs(self, destDir):
        sftp = self.place.sftpClient()
        manSvrLogsLoc = self.place.execcmd('find /var/log -type d -name management | grep %s' % (self.cmdPrefix)).strip()
        sftp.copyTreeFrom(os.path.dirname(manSvrLogsLoc), destDir)
        sftp.close()

    def lookup(self, key, default=None):
        """Perform a version based lookup on cloud config data"""
        lookupKeys = ['CLOUD_CONFIG', self.version]
        if isinstance(key, list):
            lookupKeys += key
        else:
            lookupKeys.append(key)
        return xenrt.TEC().lookup(lookupKeys, default)

    def checkManagementServerHealth(self):
        managementServerOk = False
        maxRetries = 2
        maxReboots = 2
        reboots = 0
        while(reboots < maxReboots and not managementServerOk):
            retries = 0
            while(retries < maxRetries):
                retries += 1
                xenrt.TEC().logverbose('Check Management Server Ports: Attempt: %d of %d' % (retries, maxRetries))

                # Check the management server ports are reachable
                port = 8080
                try:
                    urllib.urlopen('http://%s:%s' % (self.place.getIP(), port))
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (self.place.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)
                    continue

                port = 8096
                try:
                    urllib.urlopen('http://%s:%s' % (self.place.getIP(), port))
                    managementServerOk = True
                    break
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (self.place.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)

            if not managementServerOk:
                xenrt.TEC().logverbose('Restarting Management Server: Attempt: %d of %d' % (reboots+1, maxReboots))
                self.place.execcmd('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
                self.restart(checkHealth=False, startStop=(reboots > 0))
                reboots += 1

        if not managementServerOk:
            # Store the MS logs
            mgmtSvrHealthCheckFailedLogDir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'healthFailure')
            if not os.path.exists(mgmtSvrHealthCheckFailedLogDir):
                os.makedirs(mgmtSvrHealthCheckFailedLogDir)
            self.getLogs(mgmtSvrHealthCheckFailedLogDir)
            raise xenrt.XRTFailure('Management Server not reachable')

    def restart(self, checkHealth=True, startStop=False):
        if not startStop:
            self.place.execcmd('service %s-management restart' % (self.cmdPrefix))
        else:
            self.place.execcmd('service %s-management stop' % (self.cmdPrefix))
            xenrt.sleep(120)
            self.place.execcmd('service %s-management start' % (self.cmdPrefix))
        
        if checkHealth:
            self.checkManagementServerHealth()

    def setupManagementServerDatabase(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            # Configure SELinux
            self.place.execcmd("sed -i 's/SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config")
            self.place.execcmd('setenforce Permissive')

            self.place.execcmd('yum -y install mysql-server mysql')
            self.place.execcmd('service mysqld restart')

            self.place.execcmd('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
            self.place.execcmd('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
            self.place.execcmd('mysqladmin -u root password xensource')
            self.place.execcmd('service mysqld restart')

            setupDbLoc = self.place.execcmd('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
            self.place.execcmd('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

    def setupManagementServer(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')
            setupMsLoc = self.place.execcmd('find /usr/bin -name %s-setup-management' % (self.cmdPrefix)).strip()
            self.place.execcmd(setupMsLoc)

            self.place.execcmd('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')

            templateSubsts = {"http://download.cloud.com/templates/builtin/centos56-x86_64.vhd.bz2": "%s/cloudTemplates/centos56-x86_64.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")}

            for t in templateSubsts.keys():
                self.place.execcmd("""mysql -u cloud --password=cloud --execute="UPDATE cloud.vm_template SET url='%s' WHERE url='%s'" """ % (templateSubsts[t], t))
        self.restart()
        xenrt.GEC().dbconnect.jobUpdate("CLOUD_MGMT_SVR_IP", self.place.getIP())
        xenrt.TEC().registry.toolstackPut("cloud", xenrt.lib.cloud.CloudStack(place=self.place))

    def installApacheProxy(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd("yum -y install httpd")
            self.place.execcmd("echo ProxyPass /client http://127.0.0.1:8080/client > /etc/httpd/conf.d/cloudstack.conf")
            self.place.execcmd("echo ProxyPassReverse /client http://127.0.0.1:8080/client >> /etc/httpd/conf.d/cloudstack.conf")
            self.place.execcmd("echo RedirectMatch ^/$ /client >> /etc/httpd/conf.d/cloudstack.conf")
            self.place.execcmd("chkconfig httpd on")
            self.place.execcmd("service httpd restart")

    def checkJavaVersion(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            if self.version in ['4.4', 'master']:
                # Check if Java 1.7.0 is installed
                self.place.execcmd('yum -y install java*1.7*')
                if not '1.7.0' in self.place.execcmd('java -version').strip():
                    javaDir = self.place.execcmd('update-alternatives --display java | grep "^/usr/lib.*1.7.0"').strip()
                    self.place.execcmd('update-alternatives --set java %s' % (javaDir.split()[0]))

                if not '1.7.0' in self.place.execcmd('java -version').strip():
                    raise xenrt.XRTError('Failed to install and select Java 1.7')

    def installCloudPlatformManagementServer(self):
        if self.place.arch != 'x86-64':
            raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

        manSvrInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
        if not manSvrInputDir:
            raise xenrt.XRTError('Location of management server build not specified')

        if self.place.distro in ['rhel63', 'rhel64', ]:
            manSvrFile = xenrt.TEC().getFile(manSvrInputDir)
            webdir = xenrt.WebDirectory()
            webdir.copyIn(manSvrFile)
            manSvrUrl = webdir.getURL(os.path.basename(manSvrFile))

            self.place.execcmd('wget %s -O cp.tar.gz' % (manSvrUrl))
            webdir.remove()
            self.place.execcmd('mkdir cloudplatform')
            self.place.execcmd('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            installDir = os.path.dirname(self.place.execcmd('find cloudplatform/ -type f -name install.sh'))
            self.place.execcmd('cd %s && ./install.sh -m' % (installDir), timeout=600)

        self.checkJavaVersion()
        self.setupManagementServerDatabase()
        self.setupManagementServer()
        self.installApacheProxy()

    def getLatestMSArtifactsFromJenkins(self):
        jenkinsUrl = 'http://jenkins.buildacloud.org'

        j = Jenkins(jenkinsUrl)
        # TODO - Add support for getting a specific build (not just the last good one)?
        branch = xenrt.TEC().lookup('ACS_BRANCH', 'master')
        if not branch in j.views.keys():
            raise xenrt.XRTError('Could not find ACS_BRANCH %s' % (branch))

        view = j.views[branch]
        xenrt.TEC().logverbose('View %s has jobs: %s' % (branch, view.keys()))

        jobKey = None
        if 'package-%s-%s' % (self.place.distro, branch) in view.keys():
            jobKey = 'package-%s-%s' % (self.place.distro, branch)
        else:
            packageType = 'deb'
            if self.place.distro.startswith('rhel') or self.place.distro.startswith('centos'):
                packageType = 'rpm'

            if 'package-%s-%s' % (packageType, branch) in view.keys():
                jobKey = 'package-%s-%s' % (packageType, branch)

            if 'cloudstack-%s-package-%s' % (branch, packageType) in view.keys():
                jobKey = 'cloudstack-%s-package-%s' % (branch, packageType)

        if not jobKey:
            raise xenrt.XRTError('Failed to find a jenkins job for creating MS package')
        else:
            xenrt.TEC().logverbose('Using jobKey: %s' % (jobKey))

        lastGoodBuild = view[jobKey].get_last_good_build()
        xenrt.GEC().dbconnect.jobUpdate("ACSINPUTDIR", lastGoodBuild.baseurl)
        artifactsDict = lastGoodBuild.get_artifact_dict()

        artifactKeys = filter(lambda x:x.startswith('cloudstack-management-') or x.startswith('cloudstack-common-') or x.startswith('cloudstack-awsapi-'), artifactsDict.keys())

        placeArtifactDir = '/tmp/csartifacts'
        self.place.execcmd('mkdir %s' % (placeArtifactDir))

        xenrt.TEC().logverbose('Using CloudStack Build: %d, Timestamp %s' % (lastGoodBuild.get_number(), lastGoodBuild.get_timestamp().strftime('%d-%b-%y %H:%M:%S')))
        
        # Copy artifacts into the temp directory
        localFiles = [xenrt.TEC().getFile(artifactsDict[x].url) for x in artifactKeys]

        webdir = xenrt.WebDirectory()
        for f in localFiles:
            webdir.copyIn(f)
            self.place.execcmd('wget %s -P %s' % (webdir.getURL(os.path.basename(f)), placeArtifactDir))

        webdir.remove()

        return placeArtifactDir

    def installCloudStackManagementServer(self):
        self.isCCP = False
        placeArtifactDir = self.getLatestMSArtifactsFromJenkins()
        
        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd('yum -y install %s' % (os.path.join(placeArtifactDir, '*')), timeout=600)

        self.checkJavaVersion()
        self.setupManagementServerDatabase()
        self.setupManagementServer()

    @property
    def version(self):
        # This method determines the version number of CloudStack or CloudPlatform being used.
        # TODO - Need to find a better way of doing this
        if not self.__version:
            versionKeys = xenrt.TEC().lookup('CLOUD_CONFIG').keys()
            xenrt.TEC().logverbose('XenRT supports the following MS versions' % (versionKeys))
            # Try and get the version from the MS database
            dbVersionMatches = []
            installVersionMatches = []
            try:
                dbVersion = self.place.execcmd('mysql -u cloud --password=cloud -s -N --execute="SELECT version from cloud.version ORDER BY id DESC LIMIT 1"').strip()
                xenrt.TEC().logverbose('Found MS version %s from database' % (dbVersion))
                dbVersionMatches = filter(lambda x:x in dbVersion, versionKeys)
            except Exception, e:
                xenrt.TEC().logverbose('Failed to get MS version from database: %s' % (str(e)))

            installVersionStr = xenrt.TEC().lookup("CLOUDINPUTDIR", xenrt.TEC().lookup('ACS_BRANCH', None))
            if installVersionStr:
                installVersionMatches = filter(lambda x:x in installVersionStr, versionKeys)

            xenrt.TEC().logverbose('XenRT support MS versions matching DB version: %s' % (dbVersionMatches))
            xenrt.TEC().logverbose('XenRT support MS versions matching install version: %s' % (installVersionMatches))

            versionMatches = list(set(dbVersionMatches + installVersionMatches))
            if len(versionMatches) == 1:
                self.__version = versionMatches[0]
            elif len(versionMatches) == 0:
                xenrt.TEC().warning('Management Server version could not be determined')
            else:
                raise xenrt.XRTError('Multiple version detected: %s' % (versionMatches))

            xenrt.TEC().comment('Using Management Server version: %s' % (self.__version))
        return self.__version

    def preManagementServerInstall(self):
        # Check correct Java version is installed (installs correct version if required)
        self.checkJavaVersion()

    def postManagementServerInstall(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            if not self.isCCP and self.version in ['4.4', 'master']:
                self.place.execcmd('wget http://download.cloud.com.s3.amazonaws.com/tools/vhd-util -P /usr/share/cloudstack-common/scripts/vm/hypervisor/xenserver/')
                self.place.execcmd('chmod 755 /usr/share/cloudstack-common/scripts/vm/hypervisor/xenserver/vhd-util')

    def installCloudManagementServer(self):
        self.preManagementServerInstall()

        if xenrt.TEC().lookup("CLOUDINPUTDIR", None) != None:
            self.installCloudPlatformManagementServer()
        elif xenrt.TEC().lookup('ACS_BRANCH', None) != None:
            self.installCloudStackManagementServer()
        else:
            raise xenrt.XRTError('CLOUDINPUTDIR and ACS_BRANCH options are not defined')

        self.postManagementServerInstall()

