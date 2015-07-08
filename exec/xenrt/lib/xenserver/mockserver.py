import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log
from abc import ABCMeta, abstractmethod ,abstractproperty

class MockServer(object):
    __metaclass__=ABCMeta

    def __init__(self,mockServerObj=None):
        self.mockServerObj=mockServerObj
        self.mockServerUrl = "%s%s%s" %(self.protocol,self.endpoint,self.port)

    @abstractmethod
    def configureGuest(self,guest):
        pass

    @abstractproperty
    def protocol(self):
        pass

    @abstractproperty
    def endpoint(self):
        pass

    @abstractproperty
    def port(self):
        pass

class StaticCISServer(MockServer):
    STATIC_CIS_SERVER_IP="10.102.123.228"

    @property
    def protocol(self):
        return "http://"

    @property
    def endpoint(self):
        return self.STATIC_CIS_SERVER_IP

    @property
    def port(self):
        return ":8080"

    @property
    def uploadendpoint(self):
        return "/feeds/api/"

    def configureGuest(self,guest):
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenCenter","HealthCheckIdentityTokenDomainName","SZ",self.mockServerUrl)
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenCenter","HealthCheckUploadTokenDomainName","SZ",self.mockServerUrl)
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenCenter","HealthCheckUploadGrantTokenDomainName","SZ",self.mockServerUrl)
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenCenter","HealthCheckDiagnosticDomainName","SZ",self.mockServerUrl)
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenCenter","HealthCheckProductKey","SZ","1a2d94a4263cd016dd7a7d510bde87f058a0b75d")
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenHealthCheck","HealthCheckUploadDomainName","SZ",self.mockServerUrl+self.uploadendpoint)
        guest.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenHealthCheck","HealthCheckTimeIntervalInMinutes","DWORD",3)

class DynamicCISServer(StaticCISServer):

    @property
    def endpoint(self):
        return self.mockServerObj.getIP()

class MockServerFactory(object):

    def getMockServer(self,serverType,mockServerObj=None):
        if serverType == "CIS":
            if mockServerObj :
                return DynamicCISServer(mockServerObj)
            else:
                return StaticCISServer()
        raise ValueError("%s Mock Service is not implemented yet "%serverType)
