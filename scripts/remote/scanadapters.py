#!/usr/bin/env python                                                                                                                                                                                        
# this script is used for refresh 
# the attached adapters on the host 
# using storage manager utilities.

import sys
if '/opt/xensource/sm' not in sys.path:
    sys.path = ['/opt/xensource/sm'] + sys.path

import devscan

if __name__ == "__main__":
    devscan.adapters()
    sys.exit(0)
