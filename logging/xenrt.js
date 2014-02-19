var subnodes = "subnodes.tar.bz2"
var getfile = "/cgi/getfile.sh"

function primeCache() {
    filename = window.location.pathname;
    tarfile = filename.match(/\/[^\/]+/) + "/" + subnodes;
    req = new XMLHttpRequest();
    req.open("GET", getfile + "?" + tarfile);
    req.send(null);
}
primeCache();

/*
Load a subtree into a given div.
*/
function loadSubTree(id) {
    // Check if this node is lazy.
    div = document.getElementById(id);
    if (div) {
        // Cache loads.
        if (!div.innerHTML) {    
            filename = window.location.pathname;
            tarfile = filename.match(/\/[^\/]+/) + "/" + subnodes;
            // Get the node data.
            req = new XMLHttpRequest();
            // Asynchronous request.
            req.open("GET", getfile + "?" + tarfile + "+" + id + ".htm");          
            // Callback to deal with data once it arrives.
            req.onreadystatechange = function (evt) {
                if (req.readyState == 4) {
                    // Load the data into the log tree.
                    div.innerHTML = req.responseText;
                }
            }
            // Issue the request.
            req.send(null);
        }
    } 
}

/*
Expand and collapse nodes in the log tree.
*/
function toggle(node, id) {
    // Load the node data if required.
    nodename = id + "_subtree"
    loadSubTree(nodename);
    // Toggle the displaying of the node.
    if (node.parentNode.className=="liOpen") {
        node.parentNode.className="liClosed";
    }
    else {
        node.parentNode.className="liOpen";
    }
}

/*
Show a table of node details.
*/
function details(node, id) {
    nodename = id + "_details"
    loadSubTree(nodename);
    div = document.getElementById(nodename);
    if (div.className=="hidedetails") {
        div.className="showdetails";
    }
    else {
        div.className="hidedetails";  
    }    
}
