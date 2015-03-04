# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer libraries
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

# Import all symbols from this package to our namespace. This is only
# for users of this package - internal references are to the submodules

import xenrt
import xenrt.lib.debugger.breakpoint2 
import xenrt.lib.debugger.codegen 
import ast, pickle, copy, subprocess, os

class debuggerFunctions(object):
    def __init__(self,tc_instance):
        self.testcase_instance = tc_instance
        self.breakpoint_counter = [0]
        self.breakpoint_files_ast = {}
        basedir = '/home/xenrtd/debugger_files'
        self.jobdir = basedir + '/%s'%(xenrt.GEC().jobid())
        try:
            if not self._exists(basedir):
                xenrt.TEC().logverbose("Creating directory %s" % (basedir))
                self._makedirs(basedir)
            if not self._exists(self.jobdir):
                xenrt.TEC().logverbose("Creating job subdirectory %s"%(self.jobdir))
                self._makedirs(self.jobdir)
                xenrt.TEC().logverbose("Created subdirectory %s" % (self.jobdir))
        except Exception, e:
            raise xenrt.XRTError("Unable to create subdirectory in %s (%s)." %
                                 (basedir, str(e)))

    def _makedirs(self,path):
        os.makedirs(path)

    def _exists(self, path):
        return os.path.exists(path)

    def initializeVars(self,job_id):
        ast_file_obj = open('/usr/share/xenrt/results/jobs/%s/temp_ast_data'%job_id,'rb')
        self.breakpoint_files_ast = pickle.load(ast_file_obj)
        ast_file_obj.close()
        self.tcdir = self.jobdir + '/%s'%(self.testcase_instance.runningtag)
        if not self._exists(self.tcdir):
            self._makedirs(self.tcdir)
            xenrt.TEC().logverbose("Created TC subdirectory %s" % (self.tcdir))

    def breakPointH2(self,filename,func_name,class_name,frame_number,job_id,loop_tag = 0,quiet = 0, contp = 0):
        if self.breakpoint_counter[0] == 0:
            self.initializeVars(job_id)
        loc_obj = open('%s/debugger_loc'%(self.tcdir),'w')
        log_obj = open('%s/debugger_logs'%(self.tcdir),'a')
        mod_before_obj = xenrt.lib.debugger.breakpoint2.Modify_AST(filename,2)
        mod_before_obj.visit(self.breakpoint_files_ast[filename])
        temp_file_obj = open('%s/temp_file.py'%(self.tcdir),'w')
        src = xenrt.lib.debugger.codegen.to_source(self.breakpoint_files_ast[filename])
        temp_file_obj.write(src)
        temp_file_obj.close()
        if quiet == 0:
            lineno_obj = xenrt.lib.debugger.breakpoint2.Testing(filename,func_name,class_name,frame_number,loop_tag,lineno_offset = 1, log_obj = loc_obj)
            lineno_obj.visit(ast.parse(src))
            xenrt.TEC().logverbose('Breakpoint: Pausing Execution')
            self.testcase_instance.pause('Breakpoint')
        temp_file_obj = open('%s/temp_file.py'%(self.tcdir),'r')
        orig_ast = ast.parse(temp_file_obj.read())
        temp_file_obj.close()
        pre_mod_before_obj = xenrt.lib.debugger.breakpoint2.pre_Modify()
        pre_mod_before_obj.visit(orig_ast)
        modify_ast_obj = xenrt.lib.debugger.breakpoint2.Modify_AST(filename,1)
        modify_ast_obj.visit(orig_ast)
        self.breakpoint_files_ast[filename] = orig_ast
        a2 = copy.deepcopy(orig_ast)
        a = xenrt.lib.debugger.breakpoint2.Testing(filename,func_name,class_name,frame_number,loop_tag)
        a.visit(a2)
        list_returned = a.l
        module_obj = ast.parse('')
        for i in range(len(list_returned)):
            module_obj.body.append(list_returned[i])
            list_returned[i] = compile(module_obj,'<string>','exec')
            log_obj.write('*****************************************************************************************************************************************************************\n')
            log_obj.write(xenrt.lib.debugger.codegen.to_source(module_obj))
            log_obj.write('\n')
            module_obj.body = []
        self.breakpoint_counter[0] += 1
        log_obj.write('###########################################################################################################################################################\n')
        log_obj.close()
        return list_returned

    def breakPointH4(self,filename,func_name,class_name,frame_number,job_id,loop_tag = 0,quiet = 0, contp = 0, error_message = 'Unknown'):
        if self.breakpoint_counter[0] == 0:
            self.initializeVars(job_id)
        log_obj = open('%s/debugger_logs'%(self.tcdir),'a')
        loc_obj = open('%s/debugger_loc'%(self.tcdir),'w')
        try:
            orig_ast = self.breakpoint_files_ast[filename]
            modify_ast_obj = xenrt.lib.debugger.breakpoint2.Modify_AST(filename,autoi = 1,style=-1,f_num=frame_number,l_num = loop_tag,i_num=contp, H4class_name = class_name, H4func_name = func_name)    #Autom(contp) #Modify_AST(filename,2)
            modify_ast_obj.visit(orig_ast)
        except Exception as e:
            log_obj.write('Error thrown here')
            log_obj.write('%s'%(e.message))
        file_obj = open('%s/temp_file.py'%(self.tcdir),'w')
        try:
            src = xenrt.lib.debugger.codegen.to_source(orig_ast)
        except Exception as e1:
            log_obj.write('Error thrown here e1')
            log_obj.write('%s'%(e.message))
        file_obj.write(src)
        file_obj.close()
        lineno_obj = xenrt.lib.debugger.breakpoint2.Testing(filename,func_name,class_name,frame_number,loop_tag, autom = 1,contp = contp, lineno_offset = 1, log_obj = loc_obj)
        lineno_obj.visit(ast.parse(src))
        
        xenrt.TEC().logverbose('Exception Catching: Pausing Execution. Edit code and continue')
        xenrt.TEC().logverbose('ERROR: %s'%(error_message))
        self.testcase_instance.pause('Exception Catching')
        file_obj = open('%s/temp_file.py'%(self.tcdir),'r')
        a2 = ast.parse(file_obj.read())
        file_obj.close()
        a = xenrt.lib.debugger.breakpoint2.Testing(filename,func_name,class_name,frame_number,loop_tag, autom = 1,contp = contp)
        a.visit(a2) 
        list_returned = a.l
        file_obj = open('%s/temp_file.py'%(self.tcdir),'r')
        a3 = ast.parse(file_obj.read())
        file_obj.close()
        modify_ast_obj2 = xenrt.lib.debugger.breakpoint2.Autom(-1)
        modify_ast_obj2.visit(a3)
        pre_modify_obj = xenrt.lib.debugger.breakpoint2.pre_Modify()
        pre_modify_obj.visit(a3)
        self.breakpoint_files_ast[filename] = a3
        module_obj = ast.parse('')
        for i in range(len(list_returned)):
                module_obj.body.append(list_returned[i])
                list_returned[i] = compile(module_obj,'<string>','exec')
                log_obj.write('*****************************************************************************************************************************************************************\n')
                log_obj.write(xenrt.lib.debugger.codegen.to_source(module_obj))
                log_obj.write('\n')
                module_obj.body = []
        self.breakpoint_counter[0] += 1
        log_obj.write('###########################################################################################################################################################\n')
        log_obj.close()
        return list_returned
