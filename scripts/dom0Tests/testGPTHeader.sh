#!/bin/bash

#Imported from: http://hg.uk.xensource.com/git/carbon/trunk-ring0/test-ring0.git/blob/HEAD:/gdisk/test1

# Test again SCTX-1646
# --zap-all should clear partition even if backup have wrong
# LBA addresses

status() {
    echo "==================="
    echo "$@"
}

cleanup() {
    local RES=$?
    trap '' EXIT ERR
    set +e
    test "$LOOP" != "" && losetup -d $LOOP
    rm -f disk.$uuid.dat last.dat
    exit $RES
}

loopback() {
    local loop
    losetup -f "$1"
    loop=$(losetup -a | grep $uuid)
    losetup -a >&2
    loop="${loop%%:*}"
    case "$loop" in
    /dev/loop*)
        ;;
    *)
        rm -f "$1"
        exit 1
    esac
    echo $loop
}

set -ex
cd /tmp
rm -f disk.*.dat

uuid=$(uuidgen | sed 's/-//g')

# create a disk raw image of 100 MB (empty with zeroes)
dd if=/dev/zero bs=1M count=1 seek=99 of=disk.$uuid.dat

# create a block device from a file
LOOP=
trap cleanup ERR EXIT
LOOP=$(loopback disk.$uuid.dat)

# clear the disk (-o), gdisk write header and footer
sgdisk -o $LOOP

# delete the block device previously created
losetup -d $LOOP
LOOP=

# copy the last MB of data into a new "last.dat" file
dd if=disk.$uuid.dat bs=1M skip=99 count=1 of=last.dat

# create a new raw disk image of 101 MB (more that 100!)
# this image contains at the end the old GPT footer
# (which contains pointer to the last MB of the old image)
rm disk.$uuid.dat
dd if=last.dat of=disk.$uuid.dat bs=1M seek=100

# create again a block device (this time bigger)
LOOP=$(loopback disk.$uuid.dat)

# now check the the disk image we create is corrupted
# (the header is cleared and we have only a moved footer)
status 'Partition corrupted:'
sgdisk -p $LOOP || true

# now try to destroy entirely the GPT data, this should clear
# the corruption
status 'echo Going to Zap !'
sgdisk -Z $LOOP || true

# now we should able to see that there is no partitions
# if still fail we hit the bug
# (gdisk was not able to reset the disk structure)
status Fixed partitions
sgdisk -p $LOOP
