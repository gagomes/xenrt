import xml.dom.minidom, sys

def truncateText(text, url):
    ret = text.split("--------")[0]
    ret += "\n\nLogs available at %s" % url
    return ret

def processTC(tc, suite, doc, url):
    t = doc.createElement("testcase")
    for a in tc.attributes.keys():
        t.setAttribute(a, tc.getAttribute(a))

    for n in tc.childNodes:
        if n.nodeName in ("system-out", "system-err"):
            continue
        
        newNode = doc.createElement(n.nodeName)
        for a in n.attributes.keys():
            if a == "message":
                newNode.setAttribute("message", truncateText(n.getAttribute("message"), url))
            else:
                newNode.setAttribute(a, n.getAttribute(a))
        for m in n.childNodes:
            if m.nodeType == m.CDATA_SECTION_NODE:
                cdata = doc.createCDATASection(truncateText(m.data, url))
                newNode.appendChild(cdata) 
            else:
                newNode.appendChild(m)
        t.appendChild(newNode)

    suite.appendChild(t)

def processSuite(suite, doc, url):
    s = doc.createElement("testsuite")

    for a in suite.attributes.keys():
        s.setAttribute(a, suite.getAttribute(a))

    for t in suite.getElementsByTagName("testcase"):
        processTC(t, s, doc, url)

    doc.appendChild(s)

with open(sys.argv[1]) as f:
    dom = xml.dom.minidom.parseString(f.read())

suites = dom.getElementsByTagName("testsuite")

d = xml.dom.minidom.Document()
for s in suites:
    processSuite(s,d, sys.argv[3])

with open(sys.argv[2], "w") as f:
    f.write(d.toprettyxml())
