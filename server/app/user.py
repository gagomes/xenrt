import base64, hashlib, random

class User(object):
    def __init__(self, page, userid):
        self.page = page
        self.userid = userid
        self._valid = None
        self._email = None
        self._apiKey = None

    @classmethod
    def fromApiKey(cls, page, apiKey):
        cur = page.getDB().cursor()
        cur.execute("SELECT userid,apikey,email FROM tblusers WHERE apikey=%s", [apiKey])
        rc = cur.fetchone()
        if rc:
            user = cls(page, rc[0].strip())
            user._valid = True
            user._apiKey = apiKey
            user._email = rc[2].strip() if rc[2] else None
            return user
        return None

    @property
    def valid(self):
        if self._valid is None:
            self._getFromDBorAD()
        return self._valid

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
    def admin(self):
        """Property that defines if the user is a XenRT admin"""
        return True

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
        cur.execute("SELECT userid,apikey,email FROM tblusers WHERE userid=%s", [self.userid])
        rc = cur.fetchone()
        if rc:
            self._valid = True
            self._apiKey = rc[1].strip()
            self._email = rc[2].strip()
            return

        if not rc:
            # Might be a valid user who's not in tblusers
            try:
                self._email = self.page.getAD().get_email(self.userid)
                self._valid = True
                db = self.page.getWriteDB()
                cur = db.cursor()
                cur.execute("INSERT INTO tblusers (userid,email) VALUES (%s,%s)", [self.userid, self._email])
                db.commit()
            except KeyError:
                self._valid = False

