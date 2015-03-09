<!doctype html>
<html lang=''>
<head>
    <title>XenRT: ACL Management</title>

${commonhead | n}
    <script>
$(function() {
    $( document ).ready(function () {
        populateAcls();

        // Are we creating a new ACL or editing an existing one
        var id = unescape(self.location.search.substring(1));
        if (id == "new")
        {
            // Create a new one
            $ ( "#aclname" ).val("New ACL");
        } else if ($.isNumeric(id))
        {
            // Editing an existing one
            var aclurl = "/xenrt/api/v2/acl/" + id
            $.getJSON(aclurl).done(function(data) {
                $( "#acldata" ).data("acl", data);
                $( "#aclname" ).val(data.name);
                if (data.parent != null)
                    $( "#parent" ).val(data.parent);
                // TODO: Ensure we process this in sorted order
                $.each(data.entries, function(prio, entry) {
                    addEntry(entry);
                });
            });
        } else {
            // Unknown request - send them back to the main acls page
            window.location = "/xenrt/ui/acls";
            return;
        }

        $( ".aclcolumn" ).sortable({
            connectWith: ".aclcolumn",
            handle: ".aclentry-header",
            placeholder: "aclentry-placeholder ui-corner-all",
            cancel: ".aclentry-toggle"
        });

});
    function populateAcls() {
        $.getJSON ("/xenrt/api/v2/acls", {"owner": "me"})
            .done(function(data) {
                $.each(data, function(aclid, acldata) {
                    if (acldata.parent == null)
                        $(" #parent" ).append("<option value=" + aclid + ">" + acldata.name + "</option>");
                });
            });
    }

    function addEntry(entry) {
        var aclDiv = $( "<div class=\"aclentry ui-widget ui-widget-content ui-helper-clearfix ui-corner-all\" />" );
        var entryType = "Unknown";
        var entryContent = "";
        if (entry.type == "user")
            entryType = "User match";
        else if (entry.type == "group")
            entryType = "Group match";
        else
            entryType = "Default match";
        var aclHeader = $( "<div class=\"aclentry-header ui-widget-header ui-corner-all\"><span class='ui-icon ui-icon-minusthick aclentry-toggle'></span>" + entryType + "</div>");
        var aclContent = $( "<div class=\"aclentry-content\" />");

        var useridText = "Username";
        if (entry.type == "group")
            useridText = "Group";

        if (entry.type != "default") {
            var perUserDiv = $( "<div class=\"aclentry-userid\" />" );
            perUserDiv.append("<p>" + useridText + ": <input type=\"text\" id=\"userid\" value=\"" + entry.userid + "\" /></p>");
            aclContent.append(perUserDiv);
        }

        var userLimitsDiv = $( "<div class=\"aclentry-userlimits\" />" );
        userLimitsDiv.append("User limit: <input type=\"text\" id=\"userlimit\" value=\"" + (entry.userlimit ? entry.userlimit : "") + "\" /><br />");
        userLimitsDiv.append("User percentage: <input type=\"text\" id=\"userpercent\" value=\"" + (entry.userpercent ? entry.userpercent : "") + "\" /><br />");
        aclContent.append(userLimitsDiv);

        if (entry.type != "user") {
            var groupLimitsDiv = $( "<div class=\"aclentry-grouplimits\" />" );
            groupLimitsDiv.append("Group limit: <input type=\"text\" id=\"grouplimit\" value=\"" + (entry.grouplimit ? entry.grouplimit : "") + "\" /><br />");
            groupLimitsDiv.append("Group percentage: <input type=\"text\" id=\"grouppercent\" value=\"" + (entry.grouppercent ? entry.grouppercent : "") + "\" /><br />");
            aclContent.append(groupLimitsDiv);
        }             

        aclContent.append("Maximum lease hours: <input type=\"text\" id=\"maxlease\" value=\"" + (entry.maxleasehours ? entry.maxleashours : "") + "\" />");

        aclDiv.append(aclHeader);
        aclDiv.append(aclContent);
        aclDiv.data("entry", entry);
        $( ".aclcolumn" ).append(aclDiv);
        return aclDiv;
    }
    $( "#adduser" ).click(function() {
        var entry = addEntry({"type": "user", "userid": ""});
        $( ".aclcolumn" ).sortable("refresh");
        entry.children("#userid").focus()
    });
    $( "#addgroup" ).click(function() {
        var entry = addEntry({"type": "group", "userid": ""});
        $( ".aclcolumn" ).sortable("refresh");
        entry.children("#userid").focus()
    });
    $( "#adddefault" ).click(function() {
        var entry = addEntry({"type": "default"});
        $( ".aclcolumn" ).sortable("refresh");
        entry.children("#userlimit").focus()
    });
    $( ".aclcolumn" ).on('click', '.aclentry-toggle', function() {
        $( this ).parents(".aclentry").remove();
        $( ".aclcolumn" ).sortable("refresh");
    });
    $( ".aclcolumn" ).on('change', '#userid', function() {
        // Validate the new user / group id is valid
        var aclEntry = $( this ).parents(".aclentry").data("entry");
        var adurl = "/xenrt/api/v2/ad?search=" + encodeURIComponent($( this ).val()) + "&attributes=objectClass";
        var parent = $( this ).parent();
        $.getJSON(adurl).done(function(data) {
            parent.children(".ui-icon-notice").remove()
            if (!(data.length == 1 && $.inArray((aclEntry.type == "user" ? "person" : "group"), data[0].objectClass))) {
                var notice = $( "<span class='ui-icon ui-icon-notice' style='float: right' title='The given " + aclEntry.type + " was not found in AD'></span>" );
                parent.append(notice);
            }
        });
    });
    $( document ).tooltip();
});
    </script>
    <style>
        .aclcolumn {
            width: 250px;
            float: left;
            padding-bottom: 100px;
        }
        .aclentry {
            margin: 0 1em 1em 0;
            padding: 0.3em;
        }
        .aclentry-header {
            padding: 0.2em 0.3em;
            margin-bottom: 0.5em;
            position: relative;
        }
        .aclentry-content {
            padding: 0.4em;
        }
        .aclentry-placeholder {
            border: 1px dotted black;
            margin: 0 1em 1em 0;
            height: 50px;
        }
        .aclentry-toggle {
            position: absolute;
            top: 50%;
            right: 0;
            margin-top: -8px;
        }
    </style>
</head>
<body>

${commonbody | n}
<div id="mainbody">

<h1>ACL Editor</h1>
<h2>ACL Details</h2>
<p>
<input type="hidden" id="acldata" />
Name: <input type="text" id="aclname" /><br />
Parent: <select id="parent"><option value="" selected>&lt; None &gt;</option></select>
</p>

<h2>ACL Entries</h2>
<div class="aclcolumn">
</div>
<p>
<button id="adduser" class="ui-state-default ui-corner-all">Add User Entry</button>
<button id="addgroup" class="ui-state-default ui-corner-all">Add Group Entry</button>
<button id="adddefault" class="ui-state-default ui-corner-all">Add Default Entry</button>
</p>

<p>
<button id="saveacl" class="ui-state-default ui-corner-all">Save</button>
</p>
</div>
</body>
</html>
