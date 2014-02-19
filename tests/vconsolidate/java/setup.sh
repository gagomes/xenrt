#!/bin/bash
jdk="${1}/vconsolidate/java/jrockit-jdk1.5.0"
cd ${1}/specjbb2005
patch -p1 < ${1}/vconsolidate/java/specjbb.patch
cd installed/src
mkdir -p class
${jdk}/bin/javac -classpath ${jdk}/jre/lib/rt.jar -bootclasspath class/ -d class/ `find | grep -e ".java$"`
cd class
${jdk}/bin/jar -cf jbb.jar spec/jbb/*.class spec/jbb/infra/Util/*.class spec/reporter/*.class
${jdk}/bin/jar -cf check.jar spec/jbb/validity/*.class
cp -f jbb.jar ${1}/specjbb2005/installed/
cp -f check.jar ${1}/specjbb2005/installed/

