REM
REM XenRT: Test harness for Xen and the XenServer product family
REM
REM Run the post-OS-install installer
REM
REM Copyright (c) 2007 XenSource, Inc. All use and distribution of this
REM copyrighted material is governed by and subject to terms and
REM conditions as licensed by XenSource, Inc. All other rights reserved.
REM

NETSH FIREWALL SET ALLOWEDPROGRAM PROGRAM=c:\Python27\python.exe
c:\install\install.py > c:\installer.out 2>&1

