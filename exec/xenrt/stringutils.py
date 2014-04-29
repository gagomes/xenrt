import random
import string
from zope.interface import implements
import xenrt


class RandomStringGenerator(object):
    implements(xenrt.interfaces.StringGenerator)

    def __init__(self):
        self.__seed = string.ascii_lowercase + \
                      string.ascii_uppercase + \
                      string.digits
        self.__length = 30

    @property
    def length(self):
        return self.__length

    def generate(self):
        return ''.join(random.choice(self.__seed)
                for x in range(self.__length))
