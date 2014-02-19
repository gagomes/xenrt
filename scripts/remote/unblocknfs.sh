#!/bin/bash

/bin/logger "Unblocking NFS access as part of HA testing"
/sbin/iptables -D OUTPUT -p tcp --dport 111 -j DROP
/sbin/iptables -D OUTPUT -p udp --dport 111 -j DROP
/sbin/iptables -D OUTPUT -p udp --dport 2049 -j DROP

