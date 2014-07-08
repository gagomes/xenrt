import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    import jenkinsapi
    from jenkinsapi.jenkins import Jenkins
except ImportError:
    pass

__all__ = ["ManagementServer"]

class ManagementServer(object):
    def __init__(self, place):
        self.place = place
        self.place.addExtraLogFile("/var/log/cloudstack")
        self.__isCCP = None
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
            self.place.execcmd('chkconfig mysqld on')

            self.place.execcmd('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
            self.place.execcmd('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
            self.place.execcmd('mysqladmin -u root password xensource')
            self.place.execcmd('service mysqld restart')

        if xenrt.TEC().lookup("USE_CCP_SIMULATOR", False, boolean=True):
            self.tailorForSimulator()

        setupDbLoc = self.place.execcmd('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
        self.place.execcmd('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

    def setupManagementServer(self):
        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')
            setupMsLoc = self.place.execcmd('find /usr/bin -name %s-setup-management' % (self.cmdPrefix)).strip()
            self.place.execcmd(setupMsLoc)

            self.place.execcmd('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')

            templateSubsts = {"http://download.cloud.com/templates/builtin/centos56-x86_64.vhd.bz2":
                                "%s/cloudTemplates/centos56-x86_64.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                               "http://download.cloud.com/releases/4.3/centos6_4_64bit.vhd.bz2":
                                "%s/cloudTemplates/centos6_4_64bit.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                               "http://download.cloud.com/templates/builtin/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2":
                                "%s/cloudTemplates/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                               "http://download.cloud.com/releases/2.2.0/CentOS5.3-x86_64.ova":
                                "%s/cloudTemplates/CentOS5.3-x86_64.ova" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                              "http://download.cloud.com/releases/2.2.0/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2":
                                "%s/cloudTemplates/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")}

            if xenrt.TEC().lookup("MARVIN_BUILTIN_TEMPLATES", False, boolean=True):
                templateSubsts["http://download.cloud.com/templates/builtin/centos56-x86_64.vhd.bz2"] = \
                        "%s/cloudTemplates/centos56-httpd-64bit.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")
                templateSubsts["http://download.cloud.com/releases/2.2.0/CentOS5.3-x86_64.ova"] = \
                        "%s/cloudTemplates/centos53-httpd-64bit.ova" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                templateSubsts["http://download.cloud.com/releases/2.2.0/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2"] = \
                        "%s/cloudTemplates/centos55-httpd-64bit.qcow2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                  

            for t in templateSubsts.keys():
                self.place.execcmd("""mysql -u cloud --password=cloud --execute="UPDATE cloud.vm_template SET url='%s' WHERE url='%s'" """ % (templateSubsts[t], t))

        self.restart()
        marvinApi = xenrt.lib.cloud.MarvinApi(self)

        marvinApi.setCloudGlobalConfig("secstorage.allowed.internal.sites", "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12")
        marvinApi.setCloudGlobalConfig("check.pod.cidrs", "false", restartManagementServer=True)
        marvinApi.setCloudGlobalConfig("use.external.dns", "true", restartManagementServer=True)
        xenrt.GEC().dbconnect.jobUpdate("CLOUD_MGMT_SVR_IP", self.place.getIP())
        xenrt.TEC().registry.toolstackPut("cloud", xenrt.lib.cloud.CloudStack(place=self.place))
        # Create one secondary storage, to speed up deployment.
        # Additional locations will need to be created during deployment
        hvlist = xenrt.TEC().lookup("CLOUD_REQ_SYS_TMPLS", None)
        if hvlist:
            hvlist = hvlist.split(",")
        else:
            hvlist = []
        if "kvm" in hvlist or "xenserver" in hvlist or "vmware" in hvlist:
            secondaryStorage = xenrt.ExternalNFSShare()
            storagePath = secondaryStorage.getMount()
            url = 'nfs://%s' % (secondaryStorage.getMount().replace(':',''))
            marvinApi.copySystemTemplatesToSecondaryStorage(storagePath, "NFS")
            self.place.special['initialNFSSecStorageUrl'] = url
        elif "hyperv" in hvlist:
            if xenrt.TEC().lookup("EXTERNAL_SMB", False, boolean=True):
                secondaryStorage = xenrt.ExternalSMBShare()
                storagePath = secondaryStorage.getMount()
                url = 'cifs://%s' % (secondaryStorage.getMount().replace(':',''))
                marvinApi.copySystemTemplatesToSecondaryStorage(storagePath, "SMB")
                self.place.special['initialSMBSecStorageUrl'] = url

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
        self.__isCCP = True
        if self.place.arch != 'x86-64':
            raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

        manSvrInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
        if not manSvrInputDir:
            raise xenrt.XRTError('Location of management server build not specified')

        if self.place.distro in ['rhel63', 'rhel64', ]:
            manSvrFile = xenrt.TEC().getFile(manSvrInputDir)
            if manSvrFile is None:
                raise xenrt.XRTError("Couldn't find CCP build")
            webdir = xenrt.WebDirectory()
            webdir.copyIn(manSvrFile)
            manSvrUrl = webdir.getURL(os.path.basename(manSvrFile))

            self.place.execcmd('wget %s -O cp.tar.gz' % (manSvrUrl))
            webdir.remove()
            self.place.execcmd('mkdir cloudplatform')
            self.place.execcmd('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            installDir = os.path.dirname(self.place.execcmd('find cloudplatform/ -type f -name install.sh'))
            self.place.execcmd('cd %s && ./install.sh -m' % (installDir), timeout=600)

        self.installCifs()
        self.checkJavaVersion()
        self.setupManagementServerDatabase()
        self.setupManagementServer()
        self.installApacheProxy()

    def installCloudStackManagementServer(self):
        self.__isCCP = False
        placeArtifactDir = xenrt.lib.cloud.getLatestArtifactsFromJenkins(self.place,
                                                                         ["cloudstack-management-",
                                                                          "cloudstack-common-",
                                                                          "cloudstack-awsapi-"],
                                                                         updateInputDir=True)
        
        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execcmd('yum -y install %s' % (os.path.join(placeArtifactDir, '*')), timeout=600)

        self.installCifs()
        self.checkJavaVersion()
        self.setupManagementServerDatabase()
        self.setupManagementServer()
        self.installApacheProxy()

    def installCifs(self):
        self.place.execcmd("yum install -y samba-client samba-common cifs-utils")

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

    @property
    def isCCP(self):
        if self.__isCCP is None:
            # There appears no reliable way on pre-release versions to identify if we're using CCP or ACS,
            # for now we are therefore going to use the presence or absence of the ACS_BRANCH variable.
            self.__isCCP = xenrt.TEC().lookup("ACS_BRANCH", None) is None

        return self.__isCCP

    def tailorForSimulator(self):
        self.place.execcmd('mysql -u root --password=xensource < /usr/share/cloudstack-management/setup/create-database-simulator.sql')
        self.place.execcmd('mysql -u root --password=xensource < /usr/share/cloudstack-management/setup/create-schema-simulator.sql')
#        self.place.execcmd('grep "INSERT INTO\|VALUES" /usr/share/cloudstack-management/setup/templates.simulator.sql >> /usr/share/cloudstack-management/setup/templates.sql')
        self.place.execcmd('wget http://files.uk.xensource.com/usr/groups/xenrt/cloud/templates.simulator.sql -O /tmp/ts.sql')
        self.place.execcmd('grep "INSERT INTO\|VALUES" /tmp/ts.sql >> /usr/share/cloudstack-management/setup/templates.sql')

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

