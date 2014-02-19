import ast, sys, os
import subprocess
import inspect,codegen, copy, pickle

def lineno():
    return inspect.currentframe().f_back.f_lineno
Score = {}
#@xenrt.irregularName
class pre_Modify(ast.NodeTransformer):
    #@xenrt.irregularName
    def visit_For(self,node):
        mod = ast.parse('xenrtdebugger_silentbreakpoint')
        mod.body.insert(0,node)
        self.generic_visit(node)
        return mod.body
    #@xenrt.irregularName
    def visit_If(self,node):
        return self.visit_For(node)
    #@xenrt.irregularName
    def visit_While(self,node):
        return self.visit_For(node)
    def visit_Call(self,node):
        mod_nonsilent = ast.parse('xenrtdebugger_breakpoint True')
        try:
            if node.func.value.id == 'xenrt' and node.func.attr == 'debuggerAction':
                if len(node.keywords) >= 1:
                    for i in node.keywords:
                        if i.arg == 'condition':
                            ## This is done because XRTC gives the condition in the form of a string, so gotta convert the string to ast.Compare object
                            temp = ast.parse(i.value.s)
                            temp = temp.body[0].value
                            mod_nonsilent.body[0].test = temp
                return mod_nonsilent.body
        except:
            return node
        return node

        
#@xenrt.irregularName
class Modify_AST(ast.NodeTransformer):
    counter = 0
    def __init__(self,file_name,style,func_to_call='self.debugger.breakPointH2', autoi= 1,f_num=0, l_num=0,i_num=0, H4class_name = '', H4func_name = ''):
        self.file_name = file_name
        self.func_name = ''
        self.func_list = []
        self.class_name = ''
        self.frame_score = {}
        self.frame_number = 0	
        self.contp_count = 0
        self.style = style
        self.func_to_call = func_to_call
        self.breakpstat = ast.parse('xenrtdebugger_silentbreakpoint').body[0]
        self.autoi = autoi
        self.f_num = f_num
        self.l_num = l_num
        self.i_num = i_num
        self.I = 1
        self.counter += 1
        self.H4class_name = H4class_name
        self.H4func_name = H4func_name
        self.pre = 1
        self.class_inside_class = [0,self,0]
        pass
    #@xenrt.irregularName
    def insert_breakpstatement(self,node):
        if self.autoi == 1 and not isinstance(node.body[0],ast.Until) and not isinstance(node.body[0],ast.Cont):
            node.body.insert(0,self.breakpstat)
    #@xenrt.irregularName
    def visit_FunctionDef(self,node):
        self.frame_number = 0	
        self.func_list.append(node.name)
        self.func_name = self.func_list[-1]
        self.frame_score[self.class_name][self.func_name] = {}
        self.frame_score[self.class_name][self.func_name]['frame_number'] = 0
        self.frame_score[self.class_name][self.func_name]['current_frame'] = []
        self.frame_score[self.class_name][self.func_name]['current_frame'].append(self.frame_score[self.class_name][self.func_name]['frame_number'])
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]] = {}
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag'] = 0
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag'] = 0
        self.contp_count = 0
        self.insert_breakpstatement(node)
        self.generic_visit(node)
        self.func_list.pop()
        self.func_name = (len(self.func_list) and self.func_list[-1]) or (not len(self.func_list) and '')
        return node
    #@xenrt.irregularName
    def visit_ClassDef(self,node):
        if self.class_name != '':
            print 'INSIDE HERE'
            self.class_inside_class[2] = copy.deepcopy(self)
            self = copy.deepcopy(self.class_inside_class[1])
            self.class_inside_class[0] = 1
   
        self.class_name = node.name
        self.func_name = ''
        self.frame_score[node.name] = {}
        self.generic_visit(node)
        self.class_name = ''
        if self.class_inside_class[0] == 1:
            print 'OUTSIDE HERE'
            self = copy.deepcopy(self.class_inside_class[2])
            self.class_inside_class[0] = 0
            print self.class_name, self.func_name

        return node
    #@xenrt.irregularName
    def visit_TryExcept(self, node):
        return self.visit_For(node,not_loop = 1)
    #@xenrt.irregularName
    def visit_TryFinally(self, node):
        return self.visit_For(node,not_loop = 1)
    #@xenrt.irregularName
    def visit_ExceptHandler(self, node):
        return self.visit_For(node,not_loop = 1)
    #@xenrt.irregularName
    def visit_For(self,node,not_loop = 0):
        self.insert_breakpstatement(node)
#        print self.class_name, self.func_name
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag']  = 0
        self.frame_score[self.class_name][self.func_name]['current_frame'].insert(0,self.frame_score[self.class_name][self.func_name]['frame_number'] + 1)
        self.frame_score[self.class_name][self.func_name]['frame_number'] = self.frame_score[self.class_name][self.func_name]['frame_number'] + 1
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]] = {}
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag'] = 0
        if not not_loop:
            self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['is_loop'] = 1
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag'] = 0
        self.generic_visit(node)
        self.frame_score[self.class_name][self.func_name]['current_frame'].pop(0)
        return node
        
    #@xenrt.irregularName
    def visit_While(self,node):
        return self.visit_For(node)
    #@xenrt.irregularName
    def body_orelse(self,node):
        ret = ast.parse('if True: print 1').body[0]
        ret.body = node
        node = [ret]
        return [ret]
    #@xenrt.irregularName
    def visit_If(self,node):
        try:
            if  not isinstance(node.orelse[0],ast.If):
                node.orelse = self.body_orelse(node.orelse)
        except:
            pass
        return self.visit_For(node,not_loop = 1)
    #@xenrt.irregularName
    def visit_Until(self,node):
        if self.style == 2:
            return None
        elif self.style == 1:
            return self.breakpstat
        elif self.style == -1:
            self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag'] = 1
            self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag'] += 1
            return None
        return self.visit_Cont(node,q = 1)
    #@xenrt.irregularName
    def visit_Contp(self,node):
        self.contp_count += 1
        return self.visit_Cont(node,func='H3')
    #@xenrt.irregularName
    def visit_Cont(self,node,q = 0,func = 'self.debugger.breakPointH2'):
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag'] = 1
        self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag'] += 1  
        if self.style == 1 or self.style == -1 or self.style == 2:
            ret_ast = ast.parse('xenrtdebugger_breakpoint False').body[0]
            try:
                ret_ast.test = node.test
            except:
                pass
            return ret_ast
        l = self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag'] 
        if q == 0:
            q = 'not ' + codegen.to_source(node.test)
        if 'is_loop' in self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]:
            src = '''
DONE = 0
L = 0
xenrtdebugger_iteratebreakpoint brki in %s('%s','%s','%s',frame_number = %d,loop_tag = %d,quiet = %s, contp = %d,job_id = xenrt.GEC().jobid()) :
	if DONE != 0 : 
		break
	
	else:  exec(brki) in globals(),locals()
if DONE == 3:
   	DONE = 0
   	continue
if DONE == 2:
	DONE = 0
	break
if DONE == 1:
	DONE = 0
	return L
	break
'''
        else:
            src = '''
DONE = 0
L = 0
xenrtdebugger_iteratebreakpoint brki in %s('%s','%s','%s',frame_number = %d,loop_tag = %d,quiet = %s, contp = %d, job_id = xenrt.GEC().jobid()) :
	if DONE != 0:
		break
	else:  exec(brki) in globals(),locals()
if DONE == 1:
	return L'''
        ret = ast.parse(src%(func,self.file_name,self.func_name,self.class_name,self.frame_score[self.class_name][self.func_name]['current_frame'][0],l,q, self.contp_count)).body
        return ret
    #@xenrt.irregularName
    def visit_Auto(self,node):
        src = '''
xenrtdebugger_errormarker
pass
xenrtdebugger_errormarker'''
        temp = ast.parse(src).body
        temp[1] = node
        return temp
    #@xenrt.irregularName
    def generic_visit(self,node):
        try:
            print self.class_name, self.func_name, node, type(node)
        except:
            print 'nonode'
        if self.style == 0:
            if self.class_name == '':
                return ast.NodeTransformer.generic_visit(self,node)
            elif self.func_name == '':
                return ast.NodeTransformer.generic_visit(self,node)
            elif self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['flag'] == 0 or isinstance(node,ast.For) or isinstance(node,ast.While) or isinstance(node,ast.If) or (isinstance(node,ast.TryExcept)) or (isinstance(node,ast.TryFinally)) :
                return ast.NodeTransformer.generic_visit(self,node)
            else:
                return None
        elif self.style == -1:
            try:
                pass
            except:
                pass
            if self.class_name == '':
                return ast.NodeTransformer.generic_visit(self,node)
            elif self.func_name == '':
                return ast.NodeTransformer.generic_visit(self,node)
            elif self.class_name == self.H4class_name and self.func_name == self.H4func_name and self.frame_score[self.class_name][self.func_name]['current_frame'][0] == self.f_num and self.frame_score[self.class_name][self.func_name][self.frame_score[self.class_name][self.func_name]['current_frame'][0]]['tag']== self.l_num and (isinstance(node,ast.Print) or isinstance(node,ast.Assign) or isinstance(node,ast.AugAssign) or isinstance(node,ast.Exec) or isinstance(node,ast.ImportFrom) or isinstance(node,ast.Import) or isinstance(node,ast.Expr) or isinstance(node,ast.Pass) or isinstance(node,ast.Delete) or isinstance(node,ast.Return) or isinstance(node,ast.Break) or isinstance(node,ast.Continue) or isinstance(node,ast.Raise) ):
                if self.i_num == self.I:
                    self.I += 1
                    return self.visit_Auto(node)
                else:
                    self.I += 1
                    return ast.NodeTransformer.generic_visit(self,node)
            else:
                return ast.NodeTransformer.generic_visit(self,node)
        else:
            return ast.NodeTransformer.generic_visit(self,node)

class Testing(ast.NodeTransformer):
    def __init__(self,filename,f_name,c_name,f_number,loop_tag, autom = 0,contp = 1,lineno_offset = 0, log_obj = None):
        self.filename = filename
        self.l = []
        self.toggle_obj = 0
        self.current_func = ''
        self.current_class = ''
        self.func_name = f_name
        self.class_name = c_name
        self.frame_number = f_number
        self.score = Score
        self.loop_tag = loop_tag
        self.auto = autom 
        self.contp = contp
        self.current_func_list = []
        self.lineno_offset = lineno_offset
        self.lineno_flag = 1
        self.log_obj = log_obj
        self.class_inside_class = [0,self,0]
    def returnLineno(self,node):
        if self.lineno_offset and self.check():
            self.log_obj.write("%d"%(node.lineno))
            self.log_obj.close()
    def toggle(self):
        if self.current_class == self.class_name and self.current_func == self.func_name and self.score[self.current_class][self.current_func]['current_frame'][0] == self.frame_number and self.auto == 0:
            if self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] == 1:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0
            elif  'is_loop' in self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]] and self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['is_loop'] == 1 and  self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] == self.loop_tag:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 1  
            elif self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] == self.loop_tag:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 1
    def check(self):
        return self.current_class == self.class_name and self.current_func == self.func_name and self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] == 1
    def modify(self,node,i):
        source = '''
try:
        print 1
except Exception as e:
        xenrtdebugger_iteratebreakpoint brkj in self.debugger.breakPointH4(filename =  '%s',func_name = '%s',class_name = '%s',job_id = xenrt.GEC().jobid(), frame_number = %d,loop_tag = %d,quiet = %d,contp = %d, error_message = e.message):
            exec(brkj)
'''
        try_except_node = ast.parse(source%(self.filename,self.current_func,self.current_class,self.frame_number,self.loop_tag,0,i))
        try_except_node.body[0].body = []
        try_except_node.body[0].body.append(node)
        return try_except_node.body[0]
    def hmmm(self,node):
        x = self.contp - 1 + len(self.l) + 1
        if self.check():
            self.l.append(self.modify(node,x))
        else:
            pass
    #@xenrt.irregularName
    def visit_Auto(self,node):
        if self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] == 1:
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0
        else:
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 1  

        if self.lineno_flag == 1:
            self.returnLineno(node)
            self.lineno_flag = 0
    #@xenrt.irregularName
    def visit_FunctionDef(self,node):
        self.current_func_list.append(node.name)
        self.current_func = self.current_func_list[-1]
        self.toggle_obj = 0
        if not self.current_func in self.score[self.current_class]:
            self.score[self.current_class][self.current_func] = {}
            self.score[self.current_class][self.current_func]['frame_counter'] = 0
            self.score[self.current_class][self.current_func]['current_frame'] = []
            self.score[self.current_class][self.current_func]['current_frame'].insert(0,self.score[self.current_class][self.current_func]['frame_counter'])
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]] = {}
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['reference_number']  = 0
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0		
        if self.current_class == self.class_name and self.current_func == self.func_name: 
            self.score[self.current_class][self.current_func]['current_frame'].insert(0,0)
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['reference_number'] += 1
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] = 0
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0
        self.lineno_flag = 1
        self.generic_visit(node)
        self.current_func_list.pop()
        self.current_func = (len(self.current_func_list) and self.current_func_list[-1]) or (not len(self.current_func_list) and '')
    #@xenrt.irregularName
    def visit_ClassDef(self,node):
        if self.current_class!= '':
            print 'INSIDE HERE'
            self.class_inside_class[2] = copy.deepcopy(self)
            self = copy.deepcopy(self.class_inside_class[1])
            self.class_inside_class[0] = 1
 

        self.current_class = node.name
        self.toggle_obj = 0
        self.score[node.name] = {}
        if self.current_class == self.class_name:
            if not node.name in self.score:
                self.score[node.name] = {}
        self.generic_visit(node)
        self.current_class = ''
        if self.class_inside_class[0] == 1:
            print 'OUTSIDE HERE'
            self = copy.deepcopy(self.class_inside_class[2])
            self.class_inside_class[0] = 0
            print self.current_class, self.current_func


    #@xenrt.irregularName
    def visit_Until(self,node):
        self.visit_Br(node)
    #@xenrt.irregularName
    def visit_Cont(self,node):
        self.visit_Br(node)
        self.returnLineno(node)
    #@xenrt.irregularName
    def visit_Br(self,node):
        if self.current_class == self.class_name and self.current_func == self.func_name and self.score[self.current_class][self.current_func]['current_frame'][0] == self.frame_number:
            if not 'count' in self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] = 1
            else:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] += 1
            if self.lineno_flag == 1 and not self.auto:
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] += self.lineno_offset
                self.lineno_flag = 0
            self.toggle()
    #@xenrt.irregularName
    def visit_Assign(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_AugAssign(self, node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_ImportFrom(self, node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Import(self, node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Expr(self, node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_If(self,node):
        self.visit_For(node)
    #@xenrt.irregularName
    def visit_TryExcept(self, node):
        self.visit_For(node)
    #@xenrt.irregularName
    def visit_TryFinally(self, node):
        self.visit_For(node)
    #@xenrt.irregularName
    def visit_ExceptHandler(self, node):
        self.visit_For(node)
    #@xenrt.irregularName
    def visit_For(self,node):
        self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0		
        self.score[self.current_class][self.current_func]['current_frame'].insert(0,self.score[self.current_class][self.current_func]['frame_counter'] +1)
        self.score[self.current_class][self.current_func]['frame_counter'] = self.score[self.current_class][self.current_func]['frame_counter'] + 1
        if not self.score[self.current_class][self.current_func]['current_frame'][0] in self.score[self.current_class][self.current_func]:
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]] = {}
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['reference_number'] = 0
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0		
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['is_loop'] = 1
        else:
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['toggle'] = 0
            self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['count'] = 0
            if self.score[self.current_class][self.current_func]['current_frame'][0] == self.frame_number:	
                self.score[self.current_class][self.current_func][self.score[self.current_class][self.current_func]['current_frame'][0]]['reference_number'] += 1
        self.lineno_flag = 1
        self.generic_visit(node)
        self.score[self.current_class][self.current_func]['current_frame'].pop(0)
    #@xenrt.irregularName
    def visit_While(self,node):
        self.visit_For(node)
    #@xenrt.irregularName
    def visit_With(self,node):
        pass
    #@xenrt.irregularName
    def visit_Pass(self,node):
        pass
    #@xenrt.irregularName
    def visit_Print(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Raise(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Delete(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Global(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Nonlocal(self,node):
        self.hmmm(node)
    #@xenrt.irregularName
    def visit_Break(self,node):
        Done_node = ast.parse('DONE = 2').body[0]
        self.hmmm(Done_node)
    #@xenrt.irregularName
    def visit_Continue(self,node):
        Done_node = ast.parse('DONE = 3').body[0]
        self.hmmm(Done_node)
    #@xenrt.irregularName
    def visit_Return(self,node):
        value_node = node.value
        L_node = ast.parse('L = obj').body[0]
        L_node.value = value_node
        self.hmmm(L_node)
        Done_node = ast.parse('DONE = 1').body[0]
        self.hmmm(Done_node)
    #@xenrt.irregularName
    def generic_visit(self,node):
        return ast.NodeTransformer.generic_visit(self,node)

class Autom(ast.NodeTransformer):
    def __init__(self,style = 0):
        self.func_name = ''
        self.class_name = ''
        self.style = style
        self.count = 0
    #@xenrt.irregularName
    def visit_FunctionDef(self,node):
        self.func_name = node.name
        self.generic_visit(node)
        self.func_name = ''
        self.count = 0
        return node
    #@xenrt.irregularName
    def visit_ClassDef(self,node):
        self.class_name = node.name
        self.func_name = ''
        self.generic_visit(node)
        self.class_name = ''
        return node
    def modify(self,node):
        source = '''
try:
        print 1
except Exception as e:
        print 'ERROR: ',e
        breakpp
'''
        try_except_node = ast.parse(source)
        try_except_node.body[0].body = []
        try_except_node.body[0].body.append(node)
        return try_except_node.body
    #@xenrt.irregularName
    def visit_Auto(self,node):
        if self.style < 0:
            pass
    #@xenrt.irregularName
    def generic_visit(self,node):
        src = '''
xenrtdebugger_errormarker
pass
xenrtdebugger_errormarker'''
        if self.class_name != '' and self.func_name != '':
            if isinstance(node,ast.Assign) or isinstance(node,ast.AugAssign) or isinstance(node,ast.Import) or isinstance(node,ast.ImportFrom) or isinstance(node,ast.Expr) or isinstance(node,ast.Print) or isinstance(node,ast.Pass) or isinstance(node,ast.Delete) or isinstance(node,ast.Global) or isinstance(node,ast.Return) or isinstance(node,ast.Break) or isinstance(node,ast.Continue) or isinstance(node,ast.Raise):
                self.count += 1
                if self.style != 0:
                    if self.count == self.style:
                        a = ast.parse(src)
                        a.body[1] = node
                        return a.body
                    else:
                        return node
                else:
                    return self.modify(node)
            else:
                return ast.NodeTransformer.generic_visit(self,node)
        else:
            return ast.NodeTransformer.generic_visit(self,node)

#@xenrt.irregularName
def Starter_Func(jobid):
        #Converting all the files
        import_obj = ast.parse('import xenrt.lib.debugger').body[0]
        log_obj = open('/home/xenrtd/temp_logs','w')
        breakpoint_files_list = []
        breakpoint_files_ast = {}
        sys.setrecursionlimit(1500)
        for breakpoint_r,breakpoint_d,breakpoint_f in os.walk("/usr/share/xenrt/%s-exec/testcases/xenserver/tc/"%(jobid)):
            for files in breakpoint_f:
                if files.endswith(".py") and not files.endswith("__init__.py"):
                    breakpoint_files_list.append(os.path.join(breakpoint_r,files))
        for i in breakpoint_files_list:
            try:
                temp_file_obj = open(i,'r')
                temp_ast = ast.parse(temp_file_obj.read())
                temp_file_obj.close()
                temp_ast.body.insert(0,import_obj)
                pre_modify_obj = pre_Modify()
                pre_modify_obj.visit(temp_ast)
                ##Temporary hack. Gotta figure out why this issue occurs and fix it later
                i_temp = codegen.to_source(temp_ast)
                temp_ast = ast.parse(i_temp)
                ##
                temp2_ast = copy.deepcopy(temp_ast)
                breakpoint_files_ast[i] = temp2_ast
                temp_file_obj = open(i,'w')
                modify_ast_obj = Modify_AST(i,0)
                modify_ast_obj.visit(temp_ast)
                temp_file_obj.write(codegen.to_source(temp_ast))
                temp_file_obj.close()
            except:
                temp_file_obj.close()
        log_obj.close()
        temp_file_obj = open('/usr/share/xenrt/results/jobs/%s/temp_ast_data'%(jobid),'wb')
        pickle.dump(breakpoint_files_ast,temp_file_obj)
        temp_file_obj.close()
