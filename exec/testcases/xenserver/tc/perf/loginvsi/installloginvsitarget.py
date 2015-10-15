#
# automated installation of loginvsi 3.5 target component
# according to confluence/display/perf/Automating+LoginVSI+deployment
#

import shutil
import urllib2
import sys,os
from zipfile import ZipFile, ZIP_DEFLATED
import time

def download(url,filename):
    print 'downloading %s->%s' % (url,filename)
    if not os.path.exists(os.path.dirname(filename)):
        os.mkdir(os.path.dirname(filename))
    req=urllib2.urlopen(url)
    fp=open(filename,'wb')
    shutil.copyfileobj(req,fp,65536)
    fp.close()

def unzip(file_in,dir_out):
    print 'unzipping %s->%s' % (file_in,dir_out)
    if not os.path.exists(dir_out):
        os.mkdir(dir_out)
    zf=ZipFile(file_in,'r',ZIP_DEFLATED)
    entries=zf.namelist()
    for e in entries:
        if not os.path.exists(dir_out+os.path.dirname(e)):
            os.mkdir(dir_out+os.path.dirname(e))
        if not (dir_out+e).endswith('/'):
            f=open(dir_out+e,'wb')
            f.write(zf.read(e))
            f.close()
    zf.close()
    os.remove(file_in)

def run(cmd):
    print 'running %s' % cmd
    r = os.system(cmd)
    if r != 0:
        raise Exception("%s returned: %s" % (cmd,r))

# global constants 
basedir='c:\\'
windows_share_drive='L:'
vsibasedir='c:\\Program Files\\Login Consultants\\VSI\\Files\\'
windows_sharename='loginvsi'
windows_sharename_dir=basedir+windows_sharename
windows_share='\\\\127.0.0.1\\'+windows_sharename

# run login vsi workload, assume it has already been installed
if 'runonly' in sys.argv:
    # prepare to run
    logoncmd_file='"'+vsibasedir+'Logon.cmd"'
    run('echo exit >> '+logoncmd_file)
    run('start /w "" '+logoncmd_file)
    try: # sometimes the L: drive does not persist across reboots, so mount it again
         # to make sure it is there, otherwise we'll block in the l: drive test next
        run('net use '+windows_share_drive+' '+windows_share+' /persistent:yes')
    except: # if it's already mounted, ignore the error
        pass
    while not os.path.exists("%s\\" % windows_share_drive): # config depends on L:
        print "%s: waiting for drive %s:" % (time.ctime(),windows_share_drive) 
        time.sleep(1)
    open(windows_share_drive+'\\!!!_$$$.IsActiveTest','w').write('')
    while not os.path.exists("g:\\"): # locallogon.cmd depends on g:
        print "%s: waiting for drive g:" % (time.ctime()) 
        time.sleep(1)
    run('"'+vsibasedir+'LocalLogon.cmd"')
    sys.exit(0)

# install login vsi target in unattended mode
msoffice_url=sys.argv[1]
msoffice_file=basedir+'msoffice.zip'
msoffice_config_url=sys.argv[2]
msoffice_config_file=basedir+'config.xml'
dotnet2_url=sys.argv[3]
dotnet2_file=basedir+'dotnet2.exe'
vsi_url=sys.argv[4]
vsi_file=basedir+'vsi35target.zip'
vsi_lic_url=sys.argv[5]


# download and install ms office
msoffice_dir=basedir+'office\\'
download(msoffice_url,msoffice_file)
unzip(msoffice_file,msoffice_dir)
# split big zip in 2 to workaround python zipfile bug for zipfiles >2GiB
download(msoffice_url+'2',msoffice_file+'2')
unzip(msoffice_file+'2',msoffice_dir)
download(msoffice_config_url,msoffice_config_file)
run('start /w '+msoffice_dir+'setup.exe /config "'+msoffice_config_file+'"')
run('rd /s /q '+msoffice_dir)

# download and install .net 2.0
download(dotnet2_url,dotnet2_file)
run('start /w '+dotnet2_file+' /q:a /c:"install.exe /q"')

# create loopback windows share
run('mkdir '+windows_sharename_dir)
try: # more specific rw method for win7+
    run('net share '+windows_sharename+'='+windows_sharename_dir+' /grant:everyone,full')
except: # if it fails, tries generic rw method for winxp
    run('net share '+windows_sharename+'='+windows_sharename_dir)
run('net use '+windows_share_drive+' '+windows_share+' /persistent:yes')

# copy licence
vsi_lic_file=windows_share_drive+'\\_VSI_Configuration\\LoginVSI.lic'
download(vsi_lic_url,vsi_lic_file)

# disable windows signature verification of executables
newregkey="""
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\Associations]
"LowRiskFileTypes"=".cmd;.exe;"

[HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Internet Settings\]
"CertificateRevocation"=dword:0
"""
newregkey_file=basedir+'lowriskfiletypes.reg' 
open(newregkey_file,'w').write(newregkey)
run('regedit /s '+newregkey_file)

# install vsi
download(vsi_url,vsi_file)
unzip(vsi_file,basedir)

# patch vsi_deploy.cmd to avoid popping up dialog
import re
vsideploy_file=basedir+'Target Setup\\Lib\\VSI_deploy.cmd'
vsideploy_data=open(vsideploy_file,'r').read()
s,e=re.search("(.*\n\n)(start.*\n)(.*)",vsideploy_data).span()
vsideploy_data=vsideploy_data[:s]+vsideploy_data[e:]
open(vsideploy_file,'w').write(vsideploy_data)

run('start /w "" "'+vsideploy_file+'" '+windows_share)
run('rd /s /q "'+basedir+'Target Setup"')

# tweak the type of load
for a in sys.argv:
    if 'workload:' in a:
        wk=a.split(':')[1]
        #eg.: workload:Heavy  
        target_config="""
[VSI]
Workload=%s
""" % wk
        sessiondir=windows_share_drive+'\\_VSI_Logfiles\\'
        if not os.path.exists(sessiondir):
            os.mkdir(sessiondir)        
        sessiondir+='$$$\\'
        if not os.path.exists(sessiondir):
            os.mkdir(sessiondir)        
        open(sessiondir+'VSITarget.ini','w').write(target_config)

# prepare to run
logoncmd_file='"'+vsibasedir+'Logon.cmd"'
run('echo exit >> '+logoncmd_file)
run('start /w "" '+logoncmd_file)
open(windows_share_drive+'\\!!!_$$$.IsActiveTest','w').write('')

# the only remaining thing now is to run
# c:\program files\login consultants\vsi\files\locallogon.cmd
#
if 'runnow' in sys.argv:
    run('"'+vsibasedir+'LocalLogon.cmd"')


#C:\Documents and Settings\Administrator>python install-loginvsi-target.py http:/
#/10.80.3.62/off2k7.zip http://www.uk.xensource.com/~marcusg/xenrt/loginvsi/2.con
#fig.xml http://www.uk.xensource.com/~marcusg/xenrt/loginvsi/0.dotnet2-setup.exe
#http://www.uk.xensource.com/~marcusg/xenrt/loginvsi/3.VSI35-TargetSetup.zip http
#://www.uk.xensource.com/~marcusg/xenrt/loginvsi/LoginVSI.lic workload:Heavy runnow
