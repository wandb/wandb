#!/bin/bash
set -e

BASEDIR=`pwd`
cd ../..

# NOTE: this is not final... just for testing

# prep location
rm -rf export/
mkdir export
mkdir export/lib
mkdir export/include
mkdir export/examples

# build core binary
rm -rf tmpbuild
mkdir tmpbuild
# build binary
cd ../../../core/
SYSTEM=`uname -s`
if [ "x$SYSTEM" == "xLinux" ]; then
CGO_ENABLED=1 go build \
  -ldflags "-extldflags \"-fuse-ld=gold -Wl,--weak-unresolved-symbols\"" \
  -o ../experimental/client-go/bindings/tmpbuild/embed-core.bin cmd/wandb-core/main.go
else
go build \
  -o ../experimental/client-go/bindings/tmpbuild/tmpbuild/embed-core.bin cmd/wandb-core/main.go
fi
cd -

# build shared-library
cp core/*.go tmpbuild/
cd tmpbuild/
go build -tags=libwandb_core -buildmode c-shared -o ../export/libwandb_core.so *.go
go build -tags=libwandb_core -buildmode c-archive -o ../export/libwandb_core.a *.go
mv ../export/libwandb_core.so ../export/libwandb_core.a ../export/lib/
mv ../export/libwandb_core.h ../export/include/
cd -
rm -rf tmpbuild/

mkdir -p $BASEDIR/wandb/lib
cp export/lib/libwandb_core.so $BASEDIR/wandb/lib
