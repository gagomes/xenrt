#!/bin/bash
cd ${1}/vconsolidate/db
mysqld_safe --user=root --basedir=/usr --socket=/tmp/mysql.sock --skip-grant-tables --default-table-type=INNODB --innodb_data_home_dir=/home/mysql/data --innodb_log_group_home_dir=/home/mysql/logs --innodb_log_buffer_size=64M --innodb_additional_mem_pool_size=32M --innodb_flush_log_at_trx_commit=0 --innodb_log_file_size=1G --innodb_thread_concurrency=1000 --max_connections=1000 --table_cache=4096 --innodb_flush_method=O_DIRECT >/dev/null 2>&1 &
sleep 300 # Give it 5 minutes
echo "create database sbtest" | mysql -S /tmp/mysql.sock
./sysbench prepare --test=oltp --mysql-table-engine=innodb --oltp-table-size=100000 --mysql-socket=/tmp/mysql.sock --mysql-user=mysql
