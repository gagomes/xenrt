#!/usr/bin/python

import sys
import re

# 
# The following list of commands doesn't have an easy mapping to 
# Client.* APIs. 

# diagnostic-compact diagnostic_compact 
# diagnostic-db-log diagnostic_db_log 
# diagnostic-db-stats diagnostic_db_stats 
# diagnostic-gc-stats diagnostic_gc_stats 
# host-all-editions host_all_editions 
# log-get log_get 
# log-get-keys log_get_keys 
# log-reopen log_reopen 
# log-set-output log_set_output 
# pool-dump-database pool_dump_db 
# pool-restore-database pool_restore_db 
# pool-retrieve-wlb-diagnostics pool_retrieve_wlb_diagnostics 
# pool-retrieve-wlb-report pool_retrieve_wlb_report 
# regenerate-built-in-templates regenerate_built_in_templates 
# snapshot-export-to-template snapshot_export 
# template-export template_export 
# vm-cd-list vm_disk_list 
# vm-crashdump-list vm_crashdump_list 
# vm-disk-list vm_disk_list 
# vm-export vm_export 
# vm-vif-list vm_vif_list 




ADDITIONAL_MAPPING = {
    'event_wait' : ['event_wait_gen']
    }

ocaml_comment = re.compile(r'\(\*.+?\*\)', re.DOTALL)
cmdtable_start = re.compile(r'^\s*rec\s*cmdtable_data')
let = re.compile(r'^let\s+', re.MULTILINE)
cmd_list = re.compile(r'\[(.*)\]', re.DOTALL|re.MULTILINE)

def strip_comments(content, comment_obj=ocaml_comment):
    return comment_obj.sub('', content)
    
def read_file_contents(fd):
    content = "".join(fd.readlines())
    return content

def get_all_lets(content):
    return let.split(content)[1:]

def get_cmd_table_string(lets):
    return filter(lambda x: cmdtable_start.match(x) is not None, lets)[0]

def get_cmd_table(cmd_string):
    return cmd_list.search(cmd_string).group(1)

def split_into_cmds(cmd_table_contents):
    p1 = re.compile(r'\}\s*;')  # match };
    tmp_lst_1 = p1.split(cmd_table_contents)
    
    p2 = re.compile(r',\s*\{')  # match ,\n{
    tmp_lst_2 = map(lambda x: p2.split(x), tmp_lst_1)
    
    cmd_obj = re.compile(r'"(.*)"')
    implementation_obj = re.compile(r'implementation\s*=.*?Cli_operations\.(\w+)')

    def get_cmd_implementation_pair(x):
        cmd_m = cmd_obj.search(x[0])
        if cmd_m:
            cmd = cmd_m.group(1)
        else:
            cmd = None

        if cmd is None:
            return (None, None)
        
        impl_m = implementation_obj.search(x[1])
        if impl_m:
            impl = impl_m.group(1)
        else:
            impl = None
        return (cmd, impl)

    tmp_lst_3 = map(get_cmd_implementation_pair, tmp_lst_2)
    
    tmp_lst_4 = filter(lambda x: x[0] is not None, tmp_lst_3)

    return dict(tmp_lst_4)

def print_cmds_and_impl_functions(cmd_dict):
    for cmd, impl in cmd_dict.items():
        print "%s %s" % (cmd, impl)
    return

def get_dict_of_cmds(fd):
    contents = strip_comments(read_file_contents(fd))
    cmd_string = get_cmd_table_string(get_all_lets(contents))
    cmd_table_contents = get_cmd_table(cmd_string)
    cmd_impl_dict = split_into_cmds(cmd_table_contents)
    # print_cmds_and_impl_functions(cmd_impl_dict)
    return cmd_impl_dict


def get_fun_api_list(fun_list):
    
    cmd_impl_obj = re.compile(r'^\w+\b')
    api_obj = re.compile(r'Client\.[.A-Za-z_]+')
    
    def cmd_apis_pair(x):
        cmd_m = cmd_impl_obj.match(x)
        if cmd_m is None:
            cmd = None
        else:
            cmd = cmd_m.group()
        if cmd is None:
            return (None, set([]))
        
        apis = api_obj.findall(x)
        return (cmd, set(apis))
    
    tmp_lst_1 = map(cmd_apis_pair, fun_list)

    tmp_lst_2 = filter(lambda x: x[0] is not None, tmp_lst_1)
    # tmp_lst_2 = filter(lambda x: x[0] is not None and len(x[1]) > 0, tmp_lst_1)

    return dict(tmp_lst_2)


def print_cli_api_list(cmd_impl_dict, api_dict):

    cmds = cmd_impl_dict.keys()
    cmds.sort()
    
    additional_mapping = set(ADDITIONAL_MAPPING.keys())

    for cmd in cmds:
        
        impl = cmd_impl_dict[cmd]
        apis = list(api_dict[impl])
        if impl in additional_mapping:
            for fun in ADDITIONAL_MAPPING[impl]:
                apis.extend(list(api_dict[fun]))
        # if len(apis) == 0:
        #     continue
        apis.sort()
        print "%s %s" % (cmd, ' '.join(apis))

    return

if __name__ == "__main__":
    fd = open('cli_frontend.ml')
    cmd_impl_dict = get_dict_of_cmds(fd)
    fd.close()

    fd = open('cli_operations.ml')
    contents = strip_comments(read_file_contents(fd))
    fun_list = get_all_lets(contents)
    # for i in fun_list:
    #     print i
    api_dict = get_fun_api_list(fun_list)
    fd.close()
    
    print_cli_api_list(cmd_impl_dict, api_dict)
    
    sys.exit(0)
