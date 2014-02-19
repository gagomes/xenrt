#!/usr/bin/python

import os,tempfile,time

def runCmd(cmd, output=False):
    print "Executing %s" % cmd
    if not output:
        os.system(cmd)
    else:
        ret = os.popen(cmd).read()
        print ret
        return ret

host=None
password=None
bridge=None
ip=None
netmask=None
gateway=None
dns=None
site=None
size=None

if not host:
    host = raw_input("Enter hostname or IP for controller host: ")
if not password:
    password = raw_input("Enter Password for controller host: ")
if not bridge:
    bridge = raw_input("Enter network to install this controler onto (e.g. \"Network 0\"): ")
if not ip:
    ip = raw_input("Enter IP of controller: ")
if not netmask:
    netmask = raw_input("Enter Netmask for controller: ")
if not gateway:
    gateway = raw_input("Enter gateway for controller: ")
if not dns:
    dns = raw_input("Enter DNS server for controller: ")
if not site:
    site = raw_input("Enter XenRT site: ")
if not size:
    size = int(raw_input("Enter disk size (GB): "))



tempdir = tempfile.mkdtemp()

runCmd("sshpass -p %s scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no root@%s:/opt/xensource/bin/xe %s" % (password, host, tempdir))

xe = "%s/xe -s %s -u root -pw %s" % (tempdir, host, password)

vm = runCmd("%s vm-install new-name-label=\"XenRT Controller (%s)\" template=\"Debian Wheezy 7.0 (64-bit)\"" % (xe, site), output=True).strip()

vdi = runCmd("%s vbd-list vm-uuid=%s params=vdi-uuid --minimal" % (xe, vm), output=True).strip()

runCmd("%s vdi-resize uuid=%s disk-size=%dGiB" % (xe, vdi, size))

network = runCmd("%s network-list name-label=\"%s\" --minimal" % (xe, bridge), output=True).strip()

runCmd("%s vif-create vm-uuid=%s network-uuid=%s device=0" % (xe, vm, network))

runCmd("%s vm-param-set uuid=%s other-config-install-repository=\"http://linuxexport.xenrt.xs.citrite.net/xenrtdata/linux/distros/Debian/Wheezy/all/\"" % (xe, vm))

mirror = "ftp.us.debian.org"

if ip.startswith("10.80") or ip.startswith("10.81") or ip.startswith("10.70"):
    mirror = "ftp.uk.debian.org"

runCmd("%s vm-param-set uuid=%s PV-args=\"auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true hostname=%s-controller domain=xenrt.xs.citrite.net url=http://xenrt.hq.xensource.com/controller/debian70-64.cfg interface=eth0 netcfg/disable_autoconfig=true netcfg/disable_dhcp=true netcfg/get_nameservers=%s netcfg/get_ipaddress=%s netcfg/get_netmask=%s netcfg/get_gateway=%s netcfg/confirm_static=true mirror/http/hostname=%s\"" % (xe, vm, site, dns, ip, netmask, gateway, mirror))

runCmd("%s vm-start uuid=%s" % (xe, vm))

while True:
     if runCmd("%s vm-param-get uuid=%s param-name=power-state" % (xe, vm), output=True).strip() == "halted":
        break
     time.sleep(30)

runCmd("%s vm-start uuid=%s" % (xe, vm))

time.sleep(120)

runCmd("sshpass -p xensource ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no xenrtd@%s \"wget -O installxenrt.sh http://xenrt.hq.xensource.com/controller/installxenrt.sh && chmod a+x installxenrt.sh\"" % ip)



os.system("rm -rf %s" % tempdir)

print "Now login to the controller as xenrtd (password xensource) and run ~/installxenrt.sh %s" % site
