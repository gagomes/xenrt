../sysbench --test=oltp --max-requests=1000000 --oltp-table-size=100000 --num-threads=4 --mysql-socket=/tmp/mysql.sock run > /tmp/raw.log
