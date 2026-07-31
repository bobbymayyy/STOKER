#!/bin/sh
set -eu

systemctl enable docker.service containerd.service
if getent group docker >/dev/null 2>&1; then
    usermod --append --groups docker stoker
fi
install -d -m 0750 -o root -g docker /opt/stoker/compose /opt/stoker/images
