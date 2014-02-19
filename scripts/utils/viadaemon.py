#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# Communicate with a test execution daemon running on a guest
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xmlrpclib, sys, time, getopt, os.path, string
import bz2

def usage(fd):
    fd.write("""Usage: %s [options] <hostname/address> [commands]

    When run without options the commands are executed on the target and
    the output returned on stdout. Each command argument is placed on a
    separate line in a batch file. To run command lines with spaces enclose
    the entire command in quotes. E.g:

        %s 10.2.3.4 "dir c:\\"

    Options:

    -r             Reload the test execution daemon on the target
    -V             Query the version of the test execution daemon on the target
    -l             List XML-RPC methods available on the target

    -S             Shut down the target
    -R             Reboot the target

    -F <filename>  Fetch the remote file and output to stdout
    
    -L <localfilename> -F <remotefilename>   Copy a local file to the target
    -U <url> -F <remotefilename> Pull a file from a URL to the target
                   [-u] to treat as a tarball and unpack into <remotefilename>

    -a             Display some information about the target
    -P             Enable PAE on the target
    -T <seconds>   Sleep for the specifed period on the target
    -p <address>   Check reachability for another test daemon from the target

    -w <ref>       Return log data for process <ref>

    -A             Dump Active Directory users and groups
    
""" % (sys.argv[0], sys.argv[0]))

reload = False
version = False
list = False
shutdown = False
reboot = False
filename = None
filenamebz2 = None
localfilename = None
about = False
pae = False
sleep = None
debug = False
ping = None
logref = None
url = None
activedir = False
unpack = False
try:
    optlist, optargs = getopt.getopt(sys.argv[1:], 'rVlSRF:aPT:L:p:hw:B:U:Au')
    for argpair in optlist:
        (flag, value) = argpair
        if flag == "-r":
            reload = True
        elif flag == "-V":
            version = True
        elif flag == "-l":
            list = True
        elif flag == "-S":
            shutdown = True
        elif flag == "-R":
            reboot = True
        elif flag == "-F":
            filename = value
        elif flag == "-B":
            filenamebz2 = value
        elif flag == "-L":
            localfilename = value
        elif flag == '-a':
            about = True
        elif flag == '-P':
            pae = True
        elif flag == "-T":
            sleep = int(value)
        elif flag == "-p":
            ping = value
        elif flag == "-w":
            logref = value
        elif flag == "-U":
            url = value
        elif flag == "-A":
            activedir = True
        elif flag == "-u":
            unpack = True
        elif flag == "-h":
            usage(sys.stdout)
            sys.exit(1)
except getopt.GetoptError:
    sys.stderr.write("ERROR: Unknown argument exception\n")
    usage(sys.stderr)
    sys.exit(1)

s = xmlrpclib.Server('http://%s:8936' % (optargs[0]))

if version:
    print s.version()
    sys.exit(0)

if reload:
    f = file('%s/execdaemon.py' % (os.path.dirname(sys.argv[0])), "r")
    data = f.read()
    f.close()
    s.stopDaemon(data)
    time.sleep(5)
    s.isAlive()
    sys.exit(0)

if shutdown:
    s.shutdown()
    sys.exit(0)

if reboot:
    s.reboot()
    sys.exit(0)

if list:
    for m in s.system.listMethods():
        print m
    sys.exit(0)

if localfilename:
    f = file(localfilename, 'r')
    data = f.read()
    f.close()
    s.createFile(filename, xmlrpclib.Binary(data))
    sys.exit(0)

if filename and url:
    if unpack:
        s.unpackTarball(url, filename)
    else:
        s.fetchFile(url, filename)
    sys.exit(0)

if filename:
    sys.stdout.write(s.readFile(filename).data)
    sys.exit(0)

if filenamebz2:
    databz2 = s.readFileBZ2(filenamebz2).data
    #sys.stderr.write("Compressed size: %u\n" % (len(databz2)))
    data = bz2.decompress(databz2)
    #sys.stderr.write("Uncompressed size: %u\n" % (len(data)))
    sys.stdout.write(data)
    sys.exit(0)    

if about:
    print "Version: %u/%s" % (s.getVersion(), s.windowsVersion())
    print "Memory: %uMB" % (s.getMemory())
    print "CPUs: %u" % (s.getCPUs())
    print "VIFs: %s" % (s.getVIFs())
    print "Memory details:\n%s" % (s.getMemory(True))
    sys.exit(0)

if pae:
    s.addBootFlag("/PAE")
    sys.exit(0)

if sleep:
    s.sleep(sleep)
    sys.exit(0)

if ping:
    print s.checkOtherDaemon(ping)
    sys.exit(0)

if logref:
    print s.log(logref)
    rc = s.returncode(logref)
    sys.exit(rc)

if activedir:
    users = s.adGetAllSubjects("user")
    groups = s.adGetAllSubjects("group")
    usergroups = dict(s.adGetGroups("user", users))
    members = dict(s.adGetMembers(groups))
    for group in groups:
        print "Group %s" % (group)
        for member in members[group]:
            print "  %s" % (member)
    sys.exit(0)

ref = s.runbatch(string.join(optargs[1:], '\n').encode("utf-16").encode("uu"))
while True:
    st = s.poll(ref)
    if st == "DONE":
        break
    time.sleep(5)
print s.log(ref).encode("utf-8")
rc = s.returncode(ref)
s.cleanup(ref)
sys.exit(rc)

