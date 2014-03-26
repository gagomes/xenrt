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
        self.cmdPrefix = 'cloudstack'

    def getLogs(self, destDir):
        sftp = self.place.sftpClient()
        manSvrLogsLoc = self.place.execcmd('find /var/log -type f -name management-server.log').strip()
        sftp.copyTreeFrom(os.path.dirname(manSvrLogsLoc), destDir)
        sftp.close()
 
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
            self.place.execcmd('cd %s && ./install.sh -m' % (installDir))

            self.setupManagementServerDatabase()
            self.setupManagementServer()

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
        placeArtifactDir = self.getLatestMSArtifactsFromJenkins()

        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd('yum -y install %s' % (os.path.join(placeArtifactDir, '*')))

        self.setupManagementServerDatabase()
        self.setupManagementServer()

