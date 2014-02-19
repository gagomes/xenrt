#!/bin/bash
mkfs.ext3 /dev/${1}
mkfs.ext3 /dev/${2}
mkdir -p /home/mysql/data
mkdir -p /home/mysql/logs
mount /dev/${1} /home/mysql/data
mount /dev/${2} /home/mysql/logs
echo "/dev/${1} /home/mysql/data ext3 defaults 1 1" >> /etc/fstab
echo "/dev/${2} /home/mysql/logs ext3 defaults 1 1" >> /etc/fstab

