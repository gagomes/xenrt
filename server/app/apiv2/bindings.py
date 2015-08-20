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
        self.returnKey = None
        self.parseParams()

    def pythonParamName(self, param):
        if param == "file":
            return "filepath"
        else:
            return param

    def pythonType(self, typename, items):
        if typename == "file":
            return "file path"
        elif typename == "object":
            return "dictionary"
        elif typename == "array":
            if items and "type" in items:
                return "list of %s" % items['type']
            else:
                return "list"
        else:
            return typename

    @property
    def methodContent(self):
        if self.masterOnly:
            ret = """        path = "%%s%s" %% (self.masterbase)\n""" % self.path
        else:
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
                    ret += """        if %s != None:\n            files['%s'] = (os.path.basename(%s), open(%s, 'rb'))\n        else:\n            files['%s'] = ('stdin', sys.stdin)\n""" % (q, p, q, q, p)
                else:
                    ret += """        if %s != None:\n            payload['%s'] = %s\n""" % (q, p, q)
        if self.method == "get":
            ret += """        r = requests.get(path, params=paramdict, headers=self.customHeaders)\n"""
            ret += """        if r.status_code in (502, 503):\n"""
            ret += """            time.sleep(30)\n"""
            ret += """            r = requests.get(path, params=paramdict, headers=self.customHeaders)\n"""
        else:
            if self.formParams:
                ret += """        myHeaders = {}\n"""
            else:
                ret += """        myHeaders = {'content-type': 'application/json'}\n"""
            ret += """        myHeaders.update(self.customHeaders)\n"""
            ret += """        r = requests.%s(path, params=paramdict, data=payload, files=files, headers=myHeaders)\n""" % self.method
            ret += """        if r.status_code in (502, 503):\n"""
            ret += """            time.sleep(30)\n"""
            ret += """            r = requests.%s(path, params=paramdict, data=payload, files=files, headers=myHeaders)\n""" % self.method
        ret += """        self.__raiseForStatus(r)\n"""
        if 'application/json' in self.data['produces']:
            if self.returnKey:
                ret += """        return r.json()['%s']""" % self.returnKey
            else:
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
                    argdesc[q] = "%s - %s" % (self.pythonType(objType['properties'][q]['type'], objType['properties'][q].get("items")), objType['properties'][q].get('description', ""))
                for q in [x for x in objType['properties'].keys() if x not in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    args.append((q, "None"))
                    argdesc[q] = "%s - %s" % (self.pythonType(objType['properties'][q]['type'], objType['properties'][q].get("items")), objType['properties'][q].get('description', ""))
            else:
                if p['in'] == "path":
                    self.pathParams.append(p['name'])
                elif p['in'] == "query":
                    self.queryParams.append(p['name'])
                elif p['in'] == "formData":
                    self.formParams.append(p['name'])

                if p.get('type') == "file":
                    self.fileParams.append(p['name'])
                argdesc[p['name']] = "%s - %s" % (self.pythonType(p.get('type'), p.get("items")), p.get('description',""))
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
                    args.append((p['name'], "None"))
        for p in self.data.get('paramOrder', []):
            pp = [x for x in args if x[0] == p]
            if not pp:
                pp = [(p,)]
            pname = self.pythonParamName(pp[0][0])
            if len(pp[0]) == 1:
                self.args.append(pname)
            else:
                self.args.append("%s=%s" % (pname, pp[0][1]))

            self.argdesc.append("`%s`: %s" % (pname, argdesc.get(pp[0][0], "")))
        for p in args:
            if not p[0] in self.data.get('paramOrder', []):
                pname = self.pythonParamName(p[0])
                if len(p) == 1:
                    self.args.append(pname)
                else:
                    self.args.append("%s=%s" % (pname, p[1]))
                self.argdesc.append("`%s`: %s" % (pname, argdesc.get(p[0], "")))

        if self.data.get('returnKey'):
            self.returnKey = self.data.get('returnKey')

    @property
    def methodSignature(self):
        return "    def %s(%s):" % (self.methodName, self.methodParams)

    @property
    def description(self):
        ret = "        \"\"\"\n        %s  \n\n" % (self.data['summary'])
        if "description" in self.data:
            ret += "        %s  \n" % self.data['description'].rstrip()
        if self.argdesc:
            ret += "        Parameters:  \n"
            for p in self.argdesc:
                ret += "        %s  \n" % (p)
        ret += "        \"\"\""
        return ret

    @property
    def masterOnly(self):
        return bool(self.data.get("masterOnly"))

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
                if swagger['paths'][p][m].get('operationId') == "no_binding":
                    continue
                self.funcs.append(Path(self, p, m, swagger['paths'][p][m], swagger['definitions']))
        
        self.scheme = swagger['schemes'][0]
        self.base = swagger['basePath']
        self.uibase = swagger['uiPath']
        self.host = swagger['host']
        self.masterhost = swagger['masterhost']

    def generateFile(self):
        ret = """#!/usr/bin/python

import requests
import json
import httplib
import os
import os.path
import base64
import sys
import time
import ConfigParser

class XenRTAPIException(Exception):
    def __init__(self, code, reason, canForce, traceback):
        self.code = code
        self.reason = reason
        self.canForce = canForce
        self.traceback = traceback

    def __str__(self):
        ret = "%%s %%s: %%s" %% (self.code, httplib.responses[self.code], self.reason)
        if self.canForce:
            ret += " (can force override)"
        if self.traceback:
            ret += "\\n%%s" %% self.traceback
        return ret

class XenRT(object):
    def __init__(self, apikey=None, user=None, password=None, server=None, masterserver=None):
        \"\"\"
        Constructor

        Parameters:  
        `apikey`: API key to use, for API key authentication  
        `user`: Username, for basic authentication  
        `password`: Password, for basic authentication  
        `server`: Server to connect to, if need to override default  
        `masterserver`: Master Server to connect to, if need to override default  
        \"\"\"
        if not server:
            server = self._getXenRTServer() or "%s"
        if not masterserver:
            masterserver = self._getXenRTMasterServer() or "%s"
        self.base = "%s://%%s%s" %% server
        self.masterbase = "%s://%%s%s" %% masterserver
        self.uibase = "%s://%%s%s" %% server

        self.customHeaders = {}
        if apikey:
            self.customHeaders['x-api-key'] = apikey
        elif user and password:
            base64string = base64.encodestring('%%s:%%s' %% (user, password)).replace('\\n', '')
            self.customHeaders["Authorization"] = "Basic %%s" %% base64string
        else:
            _apikey = self._getAPIKey()
            if _apikey:
                self.customHeaders['x-api-key'] = _apikey
            
    def _getConfigFile(self):
        path = "%%s/.xenrtrc" %% os.path.expanduser("~")
        try:
            config = ConfigParser.ConfigParser()
            config.read(path)
            return config
        except:
            return None

    def _getAPIKey(self):
        if os.getenv("XENRT_APIKEY"):
            return os.getenv("XENRT_APIKEY")
        else:
            try:
                return self._getConfigFile().get("xenrt", "apikey").strip()
            except:
                return None

    def _getXenRTServer(self):
        if os.getenv("XENRT_SERVER"):
            return os.getenv("XENRT_SERVER")
        try:
            return self._getConfigFile().get("xenrt", "server").strip()
        except:
            return None

    def _getXenRTMasterServer(self):
        if os.getenv("XENRT_MASETER_SERVER"):
            return os.getenv("XENRT_MASTER_SERVER")
        try:
            return self._getConfigFile().get("xenrt", "masterserver").strip()
        except:
            return None

    def __serializeForQuery(self, data):
        if isinstance(data, bool):
            return str(data).lower()
        elif isinstance(data, (list, tuple)):
            return ",".join([str(x) for x in data])
        else:
            return str(data)

    def __serializeForPath(self, data):
        return str(data).replace("/", "%%252F")

    def __raiseForStatus(self, response):
        try:
            if response.status_code >= 400:
                j = response.json()
                reason = j['reason']
                canForce = j.get('can_force')
                traceback = j.get('traceback')
            else:
                reason = None
                canForce = False
                traceback = None
        except:
            pass
        else:
            if reason:
                raise XenRTAPIException(response.status_code,
                                        reason,
                                        canForce,
                                        traceback)
        response.raise_for_status()

    def generate_junit_output_for_job(self, id):
        \"\"\"
        Generate JUnit compatible output for a job. Useful for sending to Jenkins

        Parameters:  
        `id`: Job ID to generate output for  
        \"\"\"

        errored=0
        failed=0
        skipped=0
        passed=0

        job = self.get_job(id, logitems=True)

        tcs = ""
        jobdesc = job['description'].split("&")[0]

        for r in job['results'].values():
            message = ""
            for l in r['log']:
                if l['type'] == "reason":
                    message = l['log'].replace('"', '')
            urltext = "Logs available at %%s/logs?detailid=%%d" %% (self.uibase, r['detailid'])
            if r['result'].startswith("pass") or r['result'].startswith("partial"):
                passed += 1
                details = ""
            elif r['result'].startswith("fail"):
                failed += 1
                details = \"\"\"    <failure message="%%s">
          %%s
        </failure>
    \"\"\" %% (message, urltext)
            elif r['result'].startswith("error") or r['result'].startswith("timeout") or r['result'].startswith("unknown"):
                errored += 1
                details = \"\"\"    <error message="%%s">
          %%s
        </error>
    \"\"\" %% (message, urltext)
            elif r['result'].startswith("blocked"):
                errored += 1
                details = \"\"\"    <error message="Blocked by previous test">
          %%s
        </error>
    \"\"\" %% (urltext)
            elif r['result'].startswith("skipped") or r['result'].startswith("blocked"):
                skipped += 1
                details = "    <skipped />\\n"
            else:
                continue

            time = 0

            if r['log']:
                time = max([x['ts'] for x in r['log']]) - min([x['ts'] for x in r['log']])

            tcs += \"\"\"
      <testcase name="%%s" classname="%%s.%%s" time="%%s">
    %%s  </testcase>
    \"\"\" %% (r['test'], jobdesc, r['phase'], time, details)

        out = \"\"\"<testsuite name="xenrt" tests="%%d" skip="%%d" failures="%%d" errors="%%d">%%s</testsuite>\"\"\" %% (
            errored + failed + skipped + passed,
            skipped,
            failed,
            errored,
            tcs)

        return out

""" % (self.host, self.masterhost, self.scheme, self.base, self.scheme, self.base, self.scheme, self.uibase)
        for func in self.funcs:
            ret += "%s\n" % func.methodSignature
            ret += "%s\n" % func.description
            ret += "%s\n" % func.methodContent
            ret += "\n\n"
    
        return ret

PageFactory(PythonBindings, "bindings/__init__.py", reqType="GET", contentType="text/plain")
