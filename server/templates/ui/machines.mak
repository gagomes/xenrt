<!doctype html>
<html lang=''>
<head>
   <title>XenRT: Machines</title>

${commonhead | n}
    <script>
$(function() {

    var curRequest = null;

    function search(searchtext) {
        if (curRequest) {
            curRequest.abort();
        }
        var machinesearch = "/xenrt/api/v2/machines"
        curRequest = $.getJSON(machinesearch, {"search": searchtext, "limit": "25"})
            .done(function(data) {
                curRequest = null;
                var out = searchHTML(data)
                $("#results").empty();
                $( out ).appendTo("#results");
            });
    }

    function searchHTML(data) {
        var out = ""
        for (var key in data) {
            out += "<div class=\"ui-widget-content ui-corner-all\">";

            out += key;
            out += ": <a href=\"/xenrt/ui/machine?" + escape(key) + "\">Manage</a>";

            out += "</div>";
        }
        return out
    }

    $( "#searchbutton" ).click(function() {
        $('#searchbutton').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        $.ajaxSetup( { "async": false } );
        var machinesearch = $( "#searchbox" ).val()
        search(machinesearch);
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#searchbutton').prop('disabled', false);
    });

    $("#searchbox").keyup(function(event){
        if(event.keyCode == 13){
            $("#searchbutton").click();
        }
        else {
            $.ajaxSetup( { "async": true } );
            var machinesearch = $( "#searchbox" ).val()
            search(machinesearch);
        }
    });

});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<h2>Find machine</h2>
<p>
<input id="searchbox" type="text" class="ui-state-default ui-corner-all">
<button id="searchbutton" class="ui-state-default ui-corner-all">Search</button></p>
<div id="results"></div>
</p>
</div>
</body>
</html>
