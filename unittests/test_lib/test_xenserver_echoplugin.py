import os
import testing

from xenrt.lib.xenserver import echoplugin


class TestEchoRequest(testing.XenRTUnitTestCase):
    def test_init(self):
        req = echoplugin.EchoRequest(
            stdout='stdout',
            stderr='stderr',
            path='path',
            data='data',
            exitCode='exitCode'
        )

        self.assertEquals('stdout', req.stdout)
        self.assertEquals('stderr', req.stderr)
        self.assertEquals('path', req.path)
        self.assertEquals('data', req.data)
        self.assertEquals('exitCode', req.exitCode)

    def test_fresh_objects_are_equal(self):
        req1 = echoplugin.EchoRequest()
        req2 = echoplugin.EchoRequest()

        self.assertTrue(req1 == req2)

    def test_equals_if_data_differs_objects_not_equal(self):
        req1 = echoplugin.EchoRequest()
        req2 = echoplugin.EchoRequest()

        req2.data = 'HELLO'

        self.assertFalse(req1 == req2)

    def test_serialise_deserialise_default_values(self):
        req1 = echoplugin.EchoRequest()
        args = req1.serialize()

        req2 = echoplugin.parseRequest(args)

        self.assertTrue(req1 == req2)

    def test_serialise_deserialise_exit_value(self):
        req1 = echoplugin.EchoRequest()
        args = req1.serialize()

        req2 = echoplugin.parseRequest(args)

        self.assertEquals(None, req2.exitCode)

    def test_serialise_deserialise_custom_exit_value(self):
        req1 = echoplugin.EchoRequest()
        req1.exitCode = 1
        args = req1.serialize()

        req2 = echoplugin.parseRequest(args)

        self.assertEquals(1, req2.exitCode)


class TestParseRequest(testing.XenRTUnitTestCase):
    def test_data_parsed(self):
        req1 = echoplugin.EchoRequest()
        req1.data = 'HELLO'

        req2 = echoplugin.parseRequest(req1.serialize())

        self.assertEquals('HELLO', req2.data)

    def test_stdout_parsed(self):
        req1 = echoplugin.EchoRequest()
        req1.stdout = True

        req2 = echoplugin.parseRequest(req1.serialize())

        self.assertEquals(True, req2.stdout)

    def test_stderr_parsed(self):
        req1 = echoplugin.EchoRequest()
        req1.stderr = True

        req2 = echoplugin.parseRequest(req1.serialize())

        self.assertEquals(True, req2.stderr)

    def test_path_parsed(self):
        req1 = echoplugin.EchoRequest()
        req1.path = '/something'

        req2 = echoplugin.parseRequest(req1.serialize())

        self.assertEquals('/something', req2.path)

    def test_default_values(self):
        null_req = echoplugin.EchoRequest()
        req = echoplugin.parseRequest({})

        self.assertTrue(null_req == req)


class TestToXapiArgs(testing.XenRTUnitTestCase):
    def test_args_empty(self):
        self.assertEquals([], echoplugin.toXapiArgs({}))

    def test_none_ignored(self):
        args = {'key': None}

        self.assertEquals([], echoplugin.toXapiArgs(args))

    def test_args_conversion(self):
        self.assertEquals(
            ['args:key="value"'], echoplugin.toXapiArgs({'key': 'value'}))


class TestGetSource(testing.XenRTUnitTestCase):
    def test_get_source(self):
        echopluginPath = echoplugin.__file__
        echoPluginDir = os.path.dirname(echopluginPath)
        echoPluginSource = os.path.join(echoPluginDir, 'echoplugin.py')

        with open(echoPluginSource, 'rb') as echoPluginFile:
            echoPluginSource = echoPluginFile.read()

        self.assertEquals(
            echoPluginSource, echoplugin.getSource())
