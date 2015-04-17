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
        self.tcs.append((cls.__name__, cls.XML, cls.JSON, cls.EXTRAVARS, cls.MAXHOSTS, cls.EXPECTEDHOSTS))

    def test_seq_prepare_parsing(self):
        self.tcs = []
        self.addTC(TC1)
        self.addTC(TC2)
        self.addTC(TC3)
        self.addTC(TC4)
        self.addTC(TC5)
        self.addTC(TC6)
        self.addTC(TC7)
        self.addTC(TC8)
        self.addTC(TC9)
        self.addTC(TC10)
        self.run_for_many(self.tcs, self.__test_seq_prepare_parsing)

    @patch("uuid.uuid4")
    @patch("xenrt.randomMAC")
    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def __test_seq_prepare_parsing(self, data, tec, gec, randommac, uuid):
        (tcname, xmlstr, jsonstr, extravars, maxhosts, expectedhosts) = data
        self.tcname = tcname
        print "Running %s" % self.tcname
        self.dummytec = DummyTEC(self)
        tec.return_value = self.dummytec
        gec.return_value = self.dummytec
        mockuuid = Mock()
        mockuuid.hex = "0000"
        uuid.return_value = mockuuid
        randommac.return_value = "00:00:00:00:00:00"
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
        if expectedhosts != None:
            self.assertEqual(len(jsondict['hosts']), expectedhosts)
            self.assertEqual(len(xmldict['hosts']), expectedhosts)
    
    def parsePrepare(self, data):

        data = "<prepare>%s</prepare>" % data
        dom = xml.dom.minidom.parseString(data)

        for n in dom.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                node = xenrt.seq.PrepareNode(self.toplevel, n, {}) 
            break

        node.tcname = self.tcname

        return node.__dict__

    def _lookup(self, var, default="BADVALUE", boolean=False):

        if var.startswith("RESOURCE_HOST_"):
            hostIndex = int(var[14:])
            if hostIndex >= self.maxhosts:
                return default
            else:
                return "h%d" % hostIndex

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
        self.dbconnect = Mock()
        self.dbconnect.jobid.return_value = "500000"

    def logverbose(self, msg):
        pass

    def jobid(self):
        return "500000"

    def warning(self, msg):
        pass

    def lookup(self, var, default="BADVALUE", boolean=False):
        return self.parent._lookup(var, default, boolean=False)

    def setVariable(self, key, value):
        pass

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
    EXPECTEDHOSTS = None

# Basic pool with specified hosts
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

# Basic pool with all hosts
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

# Basic all hosts
class TC3(BaseTC):
    MAXHOSTS = 3
    XML = """
        <allhosts />
"""

    JSON = """{
            "multihosts": {}
}"""

# Basic single host with VM

class TC4(BaseTC):
    XML = """
      <host id="0">
        <vm name="testvm">
          <distro>debian70</distro>
          <arch>x86-64</arch>
          <memory>1024</memory>
          <vcpus>1</vcpus>
          <disk device="0" size="10" />
          <disk device="1" size="10" number="2" format="yes"/>
          <corespersocket>4</corespersocket>
          <network device="0" />
          <network device="1" bridge="testbridge"/>
          <storage>testsr</storage>
          <postinstall action="test" />
          <postinstall action="test2" />
          <file>test.xva</file>
          <bootparams>testparams</bootparams>
        </vm>
      </host>
"""
    JSON = """
        { "hosts": [
            { "id": 0,
              "vms": [
                { "name": "testvm",
                  "distro": "debian70",
                  "arch": "x86-64",
                  "memory": 1024,
                  "cores_per_socket": 4,
                  "vcpus": 1,
                  "disks": [
                    { "device": 0,
                      "size": 10
                    },
                    { "device": 1,
                      "size": 10,
                      "count": 2,
                      "format": true
                    }
                  ],
                  "sr": "testsr",
                  "postinstall": [
                    { "action": "test" },
                    { "action": "test2" }
                  ],
                  "file_name": "test.xva",
                  "boot_params": "testparams",
                  "vifs": [
                    { "device": 0 },
                    { "device": 1,
                      "network": "testbridge" }
                  ]
                }
              ]
            }
          ]
        }
    """

# Richer pool
class TC5(BaseTC):
    XML = """
    <vlan name="testvlan" />
    <pool id="0" name="testpool" ssl="yes">
      <host id="0"/>
      <bridge name="internal" />
      <storage name="nfssr" type="nfs" default="true" />
        <vm name="testvm">
          <distro>debian70</distro>
          <memory>1024</memory>
          <vcpus>1</vcpus>
          <network device="0" />
          <disk device="0" size="10" />
        </vm>
        <vm name="testvm2">
          <distro>debian70</distro>
          <memory>1024</memory>
          <vcpus>1</vcpus>
          <network device="0" />
          <disk device="0" size="10" />
        </vm>
    </pool>
    <sharedhost>
      <vm name="LicenseServer">
        <file>license.xva</file>
        <postinstall action="installV6LicenseServer"/>
      </vm>
    </sharedhost>

"""
    
    JSON = """
{
    "utilityvms": [
      { "name": "LicenseServer",
        "file_name": "license.xva",
        "postinstall": [ { "action": "installV6LicenseServer" } ]
      }
    ],
    "vlans": [ {"name": "testvlan"} ],
    "pools": [
        { 
            "id": 0,
            "hosts": [ { "id": 0} ],
            "name": "testpool",
            "ssl": true,
            "srs": [
              { "type": "nfs",
                "name": "nfssr",
                "default": true
              }
            ],
            "bridges": [
                { "name": "internal" }
            ],
            "vms": [
              { "name": "testvm",
                "distro": "debian70",
                "memory": 1024,
                "vcpus": 1,
                "disks": [
                  { "device": 0,
                    "size": 10
                  }
                ],
                "vifs": [
                  { "device": 0 }
                ]
              },
              { "name": "testvm2",
                "distro": "debian70",
                "memory": 1024,
                "vcpus": 1,
                "disks": [
                  { "device": 0,
                    "size": 10
                  }
                ],
                "vifs": [
                  { "device": 0 }
                ]
              }
            ]
        }
    ]
}
"""

# Richer host
class TC6(BaseTC):
    XML = """
    <host id="0">
      <bridge name="internal" />
      <storage name="nfssr" type="nfs" default="true" />
        <vm name="testvm">
          <distro>debian70</distro>
          <memory>1024</memory>
          <vcpus>1</vcpus>
          <network device="0" />
          <disk device="0" size="10" />
        </vm>
        <vm name="testvm2">
          <distro>debian70</distro>
          <memory>1024</memory>
          <vcpus>1</vcpus>
          <network device="0" />
          <disk device="0" size="10" />
        </vm>
    </host>
"""
    
    JSON = """
{
    "hosts": [
        { 
            "id": 0,
            "srs": [
              { "type": "nfs",
                "name": "nfssr",
                "default": true
              }
            ],
            "bridges": [
                { "name": "internal" }
            ],
            "vms": [
              { "name": "testvm",
                "distro": "debian70",
                "memory": 1024,
                "vcpus": 1,
                "disks": [
                  { "device": 0,
                    "size": 10
                  }
                ],
                "vifs": [
                  { "device": 0 }
                ]
              },
              { "name": "testvm2",
                "distro": "debian70",
                "memory": 1024,
                "vcpus": 1,
                "disks": [
                  { "device": 0,
                    "size": 10
                  }
                ],
                "vifs": [
                  { "device": 0 }
                ]
              }
            ]
        }
    ]
}
"""

class TC7(BaseTC):
    EXPECTEDHOSTS = 5
    XML = """    <cloud>
{
    "zones": [
        {
            "name": "XenRT-Zone-0",
            "networktype": "Basic",
            "pods": [
                {
                    "name": "XenRT-Zone-0-Pod-0",
                    "XRT_PodIPRangeSize": 5,
                    "clusters": [
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-0",
                            "hypervisor": "XenServer",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-1",
                            "hypervisor": "vmware",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-2",
                            "hypervisor": "LXC",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-3",
                            "hypervisor": "KVM",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-4",
                            "hypervisor": "hyperv",
                            "XRT_Hosts": 1
                        }
                    ],
                    "guestIpRanges": [
                        {
                            "XRT_GuestIPRangeSize": 10
                        }
                    ]
                }
            ]
        }
    ],
    "globalConfig": [
        
    ]
}
</cloud>
    <sharedhost>
      <vm name="CS-MS">
        <distro>rhel63</distro>
        <arch>x86-64</arch>
        <memory>1024</memory>
        <vcpus>2</vcpus>
        <postinstall action="installCloudManagementServer" />
        <network device="0" />
        <disk device="0" size="12" />
      </vm>
    </sharedhost>
"""

    JSON = """
{ "cloud":
    {
    "zones": [
        {
            "name": "XenRT-Zone-0",
            "networktype": "Basic",
            "pods": [
                {
                    "name": "XenRT-Zone-0-Pod-0",
                    "XRT_PodIPRangeSize": 5,
                    "clusters": [
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-0",
                            "hypervisor": "XenServer",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-1",
                            "hypervisor": "vmware",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-2",
                            "hypervisor": "LXC",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-3",
                            "hypervisor": "KVM",
                            "XRT_Hosts": 1
                        },
                        {
                            "name": "XenRT-Zone-0-Pod-0-Cluster-4",
                            "hypervisor": "hyperv",
                            "XRT_Hosts": 1
                        }
                    ],
                    "guestIpRanges": [
                        {
                            "XRT_GuestIPRangeSize": 10
                        }
                    ]
                }
            ]
        }
    ],
    "globalConfig": [
        
    ]
  },
  "utilityvms": [
    { "name": "CS-MS",
      "distro": "rhel63",
      "arch": "x86-64",
      "memory": 1024,
      "vcpus": 2,
      "postinstall": [ {"action": "installCloudManagementServer"} ],
      "disks": [ { "device": 0, "size": 12 } ],
      "vifs": [ { "device": 0 } ]
    }
  ]
}
"""

# Basic pool with specified hosts
class TC8(BaseTC):
    XML = """
    <pool id="0">
      <host container="0" vname="xs1" />
      <host container="0" vname="xs2" />
    </pool>
"""
    
    JSON = """{
    "pools": [
        { 
            "id": 0,
            "hosts": [
                { "container": 0, "vname": "xs1"},
                { "container": 0, "vname": "xs2"}
            ]
        }
    ]
}"""

# Template node is equivalent to VM node with convertToTemplate
class TC9(BaseTC):
    XML = """
      <host id="0">
        <vm name="testvm">
          <distro>debian70</distro>
          <network device="0" />
          <postinstall action="convertToTemplate" />
        </vm>
      </host>
"""
    JSON = """
        { "hosts": [
            { "id": 0,
              "templates": [
                { "name": "testvm",
                  "distro": "debian70",
                  "vifs": [
                    { "device": 0 }
                  ]
                }
              ]
            }
          ]
        }
    """

# Template node is equivalent to VM node with convertToTemplate
class TC10(BaseTC):
    XML = """
      <host id="0">
        <template name="testvm">
          <distro>debian70</distro>
          <network device="0" />
        </template>
      </host>
"""
    JSON = """
        { "hosts": [
            { "id": 0,
              "templates": [
                { "name": "testvm",
                  "distro": "debian70",
                  "vifs": [
                    { "device": 0 }
                  ],
                  "postinstall": [
                    { "action": "convertToTemplate" }
                  ]
                }
              ]
            }
          ]
        }
    """

