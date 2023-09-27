#!/bin/bash
set -e

./scripts/base-build.sh

rm -rf dist
mkdir dist
mkdir dist/libwandb
mkdir dist/libwandb/lib
mkdir dist/libwandb/include
mkdir dist/libwandb/share
mkdir -p dist/libwandb/share/libwandb/examples
cp export/lib/libwandb_core.* dist/libwandb/lib/
cp export/lib/libwandb_cpp.* dist/libwandb/lib/
cp export/include/libwandb_core.* dist/libwandb/include/
cp export/include/libwandb_cpp.* dist/libwandb/include/
cp cpp/examples/train_session.cpp dist/libwandb/share/libwandb/examples/logging.cpp
cp docs/README-libwandb-cpp.md dist/libwandb/
git rev-parse HEAD >dist/libwandb/build-hash

cd dist
zip -r libwandb-cpp-linux-x86_64-alpha.zip libwandb/
cd -
