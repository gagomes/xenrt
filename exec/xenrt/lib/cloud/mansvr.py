import xenrt
import logging
import os, os.path, urllib, IPy
from datetime import datetime

import xenrt.lib.cloud
try:
    import jenkinsapi
    from jenkinsapi.jenkins import Jenkins
except ImportError:
    pass

__all__ = ["ManagementServer"]

class ManagementServer(object):
    def __init__(self, place, dbServer=None, simDbServer=None, additionalManagementServers=None):
        self.primaryManagementServer = place
        self._dbServer = dbServer
        self._simDbServer = simDbServer
        self.additionalManagementServers = additionalManagementServers or []
        self.primaryManagementServer.addExtraLogFile("/var/log/cloudstack")
        self.__isCCP = None
        self.__version = None
        self.__db = None
        if self.version in ['3.0.7']:
            self.cmdPrefix = 'cloud'
        else:
            self.cmdPrefix = 'cloudstack'

    def getLogs(self, destDir):
        sftp = self.primaryManagementServer.sftpClient()
        manSvrLogsLoc = self.primaryManagementServer.execcmd('find /var/log -type d -name management | grep %s' % (self.cmdPrefix)).strip()
        sftp.copyTreeFrom(os.path.dirname(manSvrLogsLoc), destDir)
        sftp.close()

    @property
    def allManagementServers(self):
        ret = [self.primaryManagementServer]
        ret.extend(self.additionalManagementServers)
        return ret

    @property
    def ip(self):
        return self.primaryManagementServer.getIP()

    def getDatabaseDump(self, destDir):
        path = self.primaryManagementServer.execcmd("mktemp").strip()
        self.primaryManagementServer.execcmd("mysqldump -u cloud --password=cloud --skip-opt cloud > %s" % path)
        sftp = self.primaryManagementServer.sftpClient()
        sftp.copyFrom(path, os.path.join(destDir, "cloud.sql"))
        sftp.close()
        self.primaryManagementServer.execcmd("rm -f %s" % path)

    def lookup(self, key, default=None):
        """Perform a version based lookup on cloud config data"""
        lookupKeys = ['CLOUD_CONFIG', self.version]
        if isinstance(key, list):
            lookupKeys += key
        else:
            lookupKeys.append(key)
        return xenrt.TEC().lookup(lookupKeys, default)

    def checkManagementServerHealth(self, timeout=120):
        managementServerOk = False
        maxRetries = timeout/60
        maxReboots = 2
        rebootChecks = 0
        while(rebootChecks <= maxReboots and not managementServerOk):
            retries = 0
            while(retries < maxRetries):
                retries += 1
                xenrt.TEC().logverbose('Check Management Server Ports: Attempt: %d of %d' % (retries, maxRetries))

                # Check the management server ports are reachable
                port = 8080
                try:
                    for m in self.allManagementServers:
                        urllib.urlopen('http://%s:%s' % (m.getIP(), port))
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (m.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)
                    continue

                port = 8096
                try:
                    for m in self.allManagementServers:
                        urllib.urlopen('http://%s:%s' % (m.getIP(), port))
                    managementServerOk = True
                    break
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (m.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)

            if not managementServerOk and rebootChecks < maxReboots:
                xenrt.TEC().logverbose('Restarting Management Server: Attempt: %d of %d' % (rebootChecks+1, maxReboots))
                self.primaryManagementServer.execcmd('mysql -u cloud --password=cloud -h %s --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"' % self.dbServer.getIP())
                self.restart(checkHealth=False, startStop=(rebootChecks > 0))
            rebootChecks += 1

        if not managementServerOk:
            # Store the MS logs
            mgmtSvrHealthCheckFailedLogDir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'healthFailure')
            if not os.path.exists(mgmtSvrHealthCheckFailedLogDir):
                os.makedirs(mgmtSvrHealthCheckFailedLogDir)
            self.getLogs(mgmtSvrHealthCheckFailedLogDir)
            raise xenrt.XRTFailure('Management Server not reachable')

    def restart(self, checkHealth=True, startStop=False):
        if not startStop:
            for m in self.allManagementServers:
                m.execcmd('service %s-management restart' % (self.cmdPrefix))
        else:
            self.stop()
            xenrt.sleep(120)
            self.start()
        
        if checkHealth:
            self.checkManagementServerHealth()

    def stop(self):
        for m in self.allManagementServers:
            m.execcmd('service %s-management stop' % (self.cmdPrefix))

    def start(self):
        for m in self.allManagementServers:
            m.execcmd('service %s-management start' % (self.cmdPrefix))


    def getCCPInputs(self):
        return xenrt.getCCPInputs(self.primaryManagementServer.distro)

    @property
    def dbServer(self):
        return self._dbServer or self.primaryManagementServer

    @property
    def simDbServer(self):
        return self._simDbServer or self._dbServer or self.primaryManagementServer

    def setupManagementServerDatabase(self):
        for m in self.allManagementServers:
            if m.distro.startswith("rhel6") or m.distro.startswith("centos6"):
                # Configure SELinux
                m.execcmd("sed -i 's/SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config")
                m.execcmd('setenforce Permissive')

        self.installMySql(self.dbServer)
        [self.installMySql(x, server=False) for x in self.allManagementServers]

        if self.primaryManagementServer == self.dbServer and not self.additionalManagementServers:
            host = "localhost"
        else:
            host = self.dbServer.getIP()
        setupDbLoc = self.primaryManagementServer.execcmd('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
        self.primaryManagementServer.execcmd('%s cloud:cloud@%s --deploy-as=root:xensource' % (setupDbLoc, host))
        for m in self.additionalManagementServers:
            setupDbLoc = m.execcmd('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
            m.execcmd('%s cloud:cloud@%s' % (setupDbLoc, host))
        
        if xenrt.TEC().lookup("USE_CCP_SIMULATOR", False, boolean=True):
            self.tailorForSimulator()

    def installMySql(self, dbServer, server=True):
        if dbServer.special.get('mysql_server_installed'):
            return
        db = "mysqld"
        if server:
            mysqlPackages = "mysql-server mysql"
            mariaPackages = "mariabdb-server mariadb"
        else:
            mysqlPackages = "mysql"
            mariaPackages = "mariadb"
        if dbServer.distro.startswith("rhel6") or dbServer.distro.startswith("centos6"):
                dbServer.execcmd('yum -y install %s' % mysqlPackages)
        elif dbServer.distro.startswith("rhel7") or dbServer.distro.startswith("centos7"):
            if xenrt.TEC().lookup("CLOUDSTACK_MARIADB", False, boolean=True):
                dbServer.execcmd('yum -y install %s' % mariaPackages)
                db = "mariadb"
            else:
                # Add a proxy if we know about one
                proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
                if proxy:
                    dbServer.execcmd("sed -i '/proxy/d' /etc/yum.conf")
                    dbServer.execcmd("echo 'proxy=http://%s' >> /etc/yum.conf" % proxy)
                dbServer.execcmd("wget -O mysql-repo.rpm %s/rpms/mysql-community-release-el7-5.noarch.rpm" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"))
                dbServer.execcmd("yum install -y mysql-repo.rpm")
                if server and xenrt.TEC().lookup("WORKAROUND_CS30447", True, boolean=True):
                    xenrt.TEC().warning("Using workaround for CS-30447")
                    dbServer.execcmd("yum -y install mysql-community-server-5.6.21")
                else:
                    dbServer.execcmd('yum -y install %s' % mysqlPackages)
        if server:
            dbServer.execcmd('service %s restart' % db)
            dbServer.execcmd('chkconfig %s on' % db)

            dbServer.execcmd('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' IDENTIFIED BY \'xensource\' WITH GRANT OPTION"')
            dbServer.execcmd('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
            dbServer.execcmd('mysqladmin -u root password xensource')
            dbServer.execcmd('service %s restart' % db)
            dbServer.special['mysql_server_installed'] = True

    def setupManagementServer(self):
        for m in self.allManagementServers:
            m.execcmd('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')
            setupMsLoc = m.execcmd('find /usr/bin -name %s-setup-management' % (self.cmdPrefix)).strip()
            m.execcmd(setupMsLoc)

        self.primaryManagementServer.execcmd('mysql -u cloud --password=cloud -h %s --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"' % self.dbServer.getIP())

        if xenrt.TEC().lookup("USE_CCP_SIMULATOR", False, boolean=True):
            # For some reason the cloud user doesn't seem to have access to the simulator DB
            [x.execcmd("""sed -i s/db.simulator.username=cloud/db.simulator.username=root/ /usr/share/cloudstack-management/conf/db.properties""") for x in self.allManagementServers]
            [x.execcmd("""sed -i s/db.simulator.password=cloud/db.simulator.password=xensource/ /usr/share/cloudstack-management/conf/db.properties""") for x in self.allManagementServers]
            if self.simDbServer != self.primaryManagementServer or self.additionalManagementServers:
                [x.execcmd("""sed -i s/db.simulator.host=localhost/db.simulator.host=%s/ /usr/share/cloudstack-management/conf/db.properties""" % self.simDbServer.getIP()) for x in self.allManagementServers]
                
        self.restart(checkHealth=False)
        self.checkManagementServerHealth(timeout=300)

        # We have to update templates *after* starting the management server as some templates are not introduced until DB schema updates are applied
        templateSubsts = {"http://download.cloud.com/templates/builtin/centos56-x86_64.vhd.bz2":
                            "%s/cloudTemplates/centos56-x86_64.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://download.cloud.com/releases/4.3/centos6_4_64bit.vhd.bz2":
                            "%s/cloudTemplates/centos6_4_64bit.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://nfs1.lab.vmops.com/templates/centos53-x86_64/latest/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2":
                            "%s/cloudTemplates/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://download.cloud.com/templates/builtin/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2":
                            "%s/cloudTemplates/f59f18fb-ae94-4f97-afd2-f84755767aca.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://download.cloud.com/releases/2.2.0/CentOS5.3-x86_64.ova":
                            "%s/cloudTemplates/CentOS5.3-x86_64.ova" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://download.cloud.com/releases/2.2.0/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2":
                            "%s/cloudTemplates/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"),
                           "http://download.cloud.com/templates/builtin/centos-7-x86_64.tar.gz":
                            "%s/cloudTemplates/centos-7-x86_64.tar.gz" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")}

        if xenrt.TEC().lookup("MARVIN_BUILTIN_TEMPLATES", False, boolean=True):
            templateSubsts["http://download.cloud.com/templates/builtin/centos56-x86_64.vhd.bz2"] = \
                    "%s/cloudTemplates/centos56-httpd-64bit.vhd.bz2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")
            templateSubsts["http://download.cloud.com/releases/2.2.0/CentOS5.3-x86_64.ova"] = \
                    "%s/cloudTemplates/centos53-httpd-64bit.ova" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")
            templateSubsts["http://download.cloud.com/releases/2.2.0/eec2209b-9875-3c8d-92be-c001bd8a0faf.qcow2.bz2"] = \
                    "%s/cloudTemplates/centos55-httpd-64bit.qcow2" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")

        for t in templateSubsts.keys():
            self.primaryManagementServer.execcmd("""mysql -u cloud --password=cloud -h %s --execute="UPDATE cloud.vm_template SET url='%s' WHERE url='%s'" """ % (self.dbServer.getIP(), templateSubsts[t], t))

        self.restart()

        marvinApi = xenrt.lib.cloud.MarvinApi(self)

        internalMask = IPy.IP("%s/%s" % (xenrt.getNetworkParam("NPRI", "SUBNET"), xenrt.getNetworkParam("NPRI", "SUBNETMASK")))

        if xenrt.TEC().lookup("USE_CCP_SIMULATOR", False, boolean=True):
            self.primaryManagementServer.execcmd('mysql -u root --password=xensource -h %s < /usr/share/cloudstack-management/setup/hypervisor_capabilities.simulator.sql', self.dbServer.getIP())
            self.primaryManagementServer.execcmd('mysql -u root --password=xensource -h %s < /usr/share/cloudstack-management/setup/templates.simulator.sql' % self.dbServer.getIP())
        marvinApi.setCloudGlobalConfig("secstorage.allowed.internal.sites", internalMask.strNormal())
        if not xenrt.TEC().lookup("MARVIN_SETUP", False, boolean=True):
            marvinApi.setCloudGlobalConfig("use.external.dns", "true")
        endpoint_url = "http://%s:8096/client/api" % marvinApi.mgtSvrDetails.mgtSvrIp
        if self.additionalManagementServers:
            marvinApi.setCloudGlobalConfig("agent.lb.enable", "true")
        marvinApi.setCloudGlobalConfig("endpointe.url", endpoint_url)
        marvinApi.setCloudGlobalConfig("check.pod.cidrs", "false", restartManagementServer=True)
        xenrt.GEC().dbconnect.jobUpdate("CLOUD_MGMT_SVR_IP", self.primaryManagementServer.getIP())
        xenrt.TEC().registry.toolstackPut("cloud", xenrt.lib.cloud.CloudStack(place=self.primaryManagementServer))
        # Create one secondary storage, to speed up deployment.
        # Additional locations will need to be created during deployment
        hvlist = xenrt.TEC().lookup("CLOUD_REQ_SYS_TMPLS", None)
        if hvlist:
            hvlist = hvlist.split(",")
        else:
            hvlist = []
        if any(map(lambda hv: hv in hvlist, ["kvm", "xenserver", "vmware", "lxc"])):
            secondaryStorage = xenrt.ExternalNFSShare()
            storagePath = secondaryStorage.getMount()
            url = 'nfs://%s' % (secondaryStorage.getMount().replace(':',''))
            marvinApi.copySystemTemplatesToSecondaryStorage(storagePath, "NFS")
            self.primaryManagementServer.special['initialNFSSecStorageUrl'] = url
        elif "hyperv" in hvlist:
            if xenrt.TEC().lookup("EXTERNAL_SMB", False, boolean=True):
                secondaryStorage = xenrt.ExternalSMBShare()
                storagePath = secondaryStorage.getMount()
                url = 'cifs://%s' % (secondaryStorage.getMount().replace(':',''))
                marvinApi.copySystemTemplatesToSecondaryStorage(storagePath, "SMB")
                self.primaryManagementServer.special['initialSMBSecStorageUrl'] = url

        if xenrt.TEC().lookup("CCP_CODE_COVERAGE", False, boolean=True):
            xenrt.TEC().logverbose("Enabling code coverage collection...")
            for m in self.allManagementServers:
                if m.execcmd("ls %s/setup_codecoverage.sh" % self.installDir, retval="code") != 0:
                    raise xenrt.XRTError("CCP_CODE_COVERAGE set but setup_codecoverage.sh not found in build")
                m.execcmd("cd %s && ./setup_codecoverage.sh" % self.installDir)
            self.restart()
            xenrt.TEC().logverbose("...done")

        commit = None
        try:
            commit = self.primaryManagementServer.execcmd("cloudstack-sccs").strip()
            xenrt.TEC().logverbose("Management server was built from commit %s" % commit)
        except:
            xenrt.TEC().warning("Error when trying to identify management server version")
        if commit:
            expectedCommit = xenrt.getCCPCommit(self.primaryManagementServer.distro)
            if expectedCommit and commit != expectedCommit:
                raise xenrt.XRTError("Management server commit %s does not match expected commit %s" % (commit, expectedCommit))

    def installApacheProxy(self):
        for m in self.allManagementServers:
            m.execcmd("yum -y install httpd")
            m.execcmd("echo ProxyPass /client http://127.0.0.1:8080/client > /etc/httpd/conf.d/cloudstack.conf")
            m.execcmd("echo ProxyPassReverse /client http://127.0.0.1:8080/client >> /etc/httpd/conf.d/cloudstack.conf")
            m.execcmd("echo RedirectMatch ^/$ /client >> /etc/httpd/conf.d/cloudstack.conf")
            m.execcmd("chkconfig httpd on")
            m.execcmd("service httpd restart")
            if m.distro == "rhel7" or m.distro == "centos7":
                m.execcmd('iptables -I INPUT -p tcp --dport 80 -j ACCEPT')

    def checkJavaVersion(self):
        for m in self.allManagementServers:
            if m.distro.startswith("rhel6") or m.distro.startswith("centos6"):
                if self.version in ['4.4', '4.5', '4.5.1', '4.6.0']:
                    # Check if Java 1.7.0 is installed
                    m.execcmd('yum -y install java-1.7.0-openjdk')
                    if not '1.7.0' in m.execcmd('java -version').strip():
                        javaDir = m.execcmd('update-alternatives --display java | grep "^/usr/lib.*1.7.0"').strip()
                        m.execcmd('update-alternatives --set java %s' % (javaDir.split()[0]))

                    if not '1.7.0' in m.execcmd('java -version').strip():
                        raise xenrt.XRTError('Failed to install and select Java 1.7')

    def installCloudPlatformManagementServer(self):
        for m in self.allManagementServers:
            self.__isCCP = True
            if m.arch != 'x86-64':
                raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

            manSvrInputDir = self.getCCPInputs()
            if not manSvrInputDir:
                raise xenrt.XRTError('Location of management server build not specified')

            manSvrFile = xenrt.TEC().getFile(manSvrInputDir)
            if manSvrFile is None:
                raise xenrt.XRTError("Couldn't find CCP build")
            webdir = xenrt.WebDirectory()
            webdir.copyIn(manSvrFile)
            manSvrUrl = webdir.getURL(os.path.basename(manSvrFile))

            m.execcmd('wget %s -O cp.tar.gz' % (manSvrUrl))
            webdir.remove()

            if m.distro == "rhel7" or m.distro == "centos7":
                fname = "ws-commons-util-1.0.1-29.el7.noarch.rpm"
                wscommons = xenrt.TEC().getFile("/usr/groups/xenrt/cloud/rpms/%s" % fname)
                webdir = xenrt.WebDirectory()
                webdir.copyIn(wscommons)
                wscommonsurl = webdir.getURL(fname)
                m.execcmd("wget %s -O /root/%s" % (wscommonsurl, fname))
                m.execcmd("yum install -y /root/%s" % fname)
                webdir.remove()

            m.execcmd('mkdir cloudplatform')
            m.execcmd('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            self.installDir = os.path.dirname(m.execcmd('find cloudplatform/ -type f -name install.sh'))
            m.execcmd('cd %s && ./install.sh -m' % (self.installDir), timeout=600)


    def installCloudStackManagementServer(self):
        self.__isCCP = False
        for m in self.allManagementServers:
            placeArtifactDir = xenrt.lib.cloud.getACSArtifacts(m,
                                                               ["cloudstack-management-",
                                                                "cloudstack-common-",
                                                                "cloudstack-awsapi-"])

            m.execcmd('yum -y install %s' % (os.path.join(placeArtifactDir, '*')), timeout=600)

    def saveFirewall(self):
        [x.execcmd("service iptables save") for x in self.allManagementServers]

    def installCifs(self):
        [x.execcmd("yum install -y samba-client samba-common cifs-utils") for x in self.allManagementServers]

    @property
    def version(self):
        # This method determines the version number of CloudStack or CloudPlatform being used.
        # TODO - Need to find a better way of doing this
        if not self.__version:
            versionKeys = xenrt.TEC().lookup('CLOUD_CONFIG').keys()
            xenrt.TEC().logverbose('XenRT supports the following MS versions: %s' % (str(versionKeys)))
            masterMap = xenrt.TEC().lookup('CLOUD_MASTER_MAP')
            xenrt.TEC().logverbose('The branch master is currently treated as: %s' % masterMap)
            versionKeys.append('master')
            # Try and get the version from the MS database
            dbVersionMatches = []
            installVersionMatches = []
            try:
                dbVersion = self.primaryManagementServer.execcmd('mysql -u cloud --password=cloud -h %s -s -N --execute="SELECT version from cloud.version ORDER BY id DESC LIMIT 1"' % self.dbServer.getIP()).strip()
                xenrt.TEC().logverbose('Found MS version %s from database' % (dbVersion))
                dbVersionMatches = filter(lambda x:x in dbVersion, versionKeys)
            except Exception, e:
                xenrt.TEC().logverbose('Failed to get MS version from database: %s' % (str(e)))

            installVersionStr = self.getCCPInputs() or xenrt.TEC().lookup("ACS_BUILD", xenrt.TEC().lookup("ACS_BRANCH", None))
            if installVersionStr:
                installVersionMatches = filter(lambda x:x in installVersionStr, versionKeys)

                if len(installVersionMatches) > 1 and "master" in installVersionMatches:
                    # We found master + a version number - we'll use the version number
                    installVersionMatches.remove("master")
                if len(installVersionMatches) == 1 and installVersionMatches[0] == "master":
                    # Just master - replace it with the version we believe master to be at the moment
                    installVersionMatches[0] = masterMap

            xenrt.TEC().logverbose('XenRT support MS versions matching DB version: %s' % (dbVersionMatches))
            xenrt.TEC().logverbose('XenRT support MS versions matching install version: %s' % (installVersionMatches))

            versionMatches = list(set(dbVersionMatches + installVersionMatches))
            if len(versionMatches) == 1:
                self.__version = versionMatches[0]
            elif len(versionMatches) == 0:
                xenrt.TEC().warning('Management Server version could not be determined')
            else:
                # Choose the most specific match (this is for e.g. 4.5 vs 4.5.1)
                self.__version = max(versionMatches, key=len)

            xenrt.TEC().comment('Using Management Server version: %s' % (self.__version))
        return self.__version

    @property
    def isCCP(self):
        if self.__isCCP is None:
            # There appears no reliable way on pre-release versions to identify if we're using CCP or ACS,
            # for now we are therefore going to use the presence or absence of the ACS_BRANCH variable.
            self.__isCCP = xenrt.TEC().lookup("ACS_BRANCH", None) is None and xenrt.TEC().lookup("CLOUDRPMTAR", None) is None and xenrt.TEC().lookup("ACS_BUILD", None) is None

        return self.__isCCP

    @property
    def db(self):
        if self.__db is None:
            # Default DB is MySQL
            self.__db = 'mysqld'

            if xenrt.TEC().lookup("CLOUDSTACK_MARIADB", False, boolean=True):
                if self.dbServer.distro.startswith("rhel7") or self.dbServer.distro.startswith("centos7"):
                    self.__db = "mariadb"
                else:
                    xenrt.XRTError('Maria DB only support in RHEL / CentOS 7')
        return self.__db

    def tailorForSimulator(self):
        self.installMySql(self.simDbServer)
        self.primaryManagementServer.execcmd('mysql -u root --password=xensource -h %s < /usr/share/cloudstack-management/setup/create-database-simulator.sql' % self.simDbServer.getIP())
        self.primaryManagementServer.execcmd('mysql -u root --password=xensource -h %s < /usr/share/cloudstack-management/setup/create-schema-simulator.sql' % self.simDbServer.getIP())

    def preManagementServerInstall(self):
        # Check correct Java version is installed (installs correct version if required)
        self.checkJavaVersion()

    def postManagementServerInstall(self):
        if not self.isCCP and self.version in ['4.4', '4.5']:
            for m in self.allManagementServers:
                m.execcmd('wget http://download.cloud.com.s3.amazonaws.com/tools/vhd-util -P /usr/share/cloudstack-common/scripts/vm/hypervisor/xenserver/')
                m.execcmd('chmod 755 /usr/share/cloudstack-common/scripts/vm/hypervisor/xenserver/vhd-util')

    def installCloudManagementServer(self):
        [x.rename(x.getName()) for x in self.allManagementServers]
        self.preManagementServerInstall()

        if self.getCCPInputs():
            self.installCloudPlatformManagementServer()
        elif xenrt.TEC().lookup('ACS_BRANCH', None) != None or xenrt.TEC().lookup("CLOUDRPMTAR", None) != None or xenrt.TEC().lookup("ACS_BUILD", None) != None:
            self.installCloudStackManagementServer()
        else:
            raise xenrt.XRTError("Didn't find one of CLOUDINPUTDIR, ACS_BRANCH, CLOUDRPMTAR or ACS_BUILD variables")

        self.installCifs()
        self.checkJavaVersion()
        self.setupManagementServerDatabase()
        self.setupManagementServer()
        self.installApacheProxy()
        self.saveFirewall()
        self.postManagementServerInstall()
