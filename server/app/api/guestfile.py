#!/usr/bin/python

from app.api import XenRTAPIPage
from server import PageFactory
import config

import time,string,os,re,traceback,subprocess,json

class XenRTGuestFile(XenRTAPIPage):
    def render(self):

        guest_ip = self.request.client_addr
        guest_mac = []
        try:
            arpdata = subprocess.check_output(["/usr/sbin/arp","-n"])
            for l in arpdata.splitlines():
                if l.startswith(guest_ip):
                    guest_mac.append(l.split()[2].replace(":","").lower())
                    break
        except:
            pass
        try:
            dhcpdata = json.loads(subprocess.check_output("%s/xenrtdhcpd/macforip.py %s" % (config.sharedir, guest_ip), shell=True))
            if dhcpdata:
                guest_mac.append(dhcpdata[0].replace(":","").lower())
        except:
            pass
        for h in self.request.headers.keys():
            if h.lower().startswith("x-rhn-provisioning-mac"):
                guest_mac.append(self.request.headers[h].split()[-1].replace(":","").lower())
        guest_fname = self.request.matchdict['filename']
        deadline = time.time() + 60

        # Form a path to find the guest file
        fname = "/local/scratch/guestfiles/%s/%s" % (guest_ip, guest_fname)

        while True:
            if os.path.exists(fname):
		        break
            found = False
            for m in guest_mac:
                gmfname = "/local/scratch/guestfiles/%s/%s" % (m, guest_fname)
                if os.path.exists(gmfname):
                    fname = gmfname
                    found = True
                    break
            if found:
                break
            if time.time() > deadline:
                return "Timed out waiting for guest preseed file"
            time.sleep(1)

        try:
            with open(fname) as f:
                data = f.read()
            with open("%s.stamp" % fname, "w") as f:
                f.write("access")
            return data
        except Exception, e:
            traceback.print_exc()
            return "ERROR Exception occurred, see error_log for details"

PageFactory(XenRTGuestFile, "/guestfile/{filename}")
