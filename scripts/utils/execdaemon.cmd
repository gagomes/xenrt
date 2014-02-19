REM
REM XenRT: Test harness for Xen and the XenServer product family
REM
REM XML-RPC test execution daemon launcher
REM
REM Copyright (c) 2007 XenSource, Inc. All use and distribution of this
REM copyrighted material is governed by and subject to terms and
REM conditions as licensed by XenSource, Inc. All other rights reserved.
REM

REM Only run this on the glass
IF x%SESSIONNAME%==x GOTO AGAIN
IF NOT %SESSIONNAME%==Console GOTO LEAVESCRIPT

:AGAIN

REM Wait for post-install actions to complete
IF NOT EXIST C:\alldone.txt GOTO TRYLATER

c:\execdaemon.py

GOTO AGAIN

:TRYLATER
REM This is how we sleep for about 15 seconds...
ping 127.0.0.1 -n 15 -w 1000
GOTO AGAIN

:LEAVESCRIPT
