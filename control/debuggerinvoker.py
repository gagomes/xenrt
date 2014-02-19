#!/usr/bin/python
import sys, string, pickle, xenrt, os
sys.path.append('/usr/share/xenrt/%s-exec/xenrt/lib/debugger'%(sys.argv[1]))
import breakpoint2, codegen
try:
    breakpoint2.Starter_Func(sys.argv[1])
    fileObj = open('/usr/share/xenrt/results/jobs/%s/jobData'%(sys.argv[1]),'rb')
    debugList = pickle.load(fileObj)
    fileObj.close()
    jobid = sys.argv[1]
    debug = debugList[0]
    logserver = debugList[1]
    cmd = debugList[2]
    com = xenrt.Commands(raw = 1)
    if not debug:
        if logserver:
            com.run("update", [jobid, "LOG_SERVER", "%s" % logserver])
        pid = os.spawnv(os.P_NOWAIT, cmd[0], cmd)
        com.run("update", [jobid, "HARNESS_PID", "%u" % (pid)])
except Exception as e:
    com.run("update", [jobid, "FAILED", "%s"%(e)])



