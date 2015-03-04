<!doctype html>
<html lang=''>
<head>
   <title>XenRT: Machine</title>

${commonhead | n}
    <script>
$(function() {
    var machine = unescape(self.location.search.substring(1));

    var heading = "<h2>Manage " + machine + "</h2>";

    $( heading ).appendTo("#heading");

    document.title = "XenRT: Machine " + machine;

    function leaseUntilText(ts) {
        if (ts == 1893456000) {
            return "forever"
        }
        else {
            var d = new Date(ts * 1000)
            return "until " + d.toLocaleString()
        }
    }

    function getBMCKVM(data) {
        var bmckvm = false;
        var out = "<div>"
        if (data['params']["BMC_WEB"] == "yes") {
            bmckvm = (data['params']["BMC_KVM"] == "yes")
            if (bmckvm) {
                out += "<h3>Baseboard management (includes KVM access)</h3>"
            }
            else {
                out += "<h3>Baseboard management</h3>"
            }
            out += "<div>URL: <a href=\"https://" + data['params']['BMC_ADDRESS'] + "\" target=\"_blank\">https://" + data['params']['BMC_ADDRESS'] + "</a></div>"
            out += "<div>Username: " + data['params']['IPMI_USERNAME'] + "</div>"
            out += "<div>Password: " + data['params']['IPMI_PASSWORD'] + "</div>"
        }
        if ("KVM_HOST" in data['params']) {
            if (bmckvm) {
                out += "<h3>Physical KVM access (if BMC fails)</h3>"
            }
            else {
                out += "<h3>KVM access</h3>"
            }
            out += "<div>URL: <a href=\"https://" + data['params']['KVM_HOST'] + "\" target=\"_blank\">https://" + data['params']['KVM_HOST'] + "</a></div>"
            out += "<div>Username: " + data['params']['KVM_USER'] + "</div>"
            if ("KVM_PASSWORD" in data['params']) {
                out += "<div>Password: " + data['params']['KVM_PASSWORD'] + "</div>"
            }
            else {
                out += "<div>Password: (blank)</div>"
            }
        }

        out += "</div>"
        return out

    }

    function getMachine(machine) {
        $.ajaxSetup( { "async": false } );
        $.getJSON("/xenrt/api/v2/machine/" + machine)
            .done(function(data) {
                var out = ""
                out += "<h3>Machine info</h3>"
                out += "<div>Status: " + data['status'] + "</div>"
                if (data['description']) {
                    out += "<div>Description: " + data['description'] + "</div>"
                }
                if (data['location']) {
                    out += "<div>Location: " + data['location'] + "</div>"
                }
                out += "<div>Site: " + data['site'] + "</div>"

                $("#machine").empty()
                $(out).appendTo("#machine");
                out = ""
                out += "<h3>Machine lease</h3>"
                if (data['leasecurrentuser']) {
                    out += "<div>"
                    out += "Leased to you " +  leaseUntilText(data['leaseto']);
                    out += " <button id=\"returnbutton\" class=\"ui-state-default ui-corner-all\">Return machine</button>"
                    out += "<h3>Power control</h3>"
                    out += "<div>Operation: <select class=\"ui-state-default ui-corner-all\" id=\"powerop\">"
                    out += "<option value=\"on\">Power on</option>"
                    out += "<option value=\"off\">Power off</option>"
                    out += "<option value=\"reboot\">Power cycle</option>"
                    out += "<option value=\"nmi\">Send NMI</option>"
                    out += "</select>"
                    out += " <button id=\"powerbutton\" class=\"ui-state-default ui-corner-all\">Go</button></div>"
                    out += "<div id=\"output\"></div>"
                    out += "<h3>Serial console</h3>"
                    out += "<div>Unix: <span style=\"font-family:monospace\">ssh -t cons@" + data['ctrladdr'] + " " + machine + "</span> (password <span style=\"font-family:monospace\">console</span>)</div>";
                    out += "<div>Windows: <span style=\"font-family:monospace\">echo " + machine + " > %TEMP%\\xenrt-puttycmd & putty.exe -t cons@" + data['ctrladdr'] + " -pw console -m %TEMP%\\xenrt-puttycmd</span> (requires PuTTY on %PATH%)</div>";
                    out += getBMCKVM(data)
                    out += "</div>"
                }
                else {
                    if (data['leaseuser']) {
                        var d = new Date(data['leaseto'] * 1000)
                        $.ajaxSetup( { "async": false } );

                        var user = data['leaseuser']
                        $.getJSON("/xenrt/api/v2/ad", {"search": data['leaseuser']})
                            .done(function(addata) {
                                if (addata[0]['mail']) {
                                    user = addata[0]['cn'] + " (<a href=\"mailto:" + addata[0]['mail'] + "\">" + addata[0]['mail'] + "</a>)"
                                }
                                else {
                                    user = addata[0]['cn']
                                }
                            });

                        out += "<div>Machine is borrowed by " + user + " " + leaseUntilText(data['leaseto']) + "</div>"
                    }
                    else{
                        if (data['status'] == "running") {
                            out += "<div><p><b>Warning - machine is running job <a href=\"/xenrt/ui/logs?jobs=" + data['jobid'] + "\" target=\"_blank\">" + data['jobid'] + "</a></b></p></div>"
                        }
                        else if (data['status'] == "broken") {
                            out += "<div><p><b>Warning - machine is marked as broken: " + data['params']['BROKEN_INFO'] + "</b></p></div>"
                        }
                        out += "<div>Lease for: "
                        out += "<input type=\"text\" id=\"duration\" class=\"ui-state-default ui-corner-all\">"
                        out += " <select id=\"durationunit\" class=\"ui-state-default ui-corner-all\">"
                        out += "<option value=\"hours\">Hours</option>"
                        out += "<option value=\"days\">Days</option>"
                        out += "<option value=\"forever\">Forever</option>"
                        out += "</select>"
                        out += "<br>Reason: <input type=\"text\" id=\"reason\" class=\"ui-state-default ui-corner-all\">"
                        out += "<br><button id=\"leasebutton\" class=\"ui-state-default ui-corner-all\">Lease</button></div>"
                    }
                }
                $(out).appendTo("#machine");
                setupHandlers()
            });

    }
    
    getMachine(machine)

    function setupHandlers() {

        $( "#powerbutton" ).click(function() {
            $('#powerbutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
            $.ajaxSetup( { "async": false } );
            $.post("/xenrt/api/v2/machine/" + machine + "/power",
                    JSON.stringify({"operation": $("#powerop").val()}),
                    function(response) {
                        out = "<h3>Output</h3><pre>\n"
                        out += response['output']
                        out += "</pre>";
                        $("#output").empty();
                        $(out).appendTo("#output");
                    }, "json");
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
            $('#powerbutton').prop('disabled', false);
        });

        $( "#returnbutton" ).click(function() {
            $('#returnbutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
            
            $.ajaxSetup( { "async": false } );
            $.ajax({
                url: "/xenrt/api/v2/machine/" + machine + "/lease",
                type: "DELETE",
                dataType: "json",
                error: function(jqXHR, textStatus, errorThrown) {
                    alert("Error returning machine: " + textStatus + " " + errorThrown)
                }
            });

            getMachine(machine);
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
        });

        $( "#leasebutton" ).click(function() {

            unit = $("#durationunit").val()
            dur = $("#duration").val()

            var duration = null;

            if (unit == "forever") {
                duration = 0;
            }
            else if (unit == "days") {
                duration = parseInt(dur) * 24;
            }
            else if (unit == "hours") {
                duration = parseInt(dur)
            }

            $('#leasebutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
           
            $.ajaxSetup( { "async": false } );
            $.ajax({
                url: "/xenrt/api/v2/machine/" + machine + "/lease",
                data: JSON.stringify({"duration": duration, "reason": $("#reason").val()}),
                type: "POST",
                dataType: "json",
                error: function(jqXHR, textStatus, errorThrown) {
                    alert("Error leasing machine: " + textStatus + " " + errorThrown)
                }
            });
            
            getMachine(machine);
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
        });
    }
});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<div id="heading"></div>
<div id="machine"></div>

</div>
</body>
</html>
