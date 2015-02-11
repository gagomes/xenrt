import re

"""
Xapi object model base and factory classes
"""
__all__ = [ 'XapiObjectFactory', 'XapiObject', 'VM', 'VBD', 'objectFactory', 'XapiHost', 'SR', 'VDI', 'PBD']


class XapiObjectFactory(object):
    """
    A factory class which allows class types to be registered and looked up
    Unregistered types return the base class "XapiObject"
    """
    def __init__(self):
        self.__XapiObjects = {}

    def getObject(self, type):
        """
        Get a stored class, based on a lookup string. The return value will need to be instantiated

        @type type: string
        @var type: A string representing the type of the object to be fetched
        @rtype: class
        @return: A class of the required type or "XapiObject" if the type is not registered.
        """
        if self.__XapiObjects.has_key(type):
            return self.__XapiObjects[type]
        else:
            return XapiObject

    def registerObject(self, classToRegister):
        """
        Register a class, along with it's type to ensure the specialisation is return
        when a lookup is requested

        @type type: string
        @var type: name of the type to register
        @type classToRegister: class reference
        @var a specialisation of the XapiObject class for a required object
        """
        self.__XapiObjects[classToRegister.OBJECT_TYPE] = classToRegister


class XapiObject(object):
    """
    XapiObject base class containing commandline commands to execute
    This class should remain generic
    """
    OBJECT_TYPE = "XapiObject"
    def __init__(self, cli, type, uuid):
        self.type = type
        self.uuid = uuid
        self.cli = cli

    def getStringParam(self, paramName):
        """
        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @return: the requested param value
        @rtype string
        """
        return self.cli.execute("%s-param-get uuid=%s param-name=%s" % (self.type, self.uuid, paramName)).strip()

    def getListParam(self, paramName, delimiter=';'):
        """
        Get the params from xapi, in the form of a list of strings - useful for composite fields

        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @var delimiter: how the resulting array is delimeted by xapi
        @type delimiter: char
        @return: the requested param value
        @rtype list
        """
        return self.cli.execute("%s-param-get uuid=%s param-name=%s" % (self.type, self.uuid, paramName )).strip().split(delimiter)

    def getDictParam(self, paramName, listDelimiter=';', keyDelimiter=':'):
        """
        Get the params from xapi, in the form of a dictionary of strings - useful for composite fields

        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @var listDelimiter: how the resulting array is delimited by xapi
        @type listDelimiter: char
        @var keyDelimiter: how the resulting array values are delimited by xapi
        @type keyDelimiter: char
        @return: the requested param values
        @rtype dictionary of strings
        """
        params = {}
        listParams = self.getListParam(paramName, listDelimiter)

        if not listParams or len(listParams) < 1:
            return params

        for p in listParams:
            pair = p.split(keyDelimiter)
            params[pair[0].strip()]=pair[1].strip()
        return params

    def getObjectParam(self, objType, paramName):
        """
        Get object-model form of a field referenced by the current object. For example if an object contains a ref to another object
        eg. for a vdi type: and sr class can be obtained by: sr = vdi.getObjectParam("sr", "sr-uuid")

        @var objType: the objects type to look up in the factory
        @type objType: string
        @var paramName: the parameter that provides the uuid of the target type
        @type paramName: string
        @return: the requested object derived from XapiObject
        @rtype class
        """
        uuid = self.cli.execute("%s-param-get  uuid=%s param-name=%s" % (self.type, self.uuid, paramName)).strip()
        return objectFactory().getObject(objType)(self.cli, objType, uuid)

    def getObjectsReferencing(self, refObjectType, currentObjectType):
        """
        Get objects that reference the current objecy
        @var refObjectType: the type to look up
        @type refObjectType:  string
        @var currentObjectType: how the resulting array is refered to
        @type delimiter: string
        @return XapiObjects represented the objects that reference the current object
        @rtype list of XapiObjects
        """
        uuids = self.cli.execute("%s-list %s-uuid=%s --minimal" % (refObjectType, currentObjectType, self.uuid)).strip().split(',')
        return [objectFactory().getObject(refObjectType)(self.cli, refObjectType, uuid) for uuid in uuids]


    def op(self, operation, params="", returnObject=None):
        ret = self.cli.execute("%s-%s uuid=%s %s" % (self.type, operation, self.uuid, params)).strip()
        if returnObject:
            ret = objectFactory().getObject(returnObject)(self.cli, returnObject, ret)
        return ret

    def __repr__(self):
        return ';'.join([self.OBJECT_TYPE, self.uuid])

    def __hash__(self):
        return hash(self.__repr__())

    def __eq__(self, other):
        return self.uuid == other.uuid

    def __ne__(self, other):
        return self.uuid != other.uuid

    #Setter could be implemented like so....
    #def setParam(paramName, value): etc...


class NamedXapiObject(XapiObject):
    __NAME = "name-label"

    def name(self):
        return self.getStringParam(self.__NAME)

    def getObjectsReferencingName(self, refObjectType, currentObjectType):
        uuids = self.cli.execute("%s-list %s=%s --minimal" % (refObjectType, currentObjectType, self.name())).strip().split(',')
        return [objectFactory().getObject(refObjectType)(self.cli, refObjectType, uuid) for uuid in uuids]

"""
Additional class implementations
NB: Don't forget to register any new implementations with the object factory
"""

class VM(NamedXapiObject):
    OBJECT_TYPE = "vm"
    __NETWORK_ADDRESSES = "networks"
    __CPU_USAGE = "VCPUs-utilisation"
    __RESIDENT = "resident-on"

    def VBD(self):
        return self.getObjectsReferencing(VBD.OBJECT_TYPE, self.OBJECT_TYPE)

    def VDI(self):
        return [x.VDI() for x in self.VBD()]

    def networkAddresses(self):
        return self.getListParam(self.__NETWORK_ADDRESSES)

    def XapiHost(self):
        return self.getObjectParam(XapiHost.OBJECT_TYPE, self.__RESIDENT)

    def SR(self):
        return list(set([v.SR() for v in self.VDI()]))

    @property
    def cpuUsage(self):
        return self.getDictParam(self.__CPU_USAGE)


class VBD(XapiObject):
    OBJECT_TYPE = "vbd"
    __VM_UUID = "vm-uuid"
    __VDI_UUID = "vdi-uuid"
    __OPS = "allowed-operations"

    def VM(self):
        return self.getObjectParam(VM.OBJECT_TYPE, self.__VM_UUID)

    def allowedOperations(self):
        return self.getListParam(self.__OPS)

    def VDI(self):
        return self.getObjectParam(VDI.OBJECT_TYPE, self.__VDI_UUID)


class XapiHost(NamedXapiObject):
    OBJECT_TYPE = "host"

    def SR(self):
        return self.getObjectsReferencingName(SR.OBJECT_TYPE, self.OBJECT_TYPE)


class PBD(XapiObject):
    OBJECT_TYPE = "pbd"

    def deviceConfig(self):
        return self.getDictParam("device-config")


class SR(NamedXapiObject):
    OBJECT_TYPE = "sr"
    __LOCAL = "Local storage"
    __TYPE = "type"

    def isLocal(self):
        return re.search(self.__LOCAL, self.name())

    def srType(self):
        return self.getStringParam(self.__TYPE)

    def VDI(self):
        return self.getObjectsReferencing(VDI.OBJECT_TYPE, self.OBJECT_TYPE)

    def PBD(self):
        return self.getObjectsReferencing(PBD.OBJECT_TYPE, self.OBJECT_TYPE)

    def otherConfig(self):
        return self.getStringParam("other-config")

    def contentType(self):
        return self.getStringParam("content-type")

    def smConfig(self):
        return self.getStringParam("sm-config")


class VDI(NamedXapiObject):
    OBJECT_TYPE = "vdi"
    __SR_UUID = "sr-uuid"
    __RC = "sm-config param-key=read-caching-enabled"

    def SR(self):
        return self.getObjectParam(SR.OBJECT_TYPE, self.__SR_UUID)

    def snapshot(self):
        return self.op("snapshot", returnObject="vdi")

    def readcachingEnabled(self):
        return self.getStringParam(self.__RC) == "true"


"""
Setup global factory and accessor method
"""
ObjectFactoryInstance = None

def objectFactory():
    """
    Used to get the global object factory instance
    """
    global ObjectFactoryInstance
    if not ObjectFactoryInstance:
        ObjectFactoryInstance = XapiObjectFactory()
    return ObjectFactoryInstance

"""
Register objects with factory - allows specialisations to be
registered and hence returned by the factory class
"""
objectFactory().registerObject(PBD)
objectFactory().registerObject(VBD)
objectFactory().registerObject(VM)
objectFactory().registerObject(SR)
objectFactory().registerObject(XapiHost)
objectFactory().registerObject(VDI)


