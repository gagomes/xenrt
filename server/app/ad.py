import config
import ldap

# TODO:
# Paging of results (particularly in get_all_members_of_group)
# Caching of DNs (ideally on a per request basis)

class ActiveDirectory(object):
    _ATTRS = ['member', 'memberOf', 'sAMAccountName', 'objectClass', 'cn']

    def __init__(self):
        self._ldap = ldap.ldapobject.ReconnectLDAPObject(config.ldap_uri)
        self._ldap.protocol_version = 3
        self._ldap.set_option(ldap.OPT_REFERRALS, 0)
        self._ldap.simple_bind_s(config.ldap_user, config.ldap_pass)
        self._base = config.ldap_base

    def is_valid_user(self, username):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, "(&(objectClass=person)(sAMAccountName=%s))" % username, attrlist=['sAMAccountName'])
        return not (len(results) == 0 or results[0][0] is None)

    def get_email(self, username):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, "(&(objectClass=person)(sAMAccountName=%s))" % username, attrlist=['mail'])
        if len(results) == 0 or results[0][0] is None:
            raise KeyError("%s not a valid user" % username)
        dn, data = results[0]
        if data.has_key('mail') and len(data['mail']) >= 1:
            return data['mail'][0]
        return None

    def get_all_members_of_group(self, group, _isDN=False, _visitedGroups=[]):
        if _isDN:
            groupres = self._ldap.search_s(group, ldap.SCOPE_BASE, "(objectClass=*)", attrlist=self._ATTRS)[0]
        else:
            groupres = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, "(CN=%s)" % group, attrlist=self._ATTRS)[0]
        dn, group = groupres
        if dn in _visitedGroups:
            return []
        _visitedGroups.append(dn)
        if 'person' in group['objectClass']:
            return [group['sAMAccountName'][0]]
        members = []
        if group.has_key('member'):
            for m in group['member']:
                members += self.get_all_members_of_group(m, _isDN=True, _visitedGroups=_visitedGroups)
        return members

    def get_groups_for_user(self, username, _isDN=False, _visitedGroups=[]):
        if _isDN:
            groupres = self._ldap.search_s(username, ldap.SCOPE_BASE, "(objectClass=*)", attrlist=self._ATTRS)[0]
        else:
            groupres = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, "(sAMAccountName=%s)" % username, attrlist=self._ATTRS)[0]
        dn, group = groupres
        if dn in _visitedGroups:
            return []
        _visitedGroups.append(dn)
        groups = [group['cn'][0]]
        if group.has_key('memberOf'):
            for m in group['memberOf']:
                groups += self.get_groups_for_user(m, _isDN=True, _visitedGroups=_visitedGroups)
        return groups

