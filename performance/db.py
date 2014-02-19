#!/usr/bin/env python

#
# db.py
#
# Interface to the XenRT performance explorer.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import urllib, re
import config

def query(product, reference):
    configurations = ""
    for (x,y) in config.configurations.items():
        for z in y: configurations += "&%s-%s=True" % (z, x)
    query = "%s?action=perfmatrix&format=csv&revision=%s&reference=%s%s" % \
            (config.server, product, reference, configurations)
    csv = urllib.urlopen(query).read()
    return re.findall("<BR>(.*)", csv)
