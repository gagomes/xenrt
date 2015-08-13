#!/usr/bin/python

import uuid, sys, os, time

path = sys.argv[1]
iterations = int(sys.argv[2])
fn = str(uuid.uuid4())
fn2 = str(uuid.uuid4())

fd = os.open("%s/%s" % (path, fn), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

for i in range(iterations):
    print "Iteration %d" % i
    print "Seeking"
    starttime = time.time()
    os.lseek(fd, 1000000+i*iterations, os.SEEK_SET)
    print "Writing"
    os.write(fd, "\000")
    if time.time() - starttime > 1:
        raise Exception("Seek+write took %.02f seconds" % (time.time() - starttime))
print "Closing file"
os.close(fd)
print "Closed file"
print os.stat("%s/%s" % (path, fn))
os.unlink("%s/%s" % (path, fn))
