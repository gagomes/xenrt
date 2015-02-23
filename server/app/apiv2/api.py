from app.apiv2 import *
from pyramid.httpexceptions import *
import base64
import hashlib
import random

class _APIKeyBase(XenRTAPIv2Page):
    WRITE = True
    ALLOW_FAKE_USER=False

    def _removeAPIKey(self):
        user = self.getUser()
        cur = self.getDB().cursor()
        try:
            cur.execute("UPDATE tblusers SET apikey=NULL WHERE userid=%s", [user])
        finally:
            cur.close()
            

    def _generateNewAPIKey(self):
        self._removeAPIKey()
        user = self.getUser()
        cur = self.getDB().cursor()
        try:
            cur.execute("DELETE FROM tblusers WHERE userid=%s", [user])
            key = base64.b64encode(hashlib.sha224( str(random.getrandbits(256)) ).digest())[:38]
            cur.execute("INSERT INTO tblusers(userid, apikey) VALUES(%s,%s)", [user, key])
        finally:
            cur.close()

    def _getAPIKey(self, generate=True):
        user = self.getUser()
        cur = self.getDB().cursor()
        cur.execute("SELECT apikey FROM tblusers WHERE userid=%s", [user])
        rc = cur.fetchone()
        if not rc or not rc[0]:
            if generate:
                self._generateNewAPIKey()
                return self._getAPIKey(generate=False)
            return None
        return rc[0]

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
        key = self._getAPIKey()
        self.getDB().commit()
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
        self._removeAPIKey()
        self.getDB().commit()
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
        key = self._generateNewAPIKey()
        self.getDB().commit()
        return {"key": self._getAPIKey(generate=False)}

RegisterAPI(ReplaceAPIKey)
RegisterAPI(GetAPIKey)
RegisterAPI(RemoveAPIKey)
