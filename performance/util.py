#!/usr/bin/env

#
# util.py
#
# Miscellaneous functions for performance report generation.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

def cf(value):
    """Convert value to a float if possible."""
    try: return float(value)
    except: return value

def ci(value):
    """Convert value to an int if possible."""
    try: return int(value)
    except: return value

def unique(variable, objects):
    """Given a list of objects, return a list of the distinct values
       present under a certain instance variable."""
    return list(set([ getattr(x, variable) for x in objects ]))

def combinations(values):
    """Choose all the combinations from a list of lists."""
    if len(values) == 1: 
        return [ [x] for x in values[0] ]
    return [ [x] + y for x in values[0] for y in combinations(values[1:]) ]

def all(values):
    """Return True if all the items of values are True."""
    return reduce(lambda x,y:x and y, values)

