#!/usr/bin/python

ECHO_FN_NAME="echo"
ECHO_PLUGIN_NAME="echoplugin"


def getSource():
    import inspect
    import sys
    return inspect.getsource(sys.modules[__name__])


def installTo(filesystem):
    targetPath = '/etc/xapi.d/plugins/%s' % ECHO_PLUGIN_NAME

    filesystem.setContents(targetPath, getSource())
    filesystem.makePathExecutable(targetPath)


def cmdLineToCallEchoFunction(echoRequest):
    args = [
        'plugin=%s' % ECHO_PLUGIN_NAME,
        'fn=%s' % ECHO_FN_NAME
    ] + toXapiArgs(echoRequest.serialize())

    return ' '.join(args)


class EchoRequest(object):
    def __init__(self, stdout=False, stderr=False, path=None,
                 exitCode=None, data=''):
        self.stdout = stdout
        self.stderr = stderr
        self.path = path
        self.exitCode = exitCode
        self.data = data

    def __eq__(self, other):
        for attrName in dir(self):
            if attrName.startswith('_'):
                continue

            if callable(getattr(self, attrName)):
                continue
            if getattr(self, attrName) != getattr(other, attrName):
                return False
        return True

    def serialize(self):
        return {
            'data': self.data,
            'stdout': _serializeBool(self.stdout),
            'stderr': _serializeBool(self.stderr),
            'path': self.path,
            'exitCode': self.exitCode,
        }


def _serializeBool(boolValue):
    if boolValue:
        return "yes"
    return "no"


def _parseBool(data):
    if data == "yes":
        return True
    return False


def parseRequest(args):
    echoRequest = EchoRequest()

    exitCode = args.get('exitCode')
    if exitCode is not None:
        exitCode = int(exitCode)

    echoRequest.exitCode = exitCode

    echoRequest.data = args.get('data', '')

    echoRequest.stdout = _parseBool(args.get('stdout'))
    echoRequest.stderr = _parseBool(args.get('stderr'))
    echoRequest.path = args.get('path')

    return echoRequest


def writeToPath(data, path):
    fhandle = open(path, 'w')
    fhandle.write(data)
    fhandle.close()


def echo(session, args):
    import sys
    echoRequest = parseRequest(args)
    data = echoRequest.data

    if echoRequest.path:
        writeToPath(data, echoRequest.path)

    if echoRequest.stdout:
        sys.stdout.write(data)

    if echoRequest.stderr:
        sys.stderr.write(data)

    if echoRequest.exitCode is not None:
        sys.exit(echoRequest.exitCode)

    return echoRequest.data


def toXapiArgs(args):
    result = []
    for k, v in args.iteritems():
        if v is not None:
            result.append('args:%s="%s"' % (k, v))
    return result


if __name__ == "__main__":
    import XenAPIPlugin
    XenAPIPlugin.dispatch({ECHO_FN_NAME: echo})
