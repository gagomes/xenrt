import xenrt, xenrt.lib.xenserver
import random

from xenrt.lazylog import log

class TCDEMUFuzzer(xenrt.TestCase):

    def isDEMUAlive(self):
        try:
            ret = self.host.execdom0(command="ps -ael | grep 'vgpu'", timeout=15).strip()
        except:
            return False
        return len(ret) > 0

    def startFuzzing(self, guest, seed = None):
        if not seed:
            seed = "%x" % random.randint(0, 0xffffffff)

        log("Starting Fuzzing with random seed: " + seed)
        self.host.xenstoreWrite("demufuzzer/randomseed", seed) # 1 is default. accpets unsigned long in C.
        # cannot use guest.start() as it run healthCheck, which will fail.
        self.host.getCLIInstance().execute("vm-start uuid=%s" % guest.getUUID())
        xenrt.sleep(10)

    def stopFuzzing(self, guest):
        log("Stopping fuzzing test.")
        # cannot use guest.shutdown().
        self.host.getCLIInstance().execute("vm-shutdown uuid=%s force=true" % guest.getUUID())
        xenrt.sleep(10)

    def prepare(self, arglist=None):
        """Do setup tasks in prepare"""

        log("Installing nVidia host driver.")
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host.installNVIDIAHostDrivers()

    def run(self, arglist=[]):
        """Do testing tasks in run"""

        # Read/initialize variables.
        args = xenrt.util.strlistToDict(arglist)
        iterations = args.get("iterations") or "0"
        logperiteration = args.get("logperiteration") or "1000"
        timeout = args.get("timeout") or "180"
        timeout = int(timeout)
        seed = args.get("seed") or "%x" % random.randint(0, 0xffffffff)

        modifier = xenrt.TEC().lookup("timeout", None)
        if modifier and modifier > 0:
            timeout = int(modifier)
            log("Using timeout from given submit command.")

        modifier = xenrt.TEC().lookup("seed", None)
        if modifier and modifier != "":
            seed = modifier
            log("Using seed from given submit command.")

        log("Create an empty guest with Windows 7 template")
        name = xenrt.randomGuestName()
        template = xenrt.lib.xenserver.getTemplate(self.host, "win7sp1")
        guest = self.host.guestFactory()(name, template, self.host)
        guest.setVCPUs(2)
        guest.setMemory(2048)
        guest.createGuestFromTemplate(template, None)

        log("Assign VGPU to the guest.")
        # Get a VGPU type
        vgputypes = self.host.minimalList("vgpu-type-list")
        vgputype = None
        for type in vgputypes:
            if self.host.genParamGet("vgpu-type", type, "model-name") != "passthrough":
                vgputype = type
                break
        if not vgputype:
            raise xenrt.XRTError("Cannot find relavant VGPU type.")
        log("VGPU type: %s" + vgputype)

        # Get a GPU Group.
        groups = self.host.minimalList("gpu-group-list")
        group = None
        for g in groups:
            if vgputype in self.host.genParamGet("gpu-group", g, "enabled-VGPU-types"):
                group = g
                break
        if not group:
            raise xenrt.XRTError("Cannot find a proper GPU group.")

        # Assign VGPU to the guest.
        cli = self.host.getCLIInstance()
        cli.execute("vgpu-create gpu-group-uuid=%s vgpu-type-uuid=%s vm-uuid=%s" % (group, vgputype, guest.getUUID()))

        log("Prepare Fuzzer")
        #Fetch File
        url = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "") + "/demufuzzer/demufuzzer-v1"
        remotepath = xenrt.TEC().getFile(url)
        try:
            xenrt.checkFileExists(remotepath)
        except:
            raise xenrt.XRTError("Failed to find demu fuzzer.")

        localpath = "/tmp/demufuzzer"
        sh = self.host.sftpClient()
        try:
            sh.copyTo(remotepath, localpath)
        finally:
            sh.close()
        # Replace HVM Loader with DEMU fuzzer.
        ret = self.host.execdom0("mv /usr/lib/xen/boot/hvmloader /usr/lib/xen/boot/hvmloader_orig")
        ret = self.host.execdom0("mv /tmp/demufuzzer /usr/lib/xen/boot/hvmloader")

        log("Setting up test variables.")
        log("iterations: %s" % iterations)
        log("log per iterations: %s" % logperiteration)
        log("Timeout: %d mins" % timeout)
        self.host.xenstoreWrite("demufuzzer/iterations", iterations) # 0 (infinity) is default.
        self.host.xenstoreWrite("demufuzzer/logperiteration", logperiteration) # 1000 is default.
        #self.host.xenstoreWrite("demufuzzer/logtoqemu", "1") # 1 is default.

        log("Start fuzzer!")
        self.startFuzzing(guest, seed)

        # capture DMESG
        self.host.execdom0("xl dmesg -c > /tmp/dmesg")
        self.host.addExtraLogFile("/tmp/dmesg")

        log("Wait for given time (%d mins) or until find a new issue" % timeout)
        targettime = xenrt.util.timenow() + timeout * 60
        while (xenrt.util.timenow() < targettime):
            self.host.execdom0("xl dmesg -c >> /tmp/dmesg")
            if not self.isDEMUAlive():
                log("DEMU is crashed.")
                try:
                    self.host.checkHealth()
                except xenrt.XRTException as e:
                    log("%s: %s happend." % (e, e.data))
                    raise xenrt.XRTFailure("Host is unhealty.")
                
                # If it is not a host crash, it is not security issue. Restarting.
                self.stopFuzzing(guest)
                self.startFuzzing(guest)
            else:
                xenrt.sleep(30)

        log("DEMU fuzzer ran for %d mins without Dom0 crash." % timeout)
