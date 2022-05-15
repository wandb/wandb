#!/usr/bin/env bash

# Function to run apt-get if needed
apt_get_update_if_needed()
{
    if [ ! -d "/var/lib/apt/lists" ] || [ "$(ls /var/lib/apt/lists/ | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update
    else
        echo "Skipping apt-get update."
    fi
}

# Checks if packages are installed and installs them if not
check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update_if_needed
        apt-get -y install --no-install-recommends "$@"
    fi
}

bail_if_not_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo -e 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
        exit 1
    fi
}

bail_if_root() {
    if [ "$(id -u)" -eq 0 ]; then
        echo -e 'Script must be run as someone other than root. Add USER vscode or otherwise to your Dockerfile before running this script.'
        exit 1
    fi
}

# Ensure apt is in non-interactive to avoid prompts
export DEBIAN_FRONTEND=noninteractive

architecture="$(uname -m)"
case $architecture in
    x86_64) architecture="amd64";;
    aarch64 | armv8*) architecture="arm64";;
    aarch32 | armv7* | armvhf*) architecture="arm";;
    i?86) architecture="386";;
    *) echo "(!) Architecture $architecture unsupported"; exit 1 ;;
esac