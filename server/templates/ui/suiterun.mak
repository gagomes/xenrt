<!doctype html>
<html lang=''>
<head>
    <title>XenRT: Start Suite</title>

${commonhead | n}
    <script>
$(function() {

    var statusInterval;
    var token;

    $( "#start" ).click(function() {
        $('#start').prop('disabled', true);
        $.ajaxSetup( { "async": false } );
        var submitdata = {
            "suite": $("#suite").val(),
            "branch": $("#branch").val(),
            "version": $("#version").val(),
            "rerun": $("#rerun").is(":checked"),
            "rerunall": $("#rerunall").is(":checked"),
            "rerunifneeded": $("#rerunifneeded").is(":checked"),
            "devrun": $("#devrun").is(":checked")
        };
        
        if ($("#seqs").val() != "") {
            submitdata['seqs'] = $("#seqs").val().split(",");
        }
        if ($("#sku").val() != "") {
            submitdata['sku'] = $("#sku").val();
        }

        if ($("#params").val() != "") {
            submitdata['params'] = {}
            var properties = $("#params").val().split('\n');
            properties.forEach(function(property) {
                var tup = property.split('=');
                    submitdata['params'][tup[0]] = tup[1];
                });
        }

        if ($("#delay").val() != "") {
            submitdata['delay'] = parseInt($("#delay").val());
        }

        if ($("#xenrtbranch").val() != "") {
            submitdata['xenrtbranch'] = $("#xenrtbranch").val();
        }

        $.post("/xenrt/api/v2/suiterun/start",
           JSON.stringify(submitdata),
           function(response) {
                token = response['token']
                $.getJSON("/xenrt/api/v2/suiterun/start/" + token,
                    function(data) {
                        var out = "<iframe id=\"logframe\" src=\"/xenrt/static/logtail/logtail.html?" + data['console'] + "\" scrolling=\"auto\" width=\"100%\" height=\"400\">"
                        $("#log").empty();
                        $(out).appendTo("#log")
                        updateStatusText(data);
                        statusInterval = setInterval(function () {updateStatus()}, 1000)
                    }
                );
            }, "json");
        $('#start').prop('disabled', false);
    }); 

    function updateStatus() {
        $.getJSON("/xenrt/api/v2/suiterun/start/" + token,
            function(data) {
                updateStatusText(data);
                if (data['status'] != "running") {
                    clearInterval(statusInterval);
                    $("#logframe").prop("src", data['console']);
                }
            }
        );

    }

    function updateStatusText(data) {
        var text = "<h2>Status: " + data['status'] + "</h2>";
        $("#status").empty();
        $(text).appendTo("#status");
    }

});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">

<h2>Start Suite</h2>
<p>
<table border=0>
<tr><td>Suite: </td><td><input type="text" id="suite"> (e.g. "TC-12720")</td></tr>
<tr><td>Branch: </td><td><input type="text" id="branch"> (e.g. "trunk")</td></tr>
<tr><td>Version: </td><td><input type="text" id="version"> (e.g. "6.2.0-12345")</td></tr>
<tr><td>Seqs: </td><td><input type="text" id="seqs"> (comma seperated to run a subset)</td></tr>
<tr><td>SKU: </td><td><input type="text" id="sku"> (e.g. "bridge")</td></tr>
<tr><td>XenRT Branch: </td><td><input type="text" id="xenrtbranch"> (leave blank for default)</td></tr>
<tr><td>Delay: </td><td><input type="text" id="delay"> (in seconds; leave blank for no delay)</td></tr>
<tr><td>Params: </td><td><textarea id="params"></textarea></td></tr>
<tr><td>Rerun a subset of sequences: </td><td><input type="checkbox" id="rerun"></td></tr>
<tr><td>Rerun all: </td><td><input type="checkbox" id="rerunall"></td></tr>
<tr><td>Rerun if needed: </td><td><input type="checkbox" id="rerunifneeded"></td></tr>
<tr><td>Dev Run: </td><td><input type="checkbox" id="devrun"></td></tr>
</table>
<button id="start" class="ui-state-default ui-corner-all">Start Suite</button>
<div id="status"></div>
<div id="log"></div>
</p>


</div>
</body>
</html>
