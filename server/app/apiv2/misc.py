from app.apiv2 import *
from pyramid.httpexceptions import *
import config

class LogServer(XenRTAPIv2Page):
    PATH = "/logserver"
    REQTYPE = "GET"
    SUMMARY = "Get default log server"
    PARAMS = []
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    RETURN_KEY = "server"

    def render(self):
        return {"server": config.log_server }

RegisterAPI(LogServer)
