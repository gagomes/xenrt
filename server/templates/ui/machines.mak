<!doctype html>
<html lang=''>
<head>
   <title>XenRT: Machines</title>

${commonhead | n}
    <script>
$(function() {

    var curRequest = null;

    function search(searchtext, user, idle) {
        $('#searchbutton').prop('disabled', true);
        $('#mybutton').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        if (curRequest) {
            curRequest.abort();
        }
        var params = null;
        if (user) {
            limit = "0"
            params = {"user": "${'${user}'}", "limit" : "0"}
        }
        else {
            params = {"search": searchtext, "limit": "100"}
            if (idle) {
                params['status'] = "idle"
            }
        }
        $.ajaxSetup( { "async": false } );
        var machinesearch = "/xenrt/api/v2/machines"
        curRequest = $.getJSON(machinesearch, params)
            .done(function(data) {
                curRequest = null;
                var out = searchHTML(data)
                $("#results").empty();
                $( out ).appendTo("#results");
            });
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#searchbutton').prop('disabled', false);
        $('#mybutton').prop('disabled', false);
    }

    function searchHTML(data) {
        var out = ""
        for (var key in data) {
            out += "<div class=\"ui-widget-content ui-corner-all\">";

            out += key;
            if (data[key]['description']) {
                out += " - " + data[key]['description']
            }
            if (data[key]['location']) {
                out += " (" + data[key]['location'] + " - " + data[key]['site'] + ")"
            }
            else {
                out += " (" + data[key]['site'] + ")"
            }

            if (data[key]['leasecurrentuser']) {
                out += " - Leased to you"
            }
            else if (data[key]['leaseuser']) {
                out += " - leased to " + data[key]['leaseuser']
            }
            else if (data[key]['status'] == "running") {
                out += " - running job " + data[key]['jobid']
            }
            else {
                out += " - " + data[key]['status']
            }

            out += " - <a href=\"machine?" + escape(key) + "\">Manage</a>";

            out += "</div>";
        }
        return out
    }

    $( "#searchbutton" ).click(function() {
        var machinesearch = $( "#searchbox" ).val()
        search(machinesearch, false, $("#idlebox").is(":checked"));
    });

    $( "#mybutton").click(function() {
        search(null, true, false); 
    });

    $("#searchbox").keyup(function(event){
        if(event.keyCode == 13){
            $("#searchbutton").click();
        }
        else {
            // These lines allow real time searching, but also put a greater load on the server. Decide later whether we can enable this
            //$.ajaxSetup( { "async": true } );
            //var machinesearch = $( "#searchbox" ).val()
            //search(machinesearch);
        }
    });
        
    search(null, true, false);
});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<h2>Find machine</h2>
<p><button id="mybutton" class="ui-state-default ui-corner-all">Get my machines</button></p>
<p><input id="searchbox" type="text" class="ui-state-default ui-corner-all">
<input id="idlebox" type="checkbox" class="ui-state-default ui-corner-all"> Only find idle machines
<button id="searchbutton" class="ui-state-default ui-corner-all">Search</button></p>
<div id="results"></div>
</p>
</div>
</body>
</html>
