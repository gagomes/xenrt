#!/bin/bash

# chkconfig: 2345 09 99
# description: Blocks NFS on boot

. /etc/rc.d/init.d/functions

start() {
  /bin/logger "Blocking NFS access as part of HA testing"
  /sbin/iptables -I OUTPUT -p tcp --dport 111 -j DROP
  /sbin/iptables -I OUTPUT -p udp --dport 111 -j DROP
  /sbin/iptables -I OUTPUT -p udp --dport 2049 -j DROP
}

stop() {
  /bin/true
}

case "$1" in
  start)
    start
    ;;
  stop)
    stop
    ;;
  *)
    echo $"Usage: $0 {start|stop}"
    exit 1
esac

