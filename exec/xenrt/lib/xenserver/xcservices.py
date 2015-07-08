import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log
import calendar,time
from abc import ABCMeta, abstractmethod

class XenCenterService(object):
    __metaclass__=ABCMeta

    def __init__(self,service,guest):
        self.service = service
        self.guest=guest
        xenrt.log("Creating XenCenter Service %s on guest %s"%(self.service,self.guest.getName()))

    @abstractmethod
    def startService(self):
        pass

    @abstractmethod
    def stopService(self):
        pass

    @abstractmethod
    def installService(self):
        pass

    @abstractmethod
    def triggerService(self):
        pass

    @abstractmethod
    def verifyService(self):
        pass

    @abstractmethod
    def initializeService(self):
        pass

    @abstractmethod
    def activateService(self):
        pass

    @abstractmethod
    def deactivateService(self):
        pass


class HealthCheckService(XenCenterService):

    def startService(self):
        self.guest.xmlrpcExec("net start %s"%self.service)

    def stopService(self):
        self.guest.xmlrpcExec("net stop %s"%self.service)

    def installService(self):
        xenrt.log("Default Installation while installing XenCenter")

    def initializeService(self,pool):
        self.UPLOAD_TIMEINT_MINS = 5
        self.tokenSecret="IdentityToken_secret"
        self.diagnosticSecret="DaignosticTokenSecret"
        self.username="root"
        self.password="xenroot"

        self.secrets = [self.tokenSecret,self.diagnosticSecret,self.username,self.password]
        xenrt.TEC().logverbose('Creating secret (%s)' % self.secrets)

        #Create Secrets
        self.secretsUUID={s:pool.master.createSecret(s) for s in self.secrets}

        self.health_check_config={"Schedule.RetryInterval": "2", "Schedule.TimeOfDay":"2", "Schedule.IntervalInDays" :"13" ,\
            "UploadToken.Secret": self.secretsUUID[self.tokenSecret],"DiagnosticToken.Secret": self.secretsUUID[self.diagnosticSecret],\
            "Password.Secret": self.secretsUUID[self.password] ,"User.Secret":  self.secretsUUID[self.username],\
            "Enrollment": "true", "Schedule.DayOfWeek": "1","LastSuccessfulUpload": "2015-07-28T14:02:40.7468000Z"}

    def activateService(self,pool):
        cli = pool.master.getCLIInstance()
        #Initialize health_check_config -This is the feature enrollment stage via cli
        for health_check_key in self.health_check_config:
            cli.execute("pool-param-set","uuid=%s health-check-config:%s=%s" % (pool.getUUID(),health_check_key,self.health_check_config[health_check_key]))

        cli.execute("pool-param-get","uuid=%s param-name=health-check-config" %pool.getUUID())

    def deactivateService(self,pool):
        cli = pool.master.getCLIInstance()
        cli.execute("pool-param-clear","uuid=%s param-name=health-check-config" % (pool.getUUID()))

    def triggerService(self,pool,options=None):
        if options["trigger_mechanism"] == "SET_SCHEDULE":
            #ToDo:handle hcparams
            self.uploadTimeAbs=self.setNewUploadSchedule(pool)
        elif options["trigger_mechanism"] == "UPLOAD_NOW":
            self.uploadTimeAbs=self.setUploadNow(pool)
        else :
            raise xenrt.XRTError("Cannot find suitable mechanism to trigger Service")
        return self.uploadTimeAbs

    def setUploadNow(self,pool):
        cli = pool.master.getCLIInstance()
        #set upload time in 60 secs
        uploadNowAbs=int(self.guest.getTime()+ 60)
        uploadNowTs = time.strftime("%Y-%m-%dT%H:%M:%S.0000000Z", time.gmtime(uploadNowAbs))
        cli.execute("pool-param-set uuid=%s health-check-config:NewUploadRequest=%s"%(pool.getUUID(),uploadNowTs))
        return uploadNowAbs

    def setNewUploadSchedule(self,pool,hcparams=None):
        cli = pool.master.getCLIInstance()

        currTimeStamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.guest.getTime()))
        t=time.strptime(currTimeStamp, "%Y-%m-%dT%H:%M:%S")
        if not hcparams:
            hcparams={}
            #Adjust the dayofWeek as Monday is 1 as per XenCenter
            hcparams["Schedule.DayOfWeek"]=str((t.tm_wday+1)%7)
            #We are setting the new schedule so that upload happens in the very next hour at the time of the execution of the testcase
            hcparams["Schedule.TimeOfDay"]=str(t.tm_hour+1)
            hcparams["Schedule.IntervalInDays"]=str(7)
            hcparams["Schedule.RetryInterval"]=str(1)
            hcparams["NewUploadRequest"]=""
        xenrt.log("Set the new schedule for upload")
        for health_check_key in hcparams:
            cli.execute("pool-param-set","uuid=%s health-check-config:%s=%s" % (pool.getUUID(),health_check_key,hcparams[health_check_key]))

        #get the timestamp based on the new schedule
        nextUploadTs=str(t.tm_year)+"-"+ str(t.tm_mon)+"-"+ str(t.tm_mday)+"T"+str(hcparams["Schedule.TimeOfDay"])
        nextUploadAbs=int(calendar.timegm(time.strptime(nextUploadTs, "%Y-%m-%dT%H")))
        return nextUploadAbs


    def verifyService(self,pool,abstime,timeout=300):
        #return true or False as per the upload
        cli = pool.master.getCLIInstance()
        scheduledUpload = abstime
        uploadTimeLimit = scheduledUpload + self.UPLOAD_TIMEINT_MINS*60 + timeout

        #Between uploadtime  and uploadtime+Uploadinterval+Buffer I expect upload to happen
        while xenrt.timenow() <  uploadTimeLimit:
            lastSucUploadTs=cli.execute("pool-param-get","uuid=%s param-name=\"%s\" param-key=\"%s\"" % (pool.getUUID(),"health-check-config","LastSuccessfulUpload"),strip=True)
            xenrt.log(lastSucUploadTs)
            lastSucUploadAbs=int(calendar.timegm(time.strptime(lastSucUploadTs.split('.')[0], "%Y-%m-%dT%H:%M:%S")))
            if lastSucUploadAbs and lastSucUploadAbs > scheduledUpload  and  lastSucUploadAbs < uploadTimeLimit:
                xenrt.log("Upload for pool %s successfully took place at %s"%(pool.getName(),lastSucUploadTs))
                return True
            else:
                xenrt.sleep(30)
        xenrt.log("No upload observed for pool %s during the expected timeframe"%pool.getName())
        xenrt.log("Last Successful Upload for pool %s took place at %s"%(pool.getName(),lastSucUploadTs))
        return False


    def verifyServiceFailure(self,pool,abstime,timeout=300):
        cli = pool.master.getCLIInstance()
        scheduledUpload = abstime
        uploadTimeLimit = scheduledUpload + self.UPLOAD_TIMEINT_MINS*60 + timeout

        try:
            lastFailedUploadTs=cli.execute("pool-param-get","uuid=%s param-name=\"%s\" param-key=\"%s\"" % (pool.getUUID(),"health-check-config","LastFailedUpload"),strip=True)
        except:
            xenrt.log("LastFqailedUpload field didnt get populated  in health-chcek-config by the service")
            return False

        lastFailedUploadAbs=int(calendar.timegm(time.strptime(lastFailedUploadTs.split('.')[0], "%Y-%m-%dT%H:%M:%S")))
        xenrt.log(lastFailedUploadTs)
        if lastFailedUploadAbs and lastFailedUploadAbs>scheduledUpload and  lastFailedUploadAbs < uploadTimeLimit:
            xenrt.log("Upload Attempt for pool %s failed indeed.Service acknowledge the upload failure at %s"%(pool.getName(),lastFailedUploadTs))
            return True
        else:
            xenrt.log("Upload Attempt for pool %s failed zat some different timestamp.Service acknowledge the upload failure at %s"%(pool.getName(),lastFailedUploadTs))
            return False

class ServiceFactory(object):

    def getService(self,service,guest):
        if service == "HealthCheck":
            return HealthCheckService("XenServerHealthCheck",guest)
        raise ValueError("%s Service has not been implemented yet "%service)
    
