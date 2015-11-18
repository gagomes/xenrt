import xenrt


def assertTrue(actualValue, message=None):
    assertEquals(True, actualValue, message)


def assertFalse(actualValue, message=None):
    assertEquals(False, actualValue, message)

def assertNone(actualValue, message=None):
    assertEquals(None, actualValue, message)

def assertNotNone(actualValue, message=None):
    assertNotEquals(None, actualValue, message)

def assertEquals(expectedValue, actualValue, message=None):
    if expectedValue != actualValue:
        msg = message
        if not message:
            msg = '%s != %s' % (repr(expectedValue), repr(actualValue))
        raise xenrt.XRTFailure(msg)

def assertNotEquals(expectedValue, actualValue, message=None):
    if expectedValue == actualValue:
        msg = message
        if not message:
            msg = '%s != %s' % (repr(expectedValue), repr(actualValue))
        raise xenrt.XRTFailure(msg)

def assertIn(expectedFragment, actualData, message=None):
    if not message:
        message = "%s was not found in %s" % (expectedFragment, actualData)

    if expectedFragment not in actualData:
        raise xenrt.XRTFailure(message)

