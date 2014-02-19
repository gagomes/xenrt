#!/usr/bin/python

import sys, random, time

# Perform some minimal disk I/O
sleeptime = 5
writesize = 1048576 # 1MB

try:
    while True:
        # Pattern is a sequence of ASCII characters, starting at a randomly
        # chosen one
        startChar = random.randint(0, 255)
        c = startChar
        f = file(sys.argv[1],"w")
        for i in range(writesize):
            f.write(chr(c))
            c += 1
            if c > 255:
                c = 0
        f.close()
        time.sleep(sleeptime)
        f = file(sys.argv[1],"r")
        c = startChar
        for i in range(writesize):
            if f.read(1) != chr(c):
                raise Exception("Readback doesn't match!")
            c += 1
            if c > 255:
                c = 0
        f.close()
        sys.stdout.write("%s\n" % (str(time.time())))
        sys.stdout.flush()
        time.sleep(sleeptime)

except Exception, e:
    sys.stderr.write("Exception %s triggered, exiting...\n" % (str(e)))
    sys.exit(1)

