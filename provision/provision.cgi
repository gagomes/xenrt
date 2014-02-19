#!/usr/bin/python

import os,re,cgi,cgitb,config,Cookie

cgitb.enable()

def getMachinesAndPools():
    poolstoexclude = ["EX", "EXPV", "HCT", "BUILD", "OEMNV", "USBDELL"]
    mlist = []
    plist = []
    flist = []
    for l in os.popen("xenrt mlist2 -q -p").readlines():
        m = re.match("(.+?)\s+.+?\s+.+?\s+.+?\s+(.+?)\s+(.*?)$",l)
        if m:
            p = m.group(2)
            if not p in poolstoexclude:
                mlist.append(m.group(1))
            if not p in plist and not p in poolstoexclude and not re.match(".*x$", p):
                plist.append(p)
            flags = m.group(3).split(",")
            for f in flags:
                f = f.lstrip("-")
                f = f.lstrip("+")
                if not f in flist:
                    flist.append(f)
                    flist.append("!%s" % f)
    return (mlist,plist,flist)


print "Content-type:text/html\n"

if os.environ.has_key("HTTP_COOKIE"):
    cookie = Cookie.SimpleCookie(os.environ["HTTP_COOKIE"])
else:
    cookie = {}

if cookie.has_key("user"):
    user = cookie["user"].value
else:
    user = ""
if cookie.has_key("email"):
    email = cookie["email"].value
else:
    email = ""

(machines,pools,flags) = getMachinesAndPools()

vmlist = ""
count = 0
for i in config.guests.keys():
    for g in config.guests[i]:
        vmlist += "    <div class=\"floating vm %s\" id=\"vm%d\">%s</div>\n" % (i,count,g)
        count += 1

srlist = ""
count = 0
for s in config.srs:
    srlist += "    <div class=\"floating sr\" id=\"sr%d\">%s</div>\n" % (count,s)
    count += 1

machinestring = str(machines)
poolstring = str(pools)
flagstring = str(flags)

releasestring = ""
branchstring = ""

for r in config.releases.keys():
    (hosttype,path,version) = config.releases[r]
    releasestring += "<option value=\"%s,%s,%s\">%s</option>\n" % (hosttype,path,version,r)

for b in config.branches.keys():
    (hosttype,version) = config.branches[b]
    branchstring += "<option value=\"%s,%s,%s\">%s</option>\n" % (hosttype,b,version,b)

print """<html>
<head>
    <script src="http://ajax.googleapis.com/ajax/libs/jquery/1.6.2/jquery.min.js" type="text/javascript"></script>
    <script src="http://ajax.googleapis.com/ajax/libs/jqueryui/1.8.16/jquery-ui.min.js" type="text/javascript"></script>
    <script src="http://jquery-ui.googlecode.com/svn/tags/latest/external/jquery.bgiframe-2.1.2.js" type="text/javascript"></script>
    <script src="http://ajax.googleapis.com/ajax/libs/jqueryui/1.8.16/i18n/jquery-ui-i18n.min.js" type="text/javascript"></script>
    <style>
        body {
            font-family:Sans-Serif;
        }
        #left {float:left}
        #job {margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 260px;}
        #hostpoolsender {float:left; margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 450px; }
        #poolsender {float:left; margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 230px; }
        #hostsender {float:left; margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 170px; }
        #vmsender { margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 450px; }
        #srsender { margin: 0; padding: 0; margin-right: 10px; background: #eee; padding: 5px; width: 450px; }
        #bin { background-image: url(bin.jpg); width:150px; height: 120px; float:right }
        #senders {float:right; background: #eee}
        .vms { margin: 0; padding: 0; margin-right: 10px; background: #F79F81; padding: 5px; width: 160px; }
        .hosts { margin: 0; padding: 0; margin-right: 10px; background: #F3F781; padding: 5px; width: 200px; }
        .srs { margin: 0; padding: 0; margin-right: 10px; background: #A9BCF5; padding: 5px; width: 200px; }
        .pools { margin: 0; padding: 0; margin-right: 10px; background: #D0FA58; padding: 5px; width: 240px; }
        .vm { margin: 3px 3px 3px 3px; padding: 1px; width: 140px; border: 1px solid; cursor:pointer}
        .sr { margin: 3px 3px 3px 3px; padding: 1px; width: 140px; border: 1px solid; cursor:pointer}
        .floating {float: left}
        .pool { margin: 3px 3px 3px 3px; padding: 1px; width: 220px; border: 1px solid; cursor:pointer}
        .host { margin: 3px 3px 3px 3px; padding: 1px; width: 180px; border: 1px solid; cursor:pointer}
        .ui-autocomplete { max-height: 100px; overflow-y: auto; overflow-x: hidden; padding-right: 20px; background:#ddd; width:150px; cursor:pointer; cursor:hand}
        #overlay { position: fixed; left: 0px; top: 0px; width: 100%%; height: 100%%; opacity: .6; filter: alpha(opacity=60); z-index: 1000; background-color: #000000; display:none}
        #loading { position: fixed; left: 50%%; top: 100px; width: 32px; height: 32px; padding: 0px; border: 2px solid Silver; background: url(ajax-loader.gif); z-index: 2000; display:none}

 
    </style>
    <script>

    var hostcount;
    var srcount;
    var poolcount;
    var vmcount;

    var availablemachines = %s;
    var availablepools = %s;
    var availableflags = %s;

    function addReceiversToHost(host)
    {
        host.append("<div class=\\"vms\\">VMs:</div>")
        $(".vms").sortable({connectWith: ".bin"}).disableSelection();
        $(".vms").bind("sortreceive", function(event,ui) {
            ui.item.context.classList.remove("floating")
        });
    }

    function addReceiversToPool(pool)
    {
        pool.append("<div class=\\"hosts\\">Hosts:</div>")
        $(".hosts").sortable({connectWith: ".bin"}).disableSelection();
        pool.append("<div class=\\"srs\\">SRs:</div>")
        $(".srs").sortable({connectWith: ".bin"}).disableSelection();
        $(".srs").bind("sortreceive", function(event,ui) {
            ui.item.context.classList.remove("floating")
        });
    }

    $(function() {
        $(".hosts").sortable({connectWith: ".bin"}).disableSelection();
        $(".pools").sortable({connectWith: ".bin"}).disableSelection();
        $("#bin").sortable().disableSelection();
        $("#poolsender").sortable({connectWith: ".pools"}).disableSelection();
        $("#hostsender").sortable({connectWith: ".hosts"}).disableSelection();
        $("#vmsender").sortable({connectWith: ".vms"}).disableSelection();
        $("#srsender").sortable({connectWith: ".srs"}).disableSelection();
        $("#hostsender").bind("sortremove", function(event, ui) {
                ui.item.clone().prependTo("#hostsender");
                addReceiversToHost(ui.item)
        });
        $("#poolsender").bind("sortremove", function(event, ui) {
                ui.item.clone().prependTo("#poolsender");
                addReceiversToPool(ui.item)
        });
        $("#vmsender").bind("sortremove", function(event, ui) {
            if (ui.item.context.id == "vm0")
            {
                ui.item.clone().insertBefore("#vm1")
            }
            else
            {
                previtem = "#vm" + (parseInt(ui.item.context.id.match(/vm(\d+)/)[1]) - 1)
                ui.item.clone().insertAfter(previtem)
            }
            ui.item.context.id = ""
        });
        $("#srsender").bind("sortremove", function(event, ui) {
            if (ui.item.context.id == "sr0")
            {
                ui.item.clone().insertBefore("#sr1")
            }
            else
            {
                previtem = "#sr" + (parseInt(ui.item.context.id.match(/sr(\d+)/)[1]) - 1)
                ui.item.clone().insertAfter(previtem)
            }
            ui.item.context.id = ""
        });
        $("#bin").bind("sortreceive", function(event, ui) {
                ui.item.remove()
        });
        $( "#flags" )
            // don't navigate away from the field on tab when selecting an item
            .bind( "keydown", function( event ) {
                if ( event.keyCode === $.ui.keyCode.TAB &&
                        $( this ).data( "autocomplete" ).menu.active ) {
                    event.preventDefault();
                }
            })
            .autocomplete({
                minLength: 0,
                source: function( request, response ) {
                    // delegate back to autocomplete, but extract the last term
                    response( $.ui.autocomplete.filter(
                        availableflags, extractLast( request.term ) ) );
                },
                focus: function() {
                    // prevent value inserted on focus
                    return false;
                },
                select: function( event, ui ) {
                    var terms = split( this.value );
                    // remove the current input
                    terms.pop();
                    // add the selected item
                    terms.push( ui.item.value );
                    // add placeholder to get the comma-and-space at the end
                    this.value = terms.join( "," );
                    return false;
                }
            });
        $( "#machinechooser" )
            // don't navigate away from the field on tab when selecting an item
            .bind( "keydown", function( event ) {
                if ( event.keyCode === $.ui.keyCode.TAB &&
                        $( this ).data( "autocomplete" ).menu.active ) {
                    event.preventDefault();
                }
            })
            .autocomplete({
                minLength: 0,
                source: function( request, response ) {
                    // delegate back to autocomplete, but extract the last term
                    response( $.ui.autocomplete.filter(
                        availablemachines, extractLast( request.term ) ) );
                },
                focus: function() {
                    // prevent value inserted on focus
                    return false;
                },
                select: function( event, ui ) {
                    var terms = split( this.value );
                    // remove the current input
                    terms.pop();
                    // add the selected item
                    terms.push( ui.item.value );
                    // add placeholder to get the comma-and-space at the end
                    this.value = terms.join( "," );
                    return false;
                }
            });
        $( "#poolchooser" )
            // don't navigate away from the field on tab when selecting an item
            .bind( "keydown", function( event ) {
                if ( event.keyCode === $.ui.keyCode.TAB &&
                        $( this ).data( "autocomplete" ).menu.active ) {
                    event.preventDefault();
                }
            })
            .autocomplete({
                minLength: 0,
                source: function( request, response ) {
                    // delegate back to autocomplete, but extract the last term
                    response( $.ui.autocomplete.filter(
                        availablepools, extractLast( request.term ) ) );
                },
                focus: function() {
                    // prevent value inserted on focus
                    return false;
                },
                select: function( event, ui ) {
                    var terms = split( this.value );
                    // remove the current input
                    terms.pop();
                    // add the selected item
                    terms.push( ui.item.value );
                    // add placeholder to get the comma-and-space at the end
                    terms.push( "" );
                    this.value = terms.join( "," );
                    return false;
                }
            });
    });
    function split( val ) {
        return val.split( /,\\s*/ );
    }
    function extractLast( term ) {
        return split( term ).pop();
    }

    function serializeAll() {
        buildval = $("#build").val()
        if (buildval=="custom")
        {
            branch = $("#branch").val().split(/,\\s*/ )
            path = "%s/" + branch[1] + "/" + $("#buildno").val()
            xrtversion = branch[0]
            version = branch[2] + "-" + $("#buildno").val()
            if ($("#buildno").val() == "")
            {
                alert("Must specify a build number");
                return;
            }
        }
        else
        {
            ll = buildval.split(/,\\s*/ )
            path = ll[1]
            xrtversion = ll[0]
            version = ll[2]
        }

        seq = serializeSeq(xrtversion)

        if (hostcount==0)
        {
            alert("Job must include at least one host");
            return;
        }
        if ($("#user").val() == "")
        {
            alert("Must specify a user name");
            return;
        }
        if ($("#email").val() == "")
        {
            alert("Must specify an email address");
            return;
        }

        cmdline = "submit -o x86-32 -v xenserver -r " + version + " --inputs " + path + " -D OPTION_KEEP_ISCSI=yes -D OPTION_KEEP_NFS=yes -D OPTION_KEEP_CVSM=yes -D ENABLE_CITRIXCERT=yes -D JOBPRIO=1 -D MACHINES_REQUIRED=" + hostcount + " --email " + $("#email").val() + " -D USERID=" + $("#user").val()
        
        if ($("#machinechooser").val() != "")
        {
            cmdline += " -m " + $("#machinechooser").val()
        }
        else
        {
            if ($("#poolchooser").val() == "")
            {
                alert("Must specify either Machines or Pools");
                return;
            }
            cmdline += " --pool \\"" + $("#poolchooser").val() + "\\""
            if ($("#res").val() != "")
            {
                cmdline += " --res \\"" + $("#res").val() + "\\""
            }
            if ($("#flags").val() != "")
            {
                cmdline += " -F \\"" + $("#flags").val() + "\\""
            }
        }

        if ($("#hold").is(":checked"))
        {
            cmdline += " --hold 1440"
        }
        
        if ($("#ext").is(":checked"))
        {
            cmdline += " -D INSTALL_SR_TYPE=ext"
        }

        $("#overlay").show()
        $("#loading").show();

        $.post("submit.cgi", {"seq": seq, "cmd": cmdline, "user": $("#user").val(), "email": $("#email").val()}, function(data) {
            alert(data);
            $("#overlay").hide()
            $("#loading").hide();
        }, "html");



    }

    function serializeSeq(version) {
        xml = "<xenrt>\\n  <variables>\\n    <PRODUCT_VERSION>" + version + "</PRODUCT_VERSION>\\n    <PREPARE_WORKERS>4</PREPARE_WORKERS>\\n  </variables>\\n  <prepare>\\n"
        hostcount = 0;
        srcount = 0;
        poolcount = 0;
        vmcount = 0;
        $("#hosts").children("div").each(function(idx,elm) {
            xml += serializeHost(elm)
        });
        $("#pools").children("div").each(function(idx,elm) {
            xml += serializePool(elm)
        });
        xml += "  </prepare>\\n</xenrt>";
        return xml;
    }

    function serializePool(pool)
    {
        xml = "    <pool id=\\"" + poolcount++ + "\\">\\n";
        for (var i=0; i < pool.children.length; i++) {
            if (pool.children[i].classList.contains("hosts")) {
                for (var j=0; j < pool.children[i].children.length; j++) {
                    xml += serializeHost(pool.children[i].children[j])
                }
            }
            if (pool.children[i].classList.contains("srs")) {
                for (var j=0; j < pool.children[i].children.length; j++) {
                    xml += serializeSR(pool.children[i].children[j], j==0)
                }
            }
        }
        xml += "    </pool>\\n"
        return xml
    }

    function serializeHost(host)
    {
        xml = "      <host id=\\"" + hostcount++ + "\\">\\n";
        for (var i=0; i < host.children.length; i++)
        {
            if (host.children[i].classList.contains("vms")) {
                xml += serializeVMs(host.children[i]);
            }
        }
        xml += "      </host>\\n";
        return xml
    }
    
    function serializeSR(sr,isdefault)
    {
        type = sr.innerHTML
        xml = "      <storage name=\\"sr" + srcount++ + "_" + type + "\\" type=\\"" + type + "\\""
        if (isdefault)
        {
            xml += " default=\\"true\\""
        }
        if (type == "lvmoiscsi")
        {
            xml += " options=\\"ietvm\\""
        }
        xml += " />\\n"
        return xml
    }

    function serializeVMs(vms)
    {
        xml = ""
        for (var i=0; i < vms.children.length; i++)
        {
            xml += serializeVM(vms.children[i]);
        }
        return xml
    }

    function serializeVM(vm)
    {
        distro = vm.innerHTML
        xml = "        <vm name=\\"vm" + vmcount++ + "-" + distro + "\\">\\n          <distro>" + distro + "</distro>\\n          <network device=\\"0\\" />\\n"
        if (vm.classList.contains("windows"))
        {
            xml += "          <postinstall action=\\"installDrivers\\"/>\\n"
        }
        xml += "        </vm>\\n"
        return xml
    }

    </script>
</head>
<body>

<div id="overlay"></div>
<div id="loading"></div>

<h1>Provision machines with XenRT</h1>

<div id="senders">

Drag items from here to the job topology panel on the left

<div id="hostpoolsenders">
    <div id="poolsender" class="poolsender">
        <div class="pool">Pool</div>
    </div>
    <div id="hostsender" class="hostsender">
        <div class="host">Host</div>
    </div>
    <div style="clear:both"></div>
</div>
<div id="srsender" class="srsender">
Available Pool SRs
    <div style="clear:both"></div>
%s    <div style="clear:both"></div>
</div>
<div id="vmsender" class="vmsender">
Available VMs
    <div style="clear:both"></div>
%s    <div style="clear:both"></div>
</div>


</div>

<div id="bin" class="bin">
</div>
<div id="job" class="job">
    <h2>Job host topology</h2>
    <div class="hosts" id="hosts">Standalone Hosts</div>
    <div class="pools" id="pools">Pools</div>
</div>

<h2>Job configuration</h2>

<form>
<table border = 0>
<tr><td>Username:</td><td><input type="text" id="user" value="%s" /></td><td></td></tr>
<tr><td>Email address:</td><td><input type="text" id="email" value="%s" /></td><td></td></tr>
<tr><td>Machine(s):</td><td><div class="ui-widget"><input type="text" id="machinechooser" /></div></td><td><small>Leave blank if specifying a pool</small></td></tr>
<tr><td>Pool(s):</td><td><div class="ui-widget"><input type="text" id="poolchooser" value="VMX,SVM" /></div></td><td><small>Will not be used if machine(s) specified</small></td></tr>
<tr><td>Resources required:</td><td><input type="text" id="res" value ="cores>=4/memory>=8G" /></td><td><small>Will not be used if machine(s) specified</small></td></tr>
<tr><td>XenRT Properties string:</td><td><input type="text" id="flags" /></td><td><small>Will not be used if machine(s) specified</small></td></tr>
<tr><td>Released Build</td><td><select id="build"><option value="custom" selected>Custom branch/build</option>%s</select></td><td></td></tr>
<tr><td>Branch</td><td><select id="branch">%s</select></td><td><small>Will be ignored if released build specified</small></td></tr>
<tr><td>Build number</td><td><input type="text" id="buildno" /></td><td><small>Will be ignored if released build specified</small></td></tr>
<tr><td>Borrow machine(s) for 24 hours after completion</td><td><input type="checkbox" id="hold" /></td><td></td></tr>
<tr><td>Use ext local storage</td><td><input type="checkbox" id="ext" /></td><td></td></tr>
</table>

<input type="button" onclick="javascript:serializeAll()" value="Submit Job" />

</form>
</body>
</html>
""" % (machinestring,poolstring,flagstring,config.basedir, srlist, vmlist, user, email, releasestring, branchstring)

