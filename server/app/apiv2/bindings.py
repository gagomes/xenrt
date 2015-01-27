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
        self.fileParams = []
        self.pathParams = []
        self.queryParams = []
        self.parseParams()

    def pythonParamName(self, param):
        if param == "file":
            return "filepath"
        else:
            return param

    @property
    def methodContent(self):
        ret = """        path = "%%s%s" %% (self.base)\n""" % self.path
        for p in self.pathParams:
            q = self.pythonParamName(p)
            ret += """        path = path.replace("{%s}", self.__serializeForPath(%s))\n""" % (p, q)
        ret += """        paramdict = {}\n"""
        ret += """        files = {}\n"""
        for p in self.queryParams:
            q = self.pythonParamName(p)
            ret += """        if %s != None:\n            paramdict['%s'] = self.__serializeForQuery(%s)\n""" % (q, p, q)
        ret += """        payload = {}\n"""
        if self.jsonParams:
            ret += """        j = {}\n"""
            for p in self.jsonParams:
                q = self.pythonParamName(p)
                ret += """        if %s != None:\n            j['%s'] = %s\n""" % (q, p, q)
            ret += """        payload = json.dumps(j)\n"""
        elif self.formParams:
            for p in self.formParams:
                q = self.pythonParamName(p)
                if p in self.fileParams:
                    ret += """        if %s != None:\n            files['%s'] = (os.path.basename(%s), open(%s, 'rb'))\n""" % (q, p, q, q)
                else:
                    ret += """        if %s != None:\n            payload['%s'] = %s\n""" % (q, p, q)
        if self.method == "get":
            ret += """        r = requests.get(path, params=paramdict, auth=(self.user, self.password))\n"""
        else:
            ret += """        r = requests.%s(path, params=paramdict, data=payload, files=files, auth=(self.user, self.password))\n""" % self.method
        ret += """        self.__raiseForStatus(r)\n"""
        if 'application/json' in self.data['produces']:
            ret += """        return r.json()"""
        else:
            ret += """        return r.content"""
        return ret

    def parseParams(self):
        args = []
        argdesc = {}
        for p in self.data.get('parameters', []):
            if p['in'] == "body":
                objType = self.definitions[p['schema']['$ref'].split("/")[-1]]
                for q in [x for x in objType['properties'].keys() if x in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    args.append((q,))
                    argdesc[q] = objType['properties'][q].get('description', "")
                for q in [x for x in objType['properties'].keys() if x not in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    if objType['properties'][q]['type'] == "boolean":
                        default = "False"
                    else:
                        default = "None"
                    args.append((q, default))
                    argdesc[q] = objType['properties'][q].get('description', "")
            else:
                if p['in'] == "path":
                    self.pathParams.append(p['name'])
                elif p['in'] == "query":
                    self.queryParams.append(p['name'])
                elif p['in'] == "formData":
                    self.formParams.append(p['name'])

                if p.get('type') == "file":
                    self.fileParams.append(p['name'])
                argdesc[p['name']] = p.get('description',"")
                if p.get('required'):
                    if not p.get('default'):
                        args.append((p['name'],))
                    else:
                        if p['type'] == "string" or (p['type'] == "array" and p['items']['type'] == "string"):
                            default = "\"%s\"" % p['default']
                        else:
                            default = p['default']
                        args.append((p['name'], default))
                else:
                    if p.get('type') == "boolean":
                        default = "False"
                    else:
                        default = "None"
                    args.append((p['name'], default))
        for p in self.data.get('paramOrder', []):
            pp = [x for x in args if x[0] == p]
            if not pp:
                pp = [(p,)]
            pname = self.pythonParamName(pp[0][0])
            if len(pp[0]) == 1:
                self.args.append(pname)
            else:
                self.args.append("%s=%s" % (pname, pp[0][1]))

            self.argdesc.append("%s: %s" % (pname, argdesc.get(pp[0][0], "")))
        for p in args:
            if not p[0] in self.data.get('paramOrder', []):
                pname = self.pythonParamName(p[0])
                if len(p) == 1:
                    self.args.append(pname)
                else:
                    self.args.append("%s=%s" % (pname, p[1]))
                self.argdesc.append("%s: %s" % (pname, argdesc.get(p[0], "")))

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
        args = []
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
        
        self.scheme = swagger['schemes'][0]
        self.base = swagger['basePath']
        self.host = swagger['host']

    def generateFile(self):
        ret = """#!/usr/bin/python

import requests
import json
import httplib
import os.path

class XenRTAPIException(Exception):
    def __init__(self, code, reason, canForce):
        self.code = code
        self.reason = reason
        self.canForce = canForce

    def __str__(self):
        ret = "%%s %%s: %%s" %% (self.code, httplib.responses[self.code], self.reason)
        if self.canForce:
            ret += " (can force override)"
        return ret

class XenRT(object):
    def __init__(self, user, password):
        self.base = "%s://%s%s"
        self.user = user
        self.password = password

    def __serializeForQuery(self, data):
        if isinstance(data, bool):
            return str(data).lower()
        elif isinstance(data, (list, tuple)):
            return ",".join([str(x) for x in data])
        else:
            return str(data)

    def __serializeForPath(self, data):
        return str(data)

    def __raiseForStatus(self, response):
        try:
            if response.status_code >= 400:
                j = response.json()
                reason = j['reason']
                canForce = j.get('can_force')
            else:
                reason = None
                canForce = False
        except:
            pass
        else:
            if reason:
                raise XenRTAPIException(response.status_code,
                                        reason,
                                        canForce)
        response.raise_for_status()

""" % (self.scheme, self.host, self.base)
        for func in self.funcs:
            ret += "%s\n" % func.methodSignature
            ret += "%s\n" % func.description
            ret += "%s\n" % func.methodContent
            ret += "\n\n"
    
        return ret

PageFactory(PythonBindings, "bindings/xenrt.py", reqType="GET", contentType="text/plain")