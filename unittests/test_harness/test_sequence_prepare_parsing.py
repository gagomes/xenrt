import xenrt
import xml.dom.minidom
import pprint
import json
from mock import patch, Mock, PropertyMock
from testing import XenRTUnitTestCase


class TestSeqPrepareParsing(XenRTUnitTestCase):
    DEFAULT_VARS = {}

    def addTC(self, cls):
        json.loads(cls.JSON)
        self.tcs.append((cls.__name__, cls.XML, cls.JSON, cls.EXTRAVARS, cls.MAXHOSTS))

    def test_seq_prepare_parsing(self):
        self.tcs = []
        self.addTC(TC1)
        self.run_for_many(self.tcs, self.__test_seq_prepare_parsing)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def __test_seq_prepare_parsing(self, data, tec, gec):
        (tcname, xmlstr, jsonstr, extravars, maxhosts) = data
        self.dummytec = DummyTEC(self)
        tec.return_value = self.dummytec
        gec.return_value = self.dummytec
        self.extravars = extravars
        self.maxhosts = maxhosts

        self.toplevel = Mock()
        xmldict = self.parsePrepare(xmlstr)
        jsondict = self.parsePrepare(jsonstr)

        pprint.pprint(xmldict)
        with open("unittests-xml.out", "w") as f:
            pprint.pprint(xmldict, stream=f)
        pprint.pprint(jsondict)
        with open("unittests-json.out", "w") as f:
            pprint.pprint(jsondict, stream=f)
        self.assertEqual(xmldict, jsondict)
    
    def parsePrepare(self, data):

        data = "<prepare>%s</prepare>" % data
        dom = xml.dom.minidom.parseString(data)

        for n in dom.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                node = xenrt.sequence.PrepareNode(self.toplevel, n, {}) 
            break

        return node.__dict__

    def _lookup(self, var, default="BADVALUE", boolean=False):
        values = {}

        if isinstance(var, list):
            var = "/".join(var)

        values.update(self.DEFAULT_VARS)
        values.update(self.extravars)
        if not values.has_key(var):
            if default == "BADVALUE":
                raise Exception("No default value specified for %s" % var)
            return default
        else:
            if boolean:
                if values[var][0].lower() in ("y", "t", "1"):
                    return True
                else:
                    return False
            else:
                return values[var]

class DummyTEC(object):
    def __init__(self, parent):
        self.parent = parent
        self.registry = DummyRegistry(parent)

    def logverbose(self, msg):
        pass

    def lookup(self, var, default="BADVALUE", boolean=False):
        return self.parent._lookup(var, default, boolean=False)

    def getFile(self, *files):
        return "/path/to/file"

    @property
    def config(self):
        return self

class DummyRegistry(object):
    def __init__(self, parent):
        self.objs = {}
        self.parent = parent
    
    def dump(self):
        pass

    def hostGet(self, h):
        index = int(re.match("RESOURCE_HOST_(\d+)", h).group(1))
        if index >= self.parent.maxhosts:
            return None
        m = Mock()
        m.getIP.return_value = str(IPy.IP(IPy.IP("10.0.0.3").int() + index))
        m.getFQDN.return_value = "h%d.domain" % index
        return m

    def guestGet(self, g):
        g = Mock()
        g.createLinuxNfsShare.return_value = "guest:/path"
        return g

    def objPut(self, objType, tag, obj):
        self.objs["%s-%s" % (objType, tag)] = obj

    def objGet(self, objType, tag):
        return self.objs["%s-%s" % (objType, tag)]

class BaseTC(object):
    EXTRAVARS = {}
    MAXHOSTS = None

class TC1(BaseTC):
    XML = """
    <pool id="0">
      <host id="0"/>
      <host id="1"/>
    </pool>
"""
    
    JSON = """{
    "pools": [
        { 
            "id": 0,
            "hosts": [
                { "id": 0},
                { "id": 1}
            ]
        }
    ]
}"""

class TC2(BaseTC):
    MAXHOSTS = 3
    XML = """
    <pool id="0">
        <allhosts />
    </pool>
"""

    JSON = """{
    "pools": [
        {
            "id": 0,
            "multihosts": {}
        }
    ]
}"""
