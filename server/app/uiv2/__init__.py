from server import PageFactory
from app import XenRTPage

class XenRTUIPage(XenRTPage):
    def loggedInAs(self):
        if self.getUser():
            return "Logged in as %s" % self.getUser()
        else:
            return "Not logged in"

class XenRTUIHome(XenRTUIPage):
    def render(self):
        body = """
<h2>Welcome to XenRT</h2>
<p>To get started, please choose a link above</p>
"""
        return {"head": "", "body": body, "title": "Home", "user": self.loggedInAs()}

PageFactory(XenRTUIHome, "/ui", renderer="__main__:templates/newui.pt")
PageFactory(XenRTUIHome, "/ui/", renderer="__main__:templates/newui.pt")
import app.uiv2.logs
import app.uiv2.apikeys
