import config
import base64, hashlib, random
import jose.jws
import jose.jwt
import jwkest.jwk

class User(object):
    def __init__(self, page, userid):
        self.page = page
        self.userid = userid
        self._valid = None
        self._email = None
        self._apiKey = None
        self._disabled = False
        self._team = None
        self._groups = None

    @classmethod
    def fromApiKey(cls, page, apiKey):
        cur = page.getDB().cursor()
        cur.execute("SELECT userid,apikey,email,disabled,team FROM tblusers WHERE apikey=%s", [apiKey])
        rc = cur.fetchone()
        if rc:
            user = cls(page, rc[0].strip())
            user._valid = True
            user._apiKey = apiKey
            user._email = rc[2].strip() if rc[2] else None
            user._disabled = rc[3]
            user._team = rc[4].strip() if rc[4] else None
            return user
        return None

    @classmethod
    def fromJWT(cls, page, token):
        try:
            headers, claims, signing_input, sig = jose.jws._load(token)
            if not claims['iss'] in config.trusted_jwt_iss.split(","):
                raise Exception("JWT iss is not trusted")

            keys = jwkest.jwk.KEYS()
            keys.load_from_url("%s/.well-known/jwks" % claims['iss'])
            key = keys.by_kid(headers['kid'])[0].get_key().exportKey()
            claims = jose.jwt.decode(token, key, options={'verify_aud':False})
            username = claims['domainuserid']
        except Exception, e:
            print str(e)
            return None
        else:
            user = cls(page, username)
            return user

    @property
    def valid(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._valid

    @property
    def team(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._team
        

    @property
    def email(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._email

    @property
    def apiKey(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._apiKey

    @property
    def disabled(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._disabled

    @property
    def groups(self):
        """List of groups we know the user to be in"""
        if self._groups is None:
            self._getGroups()
        return self._groups

    def _getGroups(self):
        db = self.page.getDB()
        cur = db.cursor()
        cur.execute("SELECT g.name FROM tblgroups g INNER JOIN tblgroupusers gu ON g.groupid = gu.groupid WHERE gu.userid=%s", [self.userid.lower()])
        self._groups = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            self._groups.append(rc[0].strip())

    @property
    def admin(self):
        """Property that defines if the user is a XenRT admin"""
        return config.admin_group in self.groups

    def removeApiKey(self):
        if self.apiKey:
            db = self.page.getWriteDB()
            cur = db.cursor()
            cur.execute("UPDATE tblusers SET apikey=NULL WHERE userid=%s", [self.userid])
            db.commit()

    def generateNewApiKey(self):
        assert self.valid
        self._apiKey = base64.b64encode(hashlib.sha224( str(random.getrandbits(256)) ).digest())[:38]
        db = self.page.getWriteDB()
        cur = db.cursor()
        cur.execute("UPDATE tblusers SET apikey=%s WHERE userid=%s", [self._apiKey, self.userid])
        db.commit()
        return self._apiKey

    def _getFromDBorAD(self, apiKey=None):
        db = self.page.getDB()
        cur = db.cursor()
        cur.execute("SELECT userid,apikey,email,disabled,team FROM tblusers WHERE userid=%s", [self.userid])
        rc = cur.fetchone()
        if rc:
            self._valid = True
            self._apiKey = rc[1].strip() if rc[1] else None
            self._email = rc[2].strip() if rc[2] else None
            self._disabled = rc[3]
            self._team = rc[4].strip() if rc[4] else None
            return

        if not rc:
            # Might be a valid user who's not in tblusers
            try:
                print "Attempting to get %s from AD" % self.userid
                self._email = self.page.getAD().get_email(self.userid)
                self._valid = True
                self._disabled = self.page.getAD().is_disabled(self.userid)
                db = self.page.getWriteDB()
                cur = db.cursor()
                cur.execute("INSERT INTO tblusers (userid,email,disabled) VALUES (%s,%s,%s)", [self.userid, self._email, self._disabled])
                db.commit()
            except KeyError:
                self._valid = False

