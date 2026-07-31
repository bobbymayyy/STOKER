#!/bin/sh
set -eu

install -d -m 0750 -o root -g stoker \
    /opt/stoker \
    /opt/stoker/projects \
    /opt/stoker/.versions/projects \
    /opt/stoker/.staging/projects \
    /opt/stoker/inventory \
    /opt/stoker/roles \
    /opt/stoker/collections \
    /opt/stoker/artifacts \
    /opt/stoker/backups \
    /opt/stoker/config
install -d -m 0770 -o root -g stoker /opt/stoker/logs /opt/stoker/logs/ansible
install -d -m 0750 -o root -g stoker /etc/stoker /etc/stoker/secrets
install -d -m 0755 /etc/ansible

install -d -m 0700 -o stoker -g stoker /home/stoker/.ssh
if [ ! -f /home/stoker/.ssh/id_ed25519 ]; then
    runuser -u stoker -- ssh-keygen \
        -q -t ed25519 -N '' \
        -C "stoker@$(hostname)-controller" \
        -f /home/stoker/.ssh/id_ed25519
fi
chmod 0600 /home/stoker/.ssh/id_ed25519
chmod 0644 /home/stoker/.ssh/id_ed25519.pub

cat > /etc/ansible/ansible.cfg <<'CFG'
[defaults]
inventory = /opt/stoker/inventory/production/hosts.yaml
roles_path = /opt/stoker/roles
collections_path = /opt/stoker/collections
host_key_checking = True
retry_files_enabled = False
interpreter_python = auto_silent
stdout_callback = default
bin_ansible_callbacks = True
forks = 20
timeout = 20

[ssh_connection]
pipelining = True
CFG

# Builder-created project links are preserved, but normalize ownership and
# permissions after the rootfs overlay has been applied.
chown -R root:stoker \
    /opt/stoker/projects \
    /opt/stoker/.versions \
    /opt/stoker/.staging \
    /opt/stoker/inventory \
    /opt/stoker/roles \
    /opt/stoker/collections \
    /opt/stoker/artifacts \
    /opt/stoker/logs \
    /etc/stoker
find /opt/stoker/projects /opt/stoker/.versions /opt/stoker/inventory \
    -type d -exec chmod 0750 {} +
find /opt/stoker/projects /opt/stoker/.versions /opt/stoker/inventory \
    -type f -exec chmod 0640 {} +
find /opt/stoker/projects /opt/stoker/.versions -type f \
    \( -name '*.sh' -o -path '*/bin/*' \) -exec chmod 0750 {} +
chmod 0640 /etc/stoker/ansible-projects.yaml 2>/dev/null || true
