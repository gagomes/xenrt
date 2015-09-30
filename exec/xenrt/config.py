#
# XenRT: Test harness for Xen and the XenServer product family
#
# Job configuration
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, xml.dom.minidom, re, os.path, os, copy, yaml
import xenrt

__all__ = ["Config"]

class Config(object):
    """Configuration"""
    def __init__(self):
        self.verbose = False
        self.nologging = False
        self.config = {}

        # By default we'll use our eth0 IP address as the server address
        netdata = os.popen("/sbin/ip addr show dev eth0").read()
        r = re.search(r"inet ([0-9\.]+)", netdata)
        if r:
            self.config["XENRT_SERVER_ADDRESS"] = r.group(1)
        else:
            # Try xenbr0 (if we're running on a Xen host)
            netdata = os.popen("/sbin/ip addr show dev xenbr0").read()
            r = re.search(r"inet ([0-9\.]+)", netdata)
            if r:
                self.config["XENRT_SERVER_ADDRESS"] = r.group(1)

        # Defaults
        self.config["OSS_VOLUME_GROUP"] = "VGXenRT"
        self.config["PACKAGES_DOM0"] = "standard"
        self.config["PACKAGES_GUEST"] = "standard"
        self.config["DEFAULT_PASSWORD"] = "xenroot"
        self.config["ROOT_PASSWORDS"] = "xenroot xensource xtBrpwd"
        self.config["ROOT_PASSWORD"] = "xenroot"
        self.config["ROOT_PASSWORD_DDK"] = "xensource"
        self.config["ROOT_PASSWORD_SDK"] = "xensource"
        self.config["ROOT_PASSWORD_XGT"] = "xensource"
        self.config["ROOT_PASSWORD_DEBIAN"] = "xensource"
        self.config["EMBEDDED_PASSWORD"] = "xensource"
        # Local workig directories etc.
        self.config["XENRT_BASE"] = "/usr/share/xenrt"
        self.config["XENRT_CONF"] = "/etc/xenrt"
        self.config["HTTP_BASE_PATH"] = "/local/scratch/www"
        self.config["GUESTFILE_BASE_PATH"] = "/local/scratch/guestfiles"
        self.config["NFS_BASE_PATH"] = "/local/scratch/nfs"
        self.config["ISCSI_BASE_PATH"] = "/local/scratch/iscsi"
        self.config["FILE_MANAGER_CACHE"] = "/local/scratch/cache2"
        self.config["FILE_MANAGER_CACHE_NFS"] = "/local/scratch/cache_nfs"
        self.config["CLEANUP_FLAGS_PATH"] = "/local/scratch/cleanup"
        self.config["RESOURCE_LOCK_DIR"] = "${NFS_BASE_PATH}/locks"
        self.config["DB_BUFFER_DIR"] = "${NFS_BASE_PATH}/dbconnect"
        self.config["JIRA_BUFFER_DIR"] = "${NFS_BASE_PATH}/jiralink"

        self.config["LOCALURL"] = "http://${XENRT_SERVER_ADDRESS}"
        self.config["HTTP_BASE_URL"] = "${LOCALURL}/export"
        self.config["TEST_TARBALL_BASE"] = "${LOCALURL}/share/tests/"
        self.config["NFS_BASE_URL"] = "nfs://${XENRT_SERVER_ADDRESS}:${NFS_BASE_PATH}"

        self.config["EXPORT_ISO_NFS"] = "${XENRT_SERVER_ADDRESS}:${XENRT_BASE}/images/iso"
        self.config["EXPORT_ISO_NFS_STATIC"] = "${XENRT_SERVER_ADDRESS}:${BINARY_INPUTS_LINUX}/iso"
        self.config["EXPORT_XGT_NFS"] = "${XENRT_SERVER_ADDRESS}:${XENRT_BASE}/images/xgts"
        self.config["RPM_SOURCE_NFS"] = "${XENRT_SERVER_ADDRESS}:${BINARY_INPUTS_LINUX}/distros"
        self.config["RPM_SOURCE_HTTP"] = "${LOCALURL}/linux/distros"
        self.config["RPM_SOURCE_HTTP_BASE"] = "${LOCALURL}"
        self.config["RPM_SOURCE_NFS_BASE"] = "${XENRT_SERVER_ADDRESS}:"
        self.config["TFTP_BASE"] = "/tftpboot"

        self.config["LOCAL_BASE"] = "/tmp/local"
        self.config["GUEST_CONSOLE_LOGDIR"] = "${LOCAL_BASE}/scratch/xenrt/guest-console-logs"
        self.config["GENERATE_STATS_BASEDIR"] = "/usr/share/xenrt/stats"

        # Networking configuration
        self.config["NETWORK_CONFIG"] = {}
        self.config["NETWORK_CONFIG"]["DEFAULT"] = {}
        r = re.search(r"inet [^/]+/(\d+)", netdata)
        if r and self.config.has_key("XENRT_SERVER_ADDRESS"):
            mask = xenrt.util.prefLenToMask(int(r.group(1)))
            subnet = xenrt.util.formSubnet(self.config["XENRT_SERVER_ADDRESS"],
                                           int(r.group(1)))
            self.config["NETWORK_CONFIG"]["DEFAULT"]["SUBNETMASK"] = mask
            self.config["NETWORK_CONFIG"]["DEFAULT"]["SUBNET"] = subnet
        routedata = os.popen("/sbin/ip route show").read()
        r = re.search(r"default via ([0-9\.]+) dev eth0", routedata)
        if r:
            self.config["NETWORK_CONFIG"]["DEFAULT"]["GATEWAY"] = r.group(1)
        self.config["NETWORK_CONFIG"]["DEFAULT"]["POOLSTART"] = "TODO"
        self.config["NETWORK_CONFIG"]["DEFAULT"]["POOLEND"] = "TODO"

        self.config["NTP_SERVERS"] = "${XENRT_SERVER_ADDRESS} 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org"

        # Binary inputs
        self.config["BINARY_INPUTS_BASE"] = "/local/inputs"
        self.config["BINARY_INPUTS_WINDOWS"] = "${BINARY_INPUTS_BASE}/windows"
        self.config["BINARY_INPUTS_LINUX"] = "${BINARY_INPUTS_BASE}/linux"
        self.config["BINARY_INPUTS_TESTS"] = "${BINARY_INPUTS_BASE}/tests"

        self.config["SSH_PRIVATE_KEY_FILE"] = "${XENRT_CONF}/keys/ssh/id_dsa_xenrt"
        self.config["SSH_PUBLIC_KEY_FILE"] = "${SSH_PRIVATE_KEY_FILE}.pub"
        self.config["RPMCHROOT"] = "${XENRT_BASE}/imagesrc/rpmchroot"
        self.config["REMOTE_SCRIPTDIR"] = "/opt/xenrt/scripts"
        self.config["LOCAL_SCRIPTDIR"] = "${XENRT_BASE}/scripts"
        self.config["IMAGES_ROOT"] = "${XENRT_BASE}/images"
        self.config["VM_IMAGES_DIR"] = "${IMAGES_ROOT}/vms"
        self.config["XENRT_LOCAL_BINARIES"] = "${XENRT_BASE}/bin"
        self.config["TEST_TARBALL_ROOT"] = "${XENRT_BASE}/tests"
        self.config["SAVEDIR"] = "${LOCAL_BASE}/scratch/srm"
        self.config["SITE_CONFIG"] = "${XENRT_CONF}/site.xml"
        self.config["SITE_CONFIG_DIR"] = "${XENRT_CONF}/conf.d"
        self.config["XENRT_VERSION_CONFIG"] = "${XENRT_BASE}/VERSION"
        self.config["MACHINE_CONFIGS"] = "${XENRT_CONF}/machines"
        self.config["MACHINE_CONFIGS_INPUT"] = "${XENRT_CONF}/machinesinput"
        self.config["SUITE_CONFIGS"] = "${XENRT_CONF}/suites"
        self.config["STARTUP_DIR"] = os.getcwd()
        self.config["LOG_DIR_BASE"] = "${STARTUP_DIR}/logs"
        self.config["RESULT_DIR"] = "${STARTUP_DIR}"
        self.config["NATIVE_WINPE_PASSWORD"] = "xensource"
        # self.config["POWERCTL_ILO_SCRIPT"] = "${XENRT_BASE}/ext/iloreboot"

        self.config["OPTION_USE_EMS"] = "yes"
        self.config["DEBIAN_MODULES"] = "gcc binutils make patch flex bzip2 time stunnel4 libaio-dev libaio1"
        self.config["DEBIAN_MODULES2"] = "g++"
        self.config["DEBIAN_ETCH_MODULES"] = "autoconf automake autotools-dev libtool libaio-dev libaio1"

        self.config["MAX_CONCURRENT_VMS"] = "50"
        self.config["MAX_CONCURRENT_VIFS"] = "200"

        self.config["TEMPLATE_NAME_DEBIAN"] = "Debian Sarge Guest Template"
        self.config["TEMPLATE_NAME_DEBIAN_SARGE"] = "Debian Sarge Guest Template"
        self.config["TEMPLATE_NAME_DEBIAN_ETCH"] = "Debian Etch Guest Template"
        self.config["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003 Standard/Enterprise"
        self.config["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 Service Pack 4"
        self.config["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP Service Pack 2"
        self.config["TEMPLATE_NAME_RHEL_41"] = "RedHat Enterprise Linux 4.1 Repository"
        self.config["TEMPLATE_NAME_RHEL_44"] = "RedHat Enterprise Linux 4.4 Repository"
        self.config["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5"
        self.config["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 Service Pack 1"
        self.config["TEMPLATE_NAME_XEN_EL"] = "Xen-enabled EL-based distribution installer template"

        self.config["TOOLS_CD_NAMES_LINUX"] = "xs-tools.iso xs-tools*.iso"
        self.config["TOOLS_CD_NAMES_WINDOWS"] = "xs-tools.iso xs-tools*.iso win-tools.iso xswindrivers.iso"
        self.config["XENCENTER_DIRECTORY"] = "c:\\Program Files\\XenSource\\XenCenter;c:\\Program Files\\Citrix\\XenCenter;c:\\Program Files (x86)\\Citrix\\XenCenter;c:\\Program Files\\XenSource Inc\\XenAdmin;c:\\Program Files\\XenSource Inc\\XenCenter"
        self.config["XENCENTER_EXE_NAME"] = "XenCenter.exe;XenAdmin.exe"
        self.config["XENCENTER_LOG_FILE"] = "C:\\Documents and Settings\\Administrator\\Application Data\\XenSource\\XenCenter\\logs\\XenCenter.log;C:\\Documents and Settings\\Administrator\\Application Data\\Citrix\\XenCenter\\logs\\XenCenter.log"
        self.config["PV_DRIVERS_DIR"] = "c:\\Program Files\\XenSource\\drivers;c:\\Program Files\\Citrix\\XenTools;c:\\Program Files\\XenSource"
        self.config["PV_DRIVERS_DIR_64"] = "c:\\Program Files (x86)\\XenSource\\drivers;c:\\Program Files (x86)\\Citrix\\XenTools;c:\\Program Files (x86)\\XenSource"

        # Windows ISOs
        self.config["WINDOWS_INSTALL_ISOS"] = {}
        self.config["WINDOWS_INSTALL_ISOS"]["ADMINISTRATOR_PASSWORD"] = "xensource"

        self.config["PV_DRIVER_INSTALLATION_SOURCE"] = ["Packages", "ToolsISO"]
        self.config["PV_DRIVERS_LIST"] = "xenbus;xeniface;xennet;xenvbd;xenvif"
        self.config["PV_DRIVERS_LOCATION"] = "win-tools-builds.tar"
        
        self.config["BUILTIN_XS_GUEST_AGENT"] = "sarge,etch"

        # Configuration specific to particular versions of the product
        self.config["VERSION_CONFIG"] = {}
        self.config["VERSION_CONFIG"]["Rio"] = {}
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_DEBIAN"] = "Debian Sarge 3.1,Debian Sarge Guest Template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_DEBIAN_SARGE"] = "Debian Sarge 3.1,Debian Sarge Guest Template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Debian Etch 4.0,Debian Etch Guest Template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_RHEL_41"] = "Red Hat Enterprise Linux 4.1,RHEL 4.1 Autoinstall Template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_RHEL_44"] = "Red Hat Enterprise Linux 4.4,RHEL 4.4 Autoinstall Template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5,Xen-enabled EL-based distribution installer template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5.0,Xen-enabled EL-based distribution installer template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5,Xen-enabled EL-based distribution installer template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5.0,Xen-enabled EL-based distribution installer template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5.0,Xen-enabled EL-based distribution installer template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_OTHER_MEDIA"] = "Other install media,Other install media template"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 x64,Windows Server 2003 Standard/Enterprise 64-bit,Windows Server 2003 Standard/Enterprise (64-bit)"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003,Windows Server 2003 Standard/Enterprise"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4,Windows 2000 Service Pack 4"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP SP2,Windows XP Service Pack 2"
        self.config["VERSION_CONFIG"]["Rio"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003,Windows Server 2003 Standard/Enterprise"
        self.config["VERSION_CONFIG"]["Rio"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80"
        self.config["VERSION_CONFIG"]["Rio"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Rio"]["DOM0_DISTRO"] = "centos5"
        self.config["VERSION_CONFIG"]["Rio"]["EXPFAIL_HIBERNATE"] = "w2k3eesp2-x64,w2kassp4"
        self.config["VERSION_CONFIG"]["Miami"] = {}
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_DEBIAN"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_DEBIAN_SARGE"] = "Debian Sarge 3.1"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_41"] = "Red Hat Enterprise Linux 4.1"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_44"] = "Red Hat Enterprise Linux 4.4"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5.0"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5.1"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP SP2"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_VISTA"] = "Windows Vista"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WS08"] = "Windows Vista"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_WS08_64"] = "Windows Vista"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CPS"] = "Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["Miami"]["TEMPLATE_NAME_CPS_64"] = "Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["Miami"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["Miami"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Miami"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["Miami"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["Miami"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["Miami"]["MAX_CONCURRENT_VIFS"] = "400"
        self.config["VERSION_CONFIG"]["Miami"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["Miami"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["Miami"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["Miami"]["MAX_VM_VCPUS"] = "8"


        self.config["VERSION_CONFIG"]["Orlando"] = {}
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_DEBIAN"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_DEBIAN_SARGE"] = "Debian Sarge 3.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_41"] = "Red Hat Enterprise Linux 4.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_44"] = "Red Hat Enterprise Linux 4.4"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7,Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5.2,Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5.2 x64,Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7,CentOS 4.6"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5.0"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5.2,CentOS 5.1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5.2 x64,CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_SLES_94"] = "SUSE Linux Enterprise Server 9 SP4"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2,SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP,Windows XP SP2"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_VISTA"] = "Windows Vista"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CPS"] = "Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["Orlando"]["TEMPLATE_NAME_CPS_64"] = "Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["Orlando"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["Orlando"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Orlando"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["Orlando"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["Orlando"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["Orlando"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["Orlando"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["Orlando"]["SNAPSHOT_OF_SUSPENDED_VM_IS_SUSPENDED"] = "yes"
        self.config["VERSION_CONFIG"]["Orlando"]["DOES_NOT_COALESCE"] = "yes"
        self.config["VERSION_CONFIG"]["Orlando"]["MAX_VM_VCPUS"] = "8"

        self.config["VERSION_CONFIG"]["George"] = {}
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_DEBIAN"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_DEBIAN_SARGE"] = "Debian Sarge 3.1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_DEBIAN_50"] = "Debian Lenny 5.0"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_41"] = "Red Hat Enterprise Linux 4.1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_44"] = "Red Hat Enterprise Linux 4.4"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7,Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5.2"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5.2 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_53"] = "Red Hat Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_RHEL_53_64"] = "Red Hat Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7,CentOS 4.6"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5.0"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5.1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5.2"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5.2 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_53"] = "CentOS 5.3"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CENTOS_53_64"] = "CentOS 5.3 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_94"] = "SUSE Linux Enterprise Server 9 SP4"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2,SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_11"] = "SUSE Linux Enterprise Server 11"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_SLES_11_64"] = "SUSE Linux Enterprise Server 11 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP,Windows XP SP2"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_VISTA"] = "Windows Vista"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WS08R2_64"] = "Windows Server 2008 R2 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WIN7"] = "Windows Server 2008"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_WIN7_64"] = "Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CPS"] = "Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["George"]["TEMPLATE_NAME_CPS_64"] = "Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["George"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["George"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["George"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["George"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["George"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["George"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["George"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["George"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["George"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["George"]["SUPPORTS_HIBERNATE"] = "no"
        self.config["VERSION_CONFIG"]["George"]["GENERIC_WINDOWS_OS"] = "ws08-x86"
        self.config["VERSION_CONFIG"]["George"]["GENERIC_WINDOWS_OS_64"] = "ws08-x64"
        self.config["VERSION_CONFIG"]["George"]["GENERIC_LINUX_OS"] = "etch"
        self.config["VERSION_CONFIG"]["George"]["GENERIC_LINUX_OS_64"] = "centos53"
        self.config["VERSION_CONFIG"]["George"]["MAX_VM_VCPUS"] = "8"
        self.config["VERSION_CONFIG"]["George"]["LATEST_rhel4"] = "rhel47"
        self.config["VERSION_CONFIG"]["George"]["LATEST_rhel5"] = "rhel53"

        self.config["VERSION_CONFIG"]["MNR"] = {}
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_DEBIAN"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_DEBIAN_50"] = "Debian Lenny 5.0 (32-bit),Debian Lenny 5.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_DEBIAN_60"] = "Debian Squeeze 6.0 (32-bit),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_DEBIAN_60_64"] = "Debian Squeeze 6.0 (64-bit),Debian Squeeze 6.0 (64-bit) (experimental),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5 (32-bit),Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6 (32-bit),Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7 (32-bit),Red Hat Enterprise Linux 4.7"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_48"] = "Red Hat Enterprise Linux 4.8 (32-bit),Red Hat Enterprise Linux 4.8"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.0 (32-bit),Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.0 (64-bit),Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.1 (32-bit),Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.1 (64-bit),Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.2 (32-bit),Red Hat Enterprise Linux 5.2"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.2 (64-bit),Red Hat Enterprise Linux 5.2 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_53"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.3 (32-bit),Red Hat Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_53_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.3 (64-bit),Red Hat Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_54"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.4 (32-bit),Red Hat Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_54_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.4 (64-bit),Red Hat Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_55"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.5 (32-bit),Red Hat Enterprise Linux 5.5,Red Hat Enterprise Linux 5.5 (32-bit),Red Hat Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_55_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.5 (64-bit),Red Hat Enterprise Linux 5.5 x64,Red Hat Enterprise Linux 5.5 (64-bit),Red Hat Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_56"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.6 (32-bit),Red Hat Enterprise Linux 5.6,Red Hat Enterprise Linux 5.6 (32-bit),Red Hat Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_56_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.6 (64-bit),Red Hat Enterprise Linux 5.6 x64,Red Hat Enterprise Linux 5.6 (64-bit),Red Hat Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_6"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_RHEL_6_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_53"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.3 (32-bit),Oracle Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_53_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.3 (64-bit),Oracle Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_54"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.4 (32-bit),Oracle Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_54_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.4 (64-bit),Oracle Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_55"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.5 (32-bit),Oracle Enterprise Linux 5.5,Oracle Enterprise Linux 5.4 (32-bit),Oracle Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_OEL_55_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.5 (64-bit),Oracle Enterprise Linux 5.5 x64,Oracle Enterprise Linux 5.4 (64-bit),Oracle Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5 (32-bit),CentOS 4.5"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6 (32-bit),CentOS 4.6"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7 (32-bit),CentOS 4.7"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_48"] = "CentOS 4.8 (32-bit),CentOS 4.8"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5 (32-bit),CentOS 5.0 (32-bit),CentOS 5.0"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5 (64-bit),CentOS 5.0 (64-bit),CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5 (32-bit),CentOS 5.1 (32-bit),CentOS 5.1"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5 (64-bit),CentOS 5.1 (64-bit),CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5 (32-bit),CentOS 5.2 (32-bit),CentOS 5.2"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5 (64-bit),CentOS 5.2 (64-bit),CentOS 5.2 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_53"] = "CentOS 5 (32-bit),CentOS 5.3 (32-bit),CentOS 5.3"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_53_64"] = "CentOS 5 (64-bit),CentOS 5.3 (64-bit),CentOS 5.3 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_54"] = "CentOS 5 (32-bit),CentOS 5.4 (32-bit),CentOS 5.4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_54_64"] = "CentOS 5 (64-bit),CentOS 5.4 (64-bit),CentOS 5.4 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_55"] = "CentOS 5 (32-bit),CentOS 5.5 (32-bit),CentOS 5.5,CentOS 5.5 (32-bit),CentOS 5.5"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CENTOS_55_64"] = "CentOS 5 (64-bit),CentOS 5.5 (64-bit),CentOS 5.5 x64,CentOS 5.5 (64-bit),CentOS 5.5 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_94"] = "SUSE Linux Enterprise Server 9 SP4 (32-bit),SUSE Linux Enterprise Server 9 SP4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1 (32-bit),SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 (64-bit),SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit),SUSE Linux Enterprise Server 10 SP2,SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 (64-bit),SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_103"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit)"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_103_64"] = "SUSE Linux Enterprise Server 10 SP3 (64-bit)"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_11"] = "SUSE Linux Enterprise Server 11 (32-bit),SUSE Linux Enterprise Server 11"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_11_64"] = "SUSE Linux Enterprise Server 11 (64-bit),SUSE Linux Enterprise Server 11 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_111"] = "SUSE Linux Enterprise Server 11 SP1 (32-bit),SUSE Linux Enterprise Server 11 SP1"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_SLES_111_64"] = "SUSE Linux Enterprise Server 11 SP1 (64-bit),SUSE Linux Enterprise Server 11 SP1 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 (64-bit),Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4 (32-bit),Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP SP2 (32-bit),Windows XP,Windows XP SP2"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP SP3 (32-bit),Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_VISTA"] = "Windows Vista (32-bit),Windows Vista"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008 (32-bit),Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 (64-bit),Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WS08R2_64"] = "Windows Server 2008 R2 (64-bit),Windows Server 2008 R2 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WIN7"] = "Windows 7 (32-bit),Windows 7,Windows Server 2008"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_WIN7_64"] = "Windows 7 (64-bit),Windows 7 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CPS"] = "Citrix XenApp on Windows Server 2003 (32-bit),Citrix XenApp on Windows Server 2003,Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CPS_64"] = "Citrix XenApp on Windows Server 2003 (64-bit),Citrix XenApp x64 on Windows Server 2003 x64,Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CPS_2008"] = "Citrix XenApp on Windows Server 2008 (32-bit),Citrix XenApp on Windows Server 2008"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CPS_2008_64"] = "Citrix XenApp on Windows Server 2008 (64-bit),Citrix XenApp x64 on Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["MNR"]["TEMPLATE_NAME_CPS_2008R2_64"] = "Citrix XenApp on Windows Server 2008 R2 (64-bit),Citrix XenApp x64 on Windows Server 2008 R2 x64"
        self.config["VERSION_CONFIG"]["MNR"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["MNR"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["MNR"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["MNR"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_HOST_MEMORY"] = "262144"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_HOST_LOG_CPUS"] = "64"
        self.config["VERSION_CONFIG"]["MNR"]["MIN_VM_MEMORY"] = "128"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VM_MEMORY"] = "32768"
        # XenServer enforced minimum memory limitations
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"] = {}
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3se"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp1"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3ser2"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp2"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3ee"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp1"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3eer2"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-x64"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-rc"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["winxpsp2"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["VM_MIN_MEMORY_LIMITS"]["winxpsp3"] = "256"
        self.config["VERSION_CONFIG"]["MNR"]["DMC_WIN_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["MNR"]["DMC_LINUX_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "1024"
        self.config["VERSION_CONFIG"]["MNR"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["MNR"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["MNR"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["MNR"]["SUPPORTS_HIBERNATE"] = "no"
        self.config["VERSION_CONFIG"]["MNR"]["GENERIC_WINDOWS_OS"] = "ws08-x86"
        self.config["VERSION_CONFIG"]["MNR"]["GENERIC_WINDOWS_OS_64"] = "ws08-x64"
        self.config["VERSION_CONFIG"]["MNR"]["GENERIC_LINUX_OS"] = "etch"
        self.config["VERSION_CONFIG"]["MNR"]["GENERIC_LINUX_OS_64"] = "centos53"
        self.config["VERSION_CONFIG"]["MNR"]["TILE_WIN_DISTRO"] = "ws08-x86"
        self.config["VERSION_CONFIG"]["MNR"]["TILE_LINUX_DISTRO"] = "centos53"
        self.config["VERSION_CONFIG"]["MNR"]["EXPECTED_CRASHDUMP_FILES"] = "crash.log,debug.log,domain0.log"
        self.config["VERSION_CONFIG"]["MNR"]["V6_DBV"] = "2010.0521"
        self.config["VERSION_CONFIG"]["MNR"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel54"
        self.config["VERSION_CONFIG"]["MNR"]["MAX_VM_VCPUS"] = "8"
        self.config["VERSION_CONFIG"]["MNR"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["MNR"]["LATEST_rhel5"] = "rhel54"
        self.config["VERSION_CONFIG"]["MNR"]["LATEST_rhel6"] = "rhel6"

        # Cowley
        self.config["VERSION_CONFIG"]["Cowley"] = self.config["VERSION_CONFIG"]["MNR"]

        # Oxford
        self.config["VERSION_CONFIG"]["Oxford"] = self.config["VERSION_CONFIG"]["MNR"]

        # Boston
        self.config["VERSION_CONFIG"]["Boston"] = {}
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_DEBIAN"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_DEBIAN_50"] = "Debian Lenny 5.0 (32-bit),Debian Lenny 5.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_DEBIAN_60"] = "Debian Squeeze 6.0 (32-bit),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_DEBIAN_60_64"] = "Debian Squeeze 6.0 (64-bit),Debian Squeeze 6.0 (64-bit) (experimental),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5 (32-bit),Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6 (32-bit),Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7 (32-bit),Red Hat Enterprise Linux 4.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_48"] = "Red Hat Enterprise Linux 4.8 (32-bit),Red Hat Enterprise Linux 4.8"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.0 (32-bit),Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.0 (64-bit),Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.1 (32-bit),Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.1 (64-bit),Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.2 (32-bit),Red Hat Enterprise Linux 5.2"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.2 (64-bit),Red Hat Enterprise Linux 5.2 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_53"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.3 (32-bit),Red Hat Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_53_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.3 (64-bit),Red Hat Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_54"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.4 (32-bit),Red Hat Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_54_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.4 (64-bit),Red Hat Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_55"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.5 (32-bit),Red Hat Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_55_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.5 (64-bit),Red Hat Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_56"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.6 (32-bit),Red Hat Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_56_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.6 (64-bit),Red Hat Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_57"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.7 (32-bit),Red Hat Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_57_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.7 (64-bit),Red Hat Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_6"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6,Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_RHEL_6_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_53"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.3 (32-bit),Oracle Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_53_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.3 (64-bit),Oracle Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_54"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.4 (32-bit),Oracle Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_54_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.4 (64-bit),Oracle Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_55"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.5 (32-bit),Oracle Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_55_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.5 (64-bit),Oracle Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_56"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.6 (32-bit),Oracle Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_56_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.6 (64-bit),Oracle Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_57"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.7 (32-bit),Oracle Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_57_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.7 (64-bit),Oracle Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_510"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.7 (32-bit),Oracle Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_510_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.7 (64-bit),Oracle Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_6"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_6_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_65"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_OEL_65_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5 (32-bit),CentOS 4.5"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6 (32-bit),CentOS 4.6"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7 (32-bit),CentOS 4.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_48"] = "CentOS 4.8 (32-bit),CentOS 4.8"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5 (32-bit),CentOS 5.0 (32-bit),CentOS 5.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5 (64-bit),CentOS 5.0 (64-bit),CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5 (32-bit),CentOS 5.1 (32-bit),CentOS 5.1"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5 (64-bit),CentOS 5.1 (64-bit),CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5 (32-bit),CentOS 5.2 (32-bit),CentOS 5.2"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5 (64-bit),CentOS 5.2 (64-bit),CentOS 5.2 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_53"] = "CentOS 5 (32-bit),CentOS 5.3 (32-bit),CentOS 5.3"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_53_64"] = "CentOS 5 (64-bit),CentOS 5.3 (64-bit),CentOS 5.3 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_54"] = "CentOS 5 (32-bit),CentOS 5.4 (32-bit),CentOS 5.4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_54_64"] = "CentOS 5 (64-bit),CentOS 5.4 (64-bit),CentOS 5.4 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_55"] = "CentOS 5 (32-bit),CentOS 5.5 (32-bit),CentOS 5.5"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_55_64"] = "CentOS 5 (64-bit),CentOS 5.5 (64-bit),CentOS 5.5 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_56"] = "CentOS 5 (32-bit),CentOS 5.6 (32-bit),CentOS 5.6,CentOS 5.6 (32-bit),CentOS 5.6"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_56_64"] = "CentOS 5 (64-bit),CentOS 5.6 (64-bit),CentOS 5.6 x64,CentOS 5.6 (64-bit),CentOS 5.6 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_57"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_57_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_6"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_6_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_63"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_63_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_64"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_64_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_65"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CENTOS_65_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_UBUNTU_1004"] = "Ubuntu Lucid Lynx 10.04 (32-bit),Ubuntu Lucid Lynx 10.04"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_UBUNTU_1004_64"] = "Ubuntu Lucid Lynx 10.04 (64-bit),Ubuntu Lucid Lynx 10.04 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_94"] = "SUSE Linux Enterprise Server 9 SP4 (32-bit),SUSE Linux Enterprise Server 9 SP4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1 (32-bit),SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 (64-bit),SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit),SUSE Linux Enterprise Server 10 SP2"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 (64-bit),SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_103"] = "SUSE Linux Enterprise Server 10 SP3 (32-bit), SUSE Linux Enterprise Server 10 SP3"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_103_64"] = "SUSE Linux Enterprise Server 10 SP3 (64-bit), SUSE Linux Enterprise Server 10 SP3 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_104"] = "SUSE Linux Enterprise Server 10 SP4 (32-bit),SUSE Linux Enterprise Server 10 SP4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_104_64"] = "SUSE Linux Enterprise Server 10 SP4 (64-bit),SUSE Linux Enterprise Server 10 SP4 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_11"] = "SUSE Linux Enterprise Server 11 (32-bit),SUSE Linux Enterprise Server 11"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_11_64"] = "SUSE Linux Enterprise Server 11 (64-bit),SUSE Linux Enterprise Server 11 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_111"] = "SUSE Linux Enterprise Server 11 SP1 (32-bit),SUSE Linux Enterprise Server 11 SP1"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SLES_111_64"] = "SUSE Linux Enterprise Server 11 SP1 (64-bit),SUSE Linux Enterprise Server 11 SP1 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SOLARIS_10U9_32"] = "Solaris 10 (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_SOLARIS_10U9"] = "Solaris 10 (experimental)"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 (64-bit),Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4 (32-bit),Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_2003_PAE"] = "Windows Server 2003 PAE (4 cores per socket) (32-bit),Windows Server 2003 PAE (32-bit),Windows Server 2003 PAE"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP SP2 (32-bit),Windows XP,Windows XP SP2"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP SP3 (32-bit),Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_VISTA"] = "Windows Vista (32-bit),Windows Vista"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008 (32-bit),Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 (64-bit),Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WS08R2_64"] = "Windows Server 2008 R2 (64-bit),Windows Server 2008 R2 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WIN7"] = "Windows 7 (32-bit),Windows 7,Windows Server 2008"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_WIN7_64"] = "Windows 7 (64-bit),Windows 7 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CPS"] = "Citrix XenApp on Windows Server 2003 (32-bit),Citrix XenApp on Windows Server 2003,Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CPS_64"] = "Citrix XenApp on Windows Server 2003 (64-bit),Citrix XenApp x64 on Windows Server 2003 x64,Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CPS_2008"] = "Citrix XenApp on Windows Server 2008 (32-bit),Citrix XenApp on Windows Server 2008"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CPS_2008_64"] = "Citrix XenApp on Windows Server 2008 (64-bit),Citrix XenApp x64 on Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Boston"]["TEMPLATE_NAME_CPS_2008R2_64"] = "Citrix XenApp on Windows Server 2008 R2 (64-bit),Citrix XenApp x64 on Windows Server 2008 R2 x64"
        self.config["VERSION_CONFIG"]["Boston"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["Boston"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Boston"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["Boston"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_HOST_MEMORY"] = "1048576"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_HOST_LOG_CPUS"] = "64"
        self.config["VERSION_CONFIG"]["Boston"]["MIN_VM_MEMORY"] = "128"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VM_MEMORY"] = "131072"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VM_MEMORY_LINUX32BIT"] = "65536"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VM_VCPUS"] = "16"
        # XenServer enforced minimum memory limitations
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"] = {}
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2pae"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3se"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp1"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3ser2"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp2"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3ee"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp1"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eer2"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-x64"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-rc"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["winxpsp2"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["VM_MIN_MEMORY_LIMITS"]["winxpsp3"] = "256"
        self.config["VERSION_CONFIG"]["Boston"]["DMC_WIN_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Boston"]["DMC_LINUX_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_VDIS_PER_SR_equal"] = "900"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "1024"
        self.config["VERSION_CONFIG"]["Boston"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "900"
        self.config["VERSION_CONFIG"]["Boston"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["Boston"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["Boston"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["Boston"]["SUPPORTS_HIBERNATE"] = "no"
        self.config["VERSION_CONFIG"]["Boston"]["GENERIC_WINDOWS_OS"] = "ws08-x86"
        self.config["VERSION_CONFIG"]["Boston"]["GENERIC_WINDOWS_OS_64"] = "ws08-x64"
        self.config["VERSION_CONFIG"]["Boston"]["GENERIC_LINUX_OS"] = "etch"
        self.config["VERSION_CONFIG"]["Boston"]["GENERIC_LINUX_OS_64"] = "centos54"
        self.config["VERSION_CONFIG"]["Boston"]["TILE_WIN_DISTRO"] = "ws08-x86"
        self.config["VERSION_CONFIG"]["Boston"]["TILE_LINUX_DISTRO"] = "centos54"
        self.config["VERSION_CONFIG"]["Boston"]["EXPECTED_CRASHDUMP_FILES"] = "crash.log,debug.log,domain0.log"
        self.config["VERSION_CONFIG"]["Boston"]["V6_DBV"] = "2010.0521"
        self.config["VERSION_CONFIG"]["Boston"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel56"
        self.config["VERSION_CONFIG"]["Boston"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Boston"]["LATEST_rhel5"] = "rhel56"
        self.config["VERSION_CONFIG"]["Boston"]["LATEST_rhel6"] = "rhel6"
        self.config["VERSION_CONFIG"]["Boston"]["EARLY_PV_LINUX"] = "rhel5\d*,rhel6\d*,centos5\d*,centos6\d*,sl5\d,sl6\d,debian60"
        self.config["VERSION_CONFIG"]["Boston"]["DOM0_PARTITIONS"] = {1:4*xenrt.GIGA, 2:4*xenrt.GIGA, 3:"*"}
        self.config["VERSION_CONFIG"]["Boston"]["INTERNAL_RPU_HOTFIX"] = "XS62E006.xsupdate"

        # XCP Derived from Boston Release
        self.config["VERSION_CONFIG"]["BostonXCP"] = self.config["VERSION_CONFIG"]["Boston"]
        # Sanibel
        self.config["VERSION_CONFIG"]["Sanibel"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Boston"])
        # 2008 SP0 is deprecated in Sanibel, so use SP2
        self.config["VERSION_CONFIG"]["Sanibel"]["GENERIC_WINDOWS_OS"] = "ws08sp2-x86"
        self.config["VERSION_CONFIG"]["Sanibel"]["GENERIC_WINDOWS_OS_64"] = "ws08sp2-x64"
        self.config["VERSION_CONFIG"]["Sanibel"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel57"
        self.config["VERSION_CONFIG"]["Sanibel"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Sanibel"]["LATEST_rhel5"] = "rhel57"
        self.config["VERSION_CONFIG"]["Sanibel"]["LATEST_rhel6"] = "rhel61"

        self.config["VERSION_CONFIG"]["SanibelCC"] = self.config["VERSION_CONFIG"]["Sanibel"]
        
        self.config["VERSION_CONFIG"]["Tampa"] = {}
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "Demo Linux VM,Debian Etch 4.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_50"] = "Debian Lenny 5.0 (32-bit),Debian Lenny 5.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_60"] = "Debian Squeeze 6.0 (32-bit),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_60_64"] = "Debian Squeeze 6.0 (64-bit),Debian Squeeze 6.0 (64-bit) (experimental),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_70"] = "Debian Wheezy 7.0 (32-bit),Debian Wheezy 7.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_DEBIAN_70_64"] = "Debian Wheezy 7.0 (64-bit),Debian Wheezy 7.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5 (32-bit),Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6 (32-bit),Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7 (32-bit),Red Hat Enterprise Linux 4.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_48"] = "Red Hat Enterprise Linux 4.8 (32-bit),Red Hat Enterprise Linux 4.8"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.0 (32-bit),Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.0 (64-bit),Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.1 (32-bit),Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.1 (64-bit),Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.2 (32-bit),Red Hat Enterprise Linux 5.2"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.2 (64-bit),Red Hat Enterprise Linux 5.2 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_53"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.3 (32-bit),Red Hat Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_53_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.3 (64-bit),Red Hat Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_54"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.4 (32-bit),Red Hat Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_54_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.4 (64-bit),Red Hat Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_55"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.5 (32-bit),Red Hat Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_55_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.5 (64-bit),Red Hat Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_56"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.6 (32-bit),Red Hat Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_56_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.6 (64-bit),Red Hat Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_57"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.7 (32-bit),Red Hat Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_57_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.7 (64-bit),Red Hat Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_6"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6,Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_RHEL_6_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_53"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.3 (32-bit),Oracle Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_53_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.3 (64-bit),Oracle Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_54"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.4 (32-bit),Oracle Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_54_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.4 (64-bit),Oracle Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_55"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.5 (32-bit),Oracle Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_55_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.5 (64-bit),Oracle Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_56"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.6 (32-bit),Oracle Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_56_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.6 (64-bit),Oracle Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_57"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.7 (32-bit),Oracle Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_57_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.7 (64-bit),Oracle Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_58"] = "Oracle Enterprise Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_58_64"] = "Oracle Enterprise Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_59"] = "Oracle Enterprise Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_59_64"] = "Oracle Enterprise Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_510"] = "Oracle Enterprise Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_510_64"] = "Oracle Enterprise Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_6"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_6_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_65"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_OEL_65_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5 (32-bit),CentOS 4.5"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6 (32-bit),CentOS 4.6"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7 (32-bit),CentOS 4.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_48"] = "CentOS 4.8 (32-bit),CentOS 4.8"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5 (32-bit),CentOS 5.0 (32-bit),CentOS 5.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5 (64-bit),CentOS 5.0 (64-bit),CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5 (32-bit),CentOS 5.1 (32-bit),CentOS 5.1"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5 (64-bit),CentOS 5.1 (64-bit),CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5 (32-bit),CentOS 5.2 (32-bit),CentOS 5.2"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5 (64-bit),CentOS 5.2 (64-bit),CentOS 5.2 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_53"] = "CentOS 5 (32-bit),CentOS 5.3 (32-bit),CentOS 5.3"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_53_64"] = "CentOS 5 (64-bit),CentOS 5.3 (64-bit),CentOS 5.3 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_54"] = "CentOS 5 (32-bit),CentOS 5.4 (32-bit),CentOS 5.4"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_54_64"] = "CentOS 5 (64-bit),CentOS 5.4 (64-bit),CentOS 5.4 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_55"] = "CentOS 5 (32-bit),CentOS 5.5 (32-bit),CentOS 5.5"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_55_64"] = "CentOS 5 (64-bit),CentOS 5.5 (64-bit),CentOS 5.5 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_56"] = "CentOS 5 (32-bit),CentOS 5.6 (32-bit),CentOS 5.6,CentOS 5.6 (32-bit),CentOS 5.6"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_56_64"] = "CentOS 5 (64-bit),CentOS 5.6 (64-bit),CentOS 5.6 x64,CentOS 5.6 (64-bit),CentOS 5.6 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_57"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_57_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_510"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_510_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_6"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CENTOS_6_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_UBUNTU_1004"] = "Ubuntu Lucid Lynx 10.04 (32-bit), Ubuntu Lucid Lynx 10.04"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_UBUNTU_1004_64"] = "Ubuntu Lucid Lynx 10.04 (64-bit), Ubuntu Lucid Lynx 10.04 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_UBUNTU_1204"] = "Ubuntu Precise Pangolin 12.04 (32-bit),Ubuntu Precise Pangolin 12.04"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_UBUNTU_1204_64"] = "Ubuntu Precise Pangolin 12.04 (64-bit),Ubuntu Precise Pangolin 12.04 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1 (32-bit),SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 (64-bit),SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit),SUSE Linux Enterprise Server 10 SP2"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 (64-bit),SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_103"] = "SUSE Linux Enterprise Server 10 SP3 (32-bit), SUSE Linux Enterprise Server 10 SP3"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_103_64"] = "SUSE Linux Enterprise Server 10 SP3 (64-bit), SUSE Linux Enterprise Server 10 SP3 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_104"] = "SUSE Linux Enterprise Server 10 SP4 (32-bit),SUSE Linux Enterprise Server 10 SP4"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_104_64"] = "SUSE Linux Enterprise Server 10 SP4 (64-bit),SUSE Linux Enterprise Server 10 SP4 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_11"] = "SUSE Linux Enterprise Server 11 (32-bit),SUSE Linux Enterprise Server 11"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_11_64"] = "SUSE Linux Enterprise Server 11 (64-bit),SUSE Linux Enterprise Server 11 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_111"] = "SUSE Linux Enterprise Server 11 SP1 (32-bit),SUSE Linux Enterprise Server 11 SP1"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_111_64"] = "SUSE Linux Enterprise Server 11 SP1 (64-bit),SUSE Linux Enterprise Server 11 SP1 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_112"] = "SUSE Linux Enterprise Server 11 SP2 (32-bit),SUSE Linux Enterprise Server 11 SP2"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SLES_112_64"] = "SUSE Linux Enterprise Server 11 SP2 (64-bit),SUSE Linux Enterprise Server 11 SP2 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SOLARIS_10U9_32"] = "Solaris 10 (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_SOLARIS_10U9"] = "Solaris 10 (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 (64-bit),Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WINDOWS_2000"] = "Windows 2000 SP4 (32-bit),Windows 2000 SP4"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WINDOWS_XP"] = "Windows XP SP2 (32-bit),Windows XP,Windows XP SP2"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP SP3 (32-bit),Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_VISTA"] = "Windows Vista (32-bit),Windows Vista"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008 (32-bit),Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 (64-bit),Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WS08R2_64"] = "Windows Server 2008 R2 (64-bit),Windows Server 2008 R2 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WIN7"] = "Windows 7 (32-bit),Windows 7,Windows Server 2008"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WIN7_64"] = "Windows 7 (64-bit),Windows 7 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WIN8"] = "Windows 8 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WIN8_64"] = "Windows 8 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_WS12_64"] = "Windows Server 2012 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CPS"] = "Citrix XenApp on Windows Server 2003 (32-bit),Citrix XenApp on Windows Server 2003,Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CPS_64"] = "Citrix XenApp on Windows Server 2003 (64-bit),Citrix XenApp x64 on Windows Server 2003 x64,Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CPS_2008"] = "Citrix XenApp on Windows Server 2008 (32-bit),Citrix XenApp on Windows Server 2008"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CPS_2008_64"] = "Citrix XenApp on Windows Server 2008 (64-bit),Citrix XenApp x64 on Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["TEMPLATE_NAME_CPS_2008R2_64"] = "Citrix XenApp on Windows Server 2008 R2 (64-bit),Citrix XenApp x64 on Windows Server 2008 R2 x64"
        self.config["VERSION_CONFIG"]["Tampa"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["Tampa"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Tampa"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["Tampa"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_HOST_MEMORY"] = "1048576"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_HOST_LOG_CPUS"] = "64"
        self.config["VERSION_CONFIG"]["Tampa"]["MIN_VM_MEMORY"] = "128"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VM_MEMORY"] = "131072"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VM_MEMORY_LINUX32BIT"] = "65536"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VM_VCPUS"] = "16"
        # XenServer enforced minimum memory limitations
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"] = {}
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2pae"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3se"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp1"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3ser2"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp2"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3ee"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp1"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eer2"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-x64"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-rc"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["winxpsp2"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["VM_MIN_MEMORY_LIMITS"]["winxpsp3"] = "256"
        self.config["VERSION_CONFIG"]["Tampa"]["DMC_WIN_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Tampa"]["DMC_LINUX_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_CONCURRENT_VMS"] = "75"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_ext"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_lvm"] = "512"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_nfs"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_SR_equal"] = "900"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "512"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "900"
        self.config["VERSION_CONFIG"]["Tampa"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["Tampa"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["Tampa"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["Tampa"]["SUPPORTS_HIBERNATE"] = "no"
        self.config["VERSION_CONFIG"]["Tampa"]["GENERIC_WINDOWS_OS"] = "ws08sp2-x86"
        self.config["VERSION_CONFIG"]["Tampa"]["GENERIC_WINDOWS_OS_64"] = "ws08sp2-x64"
        self.config["VERSION_CONFIG"]["Tampa"]["GENERIC_LINUX_OS"] = "debian60"
        self.config["VERSION_CONFIG"]["Tampa"]["GENERIC_LINUX_OS_64"] = "centos57"
        self.config["VERSION_CONFIG"]["Tampa"]["TILE_WIN_DISTRO"] = "ws08sp2-x86"
        self.config["VERSION_CONFIG"]["Tampa"]["TILE_LINUX_DISTRO"] = "centos57"
        self.config["VERSION_CONFIG"]["Tampa"]["EARLY_PV_LINUX"] = "rhel5\d*,rhel6\d*,centos5\d*,centos6\d*,sl5\d,sl6\d,debian60"
        self.config["VERSION_CONFIG"]["Tampa"]["EXPECTED_CRASHDUMP_FILES"] = "xen-crashdump-analyser.log,xen.log,dom0.log"
        self.config["VERSION_CONFIG"]["Tampa"]["V6_DBV"] = "2010.0521"
        self.config["VERSION_CONFIG"]["Tampa"]["IDLE_VMs_DOM0_CPU_Utilize"] = "260"
        # XenServer dom0 partitions
        self.config["VERSION_CONFIG"]["Tampa"]["DOM0_PARTITIONS"] = {1:4*xenrt.GIGA, 2:4*xenrt.GIGA, 3:"*"}
        self.config["VERSION_CONFIG"]["Tampa"]["INTERNAL_RPU_HOTFIX"] = "XS62E006.xsupdate"
        
        # CHECKME: Need to fix this (Tallahassee is rolled into Tampa)
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDIS_PER_VM"] = "15"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDI_SIZE_NFS"] = "2093058"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VDI_SIZE_LVM"] = "2097152"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_CONCURRENT_VMS"] = "150"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_MEM_PV64"] = "131072"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_MEM_HVM"] = "131072"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_MEM_PV32"] = "65536"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VCPU_COUNT"] = "900"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_MULTIPATH_LUN"] = "150"
        self.config["VERSION_CONFIG"]["Tampa"]["CONCURRENT_MAX_MULTIPATH_LUN"] = "75"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_HOSTS_PER_POOL"] = "16"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VLANS_PER_HOST_LINUX"] = "800"
        self.config["VERSION_CONFIG"]["Tampa"]["MAX_VLANS_PER_HOST_VSWITCH"] = "800"
        self.config["VERSION_CONFIG"]["Tampa"]["VIF_PER_VM"] = "2"
        self.config["VERSION_CONFIG"]["Tampa"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel57"
        self.config["VERSION_CONFIG"]["Tampa"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Tampa"]["LATEST_rhel5"] = "rhel58"
        self.config["VERSION_CONFIG"]["Tampa"]["LATEST_rhel6"] = "rhel62"


        # XCP Derived from Tampa Release
        self.config["VERSION_CONFIG"]["TampaXCP"] = self.config["VERSION_CONFIG"]["Tampa"]

        # Tallahassee
        #self.config["VERSION_CONFIG"]["Tallahassee"] = self.config["VERSION_CONFIG"]["Tampa"]
        self.config["VERSION_CONFIG"]["Tallahassee"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Tampa"])
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VDIS_PER_VM"] = "15"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VDI_SIZE_NFS"] = "2093058"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VDI_SIZE_LVM"] = "2097152"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VDIS_PER_SR_lvm"] = "512"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "512"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_CONCURRENT_VMS"] = "150"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_MEM_PV64"] = "131072"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_MEM_HVM"] = "131072"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_MEM_PV32"] = "65536"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VCPU_COUNT"] = "900"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_MULTIPATH_LUN"] = "150"
        self.config["VERSION_CONFIG"]["Tallahassee"]["CONCURRENT_MAX_MULTIPATH_LUN"] = "75"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_HOSTS_PER_POOL"] = "16"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VLANS_PER_HOST_LINUX"] = "800"
        self.config["VERSION_CONFIG"]["Tallahassee"]["MAX_VLANS_PER_HOST_VSWITCH"] = "800"
        self.config["VERSION_CONFIG"]["Tallahassee"]["VIF_PER_VM"] = "2"
        
        # Clearwater
        self.config["VERSION_CONFIG"]["Clearwater"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Tampa"])
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_lvm"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_nfs"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_ext"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_lvm"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_SR_equal"] = "600"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDIS_PER_VM"] = "15"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDI_SIZE_NFS"] = "2093058"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VDI_SIZE_LVM"] = "2093051"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_MEM_PV64"] = "131072"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_MEM_HVM"] = "131072"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_MEM_PV32"] = "65536"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VCPU_COUNT"] = "900"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_MULTIPATH_LUN"] = "150"
        self.config["VERSION_CONFIG"]["Clearwater"]["CONCURRENT_MAX_MULTIPATH_LUN"] = "75"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_HOSTS_PER_POOL"] = "16"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VLANS_PER_HOST_LINUX"] = "800"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VLANS_PER_HOST_VSWITCH"] = "800"
        self.config["VERSION_CONFIG"]["Clearwater"]["VIF_PER_VM"] = "7"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_CONCURRENT_VMS"] = "500"
        self.config["VERSION_CONFIG"]["Clearwater"]["LOCAL_DISK_TiB"] = "6"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_WIN8"] = "Windows 8 (32-bit),Windows 8 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_WIN8_64"] = "Windows 8 (64-bit),Windows 8 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_WS12_64"] = "Windows Server 2012 (64-bit),Windows Server 2012 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_RHEL_7_64"] = "Other install media"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_CENTOS_7_64"] = "Other install media"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_OEL_7_64"] = "Other install media"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_SLES_12_64"] = "Other install media"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_UBUNTU_1404"] = "Other install media"
        self.config["VERSION_CONFIG"]["Clearwater"]["TEMPLATE_NAME_UBUNTU_1404_64"] = "Other install media" 
        self.config["VERSION_CONFIG"]["Clearwater"]["V6_DBV"] = "2013.0621"
        self.config["VERSION_CONFIG"]["Clearwater"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel64"
        self.config["VERSION_CONFIG"]["Clearwater"]["MAX_VBDS_PER_HOST"] = "2048"
        self.config["VERSION_CONFIG"]["Clearwater"]["HVM_LINUX"] = "rhel7,centos7,oel7,ubuntu1404"
        self.config["VERSION_CONFIG"]["Clearwater"]["GENERIC_LINUX_OS"] = "debian70"
        self.config["VERSION_CONFIG"]["Clearwater"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Clearwater"]["LATEST_rhel5"] = "rhel59"
        self.config["VERSION_CONFIG"]["Clearwater"]["LATEST_rhel6"] = "rhel64"

        
        # Creedence
        self.config["VERSION_CONFIG"]["Creedence"] = {}
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_60"] = "Debian Squeeze 6.0 (32-bit),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_60_64"] = "Debian Squeeze 6.0 (64-bit),Debian Squeeze 6.0 (64-bit) (experimental),Debian Squeeze 6.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_70"] = "Debian Wheezy 7.0 (32-bit),Debian Wheezy 7.0,Debian Wheezy 7.0 (32-bit),Debian Wheezy 7.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_70_64"] = "Debian Wheezy 7.0 (64-bit),Debian Wheezy 7.0,Debian Wheezy 7.0 (64-bit),Debian Wheezy 7.0"
        # TODO Update these to Debian Jessie templates when they exist
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_80"] = "Debian Jessie 8.0,Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_80_64"] = "Debian Jessie 8.0,Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_TESTING"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_DEBIAN_TESTING_64"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_45"] = "Red Hat Enterprise Linux 4.5 (32-bit),Red Hat Enterprise Linux 4.5"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_46"] = "Red Hat Enterprise Linux 4.6 (32-bit),Red Hat Enterprise Linux 4.6"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_47"] = "Red Hat Enterprise Linux 4.7 (32-bit),Red Hat Enterprise Linux 4.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_48"] = "Red Hat Enterprise Linux 4.8 (32-bit),Red Hat Enterprise Linux 4.8"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_5"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.0 (32-bit),Red Hat Enterprise Linux 5.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_5_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.0 (64-bit),Red Hat Enterprise Linux 5.0 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_51"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.1 (32-bit),Red Hat Enterprise Linux 5.1"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_51_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.1 (64-bit),Red Hat Enterprise Linux 5.1 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_52"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.2 (32-bit),Red Hat Enterprise Linux 5.2"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_52_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.2 (64-bit),Red Hat Enterprise Linux 5.2 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_53"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.3 (32-bit),Red Hat Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_53_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.3 (64-bit),Red Hat Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_54"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.4 (32-bit),Red Hat Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_54_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.4 (64-bit),Red Hat Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_55"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.5 (32-bit),Red Hat Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_55_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.5 (64-bit),Red Hat Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_56"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.6 (32-bit),Red Hat Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_56_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.6 (64-bit),Red Hat Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_57"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.7 (32-bit),Red Hat Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_57_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.7 (64-bit),Red Hat Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_510"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.7 (32-bit),Red Hat Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_510_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.7 (64-bit),Red Hat Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_511"] = "Red Hat Enterprise Linux 5 (32-bit),Red Hat Enterprise Linux 5.7 (32-bit),Red Hat Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_511_64"] = "Red Hat Enterprise Linux 5 (64-bit),Red Hat Enterprise Linux 5.7 (64-bit),Red Hat Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_6"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6,Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_6_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_65"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6,Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_65_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_66"] = "Red Hat Enterprise Linux 6 (32-bit),Red Hat Enterprise Linux 6,Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_66_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_RHEL_7_64"] = "Red Hat Enterprise Linux 7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_53"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.3 (32-bit),Oracle Enterprise Linux 5.3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_53_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.3 (64-bit),Oracle Enterprise Linux 5.3 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_54"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.4 (32-bit),Oracle Enterprise Linux 5.4"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_54_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.4 (64-bit),Oracle Enterprise Linux 5.4 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_55"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.5 (32-bit),Oracle Enterprise Linux 5.5"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_55_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.5 (64-bit),Oracle Enterprise Linux 5.5 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_56"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.6 (32-bit),Oracle Enterprise Linux 5.6"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_56_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.6 (64-bit),Oracle Enterprise Linux 5.6 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_57"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.7 (32-bit),Oracle Enterprise Linux 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_57_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.7 (64-bit),Oracle Enterprise Linux 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_58"] = "Oracle Enterprise Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_58_64"] = "Oracle Enterprise Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_59"] = "Oracle Enterprise Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_59_64"] = "Oracle Enterprise Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_510"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.10 (32-bit),Oracle Enterprise Linux 5.10"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_510_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.10 (64-bit),Oracle Enterprise Linux 5.10 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_511"] = "Oracle Enterprise Linux 5 (32-bit),Oracle Enterprise Linux 5.10 (32-bit),Oracle Enterprise Linux 5.10"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_511_64"] = "Oracle Enterprise Linux 5 (64-bit),Oracle Enterprise Linux 5.10 (64-bit),Oracle Enterprise Linux 5.10 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_6"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_6_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_65"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_65_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_66"] = "Oracle Enterprise Linux 6 (32-bit),Oracle Enterprise Linux 6,Oracle Enterprise Linux 6 (32-bit) (experimental),Oracle Enterprise Linux 6.0 (32-bit),Oracle Enterprise Linux 6.0,Oracle Enterprise Linux 6.0 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_66_64"] = "Oracle Enterprise Linux 6 (64-bit),Oracle Enterprise Linux 6 x64,Oracle Enterprise Linux 6 (64-bit) (experimental),Oracle Enterprise Linux 6.0 (64-bit),Oracle Enterprise Linux 6.0 x64,Oracle Enterprise Linux 6.0 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_OEL_7_64"] = "Oracle Linux 7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_45"] = "CentOS 4.5 (32-bit),CentOS 4.5"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_46"] = "CentOS 4.6 (32-bit),CentOS 4.6"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_47"] = "CentOS 4.7 (32-bit),CentOS 4.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_48"] = "CentOS 4.8 (32-bit),CentOS 4.8"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_5"] = "CentOS 5 (32-bit),CentOS 5.0 (32-bit),CentOS 5.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_5_64"] = "CentOS 5 (64-bit),CentOS 5.0 (64-bit),CentOS 5.0 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_51"] = "CentOS 5 (32-bit),CentOS 5.1 (32-bit),CentOS 5.1"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_51_64"] = "CentOS 5 (64-bit),CentOS 5.1 (64-bit),CentOS 5.1 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_52"] = "CentOS 5 (32-bit),CentOS 5.2 (32-bit),CentOS 5.2"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_52_64"] = "CentOS 5 (64-bit),CentOS 5.2 (64-bit),CentOS 5.2 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_53"] = "CentOS 5 (32-bit),CentOS 5.3 (32-bit),CentOS 5.3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_53_64"] = "CentOS 5 (64-bit),CentOS 5.3 (64-bit),CentOS 5.3 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_54"] = "CentOS 5 (32-bit),CentOS 5.4 (32-bit),CentOS 5.4"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_54_64"] = "CentOS 5 (64-bit),CentOS 5.4 (64-bit),CentOS 5.4 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_55"] = "CentOS 5 (32-bit),CentOS 5.5 (32-bit),CentOS 5.5"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_55_64"] = "CentOS 5 (64-bit),CentOS 5.5 (64-bit),CentOS 5.5 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_56"] = "CentOS 5 (32-bit),CentOS 5.6 (32-bit),CentOS 5.6,CentOS 5.6 (32-bit),CentOS 5.6"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_56_64"] = "CentOS 5 (64-bit),CentOS 5.6 (64-bit),CentOS 5.6 x64,CentOS 5.6 (64-bit),CentOS 5.6 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_57"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_57_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_510"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_510_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_511"] = "CentOS 5 (32-bit),CentOS 5.7 (32-bit),CentOS 5.7,CentOS 5.7 (32-bit),CentOS 5.7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_511_64"] = "CentOS 5 (64-bit),CentOS 5.7 (64-bit),CentOS 5.7 x64,CentOS 5.7 (64-bit),CentOS 5.7 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_6"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_6_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_65"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_65_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_66"] = "CentOS 6 (32-bit),CentOS 6.0 (32-bit),CentOS 6.0,CentOS 6.0 (32-bit),CentOS 6.0"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_66_64"] = "CentOS 6 (64-bit),CentOS 6.0 (64-bit),CentOS 6.0 x64,CentOS 6.0 (64-bit),CentOS 6.0 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CENTOS_7_64"] = "CentOS 7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_FEDORA"] = "CentOS 7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_COREOS"] = "CoreOS,CoreOS (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1004"] = "Ubuntu Lucid Lynx 10.04 (32-bit), Ubuntu Lucid Lynx 10.04"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1004_64"] = "Ubuntu Lucid Lynx 10.04 (64-bit), Ubuntu Lucid Lynx 10.04 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1010"] = "Ubuntu Maverick Meerkat 10.10 (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1010_64"] = "Ubuntu Maverick Meerkat 10.10 (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1204"] = "Ubuntu Precise Pangolin 12.04 (32-bit),Ubuntu Precise Pangolin 12.04"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1204_64"] = "Ubuntu Precise Pangolin 12.04 (64-bit),Ubuntu Precise Pangolin 12.04 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1404"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_1404_64"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_DEVEL"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UBUNTU_DEVEL_64"] = "Ubuntu Trusty Tahr 14.04,Ubuntu Trusty Tahr 14.04 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_OTHER_MEDIA"] = "Other install media"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_101"] = "SUSE Linux Enterprise Server 10 SP1 (32-bit),SUSE Linux Enterprise Server 10 SP1"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_101_64"] = "SUSE Linux Enterprise Server 10 SP1 (64-bit),SUSE Linux Enterprise Server 10 SP1 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_102"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit),SUSE Linux Enterprise Server 10 SP2"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_102_64"] = "SUSE Linux Enterprise Server 10 SP2 (64-bit),SUSE Linux Enterprise Server 10 SP2 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_103"] = "SUSE Linux Enterprise Server 10 SP3 (32-bit), SUSE Linux Enterprise Server 10 SP3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_103_64"] = "SUSE Linux Enterprise Server 10 SP3 (64-bit), SUSE Linux Enterprise Server 10 SP3 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_104"] = "SUSE Linux Enterprise Server 10 SP4 (32-bit),SUSE Linux Enterprise Server 10 SP4"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_104_64"] = "SUSE Linux Enterprise Server 10 SP4 (64-bit),SUSE Linux Enterprise Server 10 SP4 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_11"] = "SUSE Linux Enterprise Server 11 (32-bit),SUSE Linux Enterprise Server 11"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_11_64"] = "SUSE Linux Enterprise Server 11 (64-bit),SUSE Linux Enterprise Server 11 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_111"] = "SUSE Linux Enterprise Server 11 SP1 (32-bit),SUSE Linux Enterprise Server 11 SP1"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_111_64"] = "SUSE Linux Enterprise Server 11 SP1 (64-bit),SUSE Linux Enterprise Server 11 SP1 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_112"] = "SUSE Linux Enterprise Server 11 SP2 (32-bit),SUSE Linux Enterprise Server 11 SP2"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_112_64"] = "SUSE Linux Enterprise Server 11 SP2 (64-bit),SUSE Linux Enterprise Server 11 SP2 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_113"] = "SUSE Linux Enterprise Server 11 SP3 (32-bit),SUSE Linux Enterprise Server 11 SP3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_113_64"] = "SUSE Linux Enterprise Server 11 SP3 (64-bit),SUSE Linux Enterprise Server 11 SP3 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SLES_12_64"] = "SUSE Linux Enterprise Server 12 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SL_511"] = "Scientific Linux 5 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SL_511_64"] = "Scientific Linux 5 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SL_66"] = "Scientific Linux 6 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SL_66_64"] = "Scientific Linux 6 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SL_7_64"] = "Scientific Linux 7"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "Windows Server 2003 (64-bit),Windows Server 2003 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WINDOWS_2003"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "Windows XP SP3 (32-bit),Windows XP,Windows XP SP3"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_UNSUPPORTED_HVM"] = "Windows Server 2003 (32-bit),Windows Server 2003"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_VISTA"] = "Windows Vista (32-bit),Windows Vista"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS08"] = "Windows Server 2008 (32-bit),Windows Server 2008,Windows Vista"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS08_64"] = "Windows Server 2008 (64-bit),Windows Server 2008 x64,Windows Vista"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS08R2_64"] = "Windows Server 2008 R2 (64-bit),Windows Server 2008 R2 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN7"] = "Windows 7 (32-bit),Windows 7,Windows Server 2008"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN7_64"] = "Windows 7 (64-bit),Windows 7 x64,Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN8"] = "Windows 8 (32-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN8_64"] = "Windows 8 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN10"] = "Windows 10 (32-bit),Windows 10 Preview (32-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WIN10_64"] = "Windows 10 (64-bit),Windows 10 Preview (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS12_64"] = "Windows Server 2012 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS12R2_64"] = "Windows Server 2012 R2 (64-bit)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_WS10_64"] = "Windows Server 10 Preview (64-bit) (experimental)"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CPS"] = "Citrix XenApp on Windows Server 2003 (32-bit),Citrix XenApp on Windows Server 2003,Citrix Presentation Server,Citrix XenApp"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CPS_64"] = "Citrix XenApp on Windows Server 2003 (64-bit),Citrix XenApp x64 on Windows Server 2003 x64,Citrix Presentation Server x64,Citrix XenApp x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CPS_2008"] = "Citrix XenApp on Windows Server 2008 (32-bit),Citrix XenApp on Windows Server 2008"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CPS_2008_64"] = "Citrix XenApp on Windows Server 2008 (64-bit),Citrix XenApp x64 on Windows Server 2008 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_CPS_2008R2_64"] = "Citrix XenApp on Windows Server 2008 R2 (64-bit),Citrix XenApp x64 on Windows Server 2008 R2 x64"
        self.config["VERSION_CONFIG"]["Creedence"]["TEMPLATE_NAME_SDK"] = "Xen API SDK"
        self.config["VERSION_CONFIG"]["Creedence"]["HVM_LINUX"] = "rhel7\d*,centos7\d*,oel7\d*,ubuntu1404,debian80,debiantesting,ubuntudevel,sl7\d*,fedora.*"
        self.config["VERSION_CONFIG"]["Creedence"]["NMAP_ALLOWED_PORTS"] = "tcp/22 tcp/443 tcp/80 (tcp/1311)"
        self.config["VERSION_CONFIG"]["Creedence"]["CLI_SERVER_FLAG"] = "-s"
        self.config["VERSION_CONFIG"]["Creedence"]["DOM0_DISTRO"] = "centos51"
        self.config["VERSION_CONFIG"]["Creedence"]["EXPFAIL_HIBERNATE"] = "none"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_HOST_MEMORY"] = "1048576"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_HOST_LOG_CPUS"] = "64"
        self.config["VERSION_CONFIG"]["Creedence"]["MIN_VM_MEMORY"] = "128"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VM_MEMORY"] = "131072"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VM_MEMORY_LINUX32BIT"] = "65536"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VM_VCPUS"] = "32"
        # XenServer enforced minimum memory limitations
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"] = {}
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2pae"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3se"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp1"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3ser2"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3sesp2"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3ee"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp1"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eer2"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-x64"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["w2k3eesp2-rc"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["winxpsp2"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["VM_MIN_MEMORY_LIMITS"]["winxpsp3"] = "256"
        self.config["VERSION_CONFIG"]["Creedence"]["DMC_WIN_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Creedence"]["DMC_LINUX_PERCENT"] = "25"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_CONCURRENT_VMS"] = "500"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_CONCURRENT_VIFS"] = "1050"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_ext"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_lvm"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_nfs"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_lvmoiscsi"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_SR_equal"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_ext"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_lvm"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_nfs"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_lvmoiscsi"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_netapp"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_ATTACHED_VDIS_PER_SR_equal"] = "600"
        self.config["VERSION_CONFIG"]["Creedence"]["VCPU_IS_SINGLE_CORE"] = "yes"
        self.config["VERSION_CONFIG"]["Creedence"]["GUEST_VIFS_rhel41"] = "3"
        self.config["VERSION_CONFIG"]["Creedence"]["GUEST_VIFS_rhel44"] = "3"
        self.config["VERSION_CONFIG"]["Creedence"]["SUPPORTS_HIBERNATE"] = "no"
        self.config["VERSION_CONFIG"]["Creedence"]["GENERIC_WINDOWS_OS"] = "ws08sp2-x86"
        self.config["VERSION_CONFIG"]["Creedence"]["GENERIC_WINDOWS_OS_64"] = "ws08r2sp1-x64"
        self.config["VERSION_CONFIG"]["Creedence"]["GENERIC_LINUX_OS"] = "debian70"
        self.config["VERSION_CONFIG"]["Creedence"]["GENERIC_LINUX_OS_64"] = "centos64"
        self.config["VERSION_CONFIG"]["Creedence"]["TILE_WIN_DISTRO"] = "ws08sp2-x86"
        self.config["VERSION_CONFIG"]["Creedence"]["TILE_LINUX_DISTRO"] = "centos57"
        self.config["VERSION_CONFIG"]["Creedence"]["EXPECTED_CRASHDUMP_FILES"] = "xen-crashdump-analyser.log,xen.log,dom0.log"
        self.config["VERSION_CONFIG"]["Creedence"]["V6_DBV"] = "2015.0101"
        self.config["VERSION_CONFIG"]["Creedence"]["DEFAULT_RPU_LINUX_VERSION"] = "rhel64"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDIS_PER_VM"] = "15"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDI_SIZE_NFS"] = "2093058"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VDI_SIZE_LVM"] = "2093051"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_MEM_PV64"] = "131072"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_MEM_HVM"] = "131072"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_MEM_PV32"] = "65536"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VCPU_COUNT"] = "900"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_MULTIPATH_LUN"] = "150"
        self.config["VERSION_CONFIG"]["Creedence"]["CONCURRENT_MAX_MULTIPATH_LUN"] = "75"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_HOSTS_PER_POOL"] = "16"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VLANS_PER_HOST_LINUX"] = "800"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VLANS_PER_HOST_VSWITCH"] = "800"
        self.config["VERSION_CONFIG"]["Creedence"]["VIF_PER_VM"] = "7"
        self.config["VERSION_CONFIG"]["Creedence"]["LOCAL_DISK_TiB"] = "6"
        self.config["VERSION_CONFIG"]["Creedence"]["MAX_VBDS_PER_HOST"] = "2048"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_rhel5"] = "rhel510"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_rhel6"] = "rhel65"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_rhel7"] = "rhel7"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_sl5"] = "sl511"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_sl6"] = "sl66"
        self.config["VERSION_CONFIG"]["Creedence"]["LATEST_sl7"] = "sl71"
        self.config["VERSION_CONFIG"]["Creedence"]["EARLY_PV_LINUX"] = "rhel5\d*,rhel6\d*,centos5\d*,centos6\d*,sl5\d,sl6\d,debian60"
        # XenServer dom0 partitions
        self.config["VERSION_CONFIG"]["Creedence"]["DOM0_PARTITIONS"] = {1:4*xenrt.GIGA, 2:4*xenrt.GIGA, 3:"*"}
        self.config["VERSION_CONFIG"]["Creedence"]["INTERNAL_RPU_HOTFIX"] = "XS65ESP1006.xsupdate"
        # Cream
        self.config["VERSION_CONFIG"]["Cream"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Creedence"])
        self.config["VERSION_CONFIG"]["Cream"]["LATEST_rhel4"] = "rhel48"
        self.config["VERSION_CONFIG"]["Cream"]["LATEST_rhel5"] = "rhel511"
        self.config["VERSION_CONFIG"]["Cream"]["LATEST_rhel6"] = "rhel66"
        self.config["VERSION_CONFIG"]["Cream"]["LATEST_rhel7"] = "rhel71"
        self.config["VERSION_CONFIG"]["Cream"]["TEMPLATE_NAME_RHEL_d66_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Cream"]["TEMPLATE_NAME_RHEL_w66_64"] = "Red Hat Enterprise Linux 6 (64-bit),Red Hat Enterprise Linux 6 x64,Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["VERSION_CONFIG"]["Cream"]["TEMPLATE_NAME_SLED_113_64"] = "SUSE Linux Enterprise Desktop 11 SP3 (64-bit),SUSE Linux Enterprise Server 11 SP3 x64"

        # Dundee
        self.config["VERSION_CONFIG"]["Dundee"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Cream"])
        self.config["VERSION_CONFIG"]["Dundee"]["V6_DBV"] = "2014.1127"
        self.config["VERSION_CONFIG"]["Dundee"]["TEMPLATE_NAME_SDK"] = ""  # SDK not present in trunk
        self.config["VERSION_CONFIG"]["Dundee"]["MAX_VDIS_PER_SR_cifs"] = "600"
        self.config["VERSION_CONFIG"]["Dundee"]["MAX_ATTACHED_VDIS_PER_SR_cifs"] = "600"
        self.config["VERSION_CONFIG"]["Dundee"]["TEMPLATE_NAME_SLES_114_64"] = "SUSE Linux Enterprise Server 11 SP3 (64-bit),SUSE Linux Enterprise Server 11 SP3 x64"
        self.config["VERSION_CONFIG"]["Dundee"]["TEMPLATE_NAME_SLED_12_64"] = "SUSE Linux Enterprise Desktop 12 (64-bit)"
        self.config["VERSION_CONFIG"]["Dundee"]["MAX_VBDS_PER_HOST"] = "4096"
        self.config["VERSION_CONFIG"]["Dundee"]["MAX_VDIS_PER_VM"] = "255"

        # XenServer dom0 partitions
        self.config["VERSION_CONFIG"]["Dundee"]["DOM0_PARTITIONS"] = {1:18*xenrt.GIGA, 2:18*xenrt.GIGA, 3:"*", 4:512*xenrt.MEGA, 5:4*xenrt.GIGA, 6:1024*xenrt.MEGA}
        self.config["VERSION_CONFIG"]["Dundee"]["DOM0_PARTITIONS_OLD"] = {1:3.5*xenrt.GIGA, 2:4*xenrt.GIGA, 3:"*", 4:512*xenrt.MEGA}
        self.config["VERSION_CONFIG"]["Dundee"]["INTERNAL_RPU_HOTFIX"] = None

        # Libvirt
        self.config["VERSION_CONFIG"]["Libvirt"] = {}
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_DEBIAN"] = "virtio26"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "debianetch"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_DEBIAN_50"] = "debianlenny"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_DEBIAN_60"] = "debiansqueeze"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_DEBIAN_70"] = "virtio26"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_41"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_44"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_45"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_46"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_47"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_48"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_51"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_52"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_53"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_54"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_55"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_56"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_57"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_58"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_59"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_6"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_61"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_62"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_63"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_RHEL_64"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_53"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_54"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_55"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_56"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_57"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_58"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_59"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_6"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_61"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_62"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_63"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_OEL_64"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_43"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_45"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_46"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_47"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_48"] = "rhel4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_5"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_51"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_52"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_53"] = "rhel5"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_54"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_55"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_56"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_57"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_58"] = "rhel5.4"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_6"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_61"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_62"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_63"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_CENTOS_64"] = "rhel6"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_UBUNTU_1004"] = "ubuntulucid"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_UBUNTU_1204"] = "virtio26"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_OTHER_MEDIA"] = "generic"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_9"] = "sles9"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_92"] = "sles9"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_93"] = "sles9"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_94"] = "sles9"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_101"] = "sles10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_102"] = "sles10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_103"] = "sles10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_104"] = "sles10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_11"] = "sles11"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_111"] = "sles11"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SLES_112"] = "sles11"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SOLARIS_10U9"] = "solaris10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_SOLARIS_10U9_32"] = "solaris10"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WINDOWS_2003"] = "win2k3"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WINDOWS_2000"] = "win2k"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WINDOWS_XP"] = "winxp"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "winxp"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_VISTA"] = "vista"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WS08"] = "win2k8"
        self.config["VERSION_CONFIG"]["Libvirt"]["TEMPLATE_NAME_WIN7"] = "win7"
        self.config["VERSION_CONFIG"]["Libvirt"]["GENERIC_LINUX_OS"] = "centos64"

        # KVM
        self.config["VERSION_CONFIG"]["kvm"] = copy.deepcopy(self.config["VERSION_CONFIG"]["Libvirt"])

        # ESX
        self.config["VERSION_CONFIG"]["esx"] = {}
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN"] = "debian6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "debian4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_50"] = "debian5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_50_64"] = "debian5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_60"] = "debian6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_60_64"] = "debian6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_70"] = "debian7"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_DEBIAN_70_64"] = "debian7_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_41"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_41_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_44"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_44_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_45"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_45_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_46"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_46_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_47"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_47_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_48"] = "rhel4"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_48_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_5"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_5_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_51"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_51_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_52"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_52_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_53"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_53_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_54"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_54_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_55"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_55_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_56"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_56_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_57"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_57_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_58"] = "rhel5"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_58_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_6"] = "rhel6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_6_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_61"] = "rhel6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_61_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_62"] = "rhel6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_62_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_63"] = "rhel6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_63_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_64"] = "rhel6"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_RHEL_64_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_53"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_53_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_54"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_54_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_55"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_55_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_56"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_56_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_57"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_57_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_58"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_58_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_6"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_6_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_61"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_61_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_62"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_62_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_63"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_63_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_64"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_OEL_64_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_43"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_43_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_45"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_45_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_46"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_46_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_47"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_47_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_48"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_48_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_5"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_5_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_51"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_51_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_52"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_52_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_53"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_53_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_54"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_54_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_55"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_55_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_56"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_56_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_57"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_57_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_58"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_58_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_6"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_6_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_61"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_61_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_62"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_62_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_63"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_63_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_64"] = "centos"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_CENTOS_64_64"] = "centos64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_UBUNTU_1004"] = "ubuntu"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_UBUNTU_1004_64"] = "ubuntu64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_UBUNTU_1204"] = "ubuntu"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_UBUNTU_1204_64"] = "ubuntu64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_OTHER_MEDIA"] = "other"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_101"] = "sles10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_101_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_102"] = "sles10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_102_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_103"] = "sles10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_103_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_104"] = "sles10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_104_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_11"] = "sles11"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_11_64"] = "sles11_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_111"] = "sles11"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SLES_111_64"] = "sles11_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SOLARIS_10U9_32"] = "solaris10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_SOLARIS_10U9"] = "solaris10_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "winNetEnterprise64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WINDOWS_2003"] = "winNetEnterprise"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WINDOWS_2000"] = "win2000Pro"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WINDOWS_XP"] = "winXPPro"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "winXPPro"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_VISTA"] = "winLonghorn"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WS08R2_64"] = "windows7Server64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN7"] = "windows7"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN7_64"] = "windows7_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN8"] = "windows8"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN8_64"] = "windows8_64"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN10"] = "windows10"
        self.config["VERSION_CONFIG"]["esx"]["TEMPLATE_NAME_WIN10_64"] = "windows10_64"

        # ESXi
        self.config["VERSION_CONFIG"]["ESXi"] = {}
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN"] = "debian6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN_ETCH"] = "debian4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN_50"] = "debian5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN_50_64"] = "debian5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN_60"] = "debian6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_DEBIAN_60_64"] = "debian6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_41"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_41_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_44"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_44_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_45"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_45_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_46"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_46_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_47"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_47_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_48"] = "rhel4"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_48_64"] = "rhel4_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_5"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_5_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_51"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_51_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_52"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_52_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_53"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_53_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_54"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_54_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_55"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_55_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_56"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_56_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_57"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_57_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_58"] = "rhel5"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_58_64"] = "rhel5_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_6"] = "rhel6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_6_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_61"] = "rhel6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_61_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_62"] = "rhel6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_62_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_63"] = "rhel6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_63_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_64"] = "rhel6"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_RHEL_64_64"] = "rhel6_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_53"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_53_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_54"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_54_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_55"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_55_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_56"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_56_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_57"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_57_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_58"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_58_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_6"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_6_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_61"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_61_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_62"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_62_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_63"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_63_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_64"] = "oracleLinux"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_OEL_64_64"] = "oracleLinux64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_43"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_43_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_45"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_45_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_46"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_46_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_47"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_47_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_48"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_48_64"] = "centos_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_5"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_5_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_51"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_51_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_52"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_52_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_53"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_53_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_54"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_54_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_55"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_55_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_56"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_56_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_57"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_57_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_58"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_58_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_6"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_6_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_61"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_61_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_62"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_62_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_63"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_63_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_64"] = "centos"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_CENTOS_64_64"] = "centos64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_UBUNTU_1004"] = "ubuntu"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_UBUNTU_1004_64"] = "ubuntu64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_UBUNTU_1204"] = "ubuntu"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_UBUNTU_1204_64"] = "ubuntu64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_OTHER_MEDIA"] = "other"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_101"] = "sles10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_101_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_102"] = "sles10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_102_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_103"] = "sles10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_103_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_104"] = "sles10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_104_64"] = "sles10_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_11"] = "sles11"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_11_64"] = "sles11_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_111"] = "sles11"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SLES_111_64"] = "sles11_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SOLARIS_10U9_32"] = "solaris10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_SOLARIS_10U9"] = "solaris10_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WINDOWS_2003_64"] = "winNetEnterprise64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WINDOWS_2003"] = "winNetEnterprise"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WINDOWS_2000"] = "win2000Pro"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WINDOWS_XP"] = "winXPPro"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WINDOWS_XP_SP3"] = "winXPPro"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_VISTA"] = "winLonghorn"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WS08R2_64"] = "windows7Server64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN7"] = "windows7"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN7_64"] = "windows7_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN8"] = "windows8"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN8_64"] = "windows8_64"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN10"] = "windows10"
        self.config["VERSION_CONFIG"]["ESXi"]["TEMPLATE_NAME_WIN10_64"] = "windows10_64"

        # Marvin File
        self.config["MARVIN_FILE"] = {}
        self.config["MARVIN_FILE"]["3.x"] =     "http://repo-ccp.citrix.com/releases/Marvin/3.0.7/Marvin-3.0.7.tar.gz"
        self.config["MARVIN_FILE"]["4.x"] =     "http://repo-ccp.citrix.com/releases/Marvin/ccp-4.5.1/Marvin-master-asfrepo-current.tar.gz"
        self.config["MARVIN_FILE"]["DEFAULT"] = "http://repo-ccp.citrix.com/releases/Marvin/ccp-4.5.1/Marvin-master-asfrepo-current.tar.gz"

        # Config for CCP / ACS
        self.config["CLOUD_CONFIG"] = {}
        self.config["CLOUD_CONFIG"]["3.0.7"] = {}
        self.config["CLOUD_CONFIG"]["3.0.7"]["SYSTEM_TEMPLATES"] = {}
        self.config["CLOUD_CONFIG"]["3.0.7"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvmtemplate-2015-08-20-3.0.7.vhd.bz2"
        self.config["CLOUD_CONFIG"]["3.0.7"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvmtemplate-2015-08-20-3.0.7.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["3.0.7"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvmtemplate-2015-08-20-3.0.7.ova"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"] = {}
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["winxpsp3"] = "Windows XP SP3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["w2k3eesp2"] = "Windows Server 2003 Enterprise Edition(32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["w2k3eesp2-x64"] = "Windows Server 2003 Enterprise Edition(64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["w2k3sesp2"] = "Windows Server 2003 Standard Edition(32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08-x86"] = "Windows Server 2008 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08-x64"] = "Windows Server 2008 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08sp2-x86"] = "Windows Server 2008 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08sp2-x64"] = "Windows Server 2008 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08r2-x64"] = "Windows Server 2008 R2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ws08r2sp1-x64"] = "Windows Server 2008 R2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win7-x86"] = "Windows 7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win7sp1-x86"] = "Windows 7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win7-x64"] = "Windows 7 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win7sp1-x64"] = "Windows 7 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win8-x86"] = "Windows 8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["win8-x64"] = "Windows 8 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["debian60_x86-32"] = "Debian GNU/Linux 6(64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["debian60_x86-64"] = "Debian GNU/Linux 6(64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["debian70_x86-32"] = "Debian GNU/Linux 7(32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["debian70_x86-64"] = "Debian GNU/Linux 7(64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1004_x86-32"] = "Ubuntu 10.04 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1004_x86-64"] = "Ubuntu 10.04 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1204_x86-32"] = "Ubuntu 12.04 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1204_x86-64"] = "Ubuntu 12.04 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1404_x86-32"] = "Other (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["ubuntu1404_x86-64"] = "Other (64-bit)"

        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel2_x86-32"] = "Red Hat Enterprise Linux 2" # assuming 32-bit
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel3_x86-32"] = "Red Hat Enterprise Linux 3(32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel3_x86-64"] = "Red Hat Enterprise Linux 3(64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel4_x86-64"] = "Red Hat Enterprise Linux 4(64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel38_x86-32"] = "Red Hat Enterprise Linux 3.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel41_x86-32"] = "Red Hat Enterprise Linux 4.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel44_x86-32"] = "Red Hat Enterprise Linux 4.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel45_x86-32"] = "Red Hat Enterprise Linux 4.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel46_x86-32"] = "Red Hat Enterprise Linux 4.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel47_x86-32"] = "Red Hat Enterprise Linux 4.7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel48_x86-32"] = "Red Hat Enterprise Linux 4.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel5_x86-32"] = "Red Hat Enterprise Linux 5.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel5_x86-64"] = "Red Hat Enterprise Linux 5.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel51_x86-32"] = "Red Hat Enterprise Linux 5.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel51_x86-64"] = "Red Hat Enterprise Linux 5.1 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel510_x86-32"] = "Red Hat Enterprise Linux 5.10 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel510_x86-64"] = "Red Hat Enterprise Linux 5.10 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel52_x86-32"] = "Red Hat Enterprise Linux 5.2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel52_x86-64"] = "Red Hat Enterprise Linux 5.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel53_x86-32"] = "Red Hat Enterprise Linux 5.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel53_x86-64"] = "Red Hat Enterprise Linux 5.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel54_x86-32"] = "Red Hat Enterprise Linux 5.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel54_x86-64"] = "Red Hat Enterprise Linux 5.4 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel55_x86-32"] = "Red Hat Enterprise Linux 5.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel55_x86-64"] = "Red Hat Enterprise Linux 5.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel56_x86-32"] = "Red Hat Enterprise Linux 5.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel56_x86-64"] = "Red Hat Enterprise Linux 5.6 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel57_x86-32"] = "Red Hat Enterprise Linux 5.7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel57_x86-64"] = "Red Hat Enterprise Linux 5.7 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel58_x86-32"] = "Red Hat Enterprise Linux 5.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel58_x86-64"] = "Red Hat Enterprise Linux 5.8 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel59_x86-32"] = "Red Hat Enterprise Linux 5.9 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel58_x86-64"] = "Red Hat Enterprise Linux 5.9 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel6_x86-32"] = "Red Hat Enterprise Linux 6.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel6_x86-64"] = "Red Hat Enterprise Linux 6.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel61_x86-32"] = "Red Hat Enterprise Linux 6.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel61_x86-64"] = "Red Hat Enterprise Linux 6.1 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel62_x86-32"] = "Red Hat Enterprise Linux 6.2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel62_x86-64"] = "Red Hat Enterprise Linux 6.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel63_x86-32"] = "Red Hat Enterprise Linux 6.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel63_x86-64"] = "Red Hat Enterprise Linux 6.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel64_x86-32"] = "Red Hat Enterprise Linux 6.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel64_x86-64"] = "Red Hat Enterprise Linux 6.4 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sl511_x86-32"] =  "Scientific Linux 5.11 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sl511_x86-64"] =  "Scientific Linux 5.11 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sl66_x86-32"] =   "Scientific Linux 6.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sl66_x86-64"] =   "Scientific Linux 6.6 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel65_x86-32"] = "Red Hat Enterprise Linux 6.5 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel65_x86-64"] = "Red Hat Enterprise Linux 6.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel7_x86-64"] = "Other (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["rhel71_x86-64"] = "Other (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sl7_x86-64"] = "Other (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos7_x86-64"] = "Other (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel7_x86-64"] = "Other (64-bit)"

        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos43_x86-32"] = "CentOS 4.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos43_x86-64"] = "CentOS 4.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos45_x86-32"] = "CentOS 4.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos46_x86-32"] = "CentOS 4.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos47_x86-32"] = "CentOS 4.7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos48_x86-32"] = "CentOS 4.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos50_x86-32"] = "CentOS 5.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos50_x86-64"] = "CentOS 5.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos51_x86-32"] = "CentOS 5.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos51_x86-64"] = "CentOS 5.1 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel510_x86-32"] = "Oracle Enterprise Linux 5.10 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel510_x86-64"] = "Oracle Enterprise Linux 5.10 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos52_x86-32"] = "CentOS 5.2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos52_x86-64"] = "CentOS 5.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos53_x86-32"] = "CentOS 5.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos53_x86-64"] = "CentOS 5.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos54_x86-32"] = "CentOS 5.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos54_x86-64"] = "CentOS 5.4 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos55_x86-32"] = "CentOS 5.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos55_x86-64"] = "CentOS 5.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos56_x86-32"] = "CentOS 5.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos56_x86-64"] = "CentOS 5.6 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos57_x86-32"] = "CentOS 5.7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos57_x86-64"] = "CentOS 5.7 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos58_x86-32"] = "CentOS 5.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos58_x86-64"] = "CentOS 5.8 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos59_x86-32"] = "CentOS 5.9 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos59_x86-64"] = "CentOS 5.9 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos60_x86-32"] = "CentOS 6.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos60_x86-64"] = "CentOS 6.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos61_x86-32"] = "CentOS 6.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos61_x86-64"] = "CentOS 6.1 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos62_x86-32"] = "CentOS 6.2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos62_x86-64"] = "CentOS 6.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos63_x86-32"] = "CentOS 6.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos63_x86-64"] = "CentOS 6.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos64_x86-32"] = "CentOS 6.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos64_x86-64"] = "CentOS 6.4 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos65_x86-32"] = "CentOS 6.5 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["centos65_x86-64"] = "CentOS 6.5 (64-bit)"

        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel5_x86-32"] = "Oracle Enterprise Linux 5.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel5_x86-64"] = "Oracle Enterprise Linux 5.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel51_x86-32"] = "Oracle Enterprise Linux 5.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel51_x86-64"] = "Oracle Enterprise Linux 5.1 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel510_x86-32"] = "Oracle Enterprise Linux 5.10 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel510_x86-64"] = "Oracle Enterprise Linux 5.10 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel52_x86-32"] = "Oracle Enterprise Linux 5.2 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel52_x86-64"] = "Oracle Enterprise Linux 5.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel53_x86-32"] = "Oracle Enterprise Linux 5.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel53_x86-64"] = "Oracle Enterprise Linux 5.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel54_x86-32"] = "Oracle Enterprise Linux 5.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel54_x86-64"] = "Oracle Enterprise Linux 5.4 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel55_x86-32"] = "Oracle Enterprise Linux 5.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel55_x86-64"] = "Oracle Enterprise Linux 5.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel56_x86-32"] = "Oracle Enterprise Linux 5.6 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel56_x86-64"] = "Oracle Enterprise Linux 5.6 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel57_x86-32"] = "Oracle Enterprise Linux 5.7 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel57_x86-64"] = "Oracle Enterprise Linux 5.7 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel58_x86-32"] = "Oracle Enterprise Linux 5.8 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel58_x86-64"] = "Oracle Enterprise Linux 5.8 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel59_x86-32"] = "Oracle Enterprise Linux 5.9 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel59_x86-64"] = "Oracle Enterprise Linux 5.9 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel6_x86-32"] = "Oracle Enterprise Linux 6.0 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel6_x86-64"] = "Oracle Enterprise Linux 6.0 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel61_x86-32"] = "Oracle Enterprise Linux 6.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel61_x86-64"] = "Oracle Enterprise Linux 6.1 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel62_x86-32"] = "Oracle Enterprise Linux 6.2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel62_x86-64"] = "Oracle Enterprise Linux 6.2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel63_x86-32"] = "Oracle Enterprise Linux 6.3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel63_x86-64"] = "Oracle Enterprise Linux 6.3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel64_x86-32"] = "Oracle Enterprise Linux 6.4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel64_x86-64"] = "Oracle Enterprise Linux 6.4 (64-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel65_x86-32"] = "Oracle Enterprise Linux 6.5 (32-bit)"
        #self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["oel65_x86-64"] = "Oracle Enterprise Linux 6.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles10_x86-32"] = "SUSE Linux Enterprise Server 10 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles10_x86-64"] = "SUSE Linux Enterprise Server 10 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles101_x86-32"] = "SUSE Linux Enterprise Server 10 SP1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles101_x86-64"] = "SUSE Linux Enterprise Server 10 SP1 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles102_x86-32"] = "SUSE Linux Enterprise Server 10 SP2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles102_x86-64"] = "SUSE Linux Enterprise Server 10 SP2 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles103_x86-32"] = "SUSE Linux Enterprise Server 10 SP3 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles103_x86-64"] = "SUSE Linux Enterprise Server 10 SP3 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles104_x86-32"] = "SUSE Linux Enterprise Server 10 SP4 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles104_x86-64"] = "SUSE Linux Enterprise Server 10 SP4 (64-bit)"

        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles11_x86-32"] = "SUSE Linux Enterprise Server 11 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles11_x86-64"] = "SUSE Linux Enterprise Server 11 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles111_x86-32"] = "SUSE Linux Enterprise Server 11 SP1 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles111_x86-64"] = "SUSE Linux Enterprise Server 11 SP1 (64-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles112_x86-32"] = "SUSE Linux Enterprise Server 11 SP2 (32-bit)"
        self.config["CLOUD_CONFIG"]["3.0.7"]["OS_NAMES"]["sles112_x86-64"] = "SUSE Linux Enterprise Server 11 SP2 (64-bit)"

        self.config["CLOUD_CONFIG"]["4.1"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["3.0.7"])
        self.config["CLOUD_CONFIG"]["4.1"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvmtemplate-2013-07-12-master-xen.vhd.bz2"

        self.config["CLOUD_CONFIG"]["4.2"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.1"])
        self.config["CLOUD_CONFIG"]["4.2"]["OS_NAMES"]["ws12-x64"] = "Windows Server 2012 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.2"]["OS_NAMES"]["ws12core-x64"] = "Windows Server 2012 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.2"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2014-10-28-4.2-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.2"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2014-10-31-master-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.2"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2014-10-31-master-vmware.ova"

        self.config["CLOUD_CONFIG"]["4.2.1"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.2"])
        self.config["CLOUD_CONFIG"]["4.2.1"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2015-08-20-4.2.1-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.2.1"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2015-08-20-4.2.1-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.2.1"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvmtemplate64-2015-08-20-4.2.1-vmware.ova"

        self.config["CLOUD_CONFIG"]["4.3"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.2"])

        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["ubuntu1404_x86-32"] = "Ubuntu 14.04 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["ubuntu1404_x86-64"] = "Ubuntu 14.04 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sles113_x86-32"] = "SUSE Linux Enterprise Server 11 SP3 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sles113_x86-64"] = "SUSE Linux Enterprise Server 11 SP3 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sles114_x86-64"] = "SUSE Linux Enterprise Server 11 SP4 RC1 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["centos65_x86-32"] = "CentOS 6.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["centos65_x86-64"] = "CentOS 6.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel65_x86-32"] = "Red Hat Enterprise Linux 6.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel65_x86-64"] = "Red Hat Enterprise Linux 6.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel510_x86-32"] = "Red Hat Enterprise Linux 5.10 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel510_x86-64"] = "Red Hat Enterprise Linux 5.10 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["oel510_x86-32"] = "Oracle Enterprise Linux 5.10 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["oel510_x86-64"] = "Oracle Enterprise Linux 5.10 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["oel65_x86-32"] = "Oracle Enterprise Linux 6.5 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["oel65_x86-64"] = "Oracle Enterprise Linux 6.5 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["win81-x86"] = "Windows 8.1 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["win81-x64"] = "Windows 8.1 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["ws12r2-x64"] = "Windows Server 2012 R2 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["ws12r2core-x64"] = "Windows Server 2012 R2 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["centos510_x86-32"] = "CentOS 5.10 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["centos510_x86-64"] = "CentOS 5.10 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel7_x86-64"] = "Red Hat Enterprise Linux 7.0"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["rhel71_x86-64"] = "Red Hat Enterprise Linux 7.1"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sl511_x86-32"] = "Scientific Linux 5.11 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sl511_x86-64"] = "Scientific Linux 5.11 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sl66_x86-32"] = "Scientific Linux 5.11 (32-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sl66_x86-64"] = "Scientific Linux 6.6 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["sl7_x86-64"] = "Scientific Linux 7 (64-bit)"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["centos7_x86-64"] = "CentOS 7"
        self.config["CLOUD_CONFIG"]["4.3"]["OS_NAMES"]["oel7_x86-64"] = "Oracle Linux 7"
        
        self.config["CLOUD_CONFIG"]["4.3"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.3-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.3"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.3-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.3"]["SYSTEM_TEMPLATES"]["hyperv"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.3-hyperv.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.3"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.3-vmware.ova"

        self.config["CLOUD_CONFIG"]["4.4"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.3"])
        self.config["CLOUD_CONFIG"]["4.4"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvm64template-master-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.4"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvm64template-master-kvm.qcow2.bz2"

        self.config["CLOUD_CONFIG"]["4.5"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.4"])
        self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.0-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.0-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["hyperv"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.0-hyperv.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.0-vmware.ova"
        # LXC currently uses KVM for System VMs, so use the KVM template
        self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["lxc"] = self.config["CLOUD_CONFIG"]["4.5"]["SYSTEM_TEMPLATES"]["kvm"]

        self.config["CLOUD_CONFIG"]["4.5.1"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.5"])
        self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.1-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.1-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["hyperv"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.1-hyperv.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-08-20-4.5.1-vmware.ova"
        self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["lxc"] = self.config["CLOUD_CONFIG"]["4.5.1"]["SYSTEM_TEMPLATES"]["kvm"]

        self.config["CLOUD_CONFIG"]["4.6.0"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.5.1"])
        self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["xenserver"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-07-22-4.6.0-xen.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["kvm"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-07-22-4.6.0-kvm.qcow2.bz2"
        self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["hyperv"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-07-22-4.6.0-hyperv.vhd.bz2"
        self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["vmware"] = "/usr/groups/xenrt/cloud/systemvm64template-2015-07-22-4.6.0-vmware.ova"
        self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["lxc"] = self.config["CLOUD_CONFIG"]["4.6.0"]["SYSTEM_TEMPLATES"]["kvm"]

        self.config["CLOUD_CONFIG"]["4.7.0"] = copy.deepcopy(self.config["CLOUD_CONFIG"]["4.6.0"])

        # Specify which version 'master' currently maps to
        self.config["CLOUD_MASTER_MAP"] = "4.7.0"


        self.config["GUEST_VIFS_centos41"] = "3"
        self.config["GUEST_VIFS_centos42"] = "3"
        self.config["GUEST_VIFS_centos43"] = "3"
        self.config["GUEST_VIFS_centos44"] = "3"
        self.config["GUEST_VIFS_rhel45"] = "3"
        self.config["GUEST_VIFS_centos45"] = "3"
        self.config["GUEST_VIFS_rhel46"] = "3"
        self.config["GUEST_VIFS_centos46"] = "3"
        self.config["GUEST_VIFS_rhel47"] = "3"
        self.config["GUEST_VIFS_centos47"] = "3"
        self.config["GUEST_VIFS_rhel48"] = "3"
        self.config["GUEST_VIFS_centos48"] = "3"
        self.config["GUEST_VIFS_rhel5"] = "3"
        self.config["GUEST_VIFS_centos5"] = "3"
        self.config["GUEST_VIFS_rhel51"] = "3"
        self.config["GUEST_VIFS_centos51"] = "3"
        self.config["GUEST_VIFS_rhel52"] = "3"
        self.config["GUEST_VIFS_centos52"] = "3"
        self.config["GUEST_VIFS_sles101"] = "3"
        self.config["GUEST_VIFS_sles102"] = "3"
        self.config["GUEST_VIFS_sles94"] = "3"

        self.config["GUEST_NO_HOTPLUG_VBD"] = ""
        self.config["GUEST_NO_HOTUNPLUG_VBD"] = "w2k3eesp2pae,w2k3se,w2k3sesp1,w2k3ser2,w2k3sesp2,w2k3sesp2-x64,w2k3ee,w2k3eesp1,w2k3eer2,w2k3eesp2,w2k3eesp2-x64,w2kassp4,winxpsp2"
        self.config["GUEST_NO_HOTPLUG_VIF"] = ""
        self.config["GUEST_NO_HOTUNPLUG_VIF"] = ""
        self.config["GUEST_NO_HOTPLUG_CPU"] = "w2k3eesp2pae,w2k3se,w2k3sesp1,w2k3ser2,w2k3sesp2,w2k3sesp2-x64,w2k3ee,w2k3eesp1,w2k3eer2,w2k3eesp2,w2k3eesp2-x64,w2kassp4,winxpsp2,ubuntu1004,sles111"
        self.config["GUEST_NO_HOTUNPLUG_CPU"] = "w2k3eesp2pae,w2k3se,w2k3sesp1,w2k3ser2,w2k3sesp2,w2k3sesp2-x64,w2k3ee,w2k3eesp1,w2k3eer2,w2k3eesp2,w2k3eesp2-x64,w2kassp4,winxpsp2,ubuntu1004,sles111"
        
        # PRODUCT_CODENAMES contains a mapping of product major and minor
        # versions to codenames. It is now loaded from
        # data/config/PRODUCT_CODENAMES.json rather than being defined in
        # config.py to allow other tools to use the data

        # Platform releases
        self.config["PLATFORM_CODENAMES"] = {}
        self.config["PLATFORM_CODENAMES"]["1.4.90"] = "BostonXCP"
        self.config["PLATFORM_CODENAMES"]["1.6.10"] = "TampaXCP"

        self.config["GUEST_LIMITATIONS"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2pae"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2pae"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2pae"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2pae"]["MAXSOCKETS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2pae"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3se"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3se"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3se"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["w2k3se"]["MAXSOCKETS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3se"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp1"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3sesp1"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp1"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp1"]["MAXSOCKETS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp1"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3ser2"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3ser2"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3ser2"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["w2k3ser2"]["MAXSOCKETS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3ser2"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp2"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3sesp2"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp2"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp2"]["MAXSOCKETS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2k3sesp2"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["w2kprosp4"] = {}
        self.config["GUEST_LIMITATIONS"]["w2kprosp4"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2kprosp4"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["w2kprosp4"]["MAXCORES"] = "2"
        self.config["GUEST_LIMITATIONS"]["w2kprosp4"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["w2kassp4"] = {}
        self.config["GUEST_LIMITATIONS"]["w2kassp4"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2kassp4"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["w2kassp4"]["MAXCORES"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2kassp4"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["winxpsp2"] = {}
        self.config["GUEST_LIMITATIONS"]["winxpsp2"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["winxpsp2"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["winxpsp2"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["winxpsp2"]["MAXCORES"] = "4"
        self.config["GUEST_LIMITATIONS"]["winxpsp2"]["MAX_VM_VCPUS"] = "4"
        self.config["GUEST_LIMITATIONS"]["winxpsp3"] = {}
        self.config["GUEST_LIMITATIONS"]["winxpsp3"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["winxpsp3"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["winxpsp3"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["winxpsp3"]["MAXCORES"] = "4"
        self.config["GUEST_LIMITATIONS"]["winxpsp3"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["w2k3ee"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3ee"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3ee"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3ee"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3ee"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp1"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp1"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp1"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp1"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp1"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eer2"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eer2"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eer2"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3eer2"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eer2"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-x64"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-x64"]["MAXMEMORY"] = "1048576"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-x64"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-x64"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-rc"] = {}
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-rc"]["MINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-rc"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-rc"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["w2k3eesp2-rc"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["vistaee"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaee"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaee"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["vistaee"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaee"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaee-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaee-x64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaee-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["vistaee-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaee-x64"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaeesp1"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaeesp1-x64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp1-x64"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaeesp2"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["vistaeesp2-x64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["vistaeesp2-x64"]["MAX_VM_VCPUS"] = "2"
        self.config["GUEST_LIMITATIONS"]["ws08-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08-x86"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08-x86"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["ws08-x86"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08-x64"]["MAXMEMORY"] = "1048576"
        self.config["GUEST_LIMITATIONS"]["ws08-x64"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x86"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x86"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x86"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x64"]["MAXMEMORY"] = "1048576"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x64"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08sp2-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08dc-x86"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x86"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x86"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08dc-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x64"]["MAXMEMORY"] = "1048576"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws08dc-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x86"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x86"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x86"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x64"]["MAXMEMORY"] = "1048576"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws08dcsp2-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08r2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08r2-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08r2-x64"]["MAXMEMORY"] = "2097152"
        self.config["GUEST_LIMITATIONS"]["ws08r2-x64"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08r2-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08r2sp1-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08r2sp1-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08r2sp1-x64"]["MAXMEMORY"] = "2097152"
        self.config["GUEST_LIMITATIONS"]["ws08r2sp1-x64"]["MAXSOCKETS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ws08r2sp1-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws08r2dcsp1-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws08r2dcsp1-x64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ws08r2dcsp1-x64"]["MAXMEMORY"] = "2097152"
        self.config["GUEST_LIMITATIONS"]["ws08r2dcsp1-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws08r2dcsp1-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win7-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["win7-x86"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["win7-x86"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["win7-x86"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win7-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win7-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["win7-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["win7-x64"]["MAXMEMORY"] = "196608"
        self.config["GUEST_LIMITATIONS"]["win7-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win7-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["win7sp1-x86"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x86"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x86"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["win7sp1-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x64"]["MAXMEMORY"] = "196608"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win7sp1-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win8-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["win8-x86"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["win8-x86"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["win8-x86"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win8-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win8-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["win8-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["win8-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["win8-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win8-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win10-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["win10-x86"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["win10-x86"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["win10-x86"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win10-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win10-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["win10-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["win10-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["win10-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win10-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win81-x86"] = {}
        self.config["GUEST_LIMITATIONS"]["win81-x86"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["win81-x86"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["win81-x86"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win81-x86"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["win81-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["win81-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["win81-x64"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["win81-x64"]["MAXSOCKETS"] = "2"
        self.config["GUEST_LIMITATIONS"]["win81-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws12-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws12-x64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["ws12-x64"]["MAXMEMORY"] = "524288"
        self.config["GUEST_LIMITATIONS"]["ws12-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws12-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"]["STATICMINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"]["MAXMEMORY"] = "524288"
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws12core-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws12r2-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws12r2-x64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["ws12r2-x64"]["MAXMEMORY"] = "524288"
        self.config["GUEST_LIMITATIONS"]["ws12r2-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws12r2-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"] = {}
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"]["MINMEMORY"] = "2048"
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"]["STATICMINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"]["MAXMEMORY"] = "524288"
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"]["MAXSOCKETS"] = "64"
        self.config["GUEST_LIMITATIONS"]["ws12r2core-x64"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["rhel38"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel38"]["MINMEMORY"] = "64"
        self.config["GUEST_LIMITATIONS"]["rhel38"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["rhel45"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel45"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["rhel45"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["rhel46"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel46"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["rhel46"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["rhel47"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel47"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["rhel47"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["rhel48"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel48"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["rhel48"]["MAXMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["rhel5"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel5"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel5"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel5"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel51"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel51"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel51"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel51"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel52"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel52"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel52"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel52"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel53"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel53"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel53"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel53"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel54"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel54"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel54"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel54"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel55"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel55"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel55"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel55"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel56"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel56"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel56"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel56"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel57"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel57"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel57"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel57"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel58"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel58"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel58"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel58"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel59"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel59"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel59"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel59"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel510"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel510"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel510"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel510"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel511"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel511"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel511"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel511"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel6"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel6"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel6"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel6"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["rhel6"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["rhel61"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel61"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel61"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel61"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["rhel61"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["rhel62"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel62"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel62"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel62"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel62"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel63"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel63"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel63"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel63"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel63"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel64"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel64"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel64"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel64"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel65"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel65"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel65"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel65"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel65"]["MAXMEMORY64"] = "131072"

        self.config["GUEST_LIMITATIONS"]["rhel66"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel66"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel66"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhel66"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhel66"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rheld66"] = {}
        self.config["GUEST_LIMITATIONS"]["rheld66"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rheld66"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rheld66"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rheld66"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhelw66"] = {}
        self.config["GUEST_LIMITATIONS"]["rhelw66"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhelw66"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["rhelw66"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["rhelw66"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["rhel7"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel7"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel7"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["rhel7"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["rhel71"] = {}
        self.config["GUEST_LIMITATIONS"]["rhel71"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["rhel71"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["rhel71"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["centos45"] = {}
        self.config["GUEST_LIMITATIONS"]["centos45"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["centos45"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos46"] = {}
        self.config["GUEST_LIMITATIONS"]["centos46"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["centos46"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos47"] = {}
        self.config["GUEST_LIMITATIONS"]["centos47"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["centos47"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos48"] = {}
        self.config["GUEST_LIMITATIONS"]["centos48"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["centos48"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos50"] = {}
        self.config["GUEST_LIMITATIONS"]["centos50"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos50"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos50"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos51"] = {}
        self.config["GUEST_LIMITATIONS"]["centos51"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos51"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos51"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos52"] = {}
        self.config["GUEST_LIMITATIONS"]["centos52"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos52"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos52"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos53"] = {}
        self.config["GUEST_LIMITATIONS"]["centos53"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos53"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos53"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos54"] = {}
        self.config["GUEST_LIMITATIONS"]["centos54"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos54"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos54"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos55"] = {}
        self.config["GUEST_LIMITATIONS"]["centos55"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos55"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos55"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos56"] = {}
        self.config["GUEST_LIMITATIONS"]["centos56"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos56"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos56"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos56"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos57"] = {}
        self.config["GUEST_LIMITATIONS"]["centos57"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos57"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos57"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos58"] = {}
        self.config["GUEST_LIMITATIONS"]["centos58"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos58"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos58"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos59"] = {}
        self.config["GUEST_LIMITATIONS"]["centos59"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos59"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos59"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos510"] = {}
        self.config["GUEST_LIMITATIONS"]["centos510"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos510"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos510"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos510"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos510"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos511"] = {}
        self.config["GUEST_LIMITATIONS"]["centos511"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos511"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos511"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos511"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos511"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos6"] = {}
        self.config["GUEST_LIMITATIONS"]["centos6"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos6"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["centos6"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["centos61"] = {}
        self.config["GUEST_LIMITATIONS"]["centos61"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos61"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["centos61"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["centos62"] = {}
        self.config["GUEST_LIMITATIONS"]["centos62"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos62"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos62"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos62"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos63"] = {}
        self.config["GUEST_LIMITATIONS"]["centos63"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos63"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos63"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos64"] = {}
        self.config["GUEST_LIMITATIONS"]["centos64"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos64"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos64"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos65"] = {}
        self.config["GUEST_LIMITATIONS"]["centos65"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos65"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos65"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos65"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos65"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos65"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos66"] = {}
        self.config["GUEST_LIMITATIONS"]["centos66"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos66"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["centos66"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["centos66"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["centos66"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos66"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["centos7"] = {}
        self.config["GUEST_LIMITATIONS"]["centos7"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos7"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["centos7"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["centos71"] = {}
        self.config["GUEST_LIMITATIONS"]["centos71"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["centos71"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["centos71"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["fedoralatest"] = {}
        self.config["GUEST_LIMITATIONS"]["fedoralatest"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["fedoralatest"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["fedoralatest"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["oel53"] = {}
        self.config["GUEST_LIMITATIONS"]["oel53"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel53"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel53"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel54"] = {}
        self.config["GUEST_LIMITATIONS"]["oel54"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel54"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel54"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel55"] = {}
        self.config["GUEST_LIMITATIONS"]["oel55"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel55"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel55"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel56"] = {}
        self.config["GUEST_LIMITATIONS"]["oel56"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel56"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel56"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel57"] = {}
        self.config["GUEST_LIMITATIONS"]["oel57"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel57"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel57"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel58"] = {}
        self.config["GUEST_LIMITATIONS"]["oel58"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel58"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel58"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel59"] = {}
        self.config["GUEST_LIMITATIONS"]["oel59"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel59"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel59"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel510"] = {}
        self.config["GUEST_LIMITATIONS"]["oel510"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel510"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel510"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel511"] = {}
        self.config["GUEST_LIMITATIONS"]["oel511"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel511"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["oel511"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel6"] = {}
        self.config["GUEST_LIMITATIONS"]["oel6"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel6"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["oel6"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["oel61"] = {}
        self.config["GUEST_LIMITATIONS"]["oel61"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel61"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["oel61"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["oel62"] = {}
        self.config["GUEST_LIMITATIONS"]["oel62"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel62"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["oel62"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel63"] = {}
        self.config["GUEST_LIMITATIONS"]["oel63"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel63"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["oel63"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel64"] = {}
        self.config["GUEST_LIMITATIONS"]["oel64"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel64"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["oel64"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel65"] = {}
        self.config["GUEST_LIMITATIONS"]["oel65"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel65"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["oel65"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel65"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["oel65"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["oel66"] = {}
        self.config["GUEST_LIMITATIONS"]["oel66"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["oel66"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["oel66"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["oel66"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["oel66"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["oel7"] = {}
        self.config["GUEST_LIMITATIONS"]["oel7"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["oel7"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["oel7"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["oel71"] = {}
        self.config["GUEST_LIMITATIONS"]["oel71"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["oel71"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["oel71"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["sles92"] = {}
        self.config["GUEST_LIMITATIONS"]["sles92"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["sles92"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles93"] = {}
        self.config["GUEST_LIMITATIONS"]["sles93"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["sles93"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles94"] = {}
        self.config["GUEST_LIMITATIONS"]["sles94"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["sles94"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles94"]["MAXMEMORY64"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles101"] = {}
        self.config["GUEST_LIMITATIONS"]["sles101"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles101"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles101"]["MAXMEMORY64"] = "491520"
        self.config["GUEST_LIMITATIONS"]["sles102"] = {}
        self.config["GUEST_LIMITATIONS"]["sles102"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles102"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles102"]["MAXMEMORY64"] = "491520"
        self.config["GUEST_LIMITATIONS"]["sles103"] = {}
        self.config["GUEST_LIMITATIONS"]["sles103"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles103"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles103"]["MAXMEMORY64"] = "491520"
        self.config["GUEST_LIMITATIONS"]["sles104"] = {}
        self.config["GUEST_LIMITATIONS"]["sles104"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles104"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles104"]["MAXMEMORY"] = "491520"
        self.config["GUEST_LIMITATIONS"]["sles104"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles104"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles11"] = {}
        self.config["GUEST_LIMITATIONS"]["sles11"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles11"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles11"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sles111"] = {}
        self.config["GUEST_LIMITATIONS"]["sles111"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles111"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles111"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sles112"] = {}
        self.config["GUEST_LIMITATIONS"]["sles112"]["MINMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["sles112"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles112"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sles113"] = {}
        self.config["GUEST_LIMITATIONS"]["sles113"]["MINMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["sles113"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles113"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles113"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sles113"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles113"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles114"] = {}
        self.config["GUEST_LIMITATIONS"]["sles114"]["MINMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["sles114"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles114"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles114"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sles114"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles114"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["sled113"] = {}
        self.config["GUEST_LIMITATIONS"]["sled113"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sled113"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sled113"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sled113"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sled113"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["sled113"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["sles12"] = {}
        self.config["GUEST_LIMITATIONS"]["sles12"]["MINMEMORY"] = "4096"
        self.config["GUEST_LIMITATIONS"]["sles12"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sles12"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sles12"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["sled12"] = {}
        self.config["GUEST_LIMITATIONS"]["sled12"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sled12"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sled12"]["MAXMEMORY"] = "16384"
        self.config["GUEST_LIMITATIONS"]["sled12"]["MAXMEMORY64"] = "524288"
        self.config["GUEST_LIMITATIONS"]["solaris10u9"] = {}
        self.config["GUEST_LIMITATIONS"]["solaris10u9"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["solaris10u9"]["MAXMEMORY"] = "131072"
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"] = {}
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ubuntu1004"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"] = {}
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["STATICMINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ubuntu1204"]["MAX_VM_VCPUS64"] = "64"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"] = {}
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["MINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ubuntu1404"]["MAX_VM_VCPUS64"] = "16"
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"] = {}
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"]["MAX_VM_VCPUS"] = "8"
        self.config["GUEST_LIMITATIONS"]["ubuntudevel"]["MAX_VM_VCPUS64"] = "16"
        self.config["GUEST_LIMITATIONS"]["debian50"] = {}
        self.config["GUEST_LIMITATIONS"]["debian50"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["debian50"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["debian50"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["debian60"] = {}
        self.config["GUEST_LIMITATIONS"]["debian60"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["debian60"]["STATICMINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["debian60"]["MAXMEMORY"] = "32768"
        self.config["GUEST_LIMITATIONS"]["debian60"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["debian60"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["debian60"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["debian70"] = {}
        self.config["GUEST_LIMITATIONS"]["debian70"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["debian70"]["STATICMINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["debian70"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["debian70"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["debian70"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["debian70"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["debian80"] = {}
        self.config["GUEST_LIMITATIONS"]["debian80"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["debian80"]["STATICMINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["debian80"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["debian80"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["debian80"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["debian80"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["debiantesting"] = {}
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["MINMEMORY"] = "256"
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["STATICMINMEMORY"] = "128"
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["MAXMEMORY"] = "65536"
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["MAXMEMORY64"] = "131072"
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["MAX_VM_VCPUS"] = "32"
        self.config["GUEST_LIMITATIONS"]["debiantesting"]["MAX_VM_VCPUS64"] = "32"
        self.config["GUEST_LIMITATIONS"]["sl511"] = {}
        self.config["GUEST_LIMITATIONS"]["sl511"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sl511"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sl511"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["sl511"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["sl511"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["sl511"]["MAX_VM_VCPUS64"] = "16"
        self.config["GUEST_LIMITATIONS"]["sl66"] = {}
        self.config["GUEST_LIMITATIONS"]["sl66"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sl66"]["STATICMINMEMORY"] = "512"
        self.config["GUEST_LIMITATIONS"]["sl66"]["MAXMEMORY"] = "8192"
        self.config["GUEST_LIMITATIONS"]["sl66"]["MAXMEMORY64"] = "32768"
        self.config["GUEST_LIMITATIONS"]["sl66"]["MAX_VM_VCPUS"] = "16"
        self.config["GUEST_LIMITATIONS"]["sl66"]["MAX_VM_VCPUS64"] = "16"
        self.config["GUEST_LIMITATIONS"]["sl7"] = {}
        self.config["GUEST_LIMITATIONS"]["sl7"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sl7"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["sl7"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["sl71"] = {}
        self.config["GUEST_LIMITATIONS"]["sl71"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["sl71"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["sl71"]["MAX_VM_VCPUS64"] = "240"
        self.config["GUEST_LIMITATIONS"]["coreos-stable"] = {}
        self.config["GUEST_LIMITATIONS"]["coreos-stable"]["MINMEMORY"] = "1024"
        self.config["GUEST_LIMITATIONS"]["coreos-stable"]["MAXMEMORY64"] = "6291456"
        self.config["GUEST_LIMITATIONS"]["coreos-stable"]["MAX_VM_VCPUS64"] = "240"
        self.config["LINUX_UPDATE"] = {}
        self.config["LINUX_UPDATE"]["rhel4"] = "rhel48"
        self.config["LINUX_UPDATE"]["rhel5"] = "rhel511"
        self.config["LINUX_UPDATE"]["rhel6"] = "rhel66"
        self.config["LINUX_UPDATE"]["rhel7"] = "rhel71"
        self.config["LINUX_UPDATE"]["oel5"] = "oel511"
        self.config["LINUX_UPDATE"]["oel6"] = "oel66"
        self.config["LINUX_UPDATE"]["oel7"] = "oel71"
        self.config["LINUX_UPDATE"]["centos4"] = "centos48"
        self.config["LINUX_UPDATE"]["centos5"] = "centos511"
        self.config["LINUX_UPDATE"]["centos6"] = "centos66"
        self.config["LINUX_UPDATE"]["centos7"] = "centos71"
        self.config["LINUX_UPDATE"]["sl5"] = "sl511"
        self.config["LINUX_UPDATE"]["sl6"] = "sl66"
        self.config["LINUX_UPDATE"]["sl7"] = "sl71"

        self.config["PRODUCT_KEYS"] = {}

        self.config["SERVICE_PACKS"] = {}
        #self.config["SERVICE_PACKS"]["ws08sp2-x86"] = "SPws08sp2.iso Windows6.0-KB948465-X86.exe SP2"
        #self.config["SERVICE_PACKS"]["ws08sp2-x64"] = "SPws08sp2.iso Windows6.0-KB948465-X64.exe SP2"
        #self.config["SERVICE_PACKS"]["vistaeesp2"] = "SPws08sp2.iso Windows6.0-KB948465-X86.exe SP2"
        #self.config["SERVICE_PACKS"]["vistaeesp2-x64"] = "SPws08sp2.iso Windows6.0-KB948465-X64.exe SP2"

        self.config["OS_INSTALL_ISO"] = {}
        self.config["OS_INSTALL_ISO"]["solaris10u9"] = "sol-10-u9-ga-x86-dvd-jumpstart-64"
        self.config["OS_INSTALL_ISO"]["solaris10u9-32"] = "sol-10-u9-ga-x86-dvd-jumpstart-32"
        self.config["OS_INSTALL_ISO"]["debian60"] = "deb6"
        self.config["OS_INSTALL_ISO"]["debian70"] = "deb7"
        self.config["OS_INSTALL_ISO"]["debian80"] = "deb8"
        
        self.config["HOTFIXES"] = {}
        self.config["HOTFIXES"]["Orlando"] = {"RTM": {}}
        self.config["HOTFIXES"]["George"] = {"RTM": {}}
        self.config["HOTFIXES"]["MNR"] = {"RTM": {}}
        self.config["HOTFIXES"]["MNRCC"] = {"RTM": {}}
        self.config["HOTFIXES"]["Cowley"] = {"RTM": {}}
        self.config["HOTFIXES"]["Oxford"] = {"RTM": {}}
        self.config["HOTFIXES"]["Boston"] = {"RTM": {}}
        self.config["HOTFIXES"]["Sanibel"] = {"RTM": {}}
        self.config["HOTFIXES"]["SanibelCC"] = {"RTM": {}}
        self.config["HOTFIXES"]["Tampa"] = {"RTM": {}}
        self.config["HOTFIXES"]["Clearwater"] = {"RTM": {}, "SP1": {}}
        self.config["HOTFIXES"]["Creedence"] = {"RTM": {}, "SP1": {}}

        self.config["TOOLS_HOTFIXES"] = {}
        self.config["TOOLS_HOTFIXES"]["Boston"] = {"RTM": []}
        self.config["TOOLS_HOTFIXES"]["Sanibel"] = {"RTM": []}
        self.config["TOOLS_HOTFIXES"]["SanibelCC"] = {"RTM": []}
        self.config["TOOLS_HOTFIXES"]["Tampa"] = {"RTM": []}
        self.config["TOOLS_HOTFIXES"]["Clearwater"] = {"RTM": [], "SP1": []}
        self.config["TOOLS_HOTFIXES"]["Creedence"] = {"RTM": [], "SP1": []}

        self.config["GUEST_TESTS"] = {}

        self.config["GUEST_TESTS"]["George"] = {}
        self.config["GUEST_TESTS"]["George"]["Primary"] = ['debian50_x86-32','rhel48_x86-32',
         'rhel53_x86-32','rhel53_x86-64','sles102_x86-32','sles102_x86-64','sles11_x86-32','sles11_x86-64','sles94_x86-32',
         'vistaeesp1','vistaeesp1-x64','w2k3eesp2','w2k3eesp2-x64','w2kassp4','win7-x64','win7-x86','winxpsp3','ws08-x64',
         'ws08-x86','ws08r2-x64']
        self.config["GUEST_TESTS"]["George"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos5_x86-32','centos5_x86-64','rhel45_x86-32',
         'rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64','rhel53_x86-32',
         'rhel53_x86-64','rhel5_x86-32','rhel5_x86-64','sles101_x86-32','sles101_x86-64','sles102_x86-32','sles102_x86-64',
         'vistaee','vistaee-x64','w2k3ee','w2k3eer2','w2k3eesp1','w2k3se','w2k3ser2','w2k3sesp1','w2k3sesp2','winxpsp2']
        self.config["GUEST_TESTS"]["George"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["MNR"] = {}
        self.config["GUEST_TESTS"]["MNR"]["Primary"] = ['debian50_x86-32','rhel48_x86-32','rhel54_x86-32','rhel54_x86-64',
         'sles103_x86-32','sles103_x86-64','sles11_x86-32','sles11_x86-64','sles94_x86-32','vistaeesp2','vistaeesp2-x64',
         'w2k3eesp2','w2k3eesp2-x64','w2kassp4','win7-x64','win7-x86','winxpsp3','ws08r2-x64','ws08sp2-x64','ws08sp2-x86']
        self.config["GUEST_TESTS"]["MNR"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos5_x86-32','centos5_x86-64','oel53_x86-32',
         'oel53_x86-64','oel54_x86-32','oel54_x86-64','rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32',
         'rhel51_x86-64','rhel52_x86-32','rhel52_x86-64','rhel53_x86-32','rhel53_x86-64','rhel5_x86-32','rhel5_x86-64',
         'sles101_x86-32','sles101_x86-64','sles102_x86-32','sles102_x86-64','vistaee','vistaee-x64','vistaeesp1',
         'vistaeesp1-x64','w2k3ee','w2k3eer2','w2k3eesp1','w2k3se','w2k3ser2','w2k3sesp1','w2k3sesp2','winxpsp2',
         'ws08-x64','ws08-x86']
        self.config["GUEST_TESTS"]["MNR"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Cowley"] = {}
        self.config["GUEST_TESTS"]["Cowley"]["Primary"] = ['debian50_x86-32','rhel48_x86-32','rhel55_x86-32',
         'rhel55_x86-64','rhel6_x86-32','rhel6_x86-64','sles103_x86-32','sles103_x86-64','sles111_x86-32','sles111_x86-64',
         'sles94_x86-32','vistaeesp2','vistaeesp2-x64','w2k3eesp2','w2k3eesp2-x64','win7sp1-x64','win7sp1-x86','winxpsp3',
         'ws08r2sp1-x64','ws08sp2-x64','ws08sp2-x86']
        self.config["GUEST_TESTS"]["Cowley"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos5_x86-32',
         'centos5_x86-64','oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32','oel55_x86-64',
         'rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64',
         'rhel53_x86-32','rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel5_x86-32','rhel5_x86-64','sles101_x86-32',
         'sles101_x86-64','sles102_x86-32','sles102_x86-64','sles11_x86-32','sles11_x86-64','vistaee','vistaee-x64',
         'vistaeesp1','vistaeesp1-x64','w2k3ee','w2k3eer2','w2k3eesp1','w2k3se','w2k3ser2','w2k3sesp1','w2k3sesp2',
         'win7-x64','ws08-x64','ws08-x86','ws08r2-x64','win7-x86']
        self.config["GUEST_TESTS"]["Cowley"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Boston"] = {}
        self.config["GUEST_TESTS"]["Boston"]["Primary"] = ['centos56_x86-32','centos56_x86-64','debian50_x86-32',
         'debian60_x86-32','debian60_x86-64','oel56_x86-32','oel56_x86-64','oel6_x86-32','oel6_x86-64','rhel48_x86-32',
         'rhel56_x86-32','rhel56_x86-64','rhel6_x86-32','rhel6_x86-64','sles104_x86-32','sles104_x86-64','sles111_x86-32',
         'sles111_x86-64','sles94_x86-32','ubuntu1004_x86-32',
         'ubuntu1004_x86-64','vistaeesp2','vistaeesp2-x64','w2k3eesp2','w2k3eesp2-x64','win7sp1-x64','win7sp1-x86',
         'winxpsp3','ws08dcsp2-x64','ws08dcsp2-x86','ws08r2dcsp1-x64']
        self.config["GUEST_TESTS"]["Boston"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos5_x86-32',
         'centos5_x86-64','oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32','oel55_x86-64',
         'rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64',
         'rhel53_x86-32','rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32','rhel55_x86-64','rhel5_x86-32',
         'rhel5_x86-64','sles102_x86-32','sles102_x86-64','sles103_x86-32','sles103_x86-64','sles11_x86-32',
         'sles11_x86-64','vistaee','vistaee-x64','vistaeesp1','vistaeesp1-x64','w2k3ee','w2k3eer2','w2k3eesp1','w2k3se',
         'w2k3ser2','w2k3sesp1','w2k3sesp2','win7-x64','ws08-x64','ws08-x86','ws08r2-x64','win7-x86']
        self.config["GUEST_TESTS"]["Boston"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Sanibel"] = {}
        self.config["GUEST_TESTS"]["Sanibel"]["Primary"] = ['centos56_x86-32','centos56_x86-64','centos57_x86-32',
         'centos57_x86-64','centos65_x86-32','centos65_x86-64','debian50_x86-32','debian60_x86-32','debian60_x86-64',
         'oel510_x86-32','oel510_x86-64','oel65_x86-32','oel65_x86-64','rhel48_x86-32','rhel56_x86-32','rhel56_x86-64',
         'rhel57_x86-32','rhel57_x86-64','rhel6_x86-32','rhel6_x86-64','sles104_x86-32','sles104_x86-64','sles111_x86-32',
         'sles111_x86-64','ubuntu1004_x86-32','ubuntu1004_x86-64','vistaeesp2',
         'vistaeesp2-x64','w2k3eesp2','w2k3eesp2-x64','w2k3eesp2pae','win7sp1-x64','win7sp1-x86','winxpsp3',
         'ws08dcsp2-x64','ws08dcsp2-x86','ws08r2dcsp1-x64']
        self.config["GUEST_TESTS"]["Sanibel"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos5_x86-32',
         'centos5_x86-64','centos63_x86-32','centos63_x86-64','centos64_x86-32','centos64_x86-64','oel53_x86-32',
         'oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32','oel55_x86-64','oel56_x86-32','oel56_x86-64',
         'oel57_x86-32','oel57_x86-64','rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64',
         'rhel52_x86-32','rhel52_x86-64','rhel53_x86-32','rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32',
         'rhel55_x86-64','rhel5_x86-32','rhel5_x86-64','sles102_x86-32','sles102_x86-64','sles103_x86-32','sles103_x86-64',
         'sles11_x86-32','sles11_x86-64','vistaee','vistaee-x64','vistaeesp1','vistaeesp1-x64','w2k3eer2','w2k3eesp1',
         'w2k3ser2','w2k3sesp1','w2k3sesp2','win7-x64','win7-x86','ws08-x64','ws08-x86','ws08r2-x64']
        self.config["GUEST_TESTS"]["Sanibel"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']


        self.config["GUEST_TESTS"]["Tampa"] = {}
        self.config["GUEST_TESTS"]["Tampa"]["Primary"] = ['centos57_x86-32','centos57_x86-64','centos61_x86-32',
         'centos61_x86-64','centos62_x86-32','centos62_x86-64','debian60_x86-32','debian60_x86-64','oel510_x86-32',
         'oel510_x86-64','oel65_x86-32','oel65_x86-64','rhel48_x86-32','rhel57_x86-32','rhel57_x86-64','rhel61_x86-32',
         'rhel61_x86-64','rhel62_x86-32','rhel62_x86-64','sles104_x86-32','sles104_x86-64','sles111_x86-32',
         'sles111_x86-64','ubuntu1004_x86-32','ubuntu1004_x86-64',
         'ubuntu1204_x86-32','ubuntu1204_x86-64','vistaeesp2','w2k3eesp2','w2k3eesp2-x64','win7sp1-x64','win7sp1-x86',
         'winxpsp3','ws08dcsp2-x64','ws08dcsp2-x86','ws08r2dcsp1-x64']
        self.config["GUEST_TESTS"]["Tampa"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos56_x86-32','centos56_x86-64','centos5_x86-32','centos5_x86-64',
         'centos6_x86-32','centos6_x86-64','oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32',
         'oel55_x86-64','oel56_x86-32','oel56_x86-64','oel57_x86-32','oel57_x86-64','oel61_x86-32','oel61_x86-64',
         'oel62_x86-32','oel62_x86-64','rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64',
         'rhel52_x86-32','rhel52_x86-64','rhel53_x86-32','rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32',
         'rhel55_x86-64','rhel56_x86-32','rhel56_x86-64','rhel5_x86-32','rhel5_x86-64','rhel6_x86-32','rhel6_x86-64',
         'sles102_x86-32','sles102_x86-64','sles103_x86-32','sles103_x86-64','sles11_x86-32','sles11_x86-64','w2k3eer2',
         'w2k3ser2','w2k3sesp2','win7-x64','win7-x86','ws08r2-x64']
        self.config["GUEST_TESTS"]["Tampa"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Clearwater"] = {}
        self.config["GUEST_TESTS"]["Clearwater"]["Primary"] = ['centos57_x86-32','centos57_x86-64','centos61_x86-32',
         'centos61_x86-64','centos62_x86-32','centos62_x86-64','debian60_x86-32','debian60_x86-64',
         'oel65_x86-32','oel65_x86-64','rhel48_x86-32','rhel57_x86-32','rhel57_x86-64','rhel61_x86-32',
         'rhel61_x86-64','rhel62_x86-32','rhel62_x86-64','sles104_x86-32','sles104_x86-64','sles111_x86-32',
         'sles111_x86-64','ubuntu1004_x86-32','ubuntu1004_x86-64','ubuntu1204_x86-32','ubuntu1204_x86-64','vistaeesp2',
         'w2k3eesp2','w2k3eesp2-x64','win7sp1-x64','win7sp1-x86','win8-x64','win8-x86','win81-x64','win81-x86','winxpsp3',
         'ws08dcsp2-x64','ws08dcsp2-x86','ws08r2dcsp1-x64','ws12-x64','ws12core-x64','ws12r2-x64','ws12r2core-x64']
        self.config["GUEST_TESTS"]["Clearwater"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos56_x86-32','centos56_x86-64','centos6_x86-32','centos6_x86-64',
         'oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32','oel55_x86-64','oel56_x86-32',
         'oel56_x86-64','oel57_x86-32','oel57_x86-64','oel61_x86-32','oel61_x86-64','oel62_x86-32','oel62_x86-64',
         'rhel45_x86-32','rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64',
         'rhel53_x86-32','rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32','rhel55_x86-64','rhel56_x86-32',
         'rhel56_x86-64','rhel6_x86-32','rhel6_x86-64','sles102_x86-32','sles102_x86-64','sles103_x86-32','sles103_x86-64',
         'sles11_x86-32','sles11_x86-64','w2k3eer2','w2k3ser2','w2k3sesp2','win7-x64','win7-x86','ws08r2-x64']
        self.config["GUEST_TESTS"]["Clearwater"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Creedence"] = {}
        self.config["GUEST_TESTS"]["Creedence"]["Primary"] = ['centos510_x86-32','centos510_x86-64','centos511_x86-32',
         'centos511_x86-64','centos65_x86-32','centos65_x86-64','centos66_x86-32','centos66_x86-64','centos7_x86-64',
         'debian60_x86-32','debian60_x86-64','debian70_x86-32','debian70_x86-64','oel510_x86-32','oel510_x86-64',
         'oel511_x86-32','oel511_x86-64','oel65_x86-32','oel65_x86-64','oel66_x86-32','oel66_x86-64','oel7_x86-64',
         'rhel48_x86-32','rhel510_x86-32','rhel510_x86-64','rhel511_x86-32','rhel511_x86-64','rhel65_x86-32',
         'rhel65_x86-64','rhel66_x86-32','rhel66_x86-64','rhel7_x86-64','sles104_x86-32',
         'sles104_x86-64','sles113_x86-32','sles113_x86-64',
         'sles12_x86-64','ubuntu1004_x86-32','ubuntu1004_x86-64','ubuntu1204_x86-32','ubuntu1204_x86-64',
         'ubuntu1404_x86-32','ubuntu1404_x86-64','vistaeesp2','w2k3eesp2','w2k3eesp2-x64',
         'win7sp1-x64','win7sp1-x86','win8-x64','win8-x86','win81-x64','win81-x86','winxpsp3','ws08dcsp2-x64',
         'ws08dcsp2-x86','ws08r2dcsp1-x64','ws12-x64','ws12core-x64','ws12r2-x64','ws12r2core-x64',
         'rhel5u_x86-32', 'rhel5u_x86-64', 'rhel6u_x86-32', 'rhel6u_x86-64', 'rhel7u_x86-64', 'rhel7xs_x86-64',
         'centos5u_x86-32', 'centos5u_x86-64', 'centos6u_x86-32', 'centos6u_x86-64', 'centos7u_x86-64', 'centos7xs_x86-64',
         'oel5u_x86-32', 'oel5u_x86-64', 'oel6u_x86-32', 'oel6u_x86-64', 'oel7u_x86-64', 'oel7xs_x86-64']
        self.config["GUEST_TESTS"]["Creedence"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos56_x86-32','centos56_x86-64','centos57_x86-32','centos57_x86-64',
         'centos58_x86-32','centos58_x86-64','centos59_x86-32','centos59_x86-64','centos63_x86-32','centos63_x86-64',
         'centos64_x86-32','centos64_x86-64','oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32',
         'oel55_x86-64','oel56_x86-32','oel56_x86-64','oel57_x86-32','oel57_x86-64','oel58_x86-32','oel58_x86-64',
         'oel59_x86-32','oel59_x86-64','oel63_x86-32','oel63_x86-64','oel64_x86-32','oel64_x86-64','rhel45_x86-32',
         'rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64','rhel53_x86-32',
         'rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32','rhel55_x86-64','rhel56_x86-32','rhel56_x86-64',
         'rhel57_x86-32','rhel57_x86-64','rhel58_x86-32','rhel58_x86-64','rhel59_x86-32','rhel59_x86-64','rhel63_x86-32',
         'rhel63_x86-64','rhel64_x86-32','rhel64_x86-64','sles102_x86-32','sles102_x86-64','sles103_x86-32',
         'sles103_x86-64','w2k3eer2','w2k3ser2','w2k3sesp2','win7-x64','ws08r2-x64','win7-x86']
        self.config["GUEST_TESTS"]["Creedence"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Cream"] = {}
        self.config["GUEST_TESTS"]["Cream"]["Primary"] = ['centos511_x86-32',
         'centos511_x86-64','centos66_x86-32','centos66_x86-64','centos71_x86-64',
         'debian60_x86-32','debian60_x86-64','debian70_x86-32','debian70_x86-64',
         'oel511_x86-32','oel511_x86-64','oel66_x86-32','oel66_x86-64','oel71_x86-64',
         'rhel48_x86-32','rhel511_x86-32','rhel511_x86-64','rhel66_x86-32','rhel66_x86-64',
         'rheld66_x86-64','rhelw66_x86-64','rhel71_x86-64',
         'sl511_x86-32','sl511_x86-64','sl66_x86-32','sl66_x86-64','sl71_x86-64',
         'sles104_x86-32','sles104_x86-64','sles113_x86-32','sles113_x86-64','sles12_x86-64',
         'ubuntu1204_x86-32','ubuntu1204_x86-64','ubuntu1404_x86-32','ubuntu1404_x86-64',
         'vistaeesp2','w2k3eesp2','w2k3eesp2-x64','win10-x64','win10-x86',
         'win7sp1-x64','win7sp1-x86','win8-x64','win8-x86','win81-x64','win81-x86','winxpsp3','ws08dcsp2-x64',
         'ws08dcsp2-x86','ws08r2dcsp1-x64','ws12-x64','ws12core-x64','ws12r2-x64','ws12r2core-x64','coreos-stable_x86-64',
         'rhel5u_x86-32', 'rhel5u_x86-64', 'rhel6u_x86-32', 'rhel6u_x86-64', 'rhel7u_x86-64', 'rhel71xs_x86-64',
         'sl5u_x86-32', 'sl5u_x86-64', 'sl6u_x86-32', 'sl6u_x86-64', 'sl7u_x86-64',
         'centos5u_x86-32', 'centos5u_x86-64', 'centos6u_x86-32', 'centos6u_x86-64', 'centos7u_x86-64', 'centos71xs_x86-64',
         'oel5u_x86-32', 'oel5u_x86-64', 'oel6u_x86-32', 'oel6u_x86-64', 'oel7u_x86-64', 'oel71xs_x86-64', 'sled113_x86-64']
        self.config["GUEST_TESTS"]["Cream"]["Secondary"] = ['centos45_x86-32','centos46_x86-32','centos47_x86-32',
         'centos48_x86-32','centos51_x86-32','centos51_x86-64','centos52_x86-32','centos52_x86-64','centos53_x86-32',
         'centos53_x86-64','centos54_x86-32','centos54_x86-64','centos55_x86-32','centos55_x86-64','centos56_x86-32','centos56_x86-64','centos57_x86-32','centos57_x86-64',
         'centos58_x86-32','centos58_x86-64','centos59_x86-32','centos59_x86-64','centos63_x86-32','centos63_x86-64',
         'centos64_x86-32','centos64_x86-64','oel53_x86-32','oel53_x86-64','oel54_x86-32','oel54_x86-64','oel55_x86-32',
         'oel55_x86-64','oel56_x86-32','oel56_x86-64','oel57_x86-32','oel57_x86-64','oel58_x86-32','oel58_x86-64',
         'oel59_x86-32','oel59_x86-64','oel63_x86-32','oel63_x86-64','oel64_x86-32','oel64_x86-64','rhel45_x86-32',
         'rhel46_x86-32','rhel47_x86-32','rhel51_x86-32','rhel51_x86-64','rhel52_x86-32','rhel52_x86-64','rhel53_x86-32',
         'rhel53_x86-64','rhel54_x86-32','rhel54_x86-64','rhel55_x86-32','rhel55_x86-64','rhel56_x86-32','rhel56_x86-64',
         'rhel57_x86-32','rhel57_x86-64','rhel58_x86-32','rhel58_x86-64','rhel59_x86-32','rhel59_x86-64','rhel63_x86-32',
         'rhel63_x86-64','rhel64_x86-32','rhel64_x86-64','sles102_x86-32','sles102_x86-64','sles103_x86-32',
         'sles103_x86-64','w2k3eer2','w2k3ser2','w2k3sesp2','win7-x64','ws08r2-x64','win7-x86',
         'rhel510_x86-32','rhel510_x86-64','centos510_x86-32','centos510_x86-64','oel510_x86-32','oel510_x86-64',
         'rhel65_x86-32','rhel65_x86-64','centos65_x86-32','centos65_x86-64','oel65_x86-32','oel65_x86-64',
         'rhel7_x86-64', 'oel7_x86-64', 'centos7_x86-64', 'sl7_x86-64']
        self.config["GUEST_TESTS"]["Cream"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']

        self.config["GUEST_TESTS"]["Dundee"] = {}
        self.config["GUEST_TESTS"]["Dundee"]["Primary"] = ['centos5u_x86-32', 'centos5u_x86-64',
            'centos6u_x86-32', 'centos6u_x86-64', 'centos7u_x86-64',
            'debian70_x86-32', 'debian70_x86-64', 'debian80_x86-32', 'debian80_x86-64',
            'oel511_x86-32', 'oel511_x86-64', 'oel5u_x86-32', 'oel5u_x86-64', 'oel66_x86-32', 'oel66_x86-64',
            'oel6u_x86-32', 'oel6u_x86-64', 'oel71_x86-64', 'oel71xs_x86-64', 'oel7u_x86-64',
            'rhel511_x86-32', 'rhel511_x86-64', 'rhel5u_x86-32', 'rhel5u_x86-64', 'rhel66_x86-32', 'rhel66_x86-64',
            'rhel6u_x86-32', 'rhel6u_x86-64', 'rhel71_x86-64', 'rhel71xs_x86-64', 'rhel7u_x86-64',
            'sles113_x86-32', 'sles113_x86-64', 'sled113_x86-64','sles114_x86-64','sles12_x86-64','sled12_x86-64',
            'ubuntu1204_x86-32', 'ubuntu1204_x86-64', 'ubuntu1404_x86-32', 'ubuntu1404_x86-64',
            'winxpsp3', 'w2k3eesp2', 'w2k3eesp2-x64',
            'vistaeesp2', 'ws08dcsp2-x64', 'ws08dcsp2-x86',
            'win7sp1-x64', 'win7sp1-x86', 'ws08r2dcsp1-x64',
            'win8-x64', 'win8-x86', 'ws12-x64',
            'win81-x64', 'win81-x86', 'ws12r2-x64',
            'win10-x64', 'win10-x86']
        self.config["GUEST_TESTS"]["Dundee"]["Secondary"] = ['centos511_x86-32', 'centos511_x86-64', 
            'centos66_x86-32', 'centos66_x86-64', 'centos71_x86-64', 'centos71xs_x86-64',
            'debian60_x86-32', 'debian60_x86-64', 'rhel48_x86-32', 'rheld66_x86-64', 'rhelw66_x86-64',
            'rhel63_x86-64',
            'sl511_x86-32', 'sl511_x86-64', 'sl5u_x86-32', 'sl5u_x86-64', 'sl66_x86-32', 'sl66_x86-64',
            'sl6u_x86-32', 'sl6u_x86-64', 'sl71_x86-64', 'sl7u_x86-64',
            'sles104_x86-32', 'sles104_x86-64', 'ws12core-x64', 'ws12r2core-x64']
        self.config["GUEST_TESTS"]["Dundee"]["Tertiary"] = ['centos48_x86-32',
            'centos510_x86-32', 'centos510_x86-64', 'centos51_x86-32', 'centos51_x86-64', 'centos52_x86-32', 'centos52_x86-64',
            'centos53_x86-32', 'centos53_x86-64', 'centos54_x86-32', 'centos54_x86-64', 'centos55_x86-32', 'centos55_x86-64',
            'centos56_x86-32', 'centos56_x86-64', 'centos57_x86-32', 'centos57_x86-64', 'centos58_x86-32', 'centos58_x86-64',
            'centos59_x86-32', 'centos59_x86-64', 'centos63_x86-32', 'centos63_x86-64', 'centos64_x86-32', 'centos64_x86-64',
            'centos65_x86-32', 'centos65_x86-64', 'centos7_x86-64',
            'oel510_x86-32', 'oel510_x86-64', 'oel53_x86-32', 'oel53_x86-64', 'oel54_x86-32', 'oel54_x86-64', 'oel55_x86-32', 'oel55_x86-64',
            'oel56_x86-32', 'oel56_x86-64', 'oel57_x86-32', 'oel57_x86-64', 'oel58_x86-32', 'oel58_x86-64', 'oel59_x86-32', 'oel59_x86-64',
            'oel63_x86-32', 'oel63_x86-64', 'oel64_x86-32', 'oel64_x86-64', 'oel65_x86-32', 'oel65_x86-64', 'oel7_x86-64',
            'rhel510_x86-32', 'rhel510_x86-64', 'rhel51_x86-32', 'rhel51_x86-64',
            'rhel52_x86-32', 'rhel52_x86-64', 'rhel53_x86-32', 'rhel53_x86-64', 'rhel54_x86-32', 'rhel54_x86-64', 'rhel55_x86-32', 'rhel55_x86-64',
            'rhel56_x86-32', 'rhel56_x86-64', 'rhel57_x86-32', 'rhel57_x86-64', 'rhel58_x86-32', 'rhel58_x86-64', 'rhel59_x86-32', 'rhel59_x86-64',
            'rhel63_x86-32', 'rhel64_x86-32', 'rhel64_x86-64', 'rhel65_x86-32', 'rhel65_x86-64', 'rhel7_x86-64',
            'sl7_x86-64', 'sles102_x86-32', 'sles102_x86-64', 'sles103_x86-32', 'sles103_x86-64', 'win7-x64', 'win7-x86', 'ws08r2-x64']
        self.config["GUEST_TESTS"]["Dundee"]["Dev"] = ['debiantesting_x86-32', 'debiantesting_x86-64', 'fedoralatest_x86-64', 'ubuntudevel_x86-32', 'ubuntudevel_x86-64']
        self.config["GUEST_TESTS"]["Dundee"]["XenApp"] = ['w2k3eesp2_XenApp', 'w2k3eesp2-x64_XenApp', 'ws08sp2-x86_XenApp', 'ws08sp2-x64_XenApp', 'ws08r2sp1-x64_XenApp']
       
        # Linux install methods supported
        nfsInstallSupport = ["rhel[dw]?[4-6]\d*_", "centos[4-6]\d*_", "sl[5-6]\d*_", "oel[4-6]\d*_", "sles9", "sles10", "sles11", "sled\d+"]
        noIsoInstallSupport = ["ubuntu1004", "debian60", "debian70", "debian80", "rhel45", "centos45", "centos46", "rhel\d+u", "rhel\d+xs", 
                               "centos\d+u", "centos\d+xs", "oel\d+u", "oel\d+xs", "sl\d+u", "sl\d+xs", "fedoralatest", "debiantesting", "ubuntudevel"]
        noHttpInstallSupport = ["rhel\d+u", "rhel\d+xs", "centos\d+u", "centos\d+xs", "oel\d+u", "oel\d+xs", "sl\d+u", "sl\d+xs"]
        # Process these into various categories
        for r in self.config["GUEST_TESTS"].keys():
            for g in self.config["GUEST_TESTS"][r].keys():
                self.config["GUEST_TESTS"][r]["%s_32BitPV" % g] = []
                self.config["GUEST_TESTS"][r]["%s_Not32BitPV" % g] = []
                self.config["GUEST_TESTS"][r]["%s_LinuxISOInstall" % g] = []
                self.config["GUEST_TESTS"][r]["%s_LinuxHTTPInstall" % g] = []
                self.config["GUEST_TESTS"][r]["%s_LinuxNFSInstall" % g] = []
                for d in self.config['GUEST_TESTS'][r][g]:
                    if xenrt.is32BitPV(d, release=r, config=self):
                        self.config["GUEST_TESTS"][r]["%s_32BitPV" % g].append(d)
                    else:
                        self.config["GUEST_TESTS"][r]["%s_Not32BitPV" % g].append(d)
                    if not xenrt.isWindows(d):
                        if not [x for x in noIsoInstallSupport if re.match(x, d)]:
                            self.config["GUEST_TESTS"][r]["%s_LinuxISOInstall" % g].append(d)
                        if not [x for x in noHttpInstallSupport if re.match(x, d)]:
                            self.config["GUEST_TESTS"][r]["%s_LinuxHTTPInstall" % g].append(d)
                        if [x for x in nfsInstallSupport if re.match(x, d)]:
                            self.config["GUEST_TESTS"][r]["%s_LinuxNFSInstall" % g].append(d)

        self.config["DEFAULT_HOTFIX_BRANCH"] = {}
        self.config["DEFAULT_HOTFIX_BRANCH"]["Clearwater"] = "SP1"
        self.config["DEFAULT_HOTFIX_BRANCH"]["Creedence"] = "SP1"
        
        self.config["HOTFIXES"]["Orlando"]["RTM"]["HF1"] = "/usr/groups/release/XenServer-5.0.0-Update1RC3/XenServer-5.0.0-Update1.xsupdate"
        self.config["HOTFIXES"]["Orlando"]["RTM"]["HF2"] = "/usr/groups/release/XenServer-5.0.0-Update2RC3/XenServer-5.0.0-Update2.xsupdate"
        self.config["HOTFIXES"]["Orlando"]["RTM"]["HF3"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA/XenServer-5.0.0-Update3.xsupdate"

        # openssl, xen. Rolls up nothing
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3004"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3004/retail-34723/hotfix-teresia/hotfix.xsupdate"
        
        # dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up nothing
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3005"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3005/retail-35120/hotfix-JPN-1/hotfix.xsupdate"
      
        # openssl, xen. Rolls up nothing
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3007"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3007/37877/hotfix-XS50EU3007/hotfix.xsupdate"
      
        # openssl, xen, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3007, XS50EU3005
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3008"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3008/44289/hotfix-XS50EU3008/XS50EU3008.xsupdate"
      
        # dhcp, openssl, xen, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3008, XS50EU3007, XS50EU3005
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3009"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3009/49952/hotfix-XS50EU3009/XS50EU3009.xsupdate"
      
        # xapi. Rolls up Nothing
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3010"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3010/55266/hotfix-XS50EU3010/XS50EU3010.xsupdate"
      
        # dhcp, openssl, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3009, XS50EU3008, XS50EU3007, XS50EU3005, XS50EU3004
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3011"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3011/55169/hotfix-XS50EU3011/XS50EU3011.xsupdate"
      
        # orjen: dhcp, openssl, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3011, XS50EU3009, XS50EU3008, XS50EU3007, XS50EU3005, XS50EU3004
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3012"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3012/58394/hotfix-XS50EU3012/XS50EU3012.xsupdate"
      
        # Osvald: dhcp, openssl, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3012, XS50EU3011, XS50EU3009, XS50EU3008, XS50EU3007, XS50EU3005, XS50EU3004
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3013"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3013/61582/hotfix-XS50EU3013/XS50EU3013.xsupdate"
    
        # Ossian: dhcp, openssl, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3013, XS50EU3012, XS50EU3011, XS50EU3009, XS50EU3008, XS50EU3007, XS50EU3005, XS50EU3004
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3014"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3014/61776/hotfix-XS50EU3014/XS50EU3014.xsupdate"
    
        # Gruffalo: dhcp, openssl, dom0 kernel, xen, adp94xx, arcmsr, gnbdm lpfc, mtnic, nxnic, pvx, qla2, qla4. Rolls up U3, XS50EU3014, XS50EU3013, XS50EU3012, XS50EU3011, XS50EU3009, XS50EU3008, XS50EU3007, XS50EU3005, XS50EU3004
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3015"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3015/63026/hotfix-XS50EU3015/XS50EU3015.xsupdate"
      
        # Boo: adp94xx, arcmsr, dhcp, dom0 kernel, gnbdm, lpfc, md3000-rdac, mtnic, nxnic, openssl, pvs, qla2, qla4, vncterm, xen. Rolls up XS50EU3002, XS50EU3004, XS50EU3005, XS50EU3007, XS50EU3008, XS50EU3009, XS50EU3011, XS50EU3012, XS50EU3013, XS50EU3014, XS50EU3015
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3016"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3016/68966/hotfix-XS50EU3016/XS50EU3016.xsupdate"
      
        # KingKong: adp94xx, arcmsr, dhcp, gnbd, kernel-kdump, kernel-xen, lpfc, md3000-rdac, mtnic, nx_nix, openssl, pvs-modules, qla2, qla4, vncterm, xen-device-model, xen-hypervisor. Rolls up XS50EU3002, XS50EU3004, XS50EU3005, XS50EU3007, XS50EU3008, XS50EU3009, XS50EU3011, XS50EU3012, XS50EU3013, XS50EU3014, XS50EU3015, XS50EU3016
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3017"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3017/72147/hotfix-XS50EU3017/XS50EU3017.xsupdate"
      
        # DonkeyKong: adp, arcmsr, dhcp, gnbd, kernel-kdump, kernel-xen, lpfc, md3000, mtnic, nx_nic, openssl, pvs, qla, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS50EU3002, XS50EU3004, XS50EU3005, XS50EU3007, XS50EU3008, XS50EU3009, XS50EU3011, XS50EU3012, XS50EU3013, XS50EU3014, XS50EU3015, XS50EU3016, XS50EU3017
        self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3018"] = "/usr/groups/release/XenServer-5.0.0-Update3-GA-extras/hotfixes/XS50EU3018/72567/hotfix-XS50EU3018/XS50EU3018.xsupdate"
        
        self.config["HOTFIXES"]["George"]["RTM"]["LVHD"] = "/usr/groups/release/XenServer-5.5.0/hotfixes/lvhd-fix1/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["EPT"] = "/usr/groups/release/XenServer-5.5.0/hotfixes/xen-fix1/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["EPT2"] = "/usr/groups/xen/carbon/george-update-1/18471/xen-fix3/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["TIME"] = "/usr/groups/release/XenServer-5.5.0/hotfixes/xen-fix2/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["BERIT"] = "/usr/groups/release/XenServer-5.5.0-CTX123193-RC1/XenServer-5.5.0-CTX123193.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["STEELEYE"] = "/usr/groups/release/XenServer-5.5.0/hotfixes/steeleye-fix1/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["HF1"] = "/usr/groups/release/XenServer-5.5.0-Update1/hotfix.xsupdate"
        self.config["HOTFIXES"]["George"]["RTM"]["HF2"] = "/usr/groups/release/XenServer-5.5.0-Update2/hotfix.xsupdate"
        
        # Bad-mac: xen-device-model. Rolls up nothing
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2004"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2004/38036/XS55EU2004.xsupdate"

        #  Fawlty: tools iso. Rolls up nothing
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2005"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2005/41243/hotfix-XS55EU2005/XS55EU2005.xsupdate"

        #  Irma: arcmsr, kernel, mtnic, nx_nic, opensll, qla2, qla4, xen. Rolls up XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2006"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2006/44288/hotfix-XS55EU2006/XS55EU2006.xsupdate"

        #  George 24x7: likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, opensll, qla2, qla4, xen. Rolls up XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2007"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2007/50111/hotfix-XS55EU2007/XS55EU2007.xsupdate"

        #  HA. Rolls up nothing
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2008"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2008/48863/hotfix-XS55EU2008/XS55EU2008.xsupdate"

        #  Masterfix: xapi. Rolls up Networking hotfix for XenServer 5.5.0 update 2, Huawei hotfix for XenServer 5.5.0.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2009"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2009/50862/hotfix-XS55EU2009/XS55EU2009.xsupdate"

        #  Goran: xapi, management iface script. Rools up XS55EU2009, Networking hotfix for XenServer 5.5.0 update 2, Huawei hotfix for XenServer 5.5.0.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2010"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2010/55254/hotfix-XS55EU2010/XS55EU2010.xsupdate"

        #  bug-tool, dhcp, likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, openssl, qla2, qla4, xen. Rolls up XS55EU2007, XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2011"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2011/56480/hotfix-XS55EU2011/XS55EU2011.xsupdate"

        #  Jon: vncterm, bug-tool, dhcp, likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, openssl, qla2, qla4, xen. Rolls up XS55EU2011, XS55EU2007, XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2012"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2012/58406/hotfix-XS55EU2012/XS55EU2012.xsupdate"
      
        #  Jarl: vncterm, bug-tool, dhcp, likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, openssl, qla2, qla4, xen. Rolls up XS55EU2012, XS55EU2011, XS55EU2007, XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2013"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2013/61586/hotfix-XS55EU2013/XS55EU2013.xsupdate"
      
        #  Johan: vncterm, bug-tool, dhcp, likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, openssl, qla2, qla4, xen. Rolls up XS55EU2013, XS55EU2012, XS55EU2011, XS55EU2007, XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2014"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2014/61770/hotfix-XS55EU2014/XS55EU2014.xsupdate"
      
        #  Gruffalo: vncterm, bug-tool, dhcp, likewise, lpfc, arcmsr, kernel, mtnic, nx_nic, openssl, qla2, qla4, xen. Rolls up XS55EU2014, XS55EU2013, XS55EU2012, XS55EU2011, XS55EU2007, XS55EU2006, XS55EU2003, XS55EU2001.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2015"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2015/63014/hotfix-XS55EU2015/XS55EU2015.xsupdate"
      
        #  Boo: arcmsr, dhcp, dom 0 kernel, likewise, lpfc, md3000-rdac, mtnic, nxnic, openssl, xenstored, qla2, qla4, xen-bugtool, vncterm, xen. Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2016"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2016/68995/hotfix-XS55EU2016/XS55EU2016.xsupdate"
       
        #  KingKong: arcmsr, dhcp, kernel-kdump, kernel-xen, likewise, lpfc, md3000, mtnic, nx_nic, openssl, qla, xen-bugtool,  vncterm, xen-device, xen-hypervisor. Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2017"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2017/70457/hotfix-XS55EU2017/XS55EU2017.xsupdate"
      
        #  DonkeyKong: arcmsr, dhcp, kernel-kdump, kernel-xen, likewise, lpfc, md3000, mtnic, nx_nic, openssl, qla, xen-bugtool, vncterm, xen-device-model, xen-hypervisor, xen-tools, xenstored. Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017.
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2018"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2018/72551/hotfix-XS55EU2018/XS55EU2018.xsupdate"
        
        #  Blunt: xenstored, xen-bugtool, arcmsr, dhcp, kernel-kdump, kernel-xen, likewise, lpfc, md3000, mtnic, nx_nic, openssl, qla, vncterm, xen-device, xen-hypervisor, xen-tools. Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017, XS55EU2018
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2019"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2019/75805/hotfix-XS55EU2019/XS55EU2019.xsupdate"
        
        #  Carabosse:openssl, xenstored , qla2xxx-modules-kdump, qla2xxx-modules-xen, qla4xxx-modules-kdump, qla4xxx-modules-xen, xen-bugtool , vncterm, xen-device-model, xen-hypervisor xen-tools... Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017, XS55EU2018, XS55EU2019
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2020"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2020/77604/hotfix-XS55EU2020/XS55EU2020.xsupdate"
        
        #  AliBaba:openssl, xen-hyp , qemu. Rolls up XS55EU2001,XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017, XS55EU2018, XS55EU2019, XS55EU2020
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2021"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2021/86503/hotfix-XS55EU2021/XS55EU2021.xsupdate"
        
        #  Ronan:arcmsr-modules, dhcp, kernel, likewise, lpfc, md3000-rdac, mtnic, nx_nic, openssl, qla2xxx, qla4xxx, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017, XS55EU2018,XS55EU2019, XS55EU2020, XS55EU2021
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2022"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2022/88499/hotfix-XS55EU2022/XS55EU2022.xsupdate"
        
        #  ShellShock: bash. Rolls up nothing
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2023"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2023/88767/hotfix-XS55EU2023/XS55EU2023.xsupdate"
        
        #  Guy: xen-hyp, xen-tools. Rolls XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017,XS55EU2018, XS55EU2019, XS55EU2020, XS55EU2021, XS55EU2022
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2024"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2024/89773/hotfix-XS55EU2024/XS55EU2024.xsupdate"
        
        #  Guy: glibc, xen-tools. Rolls nothing
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2025"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2025/91296/hotfix-XS55EU2025/XS55EU2025.xsupdate"
        
        #  Burgess: xen-hyp. Rolls XS55EU2001, XS55EU2003, XS55EU2006, XS55EU2007, XS55EU2011, XS55EU2012, XS55EU2013, XS55EU2014, XS55EU2015, XS55EU2016, XS55EU2017, XS55EU2018,XS55EU2019, XS55EU2020, XS55EU2021, XS55EU2022, XS55EU2024
        self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2026"] = "/usr/groups/release/XenServer-5.5.0-Update2-rc3/hotfixes/XS55EU2026/92027/hotfix-XS55EU2026/XS55EU2026.xsupdate"
        
        
        # INT-mnr-1: stunnel
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E001"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E001/36186/hotfix-XS56E001/hotfix.xsupdate"
      
        # James-Plus: kernel
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E002"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E002/37656/hotfix-james/XS56E002.xsupdate"
      
        # Black: opt/xensource/sm/CSLGSR.py
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E003"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E003/37793/XS56E003.xsupdate"
      
        # Diva: xapi
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E004"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E004/38098/XS56E004.xsupdate"
      
        # Slinky: StorageLink bridge
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E005"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E005/39736/hotfix-XS56E005/XS56E005.xsupdate"
      
        # Sanders: kernel. Rolls up XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E006"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E006/40276/hotfix-XS56E006/XS56E006.xsupdate"
      
        # Sylvester: xapi, bugtool, xen. Rolls up XS56E004
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E007"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E007/45744/hotfix-XS56E007/XS56E007.xsupdate"
      
        # Nadia: likewise, kernel, xen. Rolls up XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E009"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E009/48655/hotfix-XS56E009/XS56E009.xsupdate"
      
        # MNR24x7: HA
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E010"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E010/48917/hotfix-XS56E010/XS56E010.xsupdate"
      
        # MNR Overkill: LVHDoHBASR.py, LVHDoISCSISR.py
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E011"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E011/50647/hotfix-XS56E011/XS56E011.xsupdate"
      
        # Dolly: kernel, likewise, xen. Rolls up XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E012"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E012/51888/hotfix-XS56E012/XS56E012.xsupdate"
      
        # Markus: kernel, likewise, xen. Rolls up XS56E012, XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E013"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E013/56477/hotfix-XS56E013/XS56E013.xsupdate"
      
        # Rolf : openssl, vncterm, kernel, likewise, xen, xapi. Rolls up XS56E013, XS56E012, XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E014"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E014/58408/hotfix-XS56E014/XS56E014.xsupdate"
      
        # Marita : openssl, vncterm, kernel, likewise, xen, xapi. Rolls up XS56E014, XS56E013, XS56E012, XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E015"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E015/61588/hotfix-XS56E015/XS56E015.xsupdate"
      
        # Malena : openssl, vncterm, kernel, likewise, xen, xapi. Rolls up XS56E015, XS56E014, XS56E013, XS56E012, XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E016"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E016/61803/hotfix-XS56E016/XS56E016.xsupdate"
      
        # Gruffalo : openssl, vncterm, kernel, likewise, xen, xapi. Rolls up XS56E016, XS56E015, XS56E014, XS56E013, XS56E012, XS56E009, XS56E006, XS56E007, XS56E004, XS56E002
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E017"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E017/63012/hotfix-XS56E017/XS56E017.xsupdate"
      
        # Boo: dom 0 kernel, likewise, md3000-rdac, xenstored, vncterm, xen. Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E018"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E018/68996/hotfix-XS56E018/XS56E018.xsupdate"
      
        # Sid: kernel-kdump, kernel-xen, likewise, md3000-rdac, openssl, xapi, xenstored, xen-bugtool, vncterm, device-model, xen. Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017, XS56E018
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E019"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E019/69343/hotfix-XS56E019/XS56E019.xsupdate"
      
        # KingKong: kernel-kdump, kernel-xen, likewise, md3000-rdac-modules-kdymp, md3000-modules-xen, xapi, xenstored, xen-bugtool, vncterm, xen-device-model, xen-hypervisor. Rolls up Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017, XS56E018, XS56E019
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E020"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E020/72136/hotfix-XS56E020/XS56E020.xsupdate"
      
        # DonkeyKong: inittab, kernel-kdump, kernel-xen, likewise, md3000, openssl, xapi, xenstored, xen-bugtool, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017, XS56E018, XS56E019, XS56E020
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E021"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E021/72571/hotfix-XS56E021/XS56E021.xsupdate"
        
        # Blunt: inittab, xapi, xenstored, xen-bugtool, kernel-kdump, kernel-xen, likewise, md3000, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017, XS56E018, XS56E019, XS56E020, XS56E021
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E022"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E022/75810/hotfix-XS56E022/XS56E022.xsupdate"
        
        # Carabosse: inittab, kernel-xen, likewise, openssl, xapi, xenstored, xen-bugtool, md3000, xen-device, vncterm, xen-hypervisor, xen-tools . Rolls up XS56E002, XS56E004, XS56E006, XS56E007, XS56E009, XS56E012, XS56E013, XS56E014, XS56E015, XS56E016, XS56E017, XS56E018, XS56E019, XS56E020, XS56E021, XS56E022
        self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E023"] = "/usr/groups/release/XenServer-5.6.0/hotfixes/XS56E023/77134/hotfix-XS56E023/XS56E023.xsupdate"
      
      
      
      
        # Peter: xapi
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1001"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1001/41063/hotfix-XS56EFP1001/hotfix.xsupdate"
      
        # Lucia: xen, kernel
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1004"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1004/45836/hotfix-XS56EFP1004/XS56EFP1004.xsupdate"

        # Lethargy: xapi. Rolls up XS56EFP1001.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1005"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1005/43712/hotfix-XS56EFP1005/XS56EFP1005.xsupdate"
      
        # Stomp: xapi. Rolls up XS56EFP1005, XS56EFP1001.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1006"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1006/46680/hotfix-XS56EFP1006/hotfix.xsupdate"
      
        # Hog: xen, kernel. Rolls up XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1007"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1007/47081/hotfix-XS56EFP1007/XS56EFP1007.xsupdate"
      
        # Carina: likewise, xen, kernel, dhcp. Rolls up XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1008"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1008/50284/hotfix-XS56EFP1008/XS56EFP1008.xsupdate"
      
        # Hydra: xapi. Rolls up XS56EFP1006, XS56EFP1005, XS56EFP1001.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1009"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1009/52693/hotfix-XS56EFP1009/XS56EFP1009.xsupdate"
      
        # Ylva1: xapi. Rolls up XS56EFP1009, XS56EFP1006, XS56EFP1005, XS56EFP1001.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1010"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1010/55262/hotfix-XS56EFP1010/XS56EFP1010.xsupdate"
      
        # Ylva2: likewise, xen, kernel, dhcp. Rolls up XS56EFP1008, XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1011"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1011/56475/hotfix-XS56EFP1011/XS56EFP1011.xsupdate"
      
        # Kaj: vncterm, openssl, likewise, xen, kernel, dhcp. Rolls up XS56EFP1011, XS56EFP1008, XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1012"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1012/58410/hotfix-XS56EFP1012/XS56EFP1012.xsupdate"
      
        # Lukas: vncterm, openssl, likewise, xen, kernel, dhcp. Rolls up XS56EFP1012, XS56EFP1011, XS56EFP1008, XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1013"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1013/61583/hotfix-XS56EFP1013/XS56EFP1013.xsupdate"
      
        # Katja: vncterm, openssl, likewise, xen, kernel, dhcp. Rolls up XS56EFP1013, XS56EFP1012, XS56EFP1011, XS56EFP1008, XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1014"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1014/61799/hotfix-XS56EFP1014/XS56EFP1014.xsupdate"
      
        # Gruffalo #1: xapi. Rolls up XS56EFP1010, XS56EFP1009, XS56EFP1006, XS56EFP1005, XS56EFP1001.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1015"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1015/62902/hotfix-XS56EFP1015/XS56EFP1015.xsupdate"

        # Gruffalo #2: vncterm, openssl, likewise, xen, kernel, dhcp. Rolls up XS56EFP1014, XS56EFP1013, XS56EFP1012, XS56EFP1011, XS56EFP1008, XS56EFP1007, XS56EFP1004.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1016"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1016/63027/hotfix-XS56EFP1016/XS56EFP1016.xsupdate"
      
        # Boo: dhcp, dom0 kernel, likewise, md3000-rdac, openssl, bugtool, vncterm, xen. Rolls up XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1017"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1017/68970/hotfix-XS56EFP1017/XS56EFP1017.xsupdate"
      
        # Sid: kernel-kdump, kernel-xen, likewise, md3000-rdac, openssl. Rolls up XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016, XS56EFP1017.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1018"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1018/69341/hotfix-XS56EFP1018/XS56EFP1018.xsupdate"
      
        # KingKong: dhcp, kernel-kdump, kernel-xen, likewise, md3000, openssl, xen-bugtool, vncterm, xen-device-model, xen-hypervisor. Rolls up XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016, XS56EFP1017, XS56EFP1018.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1019"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1019/72171/hotfix-XS56EFP1019/XS56EFP1019.xsupdate"
      
        # DonkeyKong: dhcp, kernel-kdump, kernel-xen, likewise, md3000, openssl, xen-bugtool, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016, XS56EFP1017, XS56EFP1018, XS56EFP1019.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1020"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1020/72549/hotfix-XS56EFP1020/XS56EFP1020.xsupdate"
        
        # Blunt: xen-bugtool, dhcp, kernel-kdump, kernel-xen, likewise, md3000, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up  	XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016, XS56EFP1017, XS56EFP1018, XS56EFP1019, XS56EFP1020.
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1021"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1021/75820/hotfix-XS56EFP1021/XS56EFP1021.xsupdate"
        
        # Carabosse: dhcp, kernel-kdump, kernel-xen, likewise, md3000, md3000, openssl, xen-bugtool, vncterm, xen-device-model, xen-hypervisor, xen-tools . Rolls up  	XS56EFP1004, XS56EFP1007, XS56EFP1008, XS56EFP1011, XS56EFP1012, XS56EFP1013, XS56EFP1014, XS56EFP1016, XS56EFP1017, XS56EFP1018, XS56EFP1019, XS56EFP1020, XS56EFP1021 
        self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1022"] = "/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/hotfixes/XS56EFP1022/77176/hotfix-XS56EFP1022/XS56EFP1022.xsupdate"
      
        self.config["HOTFIXES"]["Cowley"]["RTM"]["HFOXFORD"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/RTM-47101/hotfix/XS56ESP2.xsupdate"
      
      
      
        # Bob
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2001"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2001/47929/hotfix-XS56ESP2001/XS56ESP2001.xsupdate"

        # Monika dom0 kernel, xen
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2002"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2002/50282/hotfix-XS56ESP2002/XS56ESP2002.xsupdate"

        # Oxford24x7, xha
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2003"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2003/48937/hotfix-XS56ESP2003/XS56ESP2003.xsupdate"

        # Overkill: LVHDoISCSISR.py, LVHDoHBASR.py
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2004"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2004/49768/hotfix-XS56ESP2004/XS56ESP2004.xsupdate"

        # CoursDump: dom0 kernel, xen. Rolls up XS56ESP2002.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2005"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2005/50891/hotfix-XS56ESP2005/XS56ESP2005.xsupdate"

        # Branson: dom0 kernel, xen. Rolls up XS56ESP2005 and XS56ESP2002.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2006"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2006/51232/hotfix-XS56ESP2006/XS56ESP2006.xsupdate"

        # Catch22: LVHDSR.py, cleanup.py
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2007"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2007/52141/hotfix-XS56ESP2007/XS56ESP2007.xsupdate"

        # Oxford Milton: blktap
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2008"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2008/52820/hotfix-XS56ESP2008/XS56ESP2008.xsupdate"

        # Oxford Hydra: xapi
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2009"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2009/52973/hotfix-XS56ESP2009/XS56ESP2009.xsupdate"

        # BinIt: cslg bridge
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2010"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2010/53308/hotfix-XS56ESP2010/XS56ESP2010.xsupdate"

        # Brian: xen-firmware
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2011"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2011/53854/hotfix-XS56ESP2011/XS56ESP2011.xsupdate"

        # SCTX-771: mpath_dmp.py, LVHDoHBASR.py
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2012"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2012/53854/hotfix-XS56ESP2012/XS56ESP2012.xsupdate"

        # Jones: Dom0 kernel, xen. Rolls up XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2013"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2013/54148/hotfix-XS56ESP2013/XS56ESP2013.xsupdate"

        # Shuffle: xapi. Rolls up XS56ESP2009
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2014"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2014/54441/hotfix-XS56ESP2014/XS56ESP2014.xsupdate"

        # Ferdinand1: xapi. Rolls up XS56ESP2014, XS56ESP2009
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2015"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2015/55265/hotfix-XS56ESP2015/XS56ESP2015.xsupdate"

        # Ferdinand2: Dom0 kernel, xen. Rolls up XS56ESP2013, XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2016"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2016/56474/hotfix-XS56ESP2016/XS56ESP2016.xsupdate"

        # Jitterbug:
        #self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2017"] = ""

        # Tutti Xapi: xapi. Rolls up XS56ESP2015, XS56ESP2014, XS56ESP2009
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2018"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2018/57260/hotfix-XS56ESP2018/XS56ESP2018.xsupdate"

        # Roland: openssl, vncterm, Dom0 kernel, xen, device model. Rolls up XS56ESP2016, XS56ESP2013, XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2019"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2019/58405/hotfix-XS56ESP2019/XS56ESP2019.xsupdate"

        # Ottoman: cleanup.py, ISCSISR.py, ISOSR.py, LVHDoHBASR.py, LVHDoISCSISR.py, LVHDSR.py, mpathHBA, mpath_dmp.py. Rolls up XS56ESP2012, XS56ESP2007, XS56ESP2004
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2020"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2020/61147/hotfix-XS56ESP2020/XS56ESP2020.xsupdate"
      
        # Frans: openssl, vncterm, Dom0 kernel, xen, device model. Rolls up XS56ESP2019, XS56ESP2016, XS56ESP2013, XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2021"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2021/61585/hotfix-XS56ESP2021/XS56ESP2021.xsupdate"
      
        # Isak: openssl, vncterm, Dom0 kernel, xen, device model. Rolls up XS56ESP2021, XS56ESP2019, XS56ESP2016, XS56ESP2013, XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2022"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2022/61798/hotfix-XS56ESP2022/XS56ESP2022.xsupdate"
      
        # Gruffalo #1: xapi. Rolls up XS56ESP2018, XS56ESP2015, XS56ESP2014, XS56ESP2009
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2023"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2023/62904/hotfix-XS56ESP2023/XS56ESP2023.xsupdate"
      
        # Gruffalo #2: openssl, vncterm, Dom0 kernel, xen, device model. Rolls up XS56ESP2022, XS56ESP2021, XS56ESP2019, XS56ESP2016, XS56ESP2013, XS56ESP2006, XS56ESP2005, XS56ESP2002
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2024"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2024/63025/hotfix-XS56ESP2024/XS56ESP2024.xsupdate"
      
        # LockBox: ISCSISR.py, ISOSR.py, LVHDSR.py, LVHDoHBASR.py, LVHDoISCSISR.py, cleanup.py, mpathHBA, mpath_dmp.py, vhdutil.py. Rolls up XS56ESP2004, XS56ESP2007, XS56ESP2008, XS56ESP2012, XS56ESP2020
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2025"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2025/68837/hotfix-XS56ESP2025/XS56ESP2025.xsupdate"
      
        # Makita: tools
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2026"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2026/68822/hotfix-XS56ESP2026/XS56ESP2026.xsupdate"

        # Boo: dom0 kernel, md3000-rdac, openssl, vncterm, xen. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2027"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2027/68979/hotfix-XS56ESP2027/XS56ESP2027.xsupdate"
      
        # Sid: kernel-kdump, kernel-xen, md3000-rdac, openssl, vncterm, device-model, xen. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024, XS56ESP2027.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2028"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2028/69339/hotfix-XS56ESP2028/XS56ESP2028.xsupdate"
      
        # Bruce: loadbrsysctl, kernel-kdump, kernel-xen, md3000-rdac-modules-kdump, md3000-rdac-modules-xen, openssl, vncterm, xen-device-model, xen-hypervisor. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024 , XS56ESP2027, XS56ESP2028.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2029"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2029/70414/hotfix-XS56ESP2029/XS56ESP2029.xsupdate"
      
        # Dusty: blktap, cleanup.py, intellicache-clean, sm. Rolls up XS56ESP2004, XS56ESP2007, XS56ESP2008, XS56ESP2012, XS56ESP2020, XS56ESP2025.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2030"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2030/70414/hotfix-XS56ESP2030/XS56ESP2030.xsupdate" 
      
        # KingKong: kernel-kdump, kernel-xen, md3000-rdac, openssl, vncterm, xen-device-model, xen-hypervisor. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024 , XS56ESP2027, XS56ESP2028, XS56ESP2029.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2031"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2031/72206/hotfix-XS56ESP2031/XS56ESP2031.xsupdate"
      
        # DonkeyKong: init.d, loadbrsysctl, kernel-kdump, kernel-xen, md3000, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024 , XS56ESP2027, XS56ESP2028, XS56ESP2029, XS56ESP2031.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2032"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2032/72510/hotfix-XS56ESP2032/XS56ESP2032.xsupdate"
        
        # Blunt: loadbrsysctl, kernel-kdump, kernel-xen, md3000, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024 , XS56ESP2027, XS56ESP2028, XS56ESP2029, XS56ESP2031, XS56ESP2032.
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2033"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2033/75822/hotfix-XS56ESP2033/XS56ESP2033.xsupdate"
        
        # Carabosse: loadbrsysctl , kernel-kdump, kernel-xen, md3000, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools . Rolls up XS56ESP2002, XS56ESP2005, XS56ESP2006, XS56ESP2013, XS56ESP2016, XS56ESP2019, XS56ESP2021, XS56ESP2022, XS56ESP2024, XS56ESP2027, XS56ESP2028, XS56ESP2029, XS56ESP2031, XS56ESP2032, XS56ESP2033 
        self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2034"] = "/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/hotfixes/XS56ESP2034/77126/hotfix-XS56ESP2034/XS56ESP2034.xsupdate"
      
      
      
      
      
      
        # dom0kernel. Rolled up nothing. 
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC001"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC001/45977/hotfix-XS56ECC001/XS56ECC001.xsupdate"

        # dhcp. Rolled up nothing
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC002"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC002/49533/hotfix-XS56ECC002/XS56ECC002.xsupdate"

        # xapi. Rolled up nothing
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC003"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC003/55259/hotfix-XS56ECC003/XS56ECC003.xsupdate"

        # openssl, vncterm, xen, device-model. Rolled up nothing
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC004"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC004/58407/hotfix-XS56ECC004/XS56ECC004.xsupdate"

        # openssl, vncterm, xen, device-model. Rolled up XS56ECC004
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC005"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC005/61587/hotfix-XS56ECC005/XS56ECC005.xsupdate"
      
        # openssl, vncterm, xen, device-model. Rolled up XS56ECC005, XS56ECC004
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC006"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC006/61802/hotfix-XS56ECC006/XS56ECC006.xsupdate"
      
        # Gruffalo: dom0kernel. Rolled up XS56ECC001
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC007"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC007/63019/hotfix-XS56ECC007/XS56ECC007.xsupdate"
      
        # Sid: openssl, vncterm, xen, device-model. Rolls up XS56ECC004, XS56ECC005, XS56ECC006.
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC008"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC008/69345/hotfix-XS56ECC008/XS56ECC008.xsupdate"
      
        # DonkeyKong: openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56ECC004, XS56ECC005, XS56ECC006, XS56ECC008.
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC009"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC009/72552/hotfix-XS56ECC009/XS56ECC009.xsupdate"
        
        # Blunt: openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS56ECC004, XS56ECC005, XS56ECC006, XS56ECC008, XS56ECC009 
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC010"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC010/75816/hotfix-XS56ECC010/XS56ECC010.xsupdate"
        
        # Carabosse: openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools . Rolls up XS56ECC004, XS56ECC005, XS56ECC006, XS56ECC008, XS56ECC009, XS56ECC010  
        self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC011"] = "/usr/groups/release/XenServer-5.6.0-rc3/hotfixes/XS56ECC011/77144/hotfix-XS56ECC011/XS56ECC011.xsupdate"






        # Britney: xapi and a few other dom0 config bits
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E001"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E001/51894/hotfix-XS60E001/XS60E001.xsupdate"

        # StatusQuo: xapi. Depends on and rolls-up XS60E001
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E002"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E002/51602/hotfix-XS60E002/XS60E002.xsupdate"

        # Goncales: dom0 kernel. Depends on XS60E001
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E003"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E003/52017/hotfix-XS60E003/XS60E003.xsupdate"

        # Milton: blktap. Depends on XS60E001
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E004"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E004/52271/hotfix-XS60E004/XS60E004.xsupdate"

        # Tristar: xapi. Depends on XS60E001. Rolls up XS60E001 and XS60E002.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E005"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E005/52933/hotfix-XS60E005/XS60E005.xsupdate"

        # Galaxy: xapi. Depends on XS60E001. Rolls up XS60E001, XS60E002 and XS60E005
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E006"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E006/53206/hotfix-XS60E006/XS60E006.xsupdate"

        # Admiral: glibc, libpng, cyrus-sasl. Depends on XS60E001.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E007"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E007/53405/hotfix-XS60E007/XS60E007.xsupdate"

        # Fiona: xapi. Depends on XS60E001. Rolls up XS60E001, XS60E002, XS60E005 and XS60E006.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E008"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E008/53848/hotfix-XS60E008/XS60E008.xsupdate"

        # Carrugi: xapi. Depends on XS60E001. Rolls up XS60E003. This hotfix was on a separate branch, therefore it is not rolled up by any later updates.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E010"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E010/53860/hotfix-XS60E010/XS60E010.xsupdate"

        # TimeOut: openvswitch. Depends on XS60E001. Rolls up nothing.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E012"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E012/53848/hotfix-XS60E012/XS60E012.xsupdate"

        # Gorgon: xapi. Depends on XS60E001. Rolls up XS60E002, XS60E005, XS60E006, XS60E008
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E013"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E013/55198/hotfix-XS60E013/XS60E013.xsupdate"

        # Berta: xen. Depends on XS60E001. Rolls up nothing.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E014"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E014/56511/hotfix-XS60E014/XS60E014.xsupdate"

        # IKEA: sm-closed, iSL cummulative. Depends on XS60E001. Rolls up nothing.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E015"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E015/56346/hotfix-XS60E015/XS60E015.xsupdate"

        # Shaw: sm, dom0kernel, elasticsyslog. Depends on XS60E001. Rolls up XS60E003.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E016"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E016/56679/hotfix-XS60E016/XS60E016.xsupdate"

        # Ampersand: sm, dom0kernel, elasticsyslog. Depends on XS60E001. Rolls up XS60E016, XS60E003.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E017"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E017/58491/hotfix-XS60E017/XS60E017.xsupdate"

        # Brynolf: openssl, vncterm, device-model, xen. Depends on XS60E001. Rolls up XS60E014.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E018"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E018/58403/hotfix-XS60E018/XS60E018.xsupdate"

        # Lemming: fe. Depends on XS60E001. Rolls up XS60E014.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E019"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E019/60836/hotfix-XS60E019/XS60E019.xsupdate"

        # Wall-E: kexec, openssl, vncterm, device-model, xen. Depends on XS60E001. Rolls up XS60E018, XS60E014.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E020"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E020/61218/hotfix-XS60E020/XS60E020.xsupdate"

        # Molti Xapi: xapi. Depends on XS60E001. Rolls up XS60E002, XS60E005, XS60E006, XS60E008, XS60E013.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E021"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E021/61548/hotfix-XS60E021/XS60E021.xsupdate"
      
        # Remedy: sm, dom0kernel, elasticsyslog. Depends on XS60E001. Rolls up XS60E017, XS60E016, XS60E003.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E022"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E022/61123/hotfix-XS60E022/XS60E022.xsupdate"
      
        # Britta: openssl, vncterm, device-model, xen. Depends on XS60E001. Rolls up XS60E014, XS60E018, XS60E020.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E023"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E023/61553/hotfix-XS60E023/XS60E023.xsupdate"

        # Beata: openssl, vncterm, device-model, xen. Depends on XS60E001. Rolls up XS60E014, XS60E018, XS60E020, XS60E023.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E024"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E024/61805/hotfix-XS60E024/XS60E024.xsupdate"
      
        # Orix: nash, mkinitrd. Depends on XS60E001. Rolls up nothing.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E025"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E025/62782/hotfix-XS60E025/XS60E025.xsupdate"

        # Gruffalo #1: openssl, vncterm, device-model, xen. Depends on XS60E001. Rolls up XS60E024, XS60E014, XS60E018, XS60E020, XS60E023.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E026"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E026/62914/hotfix-XS60E026/XS60E026.xsupdate"

        # Gruffalo #2: sm, dom0kernel, elasticsyslog. Depends on XS60E001. Rolls up XS60E022, XS60E017, XS60E016, XS60E003.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E027"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E027/63020/hotfix-XS60E027/XS60E027.xsupdate"

        # Boo: kexec-tools, openssl, vncterm, xen, xapi. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E028"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E028/68982/hotfix-XS60E028/XS60E028.xsupdate" 
      
        # Sid: kexec-tools, openssl, vncterm, device-model, xen, xen-tools. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E029"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E029/69335/hotfix-XS60E029/XS60E029.xsupdate"

        # Roosevelt: kernel-kdump, kernel-xen, md3000-rdac-modules-kdump, md3000-rdac-modules-xen, elasticsyslog, sm. Rolls up XS60E003, XS60E016, XS60E017, XS60E022, XS60E027. 
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E030"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E030/70191/hotfix-XS60E030/XS60E030.xsupdate"

        # TickTock: xen-bugtool. Rolls up nothing. 
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E031"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E031/70191/hotfix-XS60E031/XS60E031.xsupdate"
           
        # Huw: xapi. Rolls up XS60E001, XS60E002, XS60E005, XS60E006, XS60E008, XS60E013, XS60E021.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E032"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E032/70387/hotfix-XS60E032/XS60E032.xsupdate"
           
        # KingKong: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E033"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E033/72148/hotfix-XS60E033/XS60E033.xsupdate"
         
        # DonkeyKong: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E034"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E034/72548/hotfix-XS60E034/XS60E034.xsupdate"
        
        # Blunt: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033, XS60E034.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E035"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E035/75824/hotfix-XS60E035/XS60E035.xsupdate"
        
        # MrToad (PLACEHOLDER): xen-tools . Rolls up nothing.
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E036"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E036/84221/hotfix-XS60E036/XS60E036.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Boston"]["RTM"].append("XS60E036")
        
        # Carabosse: kexec-tools, openssl,  vncterm, xen-device-mode, xen-hypervisor, xen-tools. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033, XS60E034, XS60E035 
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E037"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E037/77408/hotfix-XS60E037/XS60E037.xsupdate"
       
       # Burglarbill: sm. Rolls up XS60E003, XS60E004, XS60E016, XS60E017, XS60E022, XS60E027, XS60E030
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E038"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E038/86305/hotfix-XS60E038/XS60E038.xsupdate"
        
        # AliBaba: xenhyp, qemu, openSSL. Rolls up XXS60E014,XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033, XS60E034, XS60E035, XS60E037
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E039"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E039/86675/hotfix-XS60E039/XS60E039.xsupdate"
       
        # Ronan: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools .Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033, XS60E034, XS60E035, XS60E037, XS60E039
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E040"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E040/88554/hotfix-XS60E040/XS60E040.xsupdate"
        
        # ShellShock: bash .Rolls up nothing
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E041"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E041/88766/hotfix-XS60E041/XS60E041.xsupdate"
        
        # Guy: xen-hyp .Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E042"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E042/89775/hotfix-XS60E042/XS60E042.xsupdate"
        
        # Guy: xglibc .Rolls up XS60E007
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E043"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E043/91281/hotfix-XS60E043/XS60E043.xsupdate"
        
        # Kraken (XS60E044) : Cancelled
        
        # Burgess: xen-hyp .Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040, XS60E042
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E045"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E045/92056/hotfix-XS60E045/XS60E045.xsupdate"
        
        # Kraken2: xen-device-model .Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040,XS60E042, XS60E045
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E046"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E046/100352/hotfix-XS60E046/XS60E046.xsupdate"
        
        # Floppy: xen-device-model .Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040,XS60E042, XS60E045, XS60E046
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E047"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E047/101556/hotfix-XS60E047/XS60E047.xsupdate"
       
        # Harry: xen-device-model. Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040,XS60E042, XS60E045, XS60E046, XS60E047 
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E048"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E048/101900/hotfix-XS60E048/XS60E048.xsupdate"
        
        # Sally: xen, xen-device-model. Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040,XS60E042, XS60E045, XS60E046, XS60E047, XS60E048 
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E049"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E049/102099/hotfix-XS60E049/XS60E049.xsupdate"

        # Seedy: xen, xen-device-model. Rolls up XS60E014,XS60E018, XS60E020,XS60E023, XS60E024,XS60E026, XS60E028,XS60E029, XS60E033,XS60E034, XS60E035,XS60E037, XS60E039,XS60E040,XS60E042, XS60E045, XS60E046, XS60E047, XS60E048, XS60E049
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E050"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E050/103293/hotfix-XS60E050/XS60E050.xsupdate"

        # Philby: xen-device-model. Rolls up XS60E014, XS60E018, XS60E020, XS60E023, XS60E024, XS60E026, XS60E028, XS60E029, XS60E033, XS60E034, XS60E035, XS60E037, XS60E039, XS60E040, XS60E042, XS60E045, XS60E046, XS60E047, XS60E048, XS60E049, XS60E050
        self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E051"] = "/usr/groups/release/XenServer-6.x/XS-6.0.0/hotfixes/XS60E051/103737/hotfix-XS60E051/XS60E051.xsupdate"
       
         # Sonja xen
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E004"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E004/56521/hotfix-XS602E004/XS602E004.xsupdate"

        # Allen dom0 kernel, sm, xapi. Rolls XS602E003, XS602E001.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E005"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E005/56329/hotfix-XS602E005/XS602E005.xsupdate"

        # Ikea sm-closed, iSL
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E006"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E006/57088/hotfix-XS602E006/XS602E006.xsupdate"

        # Misto dom0 kernel, sm, xapi. Rolls up XS602E005, XS602E003, XS602E001.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E007"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E007/57824/hotfix-XS602E007/XS602E007.xsupdate"

        # Stella xen, vncterm, openssl, qemu. Rolls up XS602E004.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E008"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E008/58413/hotfix-XS602E008/XS602E008.xsupdate"

        # Stanley tools ISO
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E009"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E009/59006/hotfix-XS602E009/XS602E009.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Sanibel"]["RTM"].append("XS602E009")

        # Martens xen-firmware
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E010"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E010/59507/hotfix-XS602E010/XS602E010.xsupdate"

        # Hangar dom0 kernel, sm, xapi-core. Rolls up XS602E007, XS602E005, XS602E003, XS602E001.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E011"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E011/61073/hotfix-XS602E011/XS602E011.xsupdate"

        # Watchman, dom0 kernel. Rolls up Nothing. Don't roll-up.
        # self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E012"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E012/60843/hotfix-XS602E012/XS602E012.xsupdate" 
      
        # Colonel dom0 kernel, sm, xapi-core. Rolls up XS602E011, XS602E007, XS602E005, XS602E003, XS602E001.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E013"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E013/61391/hotfix-XS602E013/XS602E013.xsupdate"
      
        # Sabina xen, vncterm, openssl, qemu. Rolls up XS602E008, XS602E004.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E014"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E014/61624/hotfix-XS602E014/XS602E014.xsupdate"

        # Niklas xen, vncterm, openssl, qemu. Rolls up XS602E014, XS602E008, XS602E004.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E016"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E016/61801/hotfix-XS602E016/XS602E016.xsupdate"
      
        # TwentyFour dom0 kernel, sm, xapi-core. Rolls up XS602E013, XS602E011, XS602E007, XS602E005, XS602E003, XS602E001
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E017"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E017/61937/hotfix-XS602E017/XS602E017.xsupdate"

        # Burtt kexec-tools, xen, vncterm, openssl, qemu. Rolls up XS602E016, XS602E014, XS602E008, XS602E004.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E018"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E018/62618/hotfix-XS602E018/XS602E018.xsupdate"
      
        # Rolson tools ISO. Rolls up XS602E009
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E019"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E019/64947/hotfix-XS602E019/XS602E019.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Sanibel"]["RTM"].append("XS602E019")
      
        # Gruffalo #1 xen, xen tools, vncterm, openssl, qemu. Rolls up XS602E018, XS602E016, XS602E014, XS602E008, XS602E004.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E020"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E020/62915/hotfix-XS602E020/XS602E020.xsupdate"
      
        # Gruffalo #2 dom0 kernel, sm, xapi-core. Rolls up XS602E017, XS602E013, XS602E011, XS602E007, XS602E005, XS602E003, XS602E001
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E021"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E021/63021/hotfix-XS602E021/XS602E021.xsupdate"

        # Boo: openssl,  kexec-tools, vncterm, xen,  xapi. Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E022"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E022/68998/hotfix-XS602E022/XS602E022.xsupdate"
      
        # Sid: kexec-tools, openssl, vncterm, device-model, xen, xen-tools. Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020, XS602E022.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E023"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E023/69336/hotfix-XS602E023/XS602E023.xsupdate"
      
        # Brink: openvswitch. Rolls up nothing.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E024"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E024/72145/hotfix-XS602E024/XS602E024.xsupdate"

        # KingKong: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020, XS602E022, XS602E023.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E025"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E025/72145/hotfix-XS602E025/XS602E025.xsupdate"
      
        # DonkeyKong: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020, XS602E022, XS602E023, XS602E025.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E026"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E026/72539/hotfix-XS602E026/XS602E026.xsupdate"
      
        # Obelix:  blktap, kernel-kdump, kernel-xen, md3000-rdac-kduump, md3000-rdac-xen, mkinitrd, nash, sm, xapi-core, xapi-xenops. Rolls up XS602E001, XS602E003, XS602E005, XS602E007, XS602E011, XS602E013, XS602E017, XS602E021.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E027"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E027/73026/hotfix-XS602E027/XS602E027.xsupdate"
      
        # Dogmatix: blktap, kernel-kdump, kernel-xen, md3000-rdac, mkinitrd, nash, sm, xapi-core, xapi-xenops. Rolls up XS602E001, XS602E003, XS602E005, XS602E007, XS602E011, XS602E013, XS602E017, XS602E021, XS602E027.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E028"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E028/74144/hotfix-XS602E028/XS602E028.xsupdate"
      
        # Blunt: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools. Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020, XS602E022, XS602E023, XS602E025, XS602E026 .
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E029"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E029/75852/hotfix-XS602E029/XS602E029.xsupdate"
        
        # Stratus: xen-api, sm. Rolls up XS602E001,XS602E002,XS602E003,XS602E005,XS602E007,XS602E011,XS602E013,XS602E017,XS602E021,XS602E027,XS602E028.
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E030"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E030/76582/hotfix-XS602E030/XS602E030.xsupdate"
        
        # MrToad: xen-tools . Rolls up XS602E002, XS602E009, XS602E019
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E031"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E031/84256/hotfix-XS602E031/XS602E031.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Sanibel"]["RTM"].append("XS602E031")
        
        # Carabosse: kexec-tools, openssl, vncterm, xen-device-model, xen-hypervisor, xen-tools . Rolls up XS602E004, XS602E008, XS602E014, XS602E016, XS602E018, XS602E020, XS602E022, XS602E023, XS602E025, XS602E026, XS602E029 
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E032"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E032/77409/hotfix-XS602E032/XS602E032.xsupdate"
        
        # Snowball: xapi, xen, kernel, sm. Rolls up XS602E001, XS602E003, XS602E004, XS602E005, XS602E007, XS602E008, XS602E011, XS602E013, XS602E014, XS602E016.XS602E017, XS602E018, XS602E020, XS602E021, XS602E022, XS602E023, XS602E025, XS602E026, XS602E027, XS602E028, XS602E029, XS602E030, XS602E032
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E033"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E033/84969/hotfix-XS602E033/XS602E033.xsupdate"
        
        #Burglarbill : sm. Rolls up XS602E001, XS602E003, XS602E004, XS602E005, XS602E007, XS602E008, XS602E011, XS602E013, XS602E014, XS602E016, XS602E017, XS602E018, XS602E020, XS602E021, XS602E022, XS602E023, XS602E025, XS602E026, XS602E027, XS602E028, XS602E029, XS602E0030, XS602E032, XS602E033
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E034"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E034/86306/hotfix-XS602E034/XS602E034.xsupdate"
        
        #AliBaba : qemu, xen-hyp, openSSL. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011, XS602E013, XS602E014, XS602E016, XS602E017, XS602E018, XS602E020, XS602E021, XS602E022, XS602E023, XS602E025, XS602E026, XS602E027, XS602E028, XS602E029, XS602E030, XS602E032, XS602E033, XS602E034
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E035"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E035/86670/hotfix-XS602E035/XS602E035.xsupdate"
        
        #Ronan : blktap, device-mapper-multipath, kernel, kexec-tools, kpartx, md3000-rdac, mkinitrd, nash, openssl, sm, v6d, vhd-tool, vncterm, xapi-core, xapi-xenops, xen-device-model, xen-firmware, xen-hypervisor, xen-tools. 
        #Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 ,XS602E032,XS602E033, XS602E034,XS602E035
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E036"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E036/88549/hotfix-XS602E036/XS602E036.xsupdate"
        
        #ShellShock : bash. Rolls up nothing
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E037"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E037/88769/hotfix-XS602E037/XS602E037.xsupdate"
        
        #Guy : xen-hyp. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E038"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E038/89776/hotfix-XS602E038/XS602E038.xsupdate"
        
        #Ghost : glibc. Rolls up nothing
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E039"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E039/91286/hotfix-XS602E039/XS602E039.xsupdate"
        
        #Kraken(XS602E040): Cancelled
        
        #Burgess : xen-hyp. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036, XS602E038
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E041"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E041/92001/hotfix-XS602E041/XS602E041.xsupdate"
        
        #Kraken2 : xen-device-model. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036, XS602E038, XS602E041
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E042"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E042/100341/hotfix-XS602E042/XS602E042.xsupdate"
        
        #Floppy : xen-device-model. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036, XS602E038, XS602E041, XS602E042
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E043"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E043/101570/hotfix-XS602E043/XS602E043.xsupdate"
      
        #Sally : xen, xen-device-model. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036, XS602E038, XS602E041, XS602E042,XS602E043
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E044"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E044/102102/hotfix-XS602E044/XS602E044.xsupdate"

        #Seedy : xen, xen-device-model. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030 XS602E032,XS602E033 XS602E034,XS602E035 XS602E036, XS602E038, XS602E041, XS602E042,XS602E043,XS602E044
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E045"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E045/103324/hotfix-XS602E045/XS602E045.xsupdate"

        #Philby : xen-device-model. Rolls up XS602E001,XS602E003, XS602E004,XS602E005, XS602E007,XS602E008, XS602E011,XS602E013, XS602E014,XS602E016, XS602E017,XS602E018, XS602E020,XS602E021, XS602E022,XS602E023, XS602E025,XS602E026, XS602E027,XS602E028, XS602E029,XS602E030, XS602E032,XS602E033, XS602E034,XS602E035, XS602E036,XS602E038, XS602E041,XS602E042, XS602E043,XS602E044, XS602E045
        self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E046"] = "/usr/groups/release/XenServer-6.x/XS-6.0.2/hotfixes/XS602E046/103707/hotfix-XS602E046/XS602E046.xsupdate"
      
      
        # Adam: sm. Rolls up Nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E001"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E001/61121/hotfix-XS61E001/XS61E001.xsupdate"
      
        # Crumble: XenCenter
        # self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E002"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E002/61298/xe-phase-1/client-install/XenCenter.msi"
      
        # Mulberry: xapi. Rolls up Nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E003"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E003/61333/hotfix-XS61E003/XS61E003.xsupdate"
      
        # Tor: xen. Rolls up Nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E004"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E004/61572/hotfix-XS61E004/XS61E004.xsupdate"
      
        # defunct
        # self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E005"] = ""

        # Teodor: xen. Rolls up XS61E004
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E006"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E006/61795/hotfix-XS61E006/XS61E006.xsupdate"
      
        # Borehamwood: sm. Rolls up Adam. This was not built from tampa-lcm branch.
        # self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E007"] = ""
      
        # GridCentric (private): xapi, xenopsd. Rolls up XS61E003
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E008"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E008/61931/hotfix-XS61E008/XS61E008.xsupdate"
      
        # BronzeAge: xapi, xenopsd. Rolls up XS61E008, XS61E003
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E009"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E009/62415/hotfix-XS61E009/XS61E009.xsupdate"
      
        # Gucci: Tools ISO.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E010"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E010/62464/hotfix-XS61E010/XS61E010.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Tampa"]["RTM"].append("XS61E010")
      
        # Excalibur: xapi, xenopsd. Rolls up XS61E009, XS61E008, XS61E003
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E012"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E012/62681/hotfix-XS61E012/XS61E012.xsupdate"
      
        # Gruffalo #1: xen, xen-tools. Rolls up XS61E006, XS61E004
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E013"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E013/62916/hotfix-XS61E013/XS61E013.xsupdate"

        # Gruffalo #2: dom0kernel. Rolls up Nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E014"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E014/63035/hotfix-XS61E014/XS61E014.xsupdate"
      
        # Hammonds: blktap, device-mapper-multipath, kpartx, sm, storagelink. Rolls up XS61E001, XS61E007.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E015"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E015/68783/hotfix-XS61E015/XS61E015.xsupdate"
      
        # Blancmange: XenCenter (build 63037)
        # self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E016"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E016/63037/xe-phase-1/client_install/XenCenter.msi"
      
        # Snippet: xapi, rrdd, xenopds. Rolls up XS61E012, XS61E009, XS61E008, XS61E003
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E017"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E017/65037/hotfix-XS61E017/XS61E017.xsupdate"
      
        # Kittinger: dom0 kernel. Rolls up XS61E014.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E018"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E018/69154/hotfix-XS61E018/XS61E018.xsupdate"

        # Boo:  xen, xen-tools. Rolls up XS61E004, XS61E006, XS61E013.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E019"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E019/68994/hotfix-XS61E019/XS61E019.xsupdate"
            
        # Vettel: xen-device-model. Rolls up nothing.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E020"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E020/69154/hotfix-XS61E020/XS61E020.xsupdate"

        # Tobey: xapi-core, xapi-networkd, xapi-noarch-backend-udev, xapi-rrdd, xapi-xenopsd, /xen-firmware. Rolls up XS61E003, XS61E008, XS61E009, XS61E012, XS61E017.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E021"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E021/69285/hotfix-XS61E021/XS61E021.xsupdate"
      
        # Sid: xen, xen-tools. Rolls up XS61E004, XS61E006, XS61E013, XS61E019.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E022"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E022/69355/hotfix-XS61E022/XS61E022.xsupdate"

        # Sierra: xen-hypervisor, xen-tools. Rolls up XS61E004, XS61E006, XS61E013, XS61E019, XS61E022.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E023"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E023/69584/hotfix-XS61E023/XS61E023.xsupdate"
      
        # KingKong: xen-hypervisor, xen-tools. Rolls up XS61E004, XS61E006, XS61E013, XS61E019, XS61E022, XS61E023.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E024"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E024/72199/hotfix-XS61E024/XS61E024.xsupdate"
      
        # Myers: xapi-core, xapi-networkd, xapi-noarch-backend-udev, xapi-rrdd, xapi-xenopsd, xen-firmware. Rolls up XS61E003, XS61E008, XS61E009, XS61E012, XS61E017, XS61E021.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E025"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E025/72410/hotfix-XS61E025/XS61E025.xsupdate"
      
        # DonkeyKong: xen-hypervisor, xen-tools. Rolls up XS61E004, XS61E006, XS61E013, XS61E019, XS61E022, XS61E023, XS61E024.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E026"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E026/72532/hotfix-XS61E026/XS61E026.xsupdate" 
      
        # Oliver: xapi-core, xapi-networkd, xapi-noarch-backend, xapi-rrdd, xapi-xenopsd, xen-firmware, xen-hypervisor, xen-tools. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E027"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E027/74245/hotfix-XS61E027/XS61E027.xsupdate"
             
        # Scoff: xapi-networkd. Rolls up nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E028"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E028/73471/hotfix-XS61E028/XS61E028.xsupdate" 
      
        # Bosch: tools ISO. Rolls up XS61E010. Depends on XS61E009.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E029"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E029/73563/hotfix-XS61E029/XS61E029.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Tampa"]["RTM"].append("XS61E029")

        # Excelsior: kernel-kdump, kernel-xen, md3000-rdac, openvswitch. Rolls up XS61E018, XS61E014.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E030"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E030/73563/hotfix-XS61E030/XS61E030.xsupdate"
      
        # HangUp - XS61E031 - Limited availability syslinux update
      
        # TipEx: kexec-tools, xen-bugtool, xapi-core, xapi-networkd, xapi-noarch-backend, xapi-rrdd, xapi-xenopsd, xen-firmware, xen-hypervisor, xen-tools. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E032"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E032/75763/hotfix-XS61E032/XS61E032.xsupdate"
      
        # Blunt: kexec-tools, xapi-core, xapi-networkd, xapi-noarch-backend, xapi-rrdd, xapi-xenopsd, xen-firmware, xen-hypervisor, xen-tools, xen-bugtool. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E033"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E033/75948/hotfix-XS61E033/XS61E033.xsupdate"
        
        # Cartwheel: blktap, device-mapper-multipath, kpartxsm, sm-closed, storagelink. Rolls up XS61E001, XS61E007, XS61E015
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E034"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E034/76278/hotfix-XS61E034/XS61E034.xsupdate"
        
        # Rodney: nash, mkinitrd, kernel-xen, kernel-kdump, md3000-rdac, openvswitch. Rolls up XS61E014, XS61E018, XS61E028, XS61E030
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E035"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E035/82435/hotfix-XS61E035/XS61E035.xsupdate"
        
        # Carabosse: kexec-tools, xen-bugtool, xapi-core, xapi-networkd, xapi-noarch, xapi-rrdd, xapi-xenopsd, xen-firmware, xen-hypervisor, xen-tools . Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033 
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E036"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E036/77411/hotfix-XS61E036/XS61E036.xsupdate"
        
        # Dodger: xapi, xen. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E037"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E037/84860/hotfix-XS61E037/XS61E037.xsupdate"
        
        # MrToad: xen-tools. Rolls up XS61E010, XS61E029
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E038"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E038/84220/hotfix-XS61E038/XS61E038.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Tampa"]["RTM"].append("XS61E038")
        
        # Dave: kernel, ovs. Rolls up XS61E014, XS61E018, XS61E028, XS61E030, XS61E035
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E039"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E039/84261/hotfix-XS61E039/XS61E039.xsupdate"
        
        # Burglarbill: sm. Rolls up XS61E001, XS61E007, XS61E015, XS61E034
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E040"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E040/86307/hotfix-XS61E040/XS61E040.xsupdate"
        
        # AliBaba: xen-hyp, qemu, openSSL. Rolls up XS61E003,XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E041"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E041/86672/hotfix-XS61E041/XS61E041.xsupdate"
      
        # Scalextric: xcp-python-libs, kernel, ovs. Rolls up XS61E014, XS61E018, XS61E028, XS61E030, XS61E035, XS61E039
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E042"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E042/87613/hotfix-XS61E042/XS61E042.xsupdate"
        
        # Ronan: kexec-tools, openssl, vhd-tool, xapi-core, xapi-networkd, xapi-noarch-backend-udev, xapi-rrdd, xapi-xenopsd, xen-device-model, xen-firmware, xen-hypervisor, xen-tools. 
        #Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E043"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E043/88551/hotfix-XS61E043/XS61E043.xsupdate"
        
        # ShellShock: bash. Rolls up nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E044"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E044/88768/hotfix-XS61E044/XS61E044.xsupdate"
        
        # Guy: xen-hyp. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019,XS61E020, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E045"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E045/89781/hotfix-XS61E045/XS61E045.xsupdate"
        
        # Lull: xen-hyp, xapi, xen-device-model, xenbugtool. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E046"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E046/89882/hotfix-XS61E046/XS61E046.xsupdate"
        
        # Repetir: xen-tools. Rolls up XS61E010, XS61E029, XS61E038
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E047"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E047/101342/hotfix-XS61E047/XS61E047.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Tampa"]["RTM"].append("XS61E047")
        
        # Ghost: glibc. Rolls up nothing
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E048"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E048/91291/hotfix-XS61E048/XS61E048.xsupdate"
        
        #Kraken(XS61E049) : Cancelled
        
        # Burgess: xen-hyp. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E050"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E050/92012/hotfix-XS61E050/XS61E050.xsupdate"
        
        # Kraken2: xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E051"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E051/100342/hotfix-XS61E051/XS61E051.xsupdate"
        
        # Floppy: xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E052"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E052/101561/hotfix-XS61E052/XS61E052.xsupdate"
        
        # Harry: xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051,XS61E051,XS61E052
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E053"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E053/101913/hotfix-XS61E053/XS61E053.xsupdate"
      
        # Sally: xen, xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051,XS61E051,XS61E052,XS61E053
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E054"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E054/102106/hotfix-XS61E054/XS61E054.xsupdate"
      
        # AbbeyWrap: Dom0 kernel. Rolls up XS61E014, XS61E018, XS61E028, XS61E030, XS61E035, XS61E039, XS61E042.
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E055"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E055/103772/hotfix-XS61E055/XS61E055.xsupdate"
      
        # Tardy: xen, xapi, xen-bugtool. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051, XS61E052, XS61E053, XS61E054
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E056"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E056/102720/hotfix-XS61E056/XS61E056.xsupdate"
        
        # Seedy: xen, xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020,XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051,XS61E051,XS61E052,XS61E053,XS61E054,XS61E056
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E057"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E057/103301/hotfix-XS61E057/XS61E057.xsupdate"

        # Philby: xen-device-model. Rolls up XS61E003, XS61E004, XS61E006, XS61E008, XS61E009, XS61E012, XS61E013, XS61E017, XS61E019, XS61E020, XS61E021, XS61E022, XS61E023, XS61E024, XS61E025, XS61E026, XS61E027, XS61E032, XS61E033, XS61E036, XS61E037, XS61E041, XS61E043, XS61E045, XS61E046, XS61E050, XS61E051, XS61E052, XS61E053, XS61E054, XS61E056, XS61E057
        self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E058"] = "/usr/groups/release/XenServer-6.x/XS-6.1/hotfixes/XS61E058/103772/hotfix-XS61E058/XS61E058.xsupdate"

        # Viola: Xen 
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC001"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC001/61625/hotfix-XS602ECC001/XS602ECC001.xsupdate"
      
        # Sven: Xen. Rolls up XS602ECC001
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC002"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC002/61796/hotfix-XS602ECC002/XS602ECC002.xsupdate"

        # Gruffalo #1 : Xen, Xen-tools Rolls up XS602ECC002, XS602ECC001
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC003"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC003/62917/hotfix-XS602ECC003/XS602ECC003.xsupdate"

        # Gruffalo #2 : Kernel. Rolls up Nothing
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC004"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC004/63023/hotfix-XS602ECC004/XS602ECC004.xsupdate"

        # Sid: xen, xen-tools. Rolls up XS602ECC002, XS602ECC003, XS602ECC001.
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC005"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC005/69346/hotfix-XS602ECC005/XS602ECC005.xsupdate"

        # DonkeyKong: xen-hypervisor, xen-tools. Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005.
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC006"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC006/72523/hotfix-XS602ECC006/XS602ECC006.xsupdate"

        # Blunt: xen-hypervisor, xen-tools. Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006. 
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC007"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC007/75826/hotfix-XS602ECC007/XS602ECC007.xsupdate"
        
        # Carabosse: xen-hypervisor, xen-tools . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007.
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC008"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC008/77183/hotfix-XS602ECC008/XS602ECC008.xsupdate"
        
        # MrToad - xen-tools . Rolls up nothing. 
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC009"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC009/84353/hotfix-XS602ECC009/XS602ECC009.xsupdate"
        
        # Burglarbill - sm, blktap . Rolls up nothing. 
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC010"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC010/85745/hotfix-XS602ECC010/XS602ECC010.xsupdate"
        
        # AliBaba - qemu, xen-hyp, openSSL . Rolls up XS602ECC001,XS602ECC002, XS602ECC003,XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008 
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC011"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC011/86671/hotfix-XS602ECC011/XS602ECC011.xsupdate"
        
        # Ronan - openssl, xen-device-model, xen-hypervisor, xen-tools . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC012"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC012/88550/hotfix-XS602ECC012/XS602ECC012.xsupdate"
        
        # ShellShock - bash . Rolls up nothing
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC013"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC013/88777/hotfix-XS602ECC013/XS602ECC013.xsupdate"
        
        # Guy - xen-hyp . Rolls up XS602ECC001,XS602ECC002, XS602ECC003,XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008,XS602ECC011, XS602ECC012
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC014"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC014/89777/hotfix-XS602ECC014/XS602ECC014.xsupdate"
        
        # Ghost - glibc . Rolls up nothing
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC015"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC015/91288/hotfix-XS602ECC015/XS602ECC015.xsupdate"
        
        #Kraken(XS602ECC016): Cancelled
        
        # Burgess - xen-hyp . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011, XS602ECC012, XS602ECC014
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC017"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC017/92003/hotfix-XS602ECC017/XS602ECC017.xsupdate"
        
        # Kraken2 - xen-device-model . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011, XS602ECC012, XS602ECC014, XS602ECC017
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC018"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC018/100339/hotfix-XS602ECC018/XS602ECC018.xsupdate"
        
        # Floppy - xen-device-model . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011, XS602ECC012, XS602ECC014, XS602ECC017, XS602ECC018
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC019"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC019/101571/hotfix-XS602ECC019/XS602ECC019.xsupdate"
      
        # Sally - xen, xen-device-model . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011, XS602ECC012, XS602ECC014, XS602ECC017, XS602ECC018,XS602ECC019
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC020"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC020/102104/hotfix-XS602ECC020/XS602ECC020.xsupdate"

        # Seedy - xen, xen-device-model . Rolls up XS602ECC001, XS602ECC002, XS602ECC003, XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008, XS602ECC011, XS602ECC012, XS602ECC014, XS602ECC017, XS602ECC018, XS602ECC019, XS602ECC020
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC021"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC021/103325/hotfix-XS602ECC021/XS602ECC021.xsupdate"

        # Philby - xen-device-model . Rolls up XS602ECC001,XS602ECC002, XS602ECC003,XS602ECC005, XS602ECC006,XS602ECC007, XS602ECC008,XS602ECC011, XS602ECC012,XS602ECC014, XS602ECC017,XS602ECC018, XS602ECC019,XS602ECC020, XS602ECC021
        self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC022"] = "/usr/groups/release/XenServer-6.x/sweeney/hotfixes/XS602ECC022/103729/hotfix-XS602ECC022/XS602ECC022.xsupdate"

        # vGPU Tech Preview hotfix, Rolls up XS62E001 and XS62E002
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62ETP001"] = "/usr/groups/release/XenServer-6.x/XS-6.2/tech-preview/hotfix-XS62ETP001/XS62ETP001.xsupdate"
      
        # PopUp: xapi-core. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E001"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E001/72265/hotfix-XS62E001/XS62E001.xsupdate"
      
        # DonkeyKong: xen-hypervisor, xen-tools. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E002"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E002/72536/hotfix-XS62E002/XS62E002.xsupdate"
      
        # Multipack - XS62E003: a new version of XenCenter
      
        # Loftier: kernel-kdump, kernel-xen, md3000, openvswitch. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E004"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E004/75684/hotfix-XS62E004/XS62E004.xsupdate"
      
        # Samsonite: xapi-core, xapi-networkd, xapi-xenopsd. Rolls up XS62E001.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E005"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E005/75758/hotfix-XS62E005/XS62E005.xsupdate"
        
        # Marill: xen-device-model. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E007"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E007/76091/hotfix-XS62E007/XS62E007.xsupdate"
      
      
        # MuddyWaters: tools iso. Limited availability hotfix. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E008"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E008/76367/hotfix-XS62E008/XS62E008.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["RTM"].append("XS62E008")
      
        # Blunt: xen-hypervisor, xen-tools. Rolls up XS62E002.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E009"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E009/76024/hotfix-XS62E009/XS62E009.xsupdate"

        # Artless: gpu pass-through. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E010"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E010/76482/hotfix-XS62E010/XS62E010.xsupdate"

        # Karrimor: storage. Rolls up nothing.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E011"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E011/77067/hotfix-XS62E011/XS62E011.xsupdate"
        
        # Delboy: kernel. Rolls up XS62E004.
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E012"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E012/76386/hotfix-XS62E012/XS62E012.xsupdate"
        
        # Carabosse: xen-hypervisor, xen-tools . Rolls up XS62E002, XS62E009 .
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E014"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E014/77605/hotfix-XS62E014/XS62E014.xsupdate"
        
        # MrToad: xen-tools . Rools up XS62E008
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E015"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E015/83715/hotfix-XS62E015/XS62E015.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["RTM"].append("XS62E015")
        
        # Burglarbill: sm, blktap . Rools up XS62E011
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E016"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E016/85780/hotfix-XS62E016/XS62E016.xsupdate"
        
        # AliBaba: xen-hyp, openSSL, qemu . Rools up XS62E002,XS62E007, XS62E009, XS62E014
        self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E017"] = "/usr/groups/release/XenServer-6.x/XS-6.2/hotfixes/XS62E017/86676/hotfix-XS62E017/XS62E017.xsupdate"


        # 6.2 SP1 (St. Nicholas) - start of SP1 branch, rolls up all previous hotfixes
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/RTM-77323/hotfix-XS62ESP1/XS62ESP1.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["SP1"].append("XS62ESP1")
        
        # Carabosse - xen-hypervisor, xen-tools . Rolls up XS62E014 
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1002"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1002/77446/hotfix-XS62ESP1002/XS62ESP1002.xsupdate"
        
        # MrToad - xen-tools . Rolls up XS62E015 
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1003"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1003/83753/hotfix-XS62ESP1003/XS62ESP1003.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["SP1"].append("XS62ESP1003")

        # Fox -Xapi, SM, Blktap, xen. Rolls up XS62ESP1002, XS62E014
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1004"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1004/84037/hotfix-XS62ESP1004/XS62ESP1004.xsupdate"
        
        # Albert -Xapi, kernel, openvswitch. Rolls up Nothing
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1005"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1005/83968/hotfix-XS62ESP1005/XS62ESP1005.xsupdate"

        # Tarentum - Xapi. Rolls up XS62ESP1002, XS62ESP1004, XS62E014
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1006"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1006/85395/hotfix-XS62ESP1006/XS62ESP1006.xsupdate"
        
        # Burglarbill - sm, blktap. Rolls up XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62E014
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1007"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1007/86311/hotfix-XS62ESP1007/XS62ESP1007.xsupdate"
        
        # AliBaba - Kernel. Rolls up XS62ESP1002,XS62ESP1004, XS62ESP1006,XS62ESP1007, XS62E014
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1008"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1008/86714/hotfix-XS62ESP1008/XS62ESP1008.xsupdate"
        
        # Adele - Kernel. Rolls up XS62ESP1005
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1009"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1009/87218/hotfix-XS62ESP1009/XS62ESP1009.xsupdate"
        
        # Whetstone - xapi, vgpu, guest-templates, xen-hyp. Rolls up XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62E014, XS62E017
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1011"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1011/88409/hotfix-XS62ESP1011/XS62ESP1011.xsupdate"
        
        # Esperado - xs-tools. Rolls up XS62E015, XS62ESP1003
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1012"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1012/90176/hotfix-XS62ESP1012/XS62ESP1012.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["SP1"].append("XS62ESP1012")
        
        # Ronan - blktap, guest-templates, openssl, perf-tools, sm, vgpu, vhd-tool, xapi-core, xapi-networkd, xapi-xe, xapi-xenopsd, xen-device-model, xen-hypervisor, xen-tools
        # Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1013"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1013/88548/hotfix-XS62ESP1013/XS62ESP1013.xsupdate"
        
        # ShellShock - bash. Rolls up nothing
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1014"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1014/88765/hotfix-XS62ESP1014/XS62ESP1014.xsupdate"
        
        # Guy - bash. Rolls up XS62E014,XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1015"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1015/89778/hotfix-XS62ESP1015/XS62ESP1015.xsupdate"
        
        # Nautilus - sm, xen-hyp, xen-tools, xapi, kexec, iSL. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1016"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1016/90390/hotfix-XS62ESP1016/XS62ESP1016.xsupdate"
        
        # Ghost - glibc. Rolls up nothing
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1017"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1017/91293/hotfix-XS62ESP1017/XS62ESP1017.xsupdate"
        
        #Kraken(XS62ESP1018): Cancelled
        
        # Burgess - xen-hyp. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1019"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1019/92015/hotfix-XS62ESP1019/XS62ESP1019.xsupdate"
        
        # Renovado - xs-tools. Rolls up XS62E015, XS62ESP1003, XS62ESP1012
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1020"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1020/100961/hotfix-XS62ESP1020/XS62ESP1020.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["SP1"].append("XS62ESP1020")
        
        # Kraken2 - xen-device-model. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1021"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1021/100343/hotfix-XS62ESP1021/XS62ESP1021.xsupdate"
        
        #Deadlock - xen-hyp. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019
        #Limited availability
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1022"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1022/100367/hotfix-XS62ESP1022/XS62ESP1022.xsupdate"
        
        # Lola - kernel. Rolls up XS62ESP1005, XS62ESP1009
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1024"] = "/usr/groups/build/clearwater-sp1-lcm/101109/hotfix-XS62ESP1024/XS62ESP1024.xsupdate"
        
        # Floppy- xen-device-model. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1025"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1025/101557/hotfix-XS62ESP1025/XS62ESP1025.xsupdate"
        
        # Caboodle- xapi, xen, sm, isL, rrdd, nfs, perf-tools, kexec. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022, XS62ESP1025
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1026"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1026/101918/hotfix-XS62ESP1026/XS62ESP1026.xsupdate"
        
        # Sally- xapi, xen-device-model. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022, XS62ESP1025,XS62ESP1026
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1027"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1027/102105/hotfix-XS62ESP1027/XS62ESP1027.xsupdate"
        
        # Take2- xs-tools. Rolls up XS62E015, XS62ESP1003, XS62ESP1012, XS62ESP1020
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1028"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1028/102212/hotfix-XS62ESP1028/XS62ESP1028.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Clearwater"]["SP1"].append("XS62ESP1028")

        #Private hotfix
        # DiskMatch- xapi, new - VM metadata export rewrite tool. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022, XS62ESP1025, XS62ESP1026, XS62ESP1027
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1029"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1029/103198/hotfix-XS62ESP1029/XS62ESP1029.xsupdate"
        
        # Seedy- xapi, xen-device-model. Rolls up XS62E014,XS62E017,XS62ESP1002,XS62ESP1004,XS62ESP1006,XS62ESP1007,XS62ESP1008,XS62ESP1011,XS62ESP1013,XS62ESP1015,XS62ESP1016,XS62ESP1019,XS62ESP1021,XS62ESP1022,XS62ESP1025,XS62ESP1026,XS62ESP1027
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1030"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1030/103335/hotfix-XS62ESP1030/XS62ESP1030.xsupdate"
        
        # Butterfree- SM, vGPU, Xen, Xapi. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022, XS62ESP1025, XS62ESP1026, XS62ESP1027, XS62ESP1029, XS62ESP1030
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1031"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1031/103504/hotfix-XS62ESP1031/XS62ESP1031.xsupdate"

        # Philby- xen-device-model. Rolls up XS62E014, XS62E017, XS62ESP1002, XS62ESP1004, XS62ESP1006, XS62ESP1007, XS62ESP1008, XS62ESP1011, XS62ESP1013, XS62ESP1015, XS62ESP1016, XS62ESP1019, XS62ESP1021, XS62ESP1022, XS62ESP1025, XS62ESP1026, XS62ESP1027, XS62ESP1029, XS62ESP1030, XS62ESP1031
        self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1032"] = "/usr/groups/release/XenServer-6.x/XS-6.2-SP1/hotfixes/XS62ESP1032/103827/hotfix-XS62ESP1032/XS62ESP1032.xsupdate"

        #Creedence hotfixes
        # Gloss: XenCenter, Rolls up nothing
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E001"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E001/91026/hotfix-XS65E001/XS65E001.xsupdate"
      
        # Houston: xs-tools. Rolls up nothing.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E002"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E002/91034/hotfix-XS65E002/XS65E002.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Creedence"]["RTM"].append("XS65E002")
        
        # Ghost: glibc. Rolls up nothing.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E003"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E003/91307/hotfix-XS65E003/XS65E003.xsupdate"
        
        # De-trop: lvm. Rolls up nothing.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E005"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E005/91806/hotfix-XS65E005/XS65E005.xsupdate"
        
        # Burgess: xen-hyp, xen-dom0-libs, xen-dom0-tools, xen-libs, xen-tools. Rolls up nothing.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E006"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E006/92059/hotfix-XS65E006/XS65E006.xsupdate"
        
        # Kraken2: xen-device-model. Rolls up XS65E006.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E007"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E007/100346/hotfix-XS65E007/XS65E007.xsupdate"
        
        # Crashnet: kernel. Rolls up Nothing.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E008"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E008/100346/hotfix-XS65E008/XS65E008.xsupdate"
        
        # Floppy: xen-device-model. Rolls up XS65E006, XS65E007.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E009"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E009/101559/hotfix-XS65E009/XS65E009.xsupdate"

        # Sally: xen-device-model. Rolls up XS65E006, XS65E007, XS65E009.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E010"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E010/102131/hotfix-XS65E010/XS65E010.xsupdate"

        # Dither: Toolstack fix for incorrect link state in VM 
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E011"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E011/101890/hotfix-XS65E011/XS65E011.xsupdate"

        # Seedy: xen-device-model. Rolls up XS65E006, XS65E007, XS65E009,XS65E010.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E013"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E013/103303/hotfix-XS65E013/XS65E013.xsupdate"

        # Philby: xen-device-model. Rolls up XS65E006, XS65E007, XS65E009, XS65E010, XS65E013.
        self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E014"] = "/usr/groups/release/XenServer-6.x/XS-6.5/hotfixes/XS65E014/103699/hotfix-XS65E014/XS65E014.xsupdate"

        # 6.5 SP1 (Cream) - start of SP1 branch, rolls up all previous hotfixes (till XS65E008)
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/RTM-101064/hotfix-XS65ESP1/XS65ESP1.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Creedence"]["SP1"].append("XS65ESP1")
        
        # XS 6.5 SP1 Xencenter- XS65ESP1001
        
        # Floppy: xen-device-model. Rolls up XS65E006, XS65E007.
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1002"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1002/101510/hotfix-XS65ESP1002/XS65ESP1002.xsupdate"

        # Take1: xen-tools fixes.
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1003"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1003/101805/hotfix-XS65ESP1003/XS65ESP1003.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Creedence"]["SP1"].append("XS65ESP1003")
        
        # Sally: xen, xen-device-model. Rolls up XS65E009, XS65E010, XS65ESP1002 .
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1004"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1004/102101/hotfix-XS65ESP1004/XS65ESP1004.xsupdate"
        
        # Bandicoot: fixes for Dom0 kernel. Rolls up nothing
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1005"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1005/102600/hotfix-XS65ESP1005/XS65ESP1005.xsupdate"

        # XS65ESP1006 - Internal Hotfix

        # Seedy: xen, xen-device-model. Rolls up XS65E009, XS65E010, XS65E013, XS65ESP1002,XS65ESP1004.
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1008"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1008/103364/hotfix-XS65ESP1008/XS65ESP1008.xsupdate"

        # Philby: xen-device-model. Rolls up XS65E009, XS65E010, XS65E013, XS65E014, XS65ESP1002, XS65ESP1004, XS65ESP1008.
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1009"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1009/103748/hotfix-XS65ESP1009/XS65ESP1009.xsupdate"

        # Dec: xen-tools fixes and windows10 support. rolls up  XS65ESP1003
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1010"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1010/104245/hotfix-XS65ESP1010/XS65ESP1010.xsupdate"
        self.config["TOOLS_HOTFIXES"]["Creedence"]["SP1"].append("XS65ESP1010")
        
        # Pixie: xen. Rolls up XS65E009,XS65E010,XS65E013,XS65E014,XS65ESP1002,XS65ESP1004,XS65ESP1008, XS65ESP1009.
        self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1011"] = "/usr/groups/release/XenServer-6.x/XS-6.5-SP1/hotfixes/XS65ESP1011/104305/hotfix-XS65ESP1011/XS65ESP1011.xsupdate"
        return

    def setSecondaryVariables(self):
        
        def getRevisionfromInputdir(inputdir):
            try:
                inputdirSplit = inputdir.strip("/").split("/")
                buildVersion = inputdirSplit[-1].split("-")[-1]
                productRevision = inputdirSplit[-2].strip("XS-")
                if len(productRevision) > 6:
                    productRevision = productRevision[:6]
                return "%s-%s" % (productRevision, buildVersion)
            except:
                return ""
        
        if not self.config.has_key("VERSION") and self.config.has_key("PRODUCT_TYPE"):
                self.config["VERSION"] = self.config["PRODUCT_TYPE"]

        if self.config.has_key("INPUTDIR"):
            self.config["REVISION"] = getRevisionfromInputdir(self.config["INPUTDIR"])
        elif self.config.has_key("TO_PRODUCT_INPUTDIR"):
            self.config["REVISION"] = getRevisionfromInputdir(self.config["TO_PRODUCT_INPUTDIR"])
        if self.config.has_key("OLD_PRODUCT_INPUTDIR"):
            self.config["FROM_REVISION"] = getRevisionfromInputdir(self.config["OLD_PRODUCT_INPUTDIR"])
        elif self.config.has_key("FROM_PRODUCT_INPUTDIR"):
            self.config["FROM_REVISION"] = getRevisionfromInputdir(self.config["FROM_PRODUCT_INPUTDIR"])

    def getHotfix(self, hotfix, release):
        if release is None:
            # Find the hotfix from any release
            releases = self.config["HOTFIXES"].keys()
            branches = {}
            for r in releases:
                branches.update(dict([("%s_%s" % (r, branch), hfs) for branch, hfs in self.config["HOTFIXES"][r].items()]))
        else:
            if not self.config["HOTFIXES"].has_key(release):
                raise xenrt.XRTError("Could not find hotfixes for %s" % (release))
        
            branches = self.config["HOTFIXES"][release]

        for hotfixes in branches.values():
            if hotfix in hotfixes:
                return hotfixes[hotfix]

        raise xenrt.XRTError("Hotfix %s for %s not found" % (hotfix, release))

    def addAllHotfixes(self):
        """Adds config entries for all released hotfixes so they get applied after host installation"""
            
        if not self.config.has_key("CARBON_PATCHES_ORLANDO"):
            self.config["CARBON_PATCHES_ORLANDO"] = {}
        self.config["CARBON_PATCHES_ORLANDO"]["HF10"] = self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3010"]
        self.config["CARBON_PATCHES_ORLANDO"]["HF18"] = self.config["HOTFIXES"]["Orlando"]["RTM"]["XS50EU3018"]
        
        if not self.config.has_key("CARBON_PATCHES_GEORGE"):
            self.config["CARBON_PATCHES_GEORGE"] = {}
        self.config["CARBON_PATCHES_GEORGE"]["HF04"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2004"]
        self.config["CARBON_PATCHES_GEORGE"]["HF05"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2005"]
        self.config["CARBON_PATCHES_GEORGE"]["HF08"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2008"]
        self.config["CARBON_PATCHES_GEORGE"]["HF09"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2009"]
        self.config["CARBON_PATCHES_GEORGE"]["HF10"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2010"]
        self.config["CARBON_PATCHES_GEORGE"]["HF23"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2023"]
        self.config["CARBON_PATCHES_GEORGE"]["HF25"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2025"]
        self.config["CARBON_PATCHES_GEORGE"]["HF26"] = self.config["HOTFIXES"]["George"]["RTM"]["XS55EU2026"]
        
        if not self.config.has_key("CARBON_PATCHES_MNR"):
            self.config["CARBON_PATCHES_MNR"] = {}
        self.config["CARBON_PATCHES_MNR"]["HF01"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E001"]
        self.config["CARBON_PATCHES_MNR"]["HF03"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E003"]
        self.config["CARBON_PATCHES_MNR"]["HF05"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E005"]
        self.config["CARBON_PATCHES_MNR"]["HF10"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E010"]
        self.config["CARBON_PATCHES_MNR"]["HF11"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E011"]
        self.config["CARBON_PATCHES_MNR"]["HF23"] = self.config["HOTFIXES"]["MNR"]["RTM"]["XS56E023"]
        
        if not self.config.has_key("CARBON_PATCHES_MNRCC"):
            self.config["CARBON_PATCHES_MNRCC"] = {}
            self.config["CARBON_PATCHES_MNRCC"]["HF02"] = self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC002"]
            self.config["CARBON_PATCHES_MNRCC"]["HF03"] = self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC003"]
            self.config["CARBON_PATCHES_MNRCC"]["HF07"] = self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC007"]
            self.config["CARBON_PATCHES_MNRCC"]["HF11"] = self.config["HOTFIXES"]["MNRCC"]["RTM"]["XS56ECC011"]
        
        if not self.config.has_key("CARBON_PATCHES_COWLEY"):
            self.config["CARBON_PATCHES_COWLEY"] = {}
        self.config["CARBON_PATCHES_COWLEY"]["HF15"] = self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1015"]
        self.config["CARBON_PATCHES_COWLEY"]["HF22"] = self.config["HOTFIXES"]["Cowley"]["RTM"]["XS56EFP1022"]
        
        if not self.config.has_key("CARBON_PATCHES_OXFORD"):
            self.config["CARBON_PATCHES_OXFORD"] = {}
        self.config["CARBON_PATCHES_OXFORD"]["HF03"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2003"]
        self.config["CARBON_PATCHES_OXFORD"]["HF10"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2010"]
        self.config["CARBON_PATCHES_OXFORD"]["HF11"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2011"]
        self.config["CARBON_PATCHES_OXFORD"]["HF23"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2023"]
        self.config["CARBON_PATCHES_OXFORD"]["HF26"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2026"]
        self.config["CARBON_PATCHES_OXFORD"]["HF30"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2030"]
        self.config["CARBON_PATCHES_OXFORD"]["HF34"] = self.config["HOTFIXES"]["Oxford"]["RTM"]["XS56ESP2034"]
        
        if not self.config.has_key("CARBON_PATCHES_BOSTON"):
            self.config["CARBON_PATCHES_BOSTON"] = {}
        self.config["CARBON_PATCHES_BOSTON"]["HF01"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E001"]
        self.config["CARBON_PATCHES_BOSTON"]["HF04"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E004"]
        self.config["CARBON_PATCHES_BOSTON"]["HF10"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E010"]
        self.config["CARBON_PATCHES_BOSTON"]["HF12"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E012"]
        self.config["CARBON_PATCHES_BOSTON"]["HF15"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E015"]
        self.config["CARBON_PATCHES_BOSTON"]["HF19"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E019"]
        self.config["CARBON_PATCHES_BOSTON"]["HF25"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E025"]
        self.config["CARBON_PATCHES_BOSTON"]["HF31"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E031"]
        self.config["CARBON_PATCHES_BOSTON"]["HF32"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E032"]
        self.config["CARBON_PATCHES_BOSTON"]["HF36"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E036"]
        self.config["CARBON_PATCHES_BOSTON"]["HF38"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E038"]
        self.config["CARBON_PATCHES_BOSTON"]["HF41"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E041"]
        self.config["CARBON_PATCHES_BOSTON"]["HF43"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E043"]
        self.config["CARBON_PATCHES_BOSTON"]["HF51"] = self.config["HOTFIXES"]["Boston"]["RTM"]["XS60E051"]
        
        if not self.config.has_key("CARBON_PATCHES_SANIBEL"):
            self.config["CARBON_PATCHES_SANIBEL"] = {}
        self.config["CARBON_PATCHES_SANIBEL"]["HF06"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E006"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF10"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E010"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF19"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E019"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF24"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E024"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF31"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E031"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF37"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E037"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF39"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E039"]
        self.config["CARBON_PATCHES_SANIBEL"]["HF46"] = self.config["HOTFIXES"]["Sanibel"]["RTM"]["XS602E046"]
        
        if not self.config.has_key("CARBON_PATCHES_SANIBELCC"):
            self.config["CARBON_PATCHES_SANIBELCC"] = {}
        self.config["CARBON_PATCHES_SANIBELCC"]["HF04"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC004"]
        self.config["CARBON_PATCHES_SANIBELCC"]["HF09"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC009"]
        self.config["CARBON_PATCHES_SANIBELCC"]["HF10"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC010"]
        self.config["CARBON_PATCHES_SANIBELCC"]["HF13"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC013"]
        self.config["CARBON_PATCHES_SANIBELCC"]["HF15"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC015"]
        self.config["CARBON_PATCHES_SANIBELCC"]["HF22"] = self.config["HOTFIXES"]["SanibelCC"]["RTM"]["XS602ECC022"]
        
        if not self.config.has_key("CARBON_PATCHES_TAMPA"):
            self.config["CARBON_PATCHES_TAMPA"] = {}
        self.config["CARBON_PATCHES_TAMPA"]["HF01"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E001"]
        self.config["CARBON_PATCHES_TAMPA"]["HF09"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E009"]
        self.config["CARBON_PATCHES_TAMPA"]["HF20"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E020"]
        self.config["CARBON_PATCHES_TAMPA"]["HF40"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E040"]
        self.config["CARBON_PATCHES_TAMPA"]["HF44"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E044"]
        self.config["CARBON_PATCHES_TAMPA"]["HF47"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E047"]
        self.config["CARBON_PATCHES_TAMPA"]["HF48"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E048"]
        self.config["CARBON_PATCHES_TAMPA"]["HF55"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E055"]
        self.config["CARBON_PATCHES_TAMPA"]["HF58"] = self.config["HOTFIXES"]["Tampa"]["RTM"]["XS61E058"]
        
        if not self.config.has_key("CARBON_PATCHES_CLEARWATER"):
            self.config["CARBON_PATCHES_CLEARWATER"] = {}

        branch = self.lookup("HFX_BRANCH_CLEARWATER", self.lookup(["DEFAULT_HOTFIX_BRANCH", "Clearwater"]))
        if branch == "RTM":
            self.config["CARBON_PATCHES_CLEARWATER"]["HF05"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E005"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF10"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E010"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF12"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E012"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF15"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E015"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF16"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E016"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF17"] = self.config["HOTFIXES"]["Clearwater"]["RTM"]["XS62E017"]
        elif branch == "SP1":
            self.config["CARBON_PATCHES_CLEARWATER"]["HF00"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF14"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1014"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF17"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1017"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF24"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1024"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF28"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1028"]
            self.config["CARBON_PATCHES_CLEARWATER"]["HF32"] = self.config["HOTFIXES"]["Clearwater"]["SP1"]["XS62ESP1032"]
            
        if not self.config.has_key("CARBON_PATCHES_CREEDENCE"):
            self.config["CARBON_PATCHES_CREEDENCE"] = {}

        branch = self.lookup("HFX_BRANCH_CREEDENCE", self.lookup(["DEFAULT_HOTFIX_BRANCH", "Creedence"]))
        if branch == "RTM":
            self.config["CARBON_PATCHES_CREEDENCE"]["HF01"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E001"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF02"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E002"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF03"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E003"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF05"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E005"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF08"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E008"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF11"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E011"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF14"] = self.config["HOTFIXES"]["Creedence"]["RTM"]["XS65E014"]
        elif branch == "SP1":
            self.config["CARBON_PATCHES_CREEDENCE"]["HF00"] = self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF05"] = self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1005"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF10"] = self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1010"]
            self.config["CARBON_PATCHES_CREEDENCE"]["HF11"] = self.config["HOTFIXES"]["Creedence"]["SP1"]["XS65ESP1011"]
            
    def readFromFile(self, filename, path=None):
        """Read config from an XML file."""
        self.parseConfig(filename, path=path)

    def __dictMerge(self, a, b):
        """Recursively merge dictionaries and b"""
        for k, v in b.iteritems():
            if k in a and isinstance(a[k], dict):
                self.__dictMerge(a[k], v)
            else:
                a[k] = v

    def readFromJSONFile(self, filename):
        """Read config from a JSON file."""
        with open(filename, 'r') as jf:
            self.__dictMerge(self.config, yaml.load(jf.read()))

    def writeOut(self, fd, conf=None, pref=[]):
        """Write the config out to a file descriptor"""
        if conf == None:
            conf = self.config
        keys = conf.keys()
        keys.sort()
        for key in keys:
            if type(conf[key]) == type(""):
                s = re.sub(r"\$\{(\w+)\}", self.lookupHelper, conf[key])
                value = string.replace(s, "'", "\\'")
                fd.write("%s='%s'\n" % (string.join(pref + [str(key)], "."), value))
            elif type(conf[key]) == int or type(conf[key]) == float:
                fd.write("%s=%s\n" % (string.join(pref + [str(key)], "."), str(conf[key])))
            elif type(conf[key]) == list:
                fd.write("%s=%s\n" % (string.join(pref + [str(key)], "."), str(conf[key])))
            elif conf[key] is None:
                fd.write("%s=None\n" % (string.join(pref + [str(key)], ".")))
            elif type(conf[key]) == dict:
                self.writeOut(fd, conf[key], pref + [key])
            else:
                raise xenrt.XRTError("Unknown type %s" % str(type(conf[key])))

    def setVariable(self, key, value):
        """Write a variable to the config"""
        if type(key) == type(""):
            self.config[str(key)] = str(value)
        elif type(key) == type(u""):
            self.config[str(key)] = str(value)
        else:
            dict = self.config
            for e in key[:-1]:
                e = str(e)
                if not dict.has_key(e):
                    dict[e] = {}
                dict = dict[e]
            dict[str(key[-1])] = str(value)

    def getAll(self, deep=False, dict=None, prefix=[]):
        reply = ""
        if dict == None:
            dict = self.config
        for key in dict.keys():
            if type(dict[key]) == type(""):
                if len(prefix) == 0:
                    value = self.lookup(key)
                else:
                    value = self.lookup(prefix+[key])
                value = string.replace(value, "'", "\\'")
                reply = reply + ("%s='%s'\n" %
                                 (string.join(prefix+[key], "_"), value))
            elif deep and dict[key]:
                reply = reply + self.getAll(deep=True,
                                            dict=dict[key],
                                            prefix=prefix+[key])
        return reply

    def getWithPrefix(self, prefix):
        reply = []
        dict = self.config
        for key in dict.keys():
            if (key[0:len(prefix)] == prefix):
                reply.append((key,self.lookup(key)))
        return reply

    def defined(self, var):
        """Check for the specified variable being defined."""
        return self.config.has_key(var)

    def lookup(self, var, default=xenrt.XRTError, boolean=False):
        s = None
        if type(var) == type("") and ":" in var:
            # Treat a string with colons as a list of the entities
            # separated by colons
            var = var.split(":")
        if type(var) == type(""):
            s = self._lookupThread(var)
            if s:
                xenrt.TEC().logverbose("Found thread local variable %s=%s" %
                                       (var, s))
        if not s:
            s = self.lookupNoRecurse(var, default=default)
        if type(s) == type(""):
            v = re.sub(r"\$\{([\w:]+)\}", self.lookupHelper, s)
            if boolean:
                if string.lower(v[0]) in ("1", "y", "t"):
                    return True
                if string.lower(v[0]) in ("0", "n", "f"):
                    return False
                if string.lower(v) == "on":
                    return True
                if string.lower(v) == "off":
                    return False
                return bool(v)
            return v
        v = s
        if v == None:
            return None
        if boolean:
            return bool(v)
        return v

    def lookupLeaves(self, key, node=None, reply=None):
        """Return s list of all leaf values for this variable (expanded).
        The values are sorted based on the alphanumeric sort order of the
        key names for each leaf node"""
        if reply == None:
            reply = {}
            toplevel = True
        else:
            toplevel = False
        if node == None:
            node = self.lookup(key, None)
        if node == None:
            pass
        elif type(node) == type(""):
            reply[key+str(len(reply))] = re.sub(r"\$\{([\w:]+)\}", self.lookupHelper, node)
        else:
            for k in node.keys():
                self.lookupLeaves(k, node[k], reply)
        if toplevel:
            keys = reply.keys()
            keys.sort()
            return map(lambda x:reply[x], keys)

    def lookupHost(self, hostname, var, default=xenrt.XRTError, boolean=False):
        """Lookup a variable first in a per-host config then globally"""
        l = ["HOST_CONFIGS", hostname]
        if type(var) == type(""):
            l.append(var)
        else:
            l.extend(var)
        x = self.lookup(l, None, boolean=boolean)
        if x != None:
            return x
        return self.lookup(var, default=default, boolean=boolean)

    def lookupVersion(self, ver, var, default=xenrt.XRTError, boolean=False):
        """Lookup a variable first in a per-version config then globally"""
        # Try our actual version first
        l = ["VERSION_CONFIG", ver]
        if type(var) == type(""):
            l.append(var)
        else:
            l.extend(var)
        x = self.lookup(l, None, boolean=boolean)
        if x != None:
            return x

        # Fall back to a global
        return self.lookup(var, default=default, boolean=boolean)

    def lookupHostAndVersion(self, hostname, ver, var, default=xenrt.XRTError,
                             boolean=False):
        """Lookup a variable first in a per-host config then per-version,
        then globally"""
        # Try a host specific variable first
        l = ["HOST_CONFIGS", hostname]
        if type(var) == type(""):
            l.append(var)
        else:
            l.extend(var)
        x = self.lookup(l, None, boolean=boolean)
        if x != None:
            return x
        # Fall back to a version specific lookup
        return self.lookupVersion(ver, var, default=default, boolean=boolean)
    
    def lookupHelper(self, mo):
        return self.lookup(mo.group(1))

    def lookupNoRecurse(self, var, default=xenrt.XRTError):
        """Look up the specified variable."""
        if type(var) == type(""):
            if self.config.has_key(var):
                return self.config[var]
            errstr = var
        else:
            dict = self.config
            for e in var[:-1]:
                if dict.has_key(e):
                    dict = dict[e]
                else:
                    dict = None
                    break
            if dict:
                if dict.has_key(var[-1]):
                    return dict[var[-1]]
            errstr = string.join(var, "/")
        if default == xenrt.XRTError:
            if self.lookup("IGNORE_CONFIG_LOOKUP_FAILURES", False, boolean=True):
                return None
            raise xenrt.XRTError("Config variable %s is not defined." %
                                 (errstr))
        return default

    def _lookupThread(self, var):
        """Look up a thread local variable. Returns None if no match."""
        t = xenrt.myThread()
        if not t:
            return None
        return t.lookup(var)

    def setDefault(self, var, value):
        """Sets a variable if it is not already set. This is intended to
        be used by test case classes to set defaults which may have been
        overriden by global, machine or site config.
        """
        if not self.config.has_key(var):
            self.config[var] = value

    def isVerbose(self):
        """Return true if verbose is enabled"""
        return self.verbose

    def setVerbose(self, verbose=True):
        self.verbose = verbose

    def parseXMLNode(self, node, path=None):
        for var in node.childNodes:
            if var.nodeType == var.ELEMENT_NODE:
                self.handleVar([var.localName], var, path=path)

    def parseConfig(self, filename, path=None):
        """Parse an XML configuration file"""
        dom = xml.dom.minidom.parse(filename)
        for i in dom.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "xenrt":
                    self.parseXMLNode(i, path=path)

    def handleVar(self, name, node, path=None):
        for i in node.childNodes:
            if i.nodeType == i.TEXT_NODE and i.data and \
                   string.strip(i.data) != "":
                if path:
                    self.setVariable(path + name, string.strip(i.data))
                else:
                    self.setVariable(name, string.strip(i.data))
            elif i.nodeType == i.ELEMENT_NODE:
                self.handleVar(name + [i.localName], i, path=path)
                        
