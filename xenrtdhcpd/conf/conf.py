#Copy this file to one of the following locations, then rename it to conf.py:
#/etc/staticDHCPd/, ./conf/

#For a full overview of what these parameters mean, and to further customise
#your system, please consult doc/configuration and doc/scripting

import json
import xenrtallocator

with open("xenrtdhcpd.cfg") as f:
    XENRT_CONFIG = json.load(f)



# Whether to daemonise on startup (you don't want this during initial setup)
DAEMON = True
DEBUG = True

#WARNING: The default UID and GID are those of root. THIS IS NOT GOOD!
#If testing, set them to your id, which you can find using `id` in a terminal.
#If going into production, if no standard exists in your environment, use the
#values of "nobody": `id nobody`
#The UID this server will use after initial setup
UID = 0
#The GID this server will use after initial setup
GID = 0
DATABASE_ENGINE=None
DHCP_INTERFACES = XENRT_CONFIG['interfaces'].keys()
#The databas-engine to use
#For details, see doc/configuration
PID_FILE='/var/run/xenrtdhcpd.pid'

Allocator = xenrtallocator.XenRTDHCPAllocator()


def handleUnknownMAC(packet, method, mac, client_ip, relay_ip, pxe, interface):
    return Allocator.getResponse(interface, mac, packet)
