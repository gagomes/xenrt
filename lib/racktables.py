import MySQLdb,IPy,HTMLParser

class RackTables:
    def __init__(self, host, db, user, password=None):
        # Need to supply DB Host, DB name, and username/password that can read the DB from where this is run
        if password:
            self.db = MySQLdb.connect(host=host, db=db, user=user, passwd=password)
        else:
            self.db = MySQLdb.connect(host=host, db=db, user=user)

    def _execSQL(self, sql):
        cur = self.db.cursor()
        cur.execute(sql)
        return cur.fetchall()

    def getObject(self, name):
        # Gets a RackTablesObject from an object name
        res = self._execSQL("SELECT id FROM RackObject WHERE name='%s'" % name)
        if len(res) == 0:
            raise UserWarning("Could not find Object %s" % name)
        return RackTablesObject(self, res[0][0], name)
    
    def renderString(self, val):
        return val.replace("%GPASS%", " ")

    def getAttrID(self, attr):
        res = self._execSQL("""SELECT a.id FROM Attribute a WHERE a.name = '%s'""" % attr)
        if len(res) == 0:
            return None
        return res[0][0]

    def close(self):
        self.db.close()

    def getObjectsForTag(self, tag, recurse=True):
        tags = [x[0] for x in self._execSQL("SELECT id FROM TagTree WHERE tag='%s';" % tag)]
        if recurse:
            nexttags = tags
            while True:
                if not nexttags:
                    break
                newtags = [x[0] for x in self._execSQL("SELECT id FROM TagTree WHERE parent_id IN (%s)" % ",".join([str(x) for x in nexttags]))]
                tags.extend(newtags)
                nexttags = newtags
        res = self._execSQL("SELECT RackObject.id, RackObject.name FROM TagStorage INNER JOIN RackObject ON TagStorage.entity_realm='object' AND TagStorage.entity_id=RackObject.id WHERE TagStorage.tag_id IN (%s)" % (",".join([str(x) for x in tags])))
        return [RackTablesObject(self, x[0], x[1]) for x in res]


class RackTablesObject:
    def __init__(self, parent, objid, name):
        self.parent = parent
        self.objid = objid
        self.name = name

    def getType(self):
        res = self.parent._execSQL("SELECT Dictionary.dict_value FROM RackObject INNER JOIN Dictionary on RackObject.objtype_id=Dictionary.dict_key WHERE RackObject.id=%d;" % self.objid)
        return res[0][0]

    def getChildren(self):
        res = self.parent._execSQL("SELECT child_entity_id,name FROM EntityLink INNER JOIN RackObject ON RackObject.id=child_entity_id WHERE parent_entity_type='object' AND parent_entity_id=%d AND child_entity_type='object';" % self.objid)
        return [RackTablesObject(self.parent,x[0],x[1]) for x in res]

    def getParents(self):
        res = self.parent._execSQL("SELECT parent_entity_id,name FROM EntityLink INNER JOIN RackObject ON RackObject.id=parent_entity_id WHERE parent_entity_type='object' AND child_entity_id=%d AND child_entity_type='object';" % self.objid)
        return [RackTablesObject(self.parent,x[0],x[1]) for x in res]


    def getID(self):
        # Return the object ID for this object
        return self.objid

    def getAttribute(self, attr):
        # Get an Attribute for this object
        # e.g. o.getAttribute("DRAM, GB")
        res = self.parent._execSQL("""SELECT a.type,v.string_value,v.uint_value,v.float_value
                                        FROM Attribute a
                                            INNER JOIN AttributeValue v ON a.id=v.attr_id
                                        WHERE v.object_id=%d AND a.name='%s';""" % (self.objid,attr))
        if len(res) == 0:
            return None
        type = res[0][0]
        if type == "dict":
            dictval = self.parent._execSQL("SELECT dict_value FROM Dictionary WHERE dict_key=%d" % res[0][2])
            return self.parent.renderString(dictval[0][0])
        elif type == "string":
            return self.parent.renderString(res[0][1])
        elif type == "uint":
            return res[0][2]
        elif type == "float":
            return res[0][3]

    def getComment(self):
        comment = self.parent._execSQL("SELECT comment FROM RackObject WHERE id=%d;" % self.objid)[0][0]
        return HTMLParser.HTMLParser().unescape(comment) if comment else None
        

    def getPorts(self):
        # Get the ports, and the port/object they're connected to
        # Will return a list of tuples, each tuple will be:
        # (local port name, local port type, local port MAC, local port label, remote object, remote port name)
        ret = []
        pids = []
        # Newer versions of racktables have a different table name for port types
        queries1 = ["""SELECT p.id,p.name,d.dict_value,p.l2address,ob.id,ob.name,pb.name,p.label
                        FROM Port p
                            INNER JOIN Dictionary d ON d.dict_key=p.type
                            INNER JOIN Link l ON (l.porta=p.id)
                            INNER JOIN Port pb ON (l.portb = pb.id)
                            INNER JOIN RackObject ob ON (pb.object_id=ob.id)
                        WHERE p.object_id=%d;""",
                   """SELECT p.id,p.name,d.dict_value,p.l2address,ob.id,ob.name,pb.name,p.label
                        FROM Port p
                            INNER JOIN Dictionary d ON d.dict_key=p.type
                            INNER JOIN Link l ON (l.portb=p.id)
                            INNER JOIN Port pb ON (l.porta = pb.id)
                            INNER JOIN RackObject ob ON (pb.object_id=ob.id)
                        WHERE p.object_id=%d;"""]
        queries2 = ["""SELECT p.id,p.name,d.oif_name,p.l2address,ob.id,ob.name,pb.name,p.label
                        FROM Port p
                            INNER JOIN PortOuterInterface d ON d.id=p.type
                            INNER JOIN Link l ON (l.porta=p.id)
                            INNER JOIN Port pb ON (l.portb = pb.id)
                            INNER JOIN RackObject ob ON (pb.object_id=ob.id)
                        WHERE p.object_id=%d;""",
                   """SELECT p.id,p.name,d.oif_name,p.l2address,ob.id,ob.name,pb.name,p.label
                        FROM Port p
                            INNER JOIN PortOuterInterface d ON d.id=p.type
                            INNER JOIN Link l ON (l.portb=p.id)
                            INNER JOIN Port pb ON (l.porta = pb.id)
                            INNER JOIN RackObject ob ON (pb.object_id=ob.id)
                        WHERE p.object_id=%d;"""]
                        
                        
        for q in range(len(queries1)):
            try:
                res = self.parent._execSQL(queries2[q] % self.objid)
            except:
                res = self.parent._execSQL(queries1[q] % self.objid)
            for r in res:
                pids.append(r[0])
                ret.append((r[1], r[2], self._renderMAC(r[3]),r[7],RackTablesObject(self.parent, r[4], r[5]), r[6]))
        res = self.parent._execSQL("SELECT p.id,p.name,d.dict_value,p.l2address,p.label FROM Port p INNER JOIN Dictionary d ON d.dict_key=p.type WHERE p.object_id=%d;" % self.objid)
        for r in res:
            if r[0] not in pids:
                ret.append((r[1],r[2],self._renderMAC(r[3]),r[4],None,None))
        return ret

    def _renderMAC(self,mac):
        if mac:
            return "%s:%s:%s:%s:%s:%s" % (mac[0:2],mac[2:4],mac[4:6],mac[6:8],mac[8:10],mac[10:12])
        else:
            return None

    def getName(self):
        # Returns the name of this object
        return self.name

    def getIPAddrs(self):
        # Returns the IPs for this object. Dictionary of IP=>Interface Name
        res = self.parent._execSQL("SELECT ip,name FROM IPv4Allocation WHERE object_id=%d;" % self.objid)
        ret = {}
        for r in res:
            hexip = "%08x" % r[0]
            ret["%d.%d.%d.%d" % (int(hexip[0:2], 16),int(hexip[2:4], 16),int(hexip[4:6], 16),int(hexip[6:8], 16))] = r[1]
        return ret
    
    def getIP6Addrs(self):
        # Returns the IPs for this object. Dictionary of IP=>Interface Name
        res = self.parent._execSQL("SELECT ip,name FROM IPv6Allocation WHERE object_id=%d;" % self.objid)
        ret = {}
        for r in res:
            addr = []
            for i in range(len(r[0])/2):
                addr.append("%02x%02x" % (ord(r[0][i*2]), ord(r[0][i*2+1])))
            ret[str(IPy.IP(":".join(addr)))] = r[1]
        return ret
