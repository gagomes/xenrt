#!/usr/bin/python
# Copyright (C) 2006-2007 XenSource Ltd.
# Copyright (C) 2008-2012 Citrix Ltd.
#
# This program is free software; you can redistribute it and/or modify 
# it under the terms of the GNU Lesser General Public License as published 
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU Lesser General Public License for more details.
#
# Tool to do migrate from LVHD based vdi to Raw LUN. Usage is 
# "migrate_LVHDVDI_RAWVDI.py <dest_vdi_uuid> <src_vdi_uuid>".  
# Both the vdi should be in detach state for migration to work.

import os
import shlex
import sys
import util
import lvutil
import lvhdutil
import vhdutil
import scsiutil
import B_util

def get_dom0_vm(session):
    host_ref = util.get_localhost_uuid(session)
    expr = 'field "is_control_domain" = "true" and field "resident_on" = "%s"'
    expr = expr % host_ref
    return session.xenapi.VM.get_all_records_where(expr).keys()[0]

def create_vbd(session, vm_ref, vdi_ref):
    vbd_rec = {}
    vbd_rec['VM'] = vm_ref
    vbd_rec['VDI'] = vdi_ref
    vbd_rec['userdevice'] = 'autodetect'
    vbd_rec['bootable'] = False
    vbd_rec['mode'] = 'RW'
    vbd_rec['type'] = 'disk'
    vbd_rec['unpluggable'] = True
    vbd_rec['empty'] = False
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    return session.xenapi.VBD.create(vbd_rec)

def migrate_VHD_RAW(dest_vdi_uuid, src_vdi_uuid):
    session = util.get_localAPI_session()

    # For migration to work, both the vdis should be in detach state.
    dest_vdi_ref = session.xenapi.VDI.get_by_uuid(dest_vdi_uuid)
    src_vdi_ref = session.xenapi.VDI.get_by_uuid(src_vdi_uuid)
    if B_util.is_vdi_attached(session, dest_vdi_ref) or B_util.is_vdi_attached(session, src_vdi_ref):
        print "Migration NOT complete, one of the vdis is attached to a vm!!!"
        return False

    # Migration supported only if the src sr is of type lvmohba or lvmoiscsi
    src_sr_ref = session.xenapi.VDI.get_SR(src_vdi_ref)
    src_sr_rec = session.xenapi.SR.get_record(src_sr_ref)

    if not ((src_sr_rec['type'] == 'lvmoiscsi') or (src_sr_rec['type'] == 'lvmohba')):
        print("Migration NOT complete, src vdi SR of type %s not supported !!!" \
                                                            % src_sr_rec['type'])
        return False

    # Migration supported only if the dest sr is of type hba
    dest_sr_ref = session.xenapi.VDI.get_SR(dest_vdi_ref)
    dest_sr_rec = session.xenapi.SR.get_record(dest_sr_ref)
    if not (dest_sr_rec['type'] == 'rawhba'):
        print("Migration cannot be completed, dest vdi SR must be of type hba !!!")
        return False

    # Make sure that the dest vdi can contain the data in src vdi
    src_vdi_rec = session.xenapi.VDI.get_record(src_vdi_ref)
    dest_vdi_rec = session.xenapi.VDI.get_record(dest_vdi_ref)
    if not (int(dest_vdi_rec['virtual_size']) > \
            int(src_vdi_rec['physical_utilisation'])):
            print("Migration NOT complete, dest vdi virtual-size: %s less than src physical_utilisation %s" % (dest_vdi_rec['virtual_size'], src_vdi_rec['physical_utilisation']))
            return False

    # Create and plug vbds connecting src vdi and dest and dom0
    # This way will take care of multipath if any
    dom0_ref = get_dom0_vm(session)
    
    src_vbd_ref = create_vbd(session, dom0_ref, src_vdi_ref)
    try:
        print("Plugging src VBD")
        session.xenapi.VBD.plug(src_vbd_ref)
    except:
        session.xenapi.VBD.destroy(src_vbd_ref)
        print("Migration NOT complete, srv vbd plug failed !!!")
        return False

    dest_vbd_ref = create_vbd(session, dom0_ref, dest_vdi_ref)
    try:
        print("Plugging dest VBD")
        session.xenapi.VBD.plug(dest_vbd_ref)
    except:
        session.xenapi.VBD.unplug(src_vbd_ref)
        session.xenapi.VBD.destroy(src_vbd_ref)
        session.xenapi.VBD.destroy(dest_vbd_ref)
        print("Migration NOT complete, dest vbd plug failed !!!")
        return False

    # Get the tap dev corresponding to the src device
    # Generate the LV name
    src_sr_uuid = src_sr_rec['uuid']
    dest_sr_uuid = dest_sr_rec['uuid']
    vg_name = lvhdutil.VG_PREFIX + src_sr_uuid
    lv_name = lvhdutil.LV_PREFIX[vhdutil.VDI_TYPE_VHD] + src_vdi_uuid
    vhd_path = os.path.join(lvhdutil.VG_LOCATION, vg_name, lv_name)

    # Probe tap-ctl to get the minor number 
    cmd = "tap-ctl list -f %s" % vhd_path
    args = shlex.split(cmd)
    (rc,stdout,stderr) = util.doexec(args)
    output = stdout.split(' ')
    minor = output[1].split('=')[1]
    src_dev = "/dev/xen/blktap-2/tapdev" + minor

    # Generate dest device
    dest_sympath = "/dev/sm/phy/%s/%s" % (dest_sr_uuid,dest_vdi_uuid)
    dest_dev = os.path.realpath(dest_sympath)
    
    # Perform a dd from input to output device
    cmd = "dd if=%s of=%s bs=1048576" % (src_dev, dest_dev)
    print("Performing '%s'" % cmd)
    args = shlex.split(cmd)
    (rc,stdout,stderr) = util.doexec(args)
    if rc != 0:
        print("Migration NOT complete, could not perform a dd on target")
    else:
        session.xenapi.VBD.unplug(src_vbd_ref)
        session.xenapi.VBD.destroy(src_vbd_ref)
        session.xenapi.VBD.unplug(dest_vbd_ref)
        session.xenapi.VBD.destroy(dest_vbd_ref)
        print("Migration Complete !!!")
        return True

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Incorrect Usage !!!")
        print("/opt/xensource/sm/migrate_LVHDVDI_RAWVDI.py <dest_vdi_uuid> <src_vdi_uuid>")
    else:
        migrate_VHD_RAW(sys.argv[1], sys.argv[2])


