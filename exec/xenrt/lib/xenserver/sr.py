#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer storage repository.
#
# Copyright (c) 2006-2015 Citrix Systems UK. All use and distribution of
# this copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt
import string, re, libxml2, random, xml.dom.minidom

# Symbols we want to export from the package.
__all__ = ["getStorageRepositoryClass",
           "StorageRepository",
           "EXTStorageRepository",
           "LVMStorageRepository",
           "DummyStorageRepository",
           "NFSStorageRepository",
           "NFSv4StorageRepository",
           "NFSISOStorageRepository",
           "NFSv4ISOStorageRepository",
           "SMBStorageRepository",
           "FileStorageRepository",
           "FileStorageRepositoryNFS",
           "ISCSIStorageRepository",
           "HBAStorageRepository",
           "RawHBAStorageRepository",
           "IntegratedCVSMStorageRepository",
           "CVSMStorageRepository",
           "NetAppStorageRepository",
           "EQLStorageRepository",
           "ISOStorageRepository",
           "CIFSISOStorageRepository",
           "FCStorageRepository",
           "FCOEStorageRepository",
           "SharedSASStorageRepository",
           "ISCSIHBAStorageRepository",
           "ISCSILun",
           "ISCSILunSpecified",
           "NetAppTarget",
           "EQLTarget",
           "SMAPIv3LocalStorageRepository",
           "SMAPIv3SharedStorageRepository",
           "MelioStorageRepository"
            ]


def getStorageRepositoryClass(host, sruuid):
    """Find right SR class for existing SR"""

    srtype = host.genParamGet("sr", sruuid, "type")

    if srtype == "lvm":
        return LVMStorageRepository
    if srtype == "lvmoiscsi":
        return ISCSIStorageRepository
    if srtype == "lvmohba":
        return HBAStorageRepository
    if srtype == "nfs":
        return NFSStorageRepository
    if srtype == "ext":
        return EXTStorageRepository
    if srtype == "btrfs" or srtype == "smapiv3local":
        return SMAPIv3LocalStorageRepository
    if srtype == "rawnfs" or srtype == "smapiv3shared":
        return SMAPIv3SharedStorageRepository

    raise xenrt.XRTError("%s SR type class getter is not implemented." % srtype)


class StorageRepository(object):
    """Models a storage repository."""

    CLEANUP = "forget"
    SHARED = False
    TYPENAME = None
    SIZEVAR = None
    EXTRA_DCONF = {}
    THIN_PROV_KEYWORD = "thin"

    def __init__(self, host, name, thin_prov=False):
        self.host = host
        self.name = name
        self.uuid = None
        self.lun = None
        self.resources = {}
        self.isDestroyed = False
        self.__thinProv = thin_prov

        # Recorded by _create for possible future use by introduce
        self.srtype = None
        self.dconf = None
        self.content_type = ""
        self.smconf = {}

    @classmethod
    def fromExistingSR(cls, host, sruuid):
        """
        This method allows you to use the StorageRepository class functionailty
        without having created the SR with the class in the first instance
        @param host: a host on which to attach the SR
        @type: xenrt's host object
        @param sruuid: an existing sr's uuid (maybe created by prepare for example)
        @type: string
        @return: an instance of the class with the SR metadata populated
        @rtype: StorageRepository or decendent
        """
        xsr = next((sr for sr in host.asXapiObject().SR(False) if sr.uuid == sruuid), None)

        if not xsr:
            raise ValueError("Could not find sruuid %s on host %s" %(sruuid, host))

        instance = cls(host, xsr.name())
        instance.uuid = xsr.uuid
        instance.srtype = xsr.srType()
        instance.host = host

        xpbd = next((p for p in xsr.PBD() if p.host() == host.asXapiObject()), None)
        instance.dconf = xpbd.deviceConfig()
        instance.smconf = xsr.smConfig()
        instance.content_type = xsr.contentType()
        return instance

    @property
    def thinProvisioning(self):
        """Return whether sr is thinly provisioned."""

        if not self.uuid:
            raise xenrt.XRTError("SR instance is not associated with actual SR.")

        srtype = self.host.genParamGet("sr", self.uuid, "type")
        try:
            alloc = self.host.genParamGet("sr", self.uuid, "sm-config", "allocation")
            if alloc == self.THIN_PROV_KEYWORD:
                return True
            # For compatibility to old version.
            if alloc == "dynamic":
                return True

        except:
            # sm-config may not have 'allocation' key.
            pass

        return False

    def create(self, physical_size=0, content_type="", smconf={}):
        raise xenrt.XRTError("Unimplemented")

    def introduce(self):
        """Re-introduce the SR - it must have been created with this object previously"""
        if not self.uuid:
            raise xenrt.XRTError("Cannot sr-introduce because we have no UUID")
        if not self.srtype:
            raise xenrt.XRTError("Cannot sr-introduce because we don't know the type")
        if not self.dconf:
            raise xenrt.XRTError("Cannot sr-introduce because we don't know the dconf")
        cli = self.host.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.uuid))
        args.append("type=%s" % (self.srtype))
        args.append("content-type=%s" % (self.content_type))
        args.append("name-label=\"%s\"" % (self.name))
        if self.SHARED:
            args.append("shared=true")
        cli.execute("sr-introduce", string.join(args))
        hosts = self.host.minimalList("host-list")
        pbds = []
        for h in hosts:
            args = []
            args.append("host-uuid=%s" % (h))
            args.append("sr-uuid=%s" % (self.uuid))
            args.extend(["device-config:%s=\"%s\"" % (x, y)
                         for x,y in self.dconf.items()])
            pbd = cli.execute("pbd-create", string.join(args)).strip()
            pbds.append(pbd)
        for pbd in pbds:
            cli.execute("pbd-plug", "uuid=%s" % (pbd))

    def unplugPBDs(self):
        """Unplug all PBDs associated with this SR."""
        host = self.host
        cli = host.getCLIInstance()
        if host.pool:
            host = host.pool.master
            pbds = []
            for slave in host.pool.slaves.values():
                pbds.extend(host.minimalList("pbd-list", args="sr-uuid=%s host-uuid=%s" % (self.uuid, slave.uuid)))
            pbds.extend(host.minimalList("pbd-list", args="sr-uuid=%s host-uuid=%s" % (self.uuid, host.uuid)))
        else:
            pbds = [s.strip() for s in self.paramGet("PBDs").split(";")]

        # Unplug the PBDs
        for pbd in pbds:
            cli.execute("pbd-unplug", "uuid=%s" % (pbd))

    def forget(self):
        """Forget this SR (but keep the details in this object)"""
        self.unplugPBDs()
        self.host.getCLIInstance().execute("sr-forget", "uuid=%s" % (self.uuid))

    def destroy(self):
        """Destroy this SR (but keep the details in this object)"""
        self.unplugPBDs()
        self.host.getCLIInstance().execute("sr-destroy", "uuid=%s" % (self.uuid))
        self.isDestroyed = True

    def __isEligibleThinProvisioning(self, srtype=None):
        """Evaluate sr type to check whether it supports thin provisioning"""

        if not srtype:
            srtype = self.srtype
        if srtype in ["lvmoiscsi", "lvmohba"]:
            return True
        return False

    def _create(self, srtype, dconf, physical_size=0, content_type="", smconf={}):
        actualDeviceConfiguration = dict(self.EXTRA_DCONF)
        actualDeviceConfiguration.update(dconf)

        cli = self.host.getCLIInstance()
        args = []
        args.append("type=%s" % (srtype))
        args.append("content-type=%s" % (content_type))
        if not physical_size == None:
            args.append("physical-size=%s" % (physical_size))
        args.append("name-label=\"%s\"" % (self.name))
        if self.SHARED:
            args.append("shared=true")
        args.extend(["device-config:%s=\"%s\"" % (x, y)
                     for x,y in actualDeviceConfiguration.items()])
        if not self.__thinProv:
            self.__thinProv = xenrt.TEC().lookup("FORCE_THIN_LVHD", False, boolean=True)
        if self.__thinProv:
            if self.__isEligibleThinProvisioning(srtype):
                if xenrt.TEC().lookup("USE_DYNAMIC_KEYWORD", False, boolean=True):
                    smconf["allocation"] = "dynamic"
                else:
                    smconf["allocation"] = self.THIN_PROV_KEYWORD
            else:
                xenrt.warning("SR: %s is marked as thin provisioning but %s does not support it. Ignoring..." % (self.name, srtype))
        args.extend(["sm-config:%s=\"%s\"" % (x, y)
                    for x,y in smconf.items()])
        self.uuid = cli.execute("sr-create", string.join(args)).strip()
        self.srtype = srtype
        self.dconf = actualDeviceConfiguration
        self.content_type = content_type
        self.smconf = smconf

    def check(self):
        self.checkCommon(self.srtype)
        return True

    def checkCommon(self, srtype):
        cli = self.host.getCLIInstance()
        if not self.uuid:
            raise xenrt.XRTError("SR UUID not known")
        if self.isDestroyed:
            sruuids = self.host.minimalList("sr-list")
            if self.uuid in sruuids:
                raise xenrt.XRTFailure("SR still exists after destroy",
                                       self.uuid)
            pbduuids = self.host.minimalList("pbd-list",
                                             args="sr-uuid=%s" % (self.uuid))
            if len(pbduuids) > 0:
                raise xenrt.XRTFailure("PBD(s) for SR exists after destroy",
                                       "SR %s, PBDs %s" %
                                       (self.uuid, string.join(pbduuids)))
            return
        try:
            data = cli.execute("sr-param-list", "uuid=%s" % (self.uuid))
        except:
            raise xenrt.XRTFailure("Could not fetch params for %s/%s" %
                                   (self.name, self.uuid))
        n = self.paramGet("name-label")
        if n != self.name:
            raise xenrt.XRTFailure("SR name '%s' does not match "
                                   "requested '%s'" % (n, self.name))
        t = self.paramGet("type")
        if t != srtype:
            raise xenrt.XRTFailure("SR type '%s' is not '%s'" %
                                   (t, srtype))

        pbds = string.split(self.paramGet("PBDs"), ";")
        for pbd in pbds:
            pbd = string.strip(pbd)
            ca = self.host.genParamGet("pbd", pbd, "currently-attached")
            if ca != "true":
                xenrt.TEC().logverbose("PBD %s of SR %s not attached" %
                                       (pbd, self.uuid))
                raise xenrt.XRTFailure("A PBD belonging to a %s SR is not "
                                       "attached" % (srtype))
        
    def paramGet(self, paramName, pkey=None):
        usecli = self.host.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.uuid))
        args.append("param-name=%s" % (paramName))
        if pkey:
            args.append("param-key=%s" % (pkey))
        data = usecli.execute("sr-param-get", string.join(args)).strip()
        return data

    def paramSet(self, paramName, paramValue):
        usecli = self.host.getCLIInstance()
        data = usecli.execute("sr-param-set",
                              "uuid=%s %s=\"%s\"" %
                              (self.uuid,
                               paramName,
                               str(paramValue).replace('"', '\\"')))

    def getPBDs(self):
        """Return a list of PBDs on this SR and their plugged state"""
        pbds = self.host.minimalList("pbd-list","uuid",
                                     "sr-uuid=%s" % (self.uuid))
        retDict = {}
        for p in pbds:
            if self.host.genParamGet("pbd", p, "currently-attached") == "true":
                retDict[p] = True
            else:
                retDict[p] = False

        return retDict

    def listVDIs(self):
        """Return a list of VDIs in this SR."""
        return self.host.minimalList("vdi-list", "uuid", "sr-uuid=%s" % (self.uuid))

    def remove(self):
        xenrt.TEC().logverbose("Finding VMs/VDIs in SR %s" % (self.uuid))
        usecli = self.host.getCLIInstance()
        vdilist = self.paramGet("VDIs").split(";")
        # Shutdown and remove all VMs on the SR.
        for vdi in vdilist:
            vdi = vdi.strip()
            vmlist = self.host.minimalList("vbd-list", 
                                           "vm-uuid",
                                           "vdi-uuid=%s" % (vdi))
            for vm in vmlist:
                try:
                    usecli.execute("vm-shutdown",  "uuid=%s --force" % (vm))
                except Exception, e:
                    xenrt.TEC().logverbose("Exception trying to shutdown VM "
                                           "%s on SR %s: %s" %
                                           (vm, self.uuid, str(e)))
                try:
                    usecli.execute("vm-uninstall", "uuid=%s --force" % (vm))
                except Exception, e:
                    xenrt.TEC().logverbose("Exception trying to shutdown VM "
                                           "%s on SR %s: %s" %
                                           (vm, self.uuid, str(e)))
                    
        # Try to remove any left over VDIs
        vdilist = self.paramGet("VDIs").split(";")
        for vdi in vdilist:
            vdi = vdi.strip()
            try:
                usecli.execute("vdi-destroy", "uuid=%s" % (vdi))
            except Exception, e:
                xenrt.TEC().logverbose("Exception trying to destroy VDI %s "
                                       "on SR %s: %s" %
                                       (vdi, self.uuid, str(e)))
        # Unplug all the PBDs.
        xenrt.TEC().logverbose("Unplugging PBDs")
        self.unplugPBDs()

        xenrt.TEC().logverbose("Calling sr-%s" % (self.CLEANUP))
        try:
            usecli.execute("sr-%s" % (self.CLEANUP), "uuid=%s" % (self.uuid))
        except Exception, e:
            # If a destroy failed, try a forget instead
            xenrt.TEC().logverbose("Exception trying to sr-%s %s: %s" %
                                   (self.CLEANUP, self.uuid, str(e)))
            if self.CLEANUP != "forget":
                xenrt.TEC().logverbose("Try to forget the SR instead...")
                self.unplugPBDs()
                usecli.execute("sr-forget", "uuid=%s" % (self.uuid))

    def prepareSlave(self, master, slave, special=None):
        """Perform any actions on a slave before joining a pool that are
        needed to work with this SR type. Override if needed.
        """
        pass

    def physicalSizeMB(self):
        """Returns the physical size of this SR in MB."""
        return int(self.paramGet("physical-size"))/xenrt.MEGA

    def release(self):
        self.remove()

    def messageCreate(self, name, body, priority=1):
        self.host.messageGeneralCreate("sr",
                                       self.uuid,
                                       name,
                                       body,
                                       priority)

    def scan(self):
        self.host.getCLIInstance().execute("sr-scan", "uuid=%s" % self.uuid)

    def createVDI(self, sizebytes, smconfig={}, name=None):
        cli = self.host.getCLIInstance()
        args = []
        if name and type(name) == type(""):
            name = name.strip()
            if len(name) > 0:
                args.append("name-label=\"%s\"" % (name))
            else:
                name = None
        else:
            name = None
        if not name:
            if xenrt.TEC().lookup("WORKAROUND_CA174211", False, boolean=True):
                args.append("name-label=\"Created_by_XenRT\"")
            else:
                args.append("name-label=\"Created by XenRT\"")
        args.append("sr-uuid=%s" % (self.uuid))
        args.append("virtual-size=%s" % (sizebytes))
        args.append("type=user")
        for key in smconfig:
            args.append("sm-config:%s=%s" % (key, smconfig[key]))

        return cli.execute("vdi-create", string.join(args), strip=True)

    def setDefault(self):
        """Set given SR to default"""

        pool = self.host.minimalList("pool-list")[0]
        self.host.genParamSet("pool", pool, "default-SR", self.uuid)
        self.host.genParamSet("pool", pool, "crash-dump-SR", self.uuid)
        self.host.genParamSet("pool", pool, "suspend-image-SR", self.uuid)


class EXTStorageRepository(StorageRepository):

    SHARED = False
    CLEANUP = "destroy"

    def create(self, device, physical_size=0, content_type=""):
        self._create("ext", {"device":device})


class LVMStorageRepository(StorageRepository):

    SHARED = False
    CLEANUP = "destroy"

    def create(self, device, physical_size=0, content_type="", smconf={}):
        self._create("lvm", {"device":device}, physical_size, content_type, smconf)


class SMAPIv3LocalStorageRepository(StorageRepository):

    SHARED = False
    CLEANUP = "destroy"

    def create(self, device, physical_size=0, content_type="", smconf={}):
        if not device:
            device = self.host.getGuestDisks()[0]
        if device != self.host.getInstallDisk():
            self.host.execdom0("sgdisk -Z /dev/%s" % device)
            partition = 1
        else:
            device = self.host.execdom0("source /etc/xensource-inventory; echo $PRIMARY_DISK | sed 's#/dev/##'").strip()
            partition = int(self.host.execdom0("sgdisk -p /dev/%s| tail -1 | awk '{print $1}'" % device).strip()) + 1
        self.host.execdom0("sgdisk -N %d /dev/%s" % (partition, device))
        self.host.execdom0("partprobe")
        if device.startswith("disk/"):
            path = "/dev/%s-part%d" % (device, partition)
        else:
            path = "/dev/%s%d" % (device, partition)
        self._create("btrfs", {"uri":"file://%s" % path}, physical_size, content_type, smconf)

class MelioStorageRepository(StorageRepository):
    SHARED = True
    CLEANUP = "destroy"
    
    def create(self, melio, physical_size=0, content_type="", smconf={}):
        self.melio = melio
        self._create("melio", {"uri":"file:///dev/%s" % self.melio.getSanDeviceForHost(self.melio.hosts[0])}, physical_size, content_type, smconf)

class IntegratedCVSMStorageRepository(StorageRepository):
    SHARED = True
    CLEANUP = "destroy"

# 1) sr-probe
#[root@localhost sm]# xe sr-probe type=cslg device-config:adapterid=NETAPP device-config:target=10.80.225.95 device-config:username=root device-config:password=xenroot 
# 2) sr-create
#[root@localhost sm]# xe sr-create name-label=slSr type=cslg device-config:adapterid=NETAPP device-config:target=10.80.225.95 device-config:username=root device-config:password=xenroot device-config:storageSystemId=NETAPP__LUN__0A50E2F6 device-config:storagePoolId=9d631bc2-948b-11de-b6cf-00a09804ab62

    def probe(self, deviceconf={}):
        cli = self.host.getCLIInstance()
        res = self.resources["target"]
        args = []
        args.append("type=cslg")
        #args.append("sm-config:add_adapter=1")
        args.append("device-config:adapterid=%s" % res.getType())
        args.append("device-config:target=%s" % res.getTarget())
        args.append("device-config:username=%s" % res.getUsername())
        args.append("device-config:password=%s" % res.getPassword())
        for (k,v) in deviceconf.items():
            args.append("device-config:%s=%s" % (k,v))
        out=""
        out = cli.execute("sr-probe %s" % (string.join(args)))
        xenrt.TEC().logverbose("sr-probe returned %s" % out)  
        m=re.search("(<\?xml.*>)",out,re.DOTALL)
        if m:
            return m.group(0)
        else:
            raise xenrt.XRTError("no xml string in sr-probe response: %s" % out)

    def xpath(self, expression, xmltext):
        xmltree = libxml2.parseDoc(xmltext)
        nodes = xmltree.xpathEval(expression)
        return map(lambda x:x.getContent(), nodes)

    #to get SSID, call sr-probe with neither ssid nor spoolid
    def getStorageSystemId(self):
        resource = self.resources["target"]
        str_probe = self.probe()
        x = self.xpath("//storageSystemId[../friendlyName='%s']" %
                          (resource.getFriendlyName()), str_probe)
        if len(x)<1:
            raise xenrt.XRTError("no storageSystemId with friendlyName=%s was returned by sr-probe: %s" % (resource.getFriendlyName(), str_probe))
        else:
            return x.pop()

    #to get SpoolID, call sr-probe with only ssid
    def getStoragePoolId(self):
        resource = self.resources["target"]
        ssid = self.getStorageSystemId()
        return self.xpath("//storagePoolId[../displayName='%s']" %
                          resource.getDisplayName(), #AGGR
                          self.probe({"storageSystemId":ssid})).pop()

    def create(self,
               resource,
               protocol=None,
               physical_size=0,
               multipathing=False):
        self.resources["target"] = resource
        if protocol:
            if not protocol in resource.getProtocolList():
                raise xenrt.XRTError("Resource %s does not support requested "
                                     "protocol %s" %
                                     (resource.getName(), protocol))
            self.protocol = protocol
        else:
            self.protocol = "auto"
        
        self.multipathing = multipathing
        if multipathing:
            if self.host.pool:
                self.host.pool.enableMultipathing()
            else:
                self.host.enableMultipathing()
        if physical_size == 0:
            if resource.size:
                physical_size = "%sGiB" % (resource.size)
            else:
                physical_size = xenrt.TEC().lookup(self.SIZEVAR, "50GiB")
        self._create("cslg",
                    {"storageSystemId":self.getStorageSystemId(),
                     "storagePoolId":self.getStoragePoolId(),
                     "adapterid":resource.getType(),
                     "target":resource.getTarget(),
                     "username":resource.getUsername(),
                     "password":resource.getPassword(),
                     "protocol":self.protocol
                     },
                      physical_size=physical_size) 
    
    def prepareSlave(self, master, slave, special=None):
        try:
            if self.multipathing:
                slave.enableMultipathing()
        except AttributeError:
            pass # In case someone calls this function before create


class CVSMStorageRepository(StorageRepository):

    SHARED = True
    CLEANUP = "destroy"

    def probe(self, deviceconf={}):
        cvsmserver = self.resources["cvsmserver"]
        cli = self.host.getCLIInstance()
        args = []
        args.append("type=cslg")
        args.append("device-config:target=%s" % (cvsmserver.place.getIP()))
        for (k,v) in deviceconf.items():
            args.append("device-config:%s=%s" % (k, v))
        return cli.execute("sr-probe %s" % (string.join(args)))

    def getStorageSystemId(self):
        cvsmserver = self.resources["cvsmserver"]
        resource = self.resources["target"]
        return cvsmserver.getStorageSystemId(resource)

    def getStoragePoolId(self):
        cvsmserver = self.resources["cvsmserver"]
        resource = self.resources["target"]
        return cvsmserver.getStoragePoolId(resource,
                                           "displayName",
                                           resource.getDisplayName())

    def ensureHostIsKnownToCVSM(self, host):
        cvsmserver = self.resources["cvsmserver"]
        if not cvsmserver.isHostKnownToCVSM(host):
            cvsmserver.addXenServerHost(host)
        if not cvsmserver.isHostKnownToCVSM(host):
            raise xenrt.XRTError("Host not known to CVSM after adding",
                                 host.getName())

    def create(self,
               cvsmserver,
               resource,
               protocol=None,
               physical_size=0,
               multipathing=False):
        self.resources["cvsmserver"] = cvsmserver
        self.resources["target"] = resource
        if protocol:
            if not protocol in resource.getProtocolList():
                raise xenrt.XRTError("Resource %s does not support requested "
                                     "protocol %s" %
                                     (resource.getName(), protocol))
            self.protocol = protocol
        else:
            self.protocol = "auto"
        self.ssid = self.getStorageSystemId() 
        self.poolid = self.getStoragePoolId() 
        self.ensureHostIsKnownToCVSM(self.host)
        self.multipathing = multipathing
        if multipathing:
            self.host.enableMultipathing()
        if physical_size == 0:
            if resource.size:
                physical_size = "%sGiB" % (resource.size)
            else:
                physical_size = xenrt.TEC().lookup(self.SIZEVAR, "50GiB")
        self._create("cslg",
                    {"target":cvsmserver.place.getIP(),
                     "storageSystemId":self.ssid,
                     "storagePoolId":self.poolid,
                     "protocol":self.protocol},
                      physical_size=physical_size) 
    
    def check(self):
        StorageRepository.checkCommon(self, "cslg")

    def prepareSlave(self, master, slave, special=None):
        # According to CA-41236 this isn't necessary - CVSM will figure it out...
        # self.ensureHostIsKnownToCVSM(slave)
        pass


class DummyStorageRepository(StorageRepository):
    SHARED=True

    def create(self, size):
        self._create("dummy", {}, physical_size=size)


class CIFSISOStorageRepository(StorageRepository):
    def create(self,
               server,
               share,
               type="iso",
               content_type="iso",
               username="Administrator",
               password=None,
               use_secret=False,
               shared=True):
        if not password:
            password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
        cli = self.host.getCLIInstance()
        args = []
        args.append("device-config-location=\"//%s/%s\"" %
                    (server, share))
        args.append("device-config:type=cifs")
        args.append("device-config:username=%s" % (username))
        if use_secret:
            args.append("device-config:cifspassword_secret=%s" % password)
        else:
            args.append("device-config:cifspassword=%s" % (password))
        args.append("name-label=%s" % (self.name))
        args.append("type=%s" % (type))
        args.append("content-type=%s" % (content_type))
        args.append("host-uuid=%s" % (self.host.getMyHostUUID()))
        args.append("shared=%s" % "true" if shared else "false")
        self.uuid = cli.execute("sr-create", string.join(args), strip=True)
        
    def check(self):
        StorageRepository.checkCommon(self, "iso")


class ISOStorageRepository(StorageRepository):
    """Models an ISO SR"""
    
    def create(self, server, path):
        self.host.createISOSR("%s:%s" % (server, path))
        self.uuid = self.host.minimalList("pbd-list",
                                          "sr-uuid",
                                          "device-config-location=%s:%s" %
                                          (server, path))[0]


class FileStorageRepository(StorageRepository):
    """Models a File SR"""

    def create(self, path):
        dconf = {}
        dconf['location'] = path
        self._create("file", dconf)

    def check(self):
        StorageRepository.checkCommon(self, "file")


class FileStorageRepositoryNFS(FileStorageRepository):
    SHARED = True

    def create(self, server, path):
        self.server = server
        self.path = path
        self.mountpoint = "/mnt/nfsfilesr/%d" % random.randint(0, 0xffff)
        if self.host.pool:
            self.mountNFS(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.mountNFS(slave)
        else:
            self.mountNFS(self.host)
        FileStorageRepository.create(self, self.mountpoint)

    def mountNFS(self, host):
        host.execdom0("mkdir -p %s" % self.mountpoint)
        host.execdom0("""echo "%s:%s %s nfs defaults 0 0" >> /etc/fstab""" % (self.server, self.path, self.mountpoint))
        host.execdom0("mount %s" % self.mountpoint)
    
    def prepareSlave(self, master, slave, special=None):
        self.mountNFS(slave)


class NFSStorageRepository(StorageRepository):
    """Models an NFS SR"""

    SHARED = True

    def getServerAndPath(self, server, path):
        if not (server or path):
            if xenrt.TEC().lookup("FORCE_NFSSR_ON_CTRL", False, boolean=True):
                # Create an SR using an NFS export from the XenRT controller.
                # This should only be used for small and low I/O throughput
                # activities - VMs should never be installed on this.
                nfsexport = xenrt.NFSDirectory()
                server, path = nfsexport.getHostAndPath("")
            else:
                # Create an SR on an external NFS file server
                share = xenrt.ExternalNFSShare()
                nfs = share.getMount()
                r = re.search(r"([0-9\.]+):(\S+)", nfs)
                server = r.group(1)
                path = r.group(2)
        self.server = server
        self.path = path


    def create(self, server=None, path=None, physical_size=0, content_type="", nosubdir=False):
        self.getServerAndPath(server, path)
        dconf = {}
        smconf = {}
        dconf["server"] = self.server
        dconf["serverpath"] = self.path
        if nosubdir:
            smconf["nosubdir"] = "true"
        self._create("nfs",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type,
                     smconf=smconf)

    def introduce(self, nosubdir=False):
        """Re-introduce the SR - it must have been created with this object previously"""
        if not self.uuid:
            raise xenrt.XRTError("Cannot sr-introduce because we have no UUID")
        if not self.srtype:
            raise xenrt.XRTError("Cannot sr-introduce because we don't know the type")
        if not self.dconf:
            raise xenrt.XRTError("Cannot sr-introduce because we don't know the dconf")
        cli = self.host.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.uuid))
        args.append("type=%s" % (self.srtype))
        args.append("content-type=%s" % (self.content_type))
        args.append("name-label=\"%s\"" % (self.name))
        if self.SHARED:
            args.append("shared=true")
        if nosubdir:
            args.append("sm-config:nosubdir=true")
            
        cli.execute("sr-introduce", string.join(args))
        hosts = self.host.minimalList("host-list")
        pbds = []
        for h in hosts:
            args = []
            args.append("host-uuid=%s" % (h))
            args.append("sr-uuid=%s" % (self.uuid))
            args.extend(["device-config:%s=\"%s\"" % (x, y)
                         for x,y in self.dconf.items()])
            pbd = cli.execute("pbd-create", string.join(args)).strip()
            pbds.append(pbd)
        for pbd in pbds:
            cli.execute("pbd-plug", "uuid=%s" % (pbd))

    def check(self):
        StorageRepository.checkCommon(self, "nfs")
        #cli = self.host.getCLIInstance()
        if self.host.pool:
            self.checkOnHost(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.checkOnHost(slave)
        else:
            self.checkOnHost(self.host)

    def checkOnHost(self, host):
        try:
            host.execdom0("test -d /var/run/sr-mount/%s" % (self.uuid))
        except:
            raise xenrt.XRTFailure("SR mountpoint /var/run/sr-mount/%s "
                                   "does not exist" % (self.uuid))
        nfs = string.split(host.execdom0("mount | grep \""
                                          "/run/sr-mount/%s \"" %
                                          (self.uuid)))[0]
        shouldbe = "%s:%s/%s" % (self.server, self.path, self.uuid)
        if nfs != shouldbe:
            raise xenrt.XRTFailure("Mounted path '%s' is not '%s'" %
                                   (nfs, shouldbe))


class NFSISOStorageRepository(StorageRepository):
    """Models an NFS ISO SR"""

    SHARED = True

    def create(self, server=None, path=None, physical_size=0, content_type="iso"):
        if not (server or path):
            if xenrt.TEC().lookup("FORCE_NFSSR_ON_CTRL", False, boolean=True):
                # Create an SR using an NFS export from the XenRT controller.
                # This should only be used for small and low I/O throughput
                # activities - VMs should never be installed on this.
                nfsexport = xenrt.NFSDirectory()
                server, path = nfsexport.getHostAndPath("")
            else:
                # Create an SR on an external NFS file server
                share = xenrt.ExternalNFSShare()
                nfs = share.getMount()
                r = re.search(r"([0-9\.]+):(\S+)", nfs)
                server = r.group(1)
                path = r.group(2)

        self.server = server
        self.path = path
        dconf = {}
        smconf = {}
        dconf["location"] = server + ":" + path
        self._create("iso",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type,
                     smconf=smconf)
    
    def check(self):
        StorageRepository.checkCommon(self, "iso")
        #cli = self.host.getCLIInstance()
        if self.host.pool:
            self.checkOnHost(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.checkOnHost(slave)
        else:
            self.checkOnHost(self.host)

    def checkOnHost(self, host):
        try:
            host.execdom0("test -d /var/run/sr-mount/%s" % (self.uuid))
        except:
            raise xenrt.XRTFailure("SR mountpoint /var/run/sr-mount/%s "
                                   "does not exist" % (self.uuid))
        nfs = string.split(host.execdom0("mount | grep \""
                                          "/run/sr-mount/%s \"" %
                                          (self.uuid)))[0]
        shouldbe = "%s:%s/%s" % (self.server, self.path, self.uuid)
        if nfs != shouldbe:
            raise xenrt.XRTFailure("Mounted path '%s' is not '%s'" %
                                   (nfs, shouldbe))


class NFSv4StorageRepository(NFSStorageRepository):
    EXTRA_DCONF = {'nfsversion': '4'}


class NFSv4ISOStorageRepository(NFSISOStorageRepository):
    EXTRA_DCONF = {'nfsversion': '4'}


class SMAPIv3SharedStorageRepository(NFSStorageRepository):

    def create(self, server=None, path=None, physical_size=0, content_type=""):
        self.getServerAndPath(server, path)
        dconf = {}
        smconf = {}
        dconf["uri"] = "nfs://%s%s" % (self.server, self.path)
        self._create("rawnfs",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type,
                     smconf=smconf)

    def check(self):
        StorageRepository.checkCommon(self, "rawnfs")
        #cli = self.host.getCLIInstance()
        if self.host.pool:
            self.checkOnHost(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.checkOnHost(slave)
        else:
            self.checkOnHost(self.host)

    def checkOnHost(self, host):
        path = "/run/sr-mount/nfs/%s%s" % (self.server, self.path)
        try:
            host.execdom0("test -d %s" % path)
        except:
            raise xenrt.XRTFailure("SR mountpoint %s does not exist" % path)
        nfs = string.split(host.execdom0("mount | grep \""
                                          "%s\"" % path))[0]
        shouldbe = "%s:%s" % (self.server, self.path)
        if nfs != shouldbe:
            raise xenrt.XRTFailure("Mounted path '%s' is not '%s'" %
                                   (nfs, shouldbe))


class SMBStorageRepository(StorageRepository):
    """Models a SMB SR"""

    SHARED = True

    def create(self, share=None, cifsuser=None):
        if not share:
            share = xenrt.ExternalSMBShare(version=3, cifsuser=cifsuser)

        dconf = {}
        smconf = {}
        dconf["server"] = share.getLinuxUNCPath()

        # CLI is not accepting the domain name at present. (1036047)
        #if share.domain:
        #    dconf['username'] = "%s\\\\%s" % (share.domain, share.user)
        #else:
        dconf['username'] = share.user
        dconf['password'] = share.password
        self._create("cifs", dconf)

    def check(self):
        StorageRepository.checkCommon(self, "cifs")
        if self.host.pool:
            self.checkOnHost(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.checkOnHost(slave)
        else:
            self.checkOnHost(self.host)

    def checkOnHost(self, host):
        pass
        # TODO update this to use the correct paths
        #try:
        #    host.execdom0("test -d /var/run/sr-mount/%s" % (self.uuid))
        #except:
        #    raise xenrt.XRTFailure("SR mountpoint /var/run/sr-mount/%s "
        #                           "does not exist" % (self.uuid))
        #smb = string.split(host.execdom0("mount | grep \""
        #                                  "/run/sr-mount/%s \"" %
        #                                  (self.uuid)))[0]
        #shouldbe = "%s/%s" % (self.serverpath, self.uuid)
        #if smb != shouldbe:
        #    raise xenrt.XRTFailure("Mounted path '%s' is not '%s'" %
        #                           (smb, shouldbe))


class ISCSIStorageRepository(StorageRepository):
    """Models an ISCSI SR"""

    CLEANUP = "destroy"
    SHARED = True
    THIN_PROV_KEYWORD = "xlvhd"

    def create(self,
               lun=None,
               physical_size=0,
               content_type="",
               subtype="ext",
               findSCSIID=False,
               noiqnset=False,
               multipathing=None,
               jumbo=False,
               mpp_rdac=False,
               lungroup=None,
               initiatorcount=None,
               smconf={}):
        """Create the iSCSI SR on the host

        @param multipathing: If set to C{True}, use multipathing on this SR, and
            enable it on the host if it is not already. If set to C{False}, do
            not use multipathing for this SR (even if it is enabled on the host).
            If set to C{None}, then do not specify whether to use multipathing,
            i.e. use the product default.
        """

        if self.host.lungroup:
            lun = self.host.lungroup.allocateLun()

        if not lun:
            minsize = int(self.host.lookup("SR_ISCSI_MINSIZE", 40))
            maxsize = int(self.host.lookup("SR_ISCSI_MAXSIZE", 1000000))
            params = {}
            # Check if the master host requires the LUN to be on a
            # specific network.
            fnw = self.host.lookup("FORCE_ISCSI_NETWORK", None)
            if fnw:
                params["NETWORK"] = fnw
                
                # Check we have an interface on this network
                nics = self.host.listSecondaryNICs(fnw)
                if len(nics) == 0:
                    raise xenrt.XRTError("Forced to use iSCSI network %s "
                                         "but %s does not have it" %
                                         (fnw, self.host.getName()))
                
                # See if any interface on this network is configured
                configured = False
                for nic in nics:
                    try:
                        ip = self.host.getIPAddressOfSecondaryInterface(nic)
                        configured = True
                    except:
                        pass

                if not configured:
                    raise xenrt.XRTError("Forced to use iSCSI network %s "
                                         "but %s does not have an address on "
                                         "this network" %
                                         (fnw, self.host.getName()))
            # Find a LUN with enough innitiator names for all hosts in the
            # test job.
            i = 0
            if initiatorcount:
                params["INITIATORS"] = initiatorcount
            else:
                while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
                    i = i + 1
                params["INITIATORS"] = i
            ttype = xenrt.TEC().lookup("ISCSI_TYPE", None)
            lun = xenrt.lib.xenserver.ISCSILun(minsize=minsize,
                                               maxsize=maxsize,
                                               params=params,
                                               jumbo=jumbo,
                                               mpprdac=mpp_rdac,
                                               ttype = ttype)
            if not lun.getID():
                findSCSIID = True

        self.lun = lun
        self.subtype = subtype
        self.noiqnset = noiqnset
        self.multipathing = multipathing
        if not noiqnset and not self.host.lungroup: # This will be set earlier if we're using a lun group
            self.host.setIQN(lun.getInitiatorName(allocate=True))
        cli = self.host.getCLIInstance()        

        if multipathing:
            self.host.enableMultipathing(mpp_rdac=mpp_rdac)

        if not lun.getID() and findSCSIID:
            # Do a create, and parse the XML error output for the SCSIid
            args = []
            args.append("name-label=temp-iscsi")
            args.append("shared=true")
            args.append("type=%soiscsi" % (subtype))
            args.append("physical-size=%u" % (physical_size))
            args.append("content-type=%s" % (content_type))
            args.append("device-config-target=%s" % (lun.getServer()))
            args.append("device-config-targetIQN=%s" % (lun.getTargetName()))
            args.append("device-config-LUNid=%u" % (lun.getLunID()))
            chap = lun.getCHAP()
            if chap:
                u, p = chap
                args.append("device-config-chapuser=%s" % (u))
                args.append("device-config-chappassword=%s" % (p))
            
            outgoingChap = lun.getOutgoingCHAP()
            if outgoingChap:
                u, p = outgoingChap
                args.append("device-config-incoming_chapuser=%s" % (u))
                args.append("device-config-incoming_chappassword=%s" % (p))
            
            try:
                uuid = cli.execute("sr-create", string.join(args), strip=True)
                xenrt.TEC().warning("SR was created without a SCSI ID")
                cli.execute("sr-forget", "uuid=%s" % (uuid))
            except xenrt.XRTFailure, e:
                # If this was a CLI timeout then raise that
                if "timed out" in e.reason:
                    raise e
                # XXX (should check that this is indeed a probe-stype XML
                # exception)
                
                # Split away the stuff before the <?xml
                split = e.data.split("<?",1)
                if len(split) != 2:
                    raise xenrt.XRTFailure("Couldn't find XML output from "
                                           "sr-create command")
                # Parse the XML and find the SCSIid
                dom = xml.dom.minidom.parseString("<?" + split[1])
                luns = dom.getElementsByTagName("LUN")
                found = False
                for l in luns:
                    lids = l.getElementsByTagName("LUNid")
                    if len(lids) == 0:
                        continue
                    lunid = int(lids[0].childNodes[0].data.strip())
                    if lunid == lun.getLunID():
                        ids = l.getElementsByTagName("SCSIid")
                        if len(ids) == 0:
                            raise xenrt.XRTFailure("Couldn't find SCSIid for "
                                                   "lun %u in XML output" % 
                                                   (lunid))
                        lun.setID(ids[0].childNodes[0].data.strip())
                        found = True
                        break
                if not found:
                    raise xenrt.XRTFailure("Couldn't find lun in XML output")
                
        dconf = {}
        dconf["target"] = lun.getServer()
        dconf["targetIQN"] = lun.getTargetName()
        if lun.getLunID() != None:
            dconf["LUNid"] = lun.getLunID()
        if lun.getID():
            if type(lun.getID()) == type(1):
                strscsi = string.join(["%02x" % ord(x) for x in "%08x" % lun.getID()], "")
                dconf["SCSIid"] = "14945540000000000%s0000000000000000" % strscsi
            else:
                dconf["SCSIid"] = lun.getID()
        chap = lun.getCHAP()
        if chap:
            u, p = chap
            dconf["chapuser"] = u
            dconf["chappassword"] = p
        
        outgoingChap = lun.getOutgoingCHAP()
        if outgoingChap:
            u, p = outgoingChap
            dconf["incoming_chapuser"] = u
            dconf["incoming_chappassword"] = p
            
        if multipathing:
            dconf["multihomed"] = "true"
        elif type(multipathing) == type(False):
            dconf["multihomed"] = "false"

        self._create("%soiscsi" % (subtype),
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type,
                     smconf=smconf)

    def check(self):
        StorageRepository.checkCommon(self, "%soiscsi" % (self.subtype))
        #cli = self.host.getCLIInstance()

    def prepareSlave(self, master, slave, special=None):
        if not self.noiqnset:
            if special and special.has_key("IQN"):
                slave.setIQN(special["IQN"])
            elif not master.lungroup:
                slave.setIQN(self.lun.getInitiatorName(allocate=True))
        if self.multipathing:
            slave.enableMultipathing()

    def release(self):
        # This should handle unplugging etc itself...
        xenrt.TEC().logverbose("Releasing lun")
        self.lun.release()

class _IntegratedLUNPerVDIStorageRepository(StorageRepository):
    """Parent class for SRs using LUN-per-VDI but with intergrated
    management of the array."""

    CLEANUP = "destroy"
    SHARED = True

    def create(self,
               resource,
               physical_size=None,
               content_type="",
               options=None,
               multipathing=False):

        self.multipathing = multipathing
        if multipathing:
            self.host.enableMultipathing()

        self.resources["target"] = resource
        if not physical_size:
            if resource.size:
                physical_size = "%sGiB" % (resource.size)
            else:
                physical_size = xenrt.TEC().lookup(self.SIZEVAR, "50GiB")

        dconf = {}
        dconf["target"] = resource.target
        dconf["username"] = resource.username
        dconf["password"] = resource.password
        # Any options given in the form "parameter=value" are assumed to be
        # device-config arguments
        if options:
            dconf.update(xenrt.util.strlistToDict(options.split(","), keyonly=False))
        self.deviceConfig(resource, options, dconf)
        self._create(self.TYPENAME,
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type)

    def prepareSlave(self, master, slave, special=None):
        if self.multipathing:
            slave.enableMultipathing()

    def deviceConfig(self, resource, options, dconf):
        pass
    
    def check(self):
        StorageRepository.checkCommon(self, self.TYPENAME)


class NetAppStorageRepository(_IntegratedLUNPerVDIStorageRepository):
    """Models a NetApp SR"""

    TYPENAME = "netapp"
    SIZEVAR = "SR_NETAPP_SIZE"

    def deviceConfig(self, resource, options, dconf):
        dconf["aggregate"] = resource.aggr
        if options:
            o = string.split(options, ",")
            if "thin" in o:
                dconf["allocation"] = "thin"


class EQLStorageRepository(_IntegratedLUNPerVDIStorageRepository):
    """Models an EqualLogic SR"""

    TYPENAME = "equal"
    SIZEVAR = "SR_EQL_SIZE"
    
    def deviceConfig(self, resource, options, dconf):
        dconf["storagepool"] = resource.aggr
        if options:
            o = string.split(options, ",")
            if "thin" in o:
                dconf["allocation"] = "thin"


class HBAStorageRepository(StorageRepository):
    """Models a fiber channel or iSCSI via HBA SR"""

    CLEANUP = "destroy"
    SHARED = True
    THIN_PROV_KEYWORD = "xlvhd"

    def create(self,
               scsiid,
               physical_size="0",
               content_type="",
               multipathing=False,
               smconf={}):
        self.multipathing = multipathing
        if multipathing:
            device = "/dev/mapper/%s" % (scsiid)
            prepdevice = "/dev/disk/by-id/scsi-%s" % (scsiid)
            self.host.enableMultipathing()
        else:
            device = "/dev/disk/by-id/scsi-%s" % (scsiid)
            prepdevice = device
        try:
            blockdevice = self.host.execdom0("readlink -f %s" % prepdevice).strip()
            if len(blockdevice.split('/')) !=3:
                raise xenrt.XRTFailure("The block device %s is not detected by the host." % scsiid)

            self.host.execdom0("test -x /opt/xensource/bin/diskprep && /opt/xensource/bin/diskprep -f %s || dd if=/dev/zero of=%s bs=4096 count=10" % (blockdevice, blockdevice))

        except:
            xenrt.TEC().warning("Error erasing disk on %s" % (scsiid))
        
        dconf = {}
        dconf["device"] = device
        dconf["SCSIid"] = scsiid
        self._create("lvmohba",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type,
                     smconf=smconf)

    def check(self):
        StorageRepository.checkCommon(self, "lvmohba")
        # TODO check multipathing config

    def prepareSlave(self, master, slave, special=None):
        if self.multipathing:
            slave.enableMultipathing()

class FCOEStorageRepository(StorageRepository):
    """Models a fiber channel or iSCSI via HBA SR"""

    CLEANUP = "destroy"
    SHARED = True

    def create(self,
               scsiid,
               physical_size="0",
               content_type="",
               multipathing=False):
        self.multipathing = multipathing
        if multipathing:
            device = "/dev/mapper/%s" % (scsiid)
            prepdevice = "/dev/disk/by-id/scsi-%s" % (scsiid)
            self.host.enableMultipathing()
        else:
            device = "/dev/disk/by-id/scsi-%s" % (scsiid)
            prepdevice = device
        try:
            blockdevice = self.host.execdom0("readlink -f %s" % prepdevice).strip()
            if len(blockdevice.split('/')) !=3:
                raise xenrt.XRTFailure("The block device %s is not detected by the host." % scsiid)

            self.host.execdom0("test -x /opt/xensource/bin/diskprep && /opt/xensource/bin/diskprep -f %s || dd if=/dev/zero of=%s bs=4096 count=10" % (blockdevice, blockdevice))

        except:
            xenrt.TEC().warning("Error erasing disk on %s" % (scsiid))
        
        dconf = {}
        dconf["device"] = device
        dconf["SCSIid"] = scsiid
        self._create("lvmofcoe",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type)

    def check(self):
        StorageRepository.checkCommon(self, "lvmofcoe")
        # TODO check multipathing config

    def prepareSlave(self, master, slave, special=None):
        if self.multipathing:
            slave.enableMultipathing()
            
class FCStorageRepository(HBAStorageRepository):
    pass


class ISCSIHBAStorageRepository(HBAStorageRepository):
    pass


class SharedSASStorageRepository(HBAStorageRepository):
    pass


class RawHBAStorageRepository(HBAStorageRepository):
    """Models a fiber channel SR via HBA SR called RawHBA"""

    CLEANUP = "destroy"
    SHARED = True

    # Create the RAWHBA (LUN/VDI) SR on the host.
    def create(self,
               physical_size=None,
               content_type="",
               options=None,
               multipathing=False):
        dconf = {}
        self._create("rawhba",
                     dconf,
                     physical_size=physical_size,
                     content_type=content_type)

    def introduce(self):
        raise xenrt.XRTError("Not a a supported operation for RawHBA SR.")

    def destroy(self):
        """Destroy this SR."""
        raise xenrt.XRTError("Not supported for RawHBA SR.")
        # sr-forget should remove the SR from Xapi
        # sr-destroy presumably sr-destroy should fail

    def check(self):
        StorageRepository.checkCommon(self, "rawhba")
        # TODO check multipathing config

    def prepareSlave(self, master, slave, special=None):
        """Perform any actions on a slave before joining a pool that are needed to work with this SR type. Override if needed."""
        #if self.multipathing:
        #    slave.enableMultipathing()


class ISCSILun(xenrt.ISCSILun):
    """An iSCSI LUN from a central shared pool."""
    def __init__(self, minsize=10, ttype=None, hwtype=None, maxsize=1000000, params={}, jumbo=False, mpprdac=None, usewildcard=False):
        xenrt.ISCSILun.__init__(self,
                                minsize=minsize,
                                ttype=ttype,
                                hwtype=hwtype,
                                maxsize=maxsize,
                                params=params,
                                jumbo=jumbo,
                                mpprdac=mpprdac,
                                usewildcard=usewildcard)

    def setEnvTests(self, dict):
        """Populate an environment dictionary suitable for SM RT testing"""
        dict['IQN_INITIATOR_ID'] = self.getInitiatorName()
        dict['LISCSI_TARGET_IP'] = self.getServer()
        dict['LISCSI_TARGET_ID'] = self.getTargetName()
        dict['LISCSI_LUN_ID'] = "0"
        if self.scsiid:
            dict['LISCSI_ISCSI_ID'] = self.scsiid
        if self.chap:
            i, u, s = self.chap
            dict['IQN_INITIATOR_ID_CHAP'] = i
            dict['CHAP_USERNAME'] = u
            dict['CHAP_PASSWORD'] = s


class ISCSILunSpecified(xenrt.ISCSILunSpecified):
    """An iSCSI LUN we have explicitly provided to this test."""
    def __init__(self, confstring):
        xenrt.ISCSILunSpecified.__init__(self, confstring)

    def setEnvTests(self, dict):
        """Populate an environment dictionary suitable for SM RT testing"""
        dict['IQN_INITIATOR_ID'] = self.getInitiatorName()
        dict['LISCSI_TARGET_IP'] = self.getServer()
        dict['LISCSI_TARGET_ID'] = self.getTargetName()
        dict['LISCSI_LUN_ID'] = "0"
        if self.scsiid:
            dict['LISCSI_ISCSI_ID'] = self.scsiid


class NetAppTarget(xenrt.NetAppTarget):
    """A NetApp target from a central shared pool."""
    def __init__(self, minsize=10, maxsize=1000000):
        xenrt.NetAppTarget.__init__(self, minsize=minsize, maxsize=1000000)

    def setEnvTests(self, dict):
        """Populate an environment dictionary suitable for SM RT testing"""
        dict['NAPP_TARGET'] = self.getTarget()
        dict['NAPP_USER'] = self.getUsername()
        dict['NAPP_PASSWD'] = self.getPassword()
        dict['NAPP_AGGR'] = self.getAggr()
        dict['NAPP_SIZE'] = "%sGiB" % (self.getSize())


class EQLTarget(xenrt.EQLTarget):
    """An EqualLogic target from a central shared pool."""
    def __init__(self, minsize=10, maxsize=1000000):
        xenrt.EQLTarget.__init__(self, minsize=minsize, maxsize=1000000)

    def setEnvTests(self, dict):
        """Populate an environment dictionary suitable for SM RT testing"""
        dict['EQL_TARGET'] = self.getTarget()
        dict['EQL_USER'] = self.getUsername()
        dict['EQL_PASSWD'] = self.getPassword()
        dict['EQL_SPOOL'] = self.getAggr()

#############################################################################
