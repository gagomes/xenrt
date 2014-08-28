import xenrt


def assertEquals(expectedValue, actualValue):
    if expectedValue != actualValue:
        raise xenrt.XRTFailure(
            '%s != %s' % (repr(expectedValue), repr(actualValue)))


def assertIn(expectedFragment, actualData):
    if expectedFragment not in actualData:
        raise xenrt.XRTFailure(
            '%s was not found in %s' % (expectedFragment, actualData))

