import string
import xenrt

def get_if_name_param():
    ifname = xenrt.TEC().lookup("IFNAME")
    if ifname:
        return " -i %s " % (ifname,)
    else:
        return ""

def _initialise(host, prog):
    workdir = string.strip(host.execcmd("mktemp -d /tmp/XXXXXX"))
    host.execcmd("wget -O - '%s/synexec.tgz' | tar -xz -C %s" %
                 (xenrt.TEC().lookup("TEST_TARBALL_BASE"), workdir))

    if host.execcmd("uname -m").strip() == "x86_64":
        host.execcmd("cp %s/synexec/%s.x86_64 /root/%s" % (workdir, prog, prog))
    else:
        host.execcmd("cp %s/synexec/%s.x86_32 /root/%s" % (workdir, prog, prog))
    host.execcmd("rm -rf %s" % workdir)

def initialise_master_in_dom0(host):
    _initialise(host, "synexec_master")

def initialise_slave(slave):
    _initialise(slave, "synexec_slave")

def start_slave(slave, jobid):
    slave.execguest("/root/synexec_slave -v -s %d >> /tmp/synexec.log &" % jobid)

def start_master_in_dom0(host, slaveCommand, jobid, numclients):
    # Disable firewall on DOM0 to allow synexec to communicate
    host.execdom0("iptables -F INPUT")

    # Write synexec master configuration file
    host.execdom0("echo \"%s\" > /root/synexec.conf" % slaveCommand)

    # Run synexec master
    host.execdom0("/root/synexec_master %s -v -s %d %d /root/synexec.conf 1>/root/synexec_master.log 2>&1" % (get_if_name_param(), jobid, numclients))

def get_slave_log(slave):
    return slave.execguest("cat /tmp/synexec.out")

def get_master_log(host):
    return host.execdom0("cat /root/synexec_master.log")
