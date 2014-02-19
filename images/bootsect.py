#!/usr/bin/env python
#
# Boot image extractor.
#
# Original Perl by R. Krienke <krienke@uni-koblenz.de>.
#
# Ported to python by Karl Spalding, XenSource.
#
# License: GPL
#

import sys, string, struct, getopt

vsectorsize = 512
sectorsize = 2048

def usage():
    print """Usage: %s [options] [args]

    -o <output_file>         Output file.
    -i <input_file>          Input file.
""" % (sys.argv[0])

def getSector(number, count, filename):
    # Byte list to return.
    sectors = []
    # Open the iso file for reading.
    iso = file(filename, "r")
    # Seek to the start of the sectors we want.
    iso.seek(number*sectorsize)
    # Read the sectors.
    sectorstring = iso.read(vsectorsize*count)
    iso.close()
    # Convert the result to a byte list.
    sectors = map(ord, list(sectorstring))
    return sectors

def lts(l):
    str = ""
    for c in l:
        str += chr(c)
    return str

def readBootSector(iso):
    # Read the Boot Record Volume from sector 17.
    brv = getSector(17, 1, iso)
    
    # The Boot Record Indicator must be 0.
    bri = brv[0]
    if bri != 0:
        raise Exception("Boot Record Indicator is not 0.")    
    # Make sure ISO Identifier checks out.
    isoid = lts(brv[1:6]) 
    if isoid != "CD001":
        raise Exception("The image doesn't seem to be a bootable CD.")
    # Check the descriptor version.
    version = brv[6]
    if version != 1:
        raise Exception("The Boot Record Volume version is not 1.")    
    # Get Boot System Identifer.
    bsi = lts(brv[7:30]) 
    if bsi != "EL TORITO SPECIFICATION":
        raise Exception("The Boot System Identifier is unexpected.")
    # Get the Boot Catalog pointer.
    bcpos = struct.unpack("I", lts(brv[71:75]))[0]
    print "Boot Catalog appears to start at sector %s." % (bcpos)    
 
    # Read the boot catalog.
    bootcatalog = getSector(bcpos, 1, iso)
   
    # Read the validation entry.
    validationentry = bootcatalog[0:32]
    # The Header ID must be 1.
    header = validationentry[0]
    if header != 1:
        raise Exception("Validation entry header is not 1.")
    # Get the platform ID.
    platform = validationentry[1]
    if platform == 0:
        platform = "80x86"
    elif platform == 1:
        platform = "PowerPC"
    elif platform == 2:
        platform = "Mac"
    else:
        raise Exception("Unrecognised platform.") 
    # Get the manufacturer.
    manufacturer = lts(validationentry[4:18])
    # Check entry is valid.
    if validationentry[30] != 0x55 or validationentry[31] != 0xAA:
        raise Exception("Invalid validation entry.")

    # Read default entry.
    defaultentry = bootcatalog[32:64]
    boot = defaultentry[0]
    if boot != 0x88:
        raise Exception("Boot image doesn't seem to be bootable.")
    media = defaultentry[1]
    # Try to calculate boot image size.
    if media == 0:
        media = "No emulation"
        count = 0
    elif media == 1:
        media = "1.2Mb floppy"
        count = 1200*1024/vsectorsize
    elif media == 2:
        media = "1.44Mb floppy"
        count = 1440*1024/vsectorsize
    elif media == 3:
        media = "2.88Mb floppy"
        count = 2880*1024/vsectorsize
    elif media == 4:
        media = "Harddisk"
        count = 0
    imagestart = struct.unpack("I", lts(defaultentry[8:12]))[0]
    sectorcount = struct.unpack("H", lts(defaultentry[6:8]))[0]    
    if count == 0:
        count = sectorcount

    print "Manufacturer of CD: %s" % (manufacturer)
    print "Image architecture: %s" % (platform)
    print "Boot media type is: %s" % (media)
    print "Boot image starts at sector %s and has %s sectors of %s bytes" % \
          (imagestart, count, vsectorsize)
    
    bootimage = getSector(imagestart, count, iso)
    return lts(bootimage)

i = None
o = None

try:
    optlist, optargs = getopt.getopt(sys.argv[1:], "o:i:")
    for argpair in optlist:
        (flag, value) = argpair
        if flag == "-o":
            o = value
        if flag == "-i":
            i = value
except getopt.GetoptError:
    print "Error: Unknown argument exception."
    usage()
    sys.exit(1)

if not i or not o:
    usage()
    sys.exit(1)

bootimage = readBootSector(i)
f = open(o, "w")
f.write(bootimage)
f.close() 
