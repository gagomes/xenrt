#!/bin/bash
set -u

function log() {
    echo "INFO: $@" >&2
}

COVERAGE_TARGET_DIR="/coverage_results"
PACKAGES_TO_COVER="org.apache.cloudstack.*:com.cloud.*"
TOMCAT_CONFIG="/etc/cloudstack/management/tomcat6.conf"
COVERAGE_REPORT_COOKIE="COVERAGE_REPORT_COOKIE"

. "$TOMCAT_CONFIG"

(
    mkdir -p /jacoco-dl
    cd /jacoco-dl
    wget -q -nc http://files.uk.xensource.com/usr/groups/xenrt/cloud/org.jacoco.agent-0.7.1.201405082137.jar
)
JACOCO_INSTALL=$(find /jacoco-dl -name "*.jar")
JACOCO_INSTALL=$(readlink -f "$JACOCO_INSTALL")

log "JACOCO DOWNLOADED TO $JACOCO_INSTALL"

INSTALLED_JACOCOAGENT=$(find /installed-jacoco -name "jacocoagent.jar")

if [ -z "$INSTALLED_JACOCOAGENT" ]; then
(
    mkdir -p /installed-jacoco
    cd /installed-jacoco/
    unzip "$JACOCO_INSTALL"
)
fi

INSTALLED_JACOCOAGENT=$(find /installed-jacoco -name "jacocoagent.jar")
log "JACOCO AGENT AT $INSTALLED_JACOCOAGENT"

if ! grep -q "$COVERAGE_REPORT_COOKIE" "$TOMCAT_CONFIG"; then
	cat >> "$TOMCAT_CONFIG" << EOF
# $COVERAGE_REPORT_COOKIE
JAVA_OPTS="\${JAVA_OPTS} -javaagent:$INSTALLED_JACOCOAGENT=destfile=$COVERAGE_TARGET_DIR/mgmt_srv.exec,includes=$PACKAGES_TO_COVER"
EOF
	log "$TOMCAT_CONFIG PATCHED"
else
	log "$TOMCAT_CONFIG ALREADY PATCHED"
fi


log "Clearing result directory: $COVERAGE_TARGET_DIR"
rm -rf "$COVERAGE_TARGET_DIR"
mkdir -p "$COVERAGE_TARGET_DIR"
chown $TOMCAT_USER:$TOMCAT_USER "$COVERAGE_TARGET_DIR"

cat << EOF
Now start your management server, the coverage metrics will be collected to:

$COVERAGE_TARGET_DIR/mgmt_srv.exec
EOF
