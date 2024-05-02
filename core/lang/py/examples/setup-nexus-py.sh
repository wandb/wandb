#!/bin/bash
set -e
rm -rf nexus-py-1
virtualenv nexus-py-1
source nexus-py-1/bin/activate
pip install --upgrade pip
pip install --upgrade numpy
cd ../lib
./build_proto.sh
../../../scripts/generate-proto.sh
./build_lib.sh
pip install -e .
echo "Run:"
echo "source nexus-py-1/bin/activate"
