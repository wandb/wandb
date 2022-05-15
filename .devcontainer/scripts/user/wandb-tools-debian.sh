#!/usr/bin/env bash

set -e

# TODO: wire through the USERNAME
export USERNAME=vscode

echo "set nocompatible" > /home/$USERNAME/.vimrc
mkdir -p /home/$USERNAME/.tox
mkdir -p /home/$USERNAME/.vscode-server/extensions
sudo chown -R $USERNAME /home/$USERNAME/.vscode-server