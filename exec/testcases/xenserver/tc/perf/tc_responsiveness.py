import libperf, os, os.path, time
import xenrt, xenrt.lib.xenserver

class TCResponsiveness(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCResponsiveness")

        self.host = self.getDefaultHost()

        self.measurements = 64
        self.thread_count = 64
        self.pretest_delay = 60
        self.command = "xe vm-list"
        self.dom0vcpus = None
        self.timeout = 3600
        self.mount_path = "backup-storage-cbg2.uk.xensource.com:/containers/builds_archive"

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse other arguments

        # Number of measurements to conduct
        self.measurements = libperf.getArgument(arglist, "measurements", int, 64)

        # Number of workload thread running
        self.thread_count = libperf.getArgument(arglist, "thread_count", int, 64)

        # Delay before doing measurements to allow the workload to settle
        self.pretest_delay = libperf.getArgument(arglist, "pretest_delay", int, 60)

        # Command which execution time to measure
        self.command = libperf.getArgument(arglist, "command", str, "xe vm-list")
        self.dom0vcpus = libperf.getArgument(arglist, "dom0vcpus", int, None)

        # Timeout of ssh command executing measurements
        self.timeout = libperf.getArgument(arglist, "timeout", int, 3600)

        # Mountpoint path to the builds archive
        self.mount_path = libperf.getArgument(arglist, "mount_path", str, "backup-storage-cbg2.uk.xensource.com:/containers/builds_archive")

    def copyToDom0(self, script, filename):
        tmpdir = xenrt.resources.TempDirectory()

        script_file = "%s/%s" % (tmpdir.path(), filename)
        f = open(script_file, 'w')
        f.write(script)
        f.close()

        sftp = self.host.sftpClient()
        sftp.copyTo(script_file, "/root/%s" % filename)
        sftp.close()

    def copyFromDom0(self, src, dest):
        sftp = self.host.sftpClient()
        sftp.copyFrom(src, dest)
        sftp.close()

    def installPackages(self):
        self.host.execdom0("""BUILD_NUMBER=0x
eval $(grep ^BUILD_NUMBER= /etc/xensource-inventory)
BN=$(echo $BUILD_NUMBER | sed 's/[A-Za-z]*//g')
mount %s /mnt
MNT_PATH=$(find /mnt/carbon/ -maxdepth 2 -name $BN)
rpm -i --replacepkgs $MNT_PATH/binary-packages/RPMS/domain0/RPMS/x86_64/kernel-devel-* || true
""" % (self.mount_path))

    def prepareWorkloadModule(self):
        makefile = """obj-m += workload.o

all:
	make -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules
"""

        workload = """#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kthread.h>
#include <linux/sched.h>

MODULE_LICENSE("GPL");

#define KTHREAD_NUM_MAX 1024

static int KTHREAD_NUM = 4;
module_param(KTHREAD_NUM, int, 4);

static struct task_struct *threads[KTHREAD_NUM_MAX];

static int workload_thread(void* data)
{
     while (1) {
        schedule();

        if (kthread_should_stop()) {
                break;
        }
     }

     return 0;
}

int workload_init(void)
{
     int i;

     if (KTHREAD_NUM > KTHREAD_NUM_MAX) {
        KTHREAD_NUM = KTHREAD_NUM_MAX;
        printk(KERN_ALERT "workload: Max workload thread count "
                          "is %d: \\n", KTHREAD_NUM_MAX);
     }

     for (i = 0; i < KTHREAD_NUM; ++i) {
        threads[i] = kthread_run(workload_thread, 0, "workload_thread");
     }

     return 0;
}

void workload_exit(void)
{
     int i;

     for (i = 0; i < KTHREAD_NUM; ++i) {
        kthread_stop(threads[i]);
     }
}

module_init(workload_init);
module_exit(workload_exit);
"""
        self.copyToDom0(makefile, "Makefile")
        self.copyToDom0(workload, "workload.c")

    def prepareScript(self):
        script = """#!/bin/bash

for i in {1..%d}; do time %s; done 2>&1 | grep real | cut -d"m" -f 2 | cut -d"s" -f 1
""" % (self.measurements, self.command)

        self.copyToDom0(script, "test.sh")

    def compileWorkloadModule(self):
        self.host.execdom0("cd /root && make")

    def prepareDom0(self):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)
        self.installPackages()
        self.prepareScript()
        self.prepareWorkloadModule()
        self.compileWorkloadModule()

    def runTest(self):
        self.host.execdom0("cd /root && insmod workload.ko KTHREAD_NUM=%d" % self.thread_count)

        time.sleep(self.pretest_delay)

        self.host.execdom0("cd /root && chmod +x ./test.sh && ./test.sh > /root/response.log", timeout=self.timeout)

        self.host.execdom0("cd /root && rmmod workload.ko")

        self.copyFromDom0("/root/response.log", "%s/response.log" % xenrt.TEC().getLogdir())

    def run(self, arglist=None):
        self.prepareDom0()

        self.runTest()
