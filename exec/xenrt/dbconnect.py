#
# XenRT: Test harness for Xen and the XenServer product family
#
# Interface to the results database and job server.
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, xml.dom.minidom, os.path, os, shutil, tempfile, fcntl, stat
import time
import xenrt

__all__ = ["DBConnect"]

class DBConnect:

    def __init__(self, jobid, ctrl):
        if jobid == None:
            self._jobid = None
        else:
            self._jobid = int(jobid)
        self._ctrl = ctrl
        self._bufferdir = xenrt.GEC().config.lookup("DB_BUFFER_DIR", None)
        if self._bufferdir and not os.path.exists(self._bufferdir):
            os.makedirs(self._bufferdir)

    def jobid(self):
        return self._jobid

    def detailid(self, phase, test):
        jobid = self.jobid()
        if jobid:
            did = self.jobctrl("detailid", [str(jobid),phase,test])
            if did:
                return did.strip()
        return None

    def ctrl(self):
        return self._ctrl

    def jobctrl(self, command, args, buffer=False, bufferfile=None):
        commandline = "%s %s" % (command, string.join(args))
        xenrt.TEC().logverbose("XenRT CLI %s" % (commandline))
        try:
            rc = self._ctrl.run(command, args)
            if command == "upload" and not rc:
                raise IOError("upload error")
            return rc
        except IOError, e:
            if not buffer:
                raise e
            if not self._bufferdir:
                raise e
            xenrt.TEC().logverbose("BUFFERING: %s" % (commandline))
            # If we've got a file then copy it and replace references to it
            # in the command
            if bufferfile:
                f, fn = tempfile.mkstemp("", "buffile", self._bufferdir)
                os.close(f)
                os.chmod(fn,
                         stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | \
                         stat.S_IXOTH)
                shutil.copy(bufferfile, fn)
                for i in range(len(args)):
                    args[i] = string.replace(args[i], bufferfile, fn)
            for i in range(len(args)):
                args[i] = string.replace(args[i], "\t", " ")
            f = file("%s/bufferedcommands" % (self._bufferdir), "a")
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
                x = ["COMMAND", command]
                x.extend(args)
                f.write("%s\n" % (string.join(x, "\t")))
                if bufferfile:
                    f.write("FILE\t%s\n" % (fn))
            finally:
                f.close()
            return None

    def replay(self):
        if not self._bufferdir:
            raise xenrt.XRTError("No buffer directory")
        fn = "%s/bufferedcommands" % (self._bufferdir)
        if not os.path.exists(fn):
            return
        items = []
        f = file(fn, "r+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            while True:
                line = f.readline()
                if not line:
                    break
                line = string.strip(line)
                l = string.split(line, "\t")
                if len(l) == 0:
                    continue
                items.append(l)
            f.seek(0)
            f.truncate(0)
        finally:
            f.close()
        notdone = []
        ok = True
        for item in items:
            if item[0] == "COMMAND":
                if len(item) < 2:
                    xenrt.TEC().logverbose("No command in COMMAND line")
                else:
                    try:
                        self.jobctrl(item[1], item[2:])
                        ok = True
                    except IOError:
                        xenrt.TEC().logverbose("Replayed command failed")
                        notdone.append(item)
                        ok = False
            elif item[0] == "FILE":
                if ok:
                    if len(item) < 2:
                        xenrt.TEC().logverbose("No file in FILE line")
                    else:
                        tfn = item[1]
                        try:
                            os.unlink(tfn)
                        except:
                            xenrt.TEC().logverbose("Unable to delete %s" %
                                                   (tfn))
                else:
                    notdone.append(item)
        # Write back any items we didn't replay
        f = file(fn, "a")
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            for item in notdone:
                f.write("%s\n" % (string.join(item, "\t")))
        finally:
            f.close()

    def jobProxy(self, proxy):
        self._ctrl.setProxies({'http': proxy})

    def jobUpdate(self, field, value):
        j = self.jobid()
        if j:
            self.jobctrl("update", ["%u" % (j), field, value], buffer=True)

    def jobComplete(self):
        j = self.jobid()
        if j:
            self.jobctrl("complete", ["%u" % (j)], buffer=True)

    def jobStart(self):
        j = self.jobid()
        if j:
            self.jobctrl("start", ["%u" % (j)], buffer=True)

    def jobSetResult(self, phase, test, result):
        j = self.jobid()
        if j:
            self.jobctrl("setresult", ["%u" % (j), phase, test, result],
                         buffer=True)

    def jobSubResults(self, phase, test, filename):
        j = self.jobid()
        if j:
            self.jobctrl("subresults",
                         ["%u" % (j), phase, test, "-f", filename],
                         buffer=True,
                         bufferfile = filename)

    def jobLogData(self, phase, test, key, value):
        j = self.jobid()
        if j:
            self.jobctrl("logdata", ["%u" % (j), phase, test, key, value],
                         buffer=True)

    def jobUpload(self, source, phase=None, test=None, prefix=None):
        j = self.jobid()
        if j:
            if os.path.isdir(source):
                f = xenrt.GEC().anontec.tempFile()
                cmd = "tar -jcf %s -C %s ." % (f, source)
                xenrt.TEC().logverbose("Executing %s" % (cmd))
                os.system(cmd)
            else:
                f = source
            args = []
            args.append("%u" % (j))
            if phase and test:
                args.extend(["-p", phase, "-t", test])
            if prefix:
                args.extend(["-P", prefix])
            args.extend(["-f", f])
            self.jobctrl("upload", args, buffer=True, bufferfile=f)

    def jobDownload(self, prefix=None, jobid=None, filename=None):
        if jobid:
            j = jobid
        else:
            j = self.jobid()
        if j:
            args = ["%u" % (j)]
            if prefix:
                args.append("-p")
                args.append(prefix)
            if filename:
                args.append("-f")
                args.append(filename)
            args.append("-o")
            lasterr = None
            result = None
            attempt = 3
            while attempt > 0:
                try:
                    result = self.jobctrl("download", args)
                    break
                except Exception, e:
                    xenrt.TEC().logverbose("Error during download: %s" %
                                           (str(e)))
                    if filename:
                        try:
                            os.unlink(filename)
                        except:
                            pass
                    lasterr = e
                    xenrt.sleep(10)
                attempt = attempt - 1
            if result is not None:
                return result
            if lasterr:
                raise lasterr
            details = self.jobctrl("status", [str(j)])
            if details and details.has_key('ORIGINAL_JOBID'):
                return self.jobDownload(prefix=prefix, jobid=int(details['ORIGINAL_JOBID']), filename=filename)
            else:
                raise xenrt.XRTError("Download failed")


    def jobEmail(self):
        j = self.jobid()
        if j:
            self.jobctrl("email", ["%u" % (j)], buffer=True)

    def perfUpload(self, filename):
        j = self.jobid()
        if j or xenrt.TEC().lookup("PERF_UPLOAD", False, boolean=True):
            self.jobctrl("perfdata", ["-f", filename],
                         buffer=True,
                         bufferfile=filename)

    def jobSubmit(self, args):
        return self.jobctrl("submit", args)

    def jobRemove(self, jobid):
        return self.jobctrl("remove", [str(jobid)])

    def makeTickets(self, suite, rev, findOld=False, branch=None):
        args = [] 
        if findOld:
            args.append("--findold")
        if branch:
            args.append("--branch=%s" % branch)
        args.append(suite)
        args.append(rev)
        return self.jobctrl("maketickets", args)

