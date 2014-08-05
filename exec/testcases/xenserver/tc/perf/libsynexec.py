import string
import os
import subprocess
import time
import xenrt

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

def start_slave(slave, jobid, port=None):
    port = " -p %d" % port if port else ""
    slave.execguest("/root/synexec_slave -v%s -s %d >> /tmp/synexec.log &" % (port, jobid))

def start_master_in_dom0(host, slaveCommand, jobid, numclients):
    # Disable firewall on DOM0 to allow synexec to communicate
    host.execdom0("iptables -F INPUT")

    # Write synexec master configuration file
    host.execdom0("echo \"%s\" > /root/synexec.conf" % slaveCommand)

    # Run synexec master
    host.execdom0("/root/synexec_master -v -s %d %d /root/synexec.conf 1>/root/synexec_master.log 2>&1" % (jobid, numclients))

def initialise_master_on_controller(jobid):
    workdir = "/tmp/synexec%d" % jobid
    os.mkdir(workdir)
    os.system("wget -O - '%s/synexec.tgz' | tar -xz -C %s" %
              (xenrt.TEC().lookup("TEST_TARBALL_BASE"), workdir))

    if subprocess.Popen(["uname", "-m"], stdout=subprocess.PIPE).communicate()[0].strip() == "x86_64":
        os.rename("%s/synexec/synexec_master.x86_64" % workdir,
                  "%s/synexec_master" % workdir)
    else:
        os.rename("%s/synexec/synexec_master.x86_32" % workdir,
                  "%s/synexec_master" % workdir)

def start_master_on_controller(slaveCommand, jobid, numclients):
    workdir = "/tmp/synexec%d" % jobid

    # Write synexec master configuration file
    conffile = "%s/synexec.conf" % workdir
    out = open(conffile, "w")
    out.write(slaveCommand)
    out.close()

    # Run synexec master
    port = 5165
    while port < 5300:
        p = subprocess.Popen("%s/synexec_master -v -s %d -p %d %d %s 1> %s/synexec_master.log 2>&1" %
                         (workdir, jobid, port, numclients, conffile, workdir), shell=True)
        time.sleep(1)
        if "Address already in use" not in get_master_log_on_controller(jobid):
            return (p, port)

        port += 1

    raise Exception("Could find free port to start master")

def get_slave_log(slave):
    return slave.execguest("cat /tmp/synexec.out")

def get_master_log(host):
    return host.execdom0("cat /root/synexec_master.log")

def get_master_log_on_controller(jobid):
    workdir = "/tmp/synexec%d" % jobid
    f = open("%s/synexec_master.log" % workdir, "r")
    data = f.read()
    f.close()
    return data
