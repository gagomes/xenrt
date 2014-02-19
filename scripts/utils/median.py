#! /usr/bin/env python

import sys, string

'''
type   thds    cas-N  num ptrs	align  frac_suc min-max us_succ	us_attempt
CASRC	16	2	256	1	0.936	2.563	33.187	31.052
CASRC	16	2	256	1	0.937	3.271	30.563	28.630
CASRC	16	2	256	64	0.927	1.494	4.994	4.630
CASRC	16	2	256	64	0.927	1.514	5.004	4.640
CASRC	16	2	256	128	0.927	1.459	4.682	4.342
CASRC	16	2	256	128	0.927	1.362	4.686	4.342
CASRCL	16	2	256	1	0.937	2.781	31.384	29.394
CASRCL	16	2	256	1	0.937	2.950	31.027	29.085


pkeys sets number of primary keys which must be at start of line


sort -t' ' -k2 -nk7 -nk9 y | ./average.py
sort -k3,3 -k1,1 -k5,5 -k9,9n -k7,7n foo |m

'''

pkeys = string.atoi(sys.argv[1])

lastkey = ['__NO_MATCH__']

vals = []
n = 0


def format2sig( v ):
    if (v < 1) :
        return "%.2f" % v 
    elif (v < 10) :
        return "%.1f" % v
    elif (v < 100) :
        return "%d" % v
    else:
        return "%d" % (int((v+5)/10) * 10)

def format3sig( v ):
    #if (v < 1) :
    #    return "  %.3f" % v   #  x.xxx#
    #el
    if (v < 10) :
        return "  %.2f" % v  #  x.xx #
    elif (v < 100) :
        return " %.1f " % v  # xx.x  #
    else:
        return "%d   " % v   #xxx    #

def format4tot( v ):
    if (v < 10) :
        return "%.2f" % v    #x.xx#
    elif (v < 100) :
        return "%.1f" % v  #xx.x#
    else:
        return "%.0f" % v   #xxx#

def format5tot( v ):
    if (v < 10) :
        return "%.2f " % v    #x.xx  #
    elif (v < 100) :
        return "%.1f " % v    #xx.x  #
    elif (v < 1000) :
        return "%d  " % v     #xxx   #
    else:
        return "%d " % v      #xxxx  #


def format6tot( v ):
    if (v < 10) :
        return "%.2f  " % v    #x.xx  #
    elif (v < 100) :
        return "%.1f  " % v    #xx.x  #
    elif (v < 1000) :
        return "%d   " % v     #xxx   #
    else:
        return "%d  " % v      #xxxx  #



def formatsig( v ):
    return "%.5f" % v
    #return "%d" % v

def pout(l,v):
    #print 'POUT', l, v 
    if len(l) >0 :
    	print '%s %s' % (reduce((lambda a,b: a+' '+b),l[1:],l[0] ), reduce( (lambda a,b: a+' %s' % formatsig(b)),v ))
    else:
	s=formatsig(v[0])
	for i in v[1:]: 
	    s=s+' '+formatsig(i) 
        #print '%s' % (reduce( (lambda a,b: a+' %s' % formatsig(b)),v))
	print s

def xxxpout(l,v):
    print '%s%s' % (reduce((lambda a,b: a+' '+b),l[1:],l[0] ), reduce( (lambda a,b: a+' %s' % format6tot(b)),v,'' )) 

def med( x ):
    x.sort()
    return x[n/2]

while 1:
    line = sys.stdin.readline()
    if len(line) == 0: break

    lineparts = string.split(line[:-1])

    try:
	#print lineparts, 'XXX', lineparts[:pkeys], 'YYY', lastkey
	if( lineparts[:pkeys] != lastkey ):
	
	    if( lastkey != ['__NO_MATCH__'] ):
		out = map( med , vals )
		pout( lastkey, out )

	    lastkey = lineparts[:pkeys]
	    vals = map( lambda x: [string.atof(x)], lineparts[pkeys:] )
	    n=1
	else:
	    v = map( lambda x: [string.atof(x)], lineparts[pkeys:] )
	    vals = map( (lambda x,y: x+y) , vals, v )
	    n=n+1
    except:
	#if len(line) < 3:
	#    print 'AAA'
	print line[:-1]
	lastkey=['__NO_MATCH__']

#print 'ZZZ', vals

out = map( med , vals )
pout( lastkey, out )

#print 'QQQ',out

