#!/usr/bin/python

import sys, json

sys.path.append("/root/cloudstack.git/tools/marvin/marvin/config")

import test_data

print json.dumps(test_data.test_data, indent=2)
