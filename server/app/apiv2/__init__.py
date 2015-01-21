from app import XenRTPage
from server import PageFactory
from pyramid.response import FileResponse
import os.path
import yaml
from collections import OrderedDict

def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
    class OrderedLoader(Loader):
        pass
    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))
    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
    return yaml.load(stream, OrderedLoader)

class XenRTAPIv2Swagger(XenRTPage):
    def render(self):
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "swagger.yaml")) as f:
            spec = ordered_load(f, yaml.SafeLoader)
        return spec

PageFactory(XenRTAPIv2Swagger, "/api/v2/swagger.json", reqType="GET", contentType="application/json")

class XenRTAPIv2Page(XenRTPage):
    def getMultiParam(self, paramName, delimiter=","):
        params = self.request.params.getall(paramName)
        ret = []
        for p in params:
            ret.extend(p.split(delimiter))
        return ret

    pass

import app.apiv2.jobs
