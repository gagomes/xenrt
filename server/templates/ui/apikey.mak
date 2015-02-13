<!doctype html>
<html lang=''>
<head>

${commonhead | n}
    <script>
$(function() {
    $( "#getkey" ).click(function() {
        $('#getkey').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        $( "#apikey" ).empty();
        $( "#revokestatus").empty();
        $.ajaxSetup( { "async": false } );
        var keyget = "/xenrt/api/v2/apikey"
        $.getJSON (keyget, {})
            .done(function(data) {
                var out = "<p>My API key is <span style=\"font-weight:bold\">" + data["key"] + "</span></p>";
                $( out ).appendTo( "#apikey" );
            });
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#getkey').prop('disabled', false);
    }); 
    
    $( "#revokekey" ).click(function() {
        if (!window.confirm("Are you sure you want to revoke your API key?")) {
            return;
        }
        $('#revokekey').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        $( "#apikey" ).empty();
        $( "#revokestatus").empty();
        $.ajaxSetup( { "async": false } );
        var keydelete = "/xenrt/api/v2/apikey";
        $.ajax({
            url: keydelete,
            type: 'DELETE',
            async: false,
            success: function(data) {
                var out = "<p>API key revoked successfully. To create a new key, click \"Get my API key\" above</p>";
                $( out ).appendTo( "#revokestatus" );
            }
        });
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#revokekey').prop('disabled', false);
    }); 
});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">

<h2>Manage my API key</h2>
<p>
<button id="getkey" class="ui-state-default ui-corner-all">Get my API key</button>
<div id="apikey"></div>
</p>
<p>
<button id="revokekey" class="ui-state-default ui-corner-all">Revoke my API key</button>
<div id="revokestatus"></div>
</p>


</div>
</body>
<html>
