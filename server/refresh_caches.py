#!/usr/bin/python

import app.db, app.utils
if app.db.isDBMaster():
    app.utils.refresh_ad_caches()
