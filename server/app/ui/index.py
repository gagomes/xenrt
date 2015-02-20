from server import PageFactory
from app import XenRTPage
from pyramid.httpexceptions import *

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

class XenRTFrame(XenRTPage):
    def render(self):
        url = "/xenrt/ui/logs"
        if self.request.query_string:
            url += "?%s" % self.request.query_string
        return HTTPFound(location=url)

class XenRTBlank(XenRTPage):
    def render(self):
        return ""

class XenRTDetailFrame(XenRTPage):
    def render(self):
        url = "/xenrt/ui/logs"
        url += "?menu=false&%s" % self.request.query_string
        return HTTPFound(location=url)

PageFactory(XenRTIndex, "/")
PageFactory(XenRTFrame, "/frame")
PageFactory(XenRTFrame, "/minimalframe")
PageFactory(XenRTDetailFrame, "/detailframe")
PageFactory(XenRTBlank, "/blank")
