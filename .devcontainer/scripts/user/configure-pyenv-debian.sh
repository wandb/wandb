#!/usr/bin/env bash

set -e
source $(dirname "$0")/build-utils-debian.sh
bail_if_root

export PYTHON_VERSION=${1:-"py39"}
export PIPX_HOME=${2:-"/usr/local/py-utils"}
export PIPX_BIN_DIR="${PIPX_HOME}/bin"

# Downgrade black so we're using the same version as tox
sudo PIPX_HOME=$PIPX_HOME PIPX_BIN_DIR=$PIPX_BIN_DIR /usr/local/py-utils/bin/pipx install --force black==19.10b0

echo "BLAMO $PYTHON_VERSION"
mamba env update --file /tmp/scripts/environment_dev.yml --file /tmp/scripts/environment.yml --name $PYTHON_VERSION

eval "$(pyenv init -)"
# Skipping virtual env for now as it's not playing nicely with conda
# eval "$(pyenv virtualenv-init -)"

echo 'eval "$(pyenv init -)"' >>~/.zshrc
# echo 'eval "$(pyenv virtualenv-init -)"' >>~/.zshrc
echo "conda activate ${PYTHON_VERSION}" >>~/.zshrc

echo 'eval "$(pyenv init -)"' >> ~/.bashrc
# echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
echo "conda activate ${PYTHON_VERSION}" >>~/.bashrc