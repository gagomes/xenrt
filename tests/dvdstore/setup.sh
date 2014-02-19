tar -xzf ds2.tar.gz
tar -xzf ds2_mysql.tar.gz
cd ds2/data_files/cust
sh ds2_create_cust_med.sh
cd ../orders
sh ds2_create_orders_med.sh
./ds2_create_inv 100000 > ../prod/inv.csv
cd ../prod
./ds2_create_prod 100000 > prod.csv
echo "GRANT ALL ON *.* TO web@localhost identified by 'web'" | mysql
cd ../../mysqlds2 && sh mysqlds2_create_all.sh

