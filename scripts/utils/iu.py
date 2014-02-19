#!/usr/bin/python

#                                                                                                                                                                                           
# XenRT: Test harness for Xen and the XenServer product family                                                                                                                              
#                                                                                                                                                                                           
# iSCSI utility for XenServer 5.6 FP1 (uses TransferVM)
# 
# Copyright (c) 2011 Citrix Systems, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and 
# conditions as licensed by Citrix Systems, Inc. All other rights reserved. 
#


import sys
import os
import subprocess
import xml.dom.minidom
from optparse import OptionParser
import shelve
import re

# Elements in the database
# lun_XXX = {'vdi_uuid' : xxx, 'size' : xxx, 'trvm_uuid' = xxx }
# lunid = set([1, 2, 3 ])  # -- lun numbers


POOL_MASTER = None 
POOL = None
DEFAULT_SR = None

def run_xe_cmd(cmd):
    cmd.insert(0, '/opt/xensource/bin/xe')
    p = subprocess.Popen(args=cmd,
                         stdin=None, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE,
                         close_fds=True)
    return p.stdout

def get_pool_uuid():
    global POOL
    if POOL:
        return POOL
    ret = run_xe_cmd(['pool-list', '--minimal'])
    POOL = ret.readlines()[0].strip()
    return POOL

def get_master_uuid():
    global POOL_MASTER
    if POOL_MASTER:
        return POOL_MASTER
    pool_uuid = get_pool_uuid() 
    ret = run_xe_cmd(['pool-param-get', 'uuid=%s' % pool_uuid, 'param-name=master'])
    POOL_MASTER = ret.readlines()[0].strip()
    return POOL_MASTER

def get_default_sr():
    global DEFAULT_SR
    if DEFAULT_SR:
        return DEFAULT_SR
    pool_uuid = get_pool_uuid()
    ret = run_xe_cmd(['pool-param-get', 'uuid=%s' % pool_uuid, 'param-name=default-SR'])
    DEFAULT_SR = ret.readlines()[0].strip()
    return DEFAULT_SR

def call_transfer_plugin(args):
    
    master_uuid = get_master_uuid()
    args.insert(0, 'plugin=transfer')
    args.insert(0, 'host-uuid=%s' % master_uuid)
    args.insert(0, 'host-call-plugin')
    ret = run_xe_cmd(args)
    return ret

def expose(vdi_uuid, network_mac, read_only=False):
    args = []
    args.append("transfer_mode=ISCSI")
    args.append("read_only=%s" % read_only)
    args.append("use_ssl=False")
    args.append("network_uuid=management")
    args.append("network_mode=dhcp")
    args.append("vdi_uuid=%s" % vdi_uuid)
    args.append("get_log=true")
    if network_mac!='no_mac':
        args.append("network_mac=%s" % network_mac)
    args = map(lambda x : ("args:" + x), args) 
    args.insert(0, 'fn=expose')
    ret = call_transfer_plugin(args)
    uuid = ret.readlines()[0].strip()
    return uuid

def get_record(record_handle, xml_response=False):

    fn = "get_record"
    args = []
    args.append("record_handle=" + record_handle)
    args = map(lambda arg: "args:"+arg, args)
    args.insert(0, "fn=" + fn)
    res = call_transfer_plugin(args) 

    if xml_response:
        return "".join(res.readlines())

    dom = xml.dom.minidom.parseString("".join(res.readlines()))
    attribs = dom.getElementsByTagName('transfer_record')[0].attributes
    return (dict([(k.encode('ascii'), attribs[k].value.strip().encode('ascii')) 
                  for k in attribs.keys()]))


def unexpose(trvm_uuid):
    out = run_xe_cmd(['vm-shutdown', 'uuid=%s' % trvm_uuid, 'force=true'])
    cmd = 'event-wait class=vm power-state=halted uuid=%s' % trvm_uuid
    os.system('/opt/xensource/bin/xe ' + cmd)
    out = run_xe_cmd(['vm-destroy', 'uuid=%s' % trvm_uuid])
    return

def open_db():
    db = shelve.open('iu.db', flag='c')
    return db


def parse_expose_cli():
    usage = 'Usage: %prog expose [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      action='store', default='invalid_lun',
                      help='expose the lun')
    parser.add_option('-r', '--ro', dest='read_only',
                      help='expose LUN as read-only',
                      action='store_true', default=False)
    parser.add_option('--xml', dest='xml',
                      action='store_true', default=False,
                      help='display lun info in xml format')
    parser.add_option('--mac', dest='network_mac',
                      action='store', default='no_mac',
                      help='mac address for transfer VMs vif')
    (options, args) = parser.parse_args()
    
    if options.lun == 'invalid_lun' or not options.lun.startswith('lun_'):
        parser.print_help()
        sys.exit(1)

    return options


def dispatch_expose_cmd():
    options = parse_expose_cli()
    db = open_db()
        
    if not db.has_key(options.lun):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)

    val = db[options.lun]
    vdi_uuid = val['vdi_uuid']

    if val.has_key('trvm_uuid'):
        trvm_uuid = val['trvm_uuid']
    else:
        trvm_uuid = expose(vdi_uuid, options.network_mac, options.read_only)
    val['trvm_uuid'] = trvm_uuid
    db[options.lun] = val

    record = get_record(trvm_uuid, xml_response=options.xml)
    if options.xml:
        print record
    else:
        for item in record.items():
            print "%s -> %s" % item
    
    db.close()
    return

def parse_unexpose_cli():
    usage = 'Usage: %prog unexpose [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      action='store', default='invalid_lun',
                      help='unexpose the lun')
    (options, args) = parser.parse_args()

    if options.lun == 'invalid_lun' or not options.lun.startswith('lun_'):
        parser.print_help()
        sys.exit(1)

    return options
    

def dispatch_unexpose_cmd():
    options = parse_unexpose_cli()

    db = open_db()
        
    if not db.has_key(options.lun):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)
    
    val = db[options.lun]
    if val.has_key('trvm_uuid'):
        unexpose(val['trvm_uuid'])
        del val['trvm_uuid']
        db[options.lun] = val
        
    db.close()
    return

def parse_create_lun_cli():
    usage = 'Usage: %prog create_lun [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-s', '--size', dest='lun_size',
                      help='size of the lun (suffix KiB, MiB, GiB or TiB)',
                      default='100MiB', metavar='SIZE')
    default_sr = get_default_sr()
    parser.add_option('--sr', dest='default_sr',
                      help='uuid of SR to be used for carving out LUN (vdi)',
                      action='store', default=default_sr)

    (options, args) = parser.parse_args()

    if not re.match(r'^\d+[KMGT]iB$', options.lun_size):
        print >> sys.stderr, 'lun size argument is invalid; it should match ' + r'^\d+[KMGT]iB$'
        parser.print_help()
        sys.exit(1)

    return options


def dispatch_create_lun_cmd():

    options = parse_create_lun_cli()
    
    db = open_db()

    if db.has_key('lunid'):
        lun_ids = db['lunid']
        lun_ids.add(0) # max would fail if set is empty
        free_lun_ids = set(range(max(lun_ids) + 2)) - lun_ids
        assert(free_lun_ids)
        lun = min(free_lun_ids)
    else:
        lun_ids = set([])
        lun = 0

    ret = run_xe_cmd(['vdi-create', 
                      'sr-uuid=%s' % options.default_sr, 
                      'virtual-size=%s' % options.lun_size,
                      'type=user',
                      'name-label=lun_%03d' % lun])
    
    vdi_uuid = ret.readlines()[0].strip()

    lun_ids.add(lun)
    db['lunid'] = lun_ids
    db['lun_%03d' % lun] = {'vdi_uuid' : vdi_uuid, 'size' : options.lun_size}
    db.close()
    
    print 'lun_%03d' % lun
    
    return


def parse_delete_lun_cli():
    usage = 'Usage: %prog delete_lun [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      default='invalid_lun',
                      action='store',
                      help='delete the lun')
    (options, args) = parser.parse_args()

    if options.lun == 'invalid_lun' or not options.lun.startswith('lun_'):
        parser.print_help()
        sys.exit(1)

    return options


def dispatch_delete_lun_cmd():
    options = parse_delete_lun_cli()
    
    db = open_db()
        
    if not db.has_key(options.lun):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        db.close()
        sys.exit(1)
        
    val = db[options.lun]
    if val.has_key('trvm_uuid'):
        print >>sys.stderr, 'unexpose the lun before deleting it!'
        db.close()
        sys.exit(1)

    vdi_uuid = val['vdi_uuid']
    run_xe_cmd(['vdi-destroy', 'uuid=%s' % vdi_uuid])
    del db[options.lun]

    m = re.search(r'\d+$', options.lun)
    lun = int(m.group(0))
    lunid = db['lunid']
    lunid.remove(lun)
    db['lunid'] = lunid
    db.close()
    return

def parse_list_luns_cli():
    usage = 'Usage: %prog list_luns [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-q', '--quiet', dest='quiet',
                      action='store_true', default=False,
                      help='suppress details')
    (options, args) = parser.parse_args()
    return options


def dispatch_list_luns_cmd():
    options = parse_list_luns_cli()
    db = open_db()
    for key in db.keys():
        if not key.startswith('lun_'):
            continue
        lun = key
        if options.quiet:
            print lun
        else:
            val = db[lun]
            if val.has_key('trvm_uuid'):
                exposed = 'Y'
            else:
                exposed = 'N'
            print "%s  [%s]  %s     %s" % (lun, val['vdi_uuid'], val['size'], exposed)
    db.close()
    return

def parse_clone_lun_cli():
    usage = 'Usage: %prog clone_lun [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      action='store',
                      help='clone the lun', default='invalid_lun')
    
    options, args = parser.parse_args()

    if options.lun == 'invalid_lun' or not options.lun.startswith('lun_'):
        parser.print_help()
        sys.exit(1)

    return options


def dispatch_clone_lun_cmd():
    options = parse_clone_lun_cli()
    db = open_db()
    
    if not db.has_key(options.lun):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)

    val = db[options.lun]
    vdi_uuid = val['vdi_uuid']
    lun_size = val['size']

    assert db.has_key('lunid')
    lun_ids = db['lunid']
    free_lun_ids = set(range(max(lun_ids) + 2)) - lun_ids
    assert(free_lun_ids)
    lun = min(free_lun_ids)

    ret = run_xe_cmd(['vdi-snapshot', 'uuid=%s' % vdi_uuid])
    snapshot_uuid = ret.readlines()[0].strip()

    ret = run_xe_cmd(['vdi-clone', 
                      'uuid=%s' % snapshot_uuid,
                      'new-name-label=lun_%03d' % lun])
    clone_uuid = ret.readlines()[0].strip()
    
    run_xe_cmd(['vdi-destroy', 
                'uuid=%s' % snapshot_uuid])
    
    lun_ids.add(lun)
    db['lunid'] = lun_ids
    db['lun_%03d' % lun] = { 'vdi_uuid' : clone_uuid, 'size' : lun_size }
    db.close()

    print 'lun_%03d' % lun
    return

def parse_get_info_cli():
    usage = 'Usage: %prog get_info [options]'
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      action='store', default='invalid_lun',
                      help='display info of the lun')
    parser.add_option('--xml', dest='xml',
                      action='store_true', default=False,
                      help='display lun info in xml format')

    (options, args) = parser.parse_args()
    
    if options.lun == 'invalid_lun':
        parser.print_help()
        sys.exit(1)
        
    return options
    

def dispatch_get_info_cmd():
    options = parse_get_info_cli()
    db = open_db()

    if not (options.lun.startswith('lun_') and db.has_key(options.lun)):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)
        
    lun = options.lun
    val = db[lun]
    
    if val.has_key('trvm_uuid'):
        trvm_uuid = val['trvm_uuid']
        record = get_record(trvm_uuid, xml_response=options.xml)
        if options.xml:
            print record
        else:
            print "%s %s %s" % (lun, val['vdi_uuid'], val['size'])
            for item in record.items():
                print "%s -> %s" % item
    else:
        print "%s %s %s" % (lun, val['vdi_uuid'], val['size'])
    
    db.close()
    return

def parse_generic_cmd_cli(cmd):
    usage = 'Usage: %prog' + ' %s [options]' % cmd
    parser = OptionParser(usage=usage)
    parser.add_option('-l', '--lun', dest='lun',
                      action='store', default='invalid_lun',
                      help='display info of the lun')

    (options, args) = parser.parse_args()
    
    if options.lun == 'invalid_lun':
        parser.print_help()
        sys.exit(1)
        
    return options
    

def dispatch_freeze_lun_cmd():
    options = parse_generic_cmd_cli('freeze_lun')
    db = open_db()

    if not (options.lun.startswith('lun_') and db.has_key(options.lun)):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)
        
    lun = options.lun
    val = db[lun]

    if not val.has_key('trvm_uuid'):
        print >> sys.stderr, 'LUN is not exposed ... so this is a NO-OP'
        db.close()
        return

    trvm_uuid = val['trvm_uuid']
    db.close()
    
    ret = run_xe_cmd(['vm-param-get',
                      'uuid=%s' % trvm_uuid,
                      'param-name=power-state'])
    
    trvm_state = ret.readlines()[0].strip()
    
    if trvm_state == 'running':
        run_xe_cmd(['vm-suspend', 'uuid=%s' % trvm_uuid])
        cmd = 'event-wait class=vm power-state=suspended uuid=%s' % trvm_uuid
        os.system('/opt/xensource/bin/xe ' + cmd)

    return

def dispatch_unfreeze_lun_cmd():
    options = parse_generic_cmd_cli('unfreeze_lun')
    db = open_db()

    if not (options.lun.startswith('lun_') and db.has_key(options.lun)):
        print >> sys.stderr, 'invalid/unknown lun id %s ' % options.lun
        sys.exit(1)
        
    lun = options.lun
    val = db[lun]

    if not val.has_key('trvm_uuid'):
        print >> sys.stderr, 'LUN is not exposed ... so this is a NO-OP'
        db.close()
        return

    trvm_uuid = val['trvm_uuid']
    db.close()

    ret = run_xe_cmd(['vm-param-get',
                      'uuid=%s' % trvm_uuid,
                      'param-name=power-state'])
    
    trvm_state = ret.readlines()[0].strip()
    if trvm_state == 'suspended':
        run_xe_cmd(['vm-resume', 'uuid=%s' % trvm_uuid])
        cmd = 'event-wait class=vm power-state=running uuid=%s' % trvm_uuid
        os.system('/opt/xensource/bin/xe ' + cmd)

    return

    
def print_usage():
    print """Usage: %s CMD OPTIONS
    %(prog)s help               list subcommands
    %(prog)s CMD --help         CMD suboptions 
""" % {'prog': sys.argv[0]}
    
    print 'The following subcommands are available'
    for cmd in sub_cmds.keys():
        print ' ' * 4, cmd
    
    return 


sub_cmds = {'expose': dispatch_expose_cmd,
            'unexpose' : dispatch_unexpose_cmd,
            'create_lun' : dispatch_create_lun_cmd,
            'delete_lun' : dispatch_delete_lun_cmd,
            'list_luns' : dispatch_list_luns_cmd,
            'clone_lun' : dispatch_clone_lun_cmd,
            'get_info' : dispatch_get_info_cmd,
            'freeze_lun' : dispatch_freeze_lun_cmd,
            'unfreeze_lun' : dispatch_unfreeze_lun_cmd,
            'help': print_usage}


if __name__ == "__main__":

    if len(sys.argv) == 1:
        print_usage()
        sys.exit(0)

    if sys.argv[1] not in sub_cmds.keys():
        print_usage()
        sys.exit(0)
        
    sub_cmds[sys.argv[1]]()
    sys.exit(0)
