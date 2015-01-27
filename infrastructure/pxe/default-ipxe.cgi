#!/usr/bin/python

import os

extra = ""
writeStamp = False

try:
    extra = open("%s/ipxe.cfg/%s" % (os.getcwd(), os.environ["REMOTE_ADDR"])).read()
    writeStamp = True
except:
    pass

print """Content-type: text/plain

#!ipxe

menu
item default  Default XenRT boot
item razor  Boot into Razor MicroKernel
item tc     Boot into Tinycore Linux
item end    Local boot
choose --default default --timeout 5000 target && goto ${target}

:default
%s
echo Loading PXELINUX
set 210:string tftp://${next-server}/
chain tftp://${next-server}/pxelinux.0
goto end

:razor
echo Loading Razor Microkernel
chain tftp://${next-server}/razor.ipxe
goto end

:tc
echo Loading TinyCore
kernel http://${next-server}/tftp/tinycorelinux/vmlinuz
initrd http://${next-server}/tftp/tinycorelinux/core-xenrt.gz
boot
goto end

:end
""" % extra

if writeStamp:
    f = open("%s/ipxe.cfg/%s.stamp" % (os.getcwd(), os.environ["REMOTE_ADDR"]), "w")
    f.write("Accessed")
    f.close()
