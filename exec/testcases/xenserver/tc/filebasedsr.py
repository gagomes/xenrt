import xenrt
from xenrt import log, step, warning

class TCFileBasedSRProperty(xenrt.TestCase):
    """
    Check reported SR properties are correct with actual value.

    SR physical-size
    SR physical-utilization
    SR virtual-allocation
    VDI physical-utilization
    """

    def __getSRObj(self, rule):

        xsr = next((sr for sr in self.host.xapiObject.SRs if rule(sr)), None)

        if not xsr:
            raise xenrt.XRTError("Cannot find SR with given filter.")

        return xsr

    def getSRObjByName(self, name):
        """
        Find SR by name and return Object model instance.

        @param: name: string. Name of SR to find.

        @return: uuid of SR.
        """
        log("Finding SR of which name is %s" % name)

        return self.__getSRObj(lambda sr: sr.name == name)

    def getSRObjByUuid(self, uuid):
        """
        Find SR by UUID and return Object model instance.

        @param: uuid: string. UUID of SR to find.

        @return: uuid of SR.
        """
        log("Finding SR of which uuid is %s" % uuid)

        return self.__getSRObj(lambda sr: sr.uuid == uuid)

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        self.host = self.getDefaultHost()
        if "sr" in args and args["sr"]:
            self.xsr = self.getSRObjByName(args["sr"])
        elif self.tcsku:
            self.xsr = self.getSRObjByUuid(self.host.getSRs(self.tcsku)[0])
        else:
            self.xsr = self.getSRObjByUuid(self.host.getLocalSR())

        self.srPath = ""
        srtype = self.xsr.srType
        if srtype == "ext":
            self.srPath = "/run/sr-mount/%s" % self.xsr.uuid
        elif srtype == "btrfs" or srtype == "smapiv3local":
            pbds = self.xsr.PBDs
            if len(pbds) != 1:
                raise xenrt.XRTError("Expected 1 local storage. Found %d." % len(pbds))
            dconf = pbds[0].deviceConfig
            if "uri" not in dconf:
                raise xenrt.XRTError("PBD(%s) of BTRFS SR (%s) does not have uri in device config." % \
                    (pbds[0].uuid, self.xsr.uuid))
            self.srPath = "/run/sr-mount" + dconf["uri"][len("file://"):]
        elif srtype == "rawnfs" or srtype == "smapiv3shared":
            pbds = self.xsr.PBDs
            dconf = pbds[0].deviceConfig
            if "uri" not in dconf:
                raise xenrt.XRTError("PBD(%s) of RAWNFS SR (%s) does not have uri in device config." % \
                    (pbds[0].uuid, self.xsr.uuid))
            self.srPath = "/run/sr-mount/nfs/" + dconf["uri"][len("nfs://"):]
        else:
            raise xenrt.XRTError("Unexpected sr type: %s" % srtype)

    def getRawVDISize(self, vdi):
        """
        Find size of VDI and return it.

        @param: vdi: UUID of VDI to check.

        @return: size of VDI
        """

        try:
            filename = self.host.genParamGet("vdi", vdi, "location")
        except:
            warning("VDI %s does not have location property" % vdi)
            filename = vdi

        info = None
        try:
            info = eval(self.host.execdom0("cat %s/%s.json" % (self.srPath, filename)))
        except:
            warning("VDI %s does not have valid json file." % vdi)

        if info:
            log("VDI %s INFO: %s" % (vdi, str(info)))
            if "uuid" in info:
                if info["uuid"] != vdi:
                    raise xenrt.XRTError("JSON file of VDI %s includes wrong UUID info.")
            else:
                warning("JSON file of VDI %s does not have UUID field. Skipping sanity check." % vdi)

        try:
            lsstr = self.host.execdom0("ls -l %s/%s" % (self.srPath, filename))
        except:
            lsstr = self.host.execdom0("ls -l %s/%s.vhd" % (self.srPath, filename))

        return int(lsstr.split()[4])

    def getRawProperties(self):
        """
        From local SR, collect storage information and return information.

        @return: list of physical size, physical utilisation and accumlated virtual sizes of all VDIs in the SR.
        """
        host = self.host

        # Try search by uuid in local storage. If failed try check dev.
        dfoutput = host.execdom0("df -B 1 | grep '%s'" % self.srPath).split()

        rawPhysicalSize = int(dfoutput[1])
        rawPhysicalUtil = int(dfoutput[2])
        accumVirtualSize = 0
        accumVirtualSize = sum([vdi.size for vdi in self.xsr.VDIs])
        log("Current local status: physical size = %d, physical utilisation = %d, accumulated virtual size = %d" % \
            (rawPhysicalSize, rawPhysicalUtil, accumVirtualSize))

        return (rawPhysicalSize, rawPhysicalUtil, accumVirtualSize)

    def __verifyBasicProperties(self, checkPU=True):

        self.host.execdom0("xe sr-scan uuid=%s" % self.xsr.uuid)

        log("Collect local status.")
        rawStatus = self.getRawProperties()

        log("Verify basic properties.")
        physicalSize = self.xsr.physicalSize
        if rawStatus[0] != physicalSize:
            raise xenrt.XRTFailure("Physical Size mismatched. %s from df / %s in SR property." % (rawStatus[0], physicalSize))

        virtualAlloc = self.xsr.virtualAllocation
        if rawStatus[2] != virtualAlloc:
            raise xenrt.XRTFailure("Vitual allocation mismatched. %d from %d VDIs / %s in SR property." % (rawStatus[2], len(self.xsr.VDIs), virtualAlloc))

        if checkPU:
            physicalUtil = self.xsr.physicalUtilisation
            if rawStatus[1] != physicalUtil:
                raise xenrt.XRTFailure("Physical Utilisation mismatched. %d from df / %s in SR property." % (rawStatus[1], physicalUtil))

    def verifyInitialProperties(self):

        self.__verifyBasicProperties()

    def verifyAfterGuestInstalled(self):

        log("Creating a Linux VM to test.")
        self.guest = self.host.createGenericLinuxGuest(sr = self.xsr.uuid)

        self.__verifyBasicProperties(False)

        log("Verify physical utilisation increased.")
        physicalUtil = self.xsr.physicalUtilisation
        if physicalUtil - self.initialStatus[1] < 200 * xenrt.MEGA:
            raise xenrt.XRTFailure("Physical Utilisation has not increased as expected.")

        log("Verify vdi is used properly.")
        vdiAlloc = self.getRawVDISize(self.guest.xapiObject.VDIs[0].uuid)
        if vdiAlloc < 200 * xenrt.MEGA:
            raise xenrt.XRTFailure("VDI used less than expected. Expected at least 200MiB but only %d is in use." % vdiAlloc)

    def verifyAfterVDICreated(self):

        before = self.xsr.physicalUtilisation

        log("Creating an 20GiB VDI")
        self.vdi = self.host.createVDI(20 * xenrt.GIGA, self.xsr.uuid)

        self.__verifyBasicProperties(False)

        log("Verifying physical utilisation is increased less than 200 KiB")
        physicalUtil = self.xsr.physicalUtilisation
        if physicalUtil - before > 200 * xenrt.KILO:
            raise xenrt.XRTFailure("Physical utilisazion is increased more than 200KiB after empty VDI is creaed.")

        log("Verifying size of empty VDI is less than 200 KiB")
        if self.getRawVDISize(self.vdi) > 200 * xenrt.KILO:
            raise xenrt.XRTFailure("Empty VDI size is bigger than 200KiB")

    def verifyAfterVDIFilled(self):

        before = self.xsr.physicalUtilisation

        log("Attaching VDI to guest.")
        dev = self.guest.createDisk(vdiuuid=self.vdi, returnDevice=True)

        log("Fillig 1 GiB.")
        self.guest.execguest("dd if=/dev/urandom of=/dev/%s oflag=direct bs=1M count=1024" % dev)

        self.__verifyBasicProperties(False)

        log("Verifying physical utilisation is increased about 1 GiB")
        physicalUtil = self.xsr.physicalUtilisation
        if physicalUtil - before > xenrt.GIGA + 20 * xenrt.MEGA or physicalUtil - before < xenrt.GIGA - 20 * xenrt.MEGA:
            raise xenrt.XRTFailure("Physical utilisazion is different more than 20 MiB after 1 GiB writing.")

        log("Verifying raw file size is about 1 GiB.")
        vdiSize = self.getRawVDISize(self.vdi)
        if vdiSize > xenrt.GIGA + 20 * xenrt.MEGA or vdiSize < xenrt.GIGA - 20 * xenrt.MEGA:
            raise xenrt.XRTFailure("VDI size is different more than 20 MiB after 1 GiB filling.")

    def run(self, arglist=[]):

        log ("Using %s(%s) SR to test." % (self.xsr.name(), self.xsr.uuid))

        step("Store initial status of local disk.")
        self.initialStatus = self.getRawProperties()

        step("Verify initial status of SR")
        self.verifyInitialProperties()

        step("Verify status of SR after a linux VM is installed.")
        self.verifyAfterGuestInstalled()

        step("Verify status of SR after an empty VDI is created.")
        self.verifyAfterVDICreated()

        step("Verify status of SR after fill VDI.")
        self.verifyAfterVDIFilled()

    def postRun(self):
        self.guest.uninstall(True)
        super(TCFileBasedSRProperty, self).postRun()


class TCFileBasedSROperation(xenrt.TestCase):

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        srtype = "btrfs"
        if self.tcsku:
            srtype = self.tcsku

        self.host = self.getDefaultHost()
        sruuid = self.host.getSRs(srtype)[0]
        self.sr = xenrt.lib.xenserver.getStorageRepositoryClass(self.host, sruuid).fromExistingSR(self.host, sruuid)

    def run(self, arglist=None):

        log("Creating VDI.")
        vdi = self.host.createVDI(1 * xenrt.GIGA, self.sr.uuid).strip()

        log("Forget and introduce SR.")
        self.sr.forget()
        self.sr.introduce()

        log("Verify VDI is present.")
        if not vdi in self.sr.listVDIs():
            raise xenrt.XRTFailure("Reintroduced SR does not have the VDI before forget.")

        log("Distroying SR.")
        self.sr.destroy()
        if not self.sr.uuid in self.host.minimalList("sm-list"):
            raise xenrt.XRTFailure("SR info has been disappeared after destroying SR.")

