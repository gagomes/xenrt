from server import PageFactory
from app import XenRTPage
import config
import os, os.path

class XenRTSignal(XenRTPage):
    def render(self):
        form = self.request.params
        try:
            key = self.request.params['key']
        except:
            return "ERROR: No key specified\n"

        # While this script is intended to be used in a secure environment,
        # it doesn't hurt to prevent escaping the base working directory...
        keyDir = os.path.join(config.tmp_base, os.path.basename(key))

        if not os.path.isdir(keyDir):
            return "ERROR: Key directory does not exist"

        # Write the signal file
        sigPath = os.path.join(keyDir, ".xenrtsuccess")
        with open(sigPath, 'a'):
            os.utime(sigPath, None)

        return "OK"

PageFactory(XenRTSignal, "/signal")
