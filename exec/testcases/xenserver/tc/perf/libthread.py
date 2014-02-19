import threading

class ExcThread(threading.Thread):
  def excRun(self):
    pass

  def run(self):
    self.exc = None
    try:
      self.excRun()
    except:
      import sys
      self.exc = sys.exc_info()

  def join(self):
    threading.Thread.join(self)
    if self.exc:
      msg = "Thread '%s' threw an exception: %s" % (self.getName(), self.exc[1])
      new_exc = Exception(msg)
      raise new_exc.__class__, new_exc, self.exc[2]

class TestThread(ExcThread):
  def excRun(self):
    import time
    time.sleep(0.3)
    print "TestThread.run"
    raise Exception("some random exception")
    time.sleep(0.3)

if __name__ == '__main__':
  print "main: creating"
  t = TestThread()
  print "main: starting"
  t.start()
  print "main: joining"
  t.join()
  print "main: joined"
