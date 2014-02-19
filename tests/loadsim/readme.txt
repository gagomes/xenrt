XenRT: Exchange loadsim test

This test requires 3 ISOs:

exchange.iso            Exchange 2003 Install ISO
exchange_update.iso     Exchange 2003 SP2 ISO
outlook.iso             Administrative install of Outlook 2003

exchange.iso is an ISO version of the standard Exchange install CD
exchange_update.iso is an ISO image of the extracted Exchange SP2 files

outlook.iso is created by performing an administrative install on a windows box
as follows (The normal Outlook install CD should be in the drive):

msiexec /a d:\OUTLS11.msi

Fill in the license key etc, choose a temporary directory for the output. Then
remove the AUTORUN.INF file from the temporary directory.

The iso is then simply an image of the temporary directory.
