#!/bin/bash

logFile=/tmp/flowCount.log

while true; do
  flowCount=`/usr/bin/ovs-dpctl show xenbr0 | grep flows | awk '{print $2}'`
  if [ $flowCount -gt "2000" ]; then
    date >> ${logFile}
    echo $flowCount >> ${logFile}
  fi
  sleep 1
done

