class IpTablesFirewall(object):
    """
    Class to manipulate IPTables rules on a host.
    Narrow implementation for specific scenarios, open for further implementation.
    """
    def __init__(self, host):
        self.host = host

    def blockIP(self, ipaddress, direction="INPUT"):
        # Insert the rule.
        self.host.execdom0("iptables -I %s -s %s -j DROP" % (direction, ipaddress))

    def blockPort(self, port, protocol="all", direction="INPUT"):
        # Insert the rule.
        self.host.execdom0("iptables -I %s -p %s --destination-port %s -j DROP" % (direction, protocol, port))

    def unblockIP(self, ipaddress, direction="INPUT"):
        # Delete the rule. Needs to be the same params.
        self.host.execdom0("iptables -D %s -s %s -j DROP" % (direction, ipaddress))

    def unblockPort(self, port, protocol="all", direction="INPUT"):
        # Delete the rule. Needs to be the same params.
        self.host.execdom0("iptables -D %s -p %s --destination-port %s -j DROP" % (direction, protocol, port))
