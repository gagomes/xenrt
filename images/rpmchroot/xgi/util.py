###
# GUEST INSTALLER
# Utility functions
#
# Written by Andrew Peace, November 2005
# Copyright (C) XenSource UK Ltd.

import sys

verbosity = 2

def _log(level, val):
    global verbosity
    if level > 1: val = "> " + val
    if verbosity >= level:
        print >>sys.stderr, val

# Output the [P]CDATA from within a tag, e.g. returns
# 'data' from '<id>data</id>' when node was the 'id' node.
def getNodeData(node):
    rv = ""
    for n in node.childNodes:
        if n.nodeType == node.TEXT_NODE:
            rv += n.nodeValue
    return rv.encode('utf-8')
