#!/usr/bin/python

import psycopg2, json, sys

conn = psycopg2.connect("host='127.0.0.1' dbname='dhcp' user='dhcp' password='dhcp'")
cur = conn.cursor()

cur.execute("SELECT addr FROM leases WHERE mac=%s ORDER BY expiry DESC", [sys.argv[1]])

print json.dumps([x[0] for x in cur.fetchall()])
