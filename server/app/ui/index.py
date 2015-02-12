from server import PageFactory
from app import XenRTPage

class XenRTIndex(XenRTPage):
    def render(self):
        return HTTPFound(location="/xenrt/ui/")

class XenRTJobQuery(XenRTPage):
    def render(self):
        out = """
        <TABLE border="0"><TR>
          <TD valign="top"><FORM action="matrix" method="POST" target=\"matrix\">
            Jobs:&nbsp;<INPUT type="text" name="jobs" width=12>
            <INPUT type="submit" value="Display">&nbsp;&nbsp;
            </FORM>
          </TD>
        </TR></TABLE>
    """
        return {"title": "Job Query", "main": out}

class XenRTBlank(XenRTPage):
    def render(self):
        return {"title": "", "main": ""}

class XenRTFrame(XenRTPage):
    def render(self):
        matrix = "blank"
        jobdetail = "blank"
        testdetail = "blank"
        if self.request.params.has_key("jobs"):
            matrix = "matrix?jobs=%s" % self.request.params["jobs"]
        elif self.request.params.has_key("detailid"):
            matrix = "matrix?detailid=%s" % self.request.params["detailid"]
            testdetail = "detailframe?detailid=%s" % self.request.params["detailid"]

        return {"matrix":matrix, "jobdetail": jobdetail, "testdetail":testdetail}

class XenRTMinimalFrame(XenRTPage):
    def render(self):
        matrix = "blank"
        jobdetail = "blank"
        testdetail = "blank"
        if self.request.params.has_key("jobs"):
            matrix = "matrix?jobs=%s" % self.request.params["jobs"]
        elif self.request.params.has_key("detailid"):
            matrix = "matrix?detailid=%s" % self.request.params["detailid"]
            testdetail = "detailframe?detailid=%s" % self.request.params["detailid"]

        return {"matrix":matrix, "jobdetail": jobdetail, "testdetail":testdetail}

PageFactory(XenRTIndex, "/", renderer="__main__:templates/frames.pt")
PageFactory(XenRTBlank, "/blank", renderer="__main__:templates/default.pt")
PageFactory(XenRTJobQuery, "/jobquery", renderer="__main__:templates/default.pt")
PageFactory(XenRTFrame, "/frame", renderer="__main__:templates/frames.pt")
PageFactory(XenRTMinimalFrame, "/minimalframe", renderer="__main__:templates/minimalframes.pt")
