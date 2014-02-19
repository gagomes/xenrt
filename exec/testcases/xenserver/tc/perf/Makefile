.PHONY : all
all: tc_vlan_scalability.py tc_cpuload.py

VLAN=vlan_scalability
DEPS_VLAN=$(VLAN)/tc_vlan_scalability.py $(VLAN)/at $(VLAN)/create_vlans $(VLAN)/destroy_vlans $(VLAN)/poller_xapi_restart
tc_vlan_scalability.py: mesh $(DEPS_VLAN)
	./mesh $(DEPS_VLAN) > $@

CPU=cpuload
DEPS_CPU=$(CPU)/tc_cpuload.py $(CPU)/signaller $(CPU)/atop.rpm
tc_cpuload.py: mesh $(DEPS_CPU)
	./mesh $(DEPS_CPU) > $@

$(CPU)/atop.rpm: $(CPU)/atop-1.26-1.i586.rpm
	ln -sf $(^F) $@

.PHONY : clean
clean:
	rm -f tc_vlan_scalability.py tc_ssh_test.py tc_cpuload.py $(CPU)/atop.rpm
