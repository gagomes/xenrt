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
        return self.assertIs(value[0], expected, msg)

    def assertTupleTrue(self, value, msg=None):
        return self._assertTuple(value, True, msg)

    def assertTupleFalse(self, value, msg=None):
        return self._assertTuple(value, False, msg)

    def test_check_acl(self):
        """Tests check_acl parent/child handling"""
        parentAcl = app.acl.ACL(1, "parent", None, [])
        childAcl = app.acl.ACL(2, "child", 1, [])
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
        def getMachinesInAcl(aclid):
            return {"machine1":"user1", "machine2":"user2", "machine3":None, "machine4":None, "machine5":None, "machine6":None}
        self.acl.get_machines_in_acl = getMachinesInAcl
        def groupsForUserId(userid):
            if userid in ["user1","user2"]:
                return ["group1"]
            return []
        self.acl._groups_for_userid = groupsForUserId
        def useridsForGroup(group):
            if group == "group1":
                return ["user1","user2"]
            return []
        self.acl._userids_for_group = useridsForGroup
        return app.acl.ACL(1, "test", None, [])

    # User limit tests use user1 who is already using 1 machine

    def test_user_limit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("user","user1",None,None,5,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 3))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 4))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 5))

    def test_user_percent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("user","user1",None,None,None,50,None)] # 50% = 3 machines
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 3))

    # Group limit tests use group1 which contains user1 and user2

    def test_group_limit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("group","group1",5,None,None,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 2))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 3))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 4))

    def test_group_percent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("group","group1",None,70,None,None,None)] # 70% = 4 machines
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 3))

    def test_group_userlimit(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("group","group1",None,None,5,None,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 3))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 4))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 5))

    def test_group_userpercent(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("group","group1",None,None,None,50,None)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 1))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 2))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 3))

    def test_leasehours(self):
        acl = self._setupAclReturns()
        acl.entries = [app.acl.ACLEntry("group","group1",None,None,None,None,12)]
        # Under limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 1, 6))
        # On limit
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 1, 12))
        # Over limit
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 1, 13))

    def test_multiple_entries(self):
        # Check that multiple ACL entries are processed correctly
        acl = self._setupAclReturns()

        # Matching user limit is applied and evaluation stops
        acl.entries = [app.acl.ACLEntry("user","user1",None,None,5,None,None), app.acl.ACLEntry("group","group1",None,None,4,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 4)) # +4 for user1 brings him to 5, which would fail the group limit

        # Users specifically listed in the ACL don't contribute to group entries
        self.assertTupleTrue(self.acl._check_acl(acl, "user2", 3)) # +3 for user2 brings him to 4, user1's 1 shouldn't count in the group count

        # Non matching user entries are ignored
        self.assertTupleFalse(self.acl._check_acl(acl, "user2", 4)) # +4 for user2 brings him to 5, which shouldn't be allowed

        # Failing user limit is applied even if group is OK
        acl.entries = [app.acl.ACLEntry("user","user1",None,None,2,None,None), app.acl.ACLEntry("group","group1",None,None,5,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 2)) # +2 for user1 brings him to 3, which should fail

        # Matching group limit ignores a later user limit
        acl.entries = [app.acl.ACLEntry("group","group1",None,None,5,None,None), app.acl.ACLEntry("user","user1",None,None,2,None,None)]
        self.assertTupleTrue(self.acl._check_acl(acl, "user1", 4)) # +4 for user1 brings him to 5, which should be allowed by the group limit
        acl.entries = [app.acl.ACLEntry("group","group1",None,None,2,None,None), app.acl.ACLEntry("user","user1",None,None,5,None,None)]
        self.assertTupleFalse(self.acl._check_acl(acl, "user1", 4)) # +4 for user1 brings him to 5, which isn't allowed by the group, but is by the later user

