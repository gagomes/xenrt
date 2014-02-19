import xenrt

class TCInstallXenCenter(xenrt.TestCase):
    def run(self, arglist=[]):
        guestname = xenrt.TEC().lookup("RESOURCE_HOST_0")
        container = xenrt.TEC().lookupHost(guestname, "CONTAINER_HOST")
        machine = xenrt.PhysicalHost(container)
        place = xenrt.GenericHost(machine)
        place.findPassword()
        place.checkVersion()
        host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
        place.populateSubclass(host)
        host.existing(doguests=False)
        guest = host.guestFactory()(guestname)
        guest.existing(host)
        guest.reservedIP = xenrt.TEC().lookupHost(guestname, "HOST_ADDRESS")
        guest.shutdown()
        snapUUID = host.minimalList("snapshot-list", "uuid", "snapshot-of=%s name-label=clean" % guest.uuid)[0]
        guest.revert(snapUUID)
        guest.start()
        guest.xmlrpcUnpackTarball("%s/sigcheck.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
        guest.xmlrpcExec("echo %s > c:\\winversion.txt" % guest.distro)
        guest.installCarbonWindowsGUI(forceFromCD=True)

