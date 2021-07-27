#!/bin/bash

set -e
PYTHON_VERSIONS="3.5 3.6 3.7 3.8 3.9"

echo "Configuring test environment..."
full_all=""
for v in $PYTHON_VERSIONS; do
  full=`pyenv install --list | egrep "^\s*[[:digit:]][[:digit:].]+$" | grep $v | sort --version-sort | tail -1`
  echo "Installing: $full..."
  pyenv install -s $full
  full_all="$full $full_all"
done
echo "Setting local pyenv versions to: $full_all"
pyenv local $full_all
echo "Installing dependencies: tox..."
pip install -qq tox==3.23.1
echo "Configuring submodules..."
make submodule-update
echo "Development environment setup!"
echo ""
echo "Run all unittests with:"
echo "  tox"
