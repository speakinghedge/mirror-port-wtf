import os, sys
from interface_config import RX_INTERFACE, TX_INTERFACES
import argparse

parser = argparse.ArgumentParser(description='enable/disable IPv6 support for RX/TX interfaces')
mutual_exclusive_group = parser.add_mutually_exclusive_group(required=True)
mutual_exclusive_group.add_argument('-l', '--list-interfaces', default=False, action='store_true',
                                    help='list configured interfaces and exit')
mutual_exclusive_group.add_argument('-e', '--enable', action='store_true', help='enable IPv6 support')
mutual_exclusive_group.add_argument('-d', '--disable', action='store_true', help='disable IPv6 support')
args = parser.parse_args()

if args.list_interfaces:

    for interface in [RX_INTERFACE] + TX_INTERFACES:
        print interface

    sys.exit(0)

if os.getuid() != 0:
    sys.stderr.write('Please run me as root. Abort.\n')
    sys.exit(1)

if args.enable:
    oper_str = 'enable'
    oper_val = 0
else:
    oper_str = 'disable'
    oper_val = 1

for interface in [RX_INTERFACE] + TX_INTERFACES:
    print '{} IPv6-support for {}'.format(oper_str, interface)
    os.system('sysctl -w net.ipv6.conf.{}.disable_ipv6={}'.format(interface, oper_val))
