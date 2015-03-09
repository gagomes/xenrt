from server import PageFactory
from app import XenRTPage

class XenRTUIPage(XenRTPage):
    def loggedInAs(self):
        if self.getUser():
            return "Logged in as %s" % self.getUser().userid
        else:
            return "Not logged in"

    def render(self):
        commonhead = """
   <meta charset='utf-8'>
   <meta http-equiv="X-UA-Compatible" content="IE=edge">
   <meta name="viewport" content="width=device-width, initial-scale=1">
   <link rel="stylesheet" href="/xenrt/static/menu.css">
   <script src="/xenrt/static/js/jquery-1.11.2.js" type="text/javascript"></script>
   <script src="/xenrt/static/js/jquery-ui/jquery-ui.js"></script>
   <link rel="stylesheet" href="/xenrt/static/js/jquery-ui/jquery-ui.css">
  <style>
    #mainbody {
      font-family: "Trebuchet MS", "Helvetica", "Arial",  "Verdana", "sans-serif";
      font-size: 80%;
    }
    #user {
      font-family: "Trebuchet MS", "Helvetica", "Arial",  "Verdana", "sans-serif";
      font-size: 80%;
    }
    #overlay { position: fixed; left: 0px; top: 0px; width: 100%; height: 100%; opacity: .6; filter: alpha(opacity=60); z-index: 1000; background-color: #000000; display:none}
    #loading { position: fixed; left: 50%; top: 100px; width: 32px; height: 32px; padding: 0px; border: 2px solid Silver; background: url(/xenrt/static/js/ajax-loader.gif); z-index: 2000; display:none}

  </style>
"""

        commonbody = ""

        if self.request.params.get("menu") != "false":
            commonbody += """
<div id="overlay"></div>
<div id="loading"></div>

<div id='cssmenu'>
<ul>
   <li><a href='/xenrt/ui/'><span>Home</span></a></li>
   <li class='has-sub'><a href='#'><span>Lab</span></a>
     <ul>
       <li><a href='/xenrt/ui/machines'><span>Machines</span></a></li>
     </ul>
   </li>
   <li><a href='/xenrt/ui/logs'><span>Browse logs</span></a></li>
   <li class='has-sub'><a href='#'><span>API</span></a>
      <ul>
         <li><a href='/xenrt/swagger' target="_blank"><span>API Documentation</span></a></li>
         <li><a href='/xenrt/ui/apikey'><span>Manage my API Key</span></a></li>
         <li><a href='/xenrtapi.tar.gz'><span>CLI/Python bindings Download (install with pip)</span></a></li>
         <li><a href='/xenrtapi' target='_blank'><span>Python module documentation</span></a></li>
      </ul>
   </li>
   <li class='has-sub'><a href='#'><span>XenRTCenter</span></a>
     <ul>
         <li><a href='http://qa-01.xenrt.citrite.net/XRTCINSTALL/StartXenRTCenter.exe' target="_blank"><span>Download</span></a></li>
         <li><a href='https://info.citrite.net/display/CPGQA/XenRTCenter' target="_blank"><span>Documentation</span></a></li>
     </ul>
   </li>
   <li class='has-sub last'><a href='#'><span>Administration</a>
     <ul>
       <li class='has-sub'><a href='#'><span>Jenkins</span></a>
         <ul>
             <li><a href='http://ci.xenrt.citrite.net' target="_blank"><span>XenRT CI</span></a></li>
             <li><a href='http://jenkins1.xenrt.citrite.net:8080' target="_blank"><span>XenRT Maintenance</span></a></li>
         </ul>
       </li>
     </ul>
   </li>
</ul>i
<div id='righttitle'>Citrix XenRT</div>
            """
        commonbody += """
</div>
<p>
<div id="user"><div style="float:right">%s</div></div>
</p>""" % self.loggedInAs()
        return {"commonhead": commonhead, "commonbody": commonbody}
    
PageFactory(XenRTUIPage, "/ui", renderer="__main__:templates/ui/index.mak")
PageFactory(XenRTUIPage, "/ui/", renderer="__main__:templates/ui/index.mak")
PageFactory(XenRTUIPage, "/ui/logs", renderer="__main__:templates/ui/logs.mak")
PageFactory(XenRTUIPage, "/ui/apikey", renderer="__main__:templates/ui/apikey.mak")
PageFactory(XenRTUIPage, "/ui/machines", renderer="__main__:templates/ui/machines.mak")
PageFactory(XenRTUIPage, "/ui/machine", renderer="__main__:templates/ui/machine.mak")
