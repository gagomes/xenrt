import xenrt


def assertTrue(actualValue, message=None):
    assertEquals(True, actualValue, message)


def assertFalse(actualValue, message=None):
    assertEquals(False, actualValue, message)


def assertEquals(expectedValue, actualValue, message=None):
    if not message:
        message = "%s != %s" % (repr(expectedValue), repr(actualValue))

    if expectedValue != actualValue:
        raise xenrt.XRTFailure(message)


def assertIn(expectedFragment, actualData, message=None):
    if not message:
        message = "%s was not found in %s" % (expectedFragment, actualData)

    if expectedFragment not in actualData:
        raise xenrt.XRTFailure(message)

