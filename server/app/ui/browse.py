from server import PageFactory
from app import XenRTPage

import string, os, re, tempfile, mimetypes

import app.utils
from pyramid.httpexceptions import HTTPFound

class XenRTBrowseBase(XenRTPage):
    def render(self):
        if self.request.matchdict.has_key("type"):
            id = string.atoi(self.request.matchdict["id"])
            if self.request.matchdict["type"] == "job":
                self.job = id
                self.tarfile = app.utils.results_filename("", id)
            else:
                self.job = self.lookup_jobid(id)
                self.tarfile = app.utils.results_filename("test", id)
        else:
            id = self.lookup_detailid(int(self.request.matchdict['job']), self.request.matchdict['phase'], self.request.matchdict['test'])
            self.job = int(self.request.matchdict['job'])
            self.tarfile = app.utils.results_filename("test", id)
        details = self.get_job(self.job)
        if details.has_key("LOG_SERVER") and details["LOG_SERVER"] != self.request.host:
            return HTTPFound(location="http://%s%s" % (details["LOG_SERVER"], self.request.path)) 
        
        return self.doRender()
        
class XenRTBrowseFiles(XenRTBrowseBase):
    def doRender(self):
        if os.path.exists("%s.index" % self.tarfile):
            indexFH = open("%s.index" % self.tarfile)
            createIndex = False
        else:
            indexFH = os.popen("tar -jvtf %s" % (self.tarfile))
            createIndex = True

        self.index = indexFH.readlines()
        indexFH.close()

        if createIndex and len(self.index) > 0:
            try:
                f = open("%s.index" % self.tarfile, "w")
                for l in self.index:
                    f.write(l)
                f.close()
            except:
                pass

        return self.doListing()

    def isBinary(self, fname):
        if string.split(fname, ".")[-1] in ('gz',
                                           'tgz',
                                           'bz2',
                                           'tbz2',
                                           'zip',
                                           'exe',
                                           'jpg',
                                           'jpeg',
                                           'png',
                                           'gif'):
            return True
        else:
            return False


class XenRTBrowse(XenRTBrowseFiles):
    def doListing(self):
        out = ""
        for line in self.index:
            line = string.strip(line)
            all = line.split()
            line = " ".join(all[5:len(all)])
            rawsize = int(all[2])
            if rawsize > 1024:
                size = rawsize / 1024
                if size > 1024:
                    size = size / 1024
                    size = "%uM" % (size)
                else:
                    size = "%uK" % (size)
            else:
                size = "<1K"
            if line[0:2] == "./":
                dline = line[2:]
            else:
                dline = line
            if line[0:2] == "./":
                dline = line[2:]
            else:
                dline = line


            if line [-1:] == "/":
                continue
            if self.isBinary(line):
                out += "<BR><A href=\"binary/%s\">%s (%s)</A>" % (line, dline, size)
            elif dline.strip() == "xenrt.log":
                out += "<BR><A href=\"html/%s\">%s (%s)</A> " \
                      "(<A href=\"binary/%s\">raw</A>) <b>(<A href=\"folded/%s\">folded</A>)</b>" % \
                      (line, dline, size, line, line)
            else:
                out += "<BR><A href=\"html/%s\">%s (%s)</A> " \
                      "(<A href=\"binary/%s\">raw</A>)" % \
                      (line, dline, size, line)
        return {"title": "Log Browser for job %s" % self.job, "main": out }
        
class XenRTBrowseJSON(XenRTBrowseFiles):
    def doListing(self):
        out = {"files": {}}
        for line in self.index:
            all = line.split()
            size = int(all[2])
            fname = " ".join(all[5:len(all)])
            if fname.endswith("/"):
                continue
            if fname[0:2] == "./":
                fname = fname[2:]
            out["files"][fname] = {}
            out["files"][fname]["size"] = size
            baseurl = "/".join(self.request.url.split("/")[:-1])
            out["files"][fname]["binary"] = "%s/binary/%s" % (baseurl, fname)
            if not self.isBinary(fname):
                out["files"][fname]["html"] = "%s/html/%s" % (baseurl, fname)
            elif fname == "xenrt.log":
                out["files"][fname]["folded"] = "%s/folded/%s" % (baseurl, fname)
        return out

class XenRTBrowseFile(XenRTBrowseBase):

    def render(self):
        self.length = 0
        return super(XenRTBrowseFile, self).render()

    def getFD(self):
        self.filename = "./%s" % "/".join(self.request.matchdict['file'])
        self.size = None
        if os.path.exists("%s.index" % self.tarfile):
            f = open("%s.index" % self.tarfile)
            for l in f.readlines():
                ll = l.split()
                fname = " ".join(ll[5:len(ll)])
                size = int(ll[2])
                if fname == self.filename:
                    self.size = size
                    break
            f.close()
        return os.popen('tar -jxf %s -O "%s"' % (self.tarfile, self.filename))

    def write(self, text):
        self.outfd.write(text)
        self.length += len(text)

class XenRTBrowseHTML(XenRTBrowseFile):

    def doRender(self):
        out = ""
        fd = self.getFD()
        line = fd.readline()
        self.outfd = tempfile.NamedTemporaryFile(delete=True)
        if not line:
            line = ""
        if re.search("<html>", line, re.IGNORECASE) or \
           self.filename.endswith(".html") or \
           self.filename.endswith(".htm") or \
           self.filename.endswith(".css") or \
           self.filename.endswith(".js"):
            dataishtml = True
        else:
            dataishtml = False

        if not dataishtml:
            header = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
  <head>
    <title>XenRT: Log browser: %s</title>
  </head>
  <body><pre>""" % self.filename
            self.write(header)

        while 1:
            if not dataishtml:
                line = string.replace(line, "<", "&lt;")
                line = string.replace(line, ">", "&gt;")
#            else:
#                for x in ("href", "HREF", "src", "SRC"):
#                    line = re.sub(r"%s=\"([^/]+?)\"" % (x),
#                                  "%s=\"%s\\1\"" % (x, base),
#                                  line)
            self.write(line)
            line = fd.readline()
            if not line:
                break
        if not dataishtml:
            footer = "</pre></body></html>"

            self.write(footer)

        fd.close()

        self.outfd.seek(0)

        self.request.response.body_file = self.outfd
        self.request.response.content_length=self.length
        self.request.response.content_type="text/html"

        return self.request.response

class XenRTBrowseFolded(XenRTBrowseFile):
    def doRender(self):
        self.fd = self.getFD()
        self.outfd = tempfile.NamedTemporaryFile(delete=True)
        self.processXenRTLog()
        self.outfd.seek(0)

        self.request.response.body_file = self.outfd
        self.request.response.content_length=self.length
        self.request.response.content_type="text/html"

        return self.request.response

    def processXenRTLog(self):
        self.write("""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
    <head>
    <title>XenRT Log</title>
    <script language = "javascript">
    var max = 0;
    function toggle(id)
        {
        if (document.getElementById('block' + id).style.display == 'table')
            {
            document.getElementById('block' + id).style.display='none'
            }
        else
            {
            document.getElementById('block' + id).style.display='table';
            }
        }

    function expandAll()
        {
        for (i = 0; i < max; i++)
            {
            document.getElementById('block' + i).style.display='table';
            }
        }

    function collapseAll()
        {
        for (i = 0; i < max; i++)
            {
            document.getElementById('block' + i).style.display='none';
            }
        }

    </script>
    </head>
    <body>
    <pre>
<a href="javascript:expandAll()">Expand All</a> <a href="javascript:collapseAll()">Collapse All</a>
""")
        inVerboseBlock = False
        blockCount = 0
        for l in self.fd.readlines():
            l = self.htmlEscape(l)
            if not inVerboseBlock:
                if re.match("^\[VERBOSE\]", l):
                    inVerboseBlock = True
                    verboseText = "%s\n" % l.rstrip()
                else:
                    self.nonverbLine(l)
            else:
                if not re.match("^\[VERBOSE\]", l) and re.match("^\[[A-Z]+\]", l):
                    inVerboseBlock = False
                    self.verboseSection(verboseText, blockCount)
                    self.nonverbLine(l)
                    blockCount += 1
                else:
                    verboseText += "%s\n" % l.rstrip()
        if inVerboseBlock:
            self.verboseSection(verboseText, blockCount)
            blockCount += 1
        self.write("<script language=\"javascript\">max=%d;</script>" % blockCount)
        self.write("<a href=\"javascript:expandAll()\">Expand All</a> <a href=\"javascript:collapseAll()\">Collapse All</a>")

        self.write("</pre></body></html>")

    def verboseSection(self, text, index):
        self.write("<a href=\"javascript:toggle(%d)\">(%d verbose lines)</a></pre>\n" % (index, len(text.splitlines())))
        self.write("<div id=\"block%d\" style=\"display:none;background-color:#DDDDDD;margin-left:30px\">\n<pre>" % index)
        self.write(text)
        self.write("</pre></div><pre>")
        
    def nonverbLine(self, l):
        s = l.rstrip()
        if re.match("^\[REASON\]", s):
            self.write('<span style="background-color: #FF5555;">%s</span>\n' % s)
        else:
            self.write("%s\n" % s)

                
    def htmlEscape(self, line):
        out = re.sub("&", "&amp;", line)
        out = re.sub("<", "&lt;", out)
        out = re.sub(">", "&gt;", out)
        return out

class XenRTBrowseBinary(XenRTBrowseFile):
    def doRender(self):
        fd = self.getFD()
        self.request.response.body_file = fd
        (ctype, encoding) = mimetypes.guess_type(self.filename)
        if not ctype:
            if self.filename.endswith("/messages") \
                    or self.filename.endswith(".log") \
                    or self.filename.endswith(".out") \
                    or self.filename.endswith("/SMlog") \
                    or self.filename.endswith("/syslog"):
                ctype = "text/plain"
            elif self.filename.endswith(".db"):
                ctype = "application/xml"
            else:
                ctype = "application/octet-stream"
        self.request.response.content_type = ctype
        if encoding:
            self.request.response.content_encoding=encoding
        if self.size:
            self.request.response.content_length=self.size
            

        return self.request.response
    
PageFactory(XenRTBrowse, "/logs/{type}/{id}/browse", renderer="__main__:templates/default.pt")
PageFactory(XenRTBrowse, "/logs/job/{job}/{phase}/{test}/browse", renderer="__main__:templates/default.pt")
PageFactory(XenRTBrowseJSON, "/logs/{type}/{id}/jsonlist", contentType="application/json")
PageFactory(XenRTBrowseJSON, "/logs/job/{job}/{phase}/{test}/jsonlist", contentType="application/json")
PageFactory(XenRTBrowseHTML, "/logs/{type}/{id}/html/*file", renderer=None)
PageFactory(XenRTBrowseHTML, "/logs/job/{job}/{phase}/{test}/html/*file", renderer=None)
PageFactory(XenRTBrowseBinary, "/logs/{type}/{id}/binary/*file", renderer=None)
PageFactory(XenRTBrowseBinary, "/logs/job/{job}/{phase}/{test}/binary/*file", renderer=None)
PageFactory(XenRTBrowseFolded, "/logs/{type}/{id}/folded/*file", renderer=None)
PageFactory(XenRTBrowseFolded, "/logs/job/{job}/{phase}/{test}/folded/*file", renderer=None)
