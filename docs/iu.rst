============================
iSCSI Setup using TransferVM
============================


.. contents::

Introduction
============

iu.py (for the lack of better name) is a python script to quickly setup
iSCSI targets on a host running XenServer. 

The script is executed on dom0. It uses transfer vm (available from XenServer
5.6 FP1 onwards) to expose a VDI as an iSCSI target (LUN). VDIs are allocated
from the default SR. This can be overridden. Also, script can be run on any
host that is part of a pool.

The script creates a small db (iu.db) to store the LUN metadata (size, uuid, etc).

Usage
=====

::

	jobyp@joby-pc:~$ ./iu.py --help				
	Usage: {'prog': './iu.py'} CMD OPTIONS			
	    ./iu.py help               list subcommands		
	    ./iu.py CMD --help         CMD suboptions 		
								
	The following subcommands are available			
	     create_lun						
	     get_info						
	     clone_lun						
	     list_luns						
	     unexpose						
	     expose						
	     delete_lun						
	     help                                               
	
Create a LUN
------------

::

	[root@dt11 ~]# ./iu.py create_lun -h				       
	usage: Usage: iu.py create_lun [options]			       
									       
	options:							       
	  -h, --help            show this help message and exit		       
	  -s SIZE, --size=SIZE  size of the lun (suffix KiB, MiB, GiB or TiB)  
	  --sr=DEFAULT_SR       uuid of SR to be used for carving out LUN (vdi)

Example::
	
	[root@dt11 ~]# ./iu.py create_lun -s 200MiB
	lun_001
	[root@dt11 ~]#


Expose a LUN (create iSCSI target)
----------------------------------

::

	[root@dt11 ~]# ./iu.py expose -h		       
	usage: Usage: iu.py expose [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  expose the lun		       
	  -r, --ro           expose LUN as read-only	       
	  --xml              display lun info in xml format    

Example::

	[root@dt11 ~]# ./iu.py expose -l lun_001															   
	username -> 2ab7eb69b6226767																	   
	iscsi_iqn_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> iqn.2010-01.com.citrix:vdi.b00c7fb3-6215-431c-bcb3-ec64ed07d2a2.f4be57a9-7d78-4315-15d3-2c3c1203d121		   
	Iscsi_sn_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2										   
	iscsi_iqn -> iqn.2010-01.com.citrix:vdi.b00c7fb3-6215-431c-bcb3-ec64ed07d2a2.f4be57a9-7d78-4315-15d3-2c3c1203d121						   
	record_handle -> f4be57a9-7d78-4315-15d3-2c3c1203d121														   
	iscsi_lun -> 1																			   
	iscsi_sn -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2														   
	iscsi_lun_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> 1														   
	transfer_mode -> iscsi																		   
	device_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> xvdb														   
	status -> exposed																		   
	all_devices -> xvdb																		   
	ip -> 10.80.237.231																		   
	device -> xvdb																			   
	use_ssl -> false																		   
	password -> d1ae52994daf3e38																	   
	port -> 3260																			   
	vdi_uuid -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2                                                                                                                   



List the LUNs
-------------

::

	[root@dt11 ~]# ./iu.py list_luns -h		 
	usage: Usage: iu.py list_luns [options]		 
							 
	options:					 
	  -h, --help   show this help message and exit	 
	  -q, --quiet  suppress details                  


Example::

	[root@dt11 ~]# ./iu.py list_luns			       
	lun_002  [db90b75f-0c2c-4cc0-9d0e-7bfd03e0e3dd]  100MiB     N  
	lun_001  [b00c7fb3-6215-431c-bcb3-ec64ed07d2a2]  200MiB     Y  
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N  

The 4th field ``(Y|N)`` indicates whether the LUN is exposed or not.


Get the LUN info
----------------

::

	[root@dt11 ~]# ./iu.py get_info -h		       	
	usage: Usage: iu.py list_luns [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  display info of the lun	       
	  --xml              display lun info in xml format    

Example:

+ LUN that has been exposed 

::

	[root@dt11 ~]# ./iu.py get_info -l lun_001													       
	lun_001 b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 200MiB												       
	username -> 2ab7eb69b6226767															       
	iscsi_iqn_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> iqn.2010-01.com.citrix:vdi.b00c7fb3-6215-431c-bcb3-ec64ed07d2a2.f4be57a9-7d78-4315-15d3-2c3c1203d121 
	iscsi_sn_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2								       
	iscsi_iqn -> iqn.2010-01.com.citrix:vdi.b00c7fb3-6215-431c-bcb3-ec64ed07d2a2.f4be57a9-7d78-4315-15d3-2c3c1203d121				       
	record_handle -> f4be57a9-7d78-4315-15d3-2c3c1203d121												       
	iscsi_lun -> 1																	       
	iscsi_sn -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2												       
	iscsi_lun_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> 1												       
	transfer_mode -> iscsi																       
	device_b00c7fb3-6215-431c-bcb3-ec64ed07d2a2 -> xvdb												       
	status -> exposed																       
	all_devices -> xvdb																       
	ip -> 10.80.237.231																       
	device -> xvdb																	       
	use_ssl -> false																       
	password -> d1ae52994daf3e38															       
	port -> 3260																	       
	vdi_uuid -> b00c7fb3-6215-431c-bcb3-ec64ed07d2a2												       

+ An unexposed LUN																			       

::

	[root@dt11 ~]# ./iu.py get_info -l lun_002													       
	lun_002 db90b75f-0c2c-4cc0-9d0e-7bfd03e0e3dd 100MiB												       
	[root@dt11 ~]# 																	       


Unexpose the LUN
----------------

::

	[root@dt11 ~]# ./iu.py unexpose -h		       
	usage: Usage: iu.py unexpose [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  unexpose the lun		       
	                                                       
Example::

	[root@dt11 ~]# ./iu.py list_luns			       
	lun_002  [db90b75f-0c2c-4cc0-9d0e-7bfd03e0e3dd]  100MiB     N  
	lun_001  [b00c7fb3-6215-431c-bcb3-ec64ed07d2a2]  200MiB     Y  
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N  

	[root@dt11 ~]# ./iu.py unexpose -l lun_001		       

	[root@dt11 ~]# ./iu.py list_luns			       
	lun_002  [db90b75f-0c2c-4cc0-9d0e-7bfd03e0e3dd]  100MiB     N  
	lun_001  [b00c7fb3-6215-431c-bcb3-ec64ed07d2a2]  200MiB     N  
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N  
	[root@dt11 ~]# 						       

Delete the LUN
--------------

::

	[root@dt11 ~]# ./iu.py delete_lun -h		      
	usage: Usage: iu.py delete_lun [options]	      
							      
	options:					      
	  -h, --help         show this help message and exit  
	  -l LUN, --lun=LUN  delete the lun                   

Example::

	[root@dt11 ~]# ./iu.py list_luns				
	lun_002  [cc68a8a9-003f-4539-b7b5-d328d11225e4]  100MiB     N	
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N	
	lun_001  [459e424f-2802-4ac3-9fff-a0aa9e267cbc]  200MiB     N	
	[root@dt11 ~]# 							
	[root@dt11 ~]# 							
	[root@dt11 ~]# ./iu.py delete_lun -l lun_001			
	[root@dt11 ~]# 							
	[root@dt11 ~]# ./iu.py list_luns				
	lun_002  [cc68a8a9-003f-4539-b7b5-d328d11225e4]  100MiB     N	
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N	
	[root@dt11 ~]# 							
	                                                                

Clone the LUN
-------------

::

	[root@dt11 ~]# ./iu.py clone_lun -h		       
	usage: Usage: iu.py clone_lun [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  clone the lun		       
	                                                       


Example::
	
	[root@dt11 ~]# ./iu.py list_luns				  
	lun_002  [cc68a8a9-003f-4539-b7b5-d328d11225e4]  100MiB     Y	  
	lun_003  [450335c0-ee12-41d9-bd6f-98e35b81a95a]  100MiB     N	  
									  
	[root@dt11 ~]# ./iu.py clone_lun -l lun_002			  
	lun_001								  
	                                                                  

Freeze the LUN (simulate unresponsive storage)
----------------------------------------------

The purpose of this command is to make the LUN unresponsive.

::

	[root@dt11 ~]# ./iu.py freeze_lun -h		       
	usage: Usage: iu.py clone_lun [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  clone the lun		       
	                                                       
Example::
	[root@dt11 ~]# ./iu.py list_luns
	lun_000  [ad64cbac-9aee-4d82-8025-6a1dd6bde5a1]  100MiB     Y
	lun_001  [9c3eec3f-0dc7-426d-955b-9204544e4534]  100MiB     N
	[root@dt11 ~]# ./iu.py freeze_lun -l lun_000


Unfreeze the LUN
----------------

::

	[root@dt11 ~]# ./iu.py unfreeze_lun -h		       
	usage: Usage: iu.py clone_lun [options]		       
							       
	options:					       
	  -h, --help         show this help message and exit   
	  -l LUN, --lun=LUN  clone the lun		       

Example::
	[root@dt11 ~]# ./iu.py unfreeze_lun -l lun_000

Notes
=====

This usage guide is written in reStructuredText_ which is 
the standard for Python_ doc strings.

.. _reStructuredText: http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html
.. _Python: http://www.python.org 

The utility was written for PR-1223 (Disaster Recovery).

The *freeze_lun* and *unfreeze_lun* sub commands are for simulating 
unresponsive storage. 

Repository
----------

:iscsi utility: xenrt.hg/scripts/utils/iu.py
:usage guide: xenrt.hg/docs/iu.rst
