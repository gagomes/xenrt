import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

__all__ = ["ManagementServer"]

class ManagementServer(object):
    def __init__(self, place):
        self.place = place
        self.cmdPrefix = 'cloudstack'

    def getLogs(self, destDir):
        sftp = self.place.sftpClient()
        manSvrLogsLoc = self.place.execguest('find /var/log -type f -name management-server.log').strip()
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
                reboots += 1
                xenrt.TEC().logverbose('Restarting Management Server: Attempt: %d of %d' % (reboots, maxReboots))
                self.place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
                self.restart(checkHealth=False, startStop=True)

    def restart(self, checkHealth=True, startStop=False):
        if not startStop:
            self.place.execguest('service %s-management restart' % (self.cmdPrefix))
        else:
            self.place.execguest('service %s-management stop' % (self.cmdPrefix))
            xenrt.sleep(120)
            self.place.execguest('service %s-management start' % (self.cmdPrefix))
        
        if checkHealth:
            self.checkManagementServerHealth()

    def installCloudPlatformManagementServer(self):
        if self.place.arch != 'x86-64':
            raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

        manSvrInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
        if not manSvrInputDir:
            raise xenrt.XRTError('Location of management server build not specified')

        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execguest('wget %s -O cp.tar.gz' % (manSvrInputDir))
            self.place.execguest('mkdir cloudplatform')
            self.place.execguest('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            installDir = os.path.dirname(self.place.execguest('find cloudplatform/ -type f -name install.sh'))
            self.place.execguest('cd %s && ./install.sh -m' % (installDir))

            self.place.execguest('setenforce Permissive')
            self.place.execguest('service nfs start')

            self.place.execguest('yum -y install mysql-server mysql')
            self.place.execguest('service mysqld restart')

            self.place.execguest('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
            self.place.execguest('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
            self.place.execguest('mysqladmin -u root password xensource')
            self.place.execguest('service mysqld restart')

            setupDbLoc = self.place.execguest('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
            self.place.execguest('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

            self.place.execguest('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')

            setupMsLoc = self.place.execguest('find /usr/bin -name %s-setup-management' % (self.cmdPrefix)).strip()
            self.place.execguest(setupMsLoc)    

            self.place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
        
        self.restart()

