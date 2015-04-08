import config
import ldap
from ldap.filter import filter_format

class ActiveDirectory(object):
    _ATTRS = ['member', 'memberOf', 'sAMAccountName', 'objectClass', 'cn']

    def __init__(self):
        self._ldap = ldap.ldapobject.ReconnectLDAPObject(config.ldap_uri)
        self._ldap.protocol_version = 3
        self._ldap.set_option(ldap.OPT_REFERRALS, 0)
        self._ldap.simple_bind_s(config.ldap_user, config.ldap_pass)
        self._base = config.ldap_base
        self._groupCache = {}

    def is_valid_user(self, username):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(&(objectClass=person)(sAMAccountName=%s))", [username]), attrlist=['sAMAccountName'])
        return not (len(results) == 0 or results[0][0] is None)

    def is_valid_group(self, groupname):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(&(objectClass=group)(CN=%s))", [groupname]), attrlist=['sAMAccountName'])
        return not (len(results) == 0 or results[0][0] is None)

    def is_disabled(self, username):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(&(objectClass=person)(sAMAccountName=%s))", [username]), attrlist=['userAccountControl'])
        if len(results) == 0 or results[0][0] is None:
            raise KeyError("%s not a valid user" % username)
        dn, data = results[0]
        if data.has_key('userAccountControl') and len(data['userAccountControl']) >= 1:
            uac = int(data['userAccountControl'][0])
            if uac & 2 == 2: # ADS_UF_ACCOUNTDISABLE = 2 - https://msdn.microsoft.com/en-us/library/ms680832%28v=vs.85%29.aspx
                return True
        return False

    def get_email(self, username):
        results = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(&(objectClass=person)(sAMAccountName=%s))", [username]), attrlist=['mail'])
        if len(results) == 0 or results[0][0] is None:
            raise KeyError("%s not a valid user" % username)
        dn, data = results[0]
        if data.has_key('mail') and len(data['mail']) >= 1:
            return data['mail'][0]
        return None

    def _getDN(self, dn):
        if not dn in self._groupCache:
            _, group = self._ldap.search_s(dn, ldap.SCOPE_BASE, "(objectClass=*)", attrlist=self._ATTRS)[0]
            self._groupCache[dn] = group
        return self._groupCache[dn]

    def get_all_members_of_group(self, group, _isDN=False, _visitedGroups=[]):
        if _isDN:
            groupres = group, self._getDN(group)
        else:
            groupres = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(CN=%s)", [group]), attrlist=self._ATTRS)[0]
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
            groupres = username, self._getDN(username)
        else:
            groupres = self._ldap.search_s(self._base, ldap.SCOPE_SUBTREE, filter_format("(sAMAccountName=%s)", [username]), attrlist=self._ATTRS)[0]
        dn, group = groupres
        if dn in _visitedGroups:
            return []
        _visitedGroups.append(dn)
        groups = [group['cn'][0]]
        if group.has_key('memberOf'):
            for m in group['memberOf']:
                groups += self.get_groups_for_user(m, _isDN=True, _visitedGroups=_visitedGroups)
        return groups

    def search(self, search, attributes):
        results = []
        query = filter_format("(|(&(objectClass=person)(sAMAccountName=%s))(&(objectCategory=group)(CN=%s)))", [search, search])
        for dn, data in self._ldap.search_st(self._base, ldap.SCOPE_SUBTREE, query, attrlist=map(lambda a: str(a), attributes), timeout=10):
            if not dn:
                continue
            res = {'dn': dn}
            for a in attributes:
                if data.has_key(a):
                    res[a] = data[a]
            results.append(res)
        return results

