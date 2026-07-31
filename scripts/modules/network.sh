#!/bin/sh
set -eu

# DNS, DHCP, and routing intentionally share one renderer so they cannot drift
# onto different interface roles or disagree about the downstream subnet.
/usr/local/sbin/stoker-network-config apply
