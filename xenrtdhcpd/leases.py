#!/usr/bin/python

import psycopg2, time

LEASE_TIME=14400

conn = psycopg2.connect("host='127.0.0.1' dbname='dhcp' user='dhcp' password='dhcp'")
cur = conn.cursor()

cur.execute("SELECT addr, mac, expiry FROM leases WHERE mac IS NOT NULL and mac != '' AND mac != 'static' AND expiry IS NOT NULL")

while True:
    r = cur.fetchone()
    if not r:
        break
    start = time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime(r[2]-LEASE_TIME))
    end = time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime(r[2]))
    print "lease %s {" % r[0]
    print "  starts 1 %s;" % start
    print "  ends 1 %s;" % end
    print "  tstp 1 %s;" % end
    print "  cltt 1 %s;" % start
    print "  binding state free;"
    print "  hardware ethernet %s;" % r[1]
    print "}"
