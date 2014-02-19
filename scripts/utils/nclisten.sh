#!/bin/bash
# Netcat listen script

port=${1}

# Determine if we are using the older version of netcat, or the newer one
if (nc -h 2>&1 | grep "nc -l -p port" > /dev/null); then
  # Newer version (we use tcpserver instead)
  tcpserver 0.0.0.0 ${port} /bin/sh -c 'cat > /dev/null' &
else
  # Older version (this one listens forever so is fine)
  /bin/nc -l ${port} &
fi

