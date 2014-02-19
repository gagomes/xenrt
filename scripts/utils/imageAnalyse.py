#!/usr/bin/python

import sys
from PIL import Image
from operator import itemgetter

i = Image.open(sys.argv[1])

colours = {}
total = 0
pix = i.load()
for x in range(i.size[0]):
    for y in range(i.size[1]):
        total += 1
        if colours.has_key(pix[x,y]):
            colours[pix[x,y]] += 1
        else:
            colours[pix[x,y]] = 1

# Generate percentages, then sort in order
percents = {}
for c in colours:
    percents[c] = int((float(colours[c]) / float(total)) * 100)

pcs = percents.items()
pcs.sort(key = itemgetter(1), reverse=True)
print "Colours greater than 1%:"
for p in pcs:
    if p[1] > 1:
        print "%s: %u%%" % (p[0], p[1])

