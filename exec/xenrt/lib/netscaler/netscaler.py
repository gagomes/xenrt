
import xenrt
import os
import re
from pprint import pformat

__all__ = ["NetScaler"]

class NetScaler(object):
    """Class that provides an interface for creating, controlling and observing a NetScaler VPX"""

    @classmethod
    def setupNetScalerVpx(cls, vpxName, networks=["NPRI"]):
        """Takes a VM name (present in the registry) and returns a NetScaler object"""
        vpxGuest = xenrt.TEC().registry.guestGet(vpxName)
        host = vpxGuest.host
        xenrt.TEC().logverbose('Using VPX Appliance: %s on host: %s - current state: %s' % (vpxGuest.getName(), host.getName(), vpxGuest.getState()))
        xenrt.TEC().logverbose("VPX Guest:\n" + pformat(vpxGuest.__dict__))

        vpxGuest.noguestagent = True
        vpxGuest.password = 'nsroot'

        try:
            vpxMgmtIp = vpxGuest.paramGet(paramName='xenstore-data', paramKey='vm-data/ip')
            xenrt.xrtAssert(vpxGuest.mainip == vpxMgmtIp and vpxGuest.mainip != None, 'Netscaler VPX guest has inconsistent or NULL IP Address')
            if vpxGuest.getState() == 'DOWN':
                vpxGuest.lifecycleOperation('vm-start')

            # Wait / Check for SSH connectivity
            vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')
            vpx = cls(vpxGuest, None)
        except xenrt.XRTFailure, e:
            if vpxGuest.getState() == 'UP':
                vpxGuest.shutdown()

            # Configure the VIFs
            vpxGuest.removeAllVIFs()

            mgmtNet = networks[0]
            for n in networks:
                vpxGuest.createVIF(bridge=n)

            # Configure the management network for the VPX
            vpxGuest.mainip = xenrt.StaticIP4Addr(network=mgmtNet).getAddr()
            gateway = xenrt.getNetworkParam(mgmtNet, "GATEWAY")
            mask = xenrt.getNetworkParam(mgmtNet, "SUBNETMASK")
            vpxGuest.paramSet('xenstore-data:vm-data/ip', vpxGuest.mainip)
            vpxGuest.paramSet('xenstore-data:vm-data/netmask', mask)
            vpxGuest.paramSet('xenstore-data:vm-data/gateway', gateway)

            vpxGuest.lifecycleOperation('vm-start')

            # Wait / Check for SSH connectivity
            vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')
            vpx = cls(vpxGuest, mgmtNet)
            vpx.setup(networks)
        return vpx

    @classmethod
    def createVPXOnHost(cls, host, vpxName=None, vpxHttpLocation=None):
        """Import a Netscaler VPX onto the specified host"""
        if not vpxName:
            vpxName = xenrt.randomGuestName()
        if not vpxHttpLocation:
            vpxHttpLocation = os.path.join(xenrt.TEC().lookup('EXPORT_DISTFILES_HTTP'), 'tallahassee/NSVPX-XEN-10.0-72.5_nc.xva')
        xenrt.TEC().logverbose('Importing VPX [%s] from: %s to host: %s' % (vpxName, vpxHttpLocation, host.getName()))
        xenrt.productLib(hostname=host.getName()).guest.createVMFromFile(host=host, guestname=vpxName, filename=vpxHttpLocation)
        return cls.setupNetScalerVpx(vpxName)

    def __init__(self, vpxGuest, mgmtNet):
        self.__vpxGuest = vpxGuest
        self.__version = None
        self.__managementIp = None
        self.__gateways = {}
        self.__mgmtNet = mgmtNet
        xenrt.TEC().logverbose('NetScaler VPX Version: %s' % (self.version))

    def setup(self, networks):
        i = 1
        for n in networks[1:]:
            i += 1
            self.__netScalerCliCommand("add vlan %d" % i)
            self.__netScalerCliCommand("bind vlan %d -ifnum 1/%d" % i)
            self.__gateways[n] = xenrt.StaticIP4Addr(network=n).getAddr()
            self.__netScalerCliCommand('add ip %s %s' % (self.__gateways[n], xenrt.getNetworkParam(n, "SUBNETMASK")))
            self.__netScalerCliCommand('bind vlan %d -IPAddress %s %s' % (i, self.__gateways[n], xenrt.getNetworkParam(n, "SUBNETMASK")))

    def __netScalerCliCommand(self, command):
        """Helper method for creating specific NetScaler CLI command methods"""
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler CLI Commands can only be executed on a running VPX')
        data = self.__vpxGuest.execguest(command, username='nsroot', password='nsroot')
        data = map(lambda x:x.strip(), filter(lambda x:not x.startswith(' Done'), data.splitlines()))
        xenrt.TEC().logverbose('NetScaler Command [%s] - Returned: %s' % (command, '\n'.join(data)))
        return data

    @property
    def version(self):
        if not self.__version:
            self.__version = self.__netScalerCliCommand('show ns version')
        return self.__version

    def reboot(self):
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler VPX reboot can only be done on a running VPX')
        self.__vpxGuest.lifecycleOperation('vm-reboot')
        # Wait / Check for SSH connectivity
        self.__vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')

    def getLicenseFileFromXenRT(self):
        # TODO - Allow for different licenses to be specified
        vpxLicneseFileName = 'CNS_V3000_SERVER_PLT_Retail.lic'

        v6dir = xenrt.TEC().tempDir()
        xenrt.util.command('tar -xvzf %s/v6.tgz -C %s v6/conf' % (xenrt.TEC().lookup('TEST_TARBALL_ROOT'), v6dir))
        with open(os.path.join(v6dir, 'v6/conf')) as fh:
            p = fh.read()
        zipfile = "%s/keys/citrix/v6.zip" % (xenrt.TEC().lookup("XENRT_CONF"))
        xenrt.util.command('unzip -P %s -d %s %s %s' % (p, v6dir, zipfile, vpxLicneseFileName))
        licenseFilePath = os.path.join(v6dir, vpxLicneseFileName)
        if not os.path.exists(licenseFilePath):
            raise xenrt.XRTError('Failed to find VPX License')
        xenrt.TEC().logverbose('Using VPX license file: %s' % (licenseFilePath))
        return licenseFilePath

    def applyLicense(self, localLicensePath):
        """Apply the license file specified and apply the license"""
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler license can only be applied on a running VPX')
        sftp = self.__vpxGuest.sftpClient(username='nsroot')
        sftp.copyTo(localLicensePath, os.path.join('/nsconfig/license', os.path.basename(localLicensePath)))
        sftp.close()
        self.reboot()

        xenrt.xrtAssert(self.isLicensed, 'NetScaler reports being licensed after license file is applied')

    @property
    def isLicensed(self, feature=None):
        if not feature:
            # Use LB as default
            feature = 'Load Balancing'
        licData = filter(lambda x:x.startswith(feature), self.__netScalerCliCommand('show ns license'))
        xenrt.xrtAssert(len(licData) == 1, 'There is an entry for the specified feature in the NS license data')
        licensed = licData[0].split(':')[1].strip() == 'YES'
        xenrt.TEC().logverbose('NetScaler feature: %s license state = %s' % (feature, licensed))
        return licensed

    @property
    def managementIp(self):
        if not self.__managementIp:
            mgmtIpData = filter(lambda x:'NetScaler IP' in x, self.__netScalerCliCommand('show ns ip'))
            xenrt.xrtAssert(len(mgmtIpData) == 1, 'The NetScaler only has one management interface defined')
            managementIp = re.search('(\d{1,3}\.){3}\d{1,3}', mgmtIpData[0]).group(0)
            xenrt.xrtAssert(managementIp == self.__vpxGuest.mainip, 'The IP address of the guest matches the reported Netscaler management IP address')
            self.__managementIp = managementIp
        return self.__managementIp

    def gatewayIp(self, network=None):
        if not network:
            network="NPRI"
        if network == self.__mgmtNet:
            return self.managementIp
        return self.__gateways[network]

    def disableL3(self):
        self.__netScalerCliCommand("disable ns mode L3")
