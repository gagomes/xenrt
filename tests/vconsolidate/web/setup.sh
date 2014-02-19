#!/bin/bash
cd ${1}/vconsolidate/web
chkconfig --level 2345 httpd on
service httpd start
cp simcgi.exe /var/www/cgi-bin/
tar xzf wbtree.tgz -C /var/www/html
