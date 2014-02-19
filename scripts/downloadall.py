#!/usr/bin/python
import subprocess, sys, tempfile, os, tarfile, shutil

jobid = int(sys.argv[1])
print "Retrieving all logs for jobid %d" % jobid

testData = subprocess.Popen("xenrt showlog %d" % jobid, stdout=subprocess.PIPE, shell=True).stdout.read()
tests = []
for t in testData.splitlines():
    ts = t.split()
    if len(ts) == 3:
        tests.append((ts[0],ts[1]))

# Make a temporary directory
tempDir = tempfile.mkdtemp()
# Download each tests logs in to it, in addition to the job logs
testFiles = []
for t in tests:
    rc = os.system("xenrt download %d -f %s/%s_%s.tar.bz2 -g %s -t %s > /dev/null 2>&1" % (jobid, tempDir, t[0], t[1], t[0], t[1]))
    if rc == 0:
        testFiles.append(t)
    else:
        print "Logs missing for %s / %s" % (t[0], t[1])
os.system("xenrt download %d -f %s/job.tar.bz2" % (jobid, tempDir))

# Make an (uncompressed) tarball of all the individual tarballs
tar = tarfile.open("%d.tar" % jobid, "w")
for t in testFiles:
    tar.add("%s/%s_%s.tar.bz2" % (tempDir, t[0], t[1]), arcname="%s_%s.tar.bz2" % (t[0], t[1]))
tar.add("%s/job.tar.bz2" % (tempDir), arcname="job.tar.bz2")
tar.close()

shutil.rmtree(tempDir)

