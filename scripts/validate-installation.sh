#!/bin/sh
set -eu

fail=0
check() {
    description=$1
    shift
    if "$@" >/dev/null 2>&1; then
        printf '[ OK ] %s\n' "$description"
    else
        printf '[FAIL] %s\n' "$description"
        fail=1
    fi
}

check 'stoker account exists' id stoker
check 'root account is locked' sh -c "passwd -S root | grep -q ' L '"
check 'STOKER package manifest exists' test -f /etc/stoker/install-packages.txt
check 'STOKER build manifest exists' test -f /etc/stoker/build.json
check 'STOKER module configuration exists' test -f /etc/stoker/modules.yaml
check 'Ansible project catalog exists' test -f /etc/stoker/ansible-projects.yaml
check 'Ansible configuration exists' test -f /etc/ansible/ansible.cfg
check 'controller SSH key exists' test -f /home/stoker/.ssh/id_ed25519.pub
check 'Ansible controller command exists' command -v ansible-playbook
check 'Docker CLI exists' command -v docker
check 'Docker service is enabled' systemctl is-enabled docker.service
check 'STOKER controller CLI exists' command -v stoker
check 'production inventory exists' test -f /opt/stoker/inventory/production/hosts.yaml
check 'discovered inventory exists' test -f /opt/stoker/inventory/discovered/hosts.yaml
check 'bootstrap project is active' test -f /opt/stoker/projects/stoker-bootstrap/playbooks/deploy.yml
check 'node baseline project is active' test -f /opt/stoker/projects/node-baseline/playbooks/deploy.yml
check 'project catalog is readable' stoker project list
check 'SSH service is enabled' systemctl is-enabled ssh.service

check 'network role renderer exists' command -v stoker-network-config
check 'NAT control command exists' command -v stoker-nat
check 'network roles are resolved' test -s /etc/stoker/network-roles.env
check 'downstream interface configuration exists' test -s /etc/network/interfaces.d/90-stoker-downstream
check 'network render status is readable' stoker-network-config status
check 'network render service is enabled' systemctl is-enabled stoker-network-config.service
check 'IPv4 forwarding configuration exists' grep -q '^net.ipv4.ip_forward=1$' /etc/sysctl.d/90-stoker-routing.conf
check 'nftables configuration is valid' nft -c -f /etc/nftables.conf
check 'nftables service is enabled' systemctl is-enabled nftables.service

check 'Kea configuration is valid' kea-dhcp4 -t /etc/kea/kea-dhcp4.conf
check 'Kea service is enabled' systemctl is-enabled kea-dhcp4-server.service
check 'BIND configuration is valid' named-checkconf
check 'BIND service is enabled' sh -c 'systemctl is-enabled named.service >/dev/null 2>&1 || systemctl is-enabled bind9.service >/dev/null 2>&1'

exit "$fail"
