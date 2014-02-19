import libperf, xenrt

class TCEmpty (libperf.PerfTestCase):
    def __init__ (self):
        libperf.PerfTestCase.__init__ (self, self.__class__.__name__)

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Empty run body.")
