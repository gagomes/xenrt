#!/usr/bin/python
# import pprint
import sys

s = """      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r       1414    0.4     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
"""

s = """      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22157    0.6     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22157    0.4     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158   11.8     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158    0.5     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158    0.6     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158    0.5     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158    0.7     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
      NAME  STATE   CPU(sec) CPU(%)     MEM(k) MEM(%)  MAXMEM(k) MAXMEM(%) VCPUS NETS NETTX(k) NETRX(k) VBDS   VBD_OO   VBD_RD   VBD_WR SSID
  Domain-0 -----r      22158    0.5     768768    2.3     768768       2.3     8    0        0        0    0        0        0        0    0
"""

header = ['NAME', 'STATE', 'CPU(sec)', 'CPU(%)', 'MEM(k)', 'MEM(%)', 'MAXMEM(k)', 'MAXMEM(%)', 'VCPUS', 'NETS', 'NETTX(k)', 'NETRX(k)', 'VBDS', 'VBD_OO', 'VBD_RD', 'VBD_WR', 'SSID']

s = sys.stdin.read()

#p = pprint.PrettyPrinter(width=200).pprint
data = ([(line[0], {'cpu':line[3], 'mem_percentage':line[5], 'mem_k':line[4]}) for line in [l.split() for l in s.split('\n') if l.strip() if l.split() != header]])

print ('#cpu sampleNum mem_percentage mem_k')
for (i,(dom,d)) in enumerate(data):
    dd = {'i':i}
    dd.update (d)
    print ("%(cpu)s" % dd)
#    print ("%(cpu)s %(i)s %(mem_percentage)s %(mem_k)s" % dd)

