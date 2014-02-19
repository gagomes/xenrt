date
echo $CLASSPATH
CLASSPATH=./jbb.jar:./check.jar:$CLASSPATH
echo $CLASSPATH
export CLASSPATH

../jrockit-jdk1.5.0/bin/java -fullversion

cd ../../../specjbb2005/installed
../../vconsolidate/java/jrockit-jdk1.5.0/bin/java -Xms1000m -Xmx1000m -XXaggressive -XXthroughputcompaction -XXallocprefetch -XXallocRedoPrefetch -XXcompressedRefs -XXlazyUnlocking -XXtlasize128k spec.jbb.JBBmain -propfile SPECjbb.props > /tmp/raw.log
 
date

