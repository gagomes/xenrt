def initialise_master_in_dom0(host):
    sftp = host.sftpClient()
    sftp.copyTo("/home/xenrtd/felipef/synexec_master", "/root/synexec_master")

def initialise_slave(slave):
    sftp = slave.sftpClient()
    sftp.copyTo("/home/xenrtd/felipef/synexec_slave", "/root/synexec_slave")

def start_slave(slave, jobid):
    slave.execguest("/root/synexec_slave -v -s %d >> /tmp/synexec.log &" % jobid)

def start_master_in_dom0(host, slaveCommand, jobid, numclients):
    # Disable firewall on DOM0 to allow synexec to communicate
    host.execdom0("iptables -F INPUT")

    # Write synexec master configuration file
    host.execdom0("echo \"%s\" > /root/synexec.conf" % slaveCommand)

    # Run synexec master
    host.execdom0("/root/synexec_master -v -s %d %d /root/synexec.conf 1>/root/synexec_master.log 2>&1" % (jobid, numclients))

def get_slave_log(slave):
    return slave.execguest("cat /tmp/synexec.out")

def get_master_log(host):
    return host.execdom0("cat /root/synexec_master.log")
