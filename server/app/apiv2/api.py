from app.apiv2 import *
from pyramid.httpexceptions import *

class _APIKeyBase(XenRTAPIv2Page):
    WRITE = True
    ALLOW_FAKE_USER=False

    def _getOrGenerateAPIKey(self):
        user = self.getUser()
        if not user.apiKey and generate:
            user.generateNewApiKey()
        return user.apiKey

class GetAPIKey(_APIKeyBase):
    PATH = "/apikey"
    REQTYPE = "GET"
    SUMMARY = "Get API key for logged in User"
    RESPONSES = { "200": {"description": "Successful response"}}
    PARAMS = []
    TAGS = ["apikeys"]
    OPERATION_ID = "get_apikey"
    RETURN_KEY = "key"

    def render(self):
        key = self._getOrGenerateAPIKey()
        return {"key": key}

class RemoveAPIKey(_APIKeyBase):
    PATH = "/apikey"
    REQTYPE = "DELETE"
    SUMMARY = "Remove API key for logged in User"
    RESPONSES = { "200": {"description": "Successful response"}}
    PARAMS = []
    TAGS = ["apikeys"]
    OPERATION_ID = "remove_apikey"

    def render(self):
        self.getUser().removeAPIKey()
        return {}

class ReplaceAPIKey(_APIKeyBase):
    PATH = "/apikey"
    REQTYPE = "PUT"
    SUMMARY = "Replace API key for logged in User"
    RESPONSES = { "200": {"description": "Successful response"}}
    PARAMS = []
    TAGS = ["apikeys"]
    OPERATION_ID = "replace_apikey"

    def render(self):
        self.getUser().generateNewAPIKey()
        return {"key": self.getUser().apiKey}

RegisterAPI(ReplaceAPIKey)
RegisterAPI(GetAPIKey)
RegisterAPI(RemoveAPIKey)
