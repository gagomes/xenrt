import xenrt


def equals(expectedValue, actualValue):
    if expectedValue != actualValue:
        raise xenrt.XRTFailure(
            '%s != %s' % (repr(expectedValue), repr(actualValue)))


