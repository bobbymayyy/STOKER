#!/bin/sh
set -eu

# Compatibility wrapper. v0.1.4 network modules share one authoritative renderer.
exec /usr/local/sbin/stoker-network-config apply
