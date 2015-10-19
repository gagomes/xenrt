#!/usr/bin/python
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Main harness executable
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

import sys, string, os.path, atexit, getopt, time, os, traceback, re
import trace, socket, threading, xmlrpclib, glob, xml.dom.minidom, tarfile
import pydoc, copy, urllib, IPy, json
from SimpleXMLRPCServer import SimpleXMLRPCServer

socket.setdefaulttimeout(3600)

sys.path.append(os.path.dirname(sys.argv[0]))
sys.path.append("%s/lib" % (os.path.dirname(os.path.dirname(sys.argv[0]))))
sys.path.append("%s/tests/lib" % (os.path.dirname(os.path.dirname(sys.argv[0]))))
possible_paths = ["/usr/share/xenrt/lib",
                  "/usr/groups/xenrt/production/share/lib"]
for p in possible_paths:
    if os.path.exists(p):
        sys.path.append(p)

import xenrt, xenrt.lib.cloud, xenrt.lib.xenserver, xenrt.lib.oss, xenrt.lib.xl, xenrt.lib.generic, xenrt.lib.opsys, xenrt.lib.hyperv, xenrt.lib.oraclevm, xenrt.lib.nativewindows
try:
    import xenrt.lib.libvirt
    import xenrt.lib.kvm
    import xenrt.lib.esx
except Exception, e:
    sys.stderr.write("WARNING: Could not import libvirt classes: %s\n" % (e))
import localxenrt

#############################################################################
# Command line parsing.                                                     #
#############################################################################

def usage(fd):
    fd.write("""Usage: %s [options] [args]

    -h|--help                             Usage information (this message)

    Common options:

    -C|--changedir <dir>                  Change to this directory first
    -s|--sequence <filename>              Test sequence
    -c|--config <filename>                Configuration file
    -D variable=value                     Extra config variable

    Output control and debugging:

    -V|--verbose                          Verbose output on stderr
    --dump-config                         Dump config to stdout and exit
    --dump-sequence                       Dump test sequence tree and exit
    --redir <filename>                    Redirect stdout and stderr 
    --keep                                Do not delete working directories
    --pause-on-fail <testcase>            Pause on testcase failure (or "ALL")
    --pause-on-pass <testcase>            Pause on testcase pass (or "ALL")
    --email <address>                     Email address for notifications
    --perf-upload                         Upload perf data to database
    --quick-logs                          Don't run bugtool or vncsnapshot
    --no-logs                             Don't collect any host/VM logs
    --lookup <variable>                   Look up a variable in the config

    Common variables:

    --inputs <directory>                  Directory containing product
    -o|--arch <arch>                      Arch (e.g. x86-32, x86-32p, x86-64)
    --hvarch <arch>                       Hypervisor arch (if different)
    -R|--repo <URL>                       Source repository URL
    -r|--revision <rev>                   Revision of source to use
    --pq <URL>                            Patchqueue repository URL
    --pqpatch <patchname>                 Patchqueue apply-to patch name
    --pqrev <rev>                         Patchqueue repository revision
    -v|--version <version>                Product version
    --remote                              Pull files from remote site.

    Guest parameters:

    --distro <distribution>               Linux distro to use

    Run behaviour:

    --noprepare                           Don't run host prepare tests
    --nohostprepare                       Don't run host prepare tests
    --noinstall                           Don't run guest installation tests
    --skip <testname>                     Skip a test
    --skipsku <skuname>                   Skip a test SKU
    --skipgroup <groupname>               Skip a test group
    --skiptype <type>                     Skip a test type
    --run <testname>                      Run this test (implies skip others)
    --runsku <skuname>                    Run this sku (implies skip others)
    --rungroup <groupname>                Run this group (implies skip others)
    --no-finally                          Don't execute "finally" actions
    --no-postrun                          Don't execute "postRun" actions
    --priority <n>                        Run tests up to and including P<n>

    Resource allocation:

    -H|--host <hostname>[,<hostname>[,...]] Hosts to use. These become
                                          variables RESOURCE_HOST_0, etc.

    Single test case execution:

    -T|--testcase <tcid>                  Single test case to run
    -G|--guest <guest>[,<guest>[,...]]    Guest(s) to use
    -P|--pool <pool>[,<pool>[,...]]       Pool(s) to use
    --notailor                            Do not tailor VM for XenRT use
    --nopassword                          Do not try to find the password
    --existing <hostname>                 Interrogate an existing host
    --noplace                             Testcase doesn't run on a host/guest
    --testcasefiles <filename>            Use the test definitions in filename.    
    --runon                               Entity to run on.

    Suite operations:

    --run-suite <filename>                Submit test jobs for a suite
    -r|--revision <rev>                   Revision to test
    -b|--branch <branch>                  Branch to test
    --sku <filename>                      SKU definition file
    --delay-for <seconds>                 Amount to delay start of all jobs by
    -d                                    Debug mode for suite submit
    --dump-suite <filename>               Dump test suite config and exit
    --list-suite-tcs <filename>           List TCs in suite and exit
    --check-suite <filename>              Check test suite config and exit
    --fix-suite <filename>                Fix suite links in JIRA and exit
    --suite-seqs <list>                   Comma separated list of sequence
                                          tags to run
    --rerun                               Force a rerun of part of a suite
    --rerun-all                           Force a rerun of a suite
    --rerun-if-needed                     Rerun a suite if needed
    --suite-tcs <list>                    Comma separated list of TCs to
                                          run (use with --rerun)
    --devrun                              Run the suite as a development run

    Maintenance operations:

    --sanity-check                        Run a sanity check to verify basic XenRT operation
    --make-configs                        Make server config files
    --make-machines                       Make all machine config files for this site
    --make-machine <machine>              Make a single machine config files
    --switch-config <machine>             Make switch config for a machine
    --shell                               Open an interactive shell
    --shell-logs                          Open an interactive shell with logs
    --ishell-logs                         Open an interactive ipython shell with logs
    --replay-db                           Replays failed database uploads
    --cleanup-filecache                   Cleanup the shared file cache
    --remove-filecache <file>             Remove a file from the cache
    --list-locks                          List all known shared resources and
                                          locking statuses
    --cleanup-locks                       Remove any left over locks from
                                          killed/crashed jobs
    --cleanup-temp-dirs <job>             Remove any left over temporary directories from a specified job
    --cleanup-nfs-dirs                    Remove any left over NFS directories from stale jobs
    --cleanup-nfs-dir                     Remove a specific NFS directory
    --release-lock <id>                   Force release a resource lock
    --setup-net-peer <peer>               Set up the specified network test peer
    --setup-router                        Set up the software router for this site (IPv6)
    --setup-shared-host <host>            Set up the specified shared host
    --poweroff <machine>                  Power off a machine
    --poweron <machine>                   Power on a machine
    --powercycle <machine>                Power cycle a machine
    --bootdev <device>                    When power cycling, boot a machine with a specific target (e.g. "bios")
    --nmi <machine>                       Sent NMI to a machine
    --powerstatus <machine>               Get power status for a machine
    --mconfig <machine>                   See XML config for a machine
    --bootdiskless <machine>              Boot a machine into diskless Linux
    --bootwinpe <machine>                 Boot a machine into WinPE
    --run-tool function(args)             Run a tool from xenrt.tools
    --show-network                        Display site network details
    --show-network6                       Display site IPv6 network details

    --setup-static-host <host>            Setup a Static (Xen-On-Xen/Static Windows Guests) host
    --setup-static-guest <guest>          Setup a Static Windows Guest
    --max-age <seconds>                   Only refresh a guest if it is older than <seconds>

    --install-packages                    Install packages required for a job

    --get-resource "<machine> <type> <args>"        Get a controller resource (NFS, IP address range)
    --list-resources <machine>            List resources associated with a machine

""" % (sys.argv[0]))

# Parse command line
debian = False
seqfile = None
seqdump = False
confdump = False
tcfile = None
testcase = None
optargs = []
setvars = []
verbose = False
configfiles = []
tailor = True
password = True
skip = []
skipgroup = []
skipsku = []
skiptype = []
run = []
runsku = []
rungroup = []
traceon = False
redir = False
existing = False
aux = False
sanitycheck = False
makeconfigs = False
makemachines = False
makemachine = None
switchconfig = False
doshell = False
shelllogging = False
prio = None
remote = False
updatewindows = False
perfcheck = []
noplace = False
replaydb = False
cleanupfilecache = False
removefilecache = None
docgen = False
lookupvar = None
listlocks = False
cleanuplocks = False
cleanuptempdirs = False
cleanuptempdirsjob = None
cleanupnfsdirs = False
cleanupnfsdir = None
releaselock = None
setupnetpeer = False
setuprouter = False
netpeer = None
installhost = False
installlinux = False
setupsharedhost = False
sharedhost = None
setupstatichost = False
setupstaticguest = False
staticguest = None
cleanupsharedhosts = False
cleanupvcenter = False
powercontrol = False
powerhost = None
poweroperation = None
bootdev = None
bootdiskless = False
boothost = None
bootwinpe = None
ro = None
dumpsuite = None
listsuitetcs = None
checksuite = None
fixsuite = None
runsuite = None
suitedebug = False
suitedevrun = False
skufile = None
delayfor = 0
runtool = None
shownetwork = False
shownetwork6 = False
forcepdu = False
knownissuelist = None
knownissuesadd = []
knownissuesdel = []
historyfile = os.path.expanduser("~/.xenrt_history")
noloadmachines = False
mconfig = None
installguest = None
installpackages = False
getresource = None
listresources = None

try:
    optlist, optargs = getopt.getopt(sys.argv[1:],
                                     'Vqc:D:s:hH:j:T:o:R:r:C:G:v:P:db:',
                                     ['verbose',
                                      'dump-config',
                                      'dump-sequence',
                                      'config=',
                                      'sequence=',
                                      'help',
                                      'host=',
                                      'existing=',
                                      'guest=',
                                      'jobid=',
                                      'testcase=',
                                      'arch=',
                                      'hvarch=',
                                      'repo=',
                                      'revision=',
                                      'branch=',
                                      'pq=',
                                      'pqrev=',
                                      'pqpatch=',
                                      'debian',
                                      'version=',
                                      'noprepare',
                                      'nohostprepare',
                                      'noinstall',
                                      'changedir=',
                                      'notailor',
                                      'nopassword',
                                      'skip=',
                                      'skipsku=',
                                      'skipgroup=',
                                      'skiptype=',
                                      'run=',
                                      'runsku=',
                                      'rungroup=',
                                      'distro=',
                                      'trace',
                                      'redir',
                                      'keep',
                                      'testcasefiles=',
                                      'remote',
                                      'no-finally',
                                      'no-postrun',
                                      'quick-logs',
                                      'no-logs',
                                      'pause-on-fail=',
                                      'pause-on-pass=',
                                      'email=',
                                      'sanity-check',
                                      'make-configs',
                                      'make-machines',
                                      'make-machine=',
                                      'switch-config',
                                      'shell',
                                      'shell-logs',
                                      'ishell-logs',
                                      'priority=',
                                      'perf-upload',
                                      'pool=',
                                      'perf-check=',
                                      'noplace',
                                      'replay-db',
                                      'devrun',
                                      'cleanup-filecache',
                                      'remove-filecache=',
                                      'generate-docs',
                                      'lookup=',
                                      'inputs=',
                                      'list-locks',
                                      'cleanup-locks',
                                      'cleanup-temp-dirs=',
                                      'cleanup-nfs-dirs',
                                      'cleanup-nfs-dir=',
                                      'release-lock=',
                                      'setup-net-peer=',
                                      'setup-router',
                                      'setup-shared-host=',
                                      'setup-static-host=',
                                      'setup-static-guest=',
                                      'max-age=',
                                      'install-host=',
                                      'install-linux=',
                                      'install-guest=',
                                      'cleanup-shared-hosts',
                                      'cleanup-vcenter',
                                      'poweroff=',
                                      'poweron=',
                                      'powercycle=',
                                      'bootdev=',
                                      'nmi=',
                                      'powerstatus=',
                                      'mconfig=',
                                      'bootdiskless=',
                                      'bootwinpe=',
                                      'perf-data=',
                                      'runon=',
                                      'check-suite=',
                                      'fix-suite=',
                                      'dump-suite=',
                                      'list-suite-tcs=',
                                      'run-suite=',
                                      'suite-seqs=',
                                      'suite-tcs=',
                                      'testrun=',
                                      'rerun',
                                      'rerun-all',
                                      'rerun-if-needed',
                                      'sku=',
                                      'delay-for=',
                                      'run-tool=',
                                      'show-network',
                                      'show-network6',
                                      'pdu',
                                      'install-packages',
                                      'get-resource=',
                                      'list-resources='])
    for argpair in optlist:
        (flag, value) = argpair
        if flag == "--runon":
            ro = value
        elif flag in ("-V", "--verbose"):
            verbose = True
        elif flag == "--dump-config":
            confdump = True
            aux = True
        elif flag == "--dump-sequence":
            seqdump = True
        elif flag == "--remote":
            remote = True
        elif flag in ("-c", "--config"):
            configfiles.append(value)
        elif flag == "-D":
            try:
                var, varval = string.split(value, "=", 1)
                r = re.search(r"^SKIP_(\S+)", var)
                if r:
                    if varval == "yes":
                        skip.append(r.group(1))
                        continue
                r = re.search(r"^SKIPSKU_(\S+)", var)
                if r:
                    if varval == "yes":
                        skipsku.append(r.group(1))
                        continue
                r = re.search(r"^SKIPGROUP_(\S+)", var)
                if r:
                    if varval == "yes":
                        skipgroup.append(r.group(1))
                        continue
                r = re.search(r"^SKIPG_(\S+)", var)
                if r:
                    if varval == "yes":
                        skipgroup.append(r.group(1))
                        continue
                r = re.search(r"^SKIPTYPE_(\S+)", var)
                if r:
                    if varval == "yes":
                        skiptype.append(r.group(1))
                        continue
                r = re.search(r"^SKIPT_(\S+)", var)
                if r:
                    if varval == "yes":
                        skiptype.append(r.group(1))
                        continue
                r = re.search(r"^RUN_(\S+)", var)
                if r:
                    if varval == "yes":
                        run.append(r.group(1))
                        continue
                r = re.search(r"^RUNSKU_(\S+)", var)
                if r:
                    if varval == "yes":
                        runsku.append(r.group(1))
                        continue
                r = re.search(r"^RUNGROUP_(\S+)", var)
                if r:
                    if varval == "yes":
                        rungroup.append(r.group(1))
                        continue
                r = re.search(r"^RUNG_(\S+)", var)
                if r:
                    if varval == "yes":
                        rungroup.append(r.group(1))
                        continue
                r = re.search(r"^POF_(\S+)", var)
                if r:
                    if varval == "yes":
                        setvars.append((["CLIOPTIONS",
                                         "PAUSE_ON_FAIL",
                                         r.group(1)], True))
                        continue
                r = re.search(r"^POP_(\S+)", var)
                if r:
                    if varval == "yes":
                        setvars.append((["CLIOPTIONS",
                                         "PAUSE_ON_PASS",
                                         r.group(1)], True))
                        continue
                if var == "PRIORITY":
                    prio = int(varval)
                    continue
                if var == "KNOWN_ISSUES":
                    knownissuelist = varval
                    continue
                r = re.search(r"KNOWN_([A-Z]+)(?:|-)(\d+)", var)
                if r:
                    if varval[0].lower() in ("y", "t", "1"):
                        knownissuesadd.append("%s-%s" %
                                              (r.group(1), r.group(2)))
                    else:
                        knownissuesdel.append("%s-%s" %
                                              (r.group(1), r.group(2)))
                    continue
                varparts = string.split(var, "/")
                varval = urllib.unquote(varval)
                if len(varparts) == 1:
                    setvars.append((var, varval))
                else:
                    setvars.append((varparts, varval))
            except:
                sys.stderr.write("Error parsing -D variable '%s'\n" %
                                 (value))
                sys.exit(1)
        elif flag in ("-s", "--sequence"):
            seqfile = value
        elif flag == "--testcasefiles":
            tcfile = value
        elif flag in ('-h', '--help'):
            usage(sys.stdout)
            sys.exit(0)
        elif flag in ('-H', '--host'):
            c = 0
            for h in string.split(value, ","):
                setvars.append(("RESOURCE_HOST_%u" % (c), h))
                c = c + 1
        elif flag in ('-P', '--pool'):
            existing = True
            c = 0
            for h in string.split(value, ","):
                setvars.append(("RESOURCE_POOL_%u" % (c), h))
                setvars.append(("RESOURCE_HOST_%u" % (c), h))
                c = c + 1
        elif flag == "--existing":
            existing = True
            c = 0
            for h in string.split(value, ","):
                setvars.append(("RESOURCE_HOST_%u" % (c), h))
                c = c + 1            
        elif flag in ('-G', '--guest'):
            c = 0
            for h in string.split(value, ","):
                setvars.append(("RESOURCE_GUEST_%u" % (c), h))
                c = c + 1
        elif flag in ('-j', '--jobid'):
            setvars.append(("JOBID", value))
        elif flag in ('-T', '--testcase'):
            testcase = value
            setvars.append(("SINGLE_TESTCASE_MODE", True))
        elif flag in ('-o', '--arch'):
            setvars.append((["CLIOPTIONS", "ARCH"], value))
        elif flag in ('-o', '--hvarch'):
            setvars.append((["CLIOPTIONS", "HYPERVISOR_ARCH"], value))
        elif flag in ('-R', '--repo'):
            setvars.append((["CLIOPTIONS", "REPO"], value))
        elif flag in ('-r', '--revision'):
            setvars.append((["CLIOPTIONS", "REVISION"], value))
            if "-" in value:
                setvars.append((["CLIOPTIONS", "BUILD"], value.split("-")[1]))
        elif flag in ('-b', '--branch'):
            setvars.append((["CLIOPTIONS", "BRANCH"], value))
        elif flag == "--pq":
            setvars.append((["CLIOPTIONS", "PATCHQUEUE"], value))
        elif flag == "--pqrev":
            setvars.append((["CLIOPTIONS", "PATCHQUEUE_REV"], value))
        elif flag == "--pqpatch":
            setvars.append((["CLIOPTIONS", "PQ_PATCH"], value))
        elif flag in ('-v', '--version'):
            setvars.append((["CLIOPTIONS", "VERSION"], value))
        elif flag == "--quick-logs":
            setvars.append(("QUICKLOGS", True))
        elif flag == "--no-logs":
            setvars.append(("NOLOGS", True))
        elif flag == "--noprepare":
            setvars.append((["CLIOPTIONS", "NOPREPARE"], True))
        elif flag == "--nohostprepare":
            setvars.append((["CLIOPTIONS", "NOHOSTPREPARE"], True))
        elif flag == "--debian":
            debian = True
        elif flag == "--noinstall":
            setvars.append((["CLIOPTIONS", "NOINSTALL"], True))
        elif flag in ('-C', '--changedir'):
            os.chdir(value)
        elif flag == "--notailor":
            tailor = False
        elif flag == "--nopassword":
            password = False
        elif flag == "--skip":
            skip.append(value)
        elif flag == "--skipsku":
            skipsku.append(value)
        elif flag == "--skipgroup":
            skipgroup.append(value)
        elif flag == "--skiptype":
            skiptype.append(value)
        elif flag == "--run":
            run.append(value)
        elif flag == "--runsku":
            runsku.append(value)
        elif flag == "--rungroup":
            rungroup.append(value)
        elif flag == "--distro":
            setvars.append(("DEFAULT_GUEST_DISTRO", value))
        elif flag == "--trace":
            traceon = True
        elif flag == "--redir":
            redir = True
        elif flag == "--keep":
            setvars.append(("KEEP_WORKING_DIRS", True))
        elif flag == "--no-finally":
            setvars.append((["CLIOPTIONS", "NOFINALLY"], True))
        elif flag == "--no-postrun":
            setvars.append((["CLIOPTIONS", "NOPOSTRUN"], True))
        elif flag == "--pause-on-fail":
            setvars.append((["CLIOPTIONS", "PAUSE_ON_FAIL", value], True))
        elif flag == "--pause-on-pass":
            setvars.append((["CLIOPTIONS", "PAUSE_ON_PASS", value], True))
        elif flag == "--email":
            setvars.append(("EMAIL", value))
        elif flag == "--sanity-check":
            sanitycheck = True
            aux = True
        elif flag == "--make-configs":
            makeconfigs = True
            aux = True
        elif flag == "--make-machines":
            makemachines = True
            noloadmachines = True
            aux = True
        elif flag == "--make-machine":
            makemachine = value
            noloadmachines = True
            aux = True
        elif flag == "--switch-config":
            switchconfig = True
            aux = True
        elif flag == "--shell":
            doshell = True
            aux = True
            setvars.append(("NO_HOST_POWEROFF", "yes"))
        elif flag == "--shell-logs":
            doshell = True
            shelllogging = True
            aux = True
            setvars.append(("NO_HOST_POWEROFF", "yes"))
        elif flag == "--ishell-logs":
            doshell = "ipython"
            shelllogging = True
            aux = True
            setvars.append(("NO_HOST_POWEROFF", "yes"))
        elif flag == "--priority":
            prio = int(value)
        elif flag == "--perf-upload":
            setvars.append(("PERF_UPLOAD", True))
        elif flag == "--perf-check":
            l = string.split(value, ",")
            if len(l) != 4:
                sys.stderr.write("ERROR: badly formed perf-check: %s\n" %
                                 (value))
                usage(sys.stderr)
                sys.exit(1)
            try:
                perfcheck.append((l[0], l[1], float(l[2]), float(l[3])))
            except:
                sys.stderr.write("ERROR: badly formed perf-check: %s\n" %
                                 (value))
                usage(sys.stderr)
                sys.exit(1)
        elif flag == "--noplace":
            noplace = True
        elif flag == "--replay-db":
            replaydb = True
            aux = True
        elif flag == "--cleanup-filecache":
            cleanupfilecache = True
            aux = True
        elif flag == "--remove-filecache":
            removefilecache = value
            verbose=True
            aux = True
        elif flag == "--generate-docs":
            docgen = True
            aux = True
        elif flag == "--lookup":
            lookupvar = value
            aux = True
        elif flag == "--inputs":
            setvars.append(("INPUTDIR", value))
        elif flag == "--perf-data":
            setvars.append(("PERFDATAFILE", value))
        elif flag == "--list-locks":
            listlocks = True
            aux = True
        elif flag == "--cleanup-locks":
            cleanuplocks = True
            aux = True
        elif flag == "--cleanup-temp-dirs":
            cleanuptempdirs = True
            cleanuptempdirsjob = value
            aux = True
        elif flag == "--cleanup-nfs-dirs":
            cleanupnfsdirs = True
            aux = True
        elif flag == "--cleanup-nfs-dir":
            cleanupnfsdir = value
            aux = True
        elif flag == "--release-lock":
            releaselock = value
            aux = True
        elif flag == "--setup-net-peer":
            setupnetpeer = True
            netpeer = value
            aux = True
        elif flag == "--setup-router":
            setuprouter = True
            aux = True
        elif flag == "--setup-shared-host":
            setvars.append(("INPUTDIR", "/"))
            remote = True
            setupsharedhost = True
            sharedhost = value
            aux = True
        elif flag == "--setup-static-host":
            setvars.append(("INPUTDIR", "/"))
            remote = True
            setupstatichost = True
            setvars.append(("RESOURCE_HOST_0", value))
            verbose = True
            aux = True
        elif flag == "--setup-static-guest":
            remote = True
            setupstaticguest = True
            staticguest = value
            verbose = True
            aux = True
        elif flag == "--max-age":
            setvars.append(("MAX_GUEST_AGE", int(value)))
        elif flag == "--install-host":
            remote = True
            installhost = True
            setvars.append(("RESOURCE_HOST_0", value))
            verbose = True
            aux = True
        elif flag == "--install-linux":
            remote = True
            installlinux = True
            setvars.append(("RESOURCE_HOST_0", value))
            verbose = True
            aux = True
        elif flag == "--install-guest":
            remote = True
            installguest = value
            verbose = True
            aux = True
        elif flag == "--cleanup-vcenter":
            cleanupvcenter = True
            aux = True
        elif flag == "--cleanup-shared-hosts":
            cleanupsharedhosts = True
            aux = True
        elif flag == "--poweroff":
            powercontrol = True
            powerhost = value
            poweroperation = "off"
            aux = True
        elif flag == "--poweron":
            powercontrol = True
            powerhost = value
            poweroperation = "on"
            aux = True
        elif flag == "--powercycle":
            powercontrol = True
            powerhost = value
            poweroperation = "cycle"
            aux = True
        elif flag == "--bootdev":
            bootdev = value 
            aux = True
        elif flag == "--nmi":
            powercontrol = True
            powerhost = value
            poweroperation = "nmi"
            aux = True
        elif flag == "--powerstatus":
            powercontrol = True
            powerhost = value
            poweroperation = "status"
            aux = True
        elif flag == "--mconfig":
            mconfig = value
            aux = True
        elif flag == "--pdu":
            forcepdu = True
        elif flag == "--bootdiskless":
            bootdiskless = True
            boothost = value
            aux = True
            verbose = True
        elif flag == "--bootwinpe":
            bootwinpe = value
            aux = True
            verbose = True
        elif flag == "--dump-suite":
            dumpsuite = value
            aux = True
        elif flag == "--check-suite":
            checksuite = value
            aux = True
        elif flag == "--list-suite-tcs":
            listsuitetcs = value
            aux = True
        elif flag == "--fix-suite":
            fixsuite = value
            aux = True
        elif flag == "--run-suite":
            runsuite = value
            aux = True
        elif flag == "-d":
            suitedebug = True
        elif flag == "--devrun":
            suitedevrun = True
        elif flag == "--suite-seqs":
            setvars.append((["CLIOPTIONS", "SUITE_SEQS"], value))
        elif flag == "--suite-tcs":
            setvars.append((["CLIOPTIONS", "SUITE_TCS"], value))
        elif flag == "--testrun":
            setvars.append((["CLIOPTIONS", "SUITE_TESTRUN"], value))
        elif flag == "--rerun":
            setvars.append((["CLIOPTIONS", "SUITE_TESTRUN_RERUN"], True))
        elif flag == "--rerun-if-needed":
            setvars.append((["CLIOPTIONS", "SUITE_TESTRUN_RERUN_IF_NEEDED"], True))
        elif flag == "--rerun-all":
            setvars.append((["CLIOPTIONS", "SUITE_TESTRUN_RERUN"], True))
            setvars.append((["CLIOPTIONS", "SUITE_TESTRUN_RERUN_ALL"], True))
        elif flag == "--sku":
            skufile = value
        elif flag == "--delay-for":
            delayfor = int(value)
        elif flag == "--run-tool":
            runtool = value
            aux = True
        elif flag == "--show-network":
            shownetwork = True
            shownetwork6 = False
            aux = True
        elif flag == "--show-network6":
            shownetwork = True
            shownetwork6 = True
            aux = True
        elif flag == "--install-packages":
            installpackages = True
            noloadmachines = True
            aux = True
        elif flag == "--get-resource":
            getresource = value
            noloadmachines = True
            setvars.append((["OPTION_KEEP_SETUP"], "yes"))
            aux = True
        elif flag == "--list-resources":
            listresources = value
            noloadmachines = True
            aux = True
            
except getopt.GetoptError:
    sys.stderr.write("ERROR: Unknown argument exception\n")
    usage(sys.stderr)
    sys.exit(1)

if redir:
    sys.stdout = file("harness.out", 'a')
    # unbuffered output
    # alternative: try buffering=1 for line buffering, if unbuffered is too slow, but you still want to follow harness.err with tail -f
    sys.stderr = file("harness.err", 'a', buffering=1)

    def logUncaughtExceptions(type, value, tback):
        try:
            xenrt.GEC().harnessError()
            xenrt.TEC().logverbose(''.join(traceback.format_tb(tback)))
            xenrt.GEC().dbconnect.jobUpdate("PREPARE_FAILED", str(value).replace("\n", ",")[:250])
        except:
            pass
        sys.__excepthook__(type, value, tback)

    sys.excepthook = logUncaughtExceptions

if not testcase and not seqfile and not aux:
    sys.stderr.write("ERROR: No test sequence defined\n")
    usage(sys.stderr)
    sys.exit(1)

#############################################################################
# Read configuration.                                                       #
#############################################################################

# Set up global state and config
config = xenrt.Config()
if aux and not shelllogging:
    config.nologging = True

# Read in JSON config data
for cf in glob.glob("%s/data/config/*.json" % (localxenrt.SHAREDIR)):
    config.readFromJSONFile(cf)

def readConfigDir(directory):
    global config
    for cf in glob.glob("%s/*.xml" % (directory)):
        config.readFromFile(cf)
    for cfd in glob.glob("%s/*.d" % (directory)):
        readConfigDir(cfd)
    
# Look for site/local default configs
config.setVariable("XENRT_BASE", localxenrt.SHAREDIR)
config.setVariable("XENRT_CONF", localxenrt.CONFDIR)
cf = config.lookup("SITE_CONFIG", None)
if cf:
    if os.path.exists(cf):
        config.readFromFile(cf)
cfd = config.lookup("SITE_CONFIG_DIR", None)
if cfd:
    readConfigDir(cfd)
vcf = config.lookup("XENRT_VERSION_CONFIG", None)
if vcf:
    try:
        f = file(vcf, "r")
        v = f.read().strip().replace("\n",",")
        f.close()
        config.setVariable("XENRT_VERSION", v)
    except:
        pass

if verbose:
    config.setVerbose()

for cf in configfiles:
    config.readFromFile(cf)
for sv in setvars:
    var, value = sv
    config.setVariable(var, value)
config.setSecondaryVariables()

gec = xenrt.GlobalExecutionContext(config=config)

for f in skip:
    gec.skipTest(f)
for f in skipsku:
    gec.skipSku(f)
for f in skipgroup:
    gec.skipGroup(f)
for f in skiptype:
    gec.skipType(f)
for f in run:
    gec.noSkipTest(f)
for f in runsku:
    gec.noSkipSku(f)
for f in rungroup:
    gec.noSkipGroup(f)
if prio != None:
    gec.setPriority(prio)
if len(run) > 0 or len(rungroup) > 0 or len(runsku) > 0:
    if config.lookup("SKIPALL", None) == None:
        config.setVariable("SKIPALL", True)
if knownissuelist:
    gec.addKnownIssueList(knownissuelist)
for ki in knownissuesadd:
    gec.addKnownIssue(ki)
for ki in knownissuesdel:
    gec.removeKnownIssue(ki)
for f in perfcheck:
    tc, metric, min, max = f
    gec.perfCheck(tc, metric, min, max)

machines = []
for machine in config.lookup("HOST_CONFIGS", {}).keys():
    machines.append(machine)

if not noloadmachines:
    # Read in all machine config files
    hcfbase = config.lookup("MACHINE_CONFIGS", None)
    if not hcfbase:
        sys.stderr.write("Could not find machine config directory.\n")
        sys.exit(1)
    files = glob.glob("%s/*.xml" % (hcfbase))
    files.extend(glob.glob("%s/*.xml.hidden" % (hcfbase)))
    for filename in files:
        r = re.search(r"%s/(.*)\.xml" % (hcfbase), filename)
        if r:
            machine = r.group(1)
            if not machine in machines:
                machines.append(machine)
            try:
                config.readFromFile(filename, path=["HOST_CONFIGS", machine])
            except:
                sys.stderr.write("Warning: Could not read from %s\n" % filename)

# Populate the knownissues list with any issues specified in config files
for var, varval in config.getWithPrefix("KNOWN_"):
    r = re.search(r"KNOWN_([A-Z]+)(?:|-)(\d+)", var)
    if r:
        if varval[0].lower() in ("y", "t", "1"):
            gec.addKnownIssue("%s-%s" % (r.group(1), r.group(2)))
        else:
            gec.removeKnownIssue("%s-%s" % (r.group(1), r.group(2)))
    else:
        r = re.search(r"KNOWN_([A-Z]+)", var)
        if r:
            if varval[0].lower() in ("y", "t", "1"):
                gec.addKnownIssue(r.group(1))
            else:
                gec.removeKnownIssue(r.group(1))

if not remote:
    # Check if we are 'always' remote
    if xenrt.TEC().lookup("FORCE_REMOTE", False, boolean=True) or \
       xenrt.TEC().lookup("FORCE_REMOTE_HTTP", False, boolean=True):
        remote = True

if xenrt.TEC().lookup("JOB_PASSWORD", False, boolean=True) and xenrt.TEC().lookup("JOBID", None):
    xenrt.GEC().config.setVariable("ROOT_PASSWORD", "%s%s" % (xenrt.TEC().lookup("ROOT_PASSWORD"), xenrt.TEC().lookup("JOBID")))

# Select a suitable file manager
gec.filemanager = xenrt.filemanager.getFileManager()

#############################################################################
def existingHost(hostname):
    """Return a host object for an existing host."""
    global gec, password
    host = None
    # A host is by definition a physical machine.
    machine = xenrt.PhysicalHost(hostname)
    # Start logging the serial console.
    gec.startLogger(machine)
    # Start at the top of the inheritance tree.
    place = xenrt.GenericHost(machine)
    
    ips = [place.getIP()]
    for n in place.listSecondaryNICs():
        try:
            ips.append(place.getNICAllocatedIPAddress(n)[0])
        except:
            pass
    place.checkWindows(ipList = ips)
    place.findPassword(ipList = ips)
    place.checkVersion()
    if place.productType == "hyperv":
        host = xenrt.lib.hyperv.hostFactory(place.productVersion)(machine, productVersion=place.productVersion, productType=place.productType)
    elif place.productType == "nativewindows":
        host = xenrt.lib.nativewindows.hostFactory(place.productVersion)(machine, productVersion=place.productVersion, productType=place.productType)
    elif place.productVersion in ["ESXi", "ESX", "KVM", "libvirt"]:
        host = xenrt.lib.libvirt.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    elif place.productVersion == "Linux":
        host = xenrt.lib.native.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    elif place.productVersion == "OSS":
        host = xenrt.lib.oss.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    else:
        host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    place.populateSubclass(host)

    host.existing()
    
    return host

def existingGuest(guestip, host=None):
    """Return a guest object for an existing guest."""
    global password
    guest = xenrt.objects.GenericGuest(guestip, host)
    guest.mainip = guestip
    guest.windows = guest.xmlrpcIsAlive()
    
    if not guest.windows and password:
        guest.findPassword()
    
    # Attempt to find host.
    try:
        macs = guest.getMyVIFs()
        macs = map(xenrt.normaliseMAC, macs)
        hosts = [ xenrt.TEC().registry.hostGet(x) \
                    for x in xenrt.TEC().registry.hostList() ]
        for h in hosts:
            for g in [ xenrt.TEC().registry.guestGet(x) for x in h.listGuests() ]:
                comp = [ x[0] for x in g.getVIFs().values() ]
                for m in macs:
                    if m in comp:
                        g.mainip = guestip
                        if existing and g.host:
                            g.existing(g.host)
                        return g
    except Exception, e:
        xenrt.TEC().logverbose("Couldn't find a host for %s. (%s)" % (guestip, e))

    return guest

def existingPool(mastername):
    """Return a pool object for an existing pool"""
    master = existingHost(mastername)
    pool = xenrt.lib.xenserver.poolFactory(master.productVersion)(master)
    xenrt.TEC().logverbose("Created pool object: %s" % (pool))
    try:
        pool.existing()
    except:
        traceback.print_exc(file=sys.stdout) 
        raise 
    return pool

def getCloud(hostname):
    """Populate the registry with a cloud"""
    try:
        gec.registry.toolstackGetDefault()
    except:
        try:
            m = xenrt.GEC().dbconnect.api.get_machine(hostname)['params']
            if m.has_key("CSGUEST"):
                (hostname, guestname) = m['CSGUEST'].split("/", 1)
                try:
                    host = existingHost(hostname)
                except:
                    host = xenrt.SharedHost(hostname, doguests = True).getHost()
                guest = host.guests[guestname]
                gec.registry.guestPut("CS-MS", guest)
                cloud = xenrt.lib.cloud.CloudStack(guest)
                gec.registry.toolstackPut("cloud", cloud)
            elif m.has_key('CSIP'):
                cloud = xenrt.lib.cloud.CloudStack(ip=m['CSIP'])
                gec.registry.toolstackPut("cloud", cloud)
        except Exception, e:
            xenrt.TEC().logverbose("Warning - could not retrieve CS management server - %s" % str(e))

def existingLocations():
    runon = None
    getPools = True
    poolIndex = 0 
    getHosts = True
    hostIndex = 0
    getGuests = True
    guestIndex = 0
    slaves = []

    # See if we have a pool to run on.
    masterhost = gec.config.lookup("RESOURCE_POOL_0", None)
    if masterhost:
        getCloud(masterhost)
        runon = existingPool(masterhost)
        gec.registry.poolPut("RESOURCE_POOL_%s" % (poolIndex), runon)
        poolIndex = poolIndex + 1 
        gec.registry.hostPut("RESOURCE_HOST_%s" % (hostIndex), runon.master)
        gec.registry.hostPut(masterhost, runon.master)
        hostIndex = hostIndex + 1
        slaves = slaves + runon.listSlaves()
    else:
        # See if we have a host to run on.
        runonname = gec.config.lookup("RESOURCE_HOST_0", None)
        if runonname:
            getCloud(runonname)
            runon = existingHost(runonname)
            gec.registry.hostPut("RESOURCE_HOST_0", runon)
            gec.registry.hostPut(runonname, runon)
            hostIndex = hostIndex + 1 
        else:
            # See if we have been given a guest to run on.
            runonname = gec.config.lookup("RESOURCE_GUEST_0", None)
            if runonname:
                runon = existingGuest(runonname)
                gec.registry.guestPut("RESOURCE_GUEST_0", runon)
                gec.registry.guestPut(runonname, runon)
                getPools = False
                getHosts = False
                guestIndex = guestIndex + 1 
            elif not noplace:
                sys.stderr.write("Need to specify a target to run on.\n")
                sys.exit(1)
    
    while getPools:
        poolvar = "RESOURCE_POOL_%d" % (poolIndex)
        masterhost = gec.config.lookup(poolvar, None)
        if masterhost:
            getCloud(masterhost)
            pool = existingPool(masterhost)
            gec.registry.poolPut(poolvar, pool)
            gec.registry.hostPut("RESOURCE_HOST_%s" % (hostIndex), runon.master)
            gec.registry.hostPut(masterhost, runon.master)
            slaves = slaves + pool.listSlaves()
        else:
            break
        hostIndex = hostIndex + 1
        poolIndex = poolIndex + 1
    
    while getHosts:
        hostvar = "RESOURCE_HOST_%d" % (hostIndex)
        hostname = gec.config.lookup(hostvar, None)
        if hostname:
            getCloud(hostname)
            host = existingHost(hostname)
            if existing and not hostname in slaves:
                host.existing()
            gec.registry.hostPut(hostvar, host)
            gec.registry.hostPut(hostname, host)
        else:
            break
        hostIndex = hostIndex + 1

    while getGuests:
        guestvar = "RESOURCE_GUEST_%d" % (guestIndex)
        guestip = gec.config.lookup(guestvar, None)
        if guestip:
            guest = existingGuest(guestip)
            gec.registry.guestPut(guestvar, guest)
        else:
            break
        guestIndex = guestIndex + 1

    return runon

def findSeqFile(config):
    # Try the following locations for a seqfile:
    #   1. CWD
    #   2. $XENRT_CONF/seqs
    #   3. $XENRT_BASE/seqs
    #   4. File supplied through controller
    search = ["."]
    p = config.lookup("XENRT_CONF", None)
    if p:
        search.append("%s/seqs" % (p))
    p = config.lookup("XENRT_BASE", None)
    if p:
        search.append("%s/seqs" % (p))
    usefilename = None
    for p in search:
        xenrt.TEC().logverbose("Looking for seq file in %s ..." % (p))
        filename = "%s/%s" % (p, seqfile)
        if os.path.exists(filename):
            usefilename = filename
            break
    p = config.lookup("CUSTOM_SEQUENCE", None)
    if p:
        xenrt.TEC().logverbose("Looking for seq file on controller ...")
        sf = xenrt.TEC().tempFile()
        data = xenrt.GEC().dbconnect.jobDownload(seqfile)
        f = file(sf, "w")
        f.write(data)
        f.close()
        usefilename = sf
    return usefilename 

running = None

def exitcb():
    global running, port, aux
    if running == True:
        running = False
        try:
            s = xmlrpclib.Server('http://127.0.0.1:%u' % (port))
            s.xmlrpcNop()
        except Exception, e:
            print str(e)
    try:
        gec.onExit(aux)
    except Exception, e:
        print str(e)
    if not aux:
        gec.dbconnect.jobUpdate("FINISHED",
                                time.asctime(time.gmtime()) + " UTC")
        gec.dbconnect.jobComplete()


atexit.register(exitcb)

#############################################################################
# Some uses of this script may be to perform tasks other than running tests #
#############################################################################

if confdump:
    config.writeOut(sys.stdout)

if sanitycheck:
    # If we get this far then our standard imports etc have all
    # succeeded, so report this back to the user
    sys.stderr.write("Core XenRT libraries imported sucessfully\n")

    # Now check that all the testcases can be imported successfully
    tcDir = os.path.join(localxenrt.SHAREDIR, "exec/testcases")
    importFails = []
    for root, _, files in os.walk(tcDir):
        if root.startswith(os.path.join(tcDir, "xenserver/tc/perf")):
            # Skip performance tests
            continue

        sys.stderr.write("Checking %s\n" % root)
        for fn in files:
            if not fn.endswith(".py"):
                # Ignore non .py files
                continue

            importPath = "testcases%s.%s" % (root[len(tcDir):].replace("/", "."), fn[:-3])
            # Skip any files we know to be broken that have been removed, but
            # may still exist on systems as we don't do --delete with rsync

            if importPath in ["testcases.xenserver.tc.pysphere"]:
                continue

            try:
                __import__(importPath)
            except:
                traceback.print_exc(file=sys.stderr)
                importFails.append(importPath)

    if len(importFails) > 0:
        sys.stderr.write("The following testcase files failed to import: %s" % importFails)
        sys.exit(1)

    sys.exit(0)

if makeconfigs:
    ret = xenrt.infrastructuresetup.makeConfigFiles(config, debian)
    sys.exit(ret)

if makemachines:
    xenrt.infrastructuresetup.makeMachineFiles(config)
    sys.exit(0)
elif makemachine:
    xenrt.infrastructuresetup.makeMachineFiles(config, makemachine)
    sys.exit(0)

if shownetwork:
    if shownetwork6:
        hostfield = "HOST_ADDRESS6"
        bmcfield = "BMC_ADDRESS6"
        ipfield = "IP_ADDRESS6"
        addrfield = "ADDRESS6"
        dnsfield = "NAMESERVERS6"
        ntpfield = "NTP_SERVERS6"
        subnetfield = "SUBNET6"
        subnetmaskfield = "SUBNETMASK6"
        gatewayfield = "GATEWAY6"
        poolstartfield = "POOLSTART6"
        poolendfield = "POOLEND6"
        xrtaddressfield = "XENRT_SERVER_ADDRESS6"
    else:
        hostfield = "HOST_ADDRESS"
        bmcfield = "BMC_ADDRESS"
        ipfield = "IP_ADDRESS"
        addrfield = "ADDRESS"
        dnsfield = "NAMESERVERS"
        ntpfield = "NTP_SERVERS"
        subnetfield = "SUBNET"
        subnetmaskfield = "SUBNETMASK"
        gatewayfield = "GATEWAY"
        poolstartfield = "POOLSTART"
        poolendfield = "POOLEND"
        xrtaddressfield = "XENRT_SERVER_ADDRESS"
    # Display network details and host IP allocations
    staticip = {}
    
    # Get the primary address for each machine
    staticip["primary"] = {}
    staticip["bmc"] = {}
    allip = []
    for machine in machines:
        addr = config.lookup(["HOST_CONFIGS", machine, hostfield], None)
        if not addr:
            sys.stderr.write("WARNING: No IP specified for %s\n" % (machine))
        else:
            if addr in allip:
                alsoseen = []
                for x in staticip.keys():
                    alsoseen.extend([staticip[x][y] for y in staticip[x].keys() if y == addr])
                sys.stderr.write("Have multiple entries for %s, on %s,%s\n" % (addr, machine, ",".join(alsoseen)))
                
                sys.exit(1)
            staticip["primary"][addr] = machine
            allip.append(addr)
        addr = config.lookup(["HOST_CONFIGS", machine, bmcfield], None)
        if addr:
            if addr in allip:
                alsoseen = []
                for x in staticip.keys():
                    alsoseen.extend([staticip[x][y] for y in staticip[x].keys() if y == addr])
                sys.stderr.write("Have multiple entries for %s, on %s,%s\n" % (addr, machine, ",".join(alsoseen)))
                sys.exit(1)
            staticip["bmc"][addr] = machine
            allip.append(addr)
        
    # Get entries for other interfaces with statically assigned addresses
    for machine in machines:
        nicdict = config.lookup(["HOST_CONFIGS", machine, "NICS"], None)
        if nicdict:
            for nic in nicdict.keys():
                network = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "NETWORK"], None)
                addr = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, ipfield], None)
                
                if network and addr:
                    if not staticip.has_key(network):
                        staticip[network] = {}
                    if addr in allip:
                        alsoseen = []
                        for x in staticip.keys():
                            alsoseen.extend([staticip[x][y] for y in staticip[x].keys() if y == addr])
                        sys.stderr.write("Have multiple entries for %s, on %s,%s\n" % (addr, machine, ",".join(alsoseen)))
                        sys.exit(1)
                    staticip[network][addr] = "%s-%s" % (machine, nic)
                    allip.append(addr)

    peers = config.lookup(["TTCP_PEERS"], {})
    for p in peers.keys():
        addr = config.lookup(["TTCP_PEERS", p, addrfield], None)
        if not addr:
            sys.stderr.write("WARNING: No IP specified for %s\n" % (p))
        else:
            if addr in allip:
                alsoseen = []
                for x in staticip.keys():
                    alsoseen.extend([staticip[x][y] for y in staticip[x].keys() if y == addr])
                sys.stderr.write("Have multiple entries for %s, on %s,%s\n" % (addr, p, ",".join(alsoseen)))
                sys.exit(1)
            staticip["primary"][addr] = p
            allip.append(addr)
    sharedhosts = config.lookup(["SHARED_HOSTS"], {})
    for h in sharedhosts.keys():
        managed = config.lookup("SHARED_HOSTS_MANAGED", False, boolean=True)
        if managed:
            addr = config.lookup(["SHARED_HOSTS", h, addrfield], None)
            if not addr:
                sys.stderr.write("WARNING: No IP specified for %s\n" % (p))
            else:
                if addr in allip:
                    alsoseen = []
                    for x in staticip.keys():
                        alsoseen.extend([staticip[x][y] for y in staticip[x].keys() if y == addr])
                    sys.stderr.write("Have multiple entries for %s, on %s,%s\n" % (addr, h, ",".join(alsoseen)))
                    sys.exit(1)
                staticip["primary"][addr] = h
                allip.append(addr)

    # Display general network information
    dns = config.lookup(["NETWORK_CONFIG", "DEFAULT", dnsfield], "none")
    domainname = config.lookup(["NETWORK_CONFIG", "DEFAULT", "DOMAIN"], "none")
    ntpservers = xenrt.TEC().lookup(ntpfield, "")
    print """Site network configuration:
    DNS servers: %s
    Domain name: %s
    NTP servers: %s
""" % (dns, domainname, ntpservers)

    # Display NPRI information
    subnet = config.lookup(["NETWORK_CONFIG", "DEFAULT", subnetfield])
    netmask = config.lookup(["NETWORK_CONFIG", "DEFAULT", subnetmaskfield])
    gateway = config.lookup(["NETWORK_CONFIG", "DEFAULT", gatewayfield])
    ip = config.lookup(xrtaddressfield, None)
    ps = config.lookup(["NETWORK_CONFIG", "DEFAULT", poolstartfield], None)
    pe = config.lookup(["NETWORK_CONFIG", "DEFAULT", poolendfield], None)
    iprange = IPy.IP("%s/%s" % (subnet, netmask))
    print """NPRI network:
    Subnet: %s/%s
    Gateway: %s
    Controller IP: %s""" % (subnet, netmask, gateway, ip)
    if ps and pe:
        print "    DHCP pool: %s to %s" % (ps, pe)
    print ""
    
    print "    Test server BMC interface static IP allocation:"
    addrs = []
    for a in staticip["bmc"].keys():
        try:
            if IPy.IP(a) in iprange:
                addrs.append(a)
        except Exception,e:
            pass
    addrs.sort(cmp=xenrt.util.compareIPForSort)
    for addr in addrs:
        print "      %-15s %s-BMC" % (addr, staticip["bmc"][addr])
    print ""
    
    print "    Test server primary interface static IP allocation:"
    addrs = staticip["primary"].keys()
    addrs.sort(cmp=xenrt.util.compareIPForSort)
    for addr in addrs:
        print "      %-15s %s" % (addr, staticip["primary"][addr])
    print ""

    print "    Test server non-primary interface static IP allocation:"
    if staticip.has_key("NPRI"):
        addrs = staticip["NPRI"].keys()
        addrs.sort(cmp=xenrt.util.compareIPForSort)
        for addr in addrs:
            print "      %-15s %s" % (addr, staticip["NPRI"][addr])
    else:
        print "      none"
    print ""

    # Display NSEC information
    if config.lookup(["NETWORK_CONFIG", "SECONDARY"], None):
        subnet = config.lookup(["NETWORK_CONFIG", "SECONDARY", subnetfield])
        netmask = config.lookup(["NETWORK_CONFIG", "SECONDARY", subnetmaskfield])
        gateway = config.lookup(["NETWORK_CONFIG", "SECONDARY", gatewayfield])
        ip = config.lookup(["NETWORK_CONFIG", "SECONDARY", addrfield])
        ps = config.lookup(["NETWORK_CONFIG", "SECONDARY", poolstartfield], None)
        pe = config.lookup(["NETWORK_CONFIG", "SECONDARY", poolendfield], None)
        print """NSEC network:
    Subnet: %s/%s
    Gateway: %s
    Controller IP: %s""" % (subnet, netmask, gateway, ip)
        if ps and pe:
            print "    DHCP pool: %s to %s" % (ps, pe)
        print ""

        print "    Test server NSEC interface static IP allocation:"
        if staticip.has_key("NSEC"):
            addrs = staticip["NSEC"].keys()
            addrs.sort(cmp=xenrt.util.compareIPForSort)
            for addr in addrs:
                print "      %-15s %s" % (addr, staticip["NSEC"][addr])
        else:
            print "      none"
        print ""

    # Display VLAN subnets
    vlans = config.lookup(["NETWORK_CONFIG", "VLANS"], {}).keys()
    vlans.sort()
    for v in vlans:
        id = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"])
        subnet = config.lookup(["NETWORK_CONFIG", "VLANS", v, subnetfield], None)
        if subnet:
            netmask = config.lookup(["NETWORK_CONFIG", "VLANS", v, subnetmaskfield])
            gateway = config.lookup(["NETWORK_CONFIG", "VLANS", v, gatewayfield])
            ip = config.lookup(["NETWORK_CONFIG", "VLANS", v, addrfield])
            ps = config.lookup(["NETWORK_CONFIG", "VLANS", v, poolstartfield], None)
            pe = config.lookup(["NETWORK_CONFIG", "VLANS", v, poolendfield], None)
            print """%s network (VLAN %s):
    Subnet: %s/%s
    Gateway: %s
    Controller IP: %s""" % (v, id, subnet, netmask, gateway, ip)
            if ps and pe:
                print "    DHCP pool: %s to %s" % (ps, pe)
            print ""

    print "    KVM Information:"
    for machine in machines:
        kvm = xenrt.TEC().lookupHost(machine,"KVM_HOST",None)
        if kvm:
            print "        %s %s-KVM" % (kvm, machine)

if installpackages:
    print "Evaluating whether we need marvin to be installed"
    seq = findSeqFile(config)
    if seq:
        xenrt.TEC().comment("Loading seq file %s" % (seq))
        try:
            xenrt.TestSequence(seq, tcsku=xenrt.TEC().lookup("TESTRUN_TCSKU", None))
        except Exception, e:
            xenrt.TEC().warning("Could not load seq file - %s" % str(e))
        
        # Variables defined on the command line take precedence over those
        # specified by the sequence so we reapply the command line variables
        # the config after reading the sequence file
        for sv in setvars:
            var, value = sv
            config.setVariable(var, value)

    if xenrt.TEC().lookup("MARVIN_VERSION", None) or \
       xenrt.TEC().lookup("CLOUDINPUTDIR", None) or \
       xenrt.TEC().lookup("CLOUDINPUTDIR_RHEL6", None) or \
       xenrt.TEC().lookup("CLOUDINPUTDIR_RHEL7", None) or \
       xenrt.TEC().lookup("ACS_BRANCH", None) or \
       xenrt.TEC().lookup("ACS_BUILD", None) or \
       xenrt.TEC().lookup("EXISTING_CLOUDSTACK_IP", None):
        xenrt.util.command("pip install %s" % xenrt.getMarvinFile())
    else:
        print "CLOUDINPUTDIR not specified, so marvin is not required"
    sys.exit(0)

if switchconfig:
    if len(optargs) != 1:
        raise xenrt.XRTError("Must specify a machine")
    machine = optargs[0]
    xenrt.infrastructuresetup.makeSwitchConfig(config,machine)
    

if doshell:
    try:
        runon = existingLocations()
    except:
        traceback.print_exc()

    cloudip = gec.config.lookup("EXISTING_CLOUDSTACK_IP", None)
    if cloudip:
        cloud = xenrt.lib.cloud.CloudStack(ip=cloudip)
        gec.registry.toolstackPut("cloud", cloud)
    import code
    try:
        for guest in xenrt.TEC().registry.guestList():
            try:
                c = code.compile_command("%s = xenrt.TEC().registry.guestGet('%s')" % 
                                         (guest, guest))
                exec(c)
            except:
                pass
            g = xenrt.TEC().registry.guestGet(guest)
            try:
                c = code.compile_command("%s = xenrt.TEC().registry.guestGet('%s')" % 
                                         (string.replace(g.getName(), "-", "_"),
                                          guest))
                exec(c)
            except:
                print "Didn't assign guest %s to a variable." % (g.getName())
                pass
        for host in xenrt.TEC().registry.hostList():
            try:
                c = code.compile_command("%s = xenrt.TEC().registry.hostGet('%s')" % 
                                         (host, host))
                exec(c)
            except Exception, e:
                pass
            h = xenrt.TEC().registry.hostGet(host)
            try:
                c = code.compile_command("%s = xenrt.TEC().registry.hostGet('%s')" % 
                                         (string.replace(h.getName(), "-", "_"),
                                          host))
                exec(c)
            except Exception, e:
                print "Didn't assign host %s to a variable." % (h.getName())
                pass
    except Exception, e:
        sys.stdout.write(str(e))
        traceback.print_exc(file=sys.stdout) 

    if doshell == "ipython":
        import IPython
        IPython.embed()

    else:
        import readline, rlcompleter
        readline.parse_and_bind("tab: complete")
        try:
            readline.read_history_file(historyfile)
        except:
            pass

        atexit.register(readline.write_history_file, historyfile) 
        
        print "XenRT interactive Python shell."
        more = True
        buffer = []
        while True:
            if not more:
                prompt = "..."
            else:
                prompt = ">>>"
            try:
                line = raw_input("%s " % (prompt))
                buffer.append(line)
                readline.add_history("\n".join(buffer))
                more = code.compile_command("\n".join(buffer))
                if more:
                    exec(more)
                    buffer = []
            except EOFError, e:
                print ""
                break
            except Exception, e:
                buffer = []
                more = True
                sys.stdout.write(str(e))
                traceback.print_exc(file=sys.stdout)

if replaydb:
    xenrt.TEC().logverbose("Replaying failed database uploads...")
    xenrt.GEC().dbconnect.replay()
    xenrt.TEC().logverbose("Replaying failed Jira connections...")
    jl = xenrt.jiralink.getJiraLink()
    jl.replay()

if cleanupfilecache:
    xenrt.TEC().logverbose("Cleaning shared file cache...")
    days = xenrt.TEC().lookup("FILECACHE_EXPIRY_DAYS", None)
    rfm = xenrt.getFileManager()
    if days:
        rfm.cleanup(days=int(days))
    else:
        rfm.cleanup()

if removefilecache:
    xenrt.TEC().logverbose("Removing %s from shared cache..." % removefilecache)
    fm = xenrt.filemanager.getFileManager()
    fm.removeFromCache(removefilecache)


if docgen:
    done = False
    for p in sys.path:
        if os.path.exists("%s/xenrt/__init__.py" % (p)):       
            pydoc.writedocs("%s/xenrt" % (p), "xenrt.")
            done = True
            break
    if not done:
        sys.stderr.write("Could not find library source to doc generation")
        sys.exit(1)

if lookupvar:
    try:
        print xenrt.TEC().lookup(string.split(lookupvar, "/"))
    except:
        sys.stderr.write("Variable %s not found.\n" % (lookupvar))
        sys.exit(1)

if listlocks:
    cr = xenrt.resources.CentralResource()
    locks = cr.list()
    print "Resource ID, Locked?, JobID, Timestamp"
    for l in locks:
        if l[1]:
            print "%s,Yes,%s,%s" % (l[0],l[2]['jobid'],l[2]['timestamp'])
        else:
            print "%s,No,," % (l[0])

if cleanupnfsdirs:
    jobsForMachinePowerOff = [] 
    nfsConfig = xenrt.TEC().lookup("EXTERNAL_NFS_SERVERS")
    for n in nfsConfig.keys():
        try:
            staticMount = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "STATIC_MOUNT"], None)
            if staticMount:
                mp = staticMount
                m = None
            else:
                m = xenrt.rootops.MountNFS("%s:%s" % (xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"]), xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "BASE"])))
                mp = m.getMount()
            jobs = [x.strip() for x in xenrt.command("ls %s | cut -d '-' -f 1 | sort | uniq" % mp).splitlines()]
            for j in jobs:
                try:
                    if xenrt.canCleanJobResources(j):
                        xenrt.rootops.sudo("rm -rf %s/%s-*" % (mp, j))
                        jobsForMachinePowerOff.append(j) 
                except Exception, e:
                    xenrt.TEC().logverbose(str(e))
                    continue
            if m:
                m.unmount()
        except:
            pass
    smbConfig = xenrt.TEC().lookup("EXTERNAL_SMB_SERVERS", {})
    for n in smbConfig.keys():
        try:
            staticMount = xenrt.TEC().lookup(["EXTERNAL_SMB_SERVERS", n, "STATIC_MOUNT"], None)
            if staticMount:
                mp = staticMount
                m = None
            else:
                ad = xenrt.getADConfig()
                m = xenrt.rootops.MountSMB("%s:%s" % (xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"]), xenrt.TEC().lookup(["EXTERNAL_SMB_SERVERS", n, "BASE"])), ad.domainName, ad.adminUser, ad.adminPassword)
                mp = m.getMount()
            jobs = [x.strip() for x in xenrt.command("ls %s | cut -d '-' -f 1 | sort | uniq" % mp).splitlines()]
            for j in jobs:
                try:
                    if xenrt.canCleanJobResources(j):
                        xenrt.rootops.sudo("rm -rf %s/%s-*" % (mp, j))
                        jobsForMachinePowerOff.append(j) 
                except:
                    continue
            if m:
                m.unmount()
        except:
            pass

    for j in set(jobsForMachinePowerOff):
        machinesToPowerOff = xenrt.staleMachines(j)
        for m in machinesToPowerOff:
            machine = xenrt.PhysicalHost(m, ipaddr="0.0.0.0")
            xenrt.GenericHost(machine)
            machine.powerctl.off()
    
if cleanupnfsdir:
    nfsConfig = xenrt.TEC().lookup("EXTERNAL_NFS_SERVERS")
    (cleanupAddress, cleanupPath) = cleanupnfsdir.split(":", 1)
    (cleanupBaseDir, cleanupDir) = cleanupPath.rsplit("/", 1)
    for n in nfsConfig.keys():
        try:
            staticMount = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "STATIC_MOUNT"], None)
            address = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"])
            basedir = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "BASE"])
            if address != cleanupAddress or cleanupBaseDir != basedir:
                continue
            if staticMount:
                mp = staticMount
                m = None
            else:
                m = xenrt.rootops.MountNFS("%s:%s" % (xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"]), xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "BASE"])))
                mp = m.getMount()
            xenrt.rootops.sudo("rm -rf %s/%s" % (mp, cleanupDir))
            if m:
                m.unmount()
        except:
            pass

if cleanuptempdirs:
    # to list the job ids of all running/paused/new jobs in xenrt.

    tftpBaseDir = xenrt.TEC().lookup("TFTP_BASE")
    pxeBaseDir = os.path.normpath("%s/%s" %
                            (tftpBaseDir, xenrt.TEC().lookup("TFTP_SUBDIR", default="xenrt")))

    # directories to be cleaned for the completed jobs.
    cleanDirectories = [xenrt.TEC().lookup("TEMP_DIR_BASE"), # /local/scratch/tmp
                        xenrt.TEC().lookup("HTTP_BASE_PATH"), # /local/scratch/www
                        xenrt.TEC().lookup("ISCSI_BASE_PATH"), # /local/scratch/iscsi
                        xenrt.TEC().lookup("NFS_BASE_PATH"), # /local/scratch/nfs
                        xenrt.TEC().lookup("WORKING_DIR_BASE"), # /local/scratch/working
                        pxeBaseDir # /tftpboot/xenrt or /usr/groups/netboot/xenrtd
                        ]

    # for each directory to be cleaned.
    for directoryPath in cleanDirectories:
        # check if the directory exists
        if os.path.exists(directoryPath):
            # for each files/folders in the given directory.
            for fileName in os.listdir(directoryPath):
                jobID = fileName.split("-")[0] # possible values are '', nojob, 12345
                if jobID.isdigit():
                    if jobID == cleanuptempdirsjob:
                        try:
                            xenrt.rootops.sudo("rm -rf %s/%s" % (directoryPath, fileName))
                            print "Deleted %s/%s" % (directoryPath, fileName)
                        except:
                            print "Warning, could not delete %s/%s" % (directoryPath, fileName)

if cleanuplocks:
    print "Cleaning up locks"
    cr = xenrt.resources.CentralResource()
    locks = cr.list()
    print "lock count is %d" % len(locks)
    
    jobs = set([x[2]['jobid'] for x in locks if x[1] and x[2]['jobid']])
    canClean = dict((x, xenrt.canCleanJobResources(x)) for x in jobs)
    jobsForMachinePowerOff = [] 
    jobsForGlobalRelease = []
    try:
        for lock in locks:
            if lock[1]:
                # Check timestamp
                try:
                    ts = int(lock[2]['timestamp'])
                except:
                    ts = 0
                ct = int(time.time())
                diff = ct - ts
                if diff > 5*60:
                    print "Lock %s is greater than 5 minutes old" % (lock[0])
                    if lock[2]['jobid']:
                        allowLockRelease = canClean[lock[2]['jobid']]
                    else:
                        # Doesn't have a job, must be manual run
                        pid = "(N/A)"
                        allowLockRelease = True
                    if allowLockRelease:
                        print "Job is complete, and machines not locked"
                        # Release the lock
                        if lock[0].startswith("EXT-IP4ADDR"):
                            xenrt.resources.DhcpXmlRpc().releaseAddress(lock[0].split("-")[-1])
                        else:
                            path = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
                            path += "/%s" % (lock[2]['md5'])
                            try:
                                os.unlink("%s/jobid" % (path))
                            except:
                                pass
                            try:
                                os.unlink("%s/id" % (path))
                            except:
                                pass
                            try:
                                os.unlink("%s/timestamp" % (path))
                            except:
                                pass

                            os.rmdir(path)
                        if lock[0].startswith("VLAN") or lock[0].startswith("ROUTEDVLAN") or lock[0].startswith("IP4ADDR") or lock[0].startswith("IP6ADDR") or lock[0].startswith("EXT-IP4ADDR"):
                            jobsForMachinePowerOff.append(lock[2]['jobid']) 
                        if lock[0].startswith("GLOBAL"):
                            jobsForGlobalRelease.append(lock[2]['jobid'])
                        print "Lock released"
                else:
                    print "Lock %s not greater than 5 minutes old ts=%s" % (lock[0], str(ts))
    except Exception, ex:
        print str(ex)

    for j in set(jobsForMachinePowerOff):
        machinesToPowerOff = xenrt.staleMachines(j)
        for m in machinesToPowerOff:
            machine = xenrt.PhysicalHost(m, ipaddr="0.0.0.0")
            xenrt.GenericHost(machine)
            machine.powerctl.off()
    
    for j in set(jobsForGlobalRelease):
        xenrt.GEC().dbconnect.jobctrl("globalresrelease", [j])

if releaselock:
    if (releaselock.startswith("IP4ADDR-") and xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True)) \
              or releaselock.startswith("EXT-IP4ADDR"):
        xenrt.resources.DhcpXmlRpc().releaseAddress(releaselock.split("-")[-1])
    else:
        cr = xenrt.resources.CentralResource()
        locks = cr.list()
        for lock in locks:
            if lock[1]:
                # Check ID
                if lock[0] == releaselock:
                    if lock[2]['jobid']:
                        jobdict = xenrt.GEC().dbconnect.api.get_job(int(lock[2]['jobid']))['params']
                        pid = jobdict['HARNESS_PID']
                        # See if this PID is still running
                        pr = xenrt.util.command("ps -p %s | wc -l" % (pid),strip=True)
                    else:
                        # Doesn't have a job, must be manual run
                        pid = "(N/A)"
                        pr = "1"
                    if int(pr) == 1:
                        # Release the lock
                        path = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
                        path += "/%s" % (lock[2]['md5'])
                        try:
                            os.unlink("%s/jobid" % (path))
                        except:
                            pass
                        try:
                            os.unlink("%s/id" % (path))
                        except:
                            pass
                        try:
                            os.unlink("%s/timestamp" % (path))
                        except:
                            pass

                        os.rmdir(path)
                        print "Lock %s released" % (releaselock)
                    else:
                        print "Harness process still running, not releasing lock"
                    break

if setupsharedhost:
    # Setup logdir
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    # Get the info for this peer
    sh = config.lookup(["SHARED_HOSTS",sharedhost])
    if not config.lookup("SHARED_HOSTS_MANAGED", False,boolean=True):
        print "Shared host %s is not managed by this controller" % sharedhost
    else:
        mac = sh["MAC"]
        addr = sh["ADDRESS"]
        machine = xenrt.PhysicalHost(sharedhost,ipaddr=addr)

        config.setVariable("APPLY_ALL_REQUIRED_HFXS", "yes")

        xenrt.TEC().setInputDir(sh["INPUTDIR"])
        hosttype=sh["PRODUCT_VERSION"]

        host = xenrt.lib.xenserver.hostFactory(hosttype)(machine,productVersion=hosttype)
        host.install(installSRType="ext")
        host.license()
        host.applyRequiredPatches()
        sho = xenrt.SharedHost(sharedhost)

        macs = [sh['MAC']]
        macs.extend(sh['BOND_NICS'].split(","))
        pifs = [host.minimalList("pif-list", args="MAC=%s" % x)[0] for x in macs]
        
        nets = [host.minimalList("pif-list", params="network-uuid", args="uuid=%s" % x)[0] for x in pifs]
        for n in nets:
            host.genParamSet("network", n, "name-label", "slave%s" % n)
        
        host.createBond(pifs, dhcp=True, management=True)

        # Rename the bond network to get VMs to import onto the bond rather than the slave
        bondPif = host.minimalList("bond-list", params="master")[0]
        net = host.minimalList("pif-list", params="network-uuid", args="uuid=%s" % bondPif)[0]
        host.genParamSet("network", net, "name-label", "Pool-wide network associated with eth0")

        cli = host.getCLIInstance()
        if sh.has_key("VLANS"):
            for v in sh['VLANS'].keys():
                vlan = sh['VLANS'][v]
                nw = cli.execute("network-create name-label=%s" % v).strip()
                cli.execute("vlan-create pif-uuid=%s network-uuid=%s vlan=%s" % (bondPif, nw, vlan))

        templates = sh["TEMPLATES"]
        for t in templates.keys():
            sho.createTemplate(templates[t]['DISTRO'], templates[t]['ARCH'], int(templates[t]['DISKSIZE']))


if setupstatichost:
    xenrt.infrastructuresetup.setupStaticHost()

if setupstaticguest:
    xenrt.infrastructuresetup.setupStaticGuest(staticguest)

if installhost:
    # Setup logdir
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    hosttype = config.lookup(["PRODUCT_CODENAMES", config.lookup(["CLIOPTIONS", "REVISION"]).split("-")[0]])
    host = xenrt.lib.xenserver.createHost(productVersion=hosttype, version=config.lookup("INPUTDIR"))
    
if installlinux:
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    distro = config.lookup("DEFAULT_GUEST_DISTRO")
    dd = distro.rsplit("-", 1)
    if len(dd) == 2 and dd[1] == "x64":
        arch = "x86-64"
        distro = dd[0]
    else:
        arch = "x86-32"
    mname = config.lookup("RESOURCE_HOST_0")
    m = xenrt.PhysicalHost(mname)
    h = xenrt.lib.native.NativeLinuxHost(m)
    h.installLinuxVendor(distro, arch=arch)

if installguest:
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    distro = config.lookup("DEFAULT_GUEST_DISTRO")
    dd = distro.rsplit("-", 1)
    if len(dd) == 2 and dd[1] == "x64":
        arch = "x86-64"
        distro = dd[0]
    else:
        arch = "x86-32"

    parts = installguest.split("/")

    hostAddr = parts[0]
    if len(parts) > 1:
        password = parts[1]
    else:
        password = None


    machine = xenrt.PhysicalHost("RouterHost", ipaddr = hostAddr)
    place = xenrt.GenericHost(machine)
    if password:
        place.password = password
    else:
        place.findPassword()
    place.checkVersion()
    host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    place.populateSubclass(host)
    host.existing()
    host.createBasicGuest(distro, arch=arch)

if cleanupvcenter:
    if xenrt.TEC().lookup("VCENTER_MANAGED", False, boolean=True):
        v = xenrt.lib.esx.getVCenter()
        dcs = v.listDataCenters()
        for d in dcs:
            try:
                m = re.match(".*-(\d+$)", d)
                if m:
                    try:
                        if xenrt.canCleanJobResources(m.group(1)):
                            print "Cleaning up datacenter %s" % d
                            v.removeDataCenter(d)
                        else:
                            print "Not cleaning up datacenter %s" % d
                    except Exception, e:
                        sys.stderr.write("Warning: Exception occurred %s\n" % str(e))
                        continue
                else:
                    print "Not cleaning up datacenter %s" % d
            except Exception,e:
                sys.stderr.write("Warning: Exception occurred %s\n" % str(e))

if cleanupsharedhosts:
    # Setup logdir
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    # Get the info for this peer
    sharedhosts = config.lookup(["SHARED_HOSTS"])
    for sharedhost in sharedhosts.keys():
        if config.lookup("SHARED_HOSTS_MANAGED", False,boolean=True):
            sh = xenrt.resources.SharedHost(sharedhost, doguests=True)
            vms = sh.getHost().listGuests()
            for v in vms:
                try:
                    m = re.match(".*-(\d+$)", v)
                    if m:
                        if m.group(1) == "64": # This actually indicates a 64-bit VM!
                            continue
                        try:
                            if xenrt.canCleanJobResources(m.group(1)):
                                print "Cleaning up guest %s" % v
                                g = sh.getHost().getGuest(v)
                                g.uninstall()
                            else:
                                print "Not cleaning up guest %s" % v
                        except:
                            continue
                    else:
                        print "Not cleaning up guest %s" % v
                except Exception,e:
                    sys.stderr.write("Warning: Exception occurred %s\n" % str(e))


            
    

if setupnetpeer:
    xenrt.infrastructuresetup.setupNetPeer(netpeer, config)

if setuprouter:
    xenrt.infrastructuresetup.setupRouter(config)

if bootdiskless:
    machine = xenrt.PhysicalHost(boothost)
    h = xenrt.GenericHost(machine) 
    h.bootRamdiskLinux() 

if bootwinpe:
    machine = xenrt.PhysicalHost(bootwinpe)
    h = xenrt.GenericHost(machine) 
    pxe = xenrt.PXEBoot()
    winpe = pxe.addEntry("winpe", default=True, boot="memdisk")
    winpe.setInitrd("winpe/winpe.iso")
    winpe.setArgs("iso raw")
    pxe.writeOut(machine)
    machine.powerctl.cycle()
    xenrt.TEC().logverbose("Machine will reboot into WinPE")
    

if powercontrol:
    if poweroperation != "off" and os.path.exists("%s/halted" % localxenrt.VARDIR):
        print "Site is halted"
    else:
        # Setup logdir
        if forcepdu:
            powerctltype = "APCPDU"
        else:
            powerctltype = None
        if not powerhost in xenrt.TEC().lookup("HOST_CONFIGS", {}).keys():
            print "Loading %s from Racktables" % powerhost
            xenrt.readMachineFromRackTables(powerhost)
        machine = xenrt.PhysicalHost(powerhost, ipaddr="0.0.0.0", powerctltype=powerctltype)
        h = xenrt.GenericHost(machine)
        machine.powerctl.setVerbose()
        machine.powerctl.setAntiSurge(False)
        if poweroperation == "on":
            machine.powerctl.on()
        elif poweroperation == "off":
            machine.powerctl.off()
        elif poweroperation == "cycle":
            if bootdev:
                machine.powerctl.setBootDev(bootdev)
                config.setVariable("IPMI_SET_PXE", "no")
            machine.powerctl.cycle()
        elif poweroperation == "nmi":
            machine.powerctl.triggerNMI()
        elif poweroperation == "status":
            print "POWERSTATUS: %s" % str(machine.powerctl.status())

if mconfig:
    xenrt.tools.machineXML(mconfig)

if dumpsuite:
    suites = xenrt.suite.getSuites(dumpsuite)
    if skufile:
        sku = xenrt.suite.SKU(skufile)
        for suite in suites:
            suite.setSKU(sku)
    for suite in suites:
        suite.debugPrint(sys.stdout)

if listsuitetcs:
    suites = xenrt.suite.getSuites(listsuitetcs)
    if skufile:
        sku = xenrt.suite.SKU(skufile)
        for suite in suites:
            suite.setSKU(sku)
    for suite in suites:
        print "\n".join(suite.listTCsInSequences(quiet=True))

if checksuite:
    suites = xenrt.suite.getSuites(checksuite)
    if skufile:
        sku = xenrt.suite.SKU(skufile)
        for suite in suites:
            suite.setSKU(sku)
    for suite in suites:
        suite.checkSuite(sys.stdout)
    
if fixsuite:
    suites = xenrt.suite.getSuites(fixsuite)
    if skufile:
        sku = xenrt.suite.SKU(skufile)
        for suite in suites:
            suite.setSKU(sku)
    for suite in suites:
        suite.fixSuite(sys.stdout)

if runsuite:
    suites = xenrt.suite.getSuites(runsuite)
    if skufile:
        sku = xenrt.suite.SKU(skufile)
        for suite in suites:
            suite.setSKU(sku)
    for suite in suites:
        testrun = suite.submit(debug=suitedebug,delayfor=delayfor,devrun=suitedevrun)
        print "SUITE %s" % (testrun)

if getresource:
   args = getresource.split()
   machine = args.pop(0)
   job = str(xenrt.GEC().dbconnect.api.get_machine(machine)['jobid'])
   config.setVariable("JOBID", job)
   xenrt.GEC().dbconnect._jobid = int(job)
   restype = args.pop(0)
   try:
       ret = xenrt.getResourceInteractive(restype, args)
       print json.dumps({"result": "OK", "data": ret})
   except Exception, e:
       print json.dumps({"result": "ERROR", "data": str(e)})

if listresources:
    cr = xenrt.resources.CentralResource()
    locks = cr.list()
    jobs = [x[2]['jobid'] for x in locks if x[1] and x[2]['jobid'] and x[2]['jobid'].isdigit()]
    
    jobdirs = {}

    nfsConfig = xenrt.TEC().lookup("EXTERNAL_NFS_SERVERS")
    for n in nfsConfig.keys():
        try:
            staticMount = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "STATIC_MOUNT"], None)
            address = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"])
            basedir = xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "BASE"])
            if staticMount:
                mp = staticMount
                m = None
            else:
                m = xenrt.rootops.MountNFS("%s:%s" % (address, basedir))
                mp = m.getMount()
            dirs = xenrt.command("ls %s" % mp)

            for d in dirs.splitlines():
                m = re.match("(\d+)-.*", d)
                if m:
                    job = m.group(1)
                    if not job in jobdirs.keys():
                        jobdirs[job] = []
                    jobdirs[job].append("%s:%s/%s" % (address, basedir.rstrip("/"), d))
                    jobs.append(job)
            if m:
                m.unmount()
        except:
            pass
    
    jobs = set(jobs)

    machineJobs = [x for x in jobs if xenrt.jobOnMachine(listresources, x)]

    ret = {}

    for l in locks:
        if l[1] and l[2]['jobid'] in machineJobs:
            (resclass, resname) = l[0].rsplit("-",1)
            if resclass.startswith("EXT-"):
                resclass = resclass[4:]
            if not resclass in ret.keys():
                ret[resclass] = []
            if not resname in ret[resclass]:
                ret[resclass].append(resname)

    for m in machineJobs:
        if jobdirs.has_key(m):
            if not "NFS" in ret.keys():
                ret["NFS"] = []
            ret['NFS'].extend(jobdirs[m])

    for k in ret.keys():
        if k in ("IP4ADDR", "IP6ADDR"):
            ret[k].sort(key=lambda x: IPy.IP(x).int())
        else:
            try:
                ret[k] = [int(x) for x in ret[k]]
            except:
                pass
            ret[k].sort()
        if k == "ROUTEDVLAN":
            ret[k] = dict([(x, xenrt.PrivateRoutedVLAN.getNetworkConfigForVLAN(x)) for x in ret[k]]) 

    print json.dumps(ret)

if runtool:
    eval("xenrt.tools." + runtool)

# We set the aux variable if the script is being used for things other
# than test running.
if aux:
    sys.exit(0)

#############################################################################
# If we get this far we're going to be running tests...                     #
#############################################################################

xenrt.TEC().logverbose("Command line: %s" % (string.join(sys.argv)))

if xenrt.TEC().lookup("WINPDB_DEBUG", False, boolean=True):
    import rpdb2
    rpdb2.start_embedded_debugger(xenrt.TEC().lookup("JOBID", "xenroot"), fAllowRemote=True)

# XML-RPC server
running = True
class MySimpleXMLRPCServer(SimpleXMLRPCServer):
    @xenrt.irregularName
    def serve_forever(self):
        global running
        while running:
            self.handle_request()
# Create server
rpcserver = MySimpleXMLRPCServer(("0.0.0.0", 0))
addr, port = rpcserver.socket.getsockname()
addr = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS", socket.getfqdn())
addr = xenrt.TEC().lookup("XMLRPC_SERVER_ADDRESS", addr)
xmlrpcstring = "%s:%u" % (addr, port)
gec.dbconnect.jobUpdate("XMLRPC", xmlrpcstring)
xenrt.TEC().progress("XML-RPC server on %s" % (xmlrpcstring))
config.setVariable("XMLRPC", xmlrpcstring)
def getRunningTests():
    xenrt.TEC().logverbose("XML-RPC getRunningTests")
    return gec.getRunningTests()
def setRunningStatus(test, status):
    gec.setRunningStatus(test, status)
    return True
def setBlockingStatus(test, status):
    gec.setBlockingStatus(test, status)
    return True
def setTestResult(test, result):
    gec.setTestResult(test, result)
    return True
def setConfigVariable(var, value):
    config.setVariable(var, value)
    return True
def dumpConfig():
    return config.getAll(deep=True)
def abortRun():
    gec.abortRun()
    return True
def flushLogs():
    sys.stderr.flush()
    sys.stdout.flush()
    return True
def getGuestList():
    return gec.registry.guestList()
def getGuestInfo(name):
    guest = gec.registry.guestGet(name)
    if not guest:
        raise "Unable to find guest %s" % (name)
    return guest.getInfo()
def getGuestFile(guestname, filename):
    guest = gec.registry.guestGet(guestname)
    if not guest:
        raise "Unable to find guest %s" % (guestname)
    #return guest.xmlrpcReadFile(filename, blob=True)
    sftp = guest.sftpClient()
    tmp = xenrt.TEC().tempFile()
    sftp.copyFrom(filename, tmp)
    sftp.close()
    data = xmlrpclib.Binary()
    f = file(tmp, "r")
    data.data = f.read()
    f.close()
    os.unlink(tmp)
    return data
def getHostList():
    return gec.registry.hostList()
def getHostInfo(name):
    host = gec.registry.hostGet(name)
    if not host:
        raise "Unable to find host %s" % (name)
    return host.getInfo()
def xmlrpcEcho(x):
    return x
def xmlrpcNop():
    return True
def xmlrpcShell(command):
    try:
        exec("_rc = %s" % (command))
    except EOFError, e:
        print ""
        return
    except Exception, e:
        return (str(e))
        traceback.print_exc(file=sys.stdout)
    return str(_rc)
def xmlrpcLogger():
    return gec.getLogHistory()
rpcserver.register_function(getRunningTests)
rpcserver.register_function(setRunningStatus)
rpcserver.register_function(setBlockingStatus)
rpcserver.register_function(setTestResult)
rpcserver.register_function(setConfigVariable)
rpcserver.register_function(dumpConfig)
rpcserver.register_function(abortRun)
rpcserver.register_function(flushLogs)
rpcserver.register_function(getGuestList)
rpcserver.register_function(getGuestInfo)
rpcserver.register_function(getGuestFile)
rpcserver.register_function(getHostList)
rpcserver.register_function(getHostInfo)
rpcserver.register_function(xmlrpcEcho)
rpcserver.register_function(xmlrpcNop)
rpcserver.register_function(xmlrpcShell)
rpcserver.register_function(xmlrpcLogger)
def xmlrpcServe():
    rpcserver.serve_forever()
# Don't start the deamon if we're only debugging the sequence
if not seqdump:
    rpcthread = threading.Thread(target=xmlrpcServe)
    rpcthread.name = "XML/RPC Daemon"
    rpcthread.daemon = True
    rpcthread.start()
else:
    running = False

###########################################################################

# Look for a performance limits/regression file
p = config.lookup("PERFDATAFILE", None)
if p:
    if p == "yes":
        xenrt.TEC().logverbose("Looking for perf file on controller ...")
        data = xenrt.GEC().dbconnect.jobDownload("perfdata")
    else:
        f = file(p, "r")
        data = f.read()
        f.close()
    x = xml.dom.minidom.parseString(data)
    for n in x.childNodes:
        if n.nodeType == n.ELEMENT_NODE and n.localName == "perfcheck":
            xenrt.GEC().perfCheckParse(n)
    xenrt.TEC().logverbose(str(xenrt.GEC().perfChecks))

p = config.lookup("PERFREGRESSFILE", None)
if p:
    if p == "yes":
        xenrt.TEC().logverbose("Looking for perf regress file on controller ...")
        data = xenrt.GEC().dbconnect.jobDownload("perfregress")
    else:
        f = file(p, "r")
        data = f.read()
        f.close()
    x = xml.dom.minidom.parseString(data)
    for n in x.childNodes:
        if n.nodeType == n.ELEMENT_NODE and n.localName == "sequenceresults":
            for m in n.childNodes:
                if m.nodeType == m.ELEMENT_NODE and m.localName == "testgroup":
                    group = None
                    for t in m.childNodes:
                        if t.nodeType == t.ELEMENT_NODE and \
                                t.localName == "name":
                            for x in t.childNodes:
                                if x.nodeType == x.TEXT_NODE:
                                    group = string.strip(str(x.data))
                        if t.nodeType == t.ELEMENT_NODE and \
                                t.localName == "test":
                            test = None
                            for x in t.childNodes:
                                if x.nodeType == x.ELEMENT_NODE and \
                                       x.localName == "name":
                                    for y in x.childNodes:
                                        if y.nodeType == y.TEXT_NODE:
                                            test = string.strip(str(y.data))
                                if x.nodeType == x.ELEMENT_NODE and \
                                        x.localName == "value":
                                    metric = str(x.getAttribute("param"))
                                    units = str(x.getAttribute("units"))
                                    value = 0.0
                                    for y in x.childNodes:
                                        if y.nodeType == y.TEXT_NODE:
                                            value = float(y.data)
                                    if not group:
                                        group = "DEFAULT"
                                    xenrt.GEC().perfRegress(group,
                                                            test,
                                                            metric,
                                                            value,
                                                            units)
    xenrt.TEC().logverbose(str(xenrt.GEC().perfRegresses))

###########################################################################

gec.dbconnect.jobUpdate("STARTED", time.asctime(time.gmtime()) + " UTC")
gec.dbconnect.jobUpdate("RUNDIR", gec.config.lookup("RESULT_DIR", os.getcwd()))
ver = xenrt.TEC().lookup("XENRT_VERSION", None)
if ver:
    xenrt.TEC().logverbose("Using XenRT harness version %s" % (ver))
    gec.dbconnect.jobUpdate("XENRT_VERSION", ver)

cloudip = gec.config.lookup("EXISTING_CLOUDSTACK_IP", None)
if cloudip:
    cloud = xenrt.lib.cloud.CloudStack(ip=cloudip)
    gec.registry.toolstackPut("cloud", cloud)


# Import any additional testcases.
if tcfile:
    testfiles = string.split(tcfile, ",")
    xenrt.TEC().logverbose("Test case files: %s" % (testfiles))
    for filename in testfiles:
        xenrt.TEC().logverbose("Looking for test case file on controller ...")
        sd = xenrt.TEC().tempDir()
        data = xenrt.GEC().dbconnect.jobDownload(filename)
        if data:
            f = file("%s/%s" % (sd, filename), "w")
            f.write(data)
            f.close()
            filename = "%s/%s" % (sd, filename)
        else:
            filename = gec.filemanager.getFile(filename)
        xenrt.TEC().logverbose("TCFile is now: %s" % (filename))
        base = os.path.basename(filename)
        root, ext = os.path.splitext(base)
        if ext == ".py":
            dir = os.path.dirname(filename)
        elif ext == ".gz" or ext == ".tgz":
            dir = xenrt.TEC().tempDir()
            tf = tarfile.open(filename, "r")
            for m in tf.getmembers():
                tf.extract(m, dir)
            tf.close() 
        else:
            xenrt.TEC().warning("Invalid test case file.")
            sys.exit(1)
        xenrt.TEC().logverbose("Appending %s to path." % (dir))
        sys.path.append(dir)

if testcase:
    # Run a single testcase.
    runon = existingLocations()
    if not isinstance(runon, xenrt.lib.xenserver.Pool):
        if tailor and runon:
            runon.tailor()
        elif runon:
            if password:
                runon.findPassword()

    if ro:
        try:
            runon = xenrt.TEC().registry.guestGet(ro)
        except:
            runon = xenrt.TEC().registry.hostGet(ro)
        runon.tailor()

    try:
        xenrt.TEC().logverbose("Trying to instantiate %s." % (testcase))
        tc = xenrt.SingleTestCase("%s" % (testcase), optargs)
    except Exception, e: 
        xenrt.TEC().logverbose("Failed with %s." % (str(e)))       
        xenrt.TEC().logverbose("Trying to instantiate testcases.%s." % 
                               (testcase))
        tc = xenrt.SingleTestCase("testcases.%s" % (testcase), optargs)

    tc.runon = runon
    try:
        if traceon:
            tracer = trace.Trace(trace=1)
            tracer.run('tc.run()')
        else:
            tc.run()
    except:
        if config.isVerbose():
            traceback.print_exc(file=sys.stderr)
else:
    usefilename = findSeqFile(config)
    if usefilename:
        xenrt.TEC().comment("Using sequence file %s" % (usefilename))
    else:
        gec.harnessError()
        strErr = "Could not find sequence file."
        gec.logverbose(strErr)
        try:
            gec.dbconnect.jobUpdate("PREPARE_FAILED", strErr)
        except:
            pass

        sys.stderr.write(strErr)
        sys.exit(1)
    seqfilebase = os.path.basename(usefilename)
    seqfileroot, seqfileext = os.path.splitext(seqfilebase)
    config.setVariable("SEQUENCE_NAME", seqfileroot)
    inputdir1 = xenrt.TEC().lookup("INPUTDIR", None)
    
    try:
        seq = xenrt.TestSequence(usefilename, tcsku=xenrt.TEC().lookup("TESTRUN_TCSKU", None))
    except Exception, e:
        gec.harnessError()
        xenrt.TEC().logverbose(traceback.format_exc())
        sys.exit(1)
        
    # existing must be done after the sequence has been parsed and imported.
    # this is because site-controller will blat the source code shortly
    # after running main.py so we must have everything imported promptly.
    
    if existing:
        runon = existingLocations()
        if not isinstance(runon, xenrt.lib.xenserver.Pool):
            if tailor and runon:
                runon.tailor()
            elif runon and password:
                runon.findPassword()

    # Variables defined on the command line take precedence over those
    # specified by the sequence so we reapply the command line variables
    # the config after reading the sequence file
    for sv in setvars:
        var, value = sv
        config.setVariable(var, value)
    # If the sequence defined a INPUTDIR and we did not previously have
    # one then recreate the filemanager
    inputdir2 = xenrt.TEC().lookup("INPUTDIR", None)
    if inputdir1 != inputdir2 and not inputdir1:
        gec.filemanager = xenrt.filemanager.getFileManager()
    if seqdump:
        if seq.prepare:
            seq.prepare.debugDisplay()
        seq.debugPrint(sys.stdout)
    else:
        try:
            if traceon:
                tracer = trace.Trace(trace=1)
                tracer.run('seq.run()')
            else:
                seq.run()
        except Exception, e:
            traceback.print_exc(file=sys.stderr) 

if xenrt.TEC().lookup("PAUSE_BEFORE_EXIT", False, boolean=True):
    xenrt.sleep(432000)

sys.stderr.write("XenRT about to exit\n")
sys.stderr.write("Current threads:\n")

for i in threading.enumerate():
    sys.stderr.write("\t%s, Daemon: %s\n" % (i.name, str(i.daemon)))

sys.exit(0)
