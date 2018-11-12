#!/usr/bin/env python
__author__ = "joshs@nyu.edu"
import textfsm
from netmiko import ConnectHandler
import sys
from ConfigParser import SafeConfigParser
import csv

parser = SafeConfigParser()
parser.read('secret.conf')
uname = parser.get('secret', 'username')
pword = parser.get('secret', 'password')

seed_devices = sys.argv[1].split(',')
print seed_devices

interfaces = [
    [["Ethernet", "Eth"], "Eth"],
    [["FastEthernet", " FastEthernet", "Fa", "interface FastEthernet"], "Fa"],
    [["GigabitEthernet", "Gi", " GigabitEthernet", "interface GigabitEthernet", "Gig"], "Gi"],
    [["TenGigabitEthernet", "Te", "Ten"], "Te"],
    [["Port-channel", "Po"], "Po"],
    [["Serial"], "Ser"],
]

def get_cdp_neighbor_details(ip, username, password):
    ssh_connection = ConnectHandler(
        device_type='cisco_ios',
        ip=ip,
        username=username,
        password=password,
    )
    ssh_connection.enable()
    result = ssh_connection.find_prompt() + "\n"
    result += ssh_connection.send_command("show cdp neighbor detail", delay_factor=2)
    ssh_connection.disconnect()
    return result

def get_trunk_allowed_vlans(ip, username, password):
    ssh_connection = ConnectHandler(
        device_type='cisco_ios',
        ip=ip,
        username=username,
        password=password,
    )
    ssh_connection.enable()
    result = ssh_connection.find_prompt() + "\n"
    result += ssh_connection.send_command("show interfaces trunk ", delay_factor=1)
    ssh_connection.disconnect()
    return result

def get_subvalue(my_dict,my_interface):
    for key, value in my_dict.iteritems():
        for item in value:
            if item[0] == my_interface:
                return item[1]


def split_interface(interface):
    num_index = interface.index(next(x for x in interface if x.isdigit()))
    str_part = interface[:num_index]
    num_part = interface[num_index:]
    return [str_part, num_part]


def normalize_interface_names(non_norm_int):
    tmp = split_interface(non_norm_int)
    interface_type = tmp[0]
    port = tmp[1]
    for int_types in interfaces:
        for names in int_types:
            for name in names:
                if interface_type in name:
                    return_this = int_types[1] + port
                    return return_this
    return "normalize_interface_names Failed"



for current_device in seed_devices:

    print("collect CDP information from device %s..." % (current_device))

    cdp_det_result = get_cdp_neighbor_details(
        ip=current_device,
        username=uname,
        password=pword,
    )

    cdp_table = textfsm.TextFSM(open('cisco_ios_show_cdp_neighbors_detail.template'))
    cdp_results = cdp_table.ParseText(cdp_det_result)

    local_trunk_allowed_results = get_trunk_allowed_vlans(
        ip=current_device,
        username=uname,
        password=pword,
    )

    trunk_table = textfsm.TextFSM(open('cisco_ios_show_interfaces_trunk.template'))
    local_trunk_results = trunk_table.ParseText(local_trunk_allowed_results)

    local_dict = { current_device : local_trunk_results }

    for neighbor in cdp_results:
        if "GW" in neighbor[0]:
            continue

        target_ip = neighbor[1]
        target_interface = normalize_interface_names(neighbor[3])
        local_interface = normalize_interface_names(neighbor[4])

        print("Discovered and connecting to %s at ip %s" % (neighbor[0], target_ip))
        try:
            trunk_allowed_results = get_trunk_allowed_vlans(
                ip=target_ip,
                username=uname,
                password=pword,
            )
        except Exception:
            try:
                trunk_allowed_results = get_trunk_allowed_vlans(
                    ip=neighbor[0],
                    username=uname,
                    password=pword,
                )
            except Exception:
                print "Error connecting to %s at IP %s\n" % (neighbor[0], target_ip)
                continue

        trunk_table = textfsm.TextFSM(open('cisco_ios_show_interfaces_trunk.template'))
        trunk_results = trunk_table.ParseText(trunk_allowed_results)
        remote_dict = { target_ip : trunk_results }

        my_remote_result = get_subvalue(remote_dict, target_interface)
        my_local_result = get_subvalue(local_dict, local_interface)
        if my_remote_result:
            my_remote_list = my_remote_result.split(',')
        else:
            my_remote_list = []
        if my_local_result:
            my_local_list = my_local_result.split(',')
        else:
            my_local_list = []

        if my_local_result == my_remote_result:
            #print "VLANS match on both sides of host %s on port %s and host %s on port %s, congrats!" % \
            #      (current_device, local_interface, neighbor[0], target_interface)
            continue
        else:
            """
            print "Remote host %s on interface %s has vlan: %s" % (neighbor[0], target_interface, my_remote_list)
            print "Seed host %s on interface %s has vlan: %s\n" % (current_device, local_interface, my_local_list)
            """

            s1 = set(my_remote_list)
            remote_temp = [x for x in my_local_list if x not in s1]
            s2 = set(my_local_list)
            seed_temp = [x for x in my_remote_list if x not in s2]
            """
            if seed_temp:
                print "Seed device %s missing vlans %s on interface %s" % (current_device, map(str, seed_temp), local_interface)

            if remote_temp:
                print "Remote device %s missing vlans %s on interface %s\n" % (neighbor[0], map(str, remote_temp), target_interface)
            """
            with open('trunks-post.csv', 'a') as csvfile:
                fieldnames = ['SeedHost', 'SeedInterface', 'SeedVlans', 'SeedMissing', \
                              'RemoteHost', 'RemoteInterface', 'RemoteVlans', 'RemoteMissing']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                #writer.writeheader()
                writer.writerow({'SeedHost' : current_device, 'SeedInterface' : local_interface, \
                                 'SeedVlans' : my_local_result, 'SeedMissing' : map(str, seed_temp), \
                                 'RemoteHost' : neighbor[0], 'RemoteInterface' : target_interface, \
                                 'RemoteVlans' : my_remote_result, 'RemoteMissing' : map(str, remote_temp)})