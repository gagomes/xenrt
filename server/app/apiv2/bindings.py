#!/usr/bin/python

from app.apiv2 import XenRTAPIv2Swagger
from server import PageFactory

class Path(object):
    def __init__(self, parent, path, method, data, definitions):
        self.parent = parent
        self.path = path
        self.method = method
        self.data = data
        self.definitions = definitions
        self.args = ["self"]
        self.argdesc = []
        self.jsonParams = []
        self.formParams = []
        self.pathParams = []
        self.queryParams = []
        self.parseParams()

    @property
    def methodContent(self):
        ret = """        path = "%%s%s" %% (self.base)\n""" % self.path
        for p in self.pathParams:
            ret += """        path = path.replace("{%s}", %s)\n""" % (p, p)
        ret += """        paramdict = {}\n"""
        for p in self.queryParams:
            ret += """        if %s != None:\n            paramdict['%s'] = self.__serializeForQuery(%s)\n""" % (p, p, p)
        ret += """        payload = {}\n"""
        if self.jsonParams:
            ret += """        j = {}\n"""
            for p in self.jsonParams:
                ret += """        if %s != None:\n            j['%s'] = %s\n""" % (p, p, p)
            ret += """        payload = json.dumps(j)\n"""
        elif self.formParams:
            for p in self.formParams:
                ret += """        if %s != None:\n            payload['%s'] = %s\n""" % (p, p, p)
        if self.method == "get":
            ret += """        r = requests.get(path, params=paramdict, auth=(self.user, self.password))\n"""
        else:
            ret += """        r = requests.%s(path, params=paramdict, data=payload, auth=(self.user, self.password))\n""" % self.method
        ret += """        self.__raiseForStatus(r)\n"""
        ret += """        return r.json()"""
        return ret

    def parseParams(self):
        for p in self.data.get('parameters', []):
            if p['in'] == "body":
                objType = self.definitions[p['schema']['$ref'].split("/")[-1]]
                for q in [x for x in objType['properties'].keys() if x in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    self.args.append(q)
                    self.argdesc.append("%s: %s" % (q, objType['properties'][q]['description']))
                for q in [x for x in objType['properties'].keys() if x not in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    if objType['properties'][q]['type'] == "boolean":
                        default = "False"
                    else:
                        default = "None"
                    self.args.append("%s=%s" % (q, default))
                    self.argdesc.append("%s: %s" % (q, objType['properties'][q]['description']))
            else:
                if p['in'] == "path":
                    self.pathParams.append(p['name'])
                elif p['in'] == "query":
                    self.queryParams.append(p['name'])
                self.argdesc.append("%s: %s" % (p['name'], p['description']))
                if p.get('required'):
                    if not p.get('default'):
                        self.args.append(p['name'])
                    else:
                        if p['type'] == "string" or (p['type'] == "array" and p['items']['type'] == "string"):
                            default = "\"%s\"" % p['default']
                        else:
                            default = p['default']
                        self.args.append("%s=%s" % (p['name'], default))
                else:
                    if p.get('type') == "boolean":
                        default = "False"
                    else:
                        default = "None"
                    self.args.append("%s=%s" % (p['name'], default))

    @property
    def methodSignature(self):
        return "    def %s(%s):" % (self.methodName, self.methodParams)

    @property
    def description(self):
        ret = "        \"\"\" %s\n            Parameters:\n" % (self.data['description'])
        for p in self.argdesc:
            ret += "                 %s\n" % (p)
        ret += "        \"\"\""
        return ret

    @property
    def methodName(self):
        if self.data.get('operationId'):
            return self.data['operationId']
        ret = ""
        if self.method == "get":
            ret += "get_"
        name = self.path.split("{")[0]
        name = name.replace("/", "_")
        name = name.strip("_")
        ret += name
        return ret

    @property
    def methodParams(self):
        return ", ".join(self.args)

class PythonBindings(XenRTAPIv2Swagger):
    def render(self):
        self.getPaths()
        return self.generateFile()

    def getPaths(self):
        self.funcs = []
        swagger = XenRTAPIv2Swagger.render(self)

        for p in swagger['paths'].keys():
            for m in swagger['paths'][p].keys():
                self.funcs.append(Path(self, p, m, swagger['paths'][p][m], swagger['definitions']))

    def generateFile(self):
        ret = """#!/usr/bin/python

import requests
import json
import httplib

class XenRTAPIException(Exception):
    def __init__(self, code, reason, canForce):
        self.code = code
        self.reason = reason
        self.canForce = canForce

    def __str__(self):
        ret = "%s %s: %s" % (self.code, httplib.responses[self.code], self.reason)
        if self.canForce:
            ret += " (can force override)"
        return ret

class XenRT(object):
    def __init__(self, base, user, password):
        self.base = base
        self.user = user
        self.password = password

    def __serializeForQuery(self, data):
        if isinstance(data, bool):
            return str(data).lower()
        elif isinstance(data, (list, tuple)):
            return ",".join(data)
        else:
            return data

    def __raiseForStatus(self, response):
        try:
            if response.status_code >= 400:
                j = response.json()
                reason = j['reason']
                canForce = j.get('can_force')
            else:
                reason = None
                canForce = False
        except Exception, e:
            print e
        else:
            if reason:
                raise XenRTAPIException(response.status_code,
                                        reason,
                                        canForce)
        response.raise_for_status()

"""
        for func in self.funcs:
            ret += "%s\n" % func.methodSignature
            ret += "%s\n" % func.description
            ret += "%s\n" % func.methodContent
            ret += "\n\n"
    
        return ret

PageFactory(PythonBindings, "bindings/xenrt.py", reqType="GET", contentType="text/plain")
