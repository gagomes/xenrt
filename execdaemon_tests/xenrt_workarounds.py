import logging


log = logging.getLogger(__name__)


class _FakeTestExecutionContext(object):
    def logverbose(self, *args, **kwargs):
        pass

    def lookup(self, *args, **kwargs):
        return None

    def log(self, *args, **kwargs):
        log.info(args)


def _tec():
    return _FakeTestExecutionContext()


def createWindowsOS(ipAddress):
    from xenrt.lib.opsys import windows
    import xenrt
    from xenrt import interfaces
    from zope.interface import implements

    class IPProvider(object):
        implements(interfaces.OSParent)

        def __init__(self, ipAddress):
            self.ipAddress = ipAddress

        def getIP(self):
            return self.ipAddress

    distro = "some distro"
    parent = IPProvider(ipAddress)

    my_windows = windows.WindowsOS(distro, parent)
    xenrt.TEC = _tec
    return my_windows
