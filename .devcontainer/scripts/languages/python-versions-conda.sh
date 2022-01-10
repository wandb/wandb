#!/usr/bin/env bash

set -e
source $(dirname "$0")/build-utils-debian.sh
bail_if_root

USERNAME=${1:-"vscode"}

sudo chown -R $USERNAME /tmp/scripts

curl https://pyenv.run | bash
conda init bash
conda init zsh
conda config --add channels conda-forge
conda install -y mamba
mamba env create --name py36 --file /tmp/scripts/environment.yml python=3.6
mamba env create --name py37 --file /tmp/scripts/environment.yml python=3.7
mamba env create --name py38 --file /tmp/scripts/environment.yml python=3.8
mamba env create --name py39 --file /tmp/scripts/environment.yml python=3.9
mamba env create --name py310 --file /tmp/scripts/environment.yml python=3.10