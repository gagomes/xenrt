<!doctype html>
<html lang=''>
<head>
${commonhead | n}

  <script>
$(function() {

    function getUrlParameter(param)
    {
        var sPageURL = window.location.search.substring(1);
        var sURLVariables = sPageURL.split('&');
        for (var i = 0; i < sURLVariables.length; i++) 
        {
            var parameterName = sURLVariables[i].split('=');
            if (parameterName[0] == param) 
            {
                return parameterName[1];
            }
        }
        return ""
    }         

    function getJob(jobid) {
        var jobget = "/xenrt/api/v2/job/" + jobid
        $.getJSON (jobget, {"logitems": "true"})
            .done(function(data) {
                var out = jobHTML(data)
                $( out ).appendTo( "#logs" );
                $("#togglejobdetail" + jobid).click(function(event) {
                    objid = "#" + event.target.id.replace("toggle", '');
                    $( objid ).toggle("blind", {}, 500);
                });
                var formdetail = getUrlParameter("detailid");
                for (var key in data['results']) {
                    $("#toggletestdetail" + key).click(function(event) {
                        objid = "#" + event.target.id.replace("toggle", '');
                        $( objid ).toggle("blind", {}, 500);
                    });
                    if (formdetail == key) {
                        $( "#testdetail" + key ).show();
                    }
                }
            });
    }

    function jobHTML(data) {
        var out = "<div id=\"job" + data['id'] + "\" class=\"ui-widget-content ui-corner-all\">";
        out += "<div id=\"jobheader" + data['id'] + "\" class=\"ui-widget-header ui-corner-all\">";
        out += "<h3>"
        if (data['result'])
        {
            out += "<span style=\"background-color: " + resultToColor(data['result']) + "\">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span> ";
        }
        out += "Job " + data['id'] + " (" + data['status'] + ")</h3>";
        out += "<p><a href=\"#\" id=\"togglejobdetail" + data['id'] + "\">Toggle details</a>";
        if (data['params']['UPLOADED'] == "yes") {
            out += " | <a href=\"http://" + data['params']['LOG_SERVER'] + "/xenrt/logs/job/" + data['id'] + "/browse\" target=\"_blank\">Show Logs</a>";
        }
        out += " | User: " + data['user'];
        if (data['result'])
        {
            out += " | Result: " + data['result'];
        }
        if (data['machines'].length > 0) {
            if (data['machines'].length == 1) { 
                out += " | Ran on machine: "+  data['machines'][0];
            }
            else {
                out += " | Ran on machines: "+  data['machines'].join(", ");
            }
        }
        if ("PREPARE_FAILED" in data['params']) {
            out += " | Failure message: " + data['params']['PREPARE_FAILED'];
        }
        out += "</p>";
        out += "</div>";
        out += "<div id=\"jobdetail" + data['id'] + "\" style=\"display:none;\" class=\"ui-widget-content ui-corner-all\">";
        out += jobDetailsHTML(data);
        out += "</div>";
        out += "<div id=\"jobresults" + data['id'] + "\">";
        out += resultsHTML(data);
        out += "</div>";
        out += "</div>";
        return out
    }

    function jobDetailsHTML(data) {
        var out = "<table style=\"width: 100%\">";
        var i = 0;
        for (var key in data['params']) {
            if (i % 4 == 0) {
                out += "<tr>";
            }
            out += "<td style=\"word-break: break-all; width: 25%\">" + key + ": " + data['params'][key] + "</td>";
            i++;
            if (i % 4 == 0) {
                out += "</tr>";
            }
        }

        if (i % 4 > 0) {
            for (j=0; j < (4-(i%4)); j++) {
                out += "<td></td><td></td>"; 
            }
            out += "</tr>";
        }
        out += "</table>";
        return out
        
    }

    function resultToColor(result) {
        colors = {"pass": "green",
                   "fail": "orange",
                   "vmcrash": "red",
                   "xencrash": "black",
                   "started":    "#ccff99",
                   "running":    "#ccff99",
                   "skipped":    "#FFFFFF",
                   "partial":    "#96FF00",
                   "error":      "#667FFF",
                   "other":      "#CCCCCC",
                   "paused":     "#FF80FF",
                   "continuing": "#ccff99",
                   "pass/w":     "#F5FF80",
                   "fail/w":     "orange",
                   "vmcrash/w":  "red",
                   "xencrash/w": "black",
                   "started/w":  "#ccff99",
                   "skipped/w":  "#FFFFFF",
                   "partial/w":  "#96FF00",
                   "error/w":    "#667FFF",
                   "other/w":    "#CCCCCC",
                   "paused/w":   "#FF80FF",
                   "continuing/w": "#ccff99",
                   "OK":    "green",
                   "ERROR": "red",
                   }
        return colors[result]

    }

    function resultsHTML(data) {
        var out = ""
        for (var key in data['results']) {
            var test = data['results'][key];
            out += "<div id=\"test" + key + "\" class=\"ui-widget-content ui-corner-all\">";
            out += "<span style=\"background-color: " + resultToColor(test['result']) + "\">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span> ";
            out += "<span style=\"font-weight:bold\">";
            out += test['phase'] + "/" + test['test'] + ": " + test['result'];
            out += "</span>";
            out += " | <a href=\"#\" id=\"toggletestdetail" + key + "\">Toggle details</a>";
            if (test['logUploaded']) {
                out += " | <a href=\"http://" + data['params']['LOG_SERVER'] + "/xenrt/logs/test/" + key + "/browse\" target=\"_blank\">Show Logs</a>";
            }
            var failure = getFailureMessage(test);
            if (failure) {
                out += " | Failure message: " + failure;
            }
            out += "<div id=\"testdetail" + key + "\" style=\"display:none;\">";
            out += testDetailHTML(test);
            out += "</div>";
            out += "</div>";
        }
        return out
    }

    function getFailureMessage(test) {
        for (var i in test['log']) {
            var item = test['log'][i];
            if (item['type'] == "reason") {
                return item['log'];
            }
        }
        return null;
    }

    function testDetailHTML(test) {
        var out = ""
        for (var i in test['log']) {
            var item = test['log'][i]
            out += "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;";
            if (item['type'] == "result") {
                out += "<span style=\"background-color: " + resultToColor(item['log']) + "\">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span> ";
            }
            else {
                out += "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; "
            }
            var d = new Date(item['ts'] * 1000);
            out += d.toLocaleString() + " " + item['type'] + " " + item['log']
            out += "<br />"
        }
        return out
    }

    function getJobForDetailId(test) {
        var testget = "/xenrt/api/v2/test/" + test
        $.getJSON(testget, {})
            .done(function(data) {
                $( "#jobs" ).val(data['jobId']);
                $("#displayjobbutton").click();
            });
    }

    $( "#displayjobbutton" ).click(function() {
        $('#displayjobbutton').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        $( "#logs" ).empty();
        $.ajaxSetup( { "async": false } );
        var jobs = $( "#jobs" ).val().split(",")
        for (var j in jobs) {
            job = jobs[j]
            if (jobs.indexOf(job) != -1 && jobs.indexOf(job) < j) {
                continue
            }
            getJob(job)
        }
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#displayjobbutton').prop('disabled', false);
    });

    $("#jobs").keyup(function(event){
        if(event.keyCode == 13){
            $("#displayjobbutton").click();
        }
    });

    $( "#jobs" ).val(getUrlParameter("jobs"));
    var detail = getUrlParameter("detailid");
    if (detail != "" && $( "#jobs" ).val() == "") {
        getJobForDetailId(detail);
    }
    else if ($( "#jobs" ).val() != "") {
        $("#displayjobbutton").click();
    }

});
</script>

</head>
<body>
${commonbody | n}

<div id="mainbody">

<h2>Browse XenRT Logs</h2>
<p>Jobs: <input id="jobs" type="text" width="12">
<button id="displayjobbutton" class="ui-state-default ui-corner-all">Display</button></p>
<div id="logs"></div>

</div>
</body>
<html>
