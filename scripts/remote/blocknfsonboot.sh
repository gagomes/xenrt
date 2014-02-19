#!/bin/bash

/bin/logger "Blocking NFS access as part of HA testing"
/sbin/iptables -I OUTPUT -p tcp --dport 111 -j DROP
/sbin/iptables -I OUTPUT -p udp --dport 111 -j DROP
/sbin/iptables -I OUTPUT -p udp --dport 2049 -j DROP

