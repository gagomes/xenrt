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
import time, ConfigParser, xenrtapi, requests, pipes
import xenrt

__all__ = ["DBConnect", "APIFactory"]

class DBConnect(object):

    def __init__(self, jobid):
        if jobid == None:
            self._jobid = None
        else:
            self._jobid = int(jobid)
        self._bufferdir = xenrt.GEC().config.lookup("DB_BUFFER_DIR", None)
        if self._bufferdir and not os.path.exists(self._bufferdir):
            os.makedirs(self._bufferdir)

        self._api = None

    def jobid(self):
        return self._jobid

    @property
    def api(self):
        if not self._api:
            self._api = APIFactory()
        return self._api
        

    def detailid(self, phase, test):
        jobid = self.jobid()
        job = self.api.get_job(jobid)
        detailids = [x['detailid'] for x in job['results'].values() if x['phase'] == phase and x['test'] == test]
        if detailids:
            return detailids[0]
        return None

    def jobctrl(self, command, args, bufferfile=None):
        commandline = "%s %s" % (command, string.join([pipes.quote(x) for x in args]))
        xenrt.TEC().logverbose("XenRT CLI %s" % (commandline))
        try:
            return xenrt.util.command("xenrtnew %s" % commandline)
        except:
            if not buffer:
                raise
            if not self._bufferdir:
                raise
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
                    except:
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

    def jobUpdate(self, field, value):
        j = self.jobid()
        if j:
            self.jobctrl("update", ["%u" % (j), field, value])

    def jobComplete(self):
        j = self.jobid()
        if j:
            self.jobctrl("complete", ["%u" % (j)])

    def jobStart(self):
        j = self.jobid()
        if j:
            self.jobctrl("start", ["%u" % (j)])

    def jobSetResult(self, phase, test, result):
        j = self.jobid()
        if j:
            self.jobctrl("setresult", ["%u" % (j), phase, test, result])

    def jobSubResults(self, phase, test, filename):
        j = self.jobid()
        if j:
            self.jobctrl("subresults",
                         ["%u" % (j), phase, test, "-f", filename],
                         bufferfile = filename)

    def jobLogData(self, phase, test, key, value):
        j = self.jobid()
        if j:
            self.jobctrl("logdata", ["%u" % (j), phase, test, key, value])

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
            self.jobctrl("upload", args, bufferfile=f)

    def jobDownload(self, filename, jobid=None):
        if jobid:
            j = jobid
        else:
            j = self.jobid()
        if j:
            attempt = 3
            lasterr = None
            while attempt > 0:
                try:
                    url = self.api.get_job_attachment_pre_run(j, filename)
                    r = requests.get(url)
                    r.raise_for_status()
                    result = r.content
                    break
                except Exception, e:
                    xenrt.TEC().logverbose("Error during download: %s" %
                                           (str(e)))
                    lasterr = e
                    xenrt.sleep(10)
                attempt = attempt - 1
            if not lasterr:
                return result
            
            # Try and download the file form the last job
            details = self.api.get_job(j)['params']
            if 'ORIGINAL_JOBID' in details:
                return self.jobDownload(filename, jobid=int(details['ORIGINAL_JOBID']))
            
            raise lasterr


    def jobEmail(self):
        j = self.jobid()
        if j:
            self.jobctrl("email", ["%u" % (j)])

    def perfUpload(self, filename):
        j = self.jobid()
        if j or xenrt.TEC().lookup("PERF_UPLOAD", False, boolean=True):
            self.jobctrl("perfdata", ["-f", filename],
                         bufferfile=filename)


@xenrt.irregularName
def APIFactory():
    config = ConfigParser.ConfigParser()
    if not config.read("%s/.xenrtrc" % os.path.expanduser("~")):
        raise xenrt.XRTError("Could not read .xenrtrc config file")
    apikey = config.get("xenrt", "apikey").strip()
    try:
        server = config.get("xenrt", "server").strip()
    except:
        server = None
    return xenrtapi.XenRT(apikey=apikey, server=server)
