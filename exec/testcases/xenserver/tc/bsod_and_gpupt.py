import xenrt
from testcases.xenserver.tc import gpu
from xenrt.lib.xenserver import guest as guest_lib
from PIL import Image


class Windows81GPUPTCrashtest(xenrt.TestCase):

    def run(self, arglist):
        host = self.getDefaultHost()
        guest = host.createGenericWindowsGuest(distro='win81-x86')

        self.passThroughGPUTo(guest)

        domId = guest.getDomid()

        guest.crash()

        xenrt.sleep(30)

        logdir = xenrt.TEC().getLogdir()

        filename = logdir + '/actual-bsod.jpg'
        host.getVncSnapshot(domId, filename)
        image = Image.open(filename)

        if not guest_lib.isBSODBlue(image):
            raise xenrt.XRTFailure('The screenshot does not look like a BSOD')

    def passThroughGPUTo(self, guest):
        host = guest.getHost()

        guest.shutdown()

        gpuHelper = gpu.GPUHelper()
        gpuGroups = gpuHelper.getGPUGroups(host)
        gpuHelper.attachGPU(guest, gpuGroups[0])

        guest.start(specifyOn=True)

        guest.installNvidiaVGPUDriver(1)
