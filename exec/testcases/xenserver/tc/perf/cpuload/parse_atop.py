import re
from pprint import pprint

filename = "atop-MNR-169820.log.txt"

text = [line for line in file(filename, 'r').read().split("\n")
        if line.strip()]

def splitOn(pred, list):
    nlist = [[]]
    for item in list:
        if not pred(item):
            nlist[-1].append(item)
        else:
            nlist.append([item])
    return nlist
def isHeader(line):
    return re.compile(r'ATOP - [^ ].* +..../../.. +..:..:.. *-* *([0-9]*h)?([0-9]*m)?[0-9]+s +elapsed').match(line) is not None

def isProcessSectionHeader(line):
    return re.compile(r' *PID +SYSCPU +USRCPU +VGROW +RGROW +RUID +THR +ST +EXC +S +CPU +CMD *').match(line) is not None

def dropUntilAfter(pred, list):
    for (i, x) in enumerate(list):
        if pred (x):
            return list[i+1:]

m = r' *([^ ]+ +)*(?P<percentage>([0-9.])*%) +(?P<name>[^ ]+) *'
        
#    """ATOP - q16       2011/01/06  13:39:58       ------         15m44s elapsed"""

#    re.compile(r'ATOP - [^ ].* *..../../..  ..:..:.. *-* *[0-9]+s elapsed"').match()

#print text

#pprint ([line[:80] for line in text if isHeader(line)])

pprint ([(lines[0],[re.sub(m, '\g<name>: \g<percentage>', line) for line in dropUntilAfter(isProcessSectionHeader, lines)
                    if re.compile(m).match(line) is not None])
         for lines in splitOn (isHeader, text) if lines][1:])
