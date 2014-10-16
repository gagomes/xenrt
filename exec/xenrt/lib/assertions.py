import xenrt


def assertTrue(actualValue, message=None):
    assertEquals(True, actualValue, message)


def assertEquals(expectedValue, actualValue, message=None):
    if expectedValue != actualValue:
        msg = message
        if not message:
            msg = '%s != %s' % (repr(expectedValue), repr(actualValue))
        raise xenrt.XRTFailure(msg)


def assertIn(expectedFragment, actualData):
    if expectedFragment not in actualData:
        raise xenrt.XRTFailure(
            '%s was not found in %s' % (expectedFragment, actualData))

