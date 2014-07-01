#!/usr/bin/python
import time, re, sys, psycopg2

import xenrtallocator

ip = None
mac = None
lease = None

conn = psycopg2.connect("host='127.0.0.1' dbname='dhcp' user='dhcp' password='dhcp'")
cur = conn.cursor()
conn.autocommit=True

xenrtallocator.XenRTDHCPAllocator()

query = "UPDATE leases SET mac=NULL"
print query
cur.execute(query)

with open(sys.argv[1]) as f:
    for line in f:
        m = re.match("lease (.+?) {", line)
        if m:
            ip = m.group(1)
        m = re.search("ends \d+ (.+?);", line)
        if m:
            lease = time.mktime(time.strptime(m.group(1), "%Y/%m/%d %H:%M:%S"))
            if lease < time.time():
                lease = None
        m = re.search("hardware ethernet (.+?);", line)
        if m:
            mac = m.group(1)
        if ip and mac and lease:
            query = "UPDATE leases SET mac='%s', expiry=%d WHERE addr='%s'" % (mac, lease, ip)
            print query
            try:
                cur.execute(query)
            except Exception, e:
                print "Warning: " + str(e)
            ip = None
            mac = None
            lease = None
        
