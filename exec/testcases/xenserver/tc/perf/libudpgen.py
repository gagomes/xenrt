import xenrt

def run_tx(host, destination, npkts=-1, size=-1):
    cmd = "/root/udptx"
    if npkts != -1:
        cmd += " -n %d" % npkts
    if size != -1:
        cmd += " -s %d" % size
    cmd += " " + destination

    return host.execcmd(cmd)

def run_rx(host, npkts=-1, size=-1, tolerance=-1, quiet=False):
    cmd = "/root/udprx"
    if npkts != -1:
        cmd += " -n %d" % npkts
    if size != -1:
        cmd += " -s %d" % size
    if tolerance != -1:
        cmd += " -t %d" % tolerance
    if quiet:
        cmd += " -q"
    cmd += " 2> /tmp/err"

    stdout = host.execcmd(cmd)
    stderr = host.execcmd("cat /tmp/err")

    return stdout, stderr
