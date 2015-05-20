# ACL Unit tests
from mock import patch, Mock
from testing import XenRTUnitTestCase
import app.acl

class AclTests(XenRTUnitTestCase):

    def setUp(self):
        self.page = Mock()
        self.acl = app.acl.ACLHelper(self.page)

    def _assertTuple(self, value, expected, msg):
        if not type(value) is tuple:
            return False
        if not msg:
            msg = "Expected %s, found %s with '%s'" % (expected, value[0], value[1])
        return self.assertIs(value[0], expected, msg)

    def assertTupleTrue(self, value, msg=None):
        return self._assertTuple(value, True, msg)

    def assertTupleFalse(self, value, msg=None):
        return self._assertTuple(value, False, msg)

    def test_check_acl(self):
        """Tests check_acl parent/child handling"""
        parentAcl = app.acl.ACL(1, "parent", None, "unittests", [], {})
        childAcl = app.acl.ACL(2, "child", 1, "unittests", [], {})
        self.acl.get_acl = Mock(side_effect = lambda aclid: aclid == 1 and parentAcl or childAcl)

        # Parent
        self.acl._check_acl = Mock(return_value=(True,None))
        self.assertTupleTrue(self.acl.check_acl(1, "userid", 5, None), "check_acl returned incorrect result")
        self.acl._check_acl.assert_called_once_with(parentAcl, "userid", 5, None)

        self.acl._check_acl.reset_mock()
        self.acl._check_acl.return_value = (False, "Test")
        self.assertTupleFalse(self.acl.check_acl(1, "userid", 5, None), "check_acl returned incorrect result")
        self.acl._check_acl.assert_called_once_with(parentAcl, "userid", 5, None)

        # Child (both true)
        self.acl._check_acl.reset_mock()
        self.acl._check_acl.return_value = (True, None)
        self.assertTupleTrue(self.acl.check_acl(2, "userid", 5, None), "check_acl returned incorrect result")
        self.acl._check_acl.assert_any_call(parentAcl, "userid", 5, None)
        self.acl._check_acl.assert_any_call(childAcl, "userid", 5, None)
        self.assertEqual(self.acl._check_acl.call_count, 2)

        # Child (child false)
        self.acl._check_acl.reset_mock()
        self.acl._check_acl.return_value = (False, "Test")
        self.assertTupleFalse(self.acl.check_acl(2, "userid", 5, None), "check_acl returned incorrect result")
        self.acl._check_acl.assert_called_once_with(childAcl, "userid", 5, None)

        # Child (parent false)
        self.acl._check_acl = Mock(side_effect = lambda acl,userid,num,lease: (acl.aclid == 2, None))
        self.assertTupleFalse(self.acl.check_acl(2, "userid", 5, None), "check_acl returned incorrect result")
        self.acl._check_acl.assert_any_call(parentAcl, "userid", 5, None)
        self.acl._check_acl.assert_any_call(childAcl, "userid", 5, None)
        self.assertEqual(self.acl._check_acl.call_count, 2)

    def _setupAclReturns(self):
        """Sets up the mocked ACL environment"""
        def groupsForUserId(userid):
            if userid in ["user1","user2"]:
                return ["group1"]
            return []
        self.acl.groups_for_userid = groupsForUserId
        def useridsForGroup(group):
            if group == "group1":
                return ["user1","user2"]
            return []
        self.acl._userids_for_group = useridsForGroup
        return app.acl.ACL(1, "test", None, "unittests", [], {"machine1":"user1", "machine2":"user2", "machine3":"user3", "machine4":None, "machine5":None, "machine6":None})

    # User limit tests use user1 who is already using 1 machine

    def test_user_limit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,5,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 3))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 4))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 5))

    def test_user_percent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,None,50,None)] # 50% = 3 machines
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 3))

    # Group limit tests use group1 which contains user1 and user2

    def test_group_limit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",5,None,None,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 2))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 3))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 4))

    def test_group_percent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,70,None,None,None)] # 70% = 4 machines
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 3))

    def test_group_userlimit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,5,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 3))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 4))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 5))

    def test_group_userpercent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,None,50,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 3))

    # Default match tests

    def test_default_userlimit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "default","",None,None,5,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 3))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 4))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user3", ['dummy'] * 5))

    def test_default_userpercent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "default","",None,None,None,50,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user3", ['dummy'] * 3))

    def test_default_grouplimit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "default","",5,None,None,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user3", ['dummy'] * 3))

    def test_default_grouppercent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "default","",None,84,None,None,None)] # 84% = 5 machines
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user3", ['dummy'] * 3))

    # Lease time limit

    def test_leasehours(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,None,None,12)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'], 6))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'], 12))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'], 13))

    # Ordering tests

    def test_matching_user(self):
        """Check matching user limit is applied and evaluation stops"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,5,None,None), app.acl.ACLEntry(1, "group","group1",None,None,4,None,None), app.acl.ACLEntry(2, "default","",None,None,1,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 4)) # +4 for user1 brings him to 5, which would fail the group / default limit

    def test_users_removed_groups(self):
        """Check users specifically listed in the ACL don't contribute to group entries"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,5,None,None), app.acl.ACLEntry(1, "group","group1",None,None,4,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user2", ['dummy'] * 3)) # +3 for user2 brings him to 4, user1's 1 shouldn't count in the group count

    def test_nonmatching_user(self):
        """Check non matching user entries are ignored"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,5,None,None), app.acl.ACLEntry(1, "group","group1",None,None,4,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user2", ['dummy'] * 4)) # +4 for user2 brings him to 5, which shouldn't be allowed

    def test_no_user_fallthrough(self):
        """Check failing user limit is applied even if a later group limit is OK"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,2,None,None), app.acl.ACLEntry(1, "group","group1",None,None,5,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 2)) # +2 for user1 brings him to 3, which should fail

    def test_group_matching(self):
        """Check matching group limit is applied even if a later user limit is OK"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,5,None,None), app.acl.ACLEntry(1, "user","user1",None,None,2,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ['dummy'] * 4)) # +4 for user1 brings him to 5, which should be allowed by the group limit
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,2,None,None), app.acl.ACLEntry(1, "user","user1",None,None,5,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 4)) # +4 for user1 brings him to 5, which isn't allowed by the group, but is by the later user

    def test_group_nonmatching(self):
        """Check non matching group limit falls through to a later user limit"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group2",None,None,5,None,None), app.acl.ACLEntry(1, "user","user1",None,None,2,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", ['dummy'] * 4)) # +4 for user1 brings him to 5, which is allowed by the group, but isn't by the later user

    def test_default_fallthrough(self):
        """Check non matching user / group entries fall through to default entry"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,1,None,None), app.acl.ACLEntry(1, "group","group1",None,None,2,None,None), app.acl.ACLEntry(2, "default","",None,None,5,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 4))

    def test_groups_removed_default(self):
        """Check groups specifically listed in the ACL don't contribute to default entries"""
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry(0, "group","group1",None,None,2,None,None), app.acl.ACLEntry(1, "default","",4,None,None,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user3", ['dummy'] * 3)) # +3 for user3 brings him to 4, user1 and user2's 1s shouldn't count because of the group match

    # Note we have chosen to ignore machines in use by someone else in the same group, as the logic becomes too complicated
    # In those situations it is the case that the machine will be double counted.

    def test_one_already_inuse(self):
        """Check that an ACL doesn't double count a machine already in use by the user"""
        acl = self._setupAclReturns()
        # user1 is limited to 1 machine, and will ask to use machine1 (which they already have)
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,1,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ["machine1"]))

    def test_some_already_inuse(self):
        """Check that an ACL doesn't double count one machine already in use of others"""
        acl = self._setupAclReturns()
        # user1 is limited to 2 machines, and will ask to use machine1 (which they already have), and machine4 (which is free)
        acl.entries = [app.acl.ACLEntry(0, "user","user1",None,None,2,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", ["machine1","machine4"]))

