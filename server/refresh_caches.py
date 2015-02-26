#!/usr/bin/python

import sys
import app.db, app.utils

if app.db.isDBMaster():
    removeUsers = len(sys.argv) == 2 and sys.argv[1] == "removeusers"
    app.utils.refresh_ad_caches(removeUsers)
