#!/usr/bin/python

import cgi,cgitb,tempfile,os,Cookie,datetime
cgitb.enable()

form = cgi.FieldStorage()

expiration = datetime.datetime.now() + datetime.timedelta(days=365)
cookie = Cookie.SimpleCookie()
cookie["user"] = form["user"].value 
cookie["user"]["path"] = "/"
cookie["user"]["expires"] = expiration.strftime("%a, %d-%b-%Y %H:%M:%S GMT")
cookie["email"] = form["email"].value 
cookie["email"]["path"] = "/"
cookie["email"]["expires"] = expiration.strftime("%a, %d-%b-%Y %H:%M:%S GMT")

print "Content-type:text/plain"
print cookie.output()
print

f, seqfilename = tempfile.mkstemp(".seq", "xenrt")
fh = os.fdopen(f, "w")
fh.write(form["seq"].value)
fh.close()

cmd = "xenrt %s --customseq %s" % (form["cmd"].value, seqfilename)

out = os.popen(cmd).read()

try:
    print "Job submitted as job %d, you will receive an email when the job is complete" % int(out)
except:
    print "Error submitting job with command %s, the error was %s" % (cmd,out)

os.unlink(seqfilename)
