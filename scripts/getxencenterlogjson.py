#!/usr/bin/python

import sys, xmlrpclib,json, re
s = xmlrpclib.ServerProxy("http://%s:8936" % sys.argv[1])
files = s.globpath("%s\\Citrix\\XenCenter\\Logs\\*.log" % s.getEnvVar("APPDATA"))
ret = {"logfiles":{}}
for f in files:
    ret['logfiles'][f.rsplit("\\")[-1]] = s.readFile(f).data

try:
    ret['winversion'] = s.readFile("c:\\winversion.txt").data.strip()
except:
    ret['winversion'] = None

ret['xcversion'] = None
try:
    progfiles = None
    try:
        progfiles = s.getEnvVar("ProgramFiles(x86)")
    except:
        pass
    if not progfiles:
        progfiles = s.getEnvVar("ProgramFiles")
    verstring = s.runsync("""c:\\sigcheck\\sigcheck.exe /accepteula "%s\\Citrix\\XenCenter\\XenCenter.exe" || echo""" % progfiles)
    for l in verstring.splitlines():
        m = re.match("^\s*Version:\s*(.*)", l)
        if m:
            ret['xcversion'] = m.group(1).strip()
except:
    pass

print json.dumps(ret)
    
