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

    function getMachine(machine) {
        $.getJSON("/xenrt/api/v2/machine/" + machine)
            .done(function(data) {
                var out = ""
                out += "<h3>Serial console</h3>"
                out += "<div>Unix: <span style=\"font-family:monospace\">ssh cons@" + data['ctrladdr'] + " " + machine + "</span> (password <span style=\"font-family:monospace\">console</span>)</div>";
                out += "<div>Windows: <span style=\"font-family:monospace\">echo " + machine + " > %TEMP%\\xenrt-puttycmd & putty.exe -t cons@" + data['ctrladdr'] + " -pw console -m %TEMP%\\xenrt-puttycmd</span></div>";
                $("#access").empty()
                $(out).appendTo("#access");
            });

    }
    
    getMachine(machine)

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

});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<div id="heading"></div>

<p>Power control: <select class="ui-state-default ui-corner-all" id="powerop">
    <option value="on">Power on</option>
    <option value="off">Power off</option>
    <option value="reboot">Power cycle</option>
    <option value="nmi">Send NMI</option>
</select>
<button id="powerbutton">Go</button>

<div id="output"></div>

<div id="access"></div>

</p>

</div>
</body>
</html>
