#!/usr/bin/python

guests = {}
guests["windows"] = ["vistaee","vistaeesp1","vistaeesp1-x64","vistaeesp2","vistaeesp2-x64","vistaee-x64","w2k3ee","w2k3eer2","w2k3eesp1","w2k3eesp2","w2k3eesp2-x64","w2k3ee-x64","w2k3se","w2k3ser2","w2k3sesp1","w2k3sesp1","w2k3sesp2","win8-x64","win8-x86","win7sp1-x64","win7sp1-x86","win7-x64","win7-x86","winxpsp1-x64","winxpsp2","winxpsp3","winxp-x64","ws08dcsp2-x64","ws08dcsp2-x86","ws08dc-x64","ws08dc-x86","ws08r2dcsp1-x64","ws08r2dc-x64","ws08r2sp1-x64","ws08r2-x64","ws08sp2-x64","ws08sp2-x86","ws08-x64","ws08-x86"]
guests["linux"] = ["centos43", "centos45", "centos46", "centos47", "centos48", "centos5", "centos51", "centos52", "centos53", "centos54", "centos55", "centos56", "rhel38", "rhel41", "rhel44", "rhel45", "rhel46", "rhel47", "rhel48", "rhel5", "rhel51", "rhel52", "rhel53", "rhel54", "rhel55", "rhel56", "rhel6", "rhel61", "oel53", "oel54", "oel55", "oel56", "oel6", "sles9", "sles92", "sles93", "sles94", "sles101", "sles102", "sles103", "sles104", "sles11", "sles111", "debian50", "debian60", "ubuntu1004"]
guests["other"] = ["solaris10u9"]

releases = {"George (5.5)":("George","/usr/groups/release/XenServer-5.5.0-Update2", "5.5.0-25727"),
            "Midnight Ride (5.6)":("MNR","/usr/groups/release/XenServer-5.6.0", "5.6.0-31188"),
            "Cowley (5.6FP1)":("MNR","/usr/groups/release/XenServer-5.x/XS-5.6.1-fp1/RTM-39265", "5.6.100-39265"),
            "Oxford (5.6SP2)":("MNR","/usr/groups/release/XenServer-5.x/XS-5.6.100-SP2/RTM-47101", "5.6.100-47101"),
            "Boston (6.0)":("Boston","/usr/groups/release/XenServer-6.x/XS-6.0.0/RTM-50762", "6.0.0-50762"),
            "Sanibel (6.0.2)":("Boston","/usr/groups/release/XenServer-6.x/XS-6.0.2/RTM-53456/", "6.0.2-53456"),
            "Tampa (6.1)":("Tampa","/usr/groups/release/XenServer-6.x/XS-6.1/RTM-59235/", "6.1.0-59235"),
            "Clearwater (6.2.0-69770)":("Clearwater","/usr/groups/release/XenServer-6.x/XS-6.2.0-rc3/RTM-69770/", "6.2.0-69770")
           }

branches = {"trunk": ("Dundee", "6.2.50"),
            "trunk-storage": ("Dundee", "6.2.50"),
            "trunk-64bit": ("Dundee", "6.2.50"),
            "trunk-ring0": ("Dundee", "6.2.50"),
            "trunk-ring3": ("Dundee", "6.2.50"),
            "trunk-storage": ("Dundee", "6.2.50"),
            "trunk-partner": ("Dundee", "6.2.50"),
            "clearwater": ("Clearwater", "6.1.2")
           }

srs = [ "nfs", "lvmoiscsi", "fc", "icvsmnetapp", "icvsmfc", "icvsmeql", "netapp", "eql", "icvsmsmisiscsi", "icvsmsmisfc", ]

basedir = "/usr/groups/xen/carbon"
