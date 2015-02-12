from server import PageFactory
from app import XenRTPage

class XenRTUIHome(XenRTPage):
    def render(self):
        body = """
<h2>Welcome to XenRT</h2>
<p>To get started, please choose a link above</p>
"""
        return {"head": "", "body": body, "title": "Home"}

PageFactory(XenRTUIHome, "/ui", renderer="__main__:templates/newui.pt")
PageFactory(XenRTUIHome, "/ui/", renderer="__main__:templates/newui.pt")
import app.uiv2.logs
import app.uiv2.apikeys
