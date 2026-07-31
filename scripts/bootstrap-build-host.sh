#!/bin/sh
set -eu

if ! command -v apt-get >/dev/null 2>&1; then
    printf 'This bootstrap script currently supports Debian-family build hosts.\n' >&2
    exit 1
fi

sudo apt-get update
sudo apt-get install -y \
    ansible-core \
    apt-utils \
    debian-archive-keyring \
    dpkg-dev \
    git \
    python3 \
    python3-jinja2 \
    python3-jsonschema \
    python3-venv \
    python3-yaml \
    whois \
    xorriso

printf '\nBuild-host dependencies installed.\n'
