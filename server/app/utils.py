import string, re, os

import config

colours = {"pass":       ("green", None, "#90c040"),
           "fail":       ("orange", None, None),
           "vmcrash":    ("red", None, None),
           "xencrash":   ("black", "white", None),
           "started":    ("#ccff99", None, None),
           "running":    ("#ccff99", None, None),
           "skipped":    ("#FFFFFF", None, None),
           "partial":    ("#96FF00", None, None),
           "error":      ("#667FFF", None, None),
           "other":      ("#CCCCCC", None, None),
           "paused":     ("#FF80FF", None, None),
           "continuing": ("#ccff99", None, None),
           "pass/w":     ("#F5FF80", None, "#90c040"),
           "fail/w":     ("orange", None, None),
           "vmcrash/w":  ("red", None, None),
           "xencrash/w": ("black", "white", None),
           "started/w":  ("#ccff99", None, None),
           "skipped/w":  ("#FFFFFF", None, None),
           "partial/w":  ("#96FF00", None, None),
           "error/w":    ("#667FFF", None, None),
           "other/w":    ("#CCCCCC", None, None),
           "paused/w":   ("#FF80FF", None, None),
           "continuing/w": ("#ccff99", None, None),
           "OK":         ("green", None, "#90c040"),
           "ERROR":      ("red", None, None),
           }

def colour_style(colour, rswarn=0):
    global colours
    if not colours.has_key(colour):
        colour = "other"
    fg, bg, warn = colours[colour]
    if rswarn and warn:
        fg = warn
    if fg:
        reply = "background-color: %s;" % (fg)
    else:
        reply = ""
    if bg:
        reply = reply + " color: %s;" % (bg)
    return reply

def colour_tag(colour):
    global colours
    if not colours.has_key(colour):
        colour = "other"
    fg, bg, warn = colours[colour]
    if fg:
        reply = "bgcolor=\"%s\"" % (fg)
    else:
        reply = ""
    if bg:
        reply = reply + " color=\"%s\"" % (bg)
    return reply

def parse_job(rc,cur):
    d = {}
    if rc[0]:
        d['JOBID'] = str(rc[0])
    if rc[1] and string.strip(rc[1]) != "":
        d['VERSION'] = string.strip(rc[1])
    if rc[2] and string.strip(rc[2]) != "":
        d['REVISION'] = string.strip(rc[2])
    if rc[3] and string.strip(rc[3]) != "":
        d['OPTIONS'] = string.strip(rc[3])
    if rc[4] and string.strip(rc[4]) != "":
        d['JOBSTATUS'] = string.strip(rc[4])
    if rc[5] and string.strip(rc[5]) != "":
        d['USERID'] = string.strip(rc[5])
    if rc[6] and string.strip(rc[6]) != "":
        d['UPLOADED'] = string.strip(rc[6])
    if rc[7] and string.strip(rc[7]) != "":
        d['REMOVED'] = string.strip(rc[7])

    cur.execute("SELECT param, value FROM tblJobDetails WHERE " +
                "jobid = %u;", [rc[0]])
    
    while 1:
        rd = cur.fetchone()
        if not rd:
            break
        if rd[0] and rd[1] and string.strip(rd[1]) != "" and \
               string.strip(rd[1]) != "":
            d[string.strip(rd[0])] = string.strip(rd[1])
    
    if d['JOBSTATUS'] == "running":
        cur.execute("SELECT COUNT(result) FROM tblresults WHERE jobid=%s AND result='paused';", [d['JOBID']])
        rd = cur.fetchone()
        if rd[0] > 0:
            d['PAUSED'] = "yes"
        else:
            d['PAUSED'] = "no"
    else:
        d['PAUSED'] = "no"

    return d

def results_filename(prefix, id, mkdir=0):
    if prefix == "":
        sprefix = "job"
    else:
        sprefix = prefix
    new_style = "%s/%s/%02u/%02u/%02u/%s%08u" % \
                (config.results, sprefix, (id/1000000)%100, (id/10000)%100,
                 (id/100)%100, prefix, id)
    if mkdir:
        dirname = os.path.dirname(new_style)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
    return new_style

def normalise(i):
    """
    Takes a number i, which may have a modifier of k, M, G or T and
    returns the number with the modifier applied.
    """
    
    number = 0
    multiplier = ''
    
    # Extract number part.
    number = long(re.match('[0-9]+', i).group())	
    
    # Extract modifier.
    multiplier = string.upper(re.search('[kKMGT]?$', i).group())
    
    # Normalise number.
    if multiplier == 'K':
        return number * 1024			
    elif multiplier == 'M':
        return number * 1024 * 1024
    elif multiplier == 'G':
        return number * 1024 * 1024 * 1024
    elif multiplier == 'T':
        return number * 1024 * 1024 * 1024 * 1024
    return number

def mystrip(s):
    if s == None:
        s = ""
    return string.strip(str(s))

def sqlescape(s):
    raise Exception("sqlescape should not be used, use the database layers quoting instead")

def parse_shared_resources(resourcestring):
    result = {}
    if resourcestring:
        # Split the input into a list of records.
        try:
            t = re.findall('[^/]+', resourcestring)
            for entry in t:
                res = string.split(entry, "=", 2)
                result[res[0]] = int(res[1])
        except:
            print "WARNING: Invalid resource string specified %s" % resourcestring
            result = {}
    return result

def check_resources(available, required):
    """
    Determines whether a machine with the resources specified by 'available'
    is suitable for running a job with the resource requirements specified by
    'required'. The function returns 1 if the resources are sufficient and 0
    if they are not.
    """

    # Remove any quotes (XRT-114)
    available = string.strip(available, "'\"")
    required = string.strip(required, "'\"")

    # Check arguments are properly formed.
    if check_input(available) or check_input(required):
        print "Error. malformed inputs to check_resources"
        print available
        print required
        return 0
	
    # Parse the two lists.
    resources = parse_input(available)
    requirements = parse_input(required)
	
    # Check to see if all constraints are satisfied.
    suitable = 1
    for constraint in requirements:
        found = 0
        for entry in resources:
            # Check if this resource is the same as the one in the current
            # constraint.
            if entry[0] == constraint[0]:
                found = 1
                if not check_constraint(constraint, entry):
                    suitable = 0
                break
        # If nothing found then the required resource is not available
        if not found:
            if not check_constraint(constraint, None):
                suitable = 0

    # All constraints satisfied!
    return suitable

# Performs the attribute checking for the FLAGS field mentioned above
# returns 1 if the required attributes are all present, 0 otherwise
# If the required attribute starts with ! then we reject the job if the
# machine has that attribute: (e.g. "FLAG=!e1000")
def check_attributes(available, required):

    suitable = 1

    if required:
        reqlist = string.split(required, ",")
    else:
        reqlist = []
    availlistraw = string.split(available, ",")
    availlist = map(lambda x:x.strip("+"), availlistraw)

    # Check each required attribute
    for req in reqlist:
        try:
            if req[0] == "~":
                # This isn't a required attribute, but it allows it to run on a machine that specifies "+"
              continue
            elif req[0] == '!':
                if req[1:] in availlist:
                    suitable = 0
                    break
            else:
                if not req in availlist or "-%s" % (req) in availlist:
                    suitable = 0
                    break
        except:
            continue
            
    # See if we have mandatory flags (the job must specify these flags
    # to be able to use this machine).
    for avail in availlistraw:
        if avail and avail[0] == "+":
            if avail[1:] not in reqlist and ("~%s" % avail[1:]) not in reqlist:
                suitable = 0
                break

    return suitable

def check_input(commandline):
    """
    Check that an argument conforms to the format specified in XRT-66. Return 0
    if the input is correctly formed, 1 otherwise.
    """	

    if re.match('([A-Za-z0-9_]+(<=|>=|=|<|>)[0-9]+[kMGT]?/)*([A-Za-z0-9_]+(<=|>=|=|>|<)[0-9]+[kMGT]?$)', 
		commandline) == None:
        return 1
    else:
        return 0

def parse_input(commandline):
    """
    Takes a string of resources/requirements as specified in XRT-66 and
    returns a list of lists. Each element of the returned list is a list
    of the form:
    
    [ <resource> , <operator> , <value> ]
    
    Where <value> is normalised, removing any suffix.
    """

    result = []
    
    # Split the input into a list of records.
    t = re.findall('[^/]+', commandline)
    
    # Split each record into [ <resource> , <operator> , <value> ] form.
    for entry in t:
        result.append(re.split('(<=|>=|<|>|=)', entry))
        
    # Normalise the values in the list.
    for entry in result:
        entry[2] = normalise(entry[2])
	
    # Return the normalised list.
    return result

def check_constraint(constraint, entry):
    """
    Check if the resource 'entry' satisfies the 'constraint'. Return 1 if
    the constraint is satisfied and 0 if it is not.
    """

    # Check all the possible predicates.
    if constraint[1] == '<':
        if not entry:
            return 1
        if entry[2] < constraint[2]:
            return 1
    elif constraint[1] == '>':
        if not entry:
            return 0
        if entry[2] > constraint[2]:
            return 1
    elif constraint[1] == '>=':
        if not entry:
            return 0
        if entry[2] >= constraint[2]:
            return 1
    elif constraint[1] == '<=':
        if not entry:
            return 1
        if entry[2] <= constraint[2]:
            return 1
    elif constraint[1] == '=':
        if not entry:
            if constraint[2] == 0:
                return 1
            return 0
        if entry[2] == constraint[2]:
            return 1
    # Constraint wasn't satisifed.
    return 0
	
