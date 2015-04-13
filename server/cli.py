#!/usr/bin/python

import sys
import app.db, app.utils

if sys.argv[1] == "refreshcaches":
    if app.db.isDBMaster():
        removeUsers = len(sys.argv) == 3 and sys.argv[2] == "removeusers"
        app.utils.refresh_ad_caches(removeUsers)
elif sys.argv[1] == "borrownotify":
    if app.db.isDBMaster():
        app.apiv2.machines.NotifyBorrow(None).run()
elif sys.argv[1] == "updateteams":
    if app.db.isDBMaster():
        app.utils.update_ad_teams()
